"""Price Highlight — the standalone bargain block (plans/PRICE_HIGHLIGHT.md).

Numbers are DERIVED; the tenant authors only two lines of copy. That is the property under test: a page
can never show a price checkout will not honour, and it can never overstate a discount.
"""

import unittest

from stripe_link.domain.bargain import FROM_PREFIX, derived_bargain
from stripe_link.runtime.html import render_price_highlight

PRODUCTS = {
    # a straightforward discount
    "p1": {"prices": [{"price_id": "a", "unit_amount": 3700, "compare_at_unit_amount": 4900,
                       "currency": "usd", "context": "standard"}]},
    # tiered: the cheapest tier has a MODEST discount, a richer tier a much larger one
    "p2": {"prices": [{"price_id": "t1", "unit_amount": 2422, "compare_at_unit_amount": 3500, "currency": "usd"},
                      {"price_id": "t2", "unit_amount": 4159, "compare_at_unit_amount": 8500, "currency": "usd"},
                      {"price_id": "t3", "unit_amount": 5571, "currency": "usd"}]},
    # no discount at all
    "p3": {"prices": [{"price_id": "s", "unit_amount": 2000, "currency": "usd", "context": "standard"}]},
}
SECTION = {"id": "ph", "main_text": "Today Only", "subtext": "Lifetime Access"}

SINGLE = {"items": [{"product_id": "p1", "price_id": "a"}]}
TIERED = {"items": [{"product_id": "p2", "selectable_prices": [{"price_id": "t1"}, {"price_id": "t2"}, {"price_id": "t3"}]}]}
PLAIN = {"items": [{"product_id": "p3", "price_id": "s"}]}


class DerivedBargainTests(unittest.TestCase):
    def test_a_tiered_item_pairs_the_lowest_price_with_ITS_OWN_regular(self):
        """The rule that keeps the discount honest. The cheapest tier is $24.22 against $35.00; the richer
        tier's $85.00 regular is a different product configuration. Pairing $24.22 against $85.00 would
        overstate the saving — fabricated savings territory, not a rounding detail."""
        bargain = derived_bargain(TIERED, PRODUCTS)
        self.assertEqual(bargain["sale"], 2422)
        self.assertEqual(bargain["regular"], 3500)
        self.assertNotEqual(bargain["regular"], 8500)
        self.assertTrue(bargain["tiered"])

    def test_an_undiscounted_item_contributes_its_own_price_to_a_bundle(self):
        # Otherwise a bundle containing one full-price item would inflate its apparent saving.
        bargain = derived_bargain({"items": [{"product_id": "p1", "price_id": "a"},
                                             {"product_id": "p3", "price_id": "s"}]}, PRODUCTS)
        self.assertEqual(bargain["sale"], 5700)
        self.assertEqual(bargain["regular"], 6900)

    def test_quantity_multiplies_both_sides(self):
        bargain = derived_bargain({"items": [{"product_id": "p1", "price_id": "a", "quantity": 2}]}, PRODUCTS)
        self.assertEqual((bargain["sale"], bargain["regular"]), (7400, 9800))

    def test_no_compare_at_means_no_bargain_but_still_a_price(self):
        bargain = derived_bargain(PLAIN, PRODUCTS)
        self.assertFalse(bargain["has_bargain"])
        self.assertEqual(bargain["sale"], 2000)


class RenderTests(unittest.TestCase):
    def test_a_discount_strikes_through_the_regular_price(self):
        html = render_price_highlight(SECTION, SINGLE, PRODUCTS)
        self.assertIn("<s>$49.00</s>", html)
        self.assertIn("$37.00", html)

    def test_no_discount_still_renders_the_price_and_copy(self):
        """The failure this avoids: client_marquee silently drops entries missing a field. An absent
        compare-at is not a reason to render nothing."""
        html = render_price_highlight(SECTION, PLAIN, PRODUCTS)
        self.assertIn("$20.00", html)
        self.assertIn("Today Only", html)
        self.assertNotIn("<s>", html)

    def test_tiered_prices_are_qualified_as_a_range(self):
        # "as low as" is what stops a static block contradicting the interactive price selector.
        html = render_price_highlight(SECTION, TIERED, PRODUCTS)
        self.assertIn(FROM_PREFIX, html)
        self.assertIn("$24.22", html)

    def test_a_single_price_is_NOT_qualified(self):
        self.assertNotIn(FROM_PREFIX, render_price_highlight(SECTION, SINGLE, PRODUCTS))

    def test_it_carries_no_call_to_action(self):
        # Deliberate: checkout_cta is the ask. A second button here would compete with it.
        html = render_price_highlight(SECTION, SINGLE, PRODUCTS)
        for token in ("<a ", "<button", "href="):
            with self.subTest(token=token):
                self.assertNotIn(token, html)

    def test_an_offer_with_no_resolvable_price_renders_nothing(self):
        self.assertEqual(render_price_highlight(SECTION, {"items": [{"product_id": "missing"}]}, PRODUCTS), "")

    def test_copy_is_optional(self):
        html = render_price_highlight({"id": "ph"}, SINGLE, PRODUCTS)
        self.assertIn("$37.00", html)
        self.assertNotIn("sl-bargain-main", html)

    def test_a_section_override_carries_derived_ink(self):
        html = render_price_highlight({**SECTION, "theme": {"bg": "#1e1033"}}, SINGLE, PRODUCTS)
        self.assertIn("--sl-section-bg:#1e1033", html)
        self.assertIn("--sl-section-ink:#ffffff", html)

    def test_without_an_override_no_inline_style_is_emitted(self):
        self.assertNotIn("style=", render_price_highlight(SECTION, SINGLE, PRODUCTS))


if __name__ == "__main__":
    unittest.main()
