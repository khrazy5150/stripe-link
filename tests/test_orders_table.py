"""The Orders screen is a fulfilment TABLE, not a card grid.

The cards showed three orders per screen and not one fact a fulfilment decision needs -- no destination, no
items, no way to select more than one. plans/ORDER_FULFILMENT.md F1 replaces them.

The display helpers are pure and live in their own module so the table and the details modal cannot
describe the same order two different ways; they are exercised through node for the same reason the offer
and purchase-flow helpers are.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = ROOT / "dashboard/src/components/Orders.vue"
MODULE = ROOT / "dashboard/src/components/orders/orderDisplay.js"


def run_js(calls):
    node = shutil.which("node")
    if not node:
        return None
    script = f"""
    import * as m from {json.dumps(str(MODULE))};
    const calls = {json.dumps(calls)};
    const out = {{}};
    for (const [key, [fn, args]] of Object.entries(calls)) out[key] = m[fn](...args);
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


ORDER = {
    "order_id": "order_cs_test_a17LZKXREGswa40vliBYZ22ciphksaZUplES02IKqo7Cj8ThmpvX2VdSpm",
    "amount_total": 1834, "currency": "usd", "created_at": "1790000000",
    "customer": {"name": "Keith Harris", "email": "k@example.com"},
    "shipping_address": {"city": "Denver", "state": "CO", "postal_code": "80204", "country": "US"},
    "line_items": [{"name": "Creatine Gummies", "quantity": 1}],
}


class TableStructureTests(unittest.TestCase):
    SOURCE = SCREEN.read_text(encoding="utf-8")

    def test_the_card_grid_is_gone(self):
        self.assertNotIn("coupon-card-grid", self.SOURCE)
        self.assertNotIn('class="coupon-card"', self.SOURCE)

    def test_it_is_a_real_table_with_a_header(self):
        for fragment in ("<table", "<thead", "<tbody", 'scope="col"'):
            self.assertIn(fragment, self.SOURCE, f"expected {fragment} in a data table")

    def test_the_page_never_scrolls_sideways(self):
        """Wide content scrolls inside its own container; the body must not."""
        self.assertIn("orders-table-wrap", self.SOURCE)
        css = (ROOT / "dashboard/src/styles.css").read_text(encoding="utf-8")
        block = css.split(".orders-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-x: auto", block)

    def test_details_survived_the_rewrite(self):
        """The ledger view predates this screen's fulfilment role; losing it would be a regression dressed
        as a redesign. It moved from a centred modal into the side drawer, where the row stays visible --
        so the anchor is the drawer, and the assertion is that the CONTENT is still reachable."""
        self.assertIn("Details", self.SOURCE)
        self.assertIn("OrderDetailDrawer", self.SOURCE)
        drawer = (ROOT / "dashboard/src/components/orders/OrderDetailDrawer.vue").read_text(encoding="utf-8")
        for fragment in ("Raw JSON", "order.fees", "amount_refunded", "order.order_id"):
            self.assertIn(fragment, drawer, f"the drawer dropped {fragment} from the old details modal")

    def test_the_destination_is_shown_because_fulfilment_needs_it(self):
        self.assertIn("destinationSummary", self.SOURCE)

    def test_a_non_shippable_order_still_opens_and_says_why(self):
        """"Not a shippable product" beats an empty shipment panel -- and the reason comes from the gate
        the row already computed, so the panel and the row cannot disagree."""
        drawer = (ROOT / "dashboard/src/components/orders/OrderDetailDrawer.vue").read_text(encoding="utf-8")
        self.assertIn("Not a shippable product", drawer)
        self.assertIn("fulfilment?.reasons", drawer)

    def test_clicking_a_row_opens_it_without_hijacking_the_buttons_inside(self):
        self.assertIn("openDetail", self.SOURCE)
        self.assertIn('closest("button, a, input, select, label")', self.SOURCE)


class DisplayHelperTests(unittest.TestCase):
    def setUp(self):
        self.out = run_js({
            "elided": ["elideId", [ORDER["order_id"]]],
            "short_id": ["elideId", ["order_123"]],
            "one_line": ["itemsSummary", [ORDER]],
            "one_line_qty": ["itemsSummary", [{"line_items": [{"name": "Gummies", "quantity": 3}]}]],
            "many_lines": ["itemsSummary", [{"line_items": [{"name": "A", "quantity": 2},
                                                            {"name": "B", "quantity": 1}]}]],
            "no_lines": ["itemsSummary", [{"product": {"name": "Beta Alanine"}}]],
            "nothing": ["itemsSummary", [{}]],
            "us": ["destinationSummary", [ORDER]],
            "ca": ["destinationSummary", [{"shipping_address": {"city": "Toronto", "state": "ON",
                                                               "postal_code": "M5H", "country": "CA"}}]],
            "none": ["destinationSummary", [{}]],
            "status": ["orderStatus", [{"payment_status": "refunded"}]],
            "status_default": ["orderStatus", [{}]],
        })
        if self.out is None:
            self.skipTest("node is not available")

    def test_a_long_id_keeps_both_ends(self):
        elided = self.out["elided"]
        self.assertTrue(elided.startswith("order_cs_test_"))
        self.assertTrue(elided.endswith("X2VdSpm"))
        self.assertIn("…", elided)
        self.assertLess(len(elided), len(ORDER["order_id"]))

    def test_a_short_id_is_left_alone(self):
        self.assertEqual(self.out["short_id"], "order_123")

    def test_one_line_reads_as_the_product(self):
        self.assertEqual(self.out["one_line"], "Creatine Gummies")
        self.assertEqual(self.out["one_line_qty"], "3 × Gummies")

    def test_several_lines_are_counted_not_listed(self):
        self.assertEqual(self.out["many_lines"], "3 items in 2 lines")

    def test_an_order_with_no_lines_falls_back_to_its_product(self):
        # Renewals and older orders have a product block and no line_items.
        self.assertEqual(self.out["no_lines"], "Beta Alanine")
        self.assertEqual(self.out["nothing"], "—")

    def test_a_domestic_destination_does_not_waste_space_on_the_country(self):
        self.assertEqual(self.out["us"], "Denver, CO 80204")

    def test_a_foreign_destination_says_so(self):
        """Checkout allows CA today and a Canadian parcel cannot be labelled yet, so the exception has to
        be the thing that stands out in the column."""
        self.assertIn("(CA)", self.out["ca"])

    def test_an_order_with_no_address_shows_nothing_rather_than_a_placeholder(self):
        self.assertEqual(self.out["none"], "")

    def test_status_prefers_payment_status_and_defaults_to_paid(self):
        self.assertEqual(self.out["status"], "refunded")
        self.assertEqual(self.out["status_default"], "paid")


class SortingTests(unittest.TestCase):
    ORDERS = [
        {"order_id": "a", "created_at": "100", "amount_total": 500, "customer": {"name": "Zoe"}},
        {"order_id": "b", "created_at": "300", "amount_total": 100, "customer": {"name": "Adam"}},
        {"order_id": "c", "created_at": "200", "amount_total": 900, "customer": {"name": "Mia"}},
    ]

    def _ids(self, key, direction):
        out = run_js({"sorted": ["sortOrders", [self.ORDERS, key, direction]]})
        if out is None:
            self.skipTest("node is not available")
        return [o["order_id"] for o in out["sorted"]]

    def test_newest_first_by_default(self):
        self.assertEqual(self._ids("created_at", "desc"), ["b", "c", "a"])

    def test_created_at_is_compared_as_a_NUMBER(self):
        """It is stored as a string of epoch seconds, so a lexicographic sort puts "1000" before "999"."""
        rows = [{"order_id": "big", "created_at": "1790000000"},
                {"order_id": "small", "created_at": "999999999"}]
        out = run_js({"sorted": ["sortOrders", [rows, "created_at", "desc"]]})
        if out is None:
            self.skipTest("node is not available")
        self.assertEqual([o["order_id"] for o in out["sorted"]], ["big", "small"])

    def test_money_sorts_by_value(self):
        self.assertEqual(self._ids("amount_total", "desc"), ["c", "a", "b"])

    def test_customers_sort_alphabetically(self):
        self.assertEqual(self._ids("customer", "asc"), ["b", "c", "a"])

    def test_sorting_does_not_mutate_the_input(self):
        out = run_js({"sorted": ["sortOrders", [self.ORDERS, "amount_total", "asc"]],
                      "original": ["sortOrders", [self.ORDERS, "created_at", "desc"]]})
        if out is None:
            self.skipTest("node is not available")
        # Both calls saw the same input; a sort that reordered in place would corrupt the second.
        self.assertEqual([o["order_id"] for o in out["original"]], ["b", "c", "a"])


if __name__ == "__main__":
    unittest.main()
