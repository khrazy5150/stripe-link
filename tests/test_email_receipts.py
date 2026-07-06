import os
import unittest
from unittest.mock import patch

from stripe_link.domain.receipts import format_money, receipt_content
from stripe_link.mailer import EmailError, from_email_address, send_email
from handlers.stripe_webhook import send_order_receipt


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m_1"}


ORDER = {
    "order_id": "order_cs_123",
    "amount_total": 3709,
    "currency": "usd",
    "customer": {"name": "Ada Lovelace", "email": "ada@example.com"},
    "product": {"name": "Creatine Gummies"},
}


class MailerTests(unittest.TestCase):
    def test_from_address_uses_display_name(self):
        with patch.dict(os.environ, {"EMAIL_FROM_ADDRESS": "support@juniorbay.net"}, clear=False):
            self.assertEqual(from_email_address("Acme Co"), "Acme Co <support@juniorbay.net>")
            self.assertEqual(from_email_address(""), "support@juniorbay.net")

    def test_send_email_builds_ses_request(self):
        ses = FakeSes()
        with patch.dict(os.environ, {"EMAIL_FROM_ADDRESS": "support@juniorbay.net"}, clear=False):
            send_email(to="ada@example.com", subject="Hi", html="<p>Hi</p>", text="Hi",
                       from_name="Acme Co", reply_to="help@acme.com", client=ses)
        req = ses.sent[0]
        self.assertEqual(req["FromEmailAddress"], "Acme Co <support@juniorbay.net>")
        self.assertEqual(req["Destination"]["ToAddresses"], ["ada@example.com"])
        self.assertEqual(req["ReplyToAddresses"], ["help@acme.com"])
        self.assertEqual(req["Content"]["Simple"]["Subject"]["Data"], "Hi")

    def test_send_email_requires_recipient_and_body(self):
        with self.assertRaises(EmailError):
            send_email(to="", subject="x", html="<p>x</p>", client=FakeSes())
        with self.assertRaises(EmailError):
            send_email(to="a@b.com", subject="x", client=FakeSes())


class ReceiptRenderTests(unittest.TestCase):
    def test_format_money(self):
        self.assertEqual(format_money(3709, "usd"), "USD 37.09")

    def test_receipt_includes_order_and_downloads(self):
        content = receipt_content(
            ORDER,
            business_name="Acme Co",
            support_email="help@acme.com",
            download_links=[{"label": "Guide.pdf", "url": "https://x/download/tok"}],
        )
        self.assertEqual(content["subject"], "Your receipt from Acme Co")
        self.assertIn("Creatine Gummies", content["html"])
        self.assertIn("USD 37.09", content["html"])
        self.assertIn("https://x/download/tok", content["html"])
        self.assertIn("help@acme.com", content["text"])


class WebhookReceiptHookTests(unittest.TestCase):
    def test_sends_receipt_with_injected_mailer_and_context(self):
        sent = []
        result = send_order_receipt(
            ORDER, "tenant_demo",
            mailer_send=lambda **kw: sent.append(kw),
            context_loader=lambda tid: {"business_name": "Acme Co", "support_email": "help@acme.com"},
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(sent[0]["to"], "ada@example.com")
        self.assertEqual(sent[0]["from_name"], "Acme Co")
        self.assertEqual(sent[0]["reply_to"], "help@acme.com")
        self.assertIn("Creatine Gummies", sent[0]["html"])

    def test_skips_when_email_not_configured_and_no_mailer(self):
        with patch.dict(os.environ, {}, clear=True):
            result = send_order_receipt(ORDER, "tenant_demo")
        self.assertEqual(result["status"], "skipped")

    def test_skips_when_no_customer_email(self):
        order = {**ORDER, "customer": {"name": "Ada", "email": ""}}
        result = send_order_receipt(order, "tenant_demo", mailer_send=lambda **kw: None)
        self.assertEqual(result["status"], "skipped")

    def test_failure_is_swallowed(self):
        def boom(**kwargs):
            raise RuntimeError("SES down")
        result = send_order_receipt(
            ORDER, "tenant_demo",
            mailer_send=boom,
            context_loader=lambda tid: {"business_name": "", "support_email": ""},
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("SES down", result["error"])


if __name__ == "__main__":
    unittest.main()
