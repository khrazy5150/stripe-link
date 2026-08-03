"""Per-tenant BNPL / installment payment-method settings (plans/BNPL_PAYMENT_METHODS.md).

The tenant toggles installment methods (Klarna first) from the dashboard Payments screen. Toggling ON requests
the matching Stripe *capability* on their connected Standard account; the live status + intent are cached on the
`stripe_keys` doc (per mode). Checkout reads that to decide which methods to add to the Checkout Session.

- GET  /payment-methods?mode=test  → toggles + live capability status + country eligibility for the screen.
- PUT  /payment-methods {mode, method, enabled} → request/revoke the capability, persist, return status.

Direct charges on Standard accounts let the PLATFORM request capabilities via `POST /v1/accounts/{acct}
capabilities[{cap}][requested]=…` with the platform secret key (no Stripe-Account header — we edit the account).
"""
import time

from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.bnpl import (
    BNPL_METHODS, apply_capability_statuses, capability_name, country_eligible, is_valid_method,
)
from stripe_link.domain.documents import DocumentValidationError, validate_stripe_keys_document
from stripe_link.entitlement_gate import require_capability
from stripe_link.repositories.documents import stripe_keys_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import get_platform_secret_key

SCHEMA_VERSION = "2026-07-31"


def handler(event, context, *, stripe_repo=None, stripe_caller=None, platform_key_loader=None, tenant_repo=None):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    stripe_repo = stripe_repo or stripe_keys_repository()
    stripe_caller = stripe_caller or stripe_request          # injectable for tests
    platform_key_loader = platform_key_loader or get_platform_secret_key

    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        return _read(tenant_id, _mode(query_params(event)), stripe_repo, stripe_caller, platform_key_loader)
    if method in {"PUT", "POST"}:
        body = parse_json_body(event) or {}
        tenant_id = tenant_id_from_event(event, body)        # PUT carries tenant_id in the JSON body
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        method_key = str(body.get("method") or "").strip()
        if not is_valid_method(method_key):
            return error_response("Unknown payment method.", code="invalid_method")
        gate = require_capability(event, "bnpl", tenant_repo)
        if gate is not None:
            return gate
        return _toggle(tenant_id, _mode(body), method_key, bool(body.get("enabled")),
                       stripe_repo, stripe_caller, platform_key_loader,
                       return_url=str(body.get("return_url") or "").strip())
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _mode(source):
    return "live" if str((source or {}).get("mode") or "test").strip().lower() == "live" else "test"


def _fetch_account(stripe_caller, platform_key_loader, mode, acct):
    """(country, capabilities-map) for the connected account, or ('', {}) on any failure — best-effort so the
    screen still renders the tenant's stored intent even if Stripe is unreachable."""
    try:
        account = stripe_caller("GET", f"/accounts/{acct}", api_key=platform_key_loader(mode))
        return str(account.get("country") or ""), (account.get("capabilities") or {})
    except StripeApiError:
        return "", {}


def _read(tenant_id, mode, stripe_repo, stripe_caller, platform_key_loader):
    keys = stripe_repo.get(tenant_id, mode=mode) or {}
    acct = str(keys.get("connect_account_id") or "").strip()
    stored = dict((keys.get("payment_methods") or {}).get("bnpl") or {})
    account_country, capabilities = _fetch_account(stripe_caller, platform_key_loader, mode, acct) if acct else ("", {})

    # Refresh the cached capability statuses from the live poll (same primitive the account.updated webhook uses).
    stored, changed = apply_capability_statuses(stored, capabilities, int(time.time())) if (acct and capabilities) \
        else (stored, False)
    methods = [{
        "method": key,
        "label": spec["label"],
        "enabled": bool((stored.get(key) or {}).get("enabled")),
        "capability_status": (stored.get(key) or {}).get("capability_status") or "unrequested",
        # No account country yet → don't claim ineligible (show enabled; Stripe is the final gate).
        "country_eligible": country_eligible(key, account_country) if account_country else True,
        "countries": sorted(spec["countries"]),
    } for key, spec in BNPL_METHODS.items()]

    # Cache the account country so publish-time on-page BNPL messaging can set the element's countryCode without
    # a live Stripe call (plans/BNPL_PAYMENT_METHODS.md P3).
    if account_country and (keys.get("payment_methods") or {}).get("account_country") != account_country:
        keys.setdefault("payment_methods", {})["account_country"] = account_country
        changed = True
    if changed:
        keys.setdefault("payment_methods", {})["bnpl"] = stored
        _persist(keys, stripe_repo)
    return json_response({"mode": mode, "connected": bool(acct), "account_country": account_country, "methods": methods})


def _toggle(tenant_id, mode, method_key, enabled, stripe_repo, stripe_caller, platform_key_loader, return_url=""):
    keys = stripe_repo.get(tenant_id, mode=mode)
    acct = str((keys or {}).get("connect_account_id") or "").strip()
    if not keys or not acct:
        return error_response("Connect a Stripe account before enabling installment methods.",
                              code="stripe_not_connected")
    # Connected accounts here are OAuth Standard accounts. Eligible BNPL (Klarna/Afterpay) is active by default;
    # Affirm/Zip start `unrequested`. When a tenant toggles a not-yet-active method ON we REQUEST the capability
    # for them (platform key) so they never have to open their Stripe dashboard. Stripe won't force it active —
    # it collects requirements first — but for a verified account it usually activates (the account.updated
    # webhook then flips this cache to active with no polling). If requirements remain, we best-effort mint a
    # hosted Account Link so they finish in one flow. In TEST mode the request is live-only and errors, so we
    # degrade to storing intent + the live status (today's behavior). Toggle-OFF only stores intent (never revokes).
    cap = capability_name(method_key)
    _country, capabilities = _fetch_account(stripe_caller, platform_key_loader, mode, acct)
    status = capabilities.get(cap, "unrequested")
    requirements_due: list[str] = []
    onboarding_url = ""

    if enabled and status != "active":
        capability = _request_capability(stripe_caller, platform_key_loader, mode, acct, cap)
        if capability is not None:
            status = str(capability.get("status") or status)
            requirements_due = _requirements_due(capability)
            if requirements_due and return_url:
                onboarding_url = _account_onboarding_link(stripe_caller, platform_key_loader, mode, acct, return_url)

    bnpl = dict((keys.get("payment_methods") or {}).get("bnpl") or {})
    bnpl[method_key] = {"enabled": enabled, "capability_status": status, "updated_at": int(time.time())}
    keys.setdefault("payment_methods", {})["bnpl"] = bnpl
    _persist(keys, stripe_repo)

    result = {"method": method_key, "enabled": enabled, "capability_status": status}
    if requirements_due:
        result["requirements_due"] = requirements_due
    if onboarding_url:
        result["onboarding_url"] = onboarding_url
    return json_response(result)


def _request_capability(stripe_caller, platform_key_loader, mode, acct, cap):
    """Request `cap` on the connected account with the platform key; returns the Capability object (status +
    requirements) or None if Stripe rejects it — test mode ('only live keys'), an un-requestable method, or any
    error. None means the caller keeps the status it already read (graceful degrade, no crash)."""
    if not cap:
        return None
    try:
        return stripe_caller("POST", f"/accounts/{acct}/capabilities/{cap}",
                             api_key=platform_key_loader(mode), data={"requested": "true"})
    except StripeApiError:
        return None


def _requirements_due(capability):
    """Requirement fields Stripe still needs before the capability activates (currently + past due), deduped."""
    reqs = capability.get("requirements") or {}
    return sorted(set((reqs.get("currently_due") or []) + (reqs.get("past_due") or [])))


def _account_onboarding_link(stripe_caller, platform_key_loader, mode, acct, return_url):
    """Best-effort hosted Account Link so the tenant finishes leftover requirements in one flow instead of
    hunting through their Stripe dashboard. May not apply to OAuth Standard accounts → returns '' and the UI
    falls back to a plain message."""
    try:
        link = stripe_caller("POST", "/account_links", api_key=platform_key_loader(mode), data={
            "account": acct, "refresh_url": return_url, "return_url": return_url, "type": "account_onboarding",
        })
        return str(link.get("url") or "")
    except StripeApiError:
        return ""


def _persist(keys, stripe_repo):
    keys.setdefault("schema_version", SCHEMA_VERSION)
    keys.setdefault("document_type", "stripe_keys")
    validate_stripe_keys_document(keys)
    stripe_repo.put(keys)
