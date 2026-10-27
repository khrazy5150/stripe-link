"""The `roundup` lead action and its composition (plans/ROUNDUP_PAGES.md §2a, P3).

A Roundup lists the tenant's own landing pages under a headline that counts itself. It captures nothing,
which is why it is a `lead_capture_action` at all: `external_url` and `social_redirect` capture nothing
either, so that enum is in practice "what does this NON-TRANSACTING page do". `product_intent=lead_gen`
is the only mechanism that can say it -- plans/SOCIAL_MEDIA_PAGES.md §2a records that expressing it
through `offer_type` could never be reached, because `offer_type` is derived.

Two traps were found building this, and both have a test here, because both would have shipped looking
fine: the composition's NAME decides whether the page transacts, and membership of `LEAD_COMPOSITIONS`
silently grants an exemption from the thin-content warning that a Roundup must not have.
"""

import unittest

from stripe_link.domain.composition import (
    LEAD_COMPOSITIONS,
    RULES,
    composition_forbids_indexing,
    composition_key,
    excluded_sections,
    is_lead_composition,
    is_section_visible,
    is_thin_by_design,
)
from stripe_link.domain.documents import LEAD_CAPTURE_ACTIONS

ROUNDUP = {"product_intent": "lead_gen", "lead_capture_action": "roundup"}


class TheActionTests(unittest.TestCase):
    def test_roundup_is_a_lead_capture_action(self):
        self.assertIn("roundup", LEAD_CAPTURE_ACTIONS)

    def test_it_composes_as_its_own_shape(self):
        self.assertEqual(composition_key(ROUNDUP), "lead_roundup")
        self.assertTrue(is_lead_composition(ROUNDUP))

    def test_every_action_maps_to_a_composition(self):
        """A new action with no entry falls through to DEFAULT_LEAD_COMPOSITION — a capture form on a page
        that was never meant to have one."""
        self.assertEqual(set(LEAD_CAPTURE_ACTIONS) - set(LEAD_COMPOSITIONS), set())


class ItMustNotTransactTests(unittest.TestCase):
    """TRAP ONE. `render_coupon` decides whether a page transacts with
    `composition_key(offer).startswith("lead_")` — the NAME, not a flag.

    A composition called `roundup` would have been handed a checkout href on a page that sells nothing.
    Naming it `lead_roundup` is load-bearing, and nothing but this test says so.
    """

    def test_the_composition_name_starts_with_lead(self):
        self.assertTrue(composition_key(ROUNDUP).startswith("lead_"))

    def test_no_lead_action_maps_to_a_name_that_would_transact(self):
        for action, composition in LEAD_COMPOSITIONS.items():
            self.assertTrue(composition.startswith("lead_"), f"{action} -> {composition}")

    def test_the_checkout_cta_is_excluded(self):
        self.assertIn("checkout_cta", excluded_sections("lead_roundup"))
        self.assertFalse(is_section_visible("lead_roundup", "checkout_cta"))

    def test_every_price_bearing_element_is_excluded(self):
        """Each entry links to its own page, which is where the product is argued and sold. A price on the
        listing would be a second claim about money that can disagree with the one on the offer page."""
        for section in ("offer_price_selector", "price_highlight", "product_details", "refund_policy"):
            self.assertIn(section, excluded_sections("lead_roundup"), section)


class ItIsNotThinByDesignTests(unittest.TestCase):
    """TRAP TWO, and the more dangerous one.

    `THIN_BY_DESIGN` is derived from `set(LEAD_COMPOSITIONS.values())`, so adding any lead composition
    silently exempts it from the thin-content warning. Every other lead shape earns that: being short is
    what a squeeze page or a link hub IS, and padding one to 150 words would damage the page to silence a
    notice.

    A Roundup is the opposite. It must carry an introduction and a note on how the products were chosen,
    or the thin-content gate publishes it `noindex` and it never ranks — which is the only thing it
    exists to do. Inheriting the exemption would have suppressed the one warning that explains why, while
    the demotion happened anyway: silently unranked, with the explanation turned off.
    """

    def test_a_roundup_still_gets_the_thin_content_warning(self):
        self.assertFalse(is_thin_by_design(ROUNDUP))

    def test_the_other_lead_shapes_keep_their_exemption(self):
        for action in ("capture_email", "call_number", "external_url", "social_redirect"):
            offer = {"product_intent": "lead_gen", "lead_capture_action": action}
            self.assertTrue(is_thin_by_design(offer), action)

    def test_it_is_not_forbidden_from_being_indexed(self):
        """Unlike `lead_bridge`, being found in search is the entire purpose."""
        self.assertFalse(composition_forbids_indexing(ROUNDUP))


class WhatTheListingPageCarriesTests(unittest.TestCase):
    def test_the_grid_and_prose_are_available(self):
        """`catalog_grid` is the Collection embed; `content_block` carries the intro and the
        how-these-were-chosen note, which is also the text the thin-content gate counts."""
        for section in ("catalog_grid", "content_block", "faq"):
            self.assertNotIn(section, excluded_sections("lead_roundup"), section)

    def test_the_star_badge_is_available_but_not_volunteered(self):
        """plans/ROUNDUP_PAGES.md §7: the `rating` element renders a number the tenant typed and emits no
        AggregateRating. A tenant who adds it makes that claim in their own name — so it is in NEITHER
        the default sections nor the exclusions. The reference page covers every entry in invented
        scores; the difference between permitting that and proposing it is the whole exposure."""
        rules = RULES["offer_types"]["lead_roundup"]
        self.assertNotIn("rating", rules["excludes"])
        self.assertNotIn("rating", rules["sections"])

    def test_it_offers_no_call_to_action_of_its_own(self):
        """There is no single thing to do on a Roundup — each entry has its own destination."""
        self.assertEqual(RULES["offer_types"]["lead_roundup"]["allowed_ctas"], [])


class TheWizardMustSeedTheGridTests(unittest.TestCase):
    """A Roundup is made of its grid, and nothing used to give it one.

    `catalog_grid` is `ui: "internal"` — it never appears in the Add-content menu, it arrives with the
    page. Offer-less pages get theirs from the storefront wizard. A Roundup HAS an offer, so it took the
    ordinary landing-page path and arrived with no grid, no Collection, and no way for the tenant to add
    either: the page the whole shape is made of simply never existed, while every piece behind it worked.

    Source assertions, because this is Vue. The behaviour they stand for is the creation flow.
    """

    BUILDER = ""
    COMPOSER = ""

    @classmethod
    def setUpClass(cls):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
        cls.BUILDER = (root / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        cls.COMPOSER = (root / "composables" / "pageComposer.js").read_text(encoding="utf-8")

    def test_the_collection_is_minted_before_the_builder_opens(self):
        """The Collection is the grid's source of truth; a page embedding an id that was never saved
        resolves to an empty grid."""
        self.assertIn("async function seedRoundupCollection()", self.BUILDER)
        self.assertIn("if (!(await seedRoundupCollection())) return;", self.BUILDER)

    def test_it_starts_manual_so_the_count_can_be_offered(self):
        block = self.BUILDER.split("async function seedRoundupCollection()", 1)[1].split("\n}", 1)[0]
        self.assertIn('rule: "manual"', block)
        self.assertIn('layout: "listicle"', block)

    def test_a_failed_mint_stops_rather_than_opening_an_empty_grid(self):
        block = self.BUILDER.split("async function seedRoundupCollection()", 1)[1].split("\n}", 1)[0]
        self.assertIn("return false;", block)

    def test_the_grid_is_emitted_on_save_for_a_roundup(self):
        """`offerlessSections` emits nothing for a page that HAS an offer, which is why this is separate."""
        self.assertIn('builderOfferType.value === "lead_roundup"', self.BUILDER)
        self.assertIn("catalogGridSection(builder)", self.BUILDER)

    def test_both_shapes_share_one_grid_emitter(self):
        """Two copies of this is the drift pattern this codebase keeps paying for."""
        self.assertIn("export function catalogGridSection(state)", self.COMPOSER)
        self.assertIn("const grid = catalogGridSection(state);", self.COMPOSER)

    def test_blank_entry_boxes_are_not_persisted_as_authored_copy(self):
        """An empty string is authored-but-blank — it would suppress the fallback to the page's own words."""
        block = self.COMPOSER.split("export function catalogGridSection(state)", 1)[1].split("\n}", 1)[0]
        self.assertIn("String(value || \"\").trim()", block)

    def test_the_layout_and_copy_round_trip(self):
        """Write-only fields are lost on reload, which reads as the builder discarding the tenant's work."""
        state = self.COMPOSER.split("export function offerlessState(page)", 1)[1]
        self.assertIn('layout: grid.layout || ""', state)
        self.assertIn("entry_copy: { ...(grid.entry_copy || {}) }", state)

    def test_the_page_is_seeded_with_words_not_just_a_list(self):
        """A bare list is under 150 words, and the thin-content gate publishes that `noindex` — which is
        the one thing a Roundup exists not to be."""
        seeds = self.BUILDER.split("const SHAPE_SEEDS = {", 1)[1].split("};", 1)[0]
        self.assertIn("lead_roundup", seeds)
        self.assertIn("content_block", seeds)
