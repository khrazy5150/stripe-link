import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain.entitlements import (
    CAPABILITIES,
    FREE_TIER_CAPABILITIES,
    EntitlementError,
    assert_entitled,
    is_entitled,
    plan_entitlements,
    tenant_entitlement_set,
)

CAPABILITIES_KEYS = set(CAPABILITIES)
from stripe_link.entitlement_gate import require_capability
from handlers import pages, services


class FakeTenantRepo:
    def __init__(self, tenants):
        self.docs = {t["tenant_id"]: dict(t) for t in tenants}

    def get(self, tenant_id, _sk=None):
        doc = self.docs.get(tenant_id)
        return dict(doc) if doc else None


class EntitlementModelTests(unittest.TestCase):
    def test_plan_entitlements_lists_enabled_known_caps(self):
        plan = {"entitlements": {"booking": True, "sites": False, "landing_pages": True, "bogus": True}}
        self.assertEqual(plan_entitlements(plan), ["booking", "landing_pages"])
        self.assertEqual(plan_entitlements({}), [])
        self.assertEqual(plan_entitlements(None), [])

    def test_subscribed_tenant_uses_its_entitlements_list_plus_free_floor(self):
        sub = {"billing_status": "active", "stripe_subscription_id": "sub_1", "entitlements": ["booking"]}
        self.assertEqual(tenant_entitlement_set(sub), {"booking"} | set(FREE_TIER_CAPABILITIES))

    def test_platform_trial_gets_full_access(self):
        # A fresh signup (trial, no subscription) sees ALL features until the trial expires.
        self.assertEqual(tenant_entitlement_set({"billing_status": "trial"}), set(CAPABILITIES_KEYS))
        self.assertEqual(tenant_entitlement_set({}), set(CAPABILITIES_KEYS))  # missing status defaults to trial

    def test_expired_platform_trial_downgrades_to_free_tier(self):
        # Free-forever model: expiry is a downgrade to the free floor, not a wall.
        expired = {"billing_status": "trial", "trial_ends_at": 1000}
        self.assertEqual(tenant_entitlement_set(expired, now=2000), set(FREE_TIER_CAPABILITIES))
        self.assertEqual(tenant_entitlement_set(expired, now=500), set(CAPABILITIES_KEYS))  # before expiry

    def test_suspended_gets_no_free_floor(self):
        suspended = {"billing_status": "suspended", "entitlements": ["booking"]}
        self.assertEqual(tenant_entitlement_set(suspended), {"booking"})

    def test_subscribed_trialing_uses_list_not_full_access(self):
        # Stripe 'trialing' after subscribing: has a subscription id, so it's the plan's entitlements (+ the free
        # floor), never the trial's full-access set.
        trialing = {"billing_status": "trial", "stripe_subscription_id": "sub_1", "entitlements": ["landing_pages"]}
        self.assertEqual(tenant_entitlement_set(trialing), set(FREE_TIER_CAPABILITIES))
        self.assertNotIn("booking", tenant_entitlement_set(trialing))

    def test_exempt_gets_everything(self):
        self.assertEqual(tenant_entitlement_set({"billing_exempt": True}), set(CAPABILITIES_KEYS))

    def test_is_entitled_and_assert(self):
        sub = {"billing_status": "active", "stripe_subscription_id": "sub_1", "entitlements": ["landing_pages"]}
        self.assertFalse(is_entitled(sub, "booking"))
        self.assertTrue(is_entitled(sub, "landing_pages"))
        self.assertTrue(is_entitled(sub, "unknown_ungated"))  # ungated cap never blocks
        with self.assertRaises(EntitlementError):
            assert_entitled(sub, "booking")


class ServicesBookingGateTests(unittest.TestCase):
    def _post_service(self, tenant_repo):
        return services.handler(
            {"httpMethod": "POST", "path": "/services",
             "body": json.dumps({"tenant_id": "t1", "service": {"name": "Cleaning"}})},
            None,
            # All repos injected (the handler builds them eagerly); none is reached when the gate blocks.
            services_repo=object(), fulfillers_repo=object(), availability_repo=object(),
            exceptions_repo=object(), appointments_repo=object(),
            tenant_repo=tenant_repo,
        )

    def test_service_create_blocked_without_booking_capability(self):
        # A SUBSCRIBED tenant on a plan without booking (a live trial would have full access instead).
        resp = self._post_service(FakeTenantRepo([{
            "tenant_id": "t1", "billing_status": "active", "stripe_subscription_id": "sub_1",
            "billing_plan_key": "basic", "entitlements": ["landing_pages"]}]))
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "plan_upgrade_required")

    def test_live_trial_tenant_can_create_service(self):
        # Full access during the platform trial: booking is allowed even though basic wouldn't include it.
        resp = self._post_service(FakeTenantRepo([{"tenant_id": "t1", "billing_status": "trial"}]))
        self.assertNotEqual(resp["statusCode"], 403)

    def test_require_capability_fails_open_on_missing_profile(self):
        # No profile row -> fail open (do not block an un-backfilled tenant).
        gate = require_capability(
            {"body": json.dumps({"tenant_id": "t1"})}, "booking", FakeTenantRepo([]))
        self.assertIsNone(gate)

    def test_require_capability_allows_exempt(self):
        gate = require_capability(
            {"body": json.dumps({"tenant_id": "t1"})}, "booking",
            FakeTenantRepo([{"tenant_id": "t1", "billing_exempt": True}]))
        self.assertIsNone(gate)

    def test_require_capability_blocks_unentitled(self):
        gate = require_capability(
            {"body": json.dumps({"tenant_id": "t1"})}, "booking",
            FakeTenantRepo([{"tenant_id": "t1", "billing_status": "active",
                             "stripe_subscription_id": "sub_1", "entitlements": ["landing_pages"]}]))
        self.assertEqual(gate["statusCode"], 403)

    def test_pages_create_gated_on_landing_pages(self):
        # A second handler proves the wiring beyond services. landing_pages is in the free-forever floor, so the
        # only tenant it can block is a SUSPENDED one (no floor) whose list lacks the capability -> 403.
        resp = pages.handler(
            {"httpMethod": "POST", "path": "/pages", "body": json.dumps({"tenant_id": "t1", "page": {}})},
            None, repository=object(),
            tenant_repo=FakeTenantRepo([{"tenant_id": "t1", "billing_status": "suspended",
                                         "stripe_subscription_id": "sub_1", "entitlements": ["booking"]}]))
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "plan_upgrade_required")

    def test_pages_create_passes_for_downgraded_free_tenant(self):
        # A canceled/downgraded tenant keeps the floor: the gate passes (the 400 is ordinary validation).
        resp = pages.handler(
            {"httpMethod": "POST", "path": "/pages", "body": json.dumps({"tenant_id": "t1", "page": {}})},
            None, repository=object(),
            tenant_repo=FakeTenantRepo([{"tenant_id": "t1", "billing_status": "canceled", "entitlements": []}]))
        self.assertNotEqual(resp["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
