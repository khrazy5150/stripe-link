"""What sold — and why it cannot be grouped on the ledger entry's own product.

A sale entry names the order's PRIMARY product and carries the whole order's gross. Grouped on that, a
bump's revenue lands on the headline product and the bump reads as never having sold. Measured on real
data 2026-10-06: Creatine Gummies $2,700.55 against $320.38 of its own lines, and a bump that had
genuinely sold $28.90 reading zero. 20 of 73 orders had more than one line.

So the breakdown is recorded on the entry and the report presents it. Money is still added up in exactly
one place: a report that summed line revenue for itself would be a second ledger.
"""
import unittest

from stripe_link.domain.ledger import sale_entry_from_order, sale_lines, what_sold


def order(**extra):
    return {"tenant_id": "t", "order_id": "o", "payment_intent_id": "pi", "amount_total": 5935,
            "currency": "usd", "created_at": 1, **extra}


CART = [
    {"name": "Creatine Gummies", "amount_total": 3900, "quantity": 1, "product_id": "gummies"},
    {"name": "Triple Omega", "amount_total": 1445, "quantity": 1, "product_id": "omega",
     "is_order_bump": True},
]


class SaleLinesTests(unittest.TestCase):
    def test_each_line_is_recorded_against_its_own_product(self):
        lines = sale_lines(order(line_items=CART))
        self.assertEqual([(l["product_id"], l["gross"]) for l in lines],
                         [("gummies", 3900), ("omega", 1445)])

    def test_a_tier_records_the_units_the_buyer_received(self):
        lines = sale_lines(order(line_items=[
            {"name": "NAD", "amount_total": 5571, "quantity": 1, "unit_quantity": 3, "product_id": "nad"}]))
        self.assertEqual(lines[0]["units"], 3)

    def test_an_upsell_is_itemised_from_its_product_block(self):
        """An upsell has no Stripe line items. Leaving it unitemised would make every upsell invisible."""
        lines = sale_lines(order(amount_total=1445, product={"product_id": "nad", "name": "NAD"}))
        self.assertEqual(lines[0]["product_id"], "nad")

    def test_an_upsells_postage_is_not_counted_as_merchandise(self):
        """`amount_total` is what the card was charged, postage included, and that postage is ALSO
        recorded as shipping revenue. Counting both over-stated merchandise by $449.12 across 39 real
        upsells before this subtraction."""
        lines = sale_lines(order(amount_total=1678, shipping_amount=233,
                                 product={"product_id": "nad"}))
        self.assertEqual(lines[0]["gross"], 1445)

    def test_a_bump_surcharge_is_not_counted_as_merchandise(self):
        """The surcharge is folded into the bump's price, so it sits inside that line AND in shipping
        revenue. It reconciled $1.50 heavy before this."""
        lines = sale_lines(order(bump_shipping_amount=150, line_items=[
            {"name": "Shaker", "amount_total": 1103, "quantity": 1, "product_id": "shaker",
             "is_order_bump": True}]))
        self.assertEqual(lines[0]["gross"], 953)

    def test_a_line_that_states_its_own_postage_is_believed(self):
        lines = sale_lines(order(bump_shipping_amount=150, line_items=[
            {"name": "Shaker", "amount_total": 1103, "quantity": 1, "shipping_amount": 150,
             "is_order_bump": True}]))
        self.assertEqual(lines[0]["gross"], 953)

    def test_an_order_with_no_breakdown_is_none_not_empty(self):
        """"Cannot break this down" and "sold nothing" are different, and a report must say which."""
        self.assertIsNone(sale_lines(order()))


class WhatSoldTests(unittest.TestCase):
    def _entries(self, *orders):
        return [sale_entry_from_order(o, now_epoch=1) for o in orders]

    def test_a_bump_is_credited_to_its_own_product(self):
        rollup = what_sold(self._entries(order(line_items=CART)))
        by_product = {row["product_id"]: row["gross"] for row in rollup["products"]}
        self.assertEqual(by_product, {"gummies": 3900, "omega": 1445})

    def test_the_bump_share_is_reported_separately(self):
        rollup = what_sold(self._entries(order(line_items=CART)))
        omega = next(r for r in rollup["products"] if r["product_id"] == "omega")
        self.assertEqual(omega["bump_gross"], 1445)

    def test_products_are_ranked_by_revenue(self):
        rollup = what_sold(self._entries(order(line_items=CART)))
        self.assertEqual([r["product_id"] for r in rollup["products"]], ["gummies", "omega"])

    def test_sales_with_no_breakdown_are_named_not_dropped(self):
        rollup = what_sold(self._entries(order(line_items=CART), order(order_id="o2", amount_total=1000)))
        self.assertEqual(rollup["unitemised_gross"], 1000)

    def test_one_product_under_two_keys_is_one_row(self):
        """A line whose price predates the catalogue index resolves only to a name. Left on its own key
        the product is listed twice with its revenue split, and both rows look like whole answers."""
        named = order(order_id="o2", line_items=[
            {"name": "Creatine Gummies", "amount_total": 1000, "quantity": 1}])
        rollup = what_sold(self._entries(order(line_items=CART), named))
        gummies = [r for r in rollup["products"] if r["name"] == "Creatine Gummies"]
        self.assertEqual(len(gummies), 1)
        self.assertEqual(gummies[0]["gross"], 4900)

    def test_refunds_and_shipping_entries_are_not_products(self):
        entries = self._entries(order(line_items=CART))
        entries.append({"entry_type": "shipping_cost", "amounts": {"shipping_cost": -669}})
        rollup = what_sold(entries)
        self.assertEqual(sum(r["gross"] for r in rollup["products"]), 5345)


class ItReconcilesWithTheMoneyReportTests(unittest.TestCase):
    """A product table whose rows do not add up to the money table is worse than one that says which
    part it cannot place."""

    def test_lines_plus_shipping_equal_gross(self):
        entry = sale_entry_from_order(order(shipping_amount=590, line_items=CART), now_epoch=1)
        rollup = what_sold([entry])
        total = sum(r["gross"] for r in rollup["products"]) + rollup["unitemised_gross"]
        self.assertEqual(total + entry["amounts"]["shipping_revenue"], entry["amounts"]["gross"])

    def test_it_reconciles_with_a_bump_surcharge_in_play(self):
        o = order(shipping_amount=590, bump_shipping_amount=150, amount_total=6085, line_items=[
            {"name": "Gummies", "amount_total": 3900, "quantity": 1, "product_id": "gummies"},
            {"name": "Shaker", "amount_total": 1595, "quantity": 1, "product_id": "shaker",
             "is_order_bump": True}])
        entry = sale_entry_from_order(o, now_epoch=1)
        rollup = what_sold([entry])
        total = sum(r["gross"] for r in rollup["products"])
        self.assertEqual(total + entry["amounts"]["shipping_revenue"], entry["amounts"]["gross"])


if __name__ == "__main__":
    unittest.main()
