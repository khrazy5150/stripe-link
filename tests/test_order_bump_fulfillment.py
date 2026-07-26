"""P2a-2 (plans/SALES_FUNNELS.md): a completed checkout session's line items are itemized on the order, and
opted-in pre-purchase order bumps (whose Stripe price id was offered as an optional_item) are flagged."""

import unittest

from handlers.stripe_webhook import (
    _fetch_line_items_for_session,
    fetch_session_line_items,
    order_record_from_session,
)


def _session(**over):
    base = {
        "id": "cs_test_1",
        "metadata": {"order_bump_ids": "price_stripe_bump", "product_id": "prod_main", "price_id": "price_main"},
        "amount_total": 2300,
        "currency": "usd",
        "payment_status": "paid",
        "livemode": False,
    }
    base.update(over)
    return base


_LINE_ITEMS = [
    {"description": "Main Product", "amount_subtotal": 1800, "amount_total": 1800, "quantity": 1, "currency": "usd", "price": {"id": "price_main_stripe"}},
    {"description": "Insulated Thermos", "amount_subtotal": 500, "amount_total": 500, "quantity": 1, "currency": "usd", "price": {"id": "price_stripe_bump"}},
]


class OrderBumpFulfillmentTests(unittest.TestCase):
    def test_order_itemizes_line_items_and_flags_the_bump(self):
        order = order_record_from_session(_session(), "tenant_demo", 100, {}, line_items=_LINE_ITEMS)
        items = order["line_items"]
        self.assertEqual(len(items), 2)
        self.assertFalse(items[0]["is_order_bump"])
        self.assertEqual(items[0]["name"], "Main Product")
        self.assertTrue(items[1]["is_order_bump"])
        self.assertEqual(items[1]["amount_total"], 500)
        self.assertTrue(order["has_order_bumps"])
        # The sale total + primary product are unchanged by itemization.
        self.assertEqual(order["amount_total"], 2300)
        self.assertEqual(order["product"]["product_id"], "prod_main")

    def test_order_without_line_items_degrades_gracefully(self):
        order = order_record_from_session(_session(), "tenant_demo", 100, {})
        self.assertEqual(order["line_items"], [])
        self.assertFalse(order["has_order_bumps"])
        self.assertEqual(order["amount_total"], 2300)  # sale still recorded

    def test_no_bump_flagged_when_none_offered(self):
        order = order_record_from_session(_session(metadata={"product_id": "p"}), "t", 100, {}, line_items=_LINE_ITEMS)
        self.assertFalse(any(item["is_order_bump"] for item in order["line_items"]))
        self.assertFalse(order["has_order_bumps"])

    def test_fetch_uses_injected_fetcher(self):
        got = _fetch_line_items_for_session(_session(), "t", fetcher=lambda session: _LINE_ITEMS)
        self.assertEqual(len(got), 2)

    def test_fetch_is_best_effort_on_error(self):
        self.assertEqual(_fetch_line_items_for_session(_session(), "t", fetcher=lambda s: (_ for _ in ()).throw(RuntimeError())), [])
        self.assertEqual(fetch_session_line_items("", api_key=""), [])  # missing args -> []


if __name__ == "__main__":
    unittest.main()
