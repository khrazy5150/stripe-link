"""A paid tenant invoice must leave a record the tenant can see.

2026-11-09: a customer paid a $15.86 invoice. The dashboard showed no revenue, no order, and a single
CRITICAL notification saying "A payment was taken that we have no order for" -- about the very payment
the invoice page already showed as paid. Four separate defects, one payment:

  1. the ledger write was gated on `invoice.payment_intent`, REMOVED in API 2025-03-31.basil, so the
     gate never fired and no revenue was recorded -- silently, with no error;
  2. `amounts.amount_paid` was never updated, so a paid invoice read `paid: 0` beside its full total;
  3. the orphan sweep asked only "is there an ORDER for this invoice?", which is the subscription
     convention -- a tenant-raised invoice records a LEDGER entry and never an order;
  4. `notifications_repo` is resolved lazily in two other paths in that module but not this one, so the
     caller's None travelled down and the only notification about this money was the wrong one.
"""
import unittest
from unittest import mock

from stripe_link.domain.orphan_charges import orphans


class TheLedgerDoesNotNeedAPaymentIntentTests(unittest.TestCase):
    def test_the_entry_is_keyed_on_the_invoice_when_there_is_no_payment_intent(self):
        import inspect

        from handlers import stripe_webhook

        src = inspect.getsource(stripe_webhook)
        self.assertIn('ledger_key = payment_intent or str(stripe_invoice.get("id")', src)
        self.assertIn('entry_id=f"le_sale_{ledger_key}"', src)
        self.assertNotIn("if ledger_repo and amount_paid and payment_intent:", src,
                         "the removed field must not gate the ledger write")

    def test_payments_array_is_read_when_present(self):
        from handlers.stripe_webhook import _invoice_payment_intent

        self.assertEqual(_invoice_payment_intent(
            {"payments": {"data": [{"payment": {"payment_intent": "pi_123"}}]}}), "pi_123")
        self.assertEqual(_invoice_payment_intent(
            {"payments": {"data": [{"payment": {"payment_intent": {"id": "pi_456"}}}]}}), "pi_456")

    def test_an_ordinary_payload_yields_nothing_rather_than_raising(self):
        """`payments` arrives only when expanded, so callers must not depend on getting one."""
        from handlers.stripe_webhook import _invoice_payment_intent

        for payload in ({}, {"payments": None}, {"payments": {"data": []}}, {"payments": []},
                        {"payments": {"data": [{}]}}):
            self.assertEqual(_invoice_payment_intent(payload), "")


class APaidInvoiceRecordsWhatWasCollectedTests(unittest.TestCase):
    def test_amount_paid_is_written_from_stripe(self):
        import inspect

        from handlers import stripe_webhook

        src = inspect.getsource(stripe_webhook)
        self.assertIn('amounts["amount_paid"] = collected', src)
        self.assertIn('amounts["amount_due"] = max(0,', src)


class LedgerRecordedMoneyIsNotAnOrphanTests(unittest.TestCase):
    CHARGE = {"id": "ch_1", "amount": 1586, "amount_captured": 1586, "currency": "usd",
              "status": "succeeded", "paid": True, "refunded": False,
              "invoice": "in_1", "payment_intent": "pi_1"}

    def test_the_fixture_is_actually_examined(self):
        """Without `amount_captured` this charge is filtered out before any of the logic below runs, and
        every test in this class passes by returning an empty list for the wrong reason. Asserting the
        NEGATIVE case first is what makes the positive ones mean anything."""
        from stripe_link.domain.orphan_charges import is_recordable

        self.assertTrue(is_recordable(self.CHARGE))

    def _orphans(self, *, order=None, ledger_ids=()):
        return orphans([self.CHARGE],
                       order_for_payment_intent=lambda _pi: None,
                       order_for_id=lambda _oid: order,
                       ledger_entry_for_id=lambda eid: {"entry_id": eid} if eid in ledger_ids else None)

    def test_a_ledger_sale_keyed_ON_THE_INVOICE_clears_it(self):
        self.assertEqual(self._orphans(ledger_ids={"le_sale_in_1"}), [])

    def test_a_ledger_sale_keyed_on_the_PAYMENT_INTENT_also_clears_it(self):
        """Entries written before Basil are keyed on the PI. An audit that knows only today's convention
        declares the past missing."""
        self.assertEqual(self._orphans(ledger_ids={"le_sale_pi_1"}), [])

    def test_with_neither_it_is_still_reported(self):
        found = self._orphans()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["reason"], "no_order_for_invoice")

    def test_a_subscription_order_still_clears_it(self):
        self.assertEqual(self._orphans(order={"order_id": "order_in_1"}), [])

    def test_a_raising_ledger_read_is_not_reported_as_missing_money(self):
        """An unreadable table must never be announced as a lost payment."""
        def boom(_eid):
            raise RuntimeError("DynamoDB is down")

        self.assertEqual(orphans([self.CHARGE], order_for_payment_intent=lambda _pi: None,
                                 order_for_id=lambda _oid: None, ledger_entry_for_id=boom), [])


class TheTenantIsToldAboutTheirOwnMoneyTests(unittest.TestCase):
    def test_the_notification_repo_is_resolved_not_merely_accepted(self):
        import inspect

        from handlers import stripe_webhook

        src = inspect.getsource(stripe_webhook)
        resolved = src.count("notifications_repo = notifications_repo or (")
        self.assertGreaterEqual(resolved, 3, "the invoice path must resolve its own, like its neighbours")


if __name__ == "__main__":
    unittest.main()
