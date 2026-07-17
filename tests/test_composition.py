import unittest
from unittest.mock import patch

from stripe_link.domain import composition as composition_module
from stripe_link.domain.composition import (
    allowed_ctas,
    compose_page,
    default_visible,
    element,
    element_label,
    goal_deprecated,
    goal_packs,
    is_section_visible,
    offerable_goals,
    optional_section_keys,
    pack_seeds,
    page_goal,
    recommended_section_keys,
    section_key,
    supported_goals,
)


class CompositionTests(unittest.TestCase):
    def _page(self, overrides=None):
        sections = [
            {"type": "brand_label"},
            {"type": "hero_media"},
            {"type": "hero"},
            {"type": "trust_badges"},
            {"type": "offer_price_selector"},
            {"type": "refund_policy"},
            {"type": "testimonials"},   # ungoverned body element
            {"type": "legal_footer"},
        ]
        page = {"sections": sections}
        if overrides is not None:
            page["composition"] = {"overrides": overrides}
        return page

    def test_section_key_is_identity_after_reframe(self):
        # One vocabulary: the composition key IS the section type (no aliasing).
        self.assertEqual(section_key("brand_label"), "brand_label")
        self.assertEqual(section_key("offer_price_selector"), "offer_price_selector")
        self.assertEqual(section_key("checkout_cta"), "checkout_cta")

    def test_element_catalog_metadata(self):
        self.assertEqual(element_label("offer_price_selector"), "Price cards")
        self.assertEqual(element_label("checkout_cta"), "Call to action")
        self.assertEqual(element("hero")["heading_role"], "h1")
        self.assertEqual(element("trust_badges")["ui"], "toggle")
        self.assertEqual(element("faq")["ui"], "add")
        self.assertEqual(element_label("unknown_type"), "unknown_type")  # graceful fallback

    def test_single_shows_governed_defaults(self):
        types = [s["type"] for s in compose_page({"offer_type": "single"}, self._page())]
        self.assertIn("trust_badges", types)
        self.assertIn("refund_policy", types)
        self.assertIn("brand_label", types)

    def test_listicle_hides_fluff_by_default(self):
        types = [s["type"] for s in compose_page({"offer_type": "listicle"}, self._page())]
        self.assertNotIn("trust_badges", types)      # not in listicle allow-list
        self.assertNotIn("refund_policy", types)
        self.assertNotIn("brand_label", types)
        # core listicle sections survive
        self.assertIn("hero", types)
        self.assertIn("offer_price_selector", types)
        self.assertIn("legal_footer", types)

    def test_ungoverned_element_always_visible(self):
        # A body element (testimonials) shows whenever present, even on a listicle (adding it IS the opt-in).
        types = [s["type"] for s in compose_page({"offer_type": "listicle"}, self._page())]
        self.assertIn("testimonials", types)

    def test_override_opts_hidden_section_back_in(self):
        page = self._page(overrides={"trust_badges": {"enabled": True}})
        types = [s["type"] for s in compose_page({"offer_type": "listicle"}, page)]
        self.assertIn("trust_badges", types)   # default != forced

    def test_override_can_disable_a_default(self):
        page = self._page(overrides={"refund_policy": {"enabled": False}})
        types = [s["type"] for s in compose_page({"offer_type": "single"}, page)]
        self.assertNotIn("refund_policy", types)

    def test_recommended_and_optional_partition(self):
        self.assertIn("trust_badges", recommended_section_keys("single"))
        self.assertIn("trust_badges", optional_section_keys("listicle"))
        self.assertNotIn("trust_badges", recommended_section_keys("listicle"))

    def test_allowed_ctas(self):
        self.assertEqual(allowed_ctas("listicle"), ["buy", "cart"])
        self.assertIn("phone_call", allowed_ctas("single"))

    def test_is_section_visible_direct(self):
        self.assertTrue(is_section_visible("single", "trust_badges", {}))
        self.assertFalse(is_section_visible("listicle", "trust_badges", {}))
        self.assertTrue(is_section_visible("listicle", "trust_badges", {"trust_badges": {"enabled": True}}))


class GoalCompositionTests(unittest.TestCase):
    """The goal axis (plans/LANDING_PAGE_GOAL_COMPOSITION.md): offer_type says WHAT the page sells, goal says
    WHY its traffic comes. Goals enable capability packs on top of the offer_type base, union-only."""

    def _page(self, goal=None):
        page = {"sections": [{"type": "hero"}, {"type": "trust_badges"}, {"type": "faq"}]}
        if goal is not None:
            page["goal"] = goal
        return page

    def test_goals_come_from_the_rules_file(self):
        goals = supported_goals()
        self.assertEqual(goals, ["paid_ads", "search_seo", "social", "email_list", "minimal"])

    def test_goal_packs_and_seeds(self):
        self.assertEqual(goal_packs("search_seo"), ["discoverability"])
        self.assertEqual(pack_seeds("search_seo"), ["faq"])
        self.assertEqual(pack_seeds("social"), ["testimonials", "rating", "client_marquee"])
        # Lean goals start with the offer only.
        self.assertEqual(pack_seeds("paid_ads"), [])
        self.assertEqual(pack_seeds("minimal"), [])

    def test_unknown_or_absent_goal_enables_nothing(self):
        # A page from before the goal axis must behave exactly as it did: base sections only.
        self.assertEqual(goal_packs(""), [])
        self.assertEqual(goal_packs("not_a_goal"), [])
        self.assertEqual(pack_seeds(""), [])

    def test_page_goal_reads_the_document(self):
        self.assertEqual(page_goal({"goal": "social"}), "social")
        self.assertEqual(page_goal({}), "")
        self.assertEqual(page_goal(None), "")

    def test_goal_never_removes_a_base_section(self):
        # Packs are union-only: no goal can take away what the offer_type already grants.
        for goal in supported_goals():
            for key in ("hero", "trust_badges", "checkout_cta", "legal_footer"):
                self.assertTrue(
                    default_visible("single", key, goal),
                    f"goal {goal} must not remove base section {key}",
                )

    def test_only_search_seo_grants_structured_data(self):
        # Phase 3 makes the pack `sections` half live: discoverability grants the derived structured_data
        # head section. Every OTHER goal must still compose exactly like a page with no goal — the goal
        # axis may add for the goal that asked, and nothing else.
        base = recommended_section_keys("single", "")
        self.assertNotIn("structured_data", base)
        self.assertEqual(recommended_section_keys("single", "search_seo"), base + ["structured_data"])
        for goal in ("paid_ads", "social", "email_list", "minimal"):
            self.assertEqual(recommended_section_keys("single", goal), base, f"{goal} must not change composition")

    def test_structured_data_is_off_unless_a_goal_asks(self):
        # It is governed but in no offer_type base, so existing pages (no goal) never gain it silently.
        self.assertFalse(default_visible("single", "structured_data", ""))
        self.assertTrue(default_visible("single", "structured_data", "search_seo"))

    def test_compose_page_is_unchanged_without_a_goal(self):
        with_goal = [s["type"] for s in compose_page({"offer_type": "single"}, self._page("search_seo"))]
        without = [s["type"] for s in compose_page({"offer_type": "single"}, self._page())]
        self.assertEqual(with_goal, without)

    def test_overrides_still_beat_the_goal_default(self):
        page = self._page("search_seo")
        page["composition"] = {"overrides": {"trust_badges": {"enabled": False}}}
        types = [s["type"] for s in compose_page({"offer_type": "single"}, page)]
        self.assertNotIn("trust_badges", types)

    def test_is_section_visible_accepts_a_goal(self):
        self.assertTrue(is_section_visible("single", "trust_badges", {}, "minimal"))
        self.assertFalse(is_section_visible("listicle", "trust_badges", {}, "minimal"))
        # Ungoverned body elements ignore the goal entirely — presence is the opt-in.
        self.assertTrue(is_section_visible("single", "faq", {}, "paid_ads"))



class GoalDeprecationTests(unittest.TestCase):
    """Retiring a goal has to be additive. Deleting one outright strands every page that already stores it:
    the page stops validating, so it can be neither saved nor re-rendered. `deprecated` hides a goal from the
    wizard while it keeps validating and composing forever."""

    DEPRECATED = {
        "paid_ads": {"label": "Paid ads", "note": "", "packs": []},
        "social": {"label": "Social", "note": "", "packs": ["social_proof"], "deprecated": True},
    }

    def test_nothing_is_deprecated_today(self):
        self.assertEqual(offerable_goals(), supported_goals())
        for goal in supported_goals():
            self.assertFalse(goal_deprecated(goal))

    def test_deprecated_goal_is_not_offered_but_stays_legal(self):
        with patch.dict(composition_module._GOALS, self.DEPRECATED, clear=True):
            self.assertEqual(offerable_goals(), ["paid_ads"])
            # ...but it remains in supported_goals(), which is what the page validator enforces.
            self.assertIn("social", supported_goals())
            self.assertTrue(goal_deprecated("social"))

    def test_deprecated_goal_still_composes_its_packs(self):
        # An existing page keeps rendering exactly as before it was retired — deprecation is a wizard
        # concern, never a composition one.
        with patch.dict(composition_module._GOALS, self.DEPRECATED, clear=True):
            self.assertEqual(goal_packs("social"), ["social_proof"])
            self.assertEqual(pack_seeds("social"), ["testimonials", "rating", "client_marquee"])



class CatalogIsTheSingleSourceTests(unittest.TestCase):
    """The element catalog in composition_rules.json is the one vocabulary. Anything that keeps its own copy
    of the element or goal list will drift out of sync, and the failure lands far from the cause: adding
    structured_data to the catalog made it composable and renderable but not storable, which surfaced only
    as a 400 from /pages/render."""

    def test_valid_section_types_come_from_the_catalog(self):
        from stripe_link.domain.documents import SUPPORTED_PAGE_SECTION_TYPES
        self.assertEqual(SUPPORTED_PAGE_SECTION_TYPES, set(composition_module.ELEMENTS.keys()))

    def test_valid_goals_come_from_the_catalog(self):
        from stripe_link.domain.documents import SUPPORTED_PAGE_GOALS
        self.assertEqual(SUPPORTED_PAGE_GOALS, set(supported_goals()))

    def test_every_governed_section_exists_in_the_catalog(self):
        for key in composition_module.RULES.get("governed_sections", []):
            self.assertIn(key, composition_module.ELEMENTS, f"governed section {key} has no catalog entry")

    def test_every_pack_reference_resolves(self):
        # A typo in a pack's seeds/sections fails silently — the pack just contributes nothing.
        for name, pack in (composition_module.RULES.get("packs") or {}).items():
            for seed in pack.get("seeds") or []:
                self.assertIn(seed, composition_module.ELEMENTS, f"pack {name} seeds unknown element {seed}")
            for section in pack.get("sections") or []:
                self.assertIn(section, composition_module.ELEMENTS, f"pack {name} grants unknown section {section}")

    def test_every_goal_references_a_real_pack(self):
        packs = composition_module.RULES.get("packs") or {}
        for goal in supported_goals():
            for name in goal_packs(goal):
                self.assertIn(name, packs, f"goal {goal} references unknown pack {name}")



if __name__ == "__main__":
    unittest.main()
