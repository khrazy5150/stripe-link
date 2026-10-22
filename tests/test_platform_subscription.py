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
            "price_id": "price_basic", "trial_days": 0, "active": True, "sort_order": 1, "fee_tier": "basic",
            "entitlements": {"landing_pages": True, "booking": False}}
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
        # Customer created + checkout session created; ONLY the customer id is recorded (not subscribed yet).
        self.assertTrue(any("/customers" in u for _, u in opener.calls))
        self.assertTrue(any("/checkout/sessions" in u for _, u in opener.calls))
        self.assertEqual(tenants.docs["t1"]["stripe_customer_id"], "cus_test_1")
        # Not marked as subscribed here — the webhook does that on subscription.created (abandoned Checkout stays trial).
        self.assertNotIn("billing_plan_key", tenants.docs["t1"])
        self.assertNotIn("entitlements", tenants.docs["t1"])

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
        # The synthesised Free card leads; the sellable plans follow it.
        self.assertEqual([p.get("plan_key") for p in body["plans"]], ["", "basic"])
        self.assertTrue(body["plans"][0]["free"])
        for card in body["plans"]:
            self.assertNotIn("price_id", card)  # internal field not exposed
        self.assertEqual(body["current"]["billing_status"], "active")


class ReconcileWebhookTests(unittest.TestCase):
    def setUp(self):
        platform_billing.reset_cache()

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

    def test_subscription_updated_denormalizes_entitlements(self):
        tenants = FakeTenantRepo([_tenant(billing_plan_key="basic")])
        event = self._event("customer.subscription.updated", {
            "id": "sub_1", "status": "active", "metadata": {"tenant_id": "t1", "plan_key": "basic"},
        })
        reconcile_platform_subscription_event(
            event, mode="test", tenant_repo=tenants, plans_repository=_basic_plans_repo())
        self.assertEqual(tenants.docs["t1"]["entitlements"], ["landing_pages"])

    def test_the_image_allowance_and_its_quality_ceiling_travel_with_the_plan(self):
        """They MUST be denormalized: the generation path reads them off the profile precisely so it
        never touches the plans table, and a ceiling left behind there would be read on every request."""
        plan = {"plan_key": "basic", "label": "Bay Pass", "monthly_amount": 958, "price_id": "price_basic",
                "trial_days": 0, "active": True, "sort_order": 1, "fee_tier": "basic",
                "entitlements": {"landing_pages": True}, "ai_generations": 20,
                "ai_images": 30, "ai_image_qualities": ["low", "high"]}
        tenants = FakeTenantRepo([_tenant(billing_plan_key="basic")])
        event = self._event("customer.subscription.updated", {
            "id": "sub_1", "status": "active", "metadata": {"tenant_id": "t1", "plan_key": "basic"},
        })
        reconcile_platform_subscription_event(
            event, mode="test", tenant_repo=tenants,
            plans_repository=FakePlansRepo([plan], {"default_plan_key": "basic"}))
        self.assertEqual(tenants.docs["t1"]["ai_images"], 30)
        # The GRANT travels, not a ceiling: a plan offering low and high must not arrive as "low".
        self.assertEqual(tenants.docs["t1"]["ai_image_qualities"], ["low", "high"])

    def test_a_plan_row_without_image_fields_does_not_strand_a_paying_tenant(self):
        # They bought something. A missing number gets the lowest paid rung, and a missing quality gets
        # the cheapest -- the two fallbacks fail in opposite directions on purpose.
        tenants = FakeTenantRepo([_tenant(billing_plan_key="basic")])
        event = self._event("customer.subscription.updated", {
            "id": "sub_1", "status": "active", "metadata": {"tenant_id": "t1", "plan_key": "basic"},
        })
        reconcile_platform_subscription_event(
            event, mode="test", tenant_repo=tenants, plans_repository=_basic_plans_repo())
        self.assertEqual(tenants.docs["t1"]["ai_images"], 30)
        self.assertEqual(tenants.docs["t1"]["ai_image_qualities"], ["low"])

    def test_cancellation_drops_the_image_allowance_and_resets_the_ceiling(self):
        """Left behind, a canceled tenant keeps generating on our bill. The stale CEILING matters too:
        a `high` sitting on a profile is still there, and still trusted, after its reason is gone."""
        tenants = FakeTenantRepo([_tenant(ai_images=30, ai_image_qualities=["low", "high"],
                                          stripe_subscription_id="sub_1")])
        event = self._event("customer.subscription.deleted", {
            "id": "sub_1", "status": "canceled", "metadata": {"tenant_id": "t1"},
        })
        reconcile_platform_subscription_event(event, mode="test", tenant_repo=tenants)
        self.assertEqual(tenants.docs["t1"]["ai_images"], 0)
        self.assertEqual(tenants.docs["t1"]["ai_generations"], 0)
        self.assertEqual(tenants.docs["t1"]["ai_image_qualities"], ["low"])
        # Subscribing writes the PLAN's fee tier onto the tenant (this fixture plan carries fee_tier "basic").
        self.assertEqual(tenants.docs["t1"]["tier_id"], "free")

    def test_subscription_updated_sets_pro_fee_tier_from_plan(self):
        plan = {"plan_key": "premium", "label": "Premium", "monthly_amount": 1900, "price_id": "price_prem",
                "trial_days": 0, "active": True, "sort_order": 1, "fee_tier": "pro",
                "entitlements": {"booking": True}}
        plans = FakePlansRepo([plan], {"default_plan_key": "premium", "exempt_emails": []})
        tenants = FakeTenantRepo([_tenant()])
        event = self._event("customer.subscription.updated", {
            "id": "sub_1", "status": "active", "metadata": {"tenant_id": "t1", "plan_key": "premium"},
        })
        reconcile_platform_subscription_event(event, mode="test", tenant_repo=tenants, plans_repository=plans)
        # The premium plan's fee_tier "pro" drives the 2% checkout fee via build_fee_context.
        self.assertEqual(tenants.docs["t1"]["tier_id"], "pro")
        self.assertEqual(tenants.docs["t1"]["entitlements"], ["booking"])

    def test_subscription_deleted_revokes_entitlements(self):
        tenants = FakeTenantRepo([_tenant(billing_status="active", entitlements=["landing_pages"], tier_id="pro")])
        reconcile_platform_subscription_event(
            self._event("customer.subscription.deleted", {"id": "sub_1", "metadata": {"tenant_id": "t1"}, "status": "canceled"}),
            mode="test", tenant_repo=tenants)
        self.assertEqual(tenants.docs["t1"]["entitlements"], [])
        # Cancellation (fired at period end for cancel_at_period_end) reverts fees to the free tier.
        self.assertEqual(tenants.docs["t1"]["tier_id"], "free")

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


class WebhookOrderingGuardTests(unittest.TestCase):
    """Stripe doesn't guarantee delivery order: an older event must not clobber a newer one (the
    incomplete-after-paid past_due bug, observed 2026-08-27)."""

    def _event(self, event_type, obj, created):
        return {"type": event_type, "created": created, "data": {"object": obj}}

    def test_stale_event_is_skipped(self):
        tenants = FakeTenantRepo([_tenant(billing_status="active", last_billing_event_at=2000)])
        result = reconcile_platform_subscription_event(
            self._event("customer.subscription.updated",
                        {"id": "sub_1", "status": "incomplete", "metadata": {"tenant_id": "t1"}}, created=1000),
            mode="test", tenant_repo=tenants)
        self.assertEqual(result["platform_billing"], "stale_event_skipped")
        self.assertEqual(tenants.docs["t1"]["billing_status"], "active")  # not clobbered to past_due

    def test_newer_event_applies_and_advances_the_clock(self):
        tenants = FakeTenantRepo([_tenant(billing_status="past_due", last_billing_event_at=1000)])
        result = reconcile_platform_subscription_event(
            self._event("invoice.paid", {"metadata": {"tenant_id": "t1"}}, created=3000),
            mode="test", tenant_repo=tenants)
        self.assertEqual(result["billing_status"], "active")
        self.assertEqual(tenants.docs["t1"]["last_billing_event_at"], 3000)


class CancelResumeTests(unittest.TestCase):
    """In-app cancel/resume — sets cancel_at_period_end on the Stripe subscription, no portal round-trip."""

    class _SubOpener(FakeOpener):
        def __init__(self, cancel_at_period_end):
            super().__init__()
            self._cape = cancel_at_period_end

        def __call__(self, request, timeout=None):
            url = request.full_url
            self.calls.append((request.method, url))
            self.bodies.append(request.data.decode("utf-8") if request.data else "")
            if "/subscriptions/" in url:
                return FakeResponse({"id": "sub_1", "cancel_at_period_end": self._cape,
                                     "current_period_end": 1790000000})
            return FakeResponse({})

    def _post(self, path, tenants, opener):
        return platform_subscription.handler(
            {"httpMethod": "POST", "path": path, "body": json.dumps({"tenant_id": "t1"})},
            None, tenant_repository=tenants, opener=opener, secret_key="sk_test_x")

    def test_cancel_sets_cancel_at_period_end(self):
        opener = self._SubOpener(True)
        tenants = FakeTenantRepo([_tenant(stripe_subscription_id="sub_1", billing_status="active")])
        resp = self._post("/platform-billing/cancel", tenants, opener)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])["platform_billing"]
        self.assertTrue(body["cancel_at_period_end"])
        self.assertEqual(body["current_period_end"], 1790000000)
        self.assertIn("cancel_at_period_end=true", opener.bodies[0])
        self.assertTrue(tenants.docs["t1"]["cancel_at_period_end"])  # reflected immediately

    def test_resume_unsets_cancel_at_period_end(self):
        opener = self._SubOpener(False)
        tenants = FakeTenantRepo([_tenant(stripe_subscription_id="sub_1", billing_status="active",
                                          cancel_at_period_end=True)])
        resp = self._post("/platform-billing/resume", tenants, opener)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("cancel_at_period_end=false", opener.bodies[0])
        self.assertFalse(tenants.docs["t1"]["cancel_at_period_end"])

    def test_cancel_requires_subscription(self):
        resp = self._post("/platform-billing/cancel", FakeTenantRepo([_tenant()]), FakeOpener())
        self.assertEqual(resp["statusCode"], 409)


class PlanCardsSayWhatYouGetTests(unittest.TestCase):
    """Two plans showing nothing but a price are indistinguishable -- a $29 tier reads as a dearer $19."""

    def test_allowances_become_plain_english(self):
        from handlers.platform_subscription import _public_plan
        card = _public_plan({"plan_key": "pro", "label": "Pro", "monthly_amount": 2900,
                             "ai_generations": 30, "ai_images": 300})
        self.assertEqual(card["features"],
                         ["30 AI-written pages a month", "300 AI images a month"])

    def test_hand_written_features_win(self):
        # An admin who wrote their own copy meant it.
        from handlers.platform_subscription import _public_plan
        card = _public_plan({"plan_key": "p", "features": ["Mine"], "ai_images": 9})
        self.assertEqual(card["features"], ["Mine"])

    def test_a_capability_that_does_not_exist_yet_is_not_advertised(self):
        # ai_videos has no generator behind it. Selling it on a card would be a promise.
        from handlers.platform_subscription import _public_plan
        card = _public_plan({"plan_key": "p", "ai_videos": 20, "ai_images": 5})
        self.assertEqual(card["features"], ["5 AI images a month"])

    def test_a_zero_allowance_is_not_listed(self):
        from handlers.platform_subscription import _public_plan
        card = _public_plan({"plan_key": "p", "ai_generations": 0, "ai_images": 200})
        self.assertEqual(card["features"], ["200 AI images a month"])

    def test_internals_never_reach_the_card(self):
        from handlers.platform_subscription import _public_plan
        card = _public_plan({"plan_key": "p", "price_id": "price_x", "product_id": "prod_x",
                             "fee_tier": "pro", "ai_images": 5})
        for secret in ("price_id", "product_id", "fee_tier"):
            self.assertNotIn(secret, card)


class ARetiredPlanStaysVisibleToItsSubscribersTests(unittest.TestCase):
    """Unticking Active hides a plan from new buyers. It must not hide it from the people ON it."""

    def _payload(self, tenant, plans):
        from handlers import platform_subscription as subs
        from stripe_link.domain import platform_billing
        platform_billing._CACHE.clear()
        # The tenant comes from VERIFIED claims on this route, not from a body.
        response = subs.handler(
            {"httpMethod": "GET", "path": "/platform/plans",
             "requestContext": {"authorizer": {"claims": {"sub": "t1"}}}}, None,
            tenant_repository=FakeTenantRepo([tenant]),
            plans_repository=FakePlansRepo(plans, {"default_plan_key": "basic"}))
        return json.loads(response["body"])["platform_billing"]

    ACTIVE = {"plan_key": "basic", "label": "Basic", "monthly_amount": 1900, "active": True,
              "sort_order": 1, "price_id": "price_19"}
    RETIRED = {"plan_key": "pro", "label": "Pro", "monthly_amount": 2900, "active": False,
               "sort_order": 2, "price_id": "price_29"}

    def test_a_retired_plan_is_hidden_from_someone_who_is_not_on_it(self):
        payload = self._payload(_tenant(), [self.ACTIVE, self.RETIRED])
        # The synthesised Free card leads; only the SELLABLE plans follow it.
        self.assertEqual([p.get("plan_key") for p in payload["plans"]], ["", "basic"])

    def test_but_a_subscriber_still_sees_the_plan_they_are_paying_for(self):
        # Otherwise nothing on the screen is marked Current, which reads as "you are not subscribed"
        # to the one person who definitely is.
        tenant = _tenant(billing_plan_key="pro", stripe_subscription_id="sub_1",
                         billing_status="active")
        payload = self._payload(tenant, [self.ACTIVE, self.RETIRED])
        keys = [p["plan_key"] for p in payload["plans"]]
        self.assertIn("pro", keys)
        retired = next(p for p in payload["plans"] if p["plan_key"] == "pro")
        self.assertTrue(retired["retired"])
        self.assertEqual(payload["current"]["billing_plan_key"], "pro")

    def test_an_active_plan_is_never_marked_retired(self):
        tenant = _tenant(billing_plan_key="basic", stripe_subscription_id="sub_1")
        payload = self._payload(tenant, [self.ACTIVE, self.RETIRED])
        basic = next(p for p in payload["plans"] if p["plan_key"] == "basic")
        self.assertNotIn("retired", basic)

    def test_a_plan_key_that_no_longer_exists_at_all_is_skipped(self):
        tenant = _tenant(billing_plan_key="deleted_plan", stripe_subscription_id="sub_1")
        payload = self._payload(tenant, [self.ACTIVE])
        self.assertEqual([p.get("plan_key") for p in payload["plans"]], ["", "basic"])


class TheFreeCardTests(unittest.TestCase):
    """Free is the ABSENCE of a subscription, so its card is synthesised -- and must not lie."""

    def _cards(self, config=None, plans=None):
        from handlers import platform_subscription as subs
        from stripe_link.domain import platform_billing
        platform_billing._CACHE.clear()
        response = subs.handler(
            {"httpMethod": "GET", "path": "/platform/plans",
             "requestContext": {"authorizer": {"claims": {"sub": "t1"}}}}, None,
            tenant_repository=FakeTenantRepo([_tenant()]),
            plans_repository=FakePlansRepo(
                plans if plans is not None else [
                    {"plan_key": "basic", "label": "Basic", "monthly_amount": 1900, "active": True,
                     "sort_order": 1, "price_id": "p", "ai_generations": 20, "ai_images": 200}],
                {"default_plan_key": "basic", **(config or {})}))
        return json.loads(response["body"])["platform_billing"]

    def test_free_comes_first_and_costs_nothing(self):
        cards = self._cards()["plans"]
        self.assertEqual(cards[0]["label"], "Free")
        self.assertEqual(cards[0]["monthly_amount"], 0)
        self.assertTrue(cards[0]["free"])

    def test_the_trial_line_is_DERIVED_from_the_same_config_the_gate_spends_from(self):
        # A number typed into marketing copy drifts from the number the generator enforces, and the
        # tenant finds out at the moment they are refused.
        cards = self._cards({"ai_trial_generations": 3, "ai_trial_images": 30})["plans"]
        line = [f for f in cards[0]["features"] if f.startswith("First ")][0]
        self.assertIn("3 AI-written pages", line)
        self.assertIn("30 AI images", line)

    def test_the_free_copy_is_editable_without_a_deploy(self):
        cards = self._cards({"free_plan_features": ["My own words"]})["plans"]
        self.assertEqual(cards[0]["features"][0], "My own words")

    def test_free_never_advertises_a_premium_capability(self):
        # ab_testing is NOT in FREE_TIER_CAPABILITIES and has its own menu view, so a tenant who
        # clicked it after reading the card would hit a wall.
        from stripe_link.domain.entitlements import FREE_TIER_CAPABILITIES
        self.assertNotIn("ab_testing", FREE_TIER_CAPABILITIES)
        copy = " ".join(self._cards()["plans"][0]["features"]).lower()
        self.assertNotIn("a/b", copy)

    def test_each_paid_tier_says_what_it_inherits(self):
        plans = [{"plan_key": "basic", "label": "Basic", "monthly_amount": 1900, "active": True,
                  "sort_order": 1, "price_id": "p", "ai_images": 200},
                 {"plan_key": "pro", "label": "Pro", "monthly_amount": 2900, "active": True,
                  "sort_order": 2, "price_id": "p", "ai_images": 300}]
        cards = self._cards(plans=plans)["plans"]
        self.assertEqual(cards[1]["features"][0], "Everything in Free, plus")
        self.assertEqual(cards[2]["features"][0], "Everything in Basic, plus")

    def test_a_retired_plan_does_not_claim_to_inherit(self):
        # It is shown for its own subscribers, not sold, so an inheritance line would be sales copy
        # on something nobody can buy -- and would renumber the ladder behind it.
        tenant = _tenant(billing_plan_key="old", stripe_subscription_id="sub_1")
        from handlers import platform_subscription as subs
        from stripe_link.domain import platform_billing
        platform_billing._CACHE.clear()
        response = subs.handler(
            {"httpMethod": "GET", "path": "/platform/plans",
             "requestContext": {"authorizer": {"claims": {"sub": "t1"}}}}, None,
            tenant_repository=FakeTenantRepo([tenant]),
            plans_repository=FakePlansRepo([
                {"plan_key": "basic", "label": "Basic", "monthly_amount": 1900, "active": True,
                 "sort_order": 1, "price_id": "p"},
                {"plan_key": "old", "label": "Old", "monthly_amount": 900, "active": False,
                 "sort_order": 9, "price_id": "p"}], {"default_plan_key": "basic"}))
        cards = json.loads(response["body"])["platform_billing"]["plans"]
        old = next(c for c in cards if c.get("plan_key") == "old")
        self.assertTrue(old["retired"])
        self.assertFalse(any(str(f).startswith("Everything in") for f in old.get("features") or []))


class ThePromoBoxTests(unittest.TestCase):
    def test_it_is_hidden_when_no_promo_could_work(self):
        from handlers import platform_subscription as subs
        from stripe_link.domain import platform_billing
        platform_billing._CACHE.clear()
        response = subs.handler(
            {"httpMethod": "GET", "path": "/platform/plans",
             "requestContext": {"authorizer": {"claims": {"sub": "t1"}}}}, None,
            tenant_repository=FakeTenantRepo([_tenant()]),
            plans_repository=FakePlansRepo([], {"default_plan_key": "basic"}))
        self.assertFalse(json.loads(response["body"])["platform_billing"]["promos_available"])
