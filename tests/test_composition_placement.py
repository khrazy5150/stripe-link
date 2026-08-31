import unittest

from stripe_link.domain.composition import (
    PLACEMENT_BANDS,
    RULES,
    element_placement,
    is_movable,
    order_section_keys,
    baseline_order,
)


class PlacementCatalogTests(unittest.TestCase):
    def test_every_element_declares_a_placement(self):
        # The point of the field: adding an element forces a decision about where it may sit. Without
        # this, a new element silently defaults to draggable — which is wrong for anything structural.
        missing = [key for key, spec in RULES["elements"].items() if "placement" not in spec]
        self.assertEqual(missing, [], f"elements missing a placement: {missing}")

    def test_placements_come_from_the_known_set(self):
        allowed = set(PLACEMENT_BANDS) | {"none"}
        for key, spec in RULES["elements"].items():
            with self.subTest(element=key):
                self.assertIn(spec["placement"], allowed)

    def test_the_hero_block_is_pinned(self):
        # hero_media is the LCP element (the renderer emits preload/priority hints for it) and one-H1-
        # first is an invariant the semantic outline depends on. Deliberate divergence from stripe-cart,
        # which allowed the hero to move. If this test is failing, that decision is being reversed.
        for key in ("hero", "hero_media", "headline", "subheadline"):
            with self.subTest(element=key):
                self.assertEqual(element_placement(key), "pinned_top")
                self.assertFalse(is_movable(key))

    def test_legal_footer_is_last_and_head_sections_are_unplaced(self):
        self.assertEqual(element_placement("legal_footer"), "pinned_bottom")
        self.assertFalse(is_movable("legal_footer"))
        self.assertEqual(element_placement("structured_data"), "none")

    def test_the_body_a_tenant_composes_is_movable(self):
        for key in ("testimonials", "faq", "content_block", "checkout_cta", "offer_price_selector"):
            with self.subTest(element=key):
                self.assertTrue(is_movable(key), f"{key} should be draggable")


class RepeatableSectionTests(unittest.TestCase):
    """`repeatable` means "this SECTION may appear more than once", NOT "it holds repeatable items"."""

    def test_only_genuine_multi_instance_sections_are_repeatable(self):
        repeatable = {k for k, v in RULES["elements"].items() if v.get("repeatable")}
        self.assertEqual(repeatable, {"content_block", "catalog_grid"})

    def test_container_sections_are_singletons(self):
        # Testimonials and FAQ are ONE section holding many items, each with its own add control. A
        # second "What Our Clients Say" heading further down the page is never what a tenant meant.
        for key in ("testimonials", "faq", "client_marquee", "rating"):
            with self.subTest(element=key):
                self.assertFalse(RULES["elements"][key].get("repeatable"), key)


class OrderSectionKeysTests(unittest.TestCase):
    def test_bands_are_honoured_regardless_of_input_order(self):
        ordered = order_section_keys(
            ["legal_footer", "faq", "hero", "countdown_timer", "hero_media", "testimonials"]
        )
        self.assertEqual(ordered[0], "countdown_timer")          # lead
        self.assertEqual(ordered[1:3], ["hero_media", "hero"])   # pinned_top, catalog order
        self.assertEqual(ordered[-1], "legal_footer")            # pinned_bottom

    def test_tenant_order_reorders_only_the_free_band(self):
        keys = ["hero", "faq", "testimonials", "legal_footer"]
        ordered = order_section_keys(keys, tenant_order=["faq", "testimonials"])
        self.assertEqual(ordered, ["hero", "faq", "testimonials", "legal_footer"])
        flipped = order_section_keys(keys, tenant_order=["testimonials", "faq"])
        self.assertEqual(flipped, ["hero", "testimonials", "faq", "legal_footer"])

    def test_a_section_missing_from_the_tenant_order_still_appears(self):
        # A newly enabled section must not vanish or jump to an end just because it predates the
        # stored order — it keeps its catalog position among the free band.
        ordered = order_section_keys(["faq", "testimonials", "rating"], tenant_order=["faq"])
        self.assertEqual(ordered[0], "faq")
        self.assertIn("rating", ordered)
        self.assertIn("testimonials", ordered)

    def test_the_baseline_orders_an_untouched_page(self):
        # No tenant order at all — the researched sequence from plans/BUILDER_SECTION_ORDER.md 4a.
        ordered = order_section_keys(
            ["faq", "checkout_cta", "testimonials", "product_details", "rating", "trust_badges"]
        )
        self.assertEqual(
            ordered,
            ["product_details", "rating", "testimonials", "faq", "trust_badges", "checkout_cta"],
        )

    def test_trust_badges_sit_beside_the_cta_not_up_by_the_hero(self):
        # The whole point of 4a: trust seals work at the moment of commitment.
        ordered = order_section_keys(["trust_badges", "faq", "checkout_cta", "testimonials"])
        self.assertLess(ordered.index("faq"), ordered.index("trust_badges"))
        self.assertLess(ordered.index("trust_badges"), ordered.index("checkout_cta"))

    def test_refund_policy_follows_the_ask(self):
        ordered = order_section_keys(["refund_policy", "checkout_cta", "offer_price_selector"])
        self.assertEqual(ordered, ["offer_price_selector", "checkout_cta", "refund_policy"])

    def test_tenant_order_still_beats_the_baseline(self):
        ordered = order_section_keys(["faq", "product_details"], tenant_order=["faq", "product_details"])
        self.assertEqual(ordered, ["faq", "product_details"])

    def test_every_placeable_element_has_a_baseline_slot(self):
        # Forces the two files to agree: an element added to the catalog without a baseline slot fails
        # here rather than silently sorting to the end of the page.
        baseline = set(baseline_order())
        for key, spec in RULES["elements"].items():
            if spec.get("placement") != "none":
                with self.subTest(element=key):
                    self.assertIn(key, baseline, f"{key} has no slot in default_order")
        for key in baseline:
            with self.subTest(baseline=key):
                self.assertIn(key, RULES["elements"], f"default_order lists unknown element {key}")

    def test_an_unslotted_element_sorts_last_not_first(self):
        ordered = order_section_keys(["faq", "made_up_element", "product_details"])
        self.assertEqual(ordered[-1], "made_up_element")

    def test_head_channel_sections_are_dropped(self):
        self.assertNotIn("structured_data", order_section_keys(["hero", "structured_data", "faq"]))


if __name__ == "__main__":
    unittest.main()
