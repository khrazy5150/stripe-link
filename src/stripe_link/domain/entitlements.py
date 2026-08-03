from typing import Any

from stripe_link.domain.billing_status import is_trial_expired

# Gateable PRODUCT features per plan. Core admin (dashboard, payments, products, offers, coupons, orders, refunds,
# customers, notifications, profile, configuration) is always-on and NOT listed here. `view` is the dashboard menu
# view key so the UI can DISABLE (not hide) an unentitled item with an upgrade hint. A plan enables a capability via
# its `entitlements` map in PlatformPlansTable; the enabled set is denormalized onto the tenant profile
# (tenant.entitlements) at subscribe + on the billing webhook, so the guard below is a pure profile check.
# See plans/SAAS_BILLING_PAYWALL.md.
CAPABILITIES: dict[str, dict[str, str]] = {
    "landing_pages": {"label": "Landing Pages", "view": "landingPages"},
    "booking": {"label": "Booking & Appointments", "view": "services"},
    "sites": {"label": "Sites", "view": "sites"},
    "custom_domains": {"label": "Custom Domains", "view": "configuration"},
    "collections": {"label": "Collections", "view": "collections"},
    "ab_testing": {"label": "A/B Testing", "view": "abTesting"},
    "reviews": {"label": "Reviews", "view": "reviews"},
    "lead_capture": {"label": "Lead Capture", "view": "leads"},
    "invoicing": {"label": "Invoicing", "view": "invoices"},
    "bnpl": {"label": "Buy Now, Pay Later", "view": "stripeKeys"},
}


class EntitlementError(RuntimeError):
    def __init__(self, capability: str):
        label = CAPABILITIES.get(capability, {}).get("label", capability)
        super().__init__(f"Your plan does not include {label}. Upgrade to enable it.")
        self.capability = capability


def plan_entitlements(plan: dict[str, Any] | None) -> list[str]:
    """The enabled capability keys for a plan, from its `entitlements` map. Used to denormalize onto the tenant
    profile at subscribe / webhook time."""
    entitlements = (plan or {}).get("entitlements")
    if not isinstance(entitlements, dict):
        return []
    return sorted(cap for cap in CAPABILITIES if bool(entitlements.get(cap)))


def tenant_entitlement_set(tenant: dict[str, Any] | None, now: int | None = None) -> set[str]:
    """The capabilities a tenant currently has:
      - exempt (comped) tenants get everything;
      - a live PLATFORM trial (unsubscribed, not yet expired) gets FULL access (trial-first onboarding);
      - an EXPIRED platform trial gets nothing (the hard wall);
      - otherwise (subscribed / any other state) it's the denormalized `entitlements` list on the profile.
    See plans/SAAS_BILLING_PAYWALL.md."""
    tenant = tenant or {}
    if tenant.get("billing_exempt"):
        return set(CAPABILITIES)
    status = str(tenant.get("billing_status") or "trial")
    if status == "trial" and not tenant.get("stripe_subscription_id"):
        return set() if is_trial_expired(tenant, now) else set(CAPABILITIES)
    return {cap for cap in (tenant.get("entitlements") or []) if cap in CAPABILITIES}


def is_entitled(tenant: dict[str, Any] | None, capability: str, now: int | None = None) -> bool:
    if capability not in CAPABILITIES:
        return True  # an unknown/ungated capability is never blocked
    return capability in tenant_entitlement_set(tenant, now)


def assert_entitled(tenant: dict[str, Any] | None, capability: str) -> None:
    if not is_entitled(tenant, capability):
        raise EntitlementError(capability)
