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


class TheTenantIsEmailedWhenTheyArePaidTests(unittest.TestCase):
    """A dashboard notice is only read by someone who opens the dashboard. The tenant who raised an
    invoice is waiting on the money, not watching a screen."""

    INVOICE = {
        "invoice_id": "inv_1",
        "amounts": {"amount_paid": 1586, "amount_due": 0, "total": 1586, "currency": "usd"},
        "customer": {"name": "Minxin Chen", "email": "buyer@example.com"},
        "line_items": [{"description": "Domain Name", "quantity": 1, "unit_amount": 1586,
                        "currency": "usd"}],
    }

    def test_it_reports_what_was_COLLECTED_not_what_was_billed(self):
        """A partial payment announced as the full amount is worse than saying nothing."""
        from stripe_link.domain.invoicing import invoice_paid_tenant_email

        partial = {**self.INVOICE,
                   "amounts": {**self.INVOICE["amounts"], "amount_paid": 500, "amount_due": 1086}}
        content = invoice_paid_tenant_email(partial, business_name="Poliaxis Nutrition")
        self.assertIn("$5.00", content["subject"])
        self.assertNotIn("$15.86", content["subject"])

    def test_it_falls_back_to_the_total_when_amount_paid_is_missing(self):
        from stripe_link.domain.invoicing import invoice_paid_tenant_email

        legacy = {**self.INVOICE, "amounts": {"total": 1586, "currency": "usd"}}
        self.assertIn("$15.86", invoice_paid_tenant_email(legacy)["subject"])

    def test_the_customer_is_named_and_the_amount_is_in_the_body(self):
        from stripe_link.domain.invoicing import invoice_paid_tenant_email

        content = invoice_paid_tenant_email(self.INVOICE, business_name="Poliaxis Nutrition",
                                            dashboard_url="https://app.juniorbay.com/invoices")
        self.assertEqual(content["subject"], "Minxin Chen paid $15.86")
        self.assertIn("$15.86", content["html"])
        self.assertIn("https://app.juniorbay.com/invoices", content["html"])
        self.assertIn("Minxin Chen", content["text"])

    def test_no_dashboard_url_drops_the_button_rather_than_linking_to_root(self):
        from stripe_link.domain.invoicing import invoice_paid_tenant_email

        content = invoice_paid_tenant_email(self.INVOICE, dashboard_url="")
        self.assertNotIn('href="/"', content["html"])

    def test_the_webhook_sends_through_the_INJECTED_mailer(self):
        """`feedback_undeliverable_recipients`: the suite once emailed real people via SES. The call
        site passes the same injected mailer the receipts use, so a test that forgets one still cannot
        reach SES."""
        import inspect

        from handlers import stripe_webhook

        src = inspect.getsource(stripe_webhook)
        self.assertIn("(mailer_send or send_email)(", src)
        call = inspect.getsource(stripe_webhook.handler) if hasattr(stripe_webhook, "handler") else src
        self.assertIn("mailer_send=receipt_mailer", src)

    def test_a_tenant_with_no_verified_address_is_skipped_loudly(self):
        import inspect

        from handlers import stripe_webhook

        src = inspect.getsource(stripe_webhook)
        self.assertIn("invoice_paid_email_skipped", src)
        self.assertIn("invoice_paid_email_failed", src)
