"""A notice for an order that should have shipped by now.

plans/THANK_YOU_PAGE.md P4. The thank-you page tells a buyer their parcel is due on a date, and the
shipment email corrects that date if it slips — but both depend on the tenant marking the order shipped,
and nothing asked them to. `shipments recorded: 0` across every order ever placed.

A notification already fires on every sale. This one earns its place by a different rule:
`feedback_notices_only_when_actionable` says a notice needs an action the tenant must take, and "you have
orders" is not that — they know. "This order should have shipped by now" is, because we stored the date
we promised on their behalf and can name which promise is at risk.
"""
import unittest
from datetime import date

from stripe_link.domain.fulfilment_overdue import (
    GRACE_DAYS,
    has_shipped,
    is_overdue,
    overdue_notification,
    promised_ship_date,
)

ORDER = {"order_id": "order_1", "tenant_id": "t1", "status": "paid",
         "customer": {"name": "Ada", "stripe_customer_id": "cus_1"},
         "delivery_estimate": {"ships_on": "2026-10-05"}}


class OnlyWhenThereIsAPromiseToBreakTests(unittest.TestCase):
    def test_an_order_with_no_estimate_is_never_overdue(self):
        """No parcel, or an order placed before this existed. Either way there is nothing to report."""
        self.assertEqual(promised_ship_date({"order_id": "x"}), "")
        self.assertFalse(is_overdue({"status": "paid", "order_id": "x"}, None, date(2027, 1, 1)))

    def test_an_unpaid_order_is_not_waiting_on_the_tenant(self):
        self.assertFalse(is_overdue(dict(ORDER, status="pending"), None, date(2026, 10, 9)))

    def test_a_shipped_order_is_not_overdue(self):
        for status in ("shipped", "purchased"):
            self.assertTrue(has_shipped({"status": status}))
            self.assertFalse(is_overdue(ORDER, {"status": status}, date(2026, 10, 9)))

    def test_a_garbled_date_is_not_a_deadline(self):
        self.assertFalse(is_overdue(dict(ORDER, delivery_estimate={"ships_on": "soon"}),
                                    None, date(2027, 1, 1)))


class TheGraceDayTests(unittest.TestCase):
    """The cutoff is already a buffer and the tenant may well have posted it without telling us, so firing
    at one minute past midnight would be a notice about our own bookkeeping rather than their parcel."""

    def test_not_on_the_promised_day(self):
        self.assertFalse(is_overdue(ORDER, None, date(2026, 10, 5)))

    def test_not_the_day_after(self):
        self.assertFalse(is_overdue(ORDER, None, date(2026, 10, 6)))

    def test_yes_two_days_later(self):
        self.assertTrue(is_overdue(ORDER, None, date(2026, 10, 7)))

    def test_the_grace_is_one_day(self):
        self.assertEqual(GRACE_DAYS, 1)


class TheNoticeNamesTheActionTests(unittest.TestCase):
    NOTICE = overdue_notification(ORDER, date(2026, 10, 8))

    def test_it_says_whose_order_and_how_late(self):
        self.assertIn("Ada", self.NOTICE["message"])
        self.assertIn("3 days ago", self.NOTICE["message"])

    def test_it_says_what_to_do_and_why_it_matters(self):
        self.assertIn("mark it shipped", self.NOTICE["message"])
        self.assertIn("told a delivery date", self.NOTICE["message"])
        self.assertEqual(self.NOTICE["action"]["route"], "orders")

    def test_it_is_a_warning_not_an_error(self):
        """Nothing has failed. A red badge for a parcel posted this morning without being recorded would
        be crying wolf, and the next real alarm would be worth less."""
        self.assertEqual(self.NOTICE["severity"], "warning")

    def test_yesterday_reads_as_yesterday(self):
        self.assertIn("yesterday", overdue_notification(ORDER, date(2026, 10, 6))["message"])

    def test_the_id_is_derived_from_the_order(self):
        """The dedup is the PRIMARY KEY, not a query: a sweep running every five minutes rewrites one row
        instead of filling the bell with copies of itself."""
        self.assertEqual(self.NOTICE["notification_id"], "notif_overdue_order_1")
        self.assertEqual(overdue_notification(ORDER, date(2027, 1, 1))["notification_id"],
                         self.NOTICE["notification_id"])


class TheSweepPassTests(unittest.TestCase):
    def _run(self, orders, shipments=None, notifications=None, now=1_791_500_000):
        from handlers.fee_reconciliation import _notify_overdue

        class Orders:
            def scan_type(self):
                return list(orders)

        class Shipments:
            def get(self, _tenant, order_id):
                return (shipments or {}).get(order_id)

        sent = []

        class Notifications:
            def put(self, doc):
                sent.append(doc)
                return doc

        count = _notify_overdue("test", now, orders_repo=Orders(),
                                shipments_repo=Shipments() if shipments is not None else None,
                                notifications_repo=Notifications())
        return count, sent

    def test_it_notifies_an_overdue_order(self):
        count, sent = self._run([ORDER], shipments={})
        self.assertEqual(count, 1)
        self.assertEqual(sent[0]["notification_id"], "notif_overdue_order_1")

    def test_it_leaves_a_shipped_one_alone(self):
        count, _ = self._run([ORDER], shipments={"order_1": {"status": "shipped"}})
        self.assertEqual(count, 0)

    def test_NO_shipments_table_means_no_notices(self):
        """Every order would look unshipped, and the tenant would get a bell full of parcels they posted
        weeks ago. Not knowing is a reason to stay quiet, not to guess."""
        count, _ = self._run([ORDER], shipments=None)
        self.assertEqual(count, 0)

    def test_one_bad_order_never_stops_the_pass(self):
        broken = {"order_id": "bad", "tenant_id": "t1", "status": "paid",
                  "delivery_estimate": {"ships_on": "2026-10-05"}, "customer": "not a dict"}
        count, sent = self._run([broken, ORDER], shipments={})
        self.assertEqual(count, 2)       # the bad one is tolerated, not skipped
        self.assertEqual(len(sent), 2)

    def test_it_shares_the_fee_sweeps_scan(self):
        """Reading the orders table is the expensive half and it is already happening; asking "and is this
        one overdue?" costs nothing on top. The decisions stay in separate modules."""
        source = (__import__("pathlib").Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "fee_reconciliation.py").read_text()
        self.assertIn("orders_repo=orders_for_mode", source)
        self.assertIn("from stripe_link.domain.fulfilment_overdue import", source)
