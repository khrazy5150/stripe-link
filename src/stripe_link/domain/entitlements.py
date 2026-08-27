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
    "collections": {"label": "Collections", "view": "collections"},
    "ab_testing": {"label": "A/B Testing", "view": "abTesting"},
    "reviews": {"label": "Reviews", "view": "reviews"},
    "lead_capture": {"label": "Lead Capture", "view": "leads"},
    "invoicing": {"label": "Invoicing", "view": "invoices"},
    # These two are sub-features of shared core screens (custom domains lives inside Configuration; BNPL is a toggle
    # on the Payments screen), so they have NO menu `view` — locking the whole screen over a sub-feature would strand
    # a walled tenant away from Stripe-connect / settings. Still backend-gated at their own actions.
    "custom_domains": {"label": "Custom Domains", "view": ""},
    "bnpl": {"label": "Buy Now, Pay Later", "view": ""},
}


# The free-forever floor (2026-08-26 pricing pivot, plans/TODO.md "Pricing pivot"): every non-suspended tenant
# keeps the core earning loop — pages, the Sites they serve on, and Collections — no matter what happens to their
# trial or subscription. Premium capabilities gate ADMIN management only; public serving/checkout never gates.
# NOTE: this floor is code (not plan-table data) because the entitlement guard is a pure profile check with no
# table read — changing the floor is a deploy, by design a rare event.
FREE_TIER_CAPABILITIES: frozenset[str] = frozenset({"landing_pages", "sites", "collections"})


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
    """The capabilities a tenant currently has (free-forever model, 2026-08-26 pivot):
      - exempt (comped) tenants get everything;
      - a live PLATFORM trial (unsubscribed, not yet expired) gets FULL access (trial-first onboarding);
      - an EXPIRED platform trial downgrades to the FREE-TIER floor (no hard wall — the store keeps selling);
      - suspended tenants get only their denormalized list (no floor — a deliberate hold);
      - otherwise (subscribed / canceled / any other state) it's the denormalized `entitlements` list on the
        profile, plus the free-tier floor (a canceled subscriber reverts to free, never to nothing).
    See plans/SAAS_BILLING_PAYWALL.md and plans/TODO.md (Pricing pivot)."""
    tenant = tenant or {}
    if tenant.get("billing_exempt"):
        return set(CAPABILITIES)
    status = str(tenant.get("billing_status") or "trial")
    denormalized = {cap for cap in (tenant.get("entitlements") or []) if cap in CAPABILITIES}
    if status == "suspended":
        return denormalized
    if status == "trial" and not tenant.get("stripe_subscription_id"):
        return set(FREE_TIER_CAPABILITIES) if is_trial_expired(tenant, now) else set(CAPABILITIES)
    return denormalized | FREE_TIER_CAPABILITIES


def is_entitled(tenant: dict[str, Any] | None, capability: str, now: int | None = None) -> bool:
    if capability not in CAPABILITIES:
        return True  # an unknown/ungated capability is never blocked
    return capability in tenant_entitlement_set(tenant, now)


def assert_entitled(tenant: dict[str, Any] | None, capability: str) -> None:
    if not is_entitled(tenant, capability):
        raise EntitlementError(capability)
