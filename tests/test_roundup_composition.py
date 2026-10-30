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
        """`manual` is load-bearing: `roundup_item_count` counts manual collections ONLY, because an
        `all` rule's membership moves when a PAGE publishes -- a direction nothing re-renders from."""
        block = self.BUILDER.split("async function seedRoundupCollection()", 1)[1].split("\n}", 1)[0]
        self.assertIn('rule: "manual"', block)

    def test_it_starts_in_an_ORDERED_layout(self):
        """A Roundup is a ranking, so it may never start in grid or masonry -- masonry fills column by
        column and destroys a curated order outright. `editorial` is the default (room to argue per
        entry); `listicle` is the compact alternative one select away."""
        block = self.BUILDER.split("async function seedRoundupCollection()", 1)[1].split("\n}", 1)[0]
        layout = next(line for line in block.splitlines() if "layout:" in line)
        self.assertRegex(layout, r'layout: "(editorial|listicle)"')

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


class TheHeadlineOpensTheArticleTests(unittest.TestCase):
    """A Roundup opens with its headline, then the picture. Every other page opens with the picture.

    `pinned_top` was the ONE band with no rule. A `free` element declares a slot and earns its position;
    the locked bands "carry no slot and need none", so their order within the band was simply the order
    their keys happened to sit in the catalog -- fine while every page wanted the same hero, arbitrary the
    moment one did not.

    A Roundup is that one. It is an article, so it opens the way an article opens: the headline that
    counts the list ("2 Amazing Gift Ideas for 2026"), then the lead image, then the entries. A sales page
    opens with the picture. Both are right, and neither is a property of the ELEMENTS -- it belongs to the
    composition, which is now where it is declared.
    """

    def test_the_hero_copy_comes_before_the_hero_image(self):
        from stripe_link.domain.composition import order_section_keys
        ordered = order_section_keys(["hero_media", "hero", "brand_label"], offer_type="lead_roundup")
        self.assertLess(ordered.index("hero"), ordered.index("hero_media"))

    def test_the_brand_still_comes_first(self):
        """It is `lead`, a band above pinned_top, so reordering inside pinned_top must not disturb it --
        the author asked for the headline "just below the brand"."""
        from stripe_link.domain.composition import order_section_keys
        ordered = order_section_keys(["hero_media", "hero", "brand_label"], offer_type="lead_roundup")
        self.assertEqual(ordered[0], "brand_label")

    def test_every_other_composition_is_untouched(self):
        """The reason this is scoped to one composition rather than reordering the catalog: flipping the
        hero globally would move the H1 above the image on every page already published."""
        from stripe_link.domain.composition import RULES, order_section_keys
        for offer_type in RULES["offer_types"]:
            if offer_type == "lead_roundup":
                continue
            ordered = order_section_keys(["hero_media", "hero"], offer_type=offer_type)
            with self.subTest(offer_type=offer_type):
                self.assertLess(ordered.index("hero_media"), ordered.index("hero"))

    def test_an_unnamed_composition_keeps_the_derived_order(self):
        from stripe_link.domain.composition import order_section_keys
        self.assertEqual(order_section_keys(["hero", "hero_media"]), ["hero_media", "hero"])

    def test_a_composition_names_only_what_it_cares_about(self):
        """Unlisted pinned_top keys keep their catalog position BEHIND the listed ones, so adding a new
        hero element does not mean editing every composition that declares an order."""
        from stripe_link.domain.composition import RULES, baseline_order
        declared = RULES["offer_types"]["lead_roundup"]["pinned_top_order"]
        every = [key for key, spec in RULES["elements"].items() if spec.get("placement") == "pinned_top"]
        self.assertTrue(set(declared) < set(every), "the list must be partial or it has to be maintained")
        order = baseline_order("", "lead_roundup")
        for unlisted in [key for key in every if key not in declared]:
            with self.subTest(unlisted=unlisted):
                self.assertGreater(order.index(unlisted), order.index(declared[-1]))

    def test_every_declared_key_is_really_a_pinned_top_element(self):
        """A typo, or a key from another band, would silently do nothing at all."""
        from stripe_link.domain.composition import RULES
        for offer_type, rule in RULES["offer_types"].items():
            for key in rule.get("pinned_top_order") or []:
                with self.subTest(offer_type=offer_type, key=key):
                    self.assertEqual(RULES["elements"].get(key, {}).get("placement"), "pinned_top")

    def test_the_builder_mirrors_the_renderer(self):
        """Two implementations of one rule. The builder's row list and the published page disagreeing
        about where the hero copy sits is precisely the drift `orderEntries` was centralised to stop, so
        both call sites must pass the composition through."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
        composer = (root / "composables" / "pageComposer.js").read_text(encoding="utf-8")
        builder = (root / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertIn("export function pinnedTopOrder(offerType", composer)
        self.assertIn('export function baselineOrder(goal = "", offerType = "")', composer)
        self.assertIn("baselineOrder(goal, offerType)", composer)
        for call in ("orderSections(", "orderSectionKeys("):
            self.assertIn("builderOfferType.value", builder.split(call, 1)[1].split(";", 1)[0], call)
