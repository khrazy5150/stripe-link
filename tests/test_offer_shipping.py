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
    buyer_paid_shipping,
    FREE,
    MAX_OPTIONS,
    SHIPPING_TAX_CODE,
    baseline_option,
    mode_for,
    options_for,
    resolve_amount,
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
        result = options_for(offer(options=[{"amount": 500}, GROUND]))
        self.assertEqual([o["label"] for o in result], [GROUND["label"]])

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


class PricingRules(unittest.TestCase):
    """The author, 2026-09-30: shipping rules may be *"free, flat rate, per item, threshold-based,
    weight-based, potentially carrier-derived"* -- and Stripe's own Shipping Rate is a FIXED amount, so the
    rule has to be resolved to a number before Stripe sees it.
    """

    PER_UNIT = {"label": "Ground", "kind": "per_item", "amount": 200, "first_item_amount": 795}

    def test_per_item_scales_with_the_cart(self):
        self.assertEqual(resolve_amount(self.PER_UNIT, item_count=1), 795)
        self.assertEqual(resolve_amount(self.PER_UNIT, item_count=3), 1195)

    def test_per_item_without_a_first_item_price_is_simple_multiplication(self):
        self.assertEqual(resolve_amount({"kind": "per_item", "amount": 200}, item_count=4), 800)

    def test_flat_ignores_the_cart(self):
        self.assertEqual(resolve_amount({"kind": "flat", "amount": 795}, item_count=9), 795)

    def test_an_empty_cart_still_charges_for_one(self):
        """A zero-item cart cannot reach checkout, and multiplying by zero would ship it free."""
        self.assertEqual(resolve_amount(self.PER_UNIT, item_count=0), 795)

    def test_rules_are_resolved_BEFORE_sorting(self):
        """With per-item pricing the cheapest option depends on the cart, so sorting on the stored amount
        would order them wrongly for a basket of six."""
        cheap_flat = {"label": "Flat", "amount": 1000}
        result = options_for(offer(options=[self.PER_UNIT, cheap_flat]), item_count=6)
        self.assertEqual([o["label"] for o in result], ["Flat", "Ground"])
        self.assertEqual(result[1]["amount"], 795 + 200 * 5)

    def test_the_mode_follows_the_resolved_amount(self):
        free_per_item = {"label": "Ground", "kind": "per_item", "amount": 0}
        self.assertEqual(mode_for(offer(options=[free_per_item]), item_count=5), FREE)


class TheTaxClassification(unittest.TestCase):
    def test_the_shipping_tax_code_is_always_sent(self):
        """Without it shipping reaches Stripe Tax as an unclassified amount rather than as shipping."""
        rate = stripe_shipping_options(offer(options=[GROUND]))[0]["shipping_rate_data"]
        self.assertEqual(rate["tax_code"], SHIPPING_TAX_CODE)

    def test_a_tenants_own_tax_code_wins(self):
        rate = stripe_shipping_options(offer(options=[dict(GROUND, tax_code="txcd_00000000")]))[0]["shipping_rate_data"]
        self.assertEqual(rate["tax_code"], "txcd_00000000")

    def test_tax_behavior_is_never_defaulted(self):
        """Whether tax is added on top of the postage or taken out of it is the tenant's decision; guessing
        would silently decide who bears it."""
        rate = stripe_shipping_options(offer(options=[GROUND]))[0]["shipping_rate_data"]
        self.assertNotIn("tax_behavior", rate)

    def test_tax_behavior_is_passed_through_when_set(self):
        rate = stripe_shipping_options(offer(options=[dict(OVERNIGHT, tax_behavior="exclusive")]))[0]["shipping_rate_data"]
        self.assertEqual(rate["tax_behavior"], "exclusive")

    def test_an_unknown_tax_behavior_is_refused_at_save(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [dict(GROUND, tax_behavior="sometimes")]})


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

    def test_an_unknown_pricing_kind_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [dict(GROUND, kind="weight_band")]})

    def test_a_first_item_price_on_a_flat_rate_is_refused(self):
        """The calculator ignores it, which means the tenant typed a number that does nothing."""
        with self.assertRaises(DocumentValidationError):
            validate_offer_shipping({"options": [{"label": "Ground", "amount": 500,
                                                  "first_item_amount": 900}]})
        validate_offer_shipping({"options": [{"label": "Ground", "amount": 500, "kind": "per_item",
                                              "first_item_amount": 900}]})

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


class WhatTheBuyerActuallyPaid(unittest.TestCase):
    """`options_for` decides what to OFFER; this records what was CHOSEN.

    It is a read rather than a calculation because the amount cannot be known at session-creation time -- the
    buyer picks the service level, so the figure only exists once Stripe reports it.
    """

    def test_it_reads_the_shipping_cost_block(self):
        paid = buyer_paid_shipping({"shipping_cost": {"amount_total": 795, "amount_tax": 64,
                                                     "shipping_rate": "shr_1"}})
        self.assertEqual(paid["shipping_amount"], 795)
        self.assertEqual(paid["shipping_tax"], 64)
        self.assertEqual(paid["shipping_rate_id"], "shr_1")

    def test_shipping_tax_is_kept_separate(self):
        """The fee base excludes shipping while tax may include it -- two independent rules over the same
        money, so they cannot share a field."""
        paid = buyer_paid_shipping({"shipping_cost": {"amount_total": 795, "amount_tax": 64}})
        self.assertNotEqual(paid["shipping_amount"], paid["shipping_tax"])

    def test_a_digital_order_reports_NOTHING_not_zero(self):
        """A stored `shipping_amount: 0` would claim shipping was offered and the buyer declined to pay."""
        self.assertEqual(buyer_paid_shipping({"total_details": {"amount_discount": 0}}), {})
        self.assertEqual(buyer_paid_shipping({}), {})
        self.assertEqual(buyer_paid_shipping(None), {})

    def test_free_shipping_DOES_report_zero(self):
        """Stripe reported a shipping line of zero, which is a different fact from no shipping at all."""
        self.assertEqual(buyer_paid_shipping({"shipping_cost": {"amount_total": 0}}),
                         {"shipping_amount": 0})

    def test_total_details_is_the_fallback(self):
        """Same figure in a different place. The fallback, not the primary, because shipping_cost appears on
        invoices as well as sessions."""
        self.assertEqual(buyer_paid_shipping({"total_details": {"amount_shipping": 500}}),
                         {"shipping_amount": 500})

    def test_an_expanded_rate_yields_the_service_name(self):
        """Which service the buyer bought matters operationally: one who paid for overnight must not be
        posted second class."""
        paid = buyer_paid_shipping({"shipping_cost": {"amount_total": 1200,
                                                     "shipping_rate": {"id": "shr_2",
                                                                       "display_name": "2-day"}}})
        self.assertEqual(paid["shipping_service"], "2-day")
        self.assertEqual(paid["shipping_rate_id"], "shr_2")

    def test_the_carrier_cost_is_never_read_from_stripe(self):
        """order.shipping_cost is what the CARRIER charged us. Nobody knows it until a label is bought, which
        may be days later and may never happen -- so it is absent here, not zero."""
        paid = buyer_paid_shipping({"shipping_cost": {"amount_total": 795}})
        self.assertNotIn("shipping_cost", paid)

    def test_decimals_survive(self):
        from decimal import Decimal
        self.assertEqual(buyer_paid_shipping({"shipping_cost": {"amount_total": Decimal("795")}}),
                         {"shipping_amount": 795})


if __name__ == "__main__":
    unittest.main()
