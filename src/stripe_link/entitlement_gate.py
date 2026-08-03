"""Shared handler helper: gate a tenant-facing action on a plan capability.

Reads the tenant's DENORMALIZED entitlements (set at subscribe / billing webhook), so this is a pure profile
lookup — no plans-table read. FAILS OPEN when the profile is absent or the lookup errors (never break an
un-backfilled tenant); blocks only when a profile exists and lacks the capability, returning 403
plan_upgrade_required. See plans/SAAS_BILLING_PAYWALL.md and stripe_link/domain/entitlements.py.
"""
from typing import Any

from stripe_link.common import error_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.entitlements import CAPABILITIES, is_entitled
from stripe_link.repositories.documents import tenant_profiles_repository


def require_capability(event: dict[str, Any], capability: str, tenant_repo=None):
    """Return a 403 error response if the tenant lacks `capability`, else None (proceed)."""
    try:
        body = parse_json_body(event) if (event or {}).get("body") else {}
    except ValueError:
        body = {}
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return None
    try:
        tenant = (tenant_repo or tenant_profiles_repository()).get(tenant_id, tenant_id)
    except Exception:
        # Fail OPEN on ANY lookup problem (missing table/grant, throttle, un-backfilled tenant): a cross-cutting
        # gate must never itself 500 a tenant action. Enforcement degrades to "allowed", not broken.
        return None
    if tenant is None or is_entitled(tenant, capability):
        return None
    label = CAPABILITIES.get(capability, {}).get("label", capability)
    return error_response(
        f"Your plan does not include {label}. Upgrade to enable it.",
        status_code=403, code="plan_upgrade_required",
    )
