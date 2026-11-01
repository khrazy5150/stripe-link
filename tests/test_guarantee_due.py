"""Which delivery guarantees have come due, and the gate that keeps the answer honest.

`no_delivery_refund` has been published on live pages with nothing watching the clock. These tests pin the
one thing that makes watching it safe: a parcel we cannot SEE is never reported as undelivered.
"""

import unittest

from stripe_link.domain.buyer_guarantees import (
    NO_DELIVERY_REFUND,
    NO_TRACKING_UPDATE_REFUND,
    PRICE_MATCH,
)
from stripe_link.domain.buyer_guarantees import resolve as resolve_guarantees
from stripe_link.domain.guarantee_due import (
    DAY_SECONDS,
    SWEEPABLE,
    due_guarantees,
    guarantee_notification,
    observable,
)

NOW = 1_800_000_000
ORDER = {"tenant_id": "t1", "order_id": "order_1", "status": "paid",
         "customer": {"name": "Dana Vale", "stripe_customer_id": "cus_1"}}

# Shipped 25 days ago, tracker registered, scanned in transit 24 days ago, never delivered.
SHIPMENT = {"order_id": "order_1", "shipped_at": NOW - 25 * DAY_SECONDS,
            "tracking_registered_at": NOW - 25 * DAY_SECONDS,
            "tracking_status": "TRANSIT", "tracking_status_at": NOW - 24 * DAY_SECONDS}


def promises(**enabled):
    """The tenant's enabled guarantees, resolved the way the sweep resolves them."""
    return resolve_guarantees({"legal_defaults": {"buyer_guarantees": {
        key: {"enabled": True, "days": days} for key, days in enabled.items()}}})


class TheObservableGate(unittest.TestCase):
    """THE clause this module turns on. `tracking.has_arrived` is False for a parcel never tracked, a
    carrier that never scans, and a parcel genuinely lost -- so the question is not "did it arrive" but
    "are we in a position to know, and it did not"."""

    def test_a_registered_tracker_is_observable(self):
        self.assertTrue(observable(SHIPMENT))

    def test_an_unregistered_one_is_not(self):
        for shipment in ({}, None, {"shipped_at": NOW}, {"tracking_registered_at": 0}):
            with self.subTest(shipment=shipment):
                self.assertFalse(observable(shipment))

    def test_a_parcel_we_cannot_see_is_never_reported(self):
        """The tenant who posts at their local counter with no provider account, and every order
        predating the tracking feed. Without this clause the sweep would report both, which is
        `feedback_absence_reads_as_safety` with a refund attached."""
        unseen = {k: v for k, v in SHIPMENT.items() if k != "tracking_registered_at"}
        self.assertEqual(due_guarantees(ORDER, unseen, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])

    def test_a_decimal_registration_still_counts(self):
        """Timestamps come straight off a stored document, where `isinstance(x, int)` is False for the
        Decimal DynamoDB returns (`feedback_decimal_from_dynamo`)."""
        from decimal import Decimal
        self.assertTrue(observable({"tracking_registered_at": Decimal("1700000000")}))


class WhenItIsDue(unittest.TestCase):
    def test_a_parcel_past_the_promise_is_due(self):
        due = due_guarantees(ORDER, SHIPMENT, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW)
        self.assertEqual([d["key"] for d in due], [NO_DELIVERY_REFUND])
        self.assertEqual(due[0]["days"], 20)
        self.assertEqual(due[0]["elapsed_days"], 25)

    def test_a_parcel_inside_the_window_is_not(self):
        due = due_guarantees(ORDER, SHIPMENT, promises(**{NO_DELIVERY_REFUND: 30}), now=NOW)
        self.assertEqual(due, [])

    def test_the_day_it_crosses_counts(self):
        shipment = dict(SHIPMENT, shipped_at=NOW - 20 * DAY_SECONDS)
        self.assertTrue(due_guarantees(ORDER, shipment, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW))

    def test_a_delivered_parcel_is_never_due(self):
        arrived = dict(SHIPMENT, delivered_at=NOW - 3 * DAY_SECONDS, tracking_status="DELIVERED")
        self.assertEqual(due_guarantees(ORDER, arrived, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])

    def test_a_returned_parcel_is_still_due(self):
        """It did not reach the buyer, which is exactly when they are owed the refund or the resend. The
        tenant's own Orders screen says "Returned" beside it, so the notice adds the promise, not the news."""
        returned = dict(SHIPMENT, tracking_status="RETURNED")
        self.assertTrue(due_guarantees(ORDER, returned, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW))

    def test_an_unpaid_order_is_not_waiting_on_anything(self):
        for status in ("pending", "refunded", ""):
            with self.subTest(status=status):
                order = dict(ORDER, status=status)
                self.assertEqual(due_guarantees(order, SHIPMENT,
                                                promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])

    def test_nothing_dispatched_means_nothing_to_have_not_arrived(self):
        unshipped = {k: v for k, v in SHIPMENT.items() if k != "shipped_at"}
        self.assertEqual(due_guarantees(ORDER, unshipped,
                                        promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])

    def test_a_promise_the_tenant_never_made_is_never_reported(self):
        """The whole point: this reports promises they made, never ones we think they should have."""
        self.assertEqual(due_guarantees(ORDER, SHIPMENT, [], now=NOW), [])
        self.assertEqual(due_guarantees(ORDER, SHIPMENT, promises(**{PRICE_MATCH: 30}), now=NOW), [])

    def test_only_the_two_with_a_clock_a_shipment_can_answer(self):
        """`damaged_in_transit` needs someone to look in the box and the price promises are about a price
        list. A sweep cannot see any of them, and a notice with nothing behind it is worse than none."""
        self.assertEqual(SWEEPABLE, (NO_DELIVERY_REFUND, NO_TRACKING_UPDATE_REFUND))

    def test_never_raises_on_rubbish(self):
        for order in (None, "", [], {}):
            with self.subTest(order=order):
                self.assertEqual(due_guarantees(order, SHIPMENT,
                                                promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])
        self.assertEqual(due_guarantees(ORDER, None, promises(**{NO_DELIVERY_REFUND: 20}), now=NOW), [])
        self.assertEqual(due_guarantees(ORDER, SHIPMENT, "nonsense", now=NOW), [])


class TheTrackingClock(unittest.TestCase):
    def test_it_runs_from_the_last_scan(self):
        due = due_guarantees(ORDER, SHIPMENT, promises(**{NO_TRACKING_UPDATE_REFUND: 15}), now=NOW)
        self.assertEqual([d["key"] for d in due], [NO_TRACKING_UPDATE_REFUND])
        self.assertEqual(due[0]["elapsed_days"], 24)

    def test_a_recent_scan_resets_it(self):
        moving = dict(SHIPMENT, tracking_status_at=NOW - 2 * DAY_SECONDS)
        self.assertEqual(due_guarantees(ORDER, moving,
                                        promises(**{NO_TRACKING_UPDATE_REFUND: 15}), now=NOW), [])

    def test_a_tracker_that_never_scanned_runs_from_registration(self):
        """The purest case of "tracking shows no movement" rather than a case with no clock."""
        silent = {k: v for k, v in SHIPMENT.items() if k != "tracking_status_at"}
        due = due_guarantees(ORDER, silent, promises(**{NO_TRACKING_UPDATE_REFUND: 15}), now=NOW)
        self.assertEqual(due[0]["elapsed_days"], 25)

    def test_both_can_be_due_at_once_longest_overdue_first(self):
        due = due_guarantees(ORDER, SHIPMENT,
                             promises(**{NO_DELIVERY_REFUND: 20, NO_TRACKING_UPDATE_REFUND: 5}), now=NOW)
        self.assertEqual([d["key"] for d in due], [NO_TRACKING_UPDATE_REFUND, NO_DELIVERY_REFUND])


class TheNotice(unittest.TestCase):
    def notice(self, key=NO_DELIVERY_REFUND, days=20, elapsed=25):
        return guarantee_notification(ORDER, {"key": key, "days": days, "elapsed_days": elapsed,
                                              "sentence": "If your order has not arrived..."}, now=NOW)

    def test_the_id_is_derived_from_the_order_and_the_guarantee(self):
        """Idempotent by PRIMARY KEY, not by query: a sweep running every five minutes rewrites one row.
        Keyed on the guarantee too, because an order can outrun both and they are two things to settle."""
        self.assertEqual(self.notice()["notification_id"], "notif_guarantee_no_delivery_refund_order_1")
        self.assertNotEqual(self.notice(key=NO_TRACKING_UPDATE_REFUND)["notification_id"],
                            self.notice()["notification_id"])

    def test_it_is_stable_across_passes(self):
        self.assertEqual(self.notice(elapsed=25)["notification_id"],
                         self.notice(elapsed=99)["notification_id"])

    def test_it_names_the_action_not_just_the_problem(self):
        """`feedback_notices_only_when_actionable`: not "a parcel is late", which the tenant can see, but
        "you promised this buyer something and the date has passed"."""
        message = self.notice()["message"]
        self.assertIn("Dana Vale", message)
        self.assertIn("25 days", message)
        self.assertIn("20", message)
        self.assertIn("their choice", message)

    def test_the_tracking_notice_says_tracking(self):
        notice = self.notice(key=NO_TRACKING_UPDATE_REFUND, days=15, elapsed=24)
        self.assertIn("no tracking movement", notice["message"])
        self.assertEqual(notice["title"], "Tracking guarantee is due")

    def test_a_nameless_buyer_still_reads_as_a_sentence(self):
        notice = guarantee_notification({"order_id": "o", "tenant_id": "t"},
                                        {"key": NO_DELIVERY_REFUND, "days": 20, "elapsed_days": 25},
                                        now=NOW)
        self.assertTrue(notice["message"].startswith("A customer's order"))

    def test_it_outranks_the_overdue_to_ship_notice(self):
        """That one is a parcel the tenant still has; this is a promise already broken in the buyer's eyes."""
        from stripe_link.domain.fulfilment_overdue import overdue_notification
        from datetime import date
        self.assertGreater(self.notice()["sort_priority"],
                           overdue_notification(ORDER, date(2026, 10, 7))["sort_priority"])

    def test_the_shape_matches_the_notification_schema(self):
        from stripe_link.domain.documents import validate_notification
        validate_notification(self.notice())


if __name__ == "__main__":
    unittest.main()
