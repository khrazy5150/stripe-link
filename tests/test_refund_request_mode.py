"""Refund requests belong to one set of books, and the list must say which.

The bell and the refund list are served by the SAME handler, and the bell was already mode-scoped with a
comment explaining why: "one prod endpoint serves both modes, so the isolation is the reader's to
enforce." Refund requests in the same table were not — a request raised in test showed up in the live
Refunds screen (found 2026-10-18).

The repository is not mode-scoped and making it so would orphan every existing record, whose sort key
carries no mode. The order id carries it instead: `order_cs_live_...`.
"""
import json
import os
import pathlib
import unittest
from unittest.mock import patch

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


class TheAlertGoesIntoTheSameBooksTests(unittest.TestCase):
    """A live refund request whose alert is filed under test is visible in neither place a tenant looks."""

    class Repo:
        def __init__(self, mode):
            self.notification_mode = mode
            self.puts = []

        def get(self, *a):
            return None

        def put(self, doc):
            self.puts.append(doc)
            return doc

    def test_a_matching_repository_is_used_as_is(self):
        from handlers.notifications import _notifications_for
        repo = self.Repo("live")
        self.assertIs(_notifications_for(repo, {"stripe_mode": "live"}), repo)

    def test_a_MISMATCHED_repository_is_not_used(self):
        """The handler builds the repo from the REQUEST's mode; the refund's own order id is the
        authority. When a submission arrives with no mode it falls back to test, and a live refund's
        alert would land in the test bell."""
        from handlers.notifications import _notifications_for
        repo = self.Repo("test")
        with patch.dict(os.environ, {"NOTIFICATIONS_TABLE": "jb-notifications-test"}):
            rebuilt = _notifications_for(repo, {"stripe_mode": "live"})
        self.assertIsNot(rebuilt, repo)
        self.assertEqual(rebuilt.notification_mode, "live")

    def test_without_a_table_it_keeps_what_it_had_rather_than_returning_nothing(self):
        """Degrading to the wrong bell is bad; degrading to NO alert is worse."""
        from handlers.notifications import _notifications_for
        repo = self.Repo("test")
        with patch.dict(os.environ, {"NOTIFICATIONS_TABLE": ""}):
            self.assertIs(_notifications_for(repo, {"stripe_mode": "live"}), repo)

    def test_a_stub_without_a_mode_is_left_alone(self):
        """Rebuilding here would quietly discard an injected fake and the test would stop testing."""
        from handlers.notifications import _notifications_for

        class Stub:
            pass
        stub = Stub()
        self.assertIs(_notifications_for(stub, {"stripe_mode": "live"}), stub)

    def test_an_unplaceable_request_keeps_whatever_it_had(self):
        from handlers.notifications import _notifications_for
        repo = self.Repo("test")
        self.assertIs(_notifications_for(repo, {}), repo)


class BothWritersAgreeTests(unittest.TestCase):
    """Two paths create a refund request: the buyer's receipt link and the API. A field that only one of
    them sets is how a derivation becomes the sole path and is then removed as dead code."""

    def test_the_buyer_path_stamps_the_mode(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "purchase_manage.py").read_text(encoding="utf-8")
        request_refund = source[source.index("def _request_refund("):]
        self.assertIn('document["stripe_mode"] = mode', request_refund)

    def test_the_api_path_stamps_it_too(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "notifications.py").read_text(encoding="utf-8")
        save = source[source.index("def save_refund_request("):]
        self.assertIn('document.setdefault("stripe_mode"', save)

    def test_a_buyer_request_is_placeable_even_unstamped(self):
        """The derivation stays the safety net for every request written before today."""
        self.assertEqual(lead_or_order_mode := refund_request_mode(
            {"refund_request_id": "rr_old", "order_id": "order_cs_live_zzz"}), "live")
        self.assertEqual(lead_or_order_mode, "live")
