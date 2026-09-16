"""What a lead-capture PAGE actually looks like to a visitor.

The author's verdict on the rendered result, 2026-09-15: "an abomination". Six separate defects, none of
them in the composition (which had the section order right all along) and all of them somewhere else — the
stylesheet, the store, the page seeder and the consent copy. Kept together here because they only show up
together, on the page.
"""
import json
import pathlib
import re
import unittest

from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
PRODUCTS_STORE = (ROOT / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")
CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)


def _offer():
    return {
        "offer_id": "off_1", "tenant_id": "t1", "status": "active", "stripe_mode": "test",
        "product_intent": "lead_gen", "lead_capture_action": "capture_email",
        "items": [{"product_id": "prod_lead", "price_id": "pr", "quantity": 1}],
        "presentation": {"headline": "2026 Guide to Junk Food Restaurants",
                         "subheadline": "My comprehensive list of fast food restaurants.",
                         "cta": {"type": "email", "label": "Get the guide"}},
    }


def _products():
    return {"prod_lead": {
        "product_id": "prod_lead", "tenant_id": "t1", "name": "2026 Guide to Junk Food Restaurants",
        "product_intent": "lead_gen",
        "lead_capture": {"action": "capture_email", "title": "Get the guide",
                         "description": "We'll email it to you.",
                         "fields": [{"name": "email", "type": "email", "required": True}]},
        # A lead product still carries the free price the store writes for it; the resolver needs one.
        "prices": [{"price_id": "pr", "currency": "usd", "quantity": 1, "unit_amount": 0,
                    "pricing_model": "one_time", "context": "standard"}],
        "default_price_id": "pr",
    }}


def _page():
    return {
        "page_id": "page_1", "tenant_id": "t1", "offer_id": "off_1", "name": "Guide", "status": "draft",
        "route": {"slug": "guide"}, "theme": {"template": "universal_bundle", "preset": "clean-slate"},
        "sections": [
            {"id": "brand", "type": "brand_label", "enabled": True},
            {"id": "hero", "type": "hero", "headline": "2026 Guide to Junk Food Restaurants",
             "subheadline": "My comprehensive list of fast food restaurants."},
            {"id": "checkout-cta", "type": "checkout_cta", "label": "Get the guide"},
            {"id": "legal-footer", "type": "legal_footer", "copyright": "© {{current_year}} All rights reserved."},
        ],
    }


def _render(site=None):
    return html_module.render_page(_page(), _offer(), _products(), site=site)


class FooterPositionTests(unittest.TestCase):
    """The footer rendered under the HERO with the form pinned to the bottom of the viewport.

    Not an ordering bug — the DOM order was right. `.sl-checkout-cta` is `position: fixed; bottom: 0`, which
    is correct for a sales page where the CTA is a sticky buy bar riding over the content. On a lead page the
    CTA *is* the form, so being fixed took the page's whole point out of the document flow and let the footer
    float up to meet the hero.
    """

    def test_the_lead_form_is_in_the_flow(self):
        rule = [line for line in CSS.splitlines() if ".sl-email-cta{" in line]
        self.assertTrue(rule, "no rule returns the lead CTA to the flow")
        self.assertIn("position:static", rule[0])

    def test_the_sales_bar_is_still_fixed(self):
        # Narrowed to the lead variant, not removed: every other page still wants the sticky buy bar.
        rule = [line for line in CSS.splitlines() if ".sl-checkout-cta{" in line][0]
        self.assertIn("position:fixed", rule)

    def test_the_strip_reserved_for_a_fixed_bar_goes_with_it(self):
        # body/main carry bottom padding so the fixed bar never covers content. In flow it is just a screen
        # of trailing white space.
        self.assertIn("body:has(.sl-email-cta){padding-bottom:0}", CSS)

    def test_the_rendered_order_puts_the_footer_last(self):
        markup = _render()
        body = markup.split("<body", 1)[1]
        cta = body.index('data-section-type="checkout_cta"')
        footer = body.index('class="sl-legal"')
        self.assertLess(cta, footer, "the form must come before the footer")


class ConsentTests(unittest.TestCase):
    def test_the_tenant_list_is_named_after_the_business(self):
        # It read "Join capture email's mailing list" — the OFFER's name, which is not a thing anyone can
        # consent to. The business name is the same one the brand label at the top of the page shows.
        markup = _render(site={"organization": {"name": "Poliaxis Nutrition"}})
        self.assertIn("Join Poliaxis Nutrition&#x27;s mailing list.", markup)

    def test_it_falls_back_to_the_offer_brand_then_to_us(self):
        markup = _render()   # no Site, so no business name
        self.assertIn("mailing list.", markup)
        self.assertNotIn("Join &#x27;s mailing list.", markup)

    def test_both_boxes_start_ticked(self):
        """Author's instruction, 2026-09-15. Recorded as a REVERSAL, not an oversight.

        plans/LEAD_CAPTURE.md specified opt-in, and GDPR recital 32 says in terms that "silence, pre-ticked
        boxes or inactivity" do not constitute consent. Both boxes stay visible, labelled and un-tickable by
        the visitor, and the chosen state is still recorded per lead — what changed is the default.
        """
        markup = _render()
        self.assertEqual(markup.count("checked data-consent-text"), 2)

    def test_the_two_opt_ins_stay_independent(self):
        # The tenant's list and Junior Bay's are separate decisions and separate records.
        markup = _render()
        self.assertIn('data-consent="tenant_marketing"', markup)
        self.assertIn('data-consent="platform_marketing"', markup)


class HeroCopyTests(unittest.TestCase):
    """The hero introduced the page as a FORM instead of as the thing on offer."""

    def test_the_seeder_never_uses_the_lead_actions_words(self):
        # "Collect the visitor's email address." describes the mechanism. It was the subheadline fallback,
        # so every capture page whose offer had no subheadline announced its own plumbing.
        self.assertNotIn("leadAction?.description", BUILDER)

    def test_the_subheadline_falls_back_to_the_product(self):
        block = BUILDER.split("function pageSections(", 1)[1][:1400]
        self.assertIn("subheadline: offerDescription(offer)", block)

    def test_the_seo_description_is_not_the_headline_again(self):
        block = BUILDER.split("function buildPageDocument(", 1)[1][:1600]
        self.assertIn("description: offer.presentation?.subheadline || offerDescription(offer)", block)

    def test_the_rendered_hero_carries_the_products_words(self):
        markup = _render()
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)
        self.assertIn("My comprehensive list of fast food restaurants.", markup)


class HeroImageTests(unittest.TestCase):
    def test_a_lead_product_keeps_its_images(self):
        """They were emptied because a lead magnet is "never sold".

        But the picture is what the squeeze page shows above the form, so the hero_media section had nothing
        to render and every lead page was text on white.
        """
        self.assertNotIn("images: isLeadGen ? [] : images", PRODUCTS_STORE)
        self.assertIn("\n    images,\n", PRODUCTS_STORE)

    def test_the_rest_of_the_lead_gen_stripping_is_untouched(self):
        # Prices, shipping and variants are genuinely meaningless on something never sold — only the IMAGES
        # were wrong to drop.
        self.assertIn("isLeadGen ? [freeLeadPrice(", PRODUCTS_STORE)
        self.assertIn("requires_shipping: isPhysical && !isLeadGen", PRODUCTS_STORE)


if __name__ == "__main__":
    unittest.main()
