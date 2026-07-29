import json
import pathlib
import re
import unittest
from copy import deepcopy

from stripe_link.domain.funnels import post_purchase_plan
from stripe_link.runtime.html import RenderError, render_page
from stripe_link.runtime.publishing import render_funnel_step_html
from stripe_link.runtime.upsell_pages import (
    DEFAULT_UPSELL_SCAFFOLD,
    synthesize_downsell_carousel_page,
    synthesize_upsell_carousel_page,
    synthesize_upsell_page,
    upsell_scaffold,
)

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "schemas" / "examples"


def _load(name):
    return json.loads((EXAMPLES / name).read_text())


class UpsellScaffoldTests(unittest.TestCase):
    def test_defaults_when_no_override(self):
        self.assertEqual(upsell_scaffold({}), DEFAULT_UPSELL_SCAFFOLD)

    def test_page_override_wins_but_blanks_ignored(self):
        page = {"post_checkout": {"upsell_scaffold": {"headline": "One more thing", "subheadline": ""}}}
        scaffold = upsell_scaffold(page)
        self.assertEqual(scaffold["headline"], "One more thing")
        # A blank override does not wipe the default.
        self.assertEqual(scaffold["subheadline"], DEFAULT_UPSELL_SCAFFOLD["subheadline"])


class SynthesizeUpsellPageTests(unittest.TestCase):
    def setUp(self):
        self.product = _load("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}
        self.source_offer = {
            "offer_id": "offer_main", "tenant_id": "tenant_demo", "stripe_mode": "test",
            "presentation": {"brand": "JuniorBay"},
            "funnel": {"upsells": [{"product_id": self.product["product_id"], "price_id": "price_upsell_1bottle"}]},
        }
        self.source_page = {
            "page_id": "page_main", "tenant_id": "tenant_demo",
            "theme": {"template": "universal_bundle", "preset": "natural-calm"},
        }
        self.entry = post_purchase_plan(self.source_offer, self.products_by_id)["upsells"][0]

    def test_synthesized_offer_points_at_upsell_price(self):
        page, offer = synthesize_upsell_page(
            self.entry, source_page=self.source_page, source_offer=self.source_offer,
            scaffold=upsell_scaffold(self.source_page),
        )
        self.assertEqual(offer["items"], [{"product_id": "prod_creatine_gummies", "price_id": "price_upsell_1bottle", "quantity": 1}])
        self.assertEqual(page["theme"]["template"], "universal_bundle")
        self.assertEqual(page["theme"]["preset"], "natural-calm")  # inherits source theme
        self.assertEqual(page["offer_id"], offer["offer_id"])

    def test_accept_label_substitutes_the_upsell_price(self):
        _, offer = synthesize_upsell_page(
            self.entry, source_page=self.source_page, source_offer=self.source_offer,
            scaffold=upsell_scaffold(self.source_page),
        )
        self.assertEqual(offer["presentation"]["cta_label"], "Yes, I'll Take This Deal for $27.00")

    def test_downsell_is_baked_in_for_the_in_place_swap(self):
        # Give the upsell product a downsell price; the synthesized page carries it for the island's swap (§6).
        self.product["prices"].append({"price_id": "price_down", "context": "downsell", "unit_amount": 1200, "currency": "usd", "quantity": 1})
        self.source_offer["funnel"]["downsells"] = [{"product_id": self.product["product_id"], "price_id": "price_down"}]
        entry = post_purchase_plan(self.source_offer, self.products_by_id)["upsells"][0]
        page, offer = synthesize_upsell_page(
            entry, source_page=self.source_page, source_offer=self.source_offer, scaffold=upsell_scaffold(self.source_page),
        )
        html = render_page(
            page, offer, self.products_by_id, selected_prices={"prod_creatine_gummies": "price_upsell_1bottle"},
            page_type="funnel_step",
        )
        self.assertIn('data-downsell-price-id="price_down"', html)
        self.assertIn('data-downsell-amount="1200"', html)
        self.assertIn("Take This Deal for $12.00", html.replace("&#x27;", "'"))
        # The island swaps in place on decline/expiry rather than navigating to a separate downsell page.
        self.assertIn("swapToDownsell", html)
        self.assertIn("if (funnelDeclineOrExpire) funnelDeclineOrExpire();", html)
        # The swap updates the featured_price card (which replaced the price selector) and re-arms the countdown
        # so the downsell's own expiry advances the funnel (Phase 1c).
        self.assertIn("querySelector('.sl-featured-price')", html)
        self.assertIn("data-fp-compare-at=", html)
        self.assertIn("funnelCountdownRestarts.push", html)
        self.assertIn("funnelCountdownRestarts.forEach", html)
        # A last-chance note sits hidden above the CTA and the swap reveals it (the second-chance won't return).
        self.assertIn("data-downsell-note hidden", html)
        self.assertIn("This offer will not be shown again.", html)
        self.assertIn("dsNote.hidden = false", html)

    def test_funnel_pages_drop_the_legal_footer(self):
        # Post-purchase pages are one-click continuations of a completed checkout, not standalone sales pages, so
        # the Terms/Privacy/Refund footer is suppressed on both the upsell and thank-you steps (user request).
        entry = post_purchase_plan(self.source_offer, self.products_by_id)["upsells"][0]
        up_page, up_offer = synthesize_upsell_page(
            entry, source_page=self.source_page, source_offer=self.source_offer, scaffold=upsell_scaffold(self.source_page),
        )
        up = render_page(up_page, up_offer, self.products_by_id,
                         selected_prices={"prod_creatine_gummies": "price_upsell_1bottle"}, page_type="funnel_step")
        self.assertNotIn("Terms of Service", up)
        self.assertNotIn('class="sl-legal"', up)

    def test_no_downsell_attributes_when_product_has_no_downsell_price(self):
        entry = post_purchase_plan(self.source_offer, self.products_by_id)["upsells"][0]
        page, offer = synthesize_upsell_page(
            entry, source_page=self.source_page, source_offer=self.source_offer, scaffold=upsell_scaffold(self.source_page),
        )
        html = render_page(page, offer, self.products_by_id, selected_prices={"prod_creatine_gummies": "price_upsell_1bottle"}, page_type="funnel_step")
        self.assertNotIn("data-downsell-price-id", html)

    def test_renders_through_the_universal_bundle_pipeline(self):
        page, offer = synthesize_upsell_page(
            self.entry, source_page=self.source_page, source_offer=self.source_offer,
            scaffold=upsell_scaffold(self.source_page),
        )
        html = render_page(
            page, offer, self.products_by_id,
            selected_prices={"prod_creatine_gummies": "price_upsell_1bottle"},
            page_type="funnel_step",
        )
        self.assertIn("Wait! Before You Go", html)
        self.assertIn("Yes, I&#x27;ll Take This Deal for $27.00", html)
        # The price is baked into the accept label; the CTA must not re-append it ("… $27.00 - $27.00").
        self.assertNotIn("$27.00 - $27.00", html)
        self.assertIn('data-cta-hide-amount="true"', html)
        # The decline affordance the island reveals on a funnel step, carrying the scaffold's copy.
        self.assertIn("sl-decline-cta", html)
        self.assertIn("No, Thank You! Let&#x27;s Move On", html)
        # A funnel step is never indexed.
        self.assertIn("noindex", html)


def _carousel_entry(seq, amount, *, downsell_amount=None):
    """A post_purchase_plan-shaped upsell entry for carousel synthesis tests."""
    entry = {
        "sequence": seq, "product_id": f"prod_{seq}", "price_id": f"price_up_{seq}",
        "product": {"name": f"Product {seq}", "description": f"desc {seq}", "images": [f"img{seq}.jpg"]},
        "price": {"price_id": f"price_up_{seq}", "unit_amount": amount, "currency": "usd"},
        "downsell": None,
    }
    if downsell_amount is not None:
        entry["downsell"] = {
            "price_id": f"price_down_{seq}", "product": {"name": f"Product {seq}"},
            "price": {"price_id": f"price_down_{seq}", "unit_amount": downsell_amount, "currency": "usd"},
        }
    return entry


class SynthesizeCarouselTests(unittest.TestCase):
    def setUp(self):
        self.source_offer = {"offer_id": "offer_main", "tenant_id": "tenant_demo", "stripe_mode": "test"}
        self.source_page = {
            "page_id": "page_main", "tenant_id": "tenant_demo",
            "theme": {"template": "universal_bundle", "preset": "natural-calm"},
        }
        self.scaffold = upsell_scaffold({})
        # Four upsells => carousel; two of them carry a downsell price.
        self.plan = {"strategy": "carousel", "upsells": [
            _carousel_entry(1, 1000, downsell_amount=500),
            _carousel_entry(2, 2000),
            _carousel_entry(3, 3000, downsell_amount=1500),
            _carousel_entry(4, 4000),
        ]}

    def test_upsell_carousel_has_one_card_per_upsell_with_charge_data(self):
        page, offer = synthesize_upsell_carousel_page(
            self.plan, source_page=self.source_page, source_offer=self.source_offer, scaffold=self.scaffold,
        )
        self.assertEqual(page["page_id"], "page_main__upsell_carousel")
        self.assertEqual(page["theme"]["preset"], "natural-calm")  # inherits source theme
        self.assertEqual(offer["items"], [])  # section is self-contained; no per-card offer resolution
        section = page["sections"][0]
        self.assertEqual(section["type"], "post_purchase_carousel")
        self.assertEqual(section["surface"], "upsell")
        self.assertEqual(section["offer_id"], "offer_main")  # the one-click charge loads the MAIN offer
        self.assertEqual([c["sequence"] for c in section["cards"]], [1, 2, 3, 4])
        first = section["cards"][0]
        self.assertEqual(first["product_id"], "prod_1")
        self.assertEqual(first["price_id"], "price_up_1")
        self.assertEqual(first["amount"], 1000)
        self.assertEqual(first["add_label"], "Add for $10.00")

    def test_downsell_carousel_only_includes_products_with_a_downsell_price(self):
        result = synthesize_downsell_carousel_page(
            self.plan, source_page=self.source_page, source_offer=self.source_offer, scaffold=self.scaffold,
        )
        self.assertIsNotNone(result)
        page, _ = result
        self.assertEqual(page["page_id"], "page_main__downsell_carousel")
        section = page["sections"][0]
        self.assertEqual(section["surface"], "downsell")
        # Only sequences 1 and 3 carry a downsell price; their downsell (cheaper) amounts/prices are used.
        self.assertEqual([c["sequence"] for c in section["cards"]], [1, 3])
        self.assertEqual([c["price_id"] for c in section["cards"]], ["price_down_1", "price_down_3"])
        self.assertEqual(section["cards"][0]["amount"], 500)
        self.assertEqual(section["cards"][0]["add_label"], "Add for $5.00")

    def test_downsell_carousel_is_none_when_no_upsell_has_a_downsell(self):
        plan = {"strategy": "carousel", "upsells": [_carousel_entry(i, i * 1000) for i in range(1, 5)]}
        result = synthesize_downsell_carousel_page(
            plan, source_page=self.source_page, source_offer=self.source_offer, scaffold=self.scaffold,
        )
        self.assertIsNone(result)

    def test_carousel_renders_a_grid_of_one_click_adds_and_a_dismiss(self):
        page, offer = synthesize_upsell_carousel_page(
            self.plan, source_page=self.source_page, source_offer=self.source_offer, scaffold=self.scaffold,
        )
        html = render_page(
            page, offer, {}, api_base_url="https://api-dev.example.com", page_type="funnel_step",
        )
        # One card per upsell, each carrying the charge identity the island posts to /upsell/charge.
        self.assertEqual(html.count("sl-pp-card\" data-pp-card"), 4)
        self.assertIn('data-product-id="prod_1"', html)
        self.assertIn('data-price-id="price_up_1"', html)
        self.assertIn('data-sequence="1"', html)
        self.assertIn("Add for $10.00", html)
        # Section container carries the charge context; single dismiss present.
        self.assertIn('data-section-type="post_purchase_carousel"', html)
        self.assertIn('data-offer-id="offer_main"', html)
        self.assertIn('data-api-base-url="https://api-dev.example.com"', html)
        self.assertIn("data-pp-dismiss", html)
        self.assertIn("No thanks, I&#x27;m good!", html)
        # After adding any card the island relabels the dismiss to this (carried as a data attr).
        self.assertIn('data-pp-proceed-label="Continue to the next step"', html)
        # Island wiring: per-card charge + dismiss advances the funnel; a funnel step is never indexed.
        self.assertIn("/upsell/charge", html)
        self.assertIn("post-checkout/next", html)
        self.assertIn("noindex", html)


class RenderFunnelStepPreviewTests(unittest.TestCase):
    """render_funnel_step_html (SALES_FUNNELS.md P3.5) — the builder's per-step Live Preview. It mirrors the
    publish-time synthesis, so a step renders the same page a buyer would see."""

    def setUp(self):
        self.product = _load("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}
        self.offer = {
            "offer_id": "offer_main", "tenant_id": "tenant_demo", "stripe_mode": "test",
            "presentation": {"brand": "JuniorBay"},
            "funnel": {"upsells": [{"product_id": self.product["product_id"], "price_id": "price_upsell_1bottle"}]},
        }
        self.page = {
            "page_id": "page_main", "tenant_id": "tenant_demo", "theme": {"template": "universal_bundle"},
            "post_checkout": {
                "thank_you_page": {"page_id": "ty", "headline": "Custom Thanks", "message": "See you soon."},
                "upsell_scaffold": {"headline": "Wait Custom Upsell", "accept_label": "Grab it for {{ upsell_price }}"},
            },
        }

    def test_thank_you_step_renders_editable_copy(self):
        html = render_funnel_step_html("thank_you", self.page, self.offer, self.products_by_id)
        self.assertIn("Custom Thanks", html)
        self.assertIn("See you soon.", html)
        self.assertNotIn("Terms of Service", html)  # post-purchase page drops the legal footer

    def test_upsell_step_renders_scaffold_copy_and_substituted_price(self):
        html = render_funnel_step_html("upsell:0", self.page, self.offer, self.products_by_id)
        self.assertIn("Custom Upsell", html)
        self.assertTrue(re.search(r"Grab it for \$", html), "the {{ upsell_price }} token is filled with the price")

    def test_upsell_page_shows_the_product_description_and_gallery(self):
        # Phase 1: an unfamiliar upsell product gets its own context — a description block + the full image
        # gallery (not one image) — derived from the product, no per-upsell editing needed.
        product = dict(self.product)
        product["description"] = "5000mg pure creatine per serving. Great for recovery."
        product["images"] = ["https://img/a.jpg", "https://img/b.jpg", "https://img/c.jpg"]
        html = render_funnel_step_html("upsell:0", self.page, self.offer, {product["product_id"]: product})
        self.assertIn('data-section-type="content_block"', html)   # description renders as its own block
        self.assertIn("sl-content-blocks--centered", html)         # centered on the upsell page (not left-indented)
        self.assertIn("Great for recovery", html)
        self.assertIn("https://img/b.jpg", html)                   # gallery, not just the first image
        self.assertIn("https://img/c.jpg", html)

    def test_upsell_page_shows_the_products_reviews(self):
        # Phase 1b: the upsell product's own reviews render on its page (social proof for a cold upsell). Keyed
        # by product, so only the upsell product's show; passing none renders no block.
        pid = self.product["product_id"]
        reviews = [{"review_id": "r1", "tenant_id": "t", "target": {"type": "product", "id": pid},
                    "rating": 5, "author": "Alex", "body": "Best creatine ever!", "status": "approved", "source": "first_party"}]
        html = render_funnel_step_html("upsell:0", self.page, self.offer, {pid: self.product}, reviews=reviews)
        self.assertIn('data-section-type="reviews"', html)
        self.assertIn("Best creatine ever!", html)
        self.assertNotIn('data-section-type="reviews"',
                         render_funnel_step_html("upsell:0", self.page, self.offer, {pid: self.product}))

    def test_upsell_page_shows_the_price_prominently(self):
        # Phase 1c: the upsell price is in the 'upsell' context, which offer_price_selector filters out, so a
        # dedicated featured_price card carries the amount + its label — not only the CTA button.
        html = render_funnel_step_html("upsell:0", self.page, self.offer, self.products_by_id)
        self.assertIn('data-section-type="featured_price"', html)
        self.assertNotIn('data-section-type="offer_price_selector"', html)  # empty for upsell context; replaced
        self.assertIn("Yours for only", html)
        self.assertIn("$27.00", html)
        self.assertNotIn('class="sl-featured-price-pills"', html)  # no regular price on the fixture, so no savings pill

    def test_upsell_price_shows_savings_when_a_regular_price_is_higher(self):
        pid = self.product["product_id"]
        product = deepcopy(self.product)
        for price in product["prices"]:
            if price["price_id"] == "price_upsell_1bottle":
                price["compare_at_unit_amount"] = 6500  # regular $65 vs upsell $27 -> save 58%
        html = render_funnel_step_html("upsell:0", self.page, self.offer, {pid: product})
        self.assertIn("$65.00", html)
        self.assertIn("You save 58%", html)
        # The savings badge is a toggle: with it off, neither the regular price nor the savings pill show.
        page = deepcopy(self.page)
        page["post_checkout"]["upsell_scaffold"]["savings_badge"] = False
        off = render_funnel_step_html("upsell:0", page, self.offer, {pid: product})
        self.assertNotIn('class="sl-featured-price-pills"', off)  # ("You save " also appears in the downsell swap JS)
        self.assertNotIn("$65.00", off)

    def test_upsell_out_of_range_raises(self):
        with self.assertRaises(RenderError):
            render_funnel_step_html("upsell:5", self.page, self.offer, self.products_by_id)

    def test_unknown_step_raises(self):
        with self.assertRaises(RenderError):
            render_funnel_step_html("nope", self.page, self.offer, self.products_by_id)

    def test_preview_matches_published_bytes_for_thank_you(self):
        # The preview IS the published renderer: the thank-you step equals what publish would synthesize+render.
        from stripe_link.runtime.upsell_pages import synthesize_thank_you_page
        ty_page, ty_offer = synthesize_thank_you_page(self.page, self.offer)
        published = render_page(ty_page, ty_offer, {}, robots="noindex,nofollow", page_type="thank_you")
        preview = render_funnel_step_html("thank_you", self.page, self.offer, self.products_by_id)
        self.assertEqual(preview, published)


class ThankYouExtrasTests(unittest.TestCase):
    """Thank-you page extras (SALES_FUNNELS.md P3.5 Phase 2, stripe-cart parity): celebration burst, the
    "What's Next?" cards, footer, home link, download."""

    def _offer(self):
        return {"offer_id": "o", "tenant_id": "t", "stripe_mode": "test", "presentation": {"brand": "Axel"}, "funnel": {"upsells": []}}

    def _render(self, thank_you):
        page = {"page_id": "p", "tenant_id": "t", "theme": {"template": "universal_bundle"},
                "post_checkout": {"thank_you_page": {"page_id": "ty", **thank_you}}}
        return render_funnel_step_html("thank_you", page, self._offer(), {})

    # Assert on the rendered ELEMENT (data-section-type) — the CSS class names always appear in the <style>.
    def test_defaults_show_celebration_and_next_steps(self):
        html = self._render({})
        self.assertIn('data-section-type="celebration"', html)
        self.assertIn('data-section-type="next_steps"', html)
        self.assertIn("Check Your Email", html)      # default card
        self.assertIn("🎉", html)                     # default headline icon

    def test_toggles_off_remove_sections(self):
        html = self._render({"enable_celebration": False, "enable_next_steps": False})
        self.assertNotIn('data-section-type="celebration"', html)
        self.assertNotIn('data-section-type="next_steps"', html)

    def test_custom_cards_and_title(self):
        html = self._render({"next_steps_title": "Here's the plan",
                             "next_steps": [{"icon": "⭐", "title": "One thing", "desc": "Do it"}]})
        self.assertIn("One thing", html)         # card title (escaped verbatim, not title-cased)
        self.assertNotIn("Check Your Email", html)

    def test_footer_home_and_download(self):
        html = self._render({"enable_footer": True, "footer_message": "Talk soon here.",
                             "show_home_button": True, "home_button_text": "Go home",
                             "enable_download": True, "download_url": "https://x/g.pdf", "download_button_text": "Get it"})
        self.assertIn('data-section-type="thank_you_footer"', html)
        self.assertIn("Talk soon here.", html)
        self.assertIn("Go home", html)
        self.assertIn("https://x/g.pdf", html)
        self.assertIn("Get it", html)

    def test_download_without_url_is_omitted(self):
        html = self._render({"enable_download": True, "download_url": ""})
        self.assertNotIn("sl-ty-download\"", html)   # the <a>, not the always-present CSS rule


if __name__ == "__main__":
    unittest.main()
