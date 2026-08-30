import unittest

from stripe_link.domain.composition import (
    PLACEMENT_BANDS,
    RULES,
    element_placement,
    is_movable,
    order_section_keys,
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

    def test_head_channel_sections_are_dropped(self):
        self.assertNotIn("structured_data", order_section_keys(["hero", "structured_data", "faq"]))


if __name__ == "__main__":
    unittest.main()
