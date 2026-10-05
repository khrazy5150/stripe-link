"""Buying a label: one order at a time, idempotent, claimed before the money is spent.

plans/ORDER_FULFILMENT.md F4. Bulk is the CLIENT driving this endpoint, because twenty purchases cannot
happen inside one API Gateway request and a timeout mid-batch would leave the tenant not knowing which
labels were bought -- the worst possible failure for an action that spends money.
"""
import json
import unittest

from handlers.shipping import handler as shipping_handler
from stripe_link.domain.shipping_providers import ProviderError, provider_for

ORDER = {
    "order_id": "order_1", "tenant_id": "t1", "stripe_mode": "test", "payment_status": "paid",
    "customer": {"name": "Ada", "email": "ada@example.com"},
    "shipping_address": {"name": "Ada", "street1": "1 Main", "city": "Denver", "state": "CO",
                         "postal_code": "80204", "country": "US"},
    "line_items": [{"name": "Gummies", "quantity": 1, "stripe_product_id": "prod_A"}],
}
CONFIG = {
    "tenant_id": "t1", "enabled": True,
    "provider": {"name": "mock", "api_key_ref": "", "connection_status": "connected"},
    # The email is not decoration: a carrier refuses a label without one on the sender, so a ship-from
    # that could really buy a label carries it (2026-10-05).
    "ship_from_address": {"name": "Shop", "street1": "9 Elm", "city": "Denver", "state": "CO",
                          "postal_code": "80204", "country": "US", "email": "shop@example.com"},
    "boxes": [{"name": "Small", "length": 8, "width": 6, "height": 4, "empty_weight": 0.2}],
}
PARCEL = {"length": 8, "width": 6, "height": 4, "distance_unit": "in", "weight": 1.2, "mass_unit": "lb"}


class Repo:
    def __init__(self, rows=None, key="order_id"):
        self.rows = list(rows or [])
        self.key = key

    def get(self, tenant_id, doc_id=None):
        if doc_id is None:  # shipping-config style: get(tenant_id)
            return self.rows[0] if self.rows else None
        return next((r for r in self.rows if r.get(self.key) == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        self.rows = [r for r in self.rows if r.get(self.key) != document.get(self.key)] + [document]
        return document


class Cipher:
    @staticmethod
    def decrypt(ref, **kwargs):
        return ""


def _buy(body=None, shipments=None, orders=None, config=None, mailer=None):
    sent = []
    shipments = shipments if shipments is not None else Repo(key="shipment_id")
    result = shipping_handler(
        {"httpMethod": "POST", "resource": "/shipping/labels",
         "queryStringParameters": {"tenant_id": "t1"},
         "body": json.dumps(body if body is not None else
                            {"order_id": "order_1", "rate_id": "mock_rate_usps",
                             "parcel": PARCEL, "amount": 750, "currency": "usd"})},
        None,
        repository=Repo([config if config is not None else CONFIG], key="tenant_id"),
        secret_cipher=Cipher(),
        products_repo=Repo(),
        orders_repo=Repo(orders if orders is not None else [ORDER]),
        shipments_repo=shipments,
        user_profiles_repo=Repo(),
        mailer_send=mailer or (lambda **kw: sent.append(kw)),
    )
    return result, shipments, sent


class PurchaseTests(unittest.TestCase):
    def test_buying_records_what_the_provider_actually_sold(self):
        result, shipments, sent = _buy()
        self.assertEqual(result["statusCode"], 201)
        shipment = json.loads(result["body"])["shipment"]
        self.assertEqual(shipment["status"], "purchased")
        self.assertTrue(shipment["tracking_number"])
        self.assertTrue(shipment["label_url"])
        self.assertEqual(shipment["cost"], {"amount": 750, "currency": "usd"})

    def test_the_buyer_is_told(self):
        _, _, sent = _buy()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], "ada@example.com")

    def test_buying_TWICE_does_not_buy_two_labels(self):
        """A label is money that cannot be un-spent by refreshing the page. The shipment id is derived
        from the order, so the second click finds the first label."""
        first, shipments, _ = _buy()
        second, _, sent2 = _buy(shipments=shipments)

        self.assertEqual(json.loads(second["body"]).get("already_bought"), True)
        self.assertEqual(json.loads(first["body"])["shipment"]["shipment_id"],
                         json.loads(second["body"])["shipment"]["shipment_id"])
        self.assertEqual(len([r for r in shipments.rows if r.get("status") == "purchased"]), 1)

    def test_the_shipment_is_claimed_BEFORE_the_provider_is_called(self):
        """A crash between claiming and buying must leave a row saying "we were buying this", not a
        silently bought label nobody recorded."""
        seen = {}

        class Watcher(Repo):
            def put(self, document):
                seen.setdefault("first_status", document.get("status"))
                return super().put(document)

        _buy(shipments=Watcher(key="shipment_id"))
        self.assertEqual(seen["first_status"], "purchasing")

    def test_a_provider_failure_is_RECORDED_not_lost(self):
        """The claim row is the evidence the attempt was made, and it carries the idempotency key needed
        to find out whether the carrier sold us a label we never saw."""
        import handlers.shipping as module

        def explode(*args, **kwargs):
            raise ProviderError("Carrier refused the parcel")

        original = module.provider_for
        module.provider_for = explode
        try:
            result, shipments, _ = _buy()
        finally:
            module.provider_for = original

        self.assertEqual(result["statusCode"], 502)
        self.assertIn("Carrier refused", json.loads(result["body"])["message"])
        self.assertEqual(shipments.rows[-1]["status"], "failed")

    def test_an_unknown_provider_never_reaches_the_carrier(self):
        # label_readiness stops it first, which is the cheaper failure: nothing was claimed.
        broken = {**CONFIG, "provider": {"name": "nope", "api_key_ref": ""}}
        result, shipments, _ = _buy(config=broken)
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(shipments.rows, [])

    def test_a_dead_mailer_does_NOT_fail_a_bought_label(self):
        """P3's rule, and it is right here: the label is already bought and paid for, so a bounced address
        must not turn a successful purchase into an error the tenant thinks they should retry."""
        def explode(**kwargs):
            raise RuntimeError("SES is down")

        result, _, _ = _buy(mailer=explode)

        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertEqual(body["shipment"]["status"], "purchased")
        self.assertFalse(body["notification"]["sent"])

    def test_a_rate_id_is_required(self):
        result, _, _ = _buy({"order_id": "order_1", "parcel": PARCEL})
        self.assertEqual(result["statusCode"], 400)

    def test_a_parcel_is_required_so_a_stale_screen_cannot_guess_one(self):
        result, _, _ = _buy({"order_id": "order_1", "rate_id": "mock_rate_usps"})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "missing_parcel")

    def test_an_unready_config_refuses_before_spending_anything(self):
        unready = {**CONFIG, "ship_from_address": {}}
        result, shipments, _ = _buy(config=unready)
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(shipments.rows, [])

    def test_an_unknown_order_is_a_404(self):
        result, _, _ = _buy(orders=[])
        self.assertEqual(result["statusCode"], 404)


class ProviderContractTests(unittest.TestCase):
    def test_the_mock_buys_nothing_but_completes_the_flow(self):
        """So F4 can be proved end to end before a tenant spends real postage."""
        purchase = provider_for("mock", "").buy_label(rate_id="mock_rate_usps", idempotency_key="shp_1")
        for field in ("provider_transaction_id", "label_url", "tracking_number", "tracking_url"):
            self.assertTrue(purchase[field], f"{field} missing from a purchase")

    def test_an_unknown_provider_fails_loudly_rather_than_mocking(self):
        with self.assertRaises(ProviderError):
            provider_for("not_a_provider", "x")


class ShippoPurchaseTests(unittest.TestCase):
    """The Shippo call itself, without touching the network."""

    def _provider(self, response, captured=None):
        import io
        from contextlib import contextmanager

        @contextmanager
        def opener(request, timeout=None):
            if captured is not None:
                captured["headers"] = dict(request.headers)
                captured["body"] = json.loads(request.data.decode())
            yield io.BytesIO(json.dumps(response).encode())

        return provider_for("shippo", "shippo_test_key", opener=opener)

    def test_a_successful_transaction_is_normalised(self):
        provider = self._provider({
            "status": "SUCCESS", "object_id": "txn_1", "label_url": "https://s/l.pdf",
            "tracking_number": "9400", "tracking_url_provider": "https://usps/9400",
            "label_file_type": "PDF"})
        purchase = provider.buy_label(rate_id="rate_1", idempotency_key="shp_1")
        self.assertEqual(purchase["provider_transaction_id"], "txn_1")
        self.assertEqual(purchase["tracking_url"], "https://usps/9400")

    def test_the_purchase_is_synchronous_and_carries_the_idempotency_key(self):
        """async defaults to true and returns a transaction with no label on it, which reads as a silent
        failure. The key is derived from the order, so a retry asks the CARRIER for the same label."""
        captured = {}
        provider = self._provider({"status": "SUCCESS", "object_id": "t"}, captured)
        provider.buy_label(rate_id="rate_1", idempotency_key="shp_order_1_outbound_1")
        self.assertIs(captured["body"]["async"], False)
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(headers["shippo-idempotency-key"], "shp_order_1_outbound_1")

    def test_a_non_success_status_raises_with_the_providers_own_reason(self):
        provider = self._provider({"status": "ERROR", "messages": [{"text": "Address is invalid"}]})
        with self.assertRaises(ProviderError) as caught:
            provider.buy_label(rate_id="rate_1")
        self.assertIn("Address is invalid", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
