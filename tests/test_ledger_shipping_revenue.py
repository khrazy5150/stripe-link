"""Shipping revenue in the ledger: a PARTITION of gross, never an addition to it.

plans/SHIPPING_CHARGES.md phase 5. `gross` is `session.amount_total`, which already contains what the buyer
paid for postage — so total profit was never wrong. What could not be done was SEPARATING shipping revenue
from product revenue, which is the only way to see shipping margin.

The tests that matter most are the ones asserting `net` and `profit` do NOT move. A breakdown key living
alongside additive components is an invitation to sum it, and summing this one counts the postage twice.
"""
import unittest

from stripe_link.domain.ledger import (
    AMOUNT_COMPONENTS,
    BREAKDOWN_COMPONENTS,
    _entry,
    refund_entry,
    sale_entry,
    sale_entry_from_order,
    summarize,
)


def sale(**kwargs):
    base = dict(tenant_id="t1", entry_id="le_1", occurred_at=100, mode="test", currency="usd",
                gross=5795, stripe_fee=198, platform_fee=116, idempotency_key="sale:1")
    base.update(kwargs)
    return sale_entry(**base)


def carrier_cost(amount):
    return _entry(tenant_id="t1", entry_id="le_cost", entry_type="shipping_cost", occurred_at=200,
                  mode="test", currency="usd", amounts={"shipping_cost": -abs(amount)},
                  idempotency_key="cost:1")


class ItIsAPartitionNotAnAddition(unittest.TestCase):
    def test_net_is_unchanged_by_its_presence(self):
        """The postage is already inside gross."""
        self.assertEqual(summarize([sale(shipping_revenue=795)])["net"], summarize([sale()])["net"])

    def test_profit_is_unchanged_by_its_presence(self):
        self.assertEqual(summarize([sale(shipping_revenue=795)])["profit"], summarize([sale()])["profit"])

    def test_it_is_not_in_the_additive_tuple(self):
        """The module's contract is that every AMOUNT_COMPONENT is additive from the tenant's-cash
        perspective. A breakdown key in that list is an invitation for the next person to sum it."""
        for key in BREAKDOWN_COMPONENTS:
            self.assertNotIn(key, AMOUNT_COMPONENTS)

    def test_it_never_exceeds_gross(self):
        totals = summarize([sale(shipping_revenue=795)])["totals"]
        self.assertLessEqual(totals["shipping_revenue"], totals["gross"])


class WhatItMakesPossible(unittest.TestCase):
    def test_shipping_revenue_is_reported(self):
        self.assertEqual(summarize([sale(shipping_revenue=795)])["shipping_revenue"], 795)

    def test_the_margin_is_None_when_the_CARRIER_cost_is_unknown(self):
        """`shipping_cost` has no source until a label is bought. Returning `revenue + 0` would publish a
        margin implying postage was free -- the same shape as the `tax_liability` bug (plans/TODO.md), a
        figure that looks authoritative and is structurally always wrong."""
        self.assertIsNone(summarize([sale(shipping_revenue=795)])["shipping_margin"])

    def test_the_margin_appears_once_BOTH_halves_exist(self):
        summary = summarize([sale(shipping_revenue=795), carrier_cost(600)])
        self.assertEqual(summary["shipping_margin"], 195)

    def test_a_margin_can_be_negative_and_is_not_clamped(self):
        """A tenant undercharging for postage is exactly what this figure exists to reveal."""
        self.assertEqual(summarize([sale(shipping_revenue=500), carrier_cost(900)])["shipping_margin"], -400)

    def test_no_shipping_at_all_reports_zero_revenue_and_no_margin(self):
        summary = summarize([sale()])
        self.assertEqual(summary["shipping_revenue"], 0)
        self.assertIsNone(summary["shipping_margin"])


class Refunds(unittest.TestCase):
    def test_a_refund_reverses_the_shipping_it_returned(self):
        entry = refund_entry(tenant_id="t1", entry_id="le_r", occurred_at=300, mode="test", currency="usd",
                             refund_amount=5795, shipping_reversed=795, idempotency_key="refund:1")
        self.assertEqual(entry["amounts"]["shipping_revenue"], -795)

    def test_a_full_refund_nets_shipping_revenue_to_zero(self):
        entry = refund_entry(tenant_id="t1", entry_id="le_r", occurred_at=300, mode="test", currency="usd",
                             refund_amount=5795, shipping_reversed=795, idempotency_key="refund:1")
        self.assertEqual(summarize([sale(shipping_revenue=795), entry])["shipping_revenue"], 0)

    def test_the_caller_decides_how_much_shipping_came_back(self):
        """A partial refund cannot be attributed between goods and shipping from the amount alone, and
        guessing would make shipping margin quietly wrong for every partially refunded order."""
        entry = refund_entry(tenant_id="t1", entry_id="le_r", occurred_at=300, mode="test", currency="usd",
                             refund_amount=1000, idempotency_key="refund:1")
        self.assertNotIn("shipping_revenue", entry["amounts"])


class FromAnOrderDocument(unittest.TestCase):
    def order(self, **kwargs):
        base = {"tenant_id": "t1", "order_id": "order_1", "payment_intent_id": "pi_1",
                "amount_total": 5795, "currency": "usd", "stripe_mode": "test", "created_at": 100}
        base.update(kwargs)
        return base

    def test_it_reads_shipping_amount_off_the_order(self):
        """Written by shipping_charges.buyer_paid_shipping on both order paths."""
        entry = sale_entry_from_order(self.order(shipping_amount=795), now_epoch=100)
        self.assertEqual(entry["amounts"]["shipping_revenue"], 795)

    def test_a_digital_order_has_no_shipping_key_and_that_is_fine(self):
        entry = sale_entry_from_order(self.order(), now_epoch=100)
        self.assertNotIn("shipping_revenue", entry["amounts"])
        self.assertEqual(entry["amounts"]["gross"], 5795)

    def test_free_shipping_records_no_revenue_but_still_sells(self):
        entry = sale_entry_from_order(self.order(shipping_amount=0), now_epoch=100)
        self.assertNotIn("shipping_revenue", entry["amounts"])
        self.assertEqual(entry["amounts"]["gross"], 5795)


class TheValidatorAcceptsWhatTheBuildersProduce(unittest.TestCase):
    """A validator that refuses its own builders' output is a guard pointed the wrong way.

    The hand-written component list in `documents.py` rejected `shipping_revenue` the moment the ledger
    learned to record it. Nothing called the validator, so nothing broke -- which is why it would have gone
    unnoticed until someone wired it in and every physical sale started failing validation.
    """

    def _check(self, entry):
        from stripe_link.domain.documents import validate_ledger_entry
        validate_ledger_entry(entry)

    def test_a_sale_with_shipping_validates(self):
        self._check(sale(shipping_revenue=795))

    def test_a_refund_reversing_shipping_validates(self):
        self._check(refund_entry(tenant_id="t1", entry_id="le_r", occurred_at=300, mode="test",
                                 currency="usd", refund_amount=5795, shipping_reversed=795,
                                 idempotency_key="refund:1"))

    def test_the_allowed_set_is_derived_not_restated(self):
        from stripe_link.domain.documents import _ledger_amount_components
        self.assertEqual(_ledger_amount_components(),
                         set(AMOUNT_COMPONENTS) | set(BREAKDOWN_COMPONENTS))

    def test_an_invented_component_is_still_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_ledger_entry
        entry = sale(shipping_revenue=795)
        entry["amounts"]["vibes"] = 1
        with self.assertRaises(DocumentValidationError):
            validate_ledger_entry(entry)


if __name__ == "__main__":
    unittest.main()
