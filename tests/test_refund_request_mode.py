"""Refund requests belong to one set of books, and the list must say which.

The bell and the refund list are served by the SAME handler, and the bell was already mode-scoped with a
comment explaining why: "one prod endpoint serves both modes, so the isolation is the reader's to
enforce." Refund requests in the same table were not — a request raised in test showed up in the live
Refunds screen (found 2026-10-18).

The repository is not mode-scoped and making it so would orphan every existing record, whose sort key
carries no mode. The order id carries it instead: `order_cs_live_...`.
"""
import json
import unittest

from handlers.notifications import list_refund_requests, refund_request_mode
from stripe_link.common import stripe_mode_from_reference


def request(rid="rr_1", order="order_cs_live_abc", **extra):
    return {"refund_request_id": rid, "tenant_id": "t1", "order_id": order, "created_at": 1, **extra}


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows

    def list_for_tenant(self, tenant_id):
        return [dict(r) for r in self.rows]


def listed(rows, mode):
    event = {"httpMethod": "GET", "queryStringParameters": {"mode": mode},
             "headers": {"X-Tenant-Id": "t1"}, "body": None, "requestContext": {}}
    resp = list_refund_requests(event, FakeRepo(rows))
    return [r["refund_request_id"] for r in json.loads(resp["body"])["refund_requests"]]


class TheModeOfARequestTests(unittest.TestCase):
    def test_it_is_derived_from_the_order_id(self):
        """No migration needed: the id has always said which books it belongs to."""
        self.assertEqual(refund_request_mode(request(order="order_cs_live_x")), "live")
        self.assertEqual(refund_request_mode(request(order="order_cs_test_x")), "test")

    def test_a_stored_mode_is_used_when_present(self):
        self.assertEqual(refund_request_mode(request(stripe_mode="test")), "test")

    def test_an_unreadable_request_has_no_mode(self):
        self.assertEqual(refund_request_mode(request(order="legacy_order_7")), "")

    def test_the_helper_finds_an_embedded_session_id(self):
        self.assertEqual(stripe_mode_from_reference("order_cs_test_abc"), "test")
        self.assertEqual(stripe_mode_from_reference("refund_cs_live_abc"), "live")
        self.assertEqual(stripe_mode_from_reference("nothing_here"), "")


class TheListIsScopedTests(unittest.TestCase):
    ROWS = [request("live_1", "order_cs_live_a"), request("test_1", "order_cs_test_b")]

    def test_live_does_not_show_test_requests(self):
        self.assertEqual(listed(self.ROWS, "live"), ["live_1"])

    def test_test_does_not_show_live_requests(self):
        self.assertEqual(listed(self.ROWS, "test"), ["test_1"])

    def test_an_UNREADABLE_request_is_shown_in_BOTH(self):
        """Deliberately the lenient direction. A refund request is a customer waiting for their money;
        showing it twice is a worse-looking failure than hiding it, and a much better one."""
        rows = [request("mystery", "legacy_order_7")]
        self.assertEqual(listed(rows, "live"), ["mystery"])
        self.assertEqual(listed(rows, "test"), ["mystery"])

    def test_a_stored_mode_wins_over_nothing(self):
        rows = [request("stored", "legacy_order_7", stripe_mode="test")]
        self.assertEqual(listed(rows, "test"), ["stored"])
        self.assertEqual(listed(rows, "live"), [])


if __name__ == "__main__":
    unittest.main()
