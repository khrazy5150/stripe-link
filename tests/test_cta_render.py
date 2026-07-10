"""The offer's presentation.cta contract drives which CTA the landing page renders (buy/call/email/
external/booking). render_checkout_cta must branch on it, not always emit a Stripe price button."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.runtime.html import offer_cta, render_checkout_cta


def _offer(cta=None):
    presentation = {"cta_label": "Buy Now"}
    if cta is not None:
        presentation["cta"] = cta
    return {"offer_id": "off_1", "tenant_id": "t1", "presentation": presentation}


def _render(cta):
    resolved = {"subtotal": 15000, "currency": "usd", "items": [{}]}
    return render_checkout_cta(_offer(cta), {"type": "checkout_cta"}, _offer(cta), resolved, None, None)


class OfferCtaTests(unittest.TestCase):
    def test_defaults_to_buy_when_absent_or_invalid(self):
        self.assertEqual(offer_cta(_offer())["type"], "buy")
        self.assertEqual(offer_cta(_offer({"type": "nonsense"}))["type"], "buy")

    def test_buy_renders_price_button(self):
        html = _render({"type": "buy", "label": "Buy Now"})
        self.assertIn('data-cta-type="buy"', html)
        self.assertIn("$150.00", html)

    def test_call_renders_tel_link_and_number(self):
        html = _render({"type": "call", "label": "Call Kristin", "target": "+1 (555) 123-4567"})
        self.assertIn('data-cta-type="call"', html)
        self.assertIn('href="tel:+15551234567"', html)
        self.assertIn("+1 (555) 123-4567", html)
        self.assertIn("Call Kristin", html)
        self.assertNotIn("$150.00", html)  # a call CTA must never show a price

    def test_external_renders_new_tab_link(self):
        html = _render({"type": "external", "label": "Learn More", "target": "https://example.com/x"})
        self.assertIn('data-cta-type="external"', html)
        self.assertIn('href="https://example.com/x"', html)
        self.assertIn('target="_blank"', html)
        self.assertNotIn("$150.00", html)

    def test_booking_and_email_render_action_button_without_price(self):
        for cta_type in ("booking", "email"):
            html = _render({"type": cta_type, "label": "Go", "target": "svc_1"})
            self.assertIn(f'data-cta-type="{cta_type}"', html)
            self.assertNotIn("$150.00", html)


class OfferCtaValidationTests(unittest.TestCase):
    def _base(self):
        return {
            "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
            "name": "X", "product_intent": "transaction", "stripe_mode": "test", "status": "active",
            "items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1}],
            "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
        }

    def test_valid_cta_passes(self):
        doc = self._base()
        doc["presentation"] = {"cta": {"type": "call", "label": "Call", "target": "+15551234567"}}
        validate_offer_document(doc)  # must not raise

    def test_invalid_cta_type_rejected(self):
        doc = self._base()
        doc["presentation"] = {"cta": {"type": "sms"}}
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(doc)


if __name__ == "__main__":
    unittest.main()
