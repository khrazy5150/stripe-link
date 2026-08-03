import os
import time
from typing import Any, Callable

from stripe_link.common import normalize_stripe_mode
from stripe_link.repositories.platform_plans import platform_plans_repository

# Manual edits to PlatformPlansTable take effect within this TTL (mirrors cached_billing_config, fees.py).
PLATFORM_BILLING_CACHE_TTL_SECONDS = 300
_CACHE: dict[str, dict[str, Any]] = {}


def platform_billing_mode() -> str:
    """The platform's OWN Stripe mode for billing tenants (Stripe Billing on the platform account) — DISTINCT from a
    tenant's storefront test/live mode. Live in production; set PLATFORM_BILLING_MODE=test to exercise the billing
    flow against Stripe test plans/prices. Webhook events instead derive the mode from event.livemode."""
    return normalize_stripe_mode(os.environ.get("PLATFORM_BILLING_MODE", "live"))


def _load(mode: str, repository: Any) -> dict[str, Any]:
    repo = repository or platform_plans_repository()
    plans: dict[str, Any] = {}
    for plan in repo.list_plans(mode):
        key = str(plan.get("plan_key") or "").strip()
        if key:
            plans[key] = plan
    config = repo.get_config(mode) or {}
    return {"plans": plans, "config": config}


def cached_platform_billing(
    mode: str, repository: Any | None = None, now_fn: Callable[[], float] = time.time
) -> dict[str, Any]:
    mode = normalize_stripe_mode(mode)
    now = now_fn()
    entry = _CACHE.get(mode)
    if entry and entry["expires_at"] > now:
        return entry["value"]
    value = _load(mode, repository)
    _CACHE[mode] = {"value": value, "expires_at": now + PLATFORM_BILLING_CACHE_TTL_SECONDS}
    return value


def platform_plan(mode: str, plan_key: str, repository: Any | None = None) -> dict[str, Any] | None:
    if not plan_key:
        return None
    return cached_platform_billing(mode, repository)["plans"].get(str(plan_key))


def active_platform_plans(mode: str, repository: Any | None = None) -> list[dict[str, Any]]:
    plans = cached_platform_billing(mode, repository)["plans"].values()
    return sorted((p for p in plans if p.get("active")), key=lambda p: int(p.get("sort_order") or 0))


def default_platform_plan_key(mode: str, repository: Any | None = None) -> str | None:
    return cached_platform_billing(mode, repository)["config"].get("default_plan_key")


def is_tenant_billing_exempt(
    mode: str, tenant_id: str = "", email: str = "", repository: Any | None = None
) -> bool:
    """A comped tenant: id/email in the config bypass list. Combined with the tenant's own billing_exempt flag by
    callers. Exempt tenants get NO Stripe subscription and are always in good standing."""
    config = cached_platform_billing(mode, repository)["config"]
    ids = {str(x) for x in (config.get("exempt_tenant_ids") or [])}
    emails = {str(x).strip().lower() for x in (config.get("exempt_emails") or [])}
    if tenant_id and str(tenant_id) in ids:
        return True
    return bool(email) and str(email).strip().lower() in emails


# Stripe subscription status -> our TenantProfile.billing_status. past_due is the DUNNING/grace window (still
# allowed by the good-standing guard); Stripe moves it to unpaid/canceled per the account's no-code dunning
# settings, which our guard then blocks. Unknown/interim states fail toward past_due (grace, not hard block).
_STRIPE_STATUS_MAP = {
    "trialing": "trial",
    "active": "active",
    "past_due": "past_due",
    "incomplete": "past_due",
    "unpaid": "suspended",
    "paused": "suspended",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


def billing_status_from_stripe(stripe_status: str) -> str:
    return _STRIPE_STATUS_MAP.get(str(stripe_status or "").strip(), "past_due")


def reset_cache() -> None:
    _CACHE.clear()
