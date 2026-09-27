"""A tip refunds the TIP, not the charge.

plans/PAY_WHAT_YOU_WANT.md §5f. Under the default net_guaranteed handling the supporter is charged the
fees on top of the gift, so refunding the charge would make the creator pay back more than ever reached
their balance. These tests pin the three places that has to hold: the amount sent to Stripe, the
aggregates the tenant reads afterwards, and the buyer's receipt.
"""

import json
import unittest

from stripe_link.domain.receipts import receipt_content
from stripe_link.domain.refund_ledger import refundable_ceiling, set_refund_aggregates
from stripe_link.domain.tips import fee_breakdown, refund_amount, tip_keyed_amount
from tests.fakes import FakeDocumentRepository
from tests.test_refunds import FakeKeys, FakeStripe, creds

from handlers.refunds import handler

# A $10.00 tip under net_guaranteed: the supporter is charged $11.00 so the creator keeps the round $10.
NET_GUARANTEED_TIP = {"metadata": {"tip_keyed_amount": "1000"}, "amount_total": 1100}


class TipKeyedAmountTests(unittest.TestCase):
    def test_reads_the_typed_amount_from_metadata(self):
        self.assertEqual(tip_keyed_amount(NET_GUARANTEED_TIP), 1000)

    def test_none_for_an_ordinary_order(self):
        self.assertIsNone(tip_keyed_amount({"amount_total": 1834}))

    def test_none_rather_than_raising_on_junk(self):
        for raw in ("", None, "abc", "0", "-5", {}, []):
            with self.subTest(raw=raw):
                self.assertIsNone(tip_keyed_amount({"metadata": {"tip_keyed_amount": raw}}))

    def test_survives_a_missing_or_mistyped_metadata_block(self):
        self.assertIsNone(tip_keyed_amount({}))
        self.assertIsNone(tip_keyed_amount({"metadata": "nope"}))
        self.assertIsNone(tip_keyed_amount(None))


class RefundAmountTests(unittest.TestCase):
    def test_net_guaranteed_tip_returns_the_tip_not_the_charge(self):
        self.assertEqual(refund_amount(NET_GUARANTEED_TIP), 1000)

    def test_standard_tip_returns_the_whole_charge(self):
        # The supporter paid exactly what they typed; the creator absorbs the fees they chose to absorb.
        self.assertEqual(refund_amount({"metadata": {"tip_keyed_amount": "1000"}, "amount_total": 1000}), 1000)

    def test_ordinary_order_refunds_its_total(self):
        self.assertEqual(refund_amount({"amount_total": 1834}), 1834)

    def test_never_more_than_was_actually_charged(self):
        # A keyed amount above the charge can only be corruption; refunding it would invent money.
        self.assertEqual(refund_amount({"metadata": {"tip_keyed_amount": "1000"}, "amount_total": 500}), 500)


class RefundableCeilingTests(unittest.TestCase):
    def test_a_fully_refunded_tip_is_refunded_not_partially_refunded(self):
        order = {**NET_GUARANTEED_TIP, "amount_paid": 1100}
        updated = set_refund_aggregates(order, amount_refunded=1000, refund_count=1, at=1781230000)
        self.assertEqual(updated["payment_status"], "refunded")
        self.assertEqual(updated["refundable_amount"], 0)
        # amount_paid stays honest: the supporter really did pay $11.00.
        self.assertEqual(updated["amount_paid"], 1100)

    def test_partial_refund_of_a_tip_measures_against_the_tip(self):
        order = {**NET_GUARANTEED_TIP, "amount_paid": 1100}
        updated = set_refund_aggregates(order, amount_refunded=400, refund_count=1, at=1781230000)
        self.assertEqual(updated["payment_status"], "partially_refunded")
        self.assertEqual(updated["refundable_amount"], 600)  # of the $10.00 tip, not the $11.00 charge

    def test_ceiling_is_the_paid_amount_for_everything_else(self):
        self.assertEqual(refundable_ceiling({"amount_total": 1834, "amount_paid": 1834}), 1834)

    def test_ordinary_order_aggregates_are_unchanged(self):
        updated = set_refund_aggregates(
            {"amount_total": 3709, "amount_paid": 3709}, amount_refunded=1000, refund_count=1, at=1781230000)
        self.assertEqual(updated["payment_status"], "partially_refunded")
        self.assertEqual(updated["refundable_amount"], 2709)


class ReceiptBreakdownTests(unittest.TestCase):
    def test_breakdown_splits_the_gross_up(self):
        self.assertEqual(fee_breakdown(NET_GUARANTEED_TIP), (1000, 100))

    def test_no_breakdown_when_nothing_was_added_on_top(self):
        self.assertIsNone(fee_breakdown({"metadata": {"tip_keyed_amount": "1000"}, "amount_total": 1000}))
        self.assertIsNone(fee_breakdown({"amount_total": 1834}))

    def test_receipt_shows_the_tip_and_the_fees_the_supporter_covered(self):
        content = receipt_content(
            {**NET_GUARANTEED_TIP, "order_id": "order_abc", "currency": "usd",
             "customer": {"name": "Ada"}, "product": {"name": "Tip jar"}},
            business_name="Junior Bay")
        for expected in ("Tip: USD 10.00", "Fees you covered: USD 1.00", "Total: USD 11.00"):
            self.assertIn(expected, content["text"])
        self.assertIn("Fees you covered", content["html"])

    def test_ordinary_receipt_shows_the_total_alone(self):
        content = receipt_content(
            {"order_id": "order_z", "amount_total": 1834, "currency": "usd",
             "customer": {"name": "Ada"}, "product": {"name": "Creatine Gummies"}})
        self.assertIn("Total: USD 18.34", content["text"])
        self.assertNotIn("Fees you covered", content["text"])
        self.assertNotIn("Tip:", content["text"])


class TipRefundHandlerTests(unittest.TestCase):
    """End to end: the amount that actually reaches Stripe."""

    def setUp(self):
        self.requests = FakeDocumentRepository("refund_request_id")
        self.orders = FakeDocumentRepository("order_id")
        self.refunds = FakeDocumentRepository("refund_id")
        self.requests.put({
            "tenant_id": "t1", "refund_request_id": "rr_tip", "document_type": "refund_request",
            "status": "approved", "order_id": "order_tip", "customer": {"email": "a@b.com"},
            "amount": {"currency": "usd", "requested_amount": 0, "paid_amount": 1100},
        })
        self.orders.put({
            "tenant_id": "t1", "order_id": "order_tip", "payment_status": "paid",
            "amount_total": 1100, "amount_paid": 1100, "amount_refunded": 0, "refund_count": 0,
            "currency": "usd", "payment_intent_id": "pi_tip", "mode": "test",
            "metadata": {"tip_keyed_amount": "1000"},
        })

    def execute(self, stripe):
        return handler(
            {"httpMethod": "POST", "resource": "/refunds/{refund_request_id}/execute",
             "pathParameters": {"refund_request_id": "rr_tip"},
             "queryStringParameters": {"tenant_id": "t1"}},
            None,
            requests_repo=self.requests, orders_repo=self.orders, refunds_repo=self.refunds,
            stripe_repo=FakeKeys(), secret_cipher=None, caller=stripe, credentials_fn=creds,
            now_fn=lambda: 1781230000,
        )

    def test_full_refund_of_a_tip_sends_the_tip_as_an_explicit_amount(self):
        stripe = FakeStripe()
        body = json.loads(self.execute(stripe)["body"])
        # A "full" refund of a tip is a PARTIAL refund at Stripe -- the amount must be stated, because
        # omitting it is what tells Stripe to return the entire charge.
        self.assertEqual(stripe.calls[0]["data"]["amount"], 1000)
        self.assertEqual(body["refund"]["amount"], 1000)
        order = self.orders.get("t1", "order_tip")
        self.assertEqual(order["payment_status"], "refunded")
        self.assertEqual(order["refundable_amount"], 0)
        self.assertEqual(self.refunds.get("t1", "re_1")["amount"], 1000)

    def test_a_request_above_the_tip_is_clamped_to_the_tip(self):
        self.requests.documents[("t1", "rr_tip")]["amount"]["requested_amount"] = 1100
        stripe = FakeStripe()
        self.execute(stripe)
        self.assertEqual(stripe.calls[0]["data"]["amount"], 1000)

    def test_a_request_below_the_tip_is_honoured(self):
        self.requests.documents[("t1", "rr_tip")]["amount"]["requested_amount"] = 250
        stripe = FakeStripe()
        self.execute(stripe)
        self.assertEqual(stripe.calls[0]["data"]["amount"], 250)
