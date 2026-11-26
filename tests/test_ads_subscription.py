import json
from decimal import Decimal

from handlers.registration import register_tenant
from stripe_link.domain.ads_subscription import ads_subscription
from stripe_link.domain.platform_billing import reset_cache
from stripe_link.domain.platform_subscription_sync import reconcile_platform_subscription_event
from tests.test_platform_subscription import FakePlansRepo, FakeTenantRepo, _tenant


def test_ads_terms_follow_subscription_and_renewal_preserves_effective_date():
    reset_cache()
    plan = {
        "plan_key": "basic", "entitlements": {"ads": True}, "ads": {
            "mode": "promo", "max_active_campaigns": Decimal(1),
            "max_average_daily_budget_micros": 5_000_000, "monthly_fee_allowance_micros": 150_000_000,
            "management_fee_bps": 0,
        },
    }
    tenants = FakeTenantRepo([_tenant()])
    plans = FakePlansRepo([plan], {})

    def sync(kind, timestamp):
        reconcile_platform_subscription_event({
            "type": f"customer.subscription.{kind}", "created": timestamp,
            "data": {"object": {"id": "sub_1", "status": "active", "metadata": {
                "tenant_id": "t1", "plan_key": "basic",
            }}},
        }, mode="test", tenant_repo=tenants, plans_repository=plans)

    sync("created", 100)
    assert tenants.docs["t1"]["entitlements"] == ["ads"]
    snapshot = tenants.docs["t1"]["ads_subscription"]
    assert snapshot["max_average_daily_budget_micros"] == 5_000_000
    assert snapshot["effective_at"] == 100
    sync("updated", 200)
    assert tenants.docs["t1"]["ads_subscription"] == snapshot
    sync("deleted", 300)
    assert tenants.docs["t1"]["ads_subscription"] is None
    assert tenants.docs["t1"]["entitlements"] == []


def test_malformed_plan_limits_provide_no_ads_snapshot():
    plan = {"entitlements": {"ads": True}, "ads": {
        "mode": "scale", "max_active_campaigns": Decimal("NaN"),
        "max_average_daily_budget_micros": 5_000_000, "monthly_fee_allowance_micros": 0,
        "management_fee_bps": 1_000,
    }}
    assert ads_subscription(plan, billing_mode="live", effective_at=100) is None


def test_public_registration_cannot_grant_ads_or_replace_an_existing_profile():
    class Profiles:
        def put_if_absent(self, document):
            assert document["tenant_id"] == "tenant-1"
            return False

    base = {
        "schema_version": "2026-05-29", "document_type": "tenant_profile", "tenant_id": "tenant-1",
        "owner_email": "pilot@example.com",
        "owner": {"first_name": "Pilot", "last_name": "Tenant", "email": "pilot@example.com"},
    }
    for managed in ({"ads_subscription": {}}, {"ads_pilot_expires_at": 10}, {"beta": ["ads"]},
                    {"entitlements": ["ads"]}):
        response = register_tenant({"body": json.dumps({**base, **managed})}, [])
        assert response["statusCode"] == 400
    response = register_tenant({"body": json.dumps(base)}, [Profiles()])
    assert response["statusCode"] == 409
