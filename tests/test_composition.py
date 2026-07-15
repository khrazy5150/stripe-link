import unittest

from stripe_link.domain.composition import (
    allowed_ctas,
    compose_page,
    is_section_visible,
    optional_section_keys,
    recommended_section_keys,
    section_key,
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

    def test_section_key_alias(self):
        self.assertEqual(section_key("brand_label"), "brand")
        self.assertEqual(section_key("offer_price_selector"), "offer_selector")
        self.assertEqual(section_key("checkout_cta"), "cta")
        self.assertEqual(section_key("hero"), "hero")

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


if __name__ == "__main__":
    unittest.main()
