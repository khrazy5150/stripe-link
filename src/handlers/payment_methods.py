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
from stripe_link.domain.bnpl import BNPL_METHODS, capability_name, country_eligible, is_valid_method
from stripe_link.domain.documents import DocumentValidationError, validate_stripe_keys_document
from stripe_link.repositories.documents import stripe_keys_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import get_platform_secret_key

SCHEMA_VERSION = "2026-07-31"


def handler(event, context, *, stripe_repo=None, stripe_caller=None, platform_key_loader=None):
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
        return _toggle(tenant_id, _mode(body), method_key, bool(body.get("enabled")),
                       stripe_repo, stripe_caller, platform_key_loader)
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

    methods, changed = [], False
    for key, spec in BNPL_METHODS.items():
        entry = dict(stored.get(key) or {})
        # Live status wins when we could reach Stripe; else fall back to the cached value.
        status = capabilities.get(spec["capability"], entry.get("capability_status") or "unrequested") if acct \
            else (entry.get("capability_status") or "unrequested")
        if acct and capabilities and entry.get("capability_status") != status:
            entry["capability_status"] = status                 # refresh the cache
            stored[key] = entry
            changed = True
        methods.append({
            "method": key,
            "label": spec["label"],
            "enabled": bool(entry.get("enabled")),
            "capability_status": status,
            # No account country yet → don't claim ineligible (show enabled; Stripe is the final gate).
            "country_eligible": country_eligible(key, account_country) if account_country else True,
            "countries": sorted(spec["countries"]),
        })

    if changed:
        keys.setdefault("payment_methods", {})["bnpl"] = stored
        _persist(keys, stripe_repo)
    return json_response({"mode": mode, "connected": bool(acct), "account_country": account_country, "methods": methods})


def _toggle(tenant_id, mode, method_key, enabled, stripe_repo, stripe_caller, platform_key_loader):
    keys = stripe_repo.get(tenant_id, mode=mode)
    acct = str((keys or {}).get("connect_account_id") or "").strip()
    if not keys or not acct:
        return error_response("Connect a Stripe account before enabling installment methods.",
                              code="stripe_not_connected")
    cap = capability_name(method_key)
    try:
        account = stripe_caller("POST", f"/accounts/{acct}", api_key=platform_key_loader(mode),
                                data={"capabilities": {cap: {"requested": enabled}}})
    except StripeApiError as exc:
        return error_response(f"Stripe could not update the {method_key} capability: {exc.message}",
                              code="capability_error")
    status = (account.get("capabilities") or {}).get(cap, "pending" if enabled else "unrequested")

    bnpl = dict((keys.get("payment_methods") or {}).get("bnpl") or {})
    bnpl[method_key] = {"enabled": enabled, "capability_status": status, "updated_at": int(time.time())}
    keys.setdefault("payment_methods", {})["bnpl"] = bnpl
    _persist(keys, stripe_repo)
    return json_response({"method": method_key, "enabled": enabled, "capability_status": status})


def _persist(keys, stripe_repo):
    keys.setdefault("schema_version", SCHEMA_VERSION)
    keys.setdefault("document_type", "stripe_keys")
    validate_stripe_keys_document(keys)
    stripe_repo.put(keys)
