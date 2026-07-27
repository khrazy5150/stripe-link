import json
import pathlib
import unittest

from stripe_link.domain.funnels import post_purchase_plan
from stripe_link.runtime.html import render_page
from stripe_link.runtime.upsell_pages import (
    DEFAULT_UPSELL_SCAFFOLD,
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


if __name__ == "__main__":
    unittest.main()
