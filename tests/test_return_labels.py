"""Return labels: the reverse leg, and the window the buyer has to use one.

plans/ORDER_FULFILMENT.md R2/R3. Built on the same primitive as an outbound label, with two differences
that are both about money: it is bought against a refund request already waiting for goods, and it
EXPIRES -- the buyer has about three days to post it or forfeits the free return postage (author, R2).
"""
import json
import unittest

from handlers.shipping import handler as shipping_handler
from stripe_link.domain.returns import (
    RETURN_IN_TRANSIT,
    RETURN_PENDING,
    advance_to_in_transit,
    return_deadline,
    return_label_expired,
)

ORDER = {"order_id": "order_1", "tenant_id": "t1", "stripe_mode": "test",
         "customer": {"name": "Ada", "email": "ada@example.com"},
         "shipping_address": {"name": "Ada", "street1": "1 Main", "city": "Denver", "state": "CO",
                              "postal_code": "80204", "country": "US"}}
CONFIG = {"tenant_id": "t1", "enabled": True,
          "provider": {"name": "mock", "api_key_ref": "", "connection_status": "connected"},
          "ship_from_address": {"name": "Shop", "street1": "9 Elm", "city": "Denver", "state": "CO",
                                "postal_code": "80204", "country": "US"},
          "boxes": [{"name": "Small", "length": 8, "width": 6, "height": 4, "empty_weight": 0.2}]}
REQUEST = {"refund_request_id": "rr_1", "tenant_id": "t1", "order_id": "order_1",
           "status": RETURN_PENDING, "policy_snapshot": {"return_required": True, "return_window_days": 3}}
PARCEL = {"length": 8, "width": 6, "height": 4, "distance_unit": "in", "weight": 1.2, "mass_unit": "lb"}


class Repo:
    def __init__(self, rows=None, key="order_id"):
        self.rows = list(rows or [])
        self.key = key

    def get(self, tenant_id, doc_id=None):
        if doc_id is None:
            return self.rows[0] if self.rows else None
        return next((r for r in self.rows if r.get(self.key) == doc_id), None)

    def put(self, document):
        self.rows = [r for r in self.rows if r.get(self.key) != document.get(self.key)] + [document]
        return document


class Cipher:
    @staticmethod
    def decrypt(ref, **kwargs):
        return ""


def _buy(request=None, body=None, shipments=None, now=1000):
    shipments = shipments if shipments is not None else Repo(key="shipment_id")
    requests_repo = Repo([request or dict(REQUEST)], key="refund_request_id")
    result = shipping_handler(
        {"httpMethod": "POST", "resource": "/shipping/return-labels",
         "queryStringParameters": {"tenant_id": "t1"},
         "body": json.dumps(body or {"refund_request_id": "rr_1", "rate_id": "mock_rate_usps",
                                     "parcel": PARCEL, "amount": 650})},
        None,
        repository=Repo([CONFIG], key="tenant_id"), secret_cipher=Cipher(),
        orders_repo=Repo([ORDER]), shipments_repo=shipments, refund_requests_repo=requests_repo,
        now_fn=lambda: now)
    return result, shipments, requests_repo


class ReturnLabelTests(unittest.TestCase):
    def test_it_ships_from_the_BUYER_back_to_the_tenant(self):
        result, _, _ = _buy()
        self.assertEqual(result["statusCode"], 201)
        shipment = json.loads(result["body"])["shipment"]
        self.assertEqual(shipment["kind"], "return")
        self.assertEqual(shipment["from_address"]["city"], "Denver")
        self.assertEqual(shipment["status"], "purchased")

    def test_it_is_a_SEPARATE_shipment_from_the_outbound_one(self):
        """Same order, different leg: shipment_id_for(order, "return") keeps them apart, so buying a
        return label cannot collide with the label that sent the parcel out."""
        result, _, _ = _buy()
        self.assertIn("_return_", json.loads(result["body"])["shipment"]["shipment_id"])

    def test_the_refund_request_remembers_its_label_and_its_deadline(self):
        result, _, requests_repo = _buy()
        saved = requests_repo.rows[0]
        self.assertTrue(saved["return_shipment_id"])
        self.assertEqual(saved["return_label_expires_at"], json.loads(result["body"])["expires_at"])

    def test_the_window_is_three_days_by_default(self):
        result, _, _ = _buy()
        expires = json.loads(result["body"])["expires_at"]
        self.assertEqual(expires - 1000, 3 * 86400)

    def test_buying_twice_does_not_buy_two_return_labels(self):
        _, shipments, _ = _buy()
        second, shipments, _ = _buy(shipments=shipments)
        self.assertTrue(json.loads(second["body"])["already_bought"])

    def test_a_refund_that_owes_no_return_gets_no_free_label(self):
        """Issuing one for a refund nobody approved gives away postage for a parcel never asked for."""
        result, _, _ = _buy(request={**REQUEST, "status": "new"})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "not_returning")

    def test_after_the_window_lapses_the_free_postage_is_FORFEIT(self):
        lapsed = {**REQUEST, "return_label_expires_at": 500}
        result, _, _ = _buy(request=lapsed)
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "return_window_passed")

    def test_a_missing_rate_or_parcel_is_refused(self):
        result, _, _ = _buy(body={"refund_request_id": "rr_1"})
        self.assertEqual(result["statusCode"], 400)


class ExpiryTests(unittest.TestCase):
    def test_a_deadline_is_computed_from_the_snapshot_not_from_todays_policy(self):
        request = {"return_started_at": 0, "policy_snapshot": {"return_window_days": 7}}
        self.assertEqual(return_deadline(request, now=0), 7 * 86400)

    def test_the_default_window_is_three_days(self):
        self.assertEqual(return_deadline({"return_started_at": 0}, now=0), 3 * 86400)

    def test_expiry_is_false_when_no_label_was_ever_issued(self):
        self.assertFalse(return_label_expired({}, now=10**9))

    def test_expiry_is_a_moment_not_a_mood(self):
        request = {"return_label_expires_at": 1000}
        self.assertFalse(return_label_expired(request, now=1000))
        self.assertTrue(return_label_expired(request, now=1001))


class InTransitTests(unittest.TestCase):
    """A scan says the parcel is MOVING. It does not say it arrived, or that the right item is in it --
    which is why `return_received` stays the tenant's decision."""

    def test_a_scan_advances_a_pending_return(self):
        updated = advance_to_in_transit({"status": RETURN_PENDING}, now=50)
        self.assertEqual(updated["status"], RETURN_IN_TRANSIT)
        self.assertEqual(updated["return_in_transit_at"], 50)

    def test_a_scan_never_marks_it_RECEIVED(self):
        updated = advance_to_in_transit({"status": RETURN_PENDING}, now=50)
        self.assertNotEqual(updated["status"], "return_received")

    def test_it_does_not_drag_a_received_return_backwards(self):
        received = {"status": "return_received"}
        self.assertEqual(advance_to_in_transit(received, now=50)["status"], "return_received")

    def test_it_does_not_mutate_the_input(self):
        original = {"status": RETURN_PENDING}
        advance_to_in_transit(original, now=50)
        self.assertEqual(original["status"], RETURN_PENDING)


if __name__ == "__main__":
    unittest.main()
