import os
import time
from typing import Any, Callable

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    tenant_id_from_event,
)
from stripe_link.domain.entitlements import CAPABILITIES, tenant_entitlement_set
from stripe_link.domain.fees import normalize_tier_id
from stripe_link.domain.platform_billing import (
    active_platform_plans,
    default_platform_plan_key,
    is_tenant_billing_exempt,
    platform_billing_mode,
    platform_plan,
    platform_promo,
    promo_is_valid,
)
from stripe_link.repositories.documents import RepositoryError, tenant_profiles_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import get_platform_secret_key

# Fields safe to expose to the dashboard billing screen (never price_id/product_id/fee_tier/exempt internals).
_PUBLIC_PLAN_FIELDS = (
    "plan_key", "label", "tagline", "badge", "cta_label",
    "monthly_amount", "trial_days", "highlight", "features", "sort_order",
)


def _default_return_url() -> str:
    # Deploy-set per stage (template Globals, derived from DashboardCustomDomainName). No hardcoded URL fallback.
    return os.environ.get("PLATFORM_BILLING_RETURN_URL", "").rstrip("/")


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: plan[key] for key in _PUBLIC_PLAN_FIELDS if key in plan}


def _safe_put(repository, document) -> None:
    try:
        repository.put(document)
    except RepositoryError:
        # Best-effort optimistic write; the webhook is the source of truth for status/subscription id.
        pass


def handler(
    event,
    context,
    *,
    tenant_repository=None,
    plans_repository=None,
    opener=None,
    secret_key=None,
    now_fn: Callable[[], float] = time.time,
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    path = (event or {}).get("path", "") or ""
    tenant_repository = tenant_repository or tenant_profiles_repository()
    # The platform's OWN Stripe mode for billing tenants (test|live), distinct from a tenant's storefront mode.
    mode = platform_billing_mode()

    if method == "GET" and path.endswith("/plans"):
        return _plans(event, tenant_repository, plans_repository, mode)
    if method == "POST" and path.endswith("/subscribe"):
        return _subscribe(event, tenant_repository, plans_repository, mode, opener, secret_key)
    if method == "POST" and path.endswith("/portal"):
        return _portal(event, tenant_repository, mode, opener, secret_key)
    return error_response(f"Unsupported route '{method} {path}'.", status_code=405, code="method_not_allowed")


def _plans(event, tenant_repository, plans_repository, mode):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        tenant = tenant_repository.get(tenant_id, tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="platform_billing_error")
    plans = active_platform_plans(mode, plans_repository)
    return json_response({
        "platform_billing": {
            "mode": mode,
            "plans": [_public_plan(p) for p in plans],
            "current": {
                "billing_status": tenant.get("billing_status") or "trial",
                "billing_plan_key": tenant.get("billing_plan_key") or "",
                "billing_exempt": bool(tenant.get("billing_exempt")),
                "current_period_end": tenant.get("current_period_end"),
                "trial_ends_at": tenant.get("trial_ends_at"),
                "has_subscription": bool(tenant.get("stripe_subscription_id")),
                "entitlements": sorted(tenant_entitlement_set(tenant)),
                # The tenant's live transaction-fee tier ("basic" free / "pro" premium) so the price-form
                # preview shows the rates this tenant actually pays.
                "tier_id": normalize_tier_id(tenant.get("tier_id")),
            },
            # The full gateable-feature catalog so the dashboard can DISABLE (not hide) the ones the tenant's
            # entitlements don't include, with an upgrade hint (plans/SAAS_BILLING_PAYWALL.md).
            "capabilities": [{"key": key, "label": meta["label"], "view": meta["view"]}
                             for key, meta in CAPABILITIES.items()],
        }
    })


def _owner_email(tenant: dict[str, Any]) -> str:
    owner = tenant.get("owner") if isinstance(tenant.get("owner"), dict) else {}
    return str(tenant.get("owner_email") or owner.get("email") or "").strip()


def _ensure_customer(tenant, tenant_id, email, key, opener) -> str:
    """Reuse the tenant's platform Stripe Customer or create one. Keyed to the tenant via metadata so the webhook
    can map platform-billing events (which carry no connected account) back to the tenant."""
    existing = str(tenant.get("stripe_customer_id") or "").strip()
    if existing:
        return existing
    data: dict[str, Any] = {"metadata": {"tenant_id": tenant_id}}
    if email:
        data["email"] = email
    name = str(tenant.get("business_name") or "").strip()
    if name:
        data["name"] = name
    customer = stripe_request("POST", "/customers", api_key=key, opener=opener, data=data)
    return str(customer.get("id") or "")


def _subscribe(event, tenant_repository, plans_repository, mode, opener, secret_key):
    body = parse_json_body(event) or {}
    tenant_id = str(body.get("tenant_id") or tenant_id_from_event(event) or "").strip()
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        tenant = tenant_repository.get(tenant_id, tenant_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="platform_billing_error")
    if not tenant:
        return error_response("Tenant not found.", status_code=404, code="not_found")

    email = _owner_email(tenant)

    # Exempt (comped) tenants: mark in-good-standing and create NO Stripe subscription — Stripe never charges them.
    if tenant.get("billing_exempt") or is_tenant_billing_exempt(mode, tenant_id, email, plans_repository):
        _safe_put(tenant_repository, {**tenant, "billing_exempt": True, "billing_status": "active"})
        return json_response({"platform_billing": {"exempt": True, "billing_status": "active"}})

    # Optional special-link promotion: a free-trial override and/or a Stripe discount, validated server-side so a
    # link can't be forged. Trials are promo-only (base plan trial_days is 0), so no valid promo = no trial.
    promo = None
    promo_code = str(body.get("promo_code") or "").strip()
    if promo_code:
        promo = platform_promo(mode, promo_code, plans_repository)
        if not promo_is_valid(promo):
            return error_response("This promotion is not valid or has expired.", status_code=422, code="invalid_promo")

    plan_key = str((promo or {}).get("plan_key") or body.get("plan_key") or default_platform_plan_key(mode, plans_repository) or "").strip()
    plan = platform_plan(mode, plan_key, plans_repository)
    if not plan or not plan.get("active"):
        return error_response("Unknown or inactive plan.", code="invalid_plan")
    price_id = str(plan.get("price_id") or "").strip()
    if not price_id:
        return error_response("Plan is not configured with a Stripe price.", status_code=503, code="plan_not_configured")

    key = secret_key or get_platform_secret_key(mode)
    if not key:
        return error_response("Platform Stripe secret is not configured.", status_code=503, code="platform_not_configured")

    # A valid promo's trial_days override wins; otherwise the plan's own (normally 0). Card is collected up front —
    # Stripe Checkout subscription mode's default payment_method_collection, so a trial auto-charges at its end.
    if promo and promo.get("trial_days") is not None:
        trial_days = int(promo.get("trial_days") or 0)
    else:
        trial_days = int(plan.get("trial_days") or 0)

    subscription_data: dict[str, Any] = {"metadata": {"tenant_id": tenant_id, "plan_key": plan_key}}
    if promo:
        subscription_data["metadata"]["promo_code"] = promo["promo_code"]
    if trial_days > 0:
        subscription_data["trial_period_days"] = trial_days

    checkout_data: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "subscription_data": subscription_data,
        "metadata": {"tenant_id": tenant_id, "plan_key": plan_key},
        "success_url": str(body.get("success_url") or "").strip() or _default_return_url(),
        "cancel_url": str(body.get("cancel_url") or "").strip() or _default_return_url(),
    }
    stripe_promotion_code = str((promo or {}).get("stripe_promotion_code") or "").strip()
    if stripe_promotion_code:
        checkout_data["discounts"] = [{"promotion_code": stripe_promotion_code}]

    try:
        customer_id = _ensure_customer(tenant, tenant_id, email, key, opener)
        checkout_data["customer"] = customer_id
        session = stripe_request("POST", "/checkout/sessions", api_key=key, opener=opener, data=checkout_data)
    except StripeApiError as exc:
        return error_response(f"Stripe error: {exc}", status_code=502, code="stripe_error")

    # Record ONLY the Stripe customer id, so a retry reuses it instead of creating duplicate customers. Do NOT mark
    # the tenant as subscribed here: plan / price / entitlements / status are set by the platform-billing webhook
    # when the subscription is actually CREATED (i.e. paid/trialing). This way an abandoned Checkout never leaves a
    # tenant looking subscribed without paying.
    if customer_id and customer_id != str(tenant.get("stripe_customer_id") or ""):
        _safe_put(tenant_repository, {**tenant, "stripe_customer_id": customer_id})
    return json_response({"platform_billing": {"checkout_url": session.get("url"), "session_id": session.get("id")}})


def _portal(event, tenant_repository, mode, opener, secret_key):
    body = parse_json_body(event) or {}
    tenant_id = str(body.get("tenant_id") or tenant_id_from_event(event) or "").strip()
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        tenant = tenant_repository.get(tenant_id, tenant_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="platform_billing_error")
    if not tenant:
        return error_response("Tenant not found.", status_code=404, code="not_found")
    customer_id = str(tenant.get("stripe_customer_id") or "").strip()
    if not customer_id:
        return error_response("No billing customer for this tenant yet.", status_code=409, code="no_customer")

    key = secret_key or get_platform_secret_key(mode)
    if not key:
        return error_response("Platform Stripe secret is not configured.", status_code=503, code="platform_not_configured")

    return_url = str(body.get("return_url") or "").strip() or _default_return_url()
    try:
        session = stripe_request(
            "POST", "/billing_portal/sessions", api_key=key, opener=opener,
            data={"customer": customer_id, "return_url": return_url},
        )
    except StripeApiError as exc:
        return error_response(f"Stripe error: {exc}", status_code=502, code="stripe_error")
    return json_response({"platform_billing": {"portal_url": session.get("url")}})
