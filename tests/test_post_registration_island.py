"""The island that carries the post-registration offer (plans/POST_REGISTRATION_OFFER.md P2–P3).

Three things have to hold, and each has a way of failing quietly:

* It must render HIDDEN. A sales pitch painted on load competes with the registration and suppresses the
  thing the page exists for.
* The claim must be an ordinary Checkout href, never the one-click charge. There is no card at this point
  in the funnel, so a one-click button would quote a price and then fail.
* It must disappear entirely when nothing is for sale, so a webinar page with no add-on composes exactly
  as it did before this element existed.
"""
import unittest

from stripe_link.domain.composition import ELEMENTS, element_channel
from stripe_link.runtime.html import SECTION_REGISTRY, render_post_registration_offer

PAGE = {"page_id": "page_webinar", "tenant_id": "ten_1", "stripe_mode": "test"}
OFFER = {
    "offer_id": "off_webinar",
    "tenant_id": "ten_1",
    "stripe_mode": "test",
    "product_intent": "lead_gen",
    "lead_capture_action": "register_event",
    "purchase_opportunities": [
        {"stage": "post_registration", "product_id": "prod_kit", "price_id": "price_kit_reg",
         "quantity": 1, "placement": {"surface": "upsell"}},
    ],
}
PRODUCTS = {"prod_kit": {
    "product_id": "prod_kit", "name": "Prep Kit", "description": "Walk in already prepared.",
    "prices": [
        {"price_id": "price_kit_reg", "context": "post_registration", "unit_amount": 2700,
         "compare_at_unit_amount": 14700, "currency": "usd"},
    ],
}}
CHECKOUT = "https://pay.example.com/checkout"


def render(offer=OFFER, products=PRODUCTS, section=None):
    return render_post_registration_offer(section or {}, PAGE, offer, products, CHECKOUT)


class TheIslandTests(unittest.TestCase):
    def test_it_renders_hidden(self):
        markup = render()
        self.assertIn("data-pr-offer hidden", markup)

    def test_it_names_the_product_and_its_registration_price(self):
        markup = render()
        self.assertIn("Prep Kit", markup)
        self.assertIn("$27.00", markup)

    def test_the_anchor_is_the_products_own_compare_at(self):
        # Struck through only because the product stores it. A number invented for the page is the part of
        # this pattern that draws a card-network complaint.
        self.assertIn("<s>$147.00</s>", render())

    def test_no_anchor_when_there_is_nothing_to_compare(self):
        products = {"prod_kit": {**PRODUCTS["prod_kit"], "prices": [
            {"price_id": "price_kit_reg", "context": "post_registration", "unit_amount": 2700,
             "currency": "usd"},
        ]}}
        self.assertNotIn("<s>", render(products=products))

    def test_nothing_renders_when_nothing_is_for_sale(self):
        products = {"prod_kit": {**PRODUCTS["prod_kit"], "prices": [
            {"price_id": "price_std", "context": "standard", "unit_amount": 14700, "currency": "usd"},
        ]}}
        self.assertEqual(render(products=products), "")

    def test_tenant_copy_overrides_the_defaults(self):
        # The heading goes through render_headline_markup like every other h2, which title-cases it.
        markup = render(section={"headline": "Before you go", "decline_label": "Skip"})
        self.assertIn("Before You Go", markup)
        self.assertIn("Skip", markup)


class TheClaimIsACheckoutLinkTests(unittest.TestCase):
    def test_it_is_an_anchor_with_a_real_href(self):
        # A real link, so it works with no JS and reads as a link to a crawler.
        markup = render()
        self.assertIn('<a class="sl-cta sl-pr-claim" href="https://pay.example.com/checkout', markup)

    def test_the_href_carries_the_registration_price_not_the_standard_one(self):
        self.assertIn("price_id=price_kit_reg", render())

    def test_the_href_carries_the_pages_stripe_mode(self):
        self.assertIn("mode=test", render())
        live = {**OFFER, "stripe_mode": "live"}
        self.assertIn("mode=live", render(offer=live))

    def test_it_never_posts_to_the_one_click_charge(self):
        markup = render()
        self.assertNotIn("data-pp-add", markup)
        self.assertNotIn("upsell/charge", markup)


class CompositionKnowsAboutItTests(unittest.TestCase):
    def test_the_element_exists_and_paints_markup(self):
        self.assertIn("post_registration_offer", ELEMENTS)
        self.assertEqual(element_channel("post_registration_offer"), "body")

    def test_a_webinar_page_seeds_it(self):
        import json
        import pathlib

        rules = json.loads(
            (pathlib.Path(__file__).resolve().parents[1]
             / "src/stripe_link/composition_rules.json").read_text()
        )
        self.assertIn("post_registration_offer", rules["offer_types"]["lead_event"]["sections"])

    def test_the_renderer_is_registered(self):
        self.assertIn("post_registration_offer", SECTION_REGISTRY)


if __name__ == "__main__":
    unittest.main()
