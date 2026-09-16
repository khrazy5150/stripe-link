"""The click-to-call page: inbound calls, and the things that page alone needs.

Author, 2026-09-16, working through the lead shapes one at a time. Two of these were bugs nobody had
reported because the page LOOKED plausible: the phone number rendered white on white, and the CTA left the
document flow. The rest is the page earning the call.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.composition import excluded_sections
from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))


def _render(badges=None, phone="+12065654418"):
    product = {
        "product_id": "p1", "tenant_id": "t1", "name": "Emergency Water Damage",
        "description": "For 24-hour service water damage", "product_intent": "lead_gen",
        "lead_capture": {"action": "call_number", "title": "T", "description": "D",
                         "target": {"type": "phone", "value": phone}},
        "prices": [{"price_id": "pr", "currency": "usd", "quantity": 1, "unit_amount": 0,
                    "pricing_model": "one_time", "context": "standard"}],
        "default_price_id": "pr",
    }
    offer = {
        "offer_id": "o1", "tenant_id": "t1", "status": "active", "stripe_mode": "test",
        "product_intent": "lead_gen", "lead_capture_action": "call_number",
        "items": [{"product_id": "p1", "price_id": "pr", "quantity": 1}],
        "presentation": {"headline": product["name"], "subheadline": product["description"],
                         "cta": {"type": "call", "label": "Call Now", "target": phone}},
    }
    sections = [{"id": "b", "type": "brand_label"}, {"id": "h", "type": "hero"}]
    if badges:
        sections.append({"id": "tb", "type": "trust_badges", "enabled": True, "badges": badges})
    sections += [{"id": "c", "type": "checkout_cta"},
                 {"id": "lf", "type": "legal_footer", "copyright": "(c)"}]
    page = {"page_id": "pg", "tenant_id": "t1", "offer_id": "o1", "name": "N", "status": "draft",
            "route": {"slug": "s"}, "theme": {"template": "universal_bundle", "preset": "clean-slate"},
            "sections": sections}
    return html_module.render_page(page, offer, {"p1": product})


class NumberLegibilityTests(unittest.TestCase):
    def test_the_number_is_not_painted_in_the_cta_text_colour(self):
        """It was `--sl-cta-text`, which is white BY DESIGN -- the colour of text sitting ON the CTA scrim.

        The moment the CTA rendered in the document flow, the number was white on white. It had been there
        the whole time; the page just looked sparse rather than broken.
        """
        rule = [line for line in CSS.splitlines() if ".sl-call-number{" in line][0]
        self.assertNotIn("var(--sl-cta-text)", rule)
        self.assertIn("color:var(--sl-price-amount)", rule)

    def test_the_number_is_shown_and_dialable(self):
        markup = _render()
        self.assertIn("+12065654418", markup)
        self.assertIn('href="tel:+12065654418"', markup)


class CtaInFlowTests(unittest.TestCase):
    """Every LEAD cta is page CONTENT, not a buy bar riding over it."""

    def test_the_call_and_bridge_ctas_join_the_email_one_in_the_flow(self):
        rule = [line for line in CSS.splitlines()
                if ".sl-email-cta" in line and "position:static" in line][0]
        self.assertIn(".sl-call-cta", rule)
        self.assertIn(".sl-external-cta", rule)

    def test_the_footer_ends_the_page(self):
        body = _render().split("<body", 1)[1]
        self.assertLess(body.index('data-cta-type="call"'), body.index('class="sl-legal"'))

    def test_the_sales_bar_is_still_fixed(self):
        self.assertIn("position:fixed", [l for l in CSS.splitlines() if ".sl-checkout-cta{" in l][0])


class TrustBadgeTests(unittest.TestCase):
    """The one lead shape where the visitor is about to phone a stranger about something urgent.

    There is no price, no checkout and no cart to reassure them, so badges are the only slot for
    licensed / insured / 24-hour -- which is exactly what that decision turns on (author, 2026-09-16).
    """

    def test_call_and_bridge_pages_may_show_badges(self):
        for key in ("lead_call", "lead_bridge"):
            self.assertNotIn("trust_badges", excluded_sections(key), key)
            self.assertIn("trust_badges", RULES["offer_types"][key]["sections"], key)

    def test_the_other_lead_shapes_still_exclude_them(self):
        # A capture page has a form doing the persuading, and a link hub sells nothing at all.
        for key in ("lead_capture", "lead_social"):
            self.assertIn("trust_badges", excluded_sections(key), key)

    def test_they_render_above_the_call(self):
        markup = _render(badges=[{"enabled": True, "emoji": "🕒", "label": "24-hour response"},
                                 {"enabled": True, "emoji": "🛡️", "label": "Licensed & insured"}])
        body = markup.split("<body", 1)[1]
        self.assertIn("24-hour response", body)
        self.assertLess(body.index("24-hour response"), body.index('data-cta-type="call"'))

    def test_a_page_with_no_badges_renders_none(self):
        # Nothing is invented on the tenant's behalf: these are claims about THEIR business.
        self.assertNotIn('data-section-type="trust_badges"', _render())


class CtaLegendTests(unittest.TestCase):
    def test_the_legend_says_inbound(self):
        """"Click-to-call" reads as the OPPOSITE to anyone who has just configured a phone CAPTURE.

        One collects a number so the tenant rings the visitor; the other hands the visitor a number to ring.
        The author lost time to exactly that.
        """
        self.assertIn('call: "Call — inbound phone calls"', BUILDER)
        self.assertIn("the visitor calls YOU", BUILDER)


class OnePhoneControlTests(unittest.TestCase):
    """The number is asked for ONCE, with the same control the Profile screen uses."""

    def test_the_picker_no_longer_asks_for_a_destination(self):
        # It was asked in the picker AND on the step that follows -- two phone controls to build, and two
        # to keep agreeing.
        picker = PRODUCTS.split("Choose a lead capture action", 1)[1].split("</footer>", 1)[0]
        self.assertNotIn("draftLeadAction.target", picker)

    def test_the_step_uses_the_shared_e164_control(self):
        self.assertIn('import PhoneInput from "./PhoneInput.vue"', PRODUCTS)
        self.assertIn('<PhoneInput v-if="leadTargetIsPhone" v-model="form.lead_capture.target" />', PRODUCTS)

    def test_a_url_action_still_gets_a_plain_box(self):
        # PhoneInput is for phones; a bridge page's destination is a URL.
        self.assertIn('leadTargetPlaceholderFor(form.lead_capture.action)', PRODUCTS)
        self.assertIn('if (action === "external_url") return "https://example.com"', PRODUCTS)

    def test_confirming_the_same_action_keeps_what_was_typed(self):
        """Re-opening the picker must not wipe the number entered on the step.

        Switching to a DIFFERENT action does drop it, because a phone number is not a URL.
        """
        apply_block = PRODUCTS.split("function applyLeadAction", 1)[1].split("\n}", 1)[0]
        self.assertIn("const sameAction = form.value.lead_capture.action === draftLeadAction.value.action",
                      apply_block)
        self.assertIn("sameAction ? form.value.lead_capture.target : \"\"", apply_block)


if __name__ == "__main__":
    unittest.main()
