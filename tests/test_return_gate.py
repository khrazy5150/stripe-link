"""No Stripe refund until the goods are back.

plans/ORDER_FULFILMENT.md R1, the author's rule. The leg between `approved` and `refunded` is the whole
change: `approved` goes back to meaning "the claim is valid" rather than "the money is going back now".

Most of the vocabulary already existed -- Product.refund_policy.return_method has carried `return_required`
and `no_return_customer_keeps` since the schema was written -- so this reads what is modelled rather than
inventing a second way to say it.
"""
import json
import unittest

from handlers.refunds import handler as refunds_handler
from stripe_link.domain.returns import (
    RETURN_PENDING,
    RETURN_RECEIVED,
    can_release_refund,
    next_status_after_approval,
    policy_snapshot,
    return_requirement,
)

KETTLEBELL = {"product_id": "p1", "name": "Kettlebell",
              "fulfillment": {"requires_shipping": True},
              "refund_policy": {"return_method": "return_required"}}
STICKER = {"product_id": "p2", "name": "Sticker",
           "fulfillment": {"requires_shipping": True},
           "refund_policy": {"return_method": "return_required", "keep_it_below": 2000}}
EBOOK = {"product_id": "p3", "name": "Ebook",
         "fulfillment": {"requires_shipping": False},
         "refund_policy": {"return_method": "return_required"}}
KEEPS = {"product_id": "p4", "name": "Tea",
         "fulfillment": {"requires_shipping": True},
         "refund_policy": {"return_method": "no_return_customer_keeps"}}
BY_ID = {p["product_id"]: p for p in (KETTLEBELL, STICKER, EBOOK, KEEPS)}


class RequirementTests(unittest.TestCase):
    def test_a_product_that_says_return_required_requires_a_return(self):
        result = return_requirement([{"product_id": "p1"}], BY_ID)
        self.assertTrue(result["required"])
        self.assertIn("Kettlebell", result["reason"])

    def test_a_DOWNLOAD_cannot_be_posted_back_whatever_the_policy_says(self):
        """Physical-return language on a digital product is a trap the tenant set for themselves, not an
        instruction to follow."""
        self.assertFalse(return_requirement([{"product_id": "p3"}], BY_ID)["required"])

    def test_customer_keeps_it_needs_no_return(self):
        self.assertFalse(return_requirement([{"product_id": "p4"}], BY_ID)["required"])

    def test_below_the_keep_it_threshold_the_return_is_WAIVED(self):
        """Return postage above the item's worth loses money, and a buyer held waiting files a chargeback
        that costs more than the refund would have."""
        result = return_requirement([{"product_id": "p2"}], BY_ID, order_total=500, keep_it_below=2000)
        self.assertFalse(result["required"])
        self.assertTrue(result["keep_it"])
        self.assertIn("less than the postage", result["reason"])

    def test_above_the_threshold_it_is_not(self):
        result = return_requirement([{"product_id": "p2"}], BY_ID, order_total=9900, keep_it_below=2000)
        self.assertTrue(result["required"])

    def test_one_returnable_product_in_a_mixed_order_is_enough(self):
        result = return_requirement([{"product_id": "p3"}, {"product_id": "p1"}], BY_ID)
        self.assertTrue(result["required"])
        self.assertEqual([p["name"] for p in result["products"]], ["Kettlebell"])

    def test_an_unknown_product_does_not_invent_a_requirement(self):
        self.assertFalse(return_requirement([{"product_id": "gone"}], BY_ID)["required"])


class SnapshotTests(unittest.TestCase):
    def test_the_terms_are_frozen_at_request_time(self):
        """A tenant editing their policy must not retroactively change a return already in flight; the
        buyer agreed to what was written at the time."""
        snapshot = policy_snapshot([{"product_id": "p1"}], BY_ID)
        self.assertTrue(snapshot["return_required"])
        self.assertEqual(snapshot["products"][0]["name"], "Kettlebell")

    def test_the_return_window_is_recorded_so_it_cannot_drift(self):
        snapshot = policy_snapshot([{"product_id": "p1"}], BY_ID, window_days=3)
        self.assertEqual(snapshot["return_window_days"], 3)

    def test_approval_lands_on_return_pending_when_a_return_is_owed(self):
        self.assertEqual(next_status_after_approval(policy_snapshot([{"product_id": "p1"}], BY_ID)),
                         RETURN_PENDING)

    def test_and_on_approved_when_it_is_not(self):
        self.assertEqual(next_status_after_approval(policy_snapshot([{"product_id": "p4"}], BY_ID)),
                         "approved")


class GateTests(unittest.TestCase):
    def test_money_waits_while_the_goods_are_in_the_post(self):
        allowed, why, code = can_release_refund(
            {"status": RETURN_PENDING,
             "policy_snapshot": {"products": [{"name": "Kettlebell"}], "return_required": True}})
        self.assertFalse(allowed)
        self.assertEqual(code, "awaiting_return")
        self.assertIn("Kettlebell", why)

    def test_and_is_released_once_they_are_back(self):
        self.assertEqual(can_release_refund({"status": RETURN_RECEIVED})[0], True)

    def test_an_ordinary_approved_refund_is_untouched(self):
        self.assertEqual(can_release_refund({"status": "approved"})[0], True)

    def test_an_UNAPPROVED_request_is_refused_for_the_right_reason(self):
        """"Awaiting return" about a request nobody has approved sends the tenant looking for a parcel
        that was never asked for."""
        allowed, _, code = can_release_refund({"status": "new"})
        self.assertFalse(allowed)
        self.assertEqual(code, "not_approved")

    def test_the_gate_reads_the_REQUEST_not_todays_policy(self):
        # A policy edited mid-return must not release a refund for goods still in the post.
        frozen = {"status": RETURN_PENDING, "policy_snapshot": {"return_required": True, "products": []}}
        self.assertFalse(can_release_refund(frozen)[0])


class Repo:
    def __init__(self, rows=None, key="refund_request_id"):
        self.rows = list(rows or [])
        self.key = key

    def get(self, tenant_id, doc_id=None):
        return next((r for r in self.rows if r.get(self.key) == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        self.rows = [r for r in self.rows if r.get(self.key) != document.get(self.key)] + [document]
        return document


REQUEST = {"refund_request_id": "rr_1", "tenant_id": "t1", "order_id": "order_1",
           "status": "new", "amount": 9900}
ORDER = {"order_id": "order_1", "tenant_id": "t1", "amount_total": 9900,
         "payment_intent_id": "pi_1", "currency": "usd",
         "line_items": [{"product_id": "p1", "quantity": 1}]}


def _call(action, request=None, body=None, products=None, orders=None):
    requests_repo = Repo([request or dict(REQUEST)])
    result = refunds_handler(
        {"httpMethod": "POST", "resource": "/refunds/{refund_request_id}/" + action,
         "pathParameters": {"refund_request_id": "rr_1"},
         "queryStringParameters": {"tenant_id": "t1"},
         "body": json.dumps(body or {})},
        None,
        requests_repo=requests_repo,
        orders_repo=Repo(orders if orders is not None else [ORDER], key="order_id"),
        products_repo=Repo(products if products is not None else [KETTLEBELL], key="product_id"),
        refunds_repo=Repo(), stripe_repo=Repo(),
        secret_cipher=None, now_fn=lambda: 1000,
    )
    return result, requests_repo


class EndToEndTests(unittest.TestCase):
    def test_approving_a_returnable_order_parks_it_at_return_pending(self):
        result, repo = _call("approve")
        self.assertEqual(result["statusCode"], 200)
        saved = repo.rows[0]
        self.assertEqual(saved["status"], RETURN_PENDING)
        self.assertTrue(saved["policy_snapshot"]["return_required"])
        self.assertEqual(saved["return_started_at"], 1000)

    def test_executing_while_it_is_pending_is_REFUSED(self):
        pending = {**REQUEST, "status": RETURN_PENDING,
                   "policy_snapshot": {"return_required": True, "products": [{"name": "Kettlebell"}]}}
        result, _ = _call("execute", request=pending)
        self.assertEqual(result["statusCode"], 400)
        body = json.loads(result["body"])
        self.assertEqual(body["error"], "awaiting_return")
        self.assertIn("Kettlebell", body["message"])

    def test_marking_received_opens_the_gate(self):
        pending = {**REQUEST, "status": RETURN_PENDING, "policy_snapshot": {"return_required": True}}
        result, repo = _call("received", request=pending, body={"note": "Box back, unopened"})
        self.assertEqual(result["statusCode"], 200)
        saved = repo.rows[0]
        self.assertEqual(saved["status"], RETURN_RECEIVED)
        self.assertEqual(saved["return_received_at"], 1000)
        self.assertEqual(saved["return_note"], "Box back, unopened")
        self.assertTrue(can_release_refund(saved)[0])

    def test_the_amount_can_CHANGE_at_receipt(self):
        """An item back damaged, used, or not the item sent is a partial refund. Restocking fees and
        non-refundable outbound postage land here too."""
        pending = {**REQUEST, "status": RETURN_PENDING, "policy_snapshot": {"return_required": True}}
        _, repo = _call("received", request=pending, body={"amount": 7000, "note": "Scratched"})
        self.assertEqual(repo.rows[0]["amount"], 7000)

    def test_marking_received_on_a_request_that_owes_no_return_is_refused(self):
        result, _ = _call("received", request={**REQUEST, "status": "approved"})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "not_returning")

    def test_approving_a_NON_returnable_order_behaves_exactly_as_before(self):
        result, repo = _call("approve", products=[KEEPS],
                             orders=[{**ORDER, "line_items": [{"product_id": "p4"}]}])
        self.assertEqual(repo.rows[0]["status"], "approved")

    def test_an_unreadable_catalogue_does_not_block_the_decision(self):
        class Exploding(Repo):
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("AccessDenied")

        requests_repo = Repo([dict(REQUEST)])
        result = refunds_handler(
            {"httpMethod": "POST", "resource": "/refunds/{refund_request_id}/approve",
             "pathParameters": {"refund_request_id": "rr_1"},
             "queryStringParameters": {"tenant_id": "t1"}, "body": "{}"},
            None, requests_repo=requests_repo, orders_repo=Repo([ORDER], key="order_id"),
            products_repo=Exploding(key="product_id"), refunds_repo=Repo(), stripe_repo=Repo(),
            secret_cipher=None, now_fn=lambda: 1000)
        self.assertEqual(result["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
