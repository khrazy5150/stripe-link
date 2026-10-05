"""Postage folded into an order bump's price, and tracked back out of it.

A pre-purchase order bump is ticked by the buyer on Stripe's own hosted Checkout page, as an
`optional_items` line. That happens strictly AFTER `shipping_options` are fixed at session creation, and
Stripe cannot re-rate shipping when an optional item is added — so a bump's size and weight never reach
the postage quote.

Measured on a real order (2026-10-05): a cart quoted at 620c needed a bigger box and cost 669c once the
bump was in it, and the tenant absorbed the 49c. The same cart with five bump units cost 1354c against
the same 620c quote. Box sizes are cliffs, so the exposure is not bounded by pennies.

`shipping_surcharge` closes that gap the only way `optional_items` allow: by riding inside the bump's own
pre-synced Stripe Price, so only the buyers who TAKE the bump pay it.
"""
import unittest

from handlers.checkout import order_bump_optional_items
from handlers.stripe_webhook import (
    bump_postage_collected,
    bump_postage_from_metadata,
    order_line_items_from_stripe,
)
from stripe_link.domain.ledger import sale_entry_from_order


BUMP_PRICE = "price_stripe_bump"


def _offer():
    return {"offer_id": "offer_1", "funnel": {"order_bumps": [{"product_id": "prod_1", "price_id": "pr_bump"}]}}


def _products(surcharge=49):
    price = {"price_id": "pr_bump", "currency": "usd", "unit_amount": 953,
             "context": "order_bump", "stripe_price_id": BUMP_PRICE}
    if surcharge is not None:
        price["shipping_surcharge"] = surcharge
    return {"prod_1": {"product_id": "prod_1", "stripe_mode": "test", "prices": [price]}}


class BumpSurchargeResolutionTests(unittest.TestCase):
    def test_the_resolver_reports_the_surcharge_alongside_the_price(self):
        bumps = order_bump_optional_items(_offer(), _products(49), "test")
        self.assertEqual(bumps, [(BUMP_PRICE, "pr_bump", 49)])

    def test_a_bump_without_a_surcharge_reports_zero(self):
        bumps = order_bump_optional_items(_offer(), _products(None), "test")
        self.assertEqual(bumps, [(BUMP_PRICE, "pr_bump", 0)])


class BumpPostageMetadataTests(unittest.TestCase):
    def test_round_trips_a_single_bump(self):
        self.assertEqual(bump_postage_from_metadata(f"{BUMP_PRICE}:49"), {BUMP_PRICE: 49})

    def test_round_trips_several(self):
        self.assertEqual(
            bump_postage_from_metadata("price_a:49,price_b:120"), {"price_a": 49, "price_b": 120})

    def test_an_absent_stamp_is_no_postage(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(bump_postage_from_metadata(raw), {})

    def test_a_malformed_pair_is_skipped_not_raised(self):
        """Classification must never cost the order.

        This stamp decides whether an amount is recorded as postage or as merchandise. Nothing about it
        should be able to stop a paid order being written, so a junk pair is dropped and the rest stands.
        """
        self.assertEqual(bump_postage_from_metadata("price_a:nope,price_b:120"), {"price_b": 120})


class BumpPostageCollectedTests(unittest.TestCase):
    def _lines(self, quantity=1, taken=True):
        stripe_lines = [
            {"description": "Creatine Gummies", "amount_total": 3900, "quantity": 1,
             "price": {"id": "price_main"}},
        ]
        if taken:
            stripe_lines.append({"description": "Protein Shaker Bottle", "amount_total": 1002 * quantity,
                                 "quantity": quantity, "price": {"id": BUMP_PRICE}})
        return order_line_items_from_stripe(stripe_lines, {BUMP_PRICE}, "usd")

    def test_counts_the_surcharge_when_the_bump_was_taken(self):
        self.assertEqual(bump_postage_collected(self._lines(), {BUMP_PRICE: 49}), 49)

    def test_counts_nothing_when_the_bump_was_declined(self):
        """The whole point of charging it this way: decliners are untouched."""
        self.assertEqual(bump_postage_collected(self._lines(taken=False), {BUMP_PRICE: 49}), 0)

    def test_scales_with_quantity(self):
        """The surcharge is per unit because the parcel growth that justified it is per unit."""
        self.assertEqual(bump_postage_collected(self._lines(quantity=3), {BUMP_PRICE: 49}), 147)

    def test_a_non_bump_line_never_contributes(self):
        lines = self._lines()
        self.assertEqual(bump_postage_collected(lines, {"price_main": 49}), 0)


class BumpPostageReachesTheLedgerTests(unittest.TestCase):
    """Because the point of collecting it is to see whether postage paid for itself."""

    def _order(self, **extra):
        return {"tenant_id": "t", "order_id": "order_1", "payment_intent_id": "pi_1",
                "amount_total": 15225, "currency": "usd", "created_at": 1700000000,
                "shipping_amount": 620, **extra}

    def test_bump_postage_is_shipping_revenue_not_product_revenue(self):
        entry = sale_entry_from_order(self._order(bump_shipping_amount=49), now_epoch=1700000000)
        self.assertEqual(entry["amounts"]["shipping_revenue"], 669)

    def test_an_order_without_a_bump_surcharge_is_unchanged(self):
        entry = sale_entry_from_order(self._order(), now_epoch=1700000000)
        self.assertEqual(entry["amounts"]["shipping_revenue"], 620)

    def test_it_does_not_inflate_gross(self):
        """`shipping_revenue` is a PARTITION of gross, so adding to it must not add to the total.

        The buyer paid the surcharge inside the bump's line, which `amount_total` already contains.
        """
        with_bump = sale_entry_from_order(self._order(bump_shipping_amount=49), now_epoch=1700000000)
        without = sale_entry_from_order(self._order(), now_epoch=1700000000)
        self.assertEqual(with_bump["amounts"]["gross"], without["amounts"]["gross"])


if __name__ == "__main__":
    unittest.main()


class BumpExposureSeesTheBoxTests(unittest.TestCase):
    """The exposure metric has to catch a bump that grows the box without adding a parcel.

    That is the case that actually produced a loss on 2026-10-05: one parcel before, one parcel after, and
    49c more postage because the one parcel had to be a Large instead of a Medium. A parcel COUNT reports
    zero exposure there, which is the most misleading possible answer — it says "free" about the only
    situation where the tenant is silently paying.
    """

    BOXES = [
        {"name": "Medium box (10x8x6)", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35},
        {"name": "Large box (14x11x8)", "length": 14, "width": 11, "height": 8, "empty_weight": 0.6},
    ]

    def _product(self, product_id, length, width, height, weight=0.5):
        return {"product_id": product_id, "name": product_id, "product_type": "physical",
                "fulfillment": {"item_dimensions": {
                    "length_in": length, "width_in": width, "height_in": height, "weight_lb": weight}}}

    def test_a_bump_that_only_grows_the_box_is_still_reported(self):
        from handlers.shipping import _bump_exposure

        products = {"base": self._product("base", 9, 7, 5), "bump": self._product("bump", 6, 5, 4)}
        exposure = _bump_exposure([{"product_id": "base", "quantity": 1}],
                                  [{"product_id": "bump", "quantity": 1}], products, self.BOXES)
        self.assertEqual(exposure["bump_parcel_delta"], 0, "precondition: the parcel count must not move")
        self.assertIn("bump_box_change", exposure)
        self.assertEqual(exposure["bump_box_change"]["from"], ["Medium box (10x8x6)"])
        self.assertEqual(exposure["bump_box_change"]["to"], ["Large box (14x11x8)"])

    def test_a_bump_that_changes_nothing_reports_no_box_change(self):
        from handlers.shipping import _bump_exposure

        products = {"base": self._product("base", 9, 7, 5), "bump": self._product("bump", 5, 4, 3)}
        exposure = _bump_exposure([{"product_id": "base", "quantity": 1}],
                                  [{"product_id": "bump", "quantity": 1}], products, self.BOXES)
        self.assertEqual(exposure["bump_parcel_delta"], 0)
        self.assertNotIn("bump_box_change", exposure)

    def test_an_offer_without_bumps_reports_nothing(self):
        from handlers.shipping import _bump_exposure

        self.assertEqual(_bump_exposure([{"product_id": "base", "quantity": 1}], [], {}, self.BOXES), {})
