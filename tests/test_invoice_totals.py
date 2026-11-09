"""An invoice must be finalized for the amount it says it is.

2026-11-09: a $15.86 invoice went out by email, finalized at $0.00, and marked itself paid on the spot.
Stripe invoice items created with only a `customer` are *pending*; a draft takes them in only if it asks,
and `pending_invoice_items_behavior` has defaulted to `exclude` since API version 2022-08-01. The draft
was therefore empty. Nothing failed: the customer got a correct-looking email and a payment page asking
for nothing.
"""
import unittest
from unittest import mock

from stripe_link.domain.invoicing import stripe_invoiceitem_params


class ItemsAreBoundToTheInvoiceTests(unittest.TestCase):
    ITEM = {"description": "Domain Name", "quantity": 1, "unit_amount": 1586}

    def test_an_invoice_id_binds_the_item(self):
        params = stripe_invoiceitem_params("cus_1", self.ITEM, "usd", "in_123")
        self.assertEqual(params["invoice"], "in_123")
        self.assertEqual(params["amount"], 1586)

    def test_without_one_the_item_is_left_pending(self):
        """The old behaviour, kept only so a caller that genuinely wants a pending item still can."""
        self.assertNotIn("invoice", stripe_invoiceitem_params("cus_1", self.ITEM, "usd"))


class TheDraftIsCreatedBeforeItsItemsTests(unittest.TestCase):
    def test_the_invoice_is_created_first(self):
        """Order is the whole fix: items bound to a draft that does not exist yet cannot be bound."""
        import inspect

        from handlers import invoices

        src = inspect.getsource(invoices.send_invoice_route)
        create_invoice = src.index('"POST", "/invoices"')
        create_items = src.index('"POST", "/invoiceitems"')
        self.assertLess(create_invoice, create_items,
                        "the draft must be created before the items that bind to it")

    def test_items_are_keyed_per_item_for_idempotency(self):
        """The invoice create is idempotent, so a retry returns the SAME draft. Without a per-item key
        the retry appends a second copy of every line."""
        import inspect

        from handlers import invoices

        src = inspect.getsource(invoices.send_invoice_route)
        self.assertIn('idempotency_key=f"invoice_{invoice_id}_item_{index}"', src)


class AMismatchedTotalIsNotSentTests(unittest.TestCase):
    """A finalized invoice is immutable and a zero one is paid on arrival, so this is the last moment
    anything can be done about it."""

    def test_the_guard_compares_stripe_against_our_line_items(self):
        import inspect

        from handlers import invoices

        src = inspect.getsource(invoices.send_invoice_route)
        self.assertIn("invoice_total_mismatch", src)
        guard = src.index("invoice_total_mismatch")
        send = src.index("send(to=customer")
        self.assertLess(guard, send, "the total must be checked BEFORE the email goes out")


class TheZeroInvoiceIsRefusedEndToEndTests(unittest.TestCase):
    """The live reproduction: Stripe finalizes at 0 while our document says 15000."""

    def _send(self, finalized_total):
        import json

        from handlers.invoices import handler
        from tests.test_invoicing import FakeCipher, SendInvoiceHandlerTests, _FakeOpener

        case = SendInvoiceHandlerTests("test_send_finalizes_and_emails")
        invoices, stripe_repo, tenant_repo = case._env()
        opener = _FakeOpener(finalized={"id": "in_1", "total": finalized_total,
                                        "hosted_invoice_url": "https://pay.stripe.com/x"})
        sent = {}

        def fake_send(*, to, subject, html, text, from_name, reply_to, **_kw):
            sent["to"] = to

        resp = handler(case._event("inv_1"), None, repository=invoices, stripe_repo=stripe_repo,
                       tenant_repo=tenant_repo, secret_cipher=FakeCipher(), opener=opener,
                       mailer_send=fake_send)
        return resp, sent

    def test_a_zero_total_is_refused_and_nothing_is_emailed(self):
        resp, sent = self._send(0)
        self.assertEqual(resp["statusCode"], 502)
        self.assertIn("invoice_total_mismatch", resp["body"])
        self.assertEqual(sent, {}, "the customer must not receive an invoice Stripe will not charge")

    def test_the_matching_total_still_sends(self):
        resp, sent = self._send(15000)
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(sent.get("to"))


if __name__ == "__main__":
    unittest.main()
