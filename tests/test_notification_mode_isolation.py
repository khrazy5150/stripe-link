"""Test-mode activity must never read as real in a live tenant's bell.

ONE prod endpoint serves both Stripe modes by design (plans/STRIPE_MODE_DECOUPLING.md P3), so a tenant's
TEST subscription writes to the PROD tables. Orders carry `stripe_mode` and are filtered on read; ledger
entries carry `mode` and LedgerRepository filters on it. Notifications carried NEITHER — so a test-mode
renewal put "New sale" in the production bell, indistinguishable from money.

Measured when found (2026-09-23): `jb-notifications-prod` held 9 unstamped rows, against 9 orders all
stamped test and ZERO live orders. Every notification in production was test activity presented as real.
"""

import re
import unittest
from pathlib import Path

from stripe_link.repositories.documents import ModeScopedNotificationsRepository

ROOT = Path(__file__).resolve().parents[1]


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = dict(Item)


def _repo(mode=None):
    """Built directly rather than through `notifications_repository`, which reads the table name from the
    environment. Setting that variable at module scope leaked into the rest of the suite — two unrelated
    tests assert the behaviour when NOTIFICATIONS_TABLE is ABSENT, and both broke."""
    return ModeScopedNotificationsRepository(
        "jb-notifications-unit-test", document_type="notification",
        id_field="notification_id", table=FakeTable(), mode=mode,
    )


class StampOnWriteTests(unittest.TestCase):
    """Stamped at the repository, because five call sites build these and a sixth will be added."""

    def test_a_write_carries_the_mode_it_was_made_in(self):
        saved = _repo("test").put({"tenant_id": "t1", "notification_id": "n1", "title": "New sale"})

        self.assertEqual(saved["mode"], "test")

    def test_a_live_write_says_live(self):
        saved = _repo("live").put({"tenant_id": "t1", "notification_id": "n1", "title": "New sale"})

        self.assertEqual(saved["mode"], "live")

    def test_an_explicit_mode_on_the_document_is_not_overwritten(self):
        saved = _repo("live").put({"tenant_id": "t1", "notification_id": "n1", "mode": "test"})

        self.assertEqual(saved["mode"], "test")

    def test_an_unscoped_repository_stamps_nothing(self):
        saved = _repo().put({"tenant_id": "t1", "notification_id": "n1"})

        self.assertNotIn("mode", saved)


class FilterOnReadTests(unittest.TestCase):
    ROWS = [
        {"notification_id": "live1", "title": "New sale", "mode": "live"},
        {"notification_id": "test1", "title": "New sale", "mode": "test"},
        {"notification_id": "old1", "title": "New sale"},          # written before the stamp existed
    ]

    def test_a_live_view_shows_only_live(self):
        kept = _repo("live")._in_mode(self.ROWS)

        self.assertEqual([row["notification_id"] for row in kept], ["live1"])

    def test_an_unstamped_row_is_treated_as_TEST_not_live(self):
        # The nine rows that were already in production are all test activity. Showing them to a live
        # tenant is the failure; hiding a genuine one would merely be a missing bell.
        self.assertNotIn("old1", [row["notification_id"] for row in _repo("live")._in_mode(self.ROWS)])
        self.assertIn("old1", [row["notification_id"] for row in _repo("test")._in_mode(self.ROWS)])

    def test_an_unscoped_repository_still_returns_everything(self):
        # Legacy callers keep working; only a caller that ASKS for a mode gets isolation.
        self.assertEqual(len(_repo()._in_mode(self.ROWS)), 3)

    def test_the_paged_read_is_filtered_too(self):
        # Nothing pages notifications today, but an unfiltered inherited method is a leak waiting for the
        # first screen that does.
        repo = _repo("live")
        self.assertTrue(hasattr(repo, "list_page_for_tenant"))
        self.assertIn("_in_mode", repo.list_page_for_tenant.__code__.co_names)


class EveryCallSiteIsScopedTests(unittest.TestCase):
    """The bug was not a missing capability -- `ledger_repository` already took a mode and the callers
    did not pass it. This asserts the notifications equivalent cannot drift back."""

    def test_no_handler_builds_an_unscoped_notifications_repository(self):
        offenders = []
        for path in sorted((ROOT / "src" / "handlers").glob("*.py")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "notifications_repository(" not in line or "def notifications_repository" in line:
                    continue
                if not re.search(r"notifications_repository\([^)]*mode\s*=", line):
                    offenders.append(f"{path.name}:{line_no} builds notifications_repository() with no "
                                     "mode — its writes are unstamped and its reads unfiltered")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()


class ReviewInviteSweepTests(unittest.TestCase):
    """The invite sweep SENDS EMAIL to a real customer, so its mode isolation is the strictest case.

    Found the same day as the notification leak and worse in consequence: four invites in
    `jb-reviews-prod`, every one minted from a `cs_test_` checkout session, three still active — so a
    live person was being asked how they were enjoying a product they never bought. One had already
    been delivered.
    """

    SOURCE = (ROOT / "src" / "handlers" / "review_invites.py").read_text(encoding="utf-8")
    WEBHOOK = (ROOT / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
    PUBLIC = (ROOT / "src" / "handlers" / "reviews_public.py").read_text(encoding="utf-8")

    def test_the_sweep_reads_live_invites_only(self):
        # Mirrors the abandoned-cart sweep, which settled this question first: never email a real person
        # about test-mode activity.
        self.assertIn('review_invites_repository(mode="live")', self.SOURCE)

    def test_an_invite_is_minted_in_the_mode_of_the_purchase(self):
        self.assertIn("review_invites_repository(mode=mode)", self.WEBHOOK)

    def test_the_public_review_form_resolves_invites_in_the_requests_mode(self):
        self.assertIn("review_invites_repository(mode=mode)", self.PUBLIC)

    def test_no_caller_builds_an_unscoped_invites_repository(self):
        offenders = []
        for path in sorted((ROOT / "src" / "handlers").glob("*.py")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "review_invites_repository(" not in line:
                    continue
                if not re.search(r"review_invites_repository\([^)]*mode\s*=", line):
                    offenders.append(f"{path.name}:{line_no} builds review_invites_repository() with no "
                                     "mode — a test purchase can then email a real customer")
        self.assertEqual(offenders, [], "\n".join(offenders))
