"""The goal step on offer-less pages (plans/OFFERLESS_PAGES_IN_BUILDER.md P3).

A storefront, category or store-profile page is now asked for a goal like any other page, because the goal
is the thing that seeds a content block and an FAQ — and content is the only route these pages have over
the 150-word indexing floor. The invariant that matters most here is the one a reader would not think to
check: a goal must not PROMISE something the offer-less compositions forbid. P1's exclusions are broad,
and every goal's note is shown verbatim on the wizard card, so a pack whose seeds were being silently
dropped would be a card advertising content the page cannot have.
"""

import copy
import json
import re
import unittest
from pathlib import Path

from stripe_link.domain.composition import (
    OFFERLESS_COMPOSITIONS,
    excluded_sections,
    goal_note,
    goal_sections,
    is_section_visible,
    offerable_goals,
    pack_seeds,
)

ROOT = Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class GoalsKeepTheirPromisesHereTests(unittest.TestCase):
    def test_no_goal_seed_is_excluded_by_an_offerless_composition(self):
        """Every seed a goal's card advertises must actually be addable to these pages."""
        for goal in offerable_goals():
            for composition in OFFERLESS_COMPOSITIONS:
                excluded = excluded_sections(composition)
                for seed in pack_seeds(goal):
                    with self.subTest(goal=goal, composition=composition, seed=seed):
                        self.assertNotIn(
                            seed, excluded,
                            f"goal {goal} advertises {seed}, which {composition} forbids",
                        )

    def test_search_seo_turns_on_structured_data_here_too(self):
        """The one goal that changes what crawlers see, which is the reason the step exists on these pages."""
        for composition in OFFERLESS_COMPOSITIONS:
            with self.subTest(composition=composition):
                self.assertIn("structured_data", goal_sections("search_seo"))
                self.assertTrue(
                    is_section_visible(composition, "structured_data", {}, "search_seo"),
                )

    def test_paid_ads_still_cannot_bring_the_transactional_sections(self):
        """Its SEEDS survive (content_block, faq) while its pack SECTIONS do not -- trust badges and a
        refund promise on a page that takes no money are incoherent. Both halves at once, because the fix
        for one must not have quietly undone the other."""
        for composition in OFFERLESS_COMPOSITIONS:
            with self.subTest(composition=composition):
                excluded = excluded_sections(composition)
                self.assertNotIn("content_block", excluded)
                self.assertNotIn("faq", excluded)
                for key in ("trust_badges", "refund_policy"):
                    self.assertFalse(is_section_visible(composition, key, {}, "paid_ads"))

    def test_no_goal_note_is_written_for_an_offer_page_only(self):
        """The cards are shared markup now, so copy that says "the offer" is read by someone building a
        page that has none."""
        for goal in offerable_goals():
            with self.subTest(goal=goal):
                self.assertNotIn("the offer", goal_note(goal).lower())

    def test_the_search_seo_note_does_not_still_call_structured_data_future_work(self):
        """It shipped. The note read "(later) structured data and llms.txt" long after the first half was
        live, which is the kind of stale promise that makes a tenant pick a different goal."""
        note = goal_note("search_seo")
        self.assertNotIn("later", note.lower())
        self.assertIn("structured data", note.lower())
        # llms.txt genuinely does not exist, so it must not be advertised either.
        self.assertNotIn("llms", note.lower())


class StructuredDataActuallyLandsTests(unittest.TestCase):
    """End to end: picking `search_seo` on a storefront has to change the published bytes, or the card is
    selling nothing."""

    @staticmethod
    def _render(goal):
        from stripe_link.runtime.html import render_page
        from stripe_link.runtime.publishing import resolve_category_grids

        fx = lambda n: json.loads((ROOT / "schemas" / "examples" / n).read_text())
        product, offer = fx("product-creatine-gummies.json"), fx("offer-creatine-standard.json")
        tenant = product["tenant_id"]
        site = {
            "document_type": "site", "tenant_id": tenant, "site_id": "s1", "name": "Probe Store",
            "hostname": "probestore.com",
            "hosting": {"custom_domain": "probestore.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"}, "status": "active",
            "organization": {"name": "Probe Store"},
            "pages": {
                "/": {"page_id": "pg_sf", "page_type": "homepage", "enabled": True},
                "/gummies": {"page_id": "pg_o", "offer_id": offer["offer_id"],
                             "page_type": "landing", "enabled": True},
            },
        }
        collections = {"c1": {"document_type": "collection", "tenant_id": tenant, "collection_id": "c1",
                              "site_id": "s1", "name": "All", "rule": "all"}}
        page = {
            "schema_version": "2026-05-29", "document_type": "page", "tenant_id": tenant,
            "page_id": "pg_sf", "name": "SF", "status": "published", "published_at": None, "revision": 1,
            "route": {"slug": "home"}, "theme": {"preset": "clean-slate"},
            "seo": {"title": "Probe Store"},
            "sections": [
                {"id": "bh", "type": "brand_hero", "headline": "Probe Store"},
                {"id": "cg", "type": "catalog_grid", "collection_id": "c1"},
                {"id": "faq", "type": "faq",
                 "items": [{"question": "Do you ship to Canada?", "answer": "Yes, we do."}]},
            ],
        }
        if goal:
            page["goal"] = goal
        work = copy.deepcopy(page)
        resolve_category_grids(work, site, collections_by_id=collections)
        html = render_page(work, {}, {product["product_id"]: product},
                           offers_by_id={offer["offer_id"]: offer},
                           canonical_url="https://probestore.com/", indexable=True, site=site,
                           page_type="homepage", home_url="https://probestore.com/",
                           api_base_url="https://api.example.com")
        return sorted(set(re.findall(r'"@type"\s*:\s*"([A-Za-z]+)"', html)))

    def test_the_goal_is_what_puts_json_ld_on_a_storefront(self):
        without = self._render("")
        with_goal = self._render("search_seo")
        self.assertEqual(without, [], "a storefront with no goal should emit no JSON-LD today")
        self.assertIn("FAQPage", with_goal)
        self.assertIn("Organization", with_goal)
        self.assertIn("WebSite", with_goal)


class WhatItTakesToClearTheFloorTests(unittest.TestCase):
    """How much a storefront has to say before it can be indexed, measured rather than assumed.

    An offer page starts at 108 words from text derived from its offer -- product description, prices, CTA,
    trust badges. A storefront starts at 9. The difference is why `discoverability` had to seed prose and
    not just an FAQ, and why the honest answer to "will my storefront be indexed?" depends on two things
    the tenant controls: how much they write, and how many products are in the grid.

    Measured on 2026-10-22, both scaffolds filled at an ordinary level of effort (one paragraph, three
    questions):

        products in grid     bare    + seeds filled
        1                       9             125
        3                      16             132
        6                      27             143
        12                     49             165  <- clears the 150 floor

    The numbers are not asserted (any copy edit moves them). The two PROPERTIES behind them are.
    """

    @staticmethod
    def _words(product_count, extra_sections):
        import copy as _copy

        from stripe_link.runtime.html import indexable_word_count, render_page
        from stripe_link.runtime.publishing import resolve_category_grids

        fx = lambda n: json.loads((ROOT / "schemas" / "examples" / n).read_text())
        base_product, base_offer = fx("product-creatine-gummies.json"), fx("offer-creatine-standard.json")
        tenant = base_product["tenant_id"]
        names = ["Creatine Gummies", "Electrolyte Sticks", "Whey Isolate Vanilla",
                 "Whey Isolate Chocolate", "Magnesium Glycinate", "Creatine Monohydrate Powder",
                 "Daily Greens Blend", "Collagen Peptides", "Omega-3 Softgels", "Vitamin D3 + K2",
                 "Pre-Workout Citrus", "Casein Night Protein"]
        products, offers, entries = {}, {}, {}
        for index, name in enumerate(names[:product_count]):
            product_id, offer_id = f"prod_{index}", f"off_{index}"
            product = _copy.deepcopy(base_product)
            product["product_id"], product["name"] = product_id, name
            for price in product["prices"]:
                price["price_id"] = f"{price['price_id']}_{index}"
            product["default_price_id"] = product["prices"][0]["price_id"]
            offer = _copy.deepcopy(base_offer)
            offer["offer_id"], offer["name"] = offer_id, name
            offer["items"] = [{"product_id": product_id,
                               "price_id": product["prices"][0]["price_id"], "quantity": 1}]
            offer.setdefault("presentation", {})["headline"] = name
            products[product_id], offers[offer_id] = product, offer
            entries[f"/{product_id}"] = {"page_id": f"pg_{index}", "offer_id": offer_id,
                                         "page_type": "landing", "enabled": True}
        site = {
            "document_type": "site", "tenant_id": tenant, "site_id": "s1", "name": "Probe Store",
            "hostname": "probestore.com",
            "hosting": {"custom_domain": "probestore.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"}, "status": "active",
            "organization": {"name": "Probe Store"},
            "pages": {"/": {"page_id": "pg_sf", "page_type": "homepage", "enabled": True}, **entries},
        }
        collections = {"c1": {"document_type": "collection", "tenant_id": tenant,
                              "collection_id": "c1", "site_id": "s1", "name": "All", "rule": "all"}}
        page = {
            "schema_version": "2026-05-29", "document_type": "page", "tenant_id": tenant,
            "page_id": "pg_sf", "name": "SF", "status": "published", "published_at": None,
            "revision": 1, "route": {"slug": "home"}, "theme": {"preset": "clean-slate"},
            "seo": {"title": "Probe Store"}, "goal": "search_seo",
            "sections": [
                {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store",
                 "tagline": "Good things, fairly priced"},
                {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1"},
            ] + extra_sections,
        }
        work = _copy.deepcopy(page)
        resolve_category_grids(work, site, collections_by_id=collections)
        html = render_page(work, {}, products, offers_by_id=offers,
                           canonical_url="https://probestore.com/", indexable=True, site=site,
                           page_type="homepage", home_url="https://probestore.com/",
                           api_base_url="https://api.example.com")
        return indexable_word_count(html)

    FILLED = [
        {"id": "content-block", "type": "content_block", "blocks": [
            {"title": "Why shop with us", "text":
             "We have sold supplements out of Springfield, Oregon since 2014 and we keep the range "
             "deliberately short: creatine, electrolytes and protein. Orders placed before two in the "
             "afternoon ship the same day from our own warehouse, not a drop-shipper."},
        ]},
        {"id": "faq", "type": "faq", "items": [
            {"question": "Do you ship outside the United States?",
             "answer": "We ship to all fifty states and to Canada. The rest of the world is on the list."},
            {"question": "Can I return something I have opened?",
             "answer": "Yes. Send the rest back within thirty days and we refund the order, return "
                       "postage included."},
            {"question": "Is everything third-party tested?",
             "answer": "Every batch, and the certificate is linked from that batch's own page so you can "
                       "read it yourself."},
        ]},
    ]

    def test_the_grid_contributes_to_the_indexable_word_count(self):
        """Non-obvious and load-bearing: the product titles and prices in the grid are real page content,
        not stripped chrome, so a bigger catalogue genuinely helps a storefront qualify. Measuring this on
        a ONE-product fixture is what made an earlier reading look worse than reality."""
        self.assertGreater(self._words(12, []), self._words(1, []))
        self.assertGreater(self._words(12, self.FILLED), self._words(1, self.FILLED))

    def test_a_real_catalogue_plus_filled_scaffolds_clears_the_floor(self):
        from stripe_link.runtime.html import THIN_CONTENT_MIN_WORDS

        self.assertGreaterEqual(self._words(12, self.FILLED), THIN_CONTENT_MIN_WORDS)

    def test_the_grid_alone_never_clears_it(self):
        """A page of product tiles and nothing else is the doorway shape the floor exists to catch. No
        catalogue size may buy its way past it -- the tenant has to write something."""
        from stripe_link.runtime.html import THIN_CONTENT_MIN_WORDS

        self.assertLess(self._words(12, []), THIN_CONTENT_MIN_WORDS)


class WizardFlowTests(unittest.TestCase):
    """Source pins for the four-step offer-less path. The dashboard has no JS test runner (TODO.md)."""

    def test_the_offerless_rail_has_a_goal_step(self):
        labels = BUILDER.split('if (form.pageKind !== "offer") return [', 1)[1].split("]", 1)[0]
        self.assertEqual(
            [part.strip().strip('"') for part in labels.split(",")],
            ["Site", "Type", "Goal", "Details"],
        )

    def test_the_detail_steps_moved_to_step_three(self):
        for kind in ("storefront", "category", "profile"):
            with self.subTest(kind=kind):
                self.assertIn(f"wizardStep === 3 && form.pageKind === '{kind}'", BUILDER)
                self.assertNotIn(f"wizardStep === 2 && form.pageKind === '{kind}'", BUILDER)

    def test_the_goal_step_is_reused_not_duplicated(self):
        """ONE goal-card block in the wizard, shared by the offer and offer-less paths -- a second copy is
        how the two would come to offer different goals. `goalOptions` itself appears twice on purpose: the
        wizard's cards and the builder's Page Settings select, which is where an existing page's goal is
        changed. The card block is identified by goalSeedLabels, which only it uses."""
        self.assertEqual(BUILDER.count("goalSeedLabels(option.value)"), 2)   # the v-if and the v-else
        self.assertEqual(BUILDER.count('<WizardChoiceCard\n                v-for="option in goalOptions"'), 1)

    def test_a_goal_must_be_chosen_before_the_details(self):
        body = BUILDER.split("function nextWizardStep() {", 1)[1].split("\n}", 1)[0]
        offerless = body.split('if (form.pageKind !== "offer") {', 1)[1].split("\n  }", 1)[0]
        self.assertIn("wizardStep.value === 2 && !form.goal", offerless)
        self.assertIn("wizardStep.value = 3", offerless)

    def test_editing_skips_the_goal_step(self):
        """The goal of an existing page is changed in the builder's Page Settings. Re-asking it on the edit
        path would also re-run the seeding over content the tenant already owns."""
        body = BUILDER.split("async function editOfferlessPage(page) {", 1)[1]
        self.assertIn("wizardStep.value = 3;", body.split("\n}", 1)[0])

    def test_the_goal_is_stored_on_the_document(self):
        body = BUILDER.split("function finalizeOfferlessDoc(", 1)[1].split("\n}", 1)[0]
        self.assertIn("goal:", body)
        # Preserved, not overwritten, when editing -- the edit path never asks for it.
        self.assertIn("isEditingOfferless.value ? base.goal : form.goal", body)

    def test_creating_one_hands_off_to_the_builder_with_the_seeds(self):
        """A goal's seeds are EMPTY elements in builder state, and builderSections() drops still-empty
        elements on save. A goal chosen and then never shown to anyone therefore seeds nothing at all."""
        handoff = BUILDER.split("function openBuilderOnCreatedOfferlessPage(saved) {", 1)[1].split("\n}", 1)[0]
        self.assertIn("seedGoalElements(form.goal)", handoff)
        self.assertIn("builderOpen.value = true", handoff)
        self.assertIn("populateBuilderFromPage(saved)", handoff)
        # All three create paths, and only on create. Four occurrences: the definition plus three calls.
        self.assertEqual(BUILDER.count("openBuilderOnCreatedOfferlessPage(saved)"), 4)
        self.assertEqual(BUILDER.count("else openBuilderOnCreatedOfferlessPage(saved);"), 3)

    def test_the_goal_card_does_not_say_offer_on_an_offerless_page(self):
        self.assertIn('form.pageKind === "offer" ? "Starts with the offer only"', BUILDER)


if __name__ == "__main__":
    unittest.main()
