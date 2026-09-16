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

    def test_neither_box_starts_ticked(self):
        """Consent needs an affirmative action, and this is the test that keeps it that way.

        GDPR recital 32 says in terms that "silence, pre-ticked boxes or inactivity" do not constitute
        consent; Art. 4(11) requires "a clear affirmative action"; CJEU Planet49 (C-673/17) settled it. The
        platform box is weaker still — third-party marketing is never covered by the ePrivacy soft opt-in
        that can otherwise excuse a tenant's own list.

        Briefly shipped pre-ticked on 2026-09-15 and reverted the same day. This test is the guard.
        """
        markup = _render()
        self.assertNotIn("checked", markup.split("sl-lead-form", 1)[1].split("</form>", 1)[0])

    def test_the_chosen_state_is_still_recorded(self):
        # Unticking the default must not quietly stop recording what the visitor actually chose.
        script = _render()
        self.assertIn("granted: box.checked", script)

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

    def test_a_new_page_stores_no_hero_copy_at_all(self):
        # The renderer derives it, so copying it in only freezes the page at what the offer said the day it
        # was made. That is how a lead page kept announcing "Capture Email" after its offer had a real one.
        block = BUILDER.split("function pageSections(", 1)[1][:1400]
        hero = block.split('type: "hero"', 1)[1].split("},", 1)[0]
        self.assertNotIn("headline:", hero)
        self.assertNotIn("subheadline:", hero)

    def test_the_builder_stores_only_what_the_tenant_changed(self):
        # Same rule the SEO fields already follow. A typed headline that matches the derived one is not an
        # edit, and storing it would silently opt the page out of every later correction to the offer.
        self.assertIn("function heroOverride(typed, derived)", BUILDER)
        build = BUILDER.split('if (sectionVisible("hero")) sections.push(', 1)[1][:1000]
        self.assertIn("heroOverride(", build)
        self.assertIn("offerHeadline(builderOffer.value)", build)
        self.assertIn("offerDescription(builderOffer.value)", build)

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


class HeroDerivationTests(unittest.TestCase):
    """A page that stores no hero copy DERIVES it, the way the picture already did.

    `hero_media_images` has always fallen back to the offer and then the product. The words had no such
    fallback, so whatever a page was seeded with was what it showed forever — the freezing problem this
    codebase keeps rediscovering, and the reason the brand label stopped storing its own text.
    """

    def _render_without(self, *fields):
        page = _page()
        for section in page["sections"]:
            if section["type"] == "hero":
                for field in fields:
                    section.pop(field, None)
        return html_module.render_page(page, _offer(), _products())

    def test_the_headline_falls_back_to_the_offer_then_the_product(self):
        markup = self._render_without("headline", "subheadline")
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)
        self.assertIn("My comprehensive list of fast food restaurants.", markup)

    def test_the_page_still_wins_when_it_says_something(self):
        # A tenant who typed a headline meant it; derivation is only for silence.
        markup = html_module.render_page(_page(), _offer(), _products())
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S).group(1)
        self.assertIn("2026 Guide to Junk Food Restaurants", h1)

    def test_it_falls_all_the_way_to_the_product(self):
        # An offer written before `presentation` existed.
        offer = _offer()
        offer["presentation"] = {"cta": {"type": "email", "label": "Get the guide"}}
        page = _page()
        for section in page["sections"]:
            if section["type"] == "hero":
                section.pop("headline", None)
                section.pop("subheadline", None)
        markup = html_module.render_page(page, offer, _products())
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)

    def test_the_forms_own_description_is_never_the_subheadline(self):
        # lead_capture.description describes the FORM. The product's words are what belong under the
        # headline; this is the same leak as the seeder's, one layer down.
        markup = self._render_without("headline", "subheadline")
        hero = markup.split('class="sl-hero"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("We&#x27;ll email it to you.", hero)

    def test_the_picture_derives_from_the_product_too(self):
        # Already true, and pinned here because the two halves are the same rule: an existing page shows the
        # image as soon as the product HAS one, with no edit to the page.
        products = _products()
        products["prod_lead"]["images"] = ["https://images.juniorbay.com/products/abc/medium.webp"]
        page = _page()
        page["sections"].insert(1, {"id": "hero-media", "type": "hero_media", "images": []})
        markup = html_module.render_page(page, _offer(), products)
        self.assertIn("products/abc", markup)



if __name__ == "__main__":
    unittest.main()
