"""The Money report: a period of the ledger, and nothing that adds money up a second time.

`/ledger` already produced a correct summary; what it could not do was answer "this month against last"
without shipping a tenant's whole ledger to the browser to slice it there.
"""
import json
import unittest
from pathlib import Path

from handlers.ledger import handler


ROOT = Path(__file__).resolve().parents[1]


class Repo:
    def __init__(self, entries):
        self.entries = entries

    def list_for_tenant(self, tenant_id):
        return list(self.entries)

    def list_for_order(self, order_id):
        return [e for e in self.entries if e.get("order_id") == order_id]


def sale(order_id, occurred_at, gross=1000):
    return {"entry_type": "sale", "order_id": order_id, "occurred_at": occurred_at,
            "currency": "usd", "amounts": {"gross": gross}}


def shipping_cost(order_id, occurred_at, cost=-500):
    return {"entry_type": "shipping_cost", "order_id": order_id, "occurred_at": occurred_at,
            "currency": "usd", "amounts": {"shipping_cost": cost}}


def call(entries, **params):
    event = {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t", **params}}
    return json.loads(handler(event, None, repository=Repo(entries))["body"])


class PeriodFilteringTests(unittest.TestCase):
    ENTRIES = [sale("a", 100), sale("b", 200), sale("c", 300)]

    def test_no_window_returns_everything(self):
        self.assertEqual(call(self.ENTRIES)["count"], 3)

    def test_from_is_inclusive(self):
        self.assertEqual(call(self.ENTRIES, **{"from": "200"})["count"], 2)

    def test_to_is_inclusive(self):
        self.assertEqual(call(self.ENTRIES, to="200")["count"], 2)

    def test_both_bounds_select_a_period(self):
        body = call(self.ENTRIES, **{"from": "150", "to": "250"})
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["summary"]["totals"]["gross"], 1000)

    def test_the_summary_describes_the_window_not_the_ledger(self):
        """The whole point: a period's total must not be the lifetime total."""
        everything = call(self.ENTRIES)["summary"]["totals"]["gross"]
        window = call(self.ENTRIES, **{"from": "150"})["summary"]["totals"]["gross"]
        self.assertEqual(everything, 3000)
        self.assertEqual(window, 2000)

    def test_a_malformed_bound_is_ignored_rather_than_fatal(self):
        """A report is a read. It should degrade to "everything" rather than refuse."""
        self.assertEqual(call(self.ENTRIES, **{"from": "not-a-number"})["count"], 3)


class ShippingMarginCoverageTests(unittest.TestCase):
    """The one figure in this summary a tenant could act wrongly on.

    `shipping_cost` only exists once a label is bought, so a period where most orders have not shipped
    reports a margin computed from the few that have -- 5 of 71 reads as a ~96% margin on postage.
    `summarize` already refuses to invent a margin when NO cost exists; this is the partial case.
    """

    def test_it_reports_how_many_sales_have_a_label(self):
        entries = [sale("a", 100), sale("b", 200), sale("c", 300), shipping_cost("a", 310)]
        coverage = call(entries)["summary"]["shipping_cost_coverage"]
        self.assertEqual(coverage, {"shipped": 1, "sales": 3})

    def test_full_coverage_is_reported_as_such(self):
        entries = [sale("a", 100), shipping_cost("a", 110)]
        coverage = call(entries)["summary"]["shipping_cost_coverage"]
        self.assertEqual(coverage["shipped"], coverage["sales"])

    def test_two_labels_for_one_order_still_count_one_order(self):
        """A grouped order can need two parcels. The question is how many SALES are accounted for."""
        entries = [sale("a", 100), shipping_cost("a", 110), shipping_cost("a", 120)]
        self.assertEqual(call(entries)["summary"]["shipping_cost_coverage"]["shipped"], 1)


class TheScreenStatesTheCaveatTests(unittest.TestCase):
    REPORTS = (ROOT / "dashboard" / "src" / "components" / "Reports.vue").read_text(encoding="utf-8")
    APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")

    def test_partial_shipping_coverage_is_shown_not_hidden(self):
        self.assertIn("shipping_cost_coverage", self.REPORTS)
        self.assertIn("reads higher than it will finish", self.REPORTS)

    def test_it_compares_against_the_same_length_of_time(self):
        """A month against a quarter is not a comparison."""
        self.assertIn("days * 2 * 86400", self.REPORTS)

    def test_the_figures_are_a_table_not_cards(self):
        """These numbers are one statement that adds up -- revenue, what was taken out, what is left.
        A row of cards says they are eight unrelated figures; read down a column the arithmetic shows."""
        self.assertIn("<table", self.REPORTS)
        self.assertIn('scope="row"', self.REPORTS)
        self.assertNotIn("reports-card", self.REPORTS)

    def test_the_money_column_lines_its_digits_up(self):
        """The whole reason for a table."""
        self.assertIn("tabular-nums", (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8"))
        self.assertIn("reports-num", self.REPORTS)

    def test_the_menu_item_is_no_longer_disabled(self):
        reports_button = self.APP.split("Reports\n", 1)[0].rsplit("<button", 1)[1]
        self.assertNotIn("disabled", reports_button)
        self.assertIn("activeView = 'reports'", reports_button)


if __name__ == "__main__":
    unittest.main()
