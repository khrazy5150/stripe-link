import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain import platform_billing
from stripe_link.domain.billing_status import (
    BillingStatusError,
    assert_billing_in_good_standing,
    is_billing_in_good_standing,
)
from stripe_link.repositories.platform_plans import PlatformPlansRepository


class FakeTable:
    """Minimal in-memory DynamoDB Table stub keyed on (PK, SK)."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression=None, **kwargs):
        # The repo only queries PK == x AND SK begins_with "PLAN#"; emulate that.
        matched = [
            dict(v)
            for (pk, sk), v in self.items.items()
            if pk.startswith("PLATFORM_BILLING#") and sk.startswith("PLAN#")
        ]
        return {"Items": matched}


def basic_plan():
    return {
        "plan_key": "basic",
        "label": "Bay Pass",
        "monthly_amount": 958,
        "price_id": "price_basic_test",
        "product_id": "prod_basic_test",
        "trial_days": 14,
        "active": True,
        "sort_order": 1,
        "fee_tier": "basic",
    }


class PlatformPlansRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        self.repo = PlatformPlansRepository("jb-platform-plans-test", table=self.table)

    def test_put_and_get_plan_round_trips_without_leaking_keys(self):
        self.repo.put_plan("test", basic_plan())
        loaded = self.repo.get_plan("test", "basic")
        self.assertEqual(loaded["monthly_amount"], 958)
        self.assertNotIn("PK", loaded)
        self.assertNotIn("SK", loaded)
        self.assertEqual(loaded["billing_mode"], "test")

    def test_list_plans_is_scoped_to_plan_items(self):
        self.repo.put_plan("test", basic_plan())
        self.repo.put_config("test", {"default_plan_key": "basic", "exempt_emails": ["me@x.com"]})
        plans = self.repo.list_plans("test")
        self.assertEqual([p["plan_key"] for p in plans], ["basic"])  # config item excluded

    def test_non_jb_table_name_is_refused(self):
        from stripe_link.repositories.documents import ResourceIsolationError

        with self.assertRaises(ResourceIsolationError):
            PlatformPlansRepository("platform-plans-test", table=self.table)


class CachedLoaderTests(unittest.TestCase):
    def setUp(self):
        platform_billing.reset_cache()
        self.table = FakeTable()
        self.repo = PlatformPlansRepository("jb-platform-plans-test", table=self.table)
        self.repo.put_plan("test", basic_plan())
        self.repo.put_plan("test", {**basic_plan(), "plan_key": "pro", "monthly_amount": 1900, "active": False, "sort_order": 2})
        self.repo.put_config("test", {"default_plan_key": "basic", "exempt_tenant_ids": ["t_comp"], "exempt_emails": ["Comp@X.com"]})

    def test_active_plans_excludes_inactive_and_sorts(self):
        active = platform_billing.active_platform_plans("test", repository=self.repo)
        self.assertEqual([p["plan_key"] for p in active], ["basic"])

    def test_platform_plan_lookup(self):
        self.assertEqual(platform_billing.platform_plan("test", "pro", repository=self.repo)["monthly_amount"], 1900)
        self.assertIsNone(platform_billing.platform_plan("test", "nope", repository=self.repo))

    def test_exempt_by_id_and_email_case_insensitive(self):
        self.assertTrue(platform_billing.is_tenant_billing_exempt("test", tenant_id="t_comp", repository=self.repo))
        self.assertTrue(platform_billing.is_tenant_billing_exempt("test", email="comp@x.com", repository=self.repo))
        self.assertFalse(platform_billing.is_tenant_billing_exempt("test", tenant_id="other", email="a@b.com", repository=self.repo))

    def test_cache_serves_within_ttl(self):
        platform_billing.reset_cache()
        calls = {"n": 0}
        original = self.repo.list_plans

        def counting_list(mode):
            calls["n"] += 1
            return original(mode)

        self.repo.list_plans = counting_list
        platform_billing.cached_platform_billing("test", repository=self.repo, now_fn=lambda: 1000.0)
        platform_billing.cached_platform_billing("test", repository=self.repo, now_fn=lambda: 1000.0)
        self.assertEqual(calls["n"], 1)  # second call served from cache


class PromoTests(unittest.TestCase):
    def setUp(self):
        self.repo = PlatformPlansRepository("jb-platform-plans-test", table=FakeTable())

    def test_put_get_promo_is_case_insensitive(self):
        self.repo.put_promo("test", {"promo_code": "trial14", "trial_days": 14, "active": True})
        loaded = self.repo.get_promo("test", "TRIAL14")
        self.assertEqual(loaded["trial_days"], 14)
        self.assertEqual(loaded["promo_code"], "TRIAL14")  # normalized upper
        self.assertEqual(self.repo.get_promo("test", "Trial14")["trial_days"], 14)

    def test_platform_promo_reads_fresh(self):
        self.repo.put_promo("test", {"promo_code": "X", "trial_days": 30, "active": True})
        self.assertEqual(platform_billing.platform_promo("test", "x", repository=self.repo)["trial_days"], 30)
        self.assertIsNone(platform_billing.platform_promo("test", "nope", repository=self.repo))

    def test_promo_is_valid(self):
        self.assertTrue(platform_billing.promo_is_valid({"active": True}))
        self.assertFalse(platform_billing.promo_is_valid({"active": False}))
        self.assertFalse(platform_billing.promo_is_valid(None))
        self.assertFalse(platform_billing.promo_is_valid({"active": True, "expires_at": 1000}, now=2000))
        self.assertTrue(platform_billing.promo_is_valid({"active": True, "expires_at": 5000}, now=2000))
        self.assertFalse(platform_billing.promo_is_valid({"active": True, "max_redemptions": 2, "redemptions": 2}))
        self.assertTrue(platform_billing.promo_is_valid({"active": True, "max_redemptions": 2, "redemptions": 1}))


class BillingStatusFromStripeTests(unittest.TestCase):
    def test_status_mapping(self):
        cases = {
            "trialing": "trial",
            "active": "active",
            "past_due": "past_due",
            "incomplete": "past_due",
            "unpaid": "suspended",
            "canceled": "canceled",
            "incomplete_expired": "canceled",
            "something_new": "past_due",  # unknown -> grace, not hard block
        }
        for stripe_status, expected in cases.items():
            self.assertEqual(platform_billing.billing_status_from_stripe(stripe_status), expected, stripe_status)


class GoodStandingGuardTests(unittest.TestCase):
    def test_trial_active_pastdue_allowed(self):
        for status in ("trial", "active", "past_due"):
            assert_billing_in_good_standing({"billing_status": status})  # no raise

    def test_only_suspended_blocked(self):
        with self.assertRaises(BillingStatusError):
            assert_billing_in_good_standing({"billing_status": "suspended"})
        # Free-forever model: canceled downgrades to the free tier and keeps selling.
        assert_billing_in_good_standing({"billing_status": "canceled"})

    def test_exempt_always_allowed_even_when_suspended(self):
        assert_billing_in_good_standing({"billing_status": "suspended", "billing_exempt": True})
        self.assertTrue(is_billing_in_good_standing({"billing_status": "canceled", "billing_exempt": True}))

    def test_missing_profile_defaults_to_allowed(self):
        assert_billing_in_good_standing(None)
        self.assertTrue(is_billing_in_good_standing({}))


if __name__ == "__main__":
    unittest.main()
