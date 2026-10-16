"""Shutting a tenant down (plans/ADMIN_SITE.md §1c).

The tests that carry weight are the ones about the two failure directions. A suspension that can be lifted
by a Stripe webhook, or by a DynamoDB blip, or by the tenant editing a page, is not a suspension.
"""
import json
import unittest

from handlers import page_publish
from stripe_link.domain.platform_suspension import (
    SUSPENSION_REASONS,
    SuspendedError,
    assert_not_suspended,
    is_suspended,
    restore,
    suspend,
)

PROFILE = {"tenant_id": "t1", "document_type": "tenant_profile", "billing_status": "active"}


def suspended(**extra):
    return {**suspend(PROFILE, reason="illegal_products", by="admin@juniorbay.com", now=1000), **extra}


class TheFieldTests(unittest.TestCase):
    def test_a_suspension_does_not_live_in_billing_status(self):
        """THE trap this design exists to avoid. `billing_status` is written by
        `platform_subscription_sync` from Stripe events, so a suspension stored there would be overwritten
        with "active" by the next subscription webhook -- silently, with nobody watching."""
        out = suspended()
        self.assertEqual(out["platform_status"], "suspended")
        self.assertEqual(out["billing_status"], "active")  # untouched

    def test_a_billing_change_cannot_lift_it(self):
        """What that webhook actually does to a suspended profile: nothing."""
        after_webhook = {**suspended(), "billing_status": "active"}
        self.assertTrue(is_suspended(after_webhook))

    def test_absent_means_active(self):
        """Every existing tenant has no such field, and must keep working."""
        self.assertFalse(is_suspended(PROFILE))
        self.assertFalse(is_suspended({}))

    def test_it_records_who_why_and_when(self):
        out = suspended()
        self.assertEqual(out["suspended_reason"], "illegal_products")
        self.assertEqual(out["suspended_by"], "admin@juniorbay.com")
        self.assertEqual(out["suspended_at"], 1000)

    def test_an_unattributed_suspension_is_refused(self):
        with self.assertRaises(ValueError):
            suspend(PROFILE, reason="fraud", by="  ")

    def test_a_reason_outside_the_list_is_refused(self):
        with self.assertRaises(ValueError):
            suspend(PROFILE, reason="i_dont_like_them", by="admin@juniorbay.com")

    def test_other_needs_a_note(self):
        with self.assertRaises(ValueError):
            suspend(PROFILE, reason="other", by="admin@juniorbay.com", note="")
        self.assertTrue(suspend(PROFILE, reason="other", by="a@b.c", note="Court order."))

    def test_nothing_of_the_tenants_is_removed(self):
        """A suspension is a stop, not a purge: the evidence has to survive for whoever asks next."""
        rich = {**PROFILE, "stripe_account_id": "acct_1", "trial_ends_at": 99}
        out = suspend(rich, reason="fraud", by="a@b.c")
        self.assertEqual(out["stripe_account_id"], "acct_1")
        self.assertEqual(out["trial_ends_at"], 99)


class RestoringTests(unittest.TestCase):
    def test_it_clears_the_block(self):
        self.assertFalse(is_suspended(restore(suspended(), by="admin@juniorbay.com")))

    def test_the_history_is_kept(self):
        """'Has this account been suspended before' is a question the next report will ask."""
        out = restore(suspended(), by="admin@juniorbay.com", now=2000)
        self.assertEqual(out["last_suspension"]["reason"], "illegal_products")
        self.assertEqual(out["last_suspension"]["restored_at"], 2000)
        self.assertNotIn("suspended_reason", out)

    def test_restoring_an_active_tenant_is_refused(self):
        with self.assertRaises(ValueError):
            restore(PROFILE, by="admin@juniorbay.com")


class TheCheckoutGateTests(unittest.TestCase):
    def test_a_suspended_tenant_cannot_take_money(self):
        with self.assertRaises(SuspendedError):
            assert_not_suspended(suspended())

    def test_the_error_names_the_reason(self):
        try:
            assert_not_suspended(suspended())
        except SuspendedError as exc:
            self.assertEqual(exc.reason, "illegal_products")
            self.assertIn("illegal", str(exc).lower())

    def test_an_ordinary_tenant_passes(self):
        assert_not_suspended(PROFILE)
        assert_not_suspended(None)


class ThePublishGateTests(unittest.TestCase):
    """The lever that stops a takedown having a one-edit undo."""

    class Repo:
        def __init__(self, profile, explode=False):
            self.profile, self.explode = profile, explode

        def get(self, *_):
            if self.explode:
                raise RuntimeError("ProvisionedThroughputExceeded")
            return self.profile

    def test_a_suspended_tenants_page_is_not_published(self):
        self.assertTrue(page_publish._tenant_is_suspended(self.Repo(suspended()), {"tenant_id": "t1"}))

    def test_an_ordinary_tenants_page_is(self):
        self.assertFalse(page_publish._tenant_is_suspended(self.Repo(PROFILE), {"tenant_id": "t1"}))

    def test_an_unreadable_profile_FAILS_CLOSED(self):
        """Deliberately the opposite of `entitlement_gate`, which fails open and says why. A DynamoDB blip
        must not be all it takes to put a suspended tenant's page back on the air."""
        self.assertTrue(page_publish._tenant_is_suspended(
            self.Repo(None, explode=True), {"tenant_id": "t1"}))


class TheTakedownTests(unittest.TestCase):
    class Pages:
        def __init__(self, pages):
            self.pages = pages
            self.written = []

        def list_for_tenant(self, tenant_id):
            return [dict(p) for p in self.pages if p["tenant_id"] == tenant_id]

    def setUp(self):
        self.deleted = []
        self.pages = self.Pages([
            {"tenant_id": "t1", "page_id": "p1", "status": "published", "stripe_mode": "live"},
            {"tenant_id": "t1", "page_id": "p2", "status": "draft", "stripe_mode": "live"},
            {"tenant_id": "t2", "page_id": "p3", "status": "published", "stripe_mode": "live"},
        ])
        page_publish.delete_page_artifacts = lambda page, **kw: self.deleted.append(page["page_id"])
        self.addCleanup(setattr, page_publish, "delete_page_artifacts",
                        page_publish.delete_page_artifacts)

    def run_action(self, action="suspend_tenant", tenant="t1"):
        return page_publish._tenant_artifact_action(
            action, {"tenant_id": tenant}, pages_repo=self.pages, s3_client=object(),
            cloudfront_client=object())

    def test_it_removes_the_published_pages(self):
        result = self.run_action()
        self.assertTrue(result["ok"])
        self.assertEqual(self.deleted, ["p1"])
        self.assertEqual(result["page_count"], 1)

    def test_it_leaves_drafts_alone(self):
        """A draft has no artifact to remove; trying would be noise in the one log that must be readable."""
        self.run_action()
        self.assertNotIn("p2", self.deleted)

    def test_it_touches_only_this_tenant(self):
        self.run_action()
        self.assertNotIn("p3", self.deleted)

    def test_page_DOCUMENTS_are_not_modified(self):
        """Artifacts only. Flipping pages to `archived` would also detach them from their Site's route map,
        which a restore would not undo."""
        before = [dict(p) for p in self.pages.pages]
        self.run_action()
        self.assertEqual(self.pages.pages, before)

    def test_one_bad_page_does_not_abandon_the_rest(self):
        self.pages.pages.append(
            {"tenant_id": "t1", "page_id": "boom", "status": "published", "stripe_mode": "live"})

        def explode(page, **kw):
            if page["page_id"] == "boom":
                raise RuntimeError("AccessDenied")
            self.deleted.append(page["page_id"])
        page_publish.delete_page_artifacts = explode
        result = self.run_action()
        self.assertIn("p1", self.deleted)
        self.assertEqual([f["page_id"] for f in result["failed"]], ["boom"])

    def test_a_half_finished_takedown_does_not_report_success(self):
        """The admin has to know which pages are still up."""
        self.pages.pages.append(
            {"tenant_id": "t1", "page_id": "boom", "status": "published", "stripe_mode": "live"})
        page_publish.delete_page_artifacts = lambda page, **kw: (_ for _ in ()).throw(RuntimeError("no"))
        self.assertFalse(self.run_action()["ok"])

    def test_a_restore_writes_a_page_that_DIFFERS_from_the_stored_one(self):
        """A byte-identical PutItem produces no DynamoDB stream record, so the republish never runs: the
        restore reported "1 page" and the page stayed down (found on dev, 2026-10-16). The bumped
        `updated_at` is what makes the write a change.

        This test can only check the shape of the write -- a fake repository records a put either way,
        which is exactly why the live restore is verified against S3 rather than its own return value.
        """
        written = []
        import stripe_link.repositories.documents as documents

        class Repo:
            def put(self, page):
                written.append(page)
        original = documents.pages_repository
        page_publish.pages_repository = lambda **kw: Repo()
        self.addCleanup(setattr, page_publish, "pages_repository", original)
        self.pages.pages[0]["updated_at"] = 1
        self.run_action(action="restore_tenant")
        self.assertEqual(len(written), 1)
        self.assertNotEqual(written[0]["updated_at"], 1)

    def test_an_unknown_action_does_nothing(self):
        result = self.run_action(action="delete_everything")
        self.assertFalse(result["ok"])
        self.assertEqual(self.deleted, [])

    def test_it_needs_a_tenant(self):
        result = page_publish._tenant_artifact_action("suspend_tenant", {}, pages_repo=self.pages)
        self.assertFalse(result["ok"])
        self.assertEqual(self.deleted, [])


if __name__ == "__main__":
    unittest.main()
