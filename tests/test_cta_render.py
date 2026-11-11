"""The offer's presentation.cta contract drives which CTA the landing page renders (buy/call/email/
external/booking). render_checkout_cta must branch on it, not always emit a Stripe price button."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.runtime.html import (
    UNIVERSAL_BUNDLE_TEMPLATE_STYLES, offer_cta, render_checkout_cta, render_email_cta)


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
        # DISPLAYED in national form from 2026-09-16 (dialable_number): the stored value is E.164, and a
        # string of digits is not a phone number to the eye. The href still carries the raw digits.
        self.assertIn("(555) 123-4567", html)
        self.assertIn("Call Kristin", html)
        self.assertNotIn("$150.00", html)  # a call CTA must never show a price

    def test_external_renders_new_tab_link(self):
        html = _render({"type": "external", "label": "Learn More", "target": "https://example.com/x"})
        self.assertIn('data-cta-type="external"', html)
        self.assertIn('href="https://example.com/x"', html)
        self.assertIn('target="_blank"', html)
        self.assertNotIn("$150.00", html)

    def test_booking_renders_inline_calendar_widget(self):
        html = _render({"type": "booking", "label": "Book Now", "target": "svc_1"})
        self.assertIn('data-cta-type="booking"', html)
        self.assertIn('data-booking-widget', html)
        self.assertIn('data-service-id="svc_1"', html)
        self.assertIn('data-booking-reveal', html)      # button reveals the panel
        self.assertIn('data-booking-panel', html)       # inline calendar panel
        self.assertIn('data-booking-slots', html)
        self.assertNotIn("$150.00", html)               # a booking CTA is not a price button

    def test_email_renders_inline_form_from_lead_capture_fields(self):
        page = {"tenant_id": "t1", "page_id": "pg_1"}
        offer = {"offer_id": "off_1", "tenant_id": "t1", "items": [{"product_id": "p1"}],
                 "presentation": {"cta": {"type": "email", "label": "Get Help"}, "headline": "Acme"}}
        products = {"p1": {"product_id": "p1", "lead_capture": {
            "action": "capture_email_phone", "title": "Get help", "description": "We'll reach out.",
            "fields": [{"name": "email", "type": "email", "required": True},
                       {"name": "phone", "type": "phone", "required": False}]}}}
        html = render_email_cta(page, offer, offer_cta(offer), products, "https://api.example.com/dev")
        self.assertIn('data-cta-type="email"', html)
        self.assertIn('data-lead-form', html)
        self.assertIn('data-endpoint="https://api.example.com/dev/leads"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="phone"', html)
        self.assertIn('name="company_website"', html)          # honeypot present
        self.assertIn('data-consent="tenant_marketing"', html)  # dual opt-in
        self.assertIn('data-consent="platform_marketing"', html)
        self.assertNotIn("$150.00", html)


class CtaRegistryTests(unittest.TestCase):
    def test_registry_covers_every_cta_type_and_defaults_to_buy(self):
        from stripe_link.runtime.html import CTA_REGISTRY
        # No "download": removed 2026-09-17. A CTA type is what a BUTTON does, and the only thing that
        # ever produced one was an extension sniff on a bridge page's typed destination.
        for kind in ("buy", "call", "email", "external", "booking", "appointment"):
            self.assertIn(kind, CTA_REGISTRY)
            self.assertTrue(callable(CTA_REGISTRY[kind]["render"]))

    def test_there_is_no_download_cta_type(self):
        """A bridge page's button redirects, full stop (author, 2026-09-17).

        The type existed only because primaryCtaContract sniffed the destination's file extension -- and it
        was wrong twice: it overrode the tenant's button label with "Download", and the `download` attribute
        it emitted is ignored by browsers for CROSS-ORIGIN URLs, so it navigated like a link while claiming
        otherwise. Real file delivery is the page ribbon's download action, backed by an uploaded asset.
        Neither table held an offer with this type when it was removed.
        """
        from stripe_link.runtime.html import CTA_REGISTRY, CTA_TYPES

        self.assertNotIn("download", CTA_TYPES)
        self.assertNotIn("download", CTA_REGISTRY)
        # An offer that somehow carries it falls back to buy rather than rendering nothing.
        html = _render({"type": "download", "label": "Get the PDF", "target": "https://x/guide.pdf"})
        self.assertIn('data-cta-type="buy"', html)

    def test_appointment_reuses_the_booking_widget(self):
        html = _render({"type": "appointment", "label": "Book", "target": "svc_1"})
        self.assertIn("data-booking-widget", html)     # appointment IS a booking
        self.assertIn('data-service-id="svc_1"', html)
        # An unknown/absent cta type falls back to the buy renderer (offer_cta already normalizes to buy).
        html = _render({"type": "buy", "label": "Buy Now"})
        self.assertIn('data-cta-type="buy"', html)


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


class TheBookingCtaIsNotAFixedBottomBar(unittest.TestCase):
    """`.sl-checkout-cta` is `position:fixed;bottom:0` -- correct for a buy bar, wrong for this one.

    The booking CTA is not one button: it OPENS, into a slot grid two weeks deep plus three fields and a
    consent line. Pinned to the viewport the panel grew upward past the top of the screen, and scrolling
    moved the page behind it rather than the bar -- so the earliest times could not be clicked at all, and
    on the way past, the bar covered the price card and the trust badges (reported 2026-11-11).

    Email, call and external already opt out of the fixed rule. Booking was simply left off that list,
    which is the same shape of bug as the lead form "abomination" the comment beside it records: a copy
    defined by what it leaves out.
    """

    def _stylesheet(self):
        return "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)

    def test_booking_opts_out_of_the_fixed_bar(self):
        rule = next((line for line in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                     if "position:static" in line and ".sl-email-cta" in line), "")
        self.assertTrue(rule, "the static opt-out rule for inline CTAs is gone")
        self.assertIn(".sl-checkout-cta.sl-booking-cta", rule,
                      "a CTA that expands into a panel cannot be pinned to the viewport")

    def test_the_fixed_rule_still_applies_to_the_buy_bar(self):
        """The opt-out is a list of exceptions, not a removal: an ordinary buy CTA stays pinned."""
        base = next((line for line in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                     if line.strip().startswith(".sl-checkout-cta{")), "")
        self.assertIn("position:fixed", base)
        self.assertIn("bottom:0", base)

    def test_the_reserved_strip_goes_with_it(self):
        """`body` reserves 8rem for the fixed bar. With nothing pinned that is 8rem of nothing under a
        page that already ends in a form -- the same pairing the email CTA makes two lines above."""
        sheet = self._stylesheet()
        self.assertIn("body:has(.sl-booking-cta){padding-bottom:0}", sheet)
        self.assertIn("body:has(.sl-booking-cta) main{padding-bottom:4rem}", sheet)


if __name__ == "__main__":
    unittest.main()
