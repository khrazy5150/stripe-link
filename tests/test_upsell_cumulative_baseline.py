"""An upsell's delta is only as honest as the thing it is measured from.

`session_shipping_baseline` answers "what did the original checkout quote cover". That is NOT the same as
"what is already in the parcel", and the gap between them is everything a buyer added after the quote was
stamped: the **order bump** (ticked on Stripe's hosted page, so it appears in no quote anywhere) and
**every upsell already accepted** (each of which was rated against that same original quote).

While upsells were small the error was exactly zero. Measured on real products 2026-10-05 when they are
not: cart 620c, two Whey Protein upsells. Each rated against the original cart and charged 203c, so the
buyer paid 1026c to post a parcel costing 837c — a 189c OVERCHARGE, taken from the customer. The reverse
is just as available: two upsells that each fit alone but together force a second parcel are each charged
nothing for it.
"""
import unittest

from handlers.upsell import MAX_DISCOVERED_UPSELLS, box_so_far


class FakeOrders:
    def __init__(self, orders=None):
        self.orders = orders or {}
        self.reads = []

    def get(self, tenant_id, order_id):
        self.reads.append(order_id)
        return self.orders.get(order_id)


class FakeProducts:
    def __init__(self, products=None):
        self.products = products or {}

    def get(self, tenant_id, product_id):
        return self.products.get(product_id)


BASELINE = {"items": [{"product_id": "cart", "quantity": 1}], "amount": 620}
OFFER = {"offer_id": "o1", "funnel": {"order_bumps": [{"product_id": "bump", "price_id": "pr_bump"}]}}
BUMP_PRODUCT = {"product_id": "bump", "prices": [{"price_id": "pr_bump", "stripe_price_id": "price_bump"}]}


def paid_upsell(product_id, shipping=0):
    return {"status": "paid", "product": {"product_id": product_id}, "shipping_amount": shipping}


class CumulativeBaselineTests(unittest.TestCase):
    def test_a_ticked_bump_joins_the_box(self):
        out = box_so_far({**BASELINE, "taken_price_ids": {"price_bump": 1}, "bump_shipping": 150},
                         tenant_id="t", session_id="cs_1", sequence=1, offer=OFFER,
                         products_repo=FakeProducts({"bump": BUMP_PRODUCT}), orders_repo=FakeOrders())
        self.assertIn({"product_id": "bump", "price_id": "pr_bump", "quantity": 1}, out["items"])
        # ...and the postage it already paid, which never reaches the shipping line.
        self.assertEqual(out["amount"], 770)

    def test_a_bump_that_was_offered_but_declined_does_not(self):
        """Offered is not bought. Packing a bump nobody took would over-state the box and under-charge."""
        out = box_so_far({**BASELINE, "taken_price_ids": {}, "bump_shipping": 0},
                         tenant_id="t", session_id="cs_1", sequence=1, offer=OFFER,
                         products_repo=FakeProducts({"bump": BUMP_PRODUCT}), orders_repo=FakeOrders())
        self.assertEqual(out["items"], BASELINE["items"])
        self.assertEqual(out["amount"], 620)

    def test_earlier_upsells_join_the_box(self):
        """The 189c overcharge. Upsell 2 must see upsell 1."""
        orders = FakeOrders({"order_cs_1_upsell_1": paid_upsell("whey", shipping=203)})
        out = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", sequence=2, offer=None,
                         products_repo=None, orders_repo=orders)
        self.assertIn({"product_id": "whey", "quantity": 1}, out["items"])
        self.assertEqual(out["amount"], 823, "the postage already collected accumulates too")

    def test_an_unpaid_earlier_step_is_not_in_the_box(self):
        orders = FakeOrders({"order_cs_1_upsell_1": {**paid_upsell("whey", 203), "status": "failed"}})
        out = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", sequence=2, offer=None,
                         products_repo=None, orders_repo=orders)
        self.assertEqual(out["items"], BASELINE["items"])
        self.assertEqual(out["amount"], 620)

    def test_a_declined_step_does_not_stop_a_later_one_counting(self):
        """A buyer who declines step 1 and takes step 2 still has step 2 in the box at step 3."""
        orders = FakeOrders({"order_cs_1_upsell_2": paid_upsell("whey", 203)})
        out = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", sequence=3, offer=None,
                         products_repo=None, orders_repo=orders)
        self.assertIn({"product_id": "whey", "quantity": 1}, out["items"])

    def test_the_bump_and_every_earlier_upsell_accumulate_together(self):
        orders = FakeOrders({"order_cs_1_upsell_1": paid_upsell("whey", 203)})
        out = box_so_far({**BASELINE, "taken_price_ids": {"price_bump": 1}, "bump_shipping": 150},
                         tenant_id="t", session_id="cs_1", sequence=2, offer=OFFER,
                         products_repo=FakeProducts({"bump": BUMP_PRODUCT}), orders_repo=orders)
        self.assertEqual(len(out["items"]), 3)
        self.assertEqual(out["amount"], 620 + 150 + 203)


class DiscoveryTests(unittest.TestCase):
    """The disclosure is a plain GET and carries no step number. Rather than republish every funnel page
    to add one, the accepted steps are discovered — and both paths must reach the same box, because the
    button states a price and the charge takes one."""

    def test_it_walks_until_a_gap(self):
        orders = FakeOrders({"order_cs_1_upsell_1": paid_upsell("a", 100),
                             "order_cs_1_upsell_2": paid_upsell("b", 50)})
        out = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", orders_repo=orders)
        self.assertEqual(out["amount"], 770)
        self.assertEqual(len(out["items"]), 3)

    def test_discovery_and_a_known_sequence_agree(self):
        orders = {"order_cs_1_upsell_1": paid_upsell("a", 100), "order_cs_1_upsell_2": paid_upsell("b", 50)}
        discovered = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", orders_repo=FakeOrders(orders))
        known = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", sequence=3,
                           orders_repo=FakeOrders(orders))
        self.assertEqual(discovered, known)

    def test_discovery_is_bounded(self):
        orders = FakeOrders()
        box_so_far(BASELINE, tenant_id="t", session_id="cs_1", orders_repo=orders)
        self.assertLessEqual(len(orders.reads), MAX_DISCOVERED_UPSELLS)

    def test_an_empty_baseline_is_left_alone(self):
        """Nothing known means the caller rates a standalone parcel, which over-charges in the one
        direction a tenant can refund."""
        self.assertEqual(box_so_far({}, tenant_id="t", session_id="cs_1", orders_repo=FakeOrders()), {})

    def test_an_unreadable_order_does_not_cost_the_sale(self):
        class Broken:
            def get(self, *a, **k):
                raise RuntimeError("dynamo down")

        out = box_so_far(BASELINE, tenant_id="t", session_id="cs_1", sequence=3, orders_repo=Broken())
        self.assertEqual(out["amount"], 620)


if __name__ == "__main__":
    unittest.main()
