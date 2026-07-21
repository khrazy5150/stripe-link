"""Stripe Connect `account.updated` → verification state, NAP auto-seed, and Site indexing eligibility
(plans/SITE_OBJECT.md Phase 2.3, plans/BUSINESS_PROFILE_AND_GBP.md).

Pure functions only — the webhook handler does the I/O. Verification follows TP-08; NAP auto-seed is
fill-empty-only with per-field provenance (never clobbers what the tenant or another source set).
"""
from typing import Any

from stripe_link.domain.documents import _E164_RE, normalize_country, normalize_e164

# A disabled_reason that means the account is actively restricted/rejected (not merely awaiting review).
_RESTRICTING_DISABLED_REASONS = {"listed", "under_review", "platform_paused", "other"}


def connect_verification_state(account: dict[str, Any]) -> str:
    """Map a Stripe account object to one of: not_started | pending | verified | restricted (TP-08).
    charges_enabled is the gate; a restricting disabled_reason overrides it."""
    disabled_reason = str((account.get("requirements") or {}).get("disabled_reason") or "")
    if disabled_reason.startswith("rejected") or disabled_reason in _RESTRICTING_DISABLED_REASONS:
        return "restricted"
    if account.get("charges_enabled"):
        return "verified"
    if account.get("details_submitted"):
        return "pending"
    return "not_started"


def connect_state_fields(account: dict[str, Any], *, now: int) -> dict[str, Any]:
    """The verification fields to persist on the stripe_keys doc from an account.updated event.
    None-valued keys are dropped so we never write empty attributes."""
    requirements = account.get("requirements") or {}
    state = connect_verification_state(account)
    fields = {
        "charges_enabled": bool(account.get("charges_enabled")),
        "payouts_enabled": bool(account.get("payouts_enabled")),
        "details_submitted": bool(account.get("details_submitted")),
        "connect_verification": state,
        "connect_disabled_reason": str(requirements.get("disabled_reason") or "") or None,
        "connect_country": str(account.get("country") or "") or None,
        "connect_verified_at": now if state == "verified" else None,
        "connect_state_updated_at": now,
    }
    return {key: value for key, value in fields.items() if value is not None}


def _address_seed(address: Any) -> dict[str, Any]:
    """Map a Stripe address ({line1,line2,city,state,postal_code,country}) to the business.address shape."""
    if not isinstance(address, dict):
        return {}
    line1 = str(address.get("line1") or "").strip()
    line2 = str(address.get("line2") or "").strip()
    street = ", ".join(part for part in (line1, line2) if part)
    out: dict[str, Any] = {}
    if street:
        out["street"] = street
    for source, target in (("city", "locality"), ("state", "region"), ("postal_code", "postal_code")):
        value = str(address.get(source) or "").strip()
        if value:
            out[target] = value
    country = normalize_country(address.get("country"))
    if country:
        out["country"] = country
    return out


def business_profile_seed(account: dict[str, Any]) -> dict[str, Any]:
    """Extract a business-identity seed (NAP) from a Stripe account's business_profile (company as fallback),
    shaped like user_profile.business and pre-normalized (phone→E.164, country→alpha-2). Only includes fields
    Stripe actually supplied and that pass their own validation, so seeding never produces an invalid profile."""
    business_profile = account.get("business_profile") or {}
    company = account.get("company") or {}
    seed: dict[str, Any] = {}
    name = str(business_profile.get("name") or company.get("name") or "").strip()
    if name:
        seed["name"] = name
    email = str(business_profile.get("support_email") or account.get("email") or "").strip()
    if email:
        seed["email"] = email
    phone = normalize_e164(business_profile.get("support_phone") or company.get("phone") or "")
    if _E164_RE.match(phone):
        seed["phone"] = phone
    address = _address_seed(business_profile.get("support_address") or company.get("address") or {})
    if address:
        seed["address"] = address
    return seed


def seed_business_identity(
    business: dict[str, Any] | None, seed: dict[str, Any], *, source: str = "stripe"
) -> tuple[dict[str, Any], bool]:
    """Fill ONLY empty fields of `business` from `seed`, stamping provenance in business['sources']. Never
    overwrites a value the tenant (or another source) already set — the fill-empty rule IS the "never clobber"
    guarantee. Returns (business, changed)."""
    business = dict(business or {})
    sources = dict(business.get("sources") or {})
    changed = False
    for key in ("name", "email", "phone"):
        if seed.get(key) and not str(business.get(key) or "").strip():
            business[key] = seed[key]
            sources[key] = source
            changed = True
    seed_address = seed.get("address") or {}
    if seed_address:
        address = dict(business.get("address") or {})
        address_changed = False
        for key, value in seed_address.items():
            if value and not str(address.get(key) or "").strip():
                address[key] = value
                address_changed = True
        if address_changed:
            business["address"] = address
            sources["address"] = source
            changed = True
    if changed:
        business["sources"] = sources
    return business, changed


def compute_site_eligibility(
    site: dict[str, Any], *, connect_verified: bool, connect_restricted: bool, domain_verified: bool
) -> str:
    """Indexing eligibility (SITE_OBJECT.md §2.2): a Site is index-eligible only with BOTH a verified custom
    domain AND a verified Stripe Connect account. Returns one of blocked | pending | eligible | revoked.

    NOTE: the custom-domain→Site bridge is deferred (Phase 2.3 scope), so today `domain_verified` is False for
    every Site (all platform-hosted) → eligibility tops out at 'pending'. That is the correct, safe default:
    nothing on platform infrastructure is ever index-eligible."""
    hosting = (site or {}).get("hosting") or {}
    has_verified_domain = hosting.get("type") == "custom" and bool(domain_verified)
    if connect_restricted:
        # An actively restricted account revokes a previously-eligible Site; otherwise there is nothing to lose.
        return "revoked" if has_verified_domain else "blocked"
    if has_verified_domain and connect_verified:
        return "eligible"
    if has_verified_domain or connect_verified:
        return "pending"
    return "blocked"
