"""P3: `free_above_amount` finally has a control.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md. The engine has honoured it since zones shipped --
`shipping_charges.options_for` frees the BASELINE option above the threshold -- and no screen could set
it, so no tenant could offer the one shipping promise every other platform makes.
"""
import pathlib
import unittest

from stripe_link.domain.shipping_charges import options_for

ROOT = pathlib.Path(__file__).resolve().parents[1]
OFFERS = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")

OFFER = {"shipping": {"eligible": True, "free_above_amount": 5000,
                      "options": [{"label": "Ground", "amount": 700},
                                  {"label": "Overnight", "amount": 2500}]}}


class TheEngineAlreadyDidThisTests(unittest.TestCase):
    def test_a_big_enough_order_frees_the_baseline(self):
        options = options_for(OFFER, merchandise_amount=6000)
        self.assertEqual(options[0]["amount"], 0)

    def test_a_small_order_still_pays(self):
        self.assertEqual(options_for(OFFER, merchandise_amount=1000)[0]["amount"], 700)

    def test_only_the_BASELINE_is_freed(self):
        # A threshold that also freed overnight would give away the expensive half of the menu.
        options = options_for(OFFER, merchandise_amount=6000)
        self.assertEqual(options[1]["amount"], 2500)


class TheControlExistsTests(unittest.TestCase):
    def test_the_offer_form_can_set_it(self):
        self.assertIn("form.shipping.free_above_amount", OFFERS)
        self.assertIn("Free shipping over", OFFERS)

    def test_a_threshold_saves_even_with_no_override(self):
        # "Use my zones, but free over $50" is the commonest shape there is; returning undefined whenever
        # the override was "none" would silently drop it.
        block = OFFERS.split("function buildShippingBlock", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn('if ((!override || override === "none") && !threshold) return undefined;', block)
        self.assertIn("block.free_above_amount = threshold", block)

    def test_it_is_stored_in_cents_like_every_other_amount(self):
        block = OFFERS.split("function buildShippingBlock", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("toCents(form.shipping.free_above_amount)", block)

    def test_it_reads_back_into_the_form(self):
        self.assertIn("free_above_amount: shipping.free_above_amount", OFFERS)

    def test_the_tenant_is_told_what_it_costs_them(self):
        # A threshold is a promise to lose MORE the more a buyer buys, unless the cost was recovered in
        # the price. The number looks free either way, which is exactly why it has to be said.
        self.assertIn("Bigger orders cost you more to post", OFFERS)
        self.assertIn("comes out of your margin", OFFERS)

    def test_the_validator_already_accepted_it(self):
        source = (ROOT / "src/stripe_link/domain/documents.py").read_text(encoding="utf-8")
        self.assertIn('optional_non_negative_int(shipping, "free_above_amount"', source)
