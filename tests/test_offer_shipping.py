"""What outbound shipping costs the BUYER.

plans/SHIPPING_CHARGES.md. The author's point that settled the design, 2026-09-30: *"You need two (charged /
free) because shipping could vary (ground, 2-day shipping, overnight) and those costs can't be baked in."*

Shipping speed is a BUYER's choice, so this is a LIST of priced options rather than an amount, and there is no
`baked` mode -- a price fixed before the buyer chooses cannot contain a cost that depends on what they pick.
"""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_offer_shipping
from stripe_link.domain.shipping_charges import (
    CHARGED,
    FREE,
    MAX_OPTIONS,
    baseline_option,
    mode_for,
    options_for,
    smart_pricing_conflict,
    stripe_shipping_options,
)

GROUND = {"label": "Ground (5-7 days)", "amount": 0, "service_token": "usps_ground_advantage"}
TWO_DAY = {"label": "2-day", "amount": 1200, "transit_days_min": 2, "transit_days_max": 2}
OVERNIGHT = {"label": "Overnight", "amount": 2500, "transit_days_min": 1, "transit_days_max": 1}


def offer(**shipping):
    return {"shipping": shipping} if shipping else {}


class ServiceLevels(unittest.TestCase):
    def test_options_come_back_cheapest_first(self):
        result = options_for(offer(options=[OVERNIGHT, GROUND, TWO_DAY]))
        self.assertEqual([o["amount"] for o in result], [0, 1200, 2500])

    def test_the_service_token_survives(self):
        """Same vocabulary as domain/rate_policy.py, so the option a buyer chose can be tied to the rate the
        tenant buys. A second vocabulary for the same thing is how drift starts."""
        self.assertEqual(options_for(offer(options=[GROUND]))[0]["service_token"], "usps_ground_advantage")

    def test_no_shipping_block_offers_nothing(self):
        self.assertEqual(options_for({}), [])
        self.assertEqual(options_for(None), [])

    def test_a_nameless_option_is_dropped(self):
        """An option with no label is a blank radio button on a checkout page."""
        self.assertEqual(options_for(offer(options=[{"amount": 500}, GROUND])), [{"label": GROUND["label"],
                                                                                 "amount": 0,
                                                                                 "service_token": GROUND["service_token"]}])

    def test_a_negative_amount_is_dropped(self):
        """It would pay the buyer to receive goods."""
        self.assertEqual(options_for(offer(options=[{"label": "Odd", "amount": -100}])), [])

    def test_decimal_amounts_from_dynamo(self):
        from decimal import Decimal
        result = options_for(offer(options=[{"label": "Ground", "amount": Decimal("800")}]))
        self.assertEqual(result[0]["amount"], 800)

    def test_the_five_option_cap_is_enforced(self):
        many = [{"label": f"Option {i}", "amount": i * 100} for i in range(1, 9)]
        self.assertEqual(len(options_for(offer(options=many))), MAX_OPTIONS)


class ModeIsDerived(unittest.TestCase):
    def test_all_zero_is_free(self):
        self.assertEqual(mode_for(offer(options=[GROUND])), FREE)

    def test_any_priced_option_is_charged(self):
        self.assertEqual(mode_for(offer(options=[GROUND, OVERNIGHT])), CHARGED)

    def test_no_options_is_free(self):
        """Nothing is being charged."""
        self.assertEqual(mode_for({}), FREE)

    def test_a_stored_mode_contradicting_its_options_is_refused(self):
        """A stored summary of other fields is a second place for the same fact to be wrong."""
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"mode": FREE, "options": [OVERNIGHT]})
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"mode": CHARGED, "options": [GROUND]})

    def test_an_agreeing_mode_passes(self):
        validate_offer_shipping({"mode": CHARGED, "options": [GROUND, OVERNIGHT]})
        validate_offer_shipping({"mode": FREE, "options": [GROUND]})


class FreeAboveThreshold(unittest.TestCase):
    def test_the_baseline_becomes_free(self):
        result = options_for(offer(options=[{"label": "Ground", "amount": 800}, OVERNIGHT],
                                  free_above_amount=5000), merchandise_amount=5000)
        self.assertEqual(result[0]["amount"], 0)
        self.assertEqual(result[0]["free_reason"], "order_total")

    def test_the_upgrades_are_untouched(self):
        """A threshold that also freed overnight would give away the premium the buyer was willing to pay
        for, and no merchant means that by "free shipping over $50"."""
        result = options_for(offer(options=[{"label": "Ground", "amount": 800}, OVERNIGHT],
                                  free_above_amount=5000), merchandise_amount=5000)
        self.assertEqual(result[1]["amount"], 2500)

    def test_below_the_threshold_nothing_changes(self):
        result = options_for(offer(options=[{"label": "Ground", "amount": 800}],
                                  free_above_amount=5000), merchandise_amount=4999)
        self.assertEqual(result[0]["amount"], 800)

    def test_the_offer_is_not_mutated(self):
        """A pure function that edits what it was handed makes the second call disagree with the first."""
        source = offer(options=[{"label": "Ground", "amount": 800}], free_above_amount=1000)
        options_for(source, merchandise_amount=5000)
        self.assertEqual(source["shipping"]["options"][0]["amount"], 800)


class TheSmartPricingInvariant(unittest.TestCase):
    """The BASELINE option's cost may sit in the cost profile only when that option is FREE to the buyer."""

    SHIPPING_LINE = {"lines": [{"label": "Shipping to customer", "kind": "fixed", "amount": 400}]}

    def test_paid_baseline_plus_a_cost_line_is_the_double_count(self):
        conflict = smart_pricing_conflict(offer(options=[{"label": "Ground", "amount": 800}]),
                                          self.SHIPPING_LINE)
        self.assertIn("twice", conflict)

    def test_free_ground_with_paid_overnight_is_allowed(self):
        """An ordinary offer: the tenant absorbs the baseline and may price it in, while the upgrade is pure
        buyer-paid revenue."""
        self.assertEqual(smart_pricing_conflict(offer(options=[GROUND, OVERNIGHT]), self.SHIPPING_LINE), "")

    def test_a_paid_baseline_with_no_cost_line_is_fine(self):
        self.assertEqual(smart_pricing_conflict(offer(options=[OVERNIGHT]), {"lines": []}), "")

    def test_inbound_freight_is_not_outbound_shipping(self):
        """Acquisition cost (plans/INVENTORY_COST_BASIS.md) is never charged to a buyer, so it can coexist
        with a paid shipping option."""
        profile = {"lines": [{"label": "Inbound freight", "kind": "fixed", "amount": 150}]}
        self.assertEqual(smart_pricing_conflict(offer(options=[OVERNIGHT]), profile), "")

    def test_a_threshold_that_frees_the_baseline_clears_the_conflict(self):
        conflict = smart_pricing_conflict(
            offer(options=[{"label": "Ground", "amount": 800}], free_above_amount=5000),
            self.SHIPPING_LINE, merchandise_amount=5000)
        self.assertEqual(conflict, "")

    def test_a_percentage_line_is_not_a_shipping_cost(self):
        profile = {"lines": [{"label": "Shipping surcharge", "kind": "pct_of_price", "rate": 0.02}]}
        self.assertEqual(smart_pricing_conflict(offer(options=[OVERNIGHT]), profile), "")


class Validation(unittest.TestCase):
    def test_absent_is_fine(self):
        validate_offer_shipping(None)

    def test_options_must_be_an_array(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": {"label": "Ground"}})

    def test_more_than_five_is_refused_at_save_time(self):
        """Stripe rejects the session, and a refused session is a lost sale. Better the tenant hears it than
        the buyer at the pay button."""
        many = [{"label": f"Option {i}", "amount": i * 100} for i in range(1, 7)]
        with self.assertRaises(DocumentValidationError) as caught:
            validate_offer_shipping({"options": many})
        self.assertIn("Stripe", str(caught.exception))

    def test_a_label_is_required(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"amount": 500}]})

    def test_an_amount_is_required(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"label": "Ground"}]})

    def test_duplicate_labels_are_refused(self):
        """Two identically named options are indistinguishable, so the buyer chooses at random."""
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"label": "Ground", "amount": 0},
                                                 {"label": "Ground", "amount": 900}]})

    def test_transit_days_must_not_invert(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"label": "Ground", "amount": 0,
                                                  "transit_days_min": 5, "transit_days_max": 2}]})

    def test_a_negative_amount_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"label": "Ground", "amount": -1}]})

    def test_an_unknown_mode_is_refused(self):
        """`baked` is deliberately not a mode: see the module docstring."""
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"mode": "baked", "options": [GROUND]})


class TheStripePayload(unittest.TestCase):
    def test_it_is_shaped_the_way_checkout_wants(self):
        payload = stripe_shipping_options(offer(options=[GROUND, OVERNIGHT]), currency="USD")
        self.assertEqual(payload[0]["shipping_rate_data"]["type"], "fixed_amount")
        self.assertEqual(payload[0]["shipping_rate_data"]["fixed_amount"],
                         {"amount": 0, "currency": "usd"})
        self.assertEqual(payload[0]["shipping_rate_data"]["display_name"], GROUND["label"])

    def test_transit_days_become_a_delivery_estimate(self):
        estimate = stripe_shipping_options(offer(options=[OVERNIGHT]))[0]["shipping_rate_data"]["delivery_estimate"]
        self.assertEqual(estimate["minimum"], {"unit": "business_day", "value": 1})
        self.assertEqual(estimate["maximum"], {"unit": "business_day", "value": 1})

    def test_no_transit_days_means_no_estimate_key(self):
        data = stripe_shipping_options(offer(options=[GROUND]))[0]["shipping_rate_data"]
        self.assertNotIn("delivery_estimate", data)

    def test_never_more_than_stripe_accepts(self):
        many = [{"label": f"Option {i}", "amount": i * 100} for i in range(1, 9)]
        self.assertEqual(len(stripe_shipping_options(offer(options=many))), MAX_OPTIONS)


if __name__ == "__main__":
    unittest.main()
