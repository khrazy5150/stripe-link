import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain import platform_billing
from stripe_link.domain.platform_subscription_sync import reconcile_platform_subscription_event
from handlers import platform_subscription, test_page_serve


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


class FakeOpener:
    def __init__(self):
        self.calls = []
        self.bodies = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append((request.method, url))
        self.bodies.append(request.data.decode("utf-8") if request.data else "")
        if "/customers" in url:
            return FakeResponse({"id": "cus_test_1"})
        if "/checkout/sessions" in url:
            return FakeResponse({"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})
        if "/billing_portal/sessions" in url:
            return FakeResponse({"url": "https://billing.stripe.com/p/sess_1"})
        return FakeResponse({})


class FakeTenantRepo:
    def __init__(self, tenants):
        self.docs = {t["tenant_id"]: dict(t) for t in tenants}

    def get(self, tenant_id, _sk=None):
        doc = self.docs.get(tenant_id)
        return dict(doc) if doc else None

    def put(self, doc):
        self.docs[doc["tenant_id"]] = dict(doc)
        return doc


class FakePlansRepo:
    def __init__(self, plans, config, promos=None):
        self._plans = plans
        self._config = config
        self._promos = {str(p["promo_code"]).upper(): dict(p) for p in (promos or [])}

    def list_plans(self, mode):
        return [dict(p) for p in self._plans]

    def get_config(self, mode):
        return dict(self._config)

    def get_promo(self, mode, code):
        promo = self._promos.get(str(code).strip().upper())
        return dict(promo) if promo else None


def _basic_plans_repo(exempt_emails=None, promos=None):
    # trial_days 0 on the base plan: trials are promo-only (plans/SAAS_BILLING_PAYWALL.md).
    plan = {"plan_key": "basic", "label": "Bay Pass", "monthly_amount": 958,
            "price_id": "price_basic", "trial_days": 0, "active": True, "sort_order": 1, "fee_tier": "basic"}
    return FakePlansRepo([plan], {"default_plan_key": "basic", "exempt_emails": exempt_emails or []}, promos=promos)


def _tenant(**over):
    base = {"tenant_id": "t1", "owner": {"email": "owner@example.com"}, "billing_status": "trial"}
    base.update(over)
    return base


class SubscribeHandlerTests(unittest.TestCase):
    def setUp(self):
        platform_billing.reset_cache()

    def test_subscribe_creates_customer_and_checkout_session(self):
        opener = FakeOpener()
        tenants = FakeTenantRepo([_tenant()])
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1", "plan_key": "basic"})},
            None, tenant_repository=tenants, plans_repository=_basic_plans_repo(),
            opener=opener, secret_key="sk_test_x",
        )
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])["platform_billing"]
        self.assertEqual(body["checkout_url"], "https://checkout.stripe.com/c/cs_1")
        # Customer created + checkout session created; customer + plan recorded optimistically.
        self.assertTrue(any("/customers" in u for _, u in opener.calls))
        self.assertTrue(any("/checkout/sessions" in u for _, u in opener.calls))
        self.assertEqual(tenants.docs["t1"]["stripe_customer_id"], "cus_test_1")
        self.assertEqual(tenants.docs["t1"]["billing_price_id"], "price_basic")

    def test_subscribe_exempt_tenant_skips_stripe(self):
        opener = FakeOpener()
        tenants = FakeTenantRepo([_tenant(billing_exempt=True)])
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=tenants, plans_repository=_basic_plans_repo(),
            opener=opener, secret_key="sk_test_x",
        )
        body = json.loads(resp["body"])["platform_billing"]
        self.assertTrue(body["exempt"])
        self.assertEqual(body["billing_status"], "active")
        self.assertEqual(opener.calls, [])  # Stripe never called
        self.assertEqual(tenants.docs["t1"]["billing_status"], "active")

    def test_subscribe_exempt_by_config_email(self):
        opener = FakeOpener()
        tenants = FakeTenantRepo([_tenant()])
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe", "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=tenants, plans_repository=_basic_plans_repo(exempt_emails=["owner@example.com"]),
            opener=opener, secret_key="sk_test_x",
        )
        self.assertTrue(json.loads(resp["body"])["platform_billing"]["exempt"])
        self.assertEqual(opener.calls, [])

    def test_subscribe_rejects_unknown_plan(self):
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1", "plan_key": "ghost"})},
            None, tenant_repository=FakeTenantRepo([_tenant()]), plans_repository=_basic_plans_repo(),
            opener=FakeOpener(), secret_key="sk_test_x",
        )
        self.assertEqual(resp["statusCode"], 400)

    def test_portal_requires_customer(self):
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/portal", "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=FakeTenantRepo([_tenant()]), opener=FakeOpener(), secret_key="sk_test_x",
        )
        self.assertEqual(resp["statusCode"], 409)

    def test_portal_returns_url_when_customer_exists(self):
        opener = FakeOpener()
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/portal", "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=FakeTenantRepo([_tenant(stripe_customer_id="cus_x")]),
            opener=opener, secret_key="sk_test_x",
        )
        self.assertEqual(json.loads(resp["body"])["platform_billing"]["portal_url"], "https://billing.stripe.com/p/sess_1")

    def test_no_promo_means_no_trial(self):
        opener = FakeOpener()
        platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe", "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=FakeTenantRepo([_tenant()]), plans_repository=_basic_plans_repo(),
            opener=opener, secret_key="sk_test_x",
        )
        checkout_body = [b for b in opener.bodies if "line_items" in b][0]
        self.assertNotIn("trial_period_days", checkout_body)

    def test_promo_grants_free_trial(self):
        opener = FakeOpener()
        promos = [{"promo_code": "TRIAL14", "trial_days": 14, "active": True}]
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1", "promo_code": "trial14"})},  # case-insensitive
            None, tenant_repository=FakeTenantRepo([_tenant()]), plans_repository=_basic_plans_repo(promos=promos),
            opener=opener, secret_key="sk_test_x",
        )
        self.assertEqual(resp["statusCode"], 200)
        checkout_body = [b for b in opener.bodies if "line_items" in b][0]
        self.assertIn("subscription_data%5Btrial_period_days%5D=14", checkout_body)
        self.assertIn("subscription_data%5Bmetadata%5D%5Bpromo_code%5D=TRIAL14", checkout_body)

    def test_promo_applies_discount(self):
        opener = FakeOpener()
        promos = [{"promo_code": "HALFOFF", "stripe_promotion_code": "promo_abc", "active": True}]
        platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1", "promo_code": "HALFOFF"})},
            None, tenant_repository=FakeTenantRepo([_tenant()]), plans_repository=_basic_plans_repo(promos=promos),
            opener=opener, secret_key="sk_test_x",
        )
        checkout_body = [b for b in opener.bodies if "line_items" in b][0]
        self.assertIn("discounts%5B0%5D%5Bpromotion_code%5D=promo_abc", checkout_body)

    def test_invalid_promo_is_rejected(self):
        promos = [{"promo_code": "OLD", "trial_days": 14, "active": False}]  # inactive
        resp = platform_subscription.handler(
            {"httpMethod": "POST", "path": "/platform-billing/subscribe",
             "body": json.dumps({"tenant_id": "t1", "promo_code": "OLD"})},
            None, tenant_repository=FakeTenantRepo([_tenant()]), plans_repository=_basic_plans_repo(promos=promos),
            opener=FakeOpener(), secret_key="sk_test_x",
        )
        self.assertEqual(resp["statusCode"], 422)
        self.assertEqual(json.loads(resp["body"])["error"], "invalid_promo")

    def test_plans_lists_active_plans_and_current_status(self):
        resp = platform_subscription.handler(
            {"httpMethod": "GET", "path": "/platform-billing/plans", "queryStringParameters": {"tenant_id": "t1"}},
            None, tenant_repository=FakeTenantRepo([_tenant(billing_status="active", billing_plan_key="basic")]),
            plans_repository=_basic_plans_repo(),
        )
        body = json.loads(resp["body"])["platform_billing"]
        self.assertEqual([p["plan_key"] for p in body["plans"]], ["basic"])
        self.assertNotIn("price_id", body["plans"][0])  # internal field not exposed
        self.assertEqual(body["current"]["billing_status"], "active")


class ReconcileWebhookTests(unittest.TestCase):
    def _event(self, event_type, obj):
        return {"type": event_type, "data": {"object": obj}}

    def test_subscription_created_sets_status_and_ids(self):
        tenants = FakeTenantRepo([_tenant()])
        event = self._event("customer.subscription.created", {
            "id": "sub_1", "customer": "cus_1", "status": "trialing", "current_period_end": 1790000000,
            "metadata": {"tenant_id": "t1"},
            "items": {"data": [{"price": {"id": "price_basic"}}]},
        })
        result = reconcile_platform_subscription_event(event, mode="test", tenant_repo=tenants)
        self.assertEqual(result["billing_status"], "trial")
        self.assertEqual(tenants.docs["t1"]["stripe_subscription_id"], "sub_1")
        self.assertEqual(tenants.docs["t1"]["current_period_end"], 1790000000)
        self.assertEqual(tenants.docs["t1"]["billing_price_id"], "price_basic")

    def test_subscription_deleted_cancels(self):
        tenants = FakeTenantRepo([_tenant(billing_status="active")])
        result = reconcile_platform_subscription_event(
            self._event("customer.subscription.deleted", {"id": "sub_1", "metadata": {"tenant_id": "t1"}, "status": "canceled"}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(result["billing_status"], "canceled")
        self.assertEqual(tenants.docs["t1"]["billing_status"], "canceled")

    def test_invoice_payment_failed_sets_past_due(self):
        tenants = FakeTenantRepo([_tenant(billing_status="active")])
        reconcile_platform_subscription_event(
            self._event("invoice.payment_failed", {"subscription_details": {"metadata": {"tenant_id": "t1"}}}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(tenants.docs["t1"]["billing_status"], "past_due")

    def test_invoice_paid_reactivates(self):
        tenants = FakeTenantRepo([_tenant(billing_status="past_due")])
        reconcile_platform_subscription_event(
            self._event("invoice.paid", {"subscription_details": {"metadata": {"tenant_id": "t1"}},
                                          "lines": {"data": [{"period": {"end": 1791111111}}]}}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(tenants.docs["t1"]["billing_status"], "active")
        self.assertEqual(tenants.docs["t1"]["current_period_end"], 1791111111)

    def test_no_tenant_id_is_a_noop(self):
        tenants = FakeTenantRepo([_tenant()])
        result = reconcile_platform_subscription_event(
            self._event("customer.subscription.updated", {"id": "sub_1", "status": "active"}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(result["platform_billing"], "no_tenant_id")

    def test_exempt_tenant_ignored(self):
        tenants = FakeTenantRepo([_tenant(billing_exempt=True)])
        result = reconcile_platform_subscription_event(
            self._event("customer.subscription.updated", {"id": "sub_1", "status": "canceled", "metadata": {"tenant_id": "t1"}}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(result["platform_billing"], "exempt_ignored")
        self.assertEqual(tenants.docs["t1"]["billing_status"], "trial")  # untouched


class ServeGateTests(unittest.TestCase):
    def test_serving_blocked_helper(self):
        suspended = FakeTenantRepo([_tenant(billing_status="suspended")])
        active = FakeTenantRepo([_tenant(billing_status="active")])
        self.assertTrue(test_page_serve._serving_blocked("t1", suspended))
        self.assertFalse(test_page_serve._serving_blocked("t1", active))
        self.assertFalse(test_page_serve._serving_blocked("t1", FakeTenantRepo([])))  # missing profile -> serve
        self.assertFalse(test_page_serve._serving_blocked("t1", None))  # no repo -> serve

    def test_published_serve_blocked_for_suspended_tenant(self):
        class FakeRoutes:
            def find_by_id(self, code):
                return {"target_type": "page", "target_page_id": "p1", "tenant_id": "t1", "stripe_mode": "live"}

        resp = test_page_serve.handler(
            {"httpMethod": "GET", "path": "/published/abc", "pathParameters": {"code": "abc"}},
            None, repository=FakeRoutes(), tenant_repo=FakeTenantRepo([_tenant(billing_status="suspended")]),
        )
        self.assertEqual(resp["statusCode"], 402)


if __name__ == "__main__":
    unittest.main()
