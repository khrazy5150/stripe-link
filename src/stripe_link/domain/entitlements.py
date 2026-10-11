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
    # Gate 1 of three (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.8): may this tenant use AI Builder AT ALL,
    # which is a different question from how many generations they are entitled to. No menu `view` -- it is
    # a fork off the product wizard, not a screen, so gating a whole screen over it would strand a tenant
    # away from their own catalogue.
    "ai_builder": {"label": "AI Builder", "view": ""},
    "bnpl": {"label": "Buy Now, Pay Later", "view": ""},
}


# The free-forever floor (2026-08-26 pricing pivot, plans/TODO.md "Pricing pivot"): every non-suspended tenant
# keeps the core earning loop — pages, the Sites they serve on, and Collections — no matter what happens to their
# trial or subscription. Premium capabilities gate ADMIN management only; public serving/checkout never gates.
# NOTE: this floor is code (not plan-table data) because the entitlement guard is a pure profile check with no
# table read — changing the floor is a deploy, by design a rare event.
FREE_TIER_CAPABILITIES: frozenset[str] = frozenset({"landing_pages", "sites", "collections"})


# NOT GENERALLY AVAILABLE. A capability listed here is granted ONLY by an explicit per-tenant beta grant
# (`tenant.beta`), never by a plan, never by the trial's full access, and never by a comped account.
#
# This is the answer to "can a tenant try a feature before it ships?" (plans/MONEY_ACROSS_SILOS.md P1).
# The author's original idea was a staging DEPLOYMENT, which cannot work: a third silo starts with empty
# tables, so a tenant's staging work would be stranded the day the feature graduated -- the exact failure
# that prompted the question, rebuilt deliberately. A flag in production gives them the feature on their
# real data, and graduating it is deleting a line from this set.
#
# EMPTY TODAY, and that is the correct starting state: every capability currently in CAPABILITIES has
# shipped. Adding a name here is the act of making a feature beta-only.
BETA_CAPABILITIES: frozenset[str] = frozenset()

# What "everything" means for a comped account or a live trial. **Not `CAPABILITIES`**, which is the
# whole catalogue including anything unreleased -- declaring a beta feature would otherwise hand it to
# every exempt tenant and every trial on the day it was named, which is the one thing a beta must not do.
GENERAL_CAPABILITIES: frozenset[str] = frozenset(set(CAPABILITIES) - BETA_CAPABILITIES)


def beta_capabilities(tenant: dict[str, Any] | None) -> set[str]:
    """The unreleased capabilities this tenant has been let into.

    Read from `tenant.beta`, which is its OWN field for one specific reason: the subscription webhook
    writes `updates["entitlements"] = plan_entitlements(plan)` -- a wholesale overwrite
    (`platform_subscription_sync.py`). A beta grant stored there would be wiped by the tenant's next
    Stripe event, silently, at a time nobody could predict and in the middle of whatever they were doing.

    Filtered to known capabilities, so a typo grants nothing rather than something adjacent.
    """
    tenant = tenant or {}
    return {cap for cap in (tenant.get("beta") or []) if cap in CAPABILITIES}


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
    beta = beta_capabilities(tenant)
    if tenant.get("billing_exempt"):
        return set(GENERAL_CAPABILITIES) | beta
    status = str(tenant.get("billing_status") or "trial")
    denormalized = {cap for cap in (tenant.get("entitlements") or []) if cap in CAPABILITIES}
    if status == "suspended":
        # NO beta here, deliberately. Suspension is a hold on the whole account, and a beta grant is a
        # statement about which features exist, not about whether the account is in good standing.
        # Letting it through would make an unreleased feature the one thing a suspended tenant could use.
        return denormalized
    if status == "trial" and not tenant.get("stripe_subscription_id"):
        return ((set(FREE_TIER_CAPABILITIES) | beta) if is_trial_expired(tenant, now)
                else set(GENERAL_CAPABILITIES) | beta)
    return denormalized | FREE_TIER_CAPABILITIES | beta


AI_BUILDER = "ai_builder"


def can_use_ai_builder(tenant: dict[str, Any] | None, *, provider_config: dict[str, Any] | None = None,
                       now: int | None = None) -> bool:
    """Gate 1: may this tenant use AI Builder at all?

    Two independent grants, and the second is the point. The capability comes with a paid plan or a live
    trial. But a tenant on their OWN key is spending their own money through their own provider account, and
    refusing that would be withholding a feature the platform does not pay for -- so a verified BYOK
    configuration qualifies regardless of plan. That is the honest version of "bring your own key", and it
    keeps the acquisition story alive now that the free tier carries no platform-paid generations.

    "Verified" is deliberately strict: `verified_at` is set by a real generation, not by a catalogue lookup,
    because a key that exists in the database and cannot actually call a model is worse than none -- it
    admits a tenant to a feature that then fails.
    """
    if is_entitled(tenant, AI_BUILDER, now):
        return True
    from stripe_link.domain.ai_provider import is_verified, pays_platform

    config = provider_config or {}
    return bool(is_verified(config) and not pays_platform(str(config.get("provider") or "")))


def is_entitled(tenant: dict[str, Any] | None, capability: str, now: int | None = None) -> bool:
    if capability not in CAPABILITIES:
        return True  # an unknown/ungated capability is never blocked
    return capability in tenant_entitlement_set(tenant, now)


def assert_entitled(tenant: dict[str, Any] | None, capability: str) -> None:
    if not is_entitled(tenant, capability):
        raise EntitlementError(capability)
