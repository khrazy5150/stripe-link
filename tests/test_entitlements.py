import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain.entitlements import (
    EntitlementError,
    assert_entitled,
    is_entitled,
    plan_entitlements,
    tenant_entitlement_set,
)
from handlers import services


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

    def test_tenant_entitlement_set(self):
        self.assertEqual(tenant_entitlement_set({"entitlements": ["booking"]}), {"booking"})
        self.assertEqual(tenant_entitlement_set({}), set())
        # Exempt tenants get everything.
        self.assertIn("booking", tenant_entitlement_set({"billing_exempt": True}))
        self.assertIn("sites", tenant_entitlement_set({"billing_exempt": True}))

    def test_is_entitled_and_assert(self):
        self.assertTrue(is_entitled({"entitlements": ["booking"]}, "booking"))
        self.assertFalse(is_entitled({"entitlements": ["landing_pages"]}, "booking"))
        self.assertTrue(is_entitled({}, "unknown_ungated"))  # ungated cap never blocks
        with self.assertRaises(EntitlementError):
            assert_entitled({"entitlements": []}, "booking")


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
        resp = self._post_service(FakeTenantRepo([{"tenant_id": "t1", "billing_plan_key": "basic", "entitlements": ["landing_pages"]}]))
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "plan_upgrade_required")

    def test_require_capability_fails_open_on_missing_profile(self):
        # No profile row -> fail open (do not block an un-backfilled tenant).
        gate = services._require_capability(
            {"body": json.dumps({"tenant_id": "t1"})}, "booking", FakeTenantRepo([]))
        self.assertIsNone(gate)

    def test_require_capability_allows_exempt(self):
        gate = services._require_capability(
            {"body": json.dumps({"tenant_id": "t1"})}, "booking",
            FakeTenantRepo([{"tenant_id": "t1", "billing_exempt": True}]))
        self.assertIsNone(gate)


if __name__ == "__main__":
    unittest.main()
