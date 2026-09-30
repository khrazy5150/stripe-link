"""What the platform fee is charged on, stated once.

plans/SHIPPING_CHARGES.md. The author, 2026-09-30: *"I would not let Stripe's resulting transaction amount
implicitly determine this. Make it an explicit JuniorBay rule."*

DECIDED: shipping is EXCLUDED. `fee_base = merchandise_amount - discounts`.

Before this the answer was an accident -- fees were computed per line item and no shipping amount existed, so
shipping happened to be excluded with nothing anywhere saying so. These tests exist so that reversing the
decision is a deliberate act that fails loudly, rather than a side effect of adding a shipping line somewhere.
"""
import unittest
from decimal import Decimal

from stripe_link.domain.fees import (
    FEE_APPLIES_TO_SHIPPING,
    application_fee_percent,
    fee_base,
)


class TheRuleIsExplicit(unittest.TestCase):
    def test_the_decision_is_a_named_constant(self):
        """If this flips, every test below changes with it -- deliberately, not by accident."""
        self.assertFalse(FEE_APPLIES_TO_SHIPPING)

    def test_shipping_is_not_in_the_base(self):
        self.assertEqual(fee_base(5000, shipping_amount=800), 5000)

    def test_discounts_come_off(self):
        self.assertEqual(fee_base(5000, shipping_amount=800, discounts=1000), 4000)

    def test_a_discount_bigger_than_the_goods_floors_at_zero(self):
        """A negative fee base would make the platform pay the tenant."""
        self.assertEqual(fee_base(1000, discounts=5000), 0)

    def test_shipping_only_order_owes_nothing(self):
        self.assertEqual(fee_base(0, shipping_amount=2000), 0)

    def test_the_carrier_cost_is_never_a_parameter(self):
        """`order.shipping_cost` is the tenant's own cost. The platform fee is a share of what the BUYER
        paid, and what the carrier charged the tenant is none of the platform's business."""
        import inspect
        self.assertNotIn("shipping_cost", inspect.signature(fee_base).parameters)


class TheSubscriptionPercentTrap(unittest.TestCase):
    """Stripe has no application_fee_amount on a subscription -- only a PERCENT, applied to each invoice's
    whole total. So the denominator must include shipping or the absolute fee comes out wrong.

    This is the trap that made the rule worth settling before Checkout was wired: `checkout.py` divided by the
    merchandise subtotal, so adding a shipping line would have charged a fee on postage on every renewal,
    with nothing in the code contradicting itself.
    """

    def test_no_shipping_behaves_as_before(self):
        self.assertEqual(application_fee_percent(100, 5000), Decimal("2.00"))

    def test_the_percent_scales_so_the_absolute_fee_is_unchanged(self):
        merchandise, shipping = 5000, 800
        fee = 100  # 2% of merchandise, which is the whole fee base
        percent = application_fee_percent(fee, merchandise + shipping)
        charged = (percent / Decimal("100")) * Decimal(merchandise + shipping)
        self.assertAlmostEqual(float(charged), float(fee), places=0)

    def test_dividing_by_merchandise_alone_would_overcharge(self):
        """The bug this replaces, made explicit: the naive percent applied to the real total takes MORE than
        the fee base allows."""
        merchandise, shipping, fee = 5000, 800, 100
        naive = (Decimal(fee) / Decimal(merchandise)) * Decimal("100")
        overcharged = (naive / Decimal("100")) * Decimal(merchandise + shipping)
        self.assertGreater(overcharged, Decimal(fee))
        self.assertAlmostEqual(float(overcharged), 116.0, places=0)

    def test_two_decimal_places_because_stripe_rejects_more(self):
        """A four-decimal fee Stripe refuses costs the entire sale."""
        percent = application_fee_percent(137, 2731)
        self.assertEqual(percent.as_tuple().exponent, -2)

    def test_zero_is_zero_not_a_division_error(self):
        self.assertEqual(application_fee_percent(0, 5000), Decimal("0.00"))
        self.assertEqual(application_fee_percent(100, 0), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
