"""Offer-less page compositions (plans/OFFERLESS_PAGES_IN_BUILDER.md P1).

A storefront homepage, a category page and a store profile carry no offer, so `composition_key` -- which
reads an offer -- used to fall through to `single`. Under `single` the price selector and the Buy CTA are
visible. The renderer survived that because `compose_page` only ever FILTERS `page.sections`; the builder
would not, because it CONSTRUCTS sections from builder state gated on the same predicate. These tests pin
the shapes so routing those pages through the builder cannot put a Buy button on a page with nothing to
sell.
"""

import unittest

from stripe_link.domain.composition import (
    OFFERLESS_COMPOSITIONS,
    compose_page,
    composition_key,
    excluded_sections,
    is_section_visible,
    offerless_composition,
    page_composition_key,
)

# Everything that only makes sense when the page has something to sell, split by WHICH mechanism keeps it
# off. The split is not cosmetic -- `is_section_visible` short-circuits on ungoverned keys:
#
#     if key not in _GOVERNED: return True        # <- excludes never consulted
#     if key in excluded_sections(...): return False
#
# So for a GOVERNED section an exclusion is enforced at render, outranking both tenant overrides and goal
# packs. For an UNGOVERNED one it is enforced only in the builder's Add-content menu, which is the sole way
# such a section can enter a document in the first place. That asymmetry predates this work (`lead_social`
# excludes ungoverned elements on the same terms) and is deliberately NOT changed here: making exclusions
# bite at render would silently drop sections from link-in-bio pages that already store them.
TRANSACTIONAL_GOVERNED = (
    "offer_price_selector", "checkout_cta", "trust_badges", "refund_policy", "shipping",
)
TRANSACTIONAL_ADDABLE = (
    "product_details", "price_highlight", "product_carousel", "related_products", "reviews",
)

STOREFRONT_PAGE = {
    "page_id": "pg_sf",
    "sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store"},
        {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1"},
    ],
}
CATEGORY_PAGE = {
    "page_id": "pg_cat",
    "sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Widgets"},
        {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c2", "heading": "Widgets"},
    ],
}
PROFILE_PAGE = {
    "page_id": "pg_pf",
    "sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "About our store"},
        {"id": "seller-profile", "type": "seller_profile", "heading": "About our store"},
    ],
}
OFFER = {
    "offer_id": "off_1", "offer_type": "single",
    "items": [{"product_id": "p1", "quantity": 1}],
}


class OfferlessShapeTests(unittest.TestCase):
    def test_each_offerless_page_resolves_to_its_own_composition(self):
        self.assertEqual(offerless_composition(STOREFRONT_PAGE), "storefront")
        # A category page composes as `storefront` deliberately: the two shapes' section lists are
        # identical, so they share one key rather than duplicating it.
        self.assertEqual(offerless_composition(CATEGORY_PAGE), "storefront")
        self.assertEqual(offerless_composition(PROFILE_PAGE), "store_profile")

    def test_an_ordinary_offer_page_has_no_offerless_shape(self):
        page = {"sections": [{"type": "hero"}, {"type": "checkout_cta"}]}
        self.assertEqual(offerless_composition(page), "")
        self.assertEqual(page_composition_key(page, OFFER), composition_key(OFFER))

    def test_a_profile_page_carrying_a_grid_is_still_a_profile(self):
        # The profile block is the more specific claim, so marker ORDER decides this one.
        page = {"sections": [{"type": "catalog_grid"}, {"type": "seller_profile"}]}
        self.assertEqual(offerless_composition(page), "store_profile")

    def test_the_offer_always_wins_over_the_page_shape(self):
        """A link-in-bio page may carry a catalog_grid of its own -- lead_social's excludes say so. If the
        page shape were consulted first it would compose as a storefront, losing every exclusion that makes
        a link hub a link hub."""
        hub = {
            "sections": [{"type": "link_cards"}, {"type": "catalog_grid"}, {"type": "social_links"}],
        }
        hub_offer = {"offer_id": "off_2", "product_intent": "lead_gen",
                     "lead_capture_action": "social_redirect"}
        self.assertEqual(composition_key(hub_offer), "lead_social")
        self.assertEqual(page_composition_key(hub, hub_offer), "lead_social")

    def test_empty_offer_is_the_no_offer_signal(self):
        """publish_page sets `offer = {}` for a page with no offer_id and only then, so an empty offer is
        exactly "no offer" -- which is what makes the guard in page_composition_key sound."""
        self.assertEqual(page_composition_key(STOREFRONT_PAGE, {}), "storefront")
        self.assertEqual(page_composition_key(STOREFRONT_PAGE, None), "storefront")


class NoTransactionalFurnitureTests(unittest.TestCase):
    def test_no_transactional_section_is_visible_on_an_offerless_page(self):
        for composition in OFFERLESS_COMPOSITIONS:
            for key in TRANSACTIONAL_GOVERNED:
                with self.subTest(composition=composition, section=key):
                    self.assertFalse(
                        is_section_visible(composition, key, {}),
                        f"{key} must not be visible on {composition}",
                    )

    def test_the_offer_shaped_addable_elements_are_off_the_add_menu(self):
        """These five read a primary product or offer that does not exist on an offer-less page, so each
        would be a control that can never fill. They are ungoverned, so `excluded_sections` -- what the
        builder's Add-content menu filters on -- is where the guarantee lives."""
        for composition in OFFERLESS_COMPOSITIONS:
            excluded = excluded_sections(composition)
            for key in TRANSACTIONAL_ADDABLE:
                with self.subTest(composition=composition, section=key):
                    self.assertIn(key, excluded)

    def test_a_tenant_override_cannot_resurrect_one(self):
        """An exclusion outranks an override: these are statements about what the page IS, not preferences."""
        for composition in OFFERLESS_COMPOSITIONS:
            for key in TRANSACTIONAL_GOVERNED:
                with self.subTest(composition=composition, section=key):
                    self.assertFalse(
                        is_section_visible(composition, key, {key: {"enabled": True}}),
                        f"an override turned {key} back on for {composition}",
                    )

    def test_a_goal_pack_cannot_union_one_back_on(self):
        """The goal axis is union-only, and `paid_ads` turns on trust_badges + refund_policy. On a page that
        takes no money, 'Secure checkout' and a 30-day refund promise are incoherent, not merely unwanted."""
        for composition in OFFERLESS_COMPOSITIONS:
            for key in ("trust_badges", "refund_policy"):
                with self.subTest(composition=composition, section=key):
                    self.assertFalse(is_section_visible(composition, key, {}, "paid_ads"))

    def test_shipping_stays_off_even_when_the_page_ships(self):
        """ships_physical defaults the shipping element ON everywhere else -- deliberately, since it is the
        only thing that collects a postcode. An offer-less page has no offer to ship, so the exclusion has
        to beat that default too."""
        for composition in OFFERLESS_COMPOSITIONS:
            with self.subTest(composition=composition):
                self.assertFalse(
                    is_section_visible(composition, "shipping", {}, "", True),
                )

    def test_only_one_h1_section_can_reach_the_page(self):
        """brand_hero is already the page's H1. `hero` and `headline` would be a second one, which breaks
        the heading outline the renderer enforces (plans/SEMANTIC_HTML.md)."""
        for composition in OFFERLESS_COMPOSITIONS:
            for key in ("hero", "hero_media", "brand_label"):
                with self.subTest(composition=composition, section=key):
                    self.assertFalse(is_section_visible(composition, key, {}))

    def test_content_elements_stay_available(self):
        """The whole point of P1: these pages need prose to clear the 150-word indexing floor, so the
        content-bearing elements must NOT be swept up by the exclusions."""
        for composition in OFFERLESS_COMPOSITIONS:
            excluded = excluded_sections(composition)
            for key in ("content_block", "faq", "photo", "info_cards", "quote", "numbered_list",
                        "testimonials", "rating", "client_marquee", "video", "coupon", "page_ribbon"):
                with self.subTest(composition=composition, section=key):
                    self.assertNotIn(key, excluded)
                    self.assertTrue(is_section_visible(composition, key, {}))

    def test_structured_data_is_not_excluded(self):
        """It emits nothing today with no offer, and it is the hook the catalog's CollectionPage/ItemList
        markup lands on (P4). Excluding it now would have to be undone then."""
        for composition in OFFERLESS_COMPOSITIONS:
            with self.subTest(composition=composition):
                self.assertNotIn("structured_data", excluded_sections(composition))


class ExistingPagesUnchangedTests(unittest.TestCase):
    """The safety property: no page that exists today may render differently because of P1."""

    def test_offerless_pages_compose_to_the_same_sections_as_before(self):
        for page in (STOREFRONT_PAGE, CATEGORY_PAGE, PROFILE_PAGE):
            with self.subTest(page=page["page_id"]):
                composed = [s["type"] for s in compose_page({}, page)]
                self.assertEqual(composed, [s["type"] for s in page["sections"]])

    def test_an_offer_page_composes_exactly_as_it_did(self):
        page = {
            "page_id": "pg_offer",
            "sections": [
                {"id": "hero", "type": "hero", "headline": "Buy it"},
                {"id": "price", "type": "offer_price_selector"},
                {"id": "cta", "type": "checkout_cta"},
            ],
        }
        composed = [s["type"] for s in compose_page(OFFER, page)]
        self.assertIn("checkout_cta", composed)
        self.assertIn("offer_price_selector", composed)


if __name__ == "__main__":
    unittest.main()
