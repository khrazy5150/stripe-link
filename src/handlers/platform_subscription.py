import os
import time
from typing import Any, Callable

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    tenant_id_from_event,
)
from stripe_link.domain.platform_billing import (
    active_platform_plans,
    default_platform_plan_key,
    is_tenant_billing_exempt,
    platform_billing_mode,
    platform_plan,
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
    return os.environ.get("PLATFORM_BILLING_RETURN_URL", "https://app.juniorbay.com").rstrip("/")


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
                "has_subscription": bool(tenant.get("stripe_subscription_id")),
            },
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

    plan_key = str(body.get("plan_key") or default_platform_plan_key(mode, plans_repository) or "").strip()
    plan = platform_plan(mode, plan_key, plans_repository)
    if not plan or not plan.get("active"):
        return error_response("Unknown or inactive plan.", code="invalid_plan")
    price_id = str(plan.get("price_id") or "").strip()
    if not price_id:
        return error_response("Plan is not configured with a Stripe price.", status_code=503, code="plan_not_configured")

    key = secret_key or get_platform_secret_key(mode)
    if not key:
        return error_response("Platform Stripe secret is not configured.", status_code=503, code="platform_not_configured")

    subscription_data: dict[str, Any] = {"metadata": {"tenant_id": tenant_id, "plan_key": plan_key}}
    trial_days = int(plan.get("trial_days") or 0)
    if trial_days > 0:
        subscription_data["trial_period_days"] = trial_days

    try:
        customer_id = _ensure_customer(tenant, tenant_id, email, key, opener)
        session = stripe_request("POST", "/checkout/sessions", api_key=key, opener=opener, data={
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "subscription_data": subscription_data,
            "metadata": {"tenant_id": tenant_id, "plan_key": plan_key},
            "success_url": str(body.get("success_url") or "").strip() or _default_return_url(),
            "cancel_url": str(body.get("cancel_url") or "").strip() or _default_return_url(),
        })
    except StripeApiError as exc:
        return error_response(f"Stripe error: {exc}", status_code=502, code="stripe_error")

    # Optimistically record the plan choice + customer; the webhook confirms subscription id + status.
    _safe_put(tenant_repository, {
        **tenant,
        "stripe_customer_id": customer_id,
        "billing_plan_key": plan_key,
        "billing_price_id": price_id,
    })
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
