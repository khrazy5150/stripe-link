import json
import unittest

from handlers.product_sync import check_product_drift, handler, run_product_sync
from stripe_link.domain.stripe_products import build_price_params, build_product_params
from stripe_link.stripe_client import StripeApiError
from tests.fakes import FakeDocumentRepository


def product_doc(**overrides):
    doc = {
        "schema_version": "2026-05-29",
        "document_type": "product",
        "tenant_id": "tenant_demo",
        "product_id": "prod_1",
        "stripe_product_id": None,
        "stripe_mode": "test",
        "status": "active",
        "name": "Creatine Gummies",
        "description": "Tasty",
        "default_price_id": "price_a",
        "prices": [
            {"price_id": "price_a", "stripe_price_id": None, "currency": "usd", "unit_amount": 3900, "badge": "Popular"},
            {"price_id": "price_b", "stripe_price_id": None, "currency": "usd", "unit_amount": 6700},
        ],
        "sync": {"status": "pending", "last_synced_at": None, "error": None},
    }
    doc.update(overrides)
    return doc


class FakeStripe:
    """Records calls; returns deterministic ids. existing_prices/stripe_product drive the
    GET responses used by orphan-archival and drift checks."""
    def __init__(self, fail_on=None, existing_prices=None, stripe_product=None):
        self.calls = []
        self.fail_on = fail_on
        self.existing_prices = existing_prices or []
        self.stripe_product = stripe_product
        self._n = 0

    def __call__(self, method, path, *, api_key, stripe_account="", data=None, params=None, **kwargs):
        self.calls.append({"method": method, "path": path, "stripe_account": stripe_account, "data": data, "params": params})
        if self.fail_on and self.fail_on in path:
            raise StripeApiError(402, "Your card was declined.", "card_declined")
        if method == "GET" and path == "/prices":
            return {"data": self.existing_prices}
        if method == "GET" and path.startswith("/products/"):
            return self.stripe_product or {"id": "prod_stripe_1", "name": "Creatine Gummies", "active": True}
        if path == "/products" or path.startswith("/products/"):
            return {"id": "prod_stripe_1"}
        if path == "/prices":
            self._n += 1
            return {"id": f"price_stripe_{self._n}"}
        return {}


class ParamBuilderTests(unittest.TestCase):
    def test_product_params(self):
        params = build_product_params(product_doc(status="archived", images=["https://x/a.png"], stripe_metadata={"sku": "AB1"}))
        self.assertEqual(params["name"], "Creatine Gummies")
        self.assertFalse(params["active"])  # archived -> inactive
        self.assertEqual(params["images"], ["https://x/a.png"])
        self.assertEqual(params["metadata"]["product_id"], "prod_1")
        self.assertEqual(params["metadata"]["sku"], "AB1")

    def test_price_params_recurring(self):
        params = build_price_params(
            {"price_id": "p", "currency": "USD", "unit_amount": 1000, "recurring": {"interval": "month", "interval_count": 3}},
            "prod_stripe_1",
        )
        self.assertEqual(params["product"], "prod_stripe_1")
        self.assertEqual(params["unit_amount"], 1000)
        self.assertEqual(params["currency"], "usd")
        self.assertEqual(params["recurring"], {"interval": "month", "interval_count": 3})


class RunSyncTests(unittest.TestCase):
    def test_creates_product_and_prices_and_sets_default(self):
        stripe = FakeStripe()
        synced, result = run_product_sync(product_doc(), api_key="sk", stripe_account="acct_1", caller=stripe, now=1781230000)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices_created"], 2)
        self.assertEqual(synced["stripe_product_id"], "prod_stripe_1")
        self.assertEqual(synced["prices"][0]["stripe_price_id"], "price_stripe_1")
        self.assertEqual(synced["sync"]["status"], "success")
        self.assertEqual(synced["sync"]["last_synced_at"], 1781230000)
        # product create used no id; connect account forwarded
        self.assertEqual(stripe.calls[0]["path"], "/products")
        self.assertEqual(stripe.calls[0]["stripe_account"], "acct_1")
        # default_price set on the product for price_a's Stripe price
        default_calls = [c for c in stripe.calls if c["path"] == "/products/prod_stripe_1" and c["data"].get("default_price")]
        self.assertEqual(default_calls[0]["data"]["default_price"], "price_stripe_1")

    def test_updates_existing_product_and_skips_synced_prices(self):
        doc = product_doc(stripe_product_id="prod_stripe_existing")
        doc["prices"][0]["stripe_price_id"] = "price_stripe_existing"
        stripe = FakeStripe()
        synced, result = run_product_sync(doc, api_key="sk", stripe_account="", caller=stripe, now=1)
        self.assertEqual(result["prices_created"], 1)  # only price_b created
        self.assertEqual(stripe.calls[0]["path"], "/products/prod_stripe_existing")

    def test_stripe_error_records_failed_status(self):
        stripe = FakeStripe(fail_on="/products")
        synced, result = run_product_sync(product_doc(), api_key="sk", stripe_account="", caller=stripe, now=5)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(synced["sync"]["status"], "failed")
        self.assertIn("declined", synced["sync"]["error"])

    def test_archives_orphan_stripe_prices(self):
        doc = product_doc(stripe_product_id="prod_stripe_1")
        doc["prices"][0]["stripe_price_id"] = "price_keep"
        doc["prices"][1]["stripe_price_id"] = "price_keep_b"
        # Stripe has an extra active price with no local counterpart -> should be archived.
        stripe = FakeStripe(existing_prices=[
            {"id": "price_keep", "active": True},
            {"id": "price_orphan", "active": True},
        ])
        _, result = run_product_sync(doc, api_key="sk", stripe_account="", caller=stripe, now=1)
        self.assertEqual(result["prices_archived"], 1)
        archive_calls = [c for c in stripe.calls if c["path"] == "/prices/price_orphan" and c["data"] == {"active": False}]
        self.assertEqual(len(archive_calls), 1)


class DriftCheckTests(unittest.TestCase):
    def test_reports_name_and_price_drift(self):
        doc = product_doc(stripe_product_id="prod_stripe_1")
        doc["prices"][0]["stripe_price_id"] = "price_a"
        doc["prices"][1]["stripe_price_id"] = "price_b"
        stripe = FakeStripe(
            stripe_product={"id": "prod_stripe_1", "name": "Different Name", "active": True},
            existing_prices=[{"id": "price_a", "unit_amount": 9999}, {"id": "price_b", "unit_amount": 6700}],
        )
        drift = check_product_drift(doc, api_key="sk", stripe_account="", caller=stripe)
        self.assertFalse(drift["in_sync"])
        fields = {d["field"] for d in drift["differences"]}
        self.assertIn("name", fields)
        self.assertIn("price_amount", fields)  # price_a amount differs (3900 vs 9999)

    def test_in_sync_when_matching(self):
        doc = product_doc(stripe_product_id="prod_stripe_1")
        doc["prices"][0]["stripe_price_id"] = "price_a"
        doc["prices"][1]["stripe_price_id"] = "price_b"
        stripe = FakeStripe(
            stripe_product={"id": "prod_stripe_1", "name": "Creatine Gummies", "active": True},
            existing_prices=[{"id": "price_a", "unit_amount": 3900}, {"id": "price_b", "unit_amount": 6700}],
        )
        drift = check_product_drift(doc, api_key="sk", stripe_account="", caller=stripe)
        self.assertTrue(drift["in_sync"])


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.products = FakeDocumentRepository("product_id")
        self.keys = FakeStripeKeys()
        self.products.put(product_doc())

    def sync(self, product_id="prod_1"):
        return handler(
            {"httpMethod": "POST", "queryStringParameters": {"tenant_id": "tenant_demo"},
             "pathParameters": {"product_id": product_id}},
            None,
            repository=self.products,
            stripe_repo=self.keys,
            secret_cipher=None,
            caller=FakeStripe(),
            credentials_fn=fake_credentials,
            now_fn=lambda: 1781230000,
        )

    def test_sync_persists_stripe_ids(self):
        response = self.sync()
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["sync"]["status"], "success")
        stored = self.products.get("tenant_demo", "prod_1")
        self.assertEqual(stored["stripe_product_id"], "prod_stripe_1")
        self.assertEqual(stored["sync"]["status"], "success")

    def test_missing_product_404(self):
        self.assertEqual(self.sync(product_id="nope")["statusCode"], 404)

    def test_no_stripe_key_configured(self):
        self.keys.doc = {}  # connect_account_id / secret_key_ref absent
        response = self.sync()
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "stripe_not_configured")


class FakeStripeKeys:
    def __init__(self):
        self.doc = {"connect_account_id": "acct_1", "secret_key_ref": ""}

    def get(self, tenant_id, mode="test"):
        return dict(self.doc)


def fake_credentials(tenant_id, mode, stripe_keys, secret_cipher):
    if stripe_keys.get("connect_account_id"):
        return "sk_test_platform", stripe_keys["connect_account_id"]
    if stripe_keys.get("secret_key_ref"):
        return "sk_test_tenant", ""
    return "", ""


if __name__ == "__main__":
    unittest.main()
