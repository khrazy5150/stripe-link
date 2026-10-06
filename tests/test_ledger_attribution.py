"""A ledger entry has to know WHAT was sold, or no report can be built on it.

`sale_entry_from_order` read `order["offer_id"]` and `order["product_id"]` flat. Both order paths write
them NESTED -- `attribution.offer_id` and `product.product_id` -- so both reads were always None and both
fields were dropped. Not one entry ever written carries a product or an offer, and nothing said so,
because an absent field looks exactly like a sale that genuinely had none.

Identical in shape to the `fees` bug recorded twelve lines above it in the same function: flat reads
against a nested document. Found 2026-10-06 while asking what reporting would need.
"""
import unittest

from stripe_link.domain.ledger import sale_entry_from_order


def order(**extra):
    return {"tenant_id": "t", "order_id": "order_1", "payment_intent_id": "pi_1",
            "amount_total": 5935, "currency": "usd", "created_at": 1700000000, **extra}


class AttributionReachesTheLedgerTests(unittest.TestCase):
    def test_the_offer_is_read_from_attribution(self):
        entry = sale_entry_from_order(
            order(attribution={"offer_id": "offer_1", "page_id": "page_1"}), now_epoch=1)
        self.assertEqual(entry["offer_id"], "offer_1")

    def test_the_product_is_read_from_the_product_block(self):
        entry = sale_entry_from_order(
            order(product={"product_id": "prod_1", "name": "Creatine Gummies"}), now_epoch=1)
        self.assertEqual(entry["product_id"], "prod_1")

    def test_both_at_once_which_is_the_shape_a_real_order_has(self):
        entry = sale_entry_from_order(
            order(attribution={"offer_id": "offer_1"}, product={"product_id": "prod_1"}), now_epoch=1)
        self.assertEqual((entry["offer_id"], entry["product_id"]), ("offer_1", "prod_1"))

    def test_a_flat_field_still_wins_for_the_paths_that_use_one(self):
        """The invoice path and anything written before the shapes diverged."""
        entry = sale_entry_from_order(
            order(offer_id="flat_offer", attribution={"offer_id": "nested_offer"}), now_epoch=1)
        self.assertEqual(entry["offer_id"], "flat_offer")

    def test_a_sale_that_genuinely_has_neither_records_neither(self):
        """Absent, not empty string: a report grouping by product must not grow a "" bucket."""
        entry = sale_entry_from_order(order(), now_epoch=1)
        self.assertIsNone(entry.get("offer_id"))
        self.assertIsNone(entry.get("product_id"))
