import json
import unittest

from handlers.invoices import handler
from stripe_link.domain.invoicing import (
    invoice_email_content,
    invoice_total,
    stripe_invoice_params,
    stripe_invoiceitem_params,
)
from tests.fakes import FakeDocumentRepository

INVOICE = {
    "schema_version": "2026-05-29", "document_type": "invoice", "tenant_id": "t1", "invoice_id": "inv_1",
    "status": "draft", "customer": {"email": "c@e.com", "name": "Casey"},
    "line_items": [
        {"type": "service", "description": "Tax prep", "quantity": 1, "unit_amount": 15000, "currency": "usd", "service_id": "svc_1"},
    ],
    "amounts": {"currency": "usd", "total": 15000},
}


class FakeCipher:
    def decrypt(self, ref, *, tenant_id, mode, field):
        return "sk_test_fake"


class FakeStripeKeys:
    def __init__(self, keys):
        self.keys = keys

    def get(self, tenant_id, mode="test"):
        return self.keys


class _FakeResp:
    def __init__(self, payload):
        self._d = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, request, timeout=None):
        return _FakeResp(self.responses.pop(0))


class InvoicingDomainTests(unittest.TestCase):
    def test_total_and_items(self):
        inv = {"line_items": [{"unit_amount": 5000, "quantity": 2}, {"unit_amount": 1000, "quantity": 1}]}
        self.assertEqual(invoice_total(inv), 11000)

    def test_invoiceitem_params(self):
        params = stripe_invoiceitem_params("cus_1", {"unit_amount": 15000, "quantity": 2, "description": "Prep"}, "usd")
        self.assertEqual(params, {"customer": "cus_1", "currency": "usd", "amount": 30000, "description": "Prep"})

    def test_invoice_params_fee_and_metadata(self):
        params = stripe_invoice_params("cus_1", application_fee=500, metadata={"invoice_id": "inv_1", "empty": ""})
        self.assertEqual(params["collection_method"], "send_invoice")
        self.assertEqual(params["application_fee_amount"], 500)
        self.assertEqual(params["metadata"], {"invoice_id": "inv_1"})

    def test_email_content_has_link_and_total(self):
        content = invoice_email_content(INVOICE, "https://pay.stripe.com/abc", business_name="Acme")
        self.assertIn("Acme", content["subject"])
        self.assertIn("$150.00", content["html"])
        self.assertIn("https://pay.stripe.com/abc", content["html"])
        self.assertIn("https://pay.stripe.com/abc", content["text"])


class SendInvoiceHandlerTests(unittest.TestCase):
    def _env(self, invoice=None):
        invoices = FakeDocumentRepository("invoice_id")
        invoices.put(dict(invoice or INVOICE))
        stripe_repo = FakeStripeKeys({"secret_key_ref": "enc:sk"})
        tenant_repo = FakeDocumentRepository("tenant_id")
        tenant_repo.put({"tenant_id": "t1", "business_name": "Acme", "support_email": "s@acme.com", "tier_id": "basic"})
        return invoices, stripe_repo, tenant_repo

    def _event(self, invoice_id="inv_1"):
        return {"httpMethod": "POST", "path": f"/invoices/{invoice_id}/send",
                "pathParameters": {"invoice_id": invoice_id}, "queryStringParameters": {"tenant_id": "t1"}}

    def test_send_finalizes_and_emails(self):
        invoices, stripe_repo, tenant_repo = self._env()
        opener = _FakeOpener(
            {"id": "cus_1"},                                                # create customer
            {"id": "ii_1"},                                                 # invoice item
            {"id": "in_1"},                                                 # create invoice
            {"id": "in_1", "hosted_invoice_url": "https://pay.stripe.com/x", "invoice_pdf": "https://pdf"},  # finalize
        )
        sent = {}
        def fake_send(*, to, subject, html, text, from_name, reply_to):
            sent.update({"to": to, "subject": subject})
            return {"MessageId": "m1"}

        response = handler(self._event(), None, repository=invoices, stripe_repo=stripe_repo, tenant_repo=tenant_repo,
                           secret_cipher=FakeCipher(), opener=opener, mailer_send=fake_send, billing_config_loader=lambda: {})
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["hosted_invoice_url"], "https://pay.stripe.com/x")
        self.assertTrue(body["delivered"])
        stored = invoices.get("t1", "inv_1")
        self.assertEqual(stored["status"], "open")
        self.assertEqual(stored["stripe_invoice_id"], "in_1")
        self.assertEqual(stored["payment"]["hosted_invoice_url"], "https://pay.stripe.com/x")
        self.assertTrue(stored["delivery"]["sent_at"])
        self.assertEqual(stored["delivery"]["send_count"], 1)
        self.assertEqual(sent["to"], "c@e.com")

    def test_send_requires_email(self):
        inv = {**INVOICE, "customer": {"name": "Casey"}}
        invoices, stripe_repo, tenant_repo = self._env(inv)
        response = handler(self._event(), None, repository=invoices, stripe_repo=stripe_repo, tenant_repo=tenant_repo, secret_cipher=FakeCipher())
        self.assertEqual(response["statusCode"], 400)

    def test_send_already_paid(self):
        inv = {**INVOICE, "status": "paid"}
        invoices, stripe_repo, tenant_repo = self._env(inv)
        response = handler(self._event(), None, repository=invoices, stripe_repo=stripe_repo, tenant_repo=tenant_repo, secret_cipher=FakeCipher())
        self.assertEqual(response["statusCode"], 409)

    def test_send_stripe_not_configured(self):
        invoices, _, tenant_repo = self._env()
        response = handler(self._event(), None, repository=invoices, stripe_repo=FakeStripeKeys({}), tenant_repo=tenant_repo, secret_cipher=FakeCipher())
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "stripe_not_configured")


class InvoiceWebhookTests(unittest.TestCase):
    def _invoice_event(self, event_type, *, payment_intent="pi_1", amount_paid=15000):
        return {"type": event_type, "data": {"object": {
            "metadata": {"invoice_id": "inv_1", "tenant_id": "t1", "product_type": "digital", "tenant_plan": "basic"},
            "payment_intent": payment_intent, "amount_paid": amount_paid, "currency": "usd",
            "hosted_invoice_url": "https://pay.stripe.com/x",
        }}}

    def test_paid_updates_status_ledger_and_notification(self):
        from handlers.stripe_webhook import persist_invoice_event
        from tests.test_ledger import FakeLedgerRepository

        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({**INVOICE, "status": "open"})
        ledger = FakeLedgerRepository()
        notifications = FakeDocumentRepository("notification_id")
        result = persist_invoice_event(self._invoice_event("invoice.paid"), tenant_id="t1", event_type="invoice.paid",
                                       mode="test", invoices_repo=invoices, ledger_repo=ledger, notifications_repo=notifications,
                                       billing_config_loader=lambda: {}, now_fn=lambda: 1000)
        self.assertEqual(result["status"], "paid")
        self.assertTrue(result["ledger_entry"])
        stored = invoices.get("t1", "inv_1")
        self.assertEqual(stored["status"], "paid")
        self.assertEqual(stored["payment"]["paid_at"], 1000)
        entries = ledger.list_for_order("inv_1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["amounts"]["gross"], 15000)
        self.assertEqual(len(notifications.list_for_tenant("t1")), 1)

    def test_voided_sets_status(self):
        from handlers.stripe_webhook import persist_invoice_event

        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({**INVOICE, "status": "open"})
        result = persist_invoice_event(self._invoice_event("invoice.voided"), tenant_id="t1", event_type="invoice.voided",
                                       mode="test", invoices_repo=invoices, now_fn=lambda: 1000)
        self.assertEqual(result["status"], "void")
        self.assertEqual(invoices.get("t1", "inv_1")["status"], "void")

    def test_untracked_invoice_skipped(self):
        from handlers.stripe_webhook import persist_invoice_event

        event = {"type": "invoice.paid", "data": {"object": {"metadata": {}}}}
        result = persist_invoice_event(event, tenant_id="t1", event_type="invoice.paid", mode="test",
                                       invoices_repo=FakeDocumentRepository("invoice_id"))
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
