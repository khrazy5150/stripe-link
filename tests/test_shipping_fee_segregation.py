"""Who gets a cut of postage, and who does not.

The author's decision, 2026-09-30: the platform fee applies to **merchandise only**. `fees.fee_base` has
encoded that since the day it was decided -- and had NO CALLERS, so the webhook recomputed the whole split
from `amount_total` and recorded a platform fee the platform never took.

Pinned to a real dev order (2026-10-01): $56.79 projector + $5.98 USPS Ground Advantage = $62.77. Stripe's
own balance transaction for it reads application_fee 284, stripe_fee 212, net 5781. The stored record said
platform_fee 314 and net_payout 5750.
"""
import unittest

from handlers.stripe_webhook import fee_breakdown_from_invoice, fee_breakdown_from_session
from stripe_link.domain.fees import (
    DEFAULT_GLOBAL_BILLING_CONFIG,
    FEE_APPLIES_TO_SHIPPING,
    fee_base,
    settled_breakdown,
)

MERCH, SHIP = 5679, 598
TOTAL = MERCH + SHIP  # 6277
PRICE_KW = dict(currency="usd", product_type="physical", fee_handling="standard",
                pricing_model="one_time", tenant_plan="basic",
                billing_config=DEFAULT_GLOBAL_BILLING_CONFIG)


def a_session(shipping=SHIP, total=TOTAL):
    session = {"amount_total": total, "currency": "usd", "mode": "payment",
               "metadata": {"product_type": "physical", "tenant_plan": "basic"}}
    if shipping:
        session["shipping_cost"] = {"amount_total": shipping}
    return session


class TheRuleItself(unittest.TestCase):
    def test_the_platform_takes_no_cut_of_postage(self):
        self.assertFalse(FEE_APPLIES_TO_SHIPPING)
        self.assertEqual(fee_base(MERCH, shipping_amount=SHIP), MERCH)

    def test_the_rule_has_a_caller_now(self):
        # It had none. A decision encoded in a function nobody calls is a decision that did not happen.
        import inspect

        self.assertIn("fee_base(", inspect.getsource(settled_breakdown))


class SettledBreakdownTests(unittest.TestCase):
    def test_the_platform_fee_matches_what_stripe_actually_took(self):
        split = settled_breakdown(charged_amount=TOTAL, shipping_amount=SHIP, **PRICE_KW)
        self.assertEqual(split["platform_fee"], 284)

    def test_recomputing_from_the_gross_is_what_was_wrong(self):
        # The old behaviour, kept as a test so the difference is visible rather than asserted in prose.
        naive = settled_breakdown(charged_amount=TOTAL, shipping_amount=0, **PRICE_KW)
        self.assertEqual(naive["platform_fee"], 314)
        self.assertEqual(naive["platform_fee"] - 284, 30, "the fee on $5.98 of postage")

    def test_stripes_fee_still_applies_to_the_whole_charge(self):
        # Stripe processed the whole charge, postage included. Nothing to exempt.
        with_ship = settled_breakdown(charged_amount=TOTAL, shipping_amount=SHIP, **PRICE_KW)
        without = settled_breakdown(charged_amount=TOTAL, shipping_amount=0, **PRICE_KW)
        self.assertEqual(with_ship["stripe_fee"], without["stripe_fee"])

    def test_the_payout_comes_from_what_the_buyer_actually_paid(self):
        split = settled_breakdown(charged_amount=TOTAL, shipping_amount=SHIP, **PRICE_KW)
        self.assertEqual(split["tenant_keyed_amount"], TOTAL)
        self.assertEqual(split["net_payout"], TOTAL - split["stripe_fee"] - split["platform_fee"])

    def test_the_tenant_keeps_the_postage_they_charged(self):
        # The whole point: $5.98 collected for shipping reaches the tenant minus Stripe's cut only.
        with_ship = settled_breakdown(charged_amount=TOTAL, shipping_amount=SHIP, **PRICE_KW)
        merch_only = settled_breakdown(charged_amount=MERCH, shipping_amount=0, **PRICE_KW)
        self.assertEqual(with_ship["platform_fee"], merch_only["platform_fee"])

    def test_no_shipping_is_unchanged(self):
        self.assertEqual(settled_breakdown(charged_amount=MERCH, shipping_amount=0, **PRICE_KW),
                         settled_breakdown(charged_amount=MERCH, **PRICE_KW))

    def test_shipping_larger_than_the_charge_cannot_go_negative(self):
        split = settled_breakdown(charged_amount=500, shipping_amount=900, **PRICE_KW)
        self.assertGreaterEqual(split["platform_fee"], 0)
        self.assertGreaterEqual(split["net_payout"], 0)


class TheWebhookRecordsIt(unittest.TestCase):
    def test_a_session_with_postage_records_the_merchandise_fee(self):
        self.assertEqual(fee_breakdown_from_session(a_session())["platform_fee"], 284)

    def test_the_stored_record_now_agrees_with_the_charge(self):
        # Stripe's balance transaction for the real order: application_fee 284, net 5781. The stripe_fee
        # here is an ESTIMATE (213 vs Stripe's actual 212, a rounding difference that predates this), so
        # the payout lands within a cent rather than exactly.
        split = fee_breakdown_from_session(a_session())
        self.assertEqual(split["platform_fee"], 284)
        self.assertAlmostEqual(split["net_payout"], 5781, delta=2)

    def test_a_session_without_postage_is_untouched(self):
        self.assertEqual(fee_breakdown_from_session(a_session(shipping=0, total=MERCH))["platform_fee"],
                         settled_breakdown(charged_amount=MERCH, **PRICE_KW)["platform_fee"])

    def test_a_renewal_applies_the_same_exemption(self):
        # Subscriptions charge no postage today, so this is a no-op -- applied anyway so the day recurring
        # shipping ships, it does not need remembering.
        invoice = {"amount_paid": TOTAL, "currency": "usd", "shipping_cost": {"amount_total": SHIP}}
        split = fee_breakdown_from_invoice(invoice, {"product_type": "physical", "tenant_plan": "basic"})
        self.assertLess(split["platform_fee"], 314)


class WhatGoesWhereTests(unittest.TestCase):
    """Segregation, stated once: three amounts, three homes."""

    def test_the_buyers_postage_is_recorded_apart_from_merchandise(self):
        from stripe_link.domain.shipping_charges import buyer_paid_shipping

        self.assertEqual(buyer_paid_shipping(a_session())["shipping_amount"], SHIP)

    def test_the_ledger_carries_shipping_as_its_own_component(self):
        from stripe_link.domain.ledger import BREAKDOWN_COMPONENTS

        self.assertIn("shipping_revenue", BREAKDOWN_COMPONENTS)
