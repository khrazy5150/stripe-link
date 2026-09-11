"""A product looks the same in the catalogue list and in the offer selector.

Reported 2026-09-10 with a screenshot of both screens: the Products list showed each lead-gen product on a
tinted tile with its action's glyph -- an envelope for email capture, a share graph for a Social Page --
while the Offers selector showed the same product as a single letter on a grey square. Picking the right
product meant remembering its initial, and two products sharing one would have been indistinguishable.

Two separate things, deliberately kept separate:
  ICON  says WHAT the product does -- one glyph per lead action, so two link-in-bio products share it.
  COLOUR says WHICH product it is -- hashed from the id, so those two stay distinguishable.
"""
import pathlib
import re
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
SELECTOR = (SRC / "components" / "SelectorCard.vue").read_text(encoding="utf-8")
LIST_CARD = (SRC / "components" / "shared" / "ListCard.vue").read_text(encoding="utf-8")
OFFERS = (SRC / "components" / "Offers.vue").read_text(encoding="utf-8")
PRODUCTS = (SRC / "components" / "Products.vue").read_text(encoding="utf-8")
ICON_UTIL = (SRC / "utils" / "leadActionIcon.js").read_text(encoding="utf-8")


class SharedTintTests(unittest.TestCase):
    def test_both_cards_tint_from_the_same_helper(self):
        # A second hand-rolled hash would drift from this one, and the whole point is that the colours match.
        for source, name in ((SELECTOR, "SelectorCard"), (LIST_CARD, "ListCard")):
            self.assertIn("idColorStyle", source, name)

    def test_the_selector_keys_the_tint_to_the_PRODUCT_not_the_name(self):
        # Two products can share a name; they cannot share an id.
        self.assertIn(':icon-color-key="productId(product)"', OFFERS)


class SharedIconTests(unittest.TestCase):
    def test_the_icon_factory_is_shared_rather_than_copied(self):
        self.assertIn("leadActionIcon", PRODUCTS)
        self.assertIn("leadActionIcon", OFFERS)
        self.assertEqual(len(re.findall(r"function leadIcon\(action\) \{", PRODUCTS)), 0,
                         "Products.vue still has its own copy of the icon factory")

    def test_every_surviving_lead_action_has_a_glyph(self):
        from stripe_link.domain.documents import LEAD_CAPTURE_ACTIONS
        defined = set(re.findall(r"^  (\w+):", ICON_UTIL, re.M))
        self.assertEqual(defined, set(LEAD_CAPTURE_ACTIONS),
                         "an action without a glyph falls back to a bare initial in every picker")

    def test_a_transactional_product_gets_no_glyph(self):
        # It has no action, so the card falls back to its initial rather than borrowing a meaning.
        self.assertIn("if (!d) return null;", ICON_UTIL)


if __name__ == "__main__":
    unittest.main()
