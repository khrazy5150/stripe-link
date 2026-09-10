"""Landing-page conversions and revenue are derived from orders, not counted.

`analytics_summary` was read by the page cards from the day they were built and written by NOTHING, so
every card showed 0 views / 0 conversions / $0.00 forever. Same shape as `same_as[].verified`: displayed,
believed, no producer.

Two of the three numbers never needed ingest. A paid order already records the page it came from, which is
how the A/B experiment results are computed -- so this is a fold over data the tenant already has.
"""
import json
import unittest

from handlers.pages import handler
from stripe_link.domain.page_analytics import PAID_ORDER_STATUSES, attach_summaries, summarize_by_page
from tests.fakes import FakeDocumentRepository


class SummarizeTests(unittest.TestCase):
    ORDERS = [
        {"status": "paid", "attribution": {"page_id": "p1"}, "amount_total": 1200},
        {"status": "completed", "attribution": {"page_id": "p1"}, "amount_total": 800},
        {"status": "pending", "attribution": {"page_id": "p1"}, "amount_total": 9999},
        {"status": "paid", "attribution": {"page_id": "p2"}, "amount_total": 500},
        {"status": "paid", "attribution": {}, "amount_total": 700},
    ]

    def test_only_paid_orders_count(self):
        summary = summarize_by_page(self.ORDERS)
        self.assertEqual(summary["p1"], {"conversions": 2, "revenue_cents": 2000})

    def test_an_order_with_no_page_is_ignored(self):
        # Revenue exists that no page can claim; attributing it anywhere would overstate a page.
        self.assertEqual(sum(v["conversions"] for v in summarize_by_page(self.ORDERS).values()), 3)

    def test_every_page_gets_a_summary_even_with_no_orders(self):
        # "Measured, zero conversions" must be distinguishable from "not in the fold".
        pages = attach_summaries([{"page_id": "p1"}, {"page_id": "nope"}], self.ORDERS)
        self.assertEqual(pages[1]["analytics_summary"], {"conversions": 0, "revenue_cents": 0})

    def test_views_are_absent_not_zero(self):
        # Nothing measures views. Reporting 0 would be a claim about traffic never counted -- the exact
        # bug this replaces. Omitted so the UI can show nothing instead of a confident wrong number.
        pages = attach_summaries([{"page_id": "p1"}], self.ORDERS)
        self.assertNotIn("views", pages[0]["analytics_summary"])

    def test_a_malformed_amount_does_not_cost_the_listing_its_numbers(self):
        summary = summarize_by_page([
            {"status": "paid", "attribution": {"page_id": "p1"}, "amount_total": "oops"},
            {"status": "paid", "attribution": {"page_id": "p1"}, "amount_total": 300},
        ])
        self.assertEqual(summary["p1"], {"conversions": 2, "revenue_cents": 300})

    def test_the_status_set_is_shared_with_the_experiment_results(self):
        from handlers.experiments import PAID_ORDER_STATUSES as experiments_statuses
        self.assertIs(experiments_statuses, PAID_ORDER_STATUSES)


class ListPagesTests(unittest.TestCase):
    def setUp(self):
        self.pages = FakeDocumentRepository("page_id")
        self.pages.put({"tenant_id": "t1", "page_id": "p1", "name": "Landing", "status": "draft"})
        self.orders = FakeDocumentRepository("order_id")
        self.orders.put({"tenant_id": "t1", "order_id": "o1", "status": "paid",
                         "attribution": {"page_id": "p1"}, "amount_total": 2500})

    def _list(self, orders_repo):
        from handlers import pages as pages_handler
        return pages_handler.list_pages(
            {"queryStringParameters": {"tenant_id": "t1"}}, self.pages, orders_repo=orders_repo)

    def test_the_listing_carries_derived_numbers(self):
        body = json.loads(self._list(self.orders)["body"])
        self.assertEqual(body["pages"][0]["analytics_summary"],
                         {"conversions": 1, "revenue_cents": 2500})

    def test_unreadable_orders_do_not_break_the_listing(self):
        # A missing IAM grant must degrade to "no numbers", never to a failed page list.
        class Broken:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("AccessDeniedException")
        response = self._list(Broken())
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(json.loads(response["body"])["pages"]), 1)


if __name__ == "__main__":
    unittest.main()
