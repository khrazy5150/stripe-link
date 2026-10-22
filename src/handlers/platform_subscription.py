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
    "monthly_amount", "trial_days", "highlight", "features", "sort_order", "retired", "free",
)


def _default_return_url() -> str:
    # Deploy-set per stage (template Globals, derived from DashboardCustomDomainName). No hardcoded URL fallback.
    return os.environ.get("PLATFORM_BILLING_RETURN_URL", "").rstrip("/")


# What an allowance is CALLED to a buyer. The stored keys are ours; these are the words on the card.
# A capability with no entry here is not shown -- an allowance named `ai_videos` on a plan sold before
# AI video exists would be advertising something nobody can use.
_ALLOWANCE_LABELS = (
    ("ai_generations", "AI-written pages a month"),
    ("ai_images", "AI images a month"),
)


# What the FREE tier offers, as copy. Data on the CONFIG row (`free_plan_features`) with this as the
# fallback, so the words can be edited from the Pricing screen without a deploy.
#
# A/B Testing is deliberately NOT here. `FREE_TIER_CAPABILITIES` is {landing_pages, sites, collections}
# and `ab_testing` is premium with its own menu view -- a free tenant who clicked it after reading this
# card would hit a wall, which is a worse outcome than not advertising it.
DEFAULT_FREE_FEATURES = (
    "Unlimited landing pages",
    "Sales funnels",
    "Sandbox mode",
    "Coupons",
    "Tips",
)


def _free_plan(mode: str, plans_repository) -> dict[str, Any]:
    """The free tier, as a card. It is not a plan row -- free is the ABSENCE of a subscription -- so it
    is synthesised, and its AI line is DERIVED from the same config the gate spends from.

    Derived rather than written, because a number typed into marketing copy drifts from the number the
    generator enforces, and the tenant finds out at the moment they are refused.
    """
    from stripe_link.domain.platform_billing import (cached_platform_billing, trial_ai_generations,
                                                     trial_ai_images)

    config = cached_platform_billing(mode, plans_repository)["config"]
    features = [str(f) for f in (config.get("free_plan_features") or DEFAULT_FREE_FEATURES) if f]
    try:
        days = int(os.environ.get("TRIAL_PERIOD_DAYS", "14"))
    except (TypeError, ValueError):
        days = 14
    pages = trial_ai_generations(mode, plans_repository)
    images = trial_ai_images(mode, plans_repository)
    if pages or images:
        granted = " and ".join(bit for bit in (
            f"{pages:,} AI-written pages" if pages else "",
            f"{images:,} AI images" if images else "") if bit)
        features.append(f"First {days} days only: {granted}")
    return {"plan_key": "", "label": "Free", "monthly_amount": 0, "features": features,
            "sort_order": 0, "free": True}


def _plan_highlights(plan: dict[str, Any]) -> list[str]:
    """What this plan GIVES you, derived rather than typed into `features` by hand.

    Two plans showing nothing but a price are indistinguishable, which is how a $29 tier reads as a
    more expensive $19 tier. The numbers are already on the row; the card just has to say them, and
    deriving them means the card cannot drift from what the plan actually grants.
    """
    out: list[str] = []
    for key, label in _ALLOWANCE_LABELS:
        try:
            count = int(plan.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out.append(f"{count:,} {label}")
    return out


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    public = {key: plan[key] for key in _PUBLIC_PLAN_FIELDS if key in plan}
    # Hand-written `features` win: an admin who wrote their own copy meant it.
    if not public.get("features"):
        derived = _plan_highlights(plan)
        if derived:
            public["features"] = derived
    return public


def _safe_put(repository, document) -> None:
    try:
        repository.put(document)
    except RepositoryError:
        # Best-effort optimistic write; the webhook is the source of truth for status/subscription id.
        pass


def _create_price(event, plans_repository, mode, opener, secret_key):
    """Create a Stripe Product (if needed) and a recurring Price. CREATE ONLY -- never modify.

    A Stripe Price is IMMUTABLE: its amount cannot be edited. So "change the price" is always "make a
    new Price and decide what happens to everyone on the old one", and this function deliberately does
    only the first half. It never touches an existing price, never archives one, and never migrates a
    subscriber -- those are decisions, and a button that quietly made them would be worse than no
    button.

    The PRODUCT is reused when the plan already has one, so a ladder of price changes stays one product
    with a history rather than a pile of near-identical products.
    """
    plan_key = str(event.get("plan_key") or "").strip()
    amount = int(event.get("monthly_amount") or 0)
    if not plan_key or amount <= 0:
        return {"ok": False, "error": "plan_key and a positive monthly_amount are required."}

    key = secret_key or get_platform_secret_key(mode)
    if not key:
        return {"ok": False, "error": f"No platform Stripe key for mode '{mode}'."}

    plan = platform_plan(mode, plan_key, plans_repository) or {}
    product_id = str(event.get("product_id") or plan.get("product_id") or "").strip()
    label = str(event.get("label") or plan.get("label") or plan_key.replace("_", " ").title())
    currency = str(event.get("currency") or "usd").lower()

    try:
        if not product_id:
            product = stripe_request(
                "POST", "/products", api_key=key, opener=opener,
                data={"name": label, "metadata": {"plan_key": plan_key, "source": "junior_bay_admin"}},
                # Keyed on the PLAN, not on the attempt: a double-click must not mint two products.
                idempotency_key=f"jb-product-{mode}-{plan_key}")
            product_id = str(product.get("id") or "")
        price = stripe_request(
            "POST", "/prices", api_key=key, opener=opener,
            data={"product": product_id, "unit_amount": amount, "currency": currency,
                  "recurring": {"interval": "month"},
                  "metadata": {"plan_key": plan_key, "source": "junior_bay_admin"}},
            # Keyed on the AMOUNT too, so re-pressing the button for the same price is a no-op while
            # a genuinely new amount still mints a new Price.
            idempotency_key=f"jb-price-{mode}-{plan_key}-{amount}-{currency}")
    except StripeApiError as exc:
        return {"ok": False, "error": f"Stripe refused: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Stripe could not be reached: {exc}"}

    return {"ok": True, "mode": mode, "plan_key": plan_key, "product_id": product_id,
            "price_id": str(price.get("id") or ""), "monthly_amount": amount, "currency": currency}


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
    # THE INTERNAL PATH: the Admin Site asking us to mint a Stripe Price for a plan it is editing.
    # It lives here rather than in the admin stack so the platform secret key stays in ONE service.
    # Copying a key that can create charges into a second place, to save one Lambda invoke, is a bad
    # trade however convenient.
    if (event or {}).get("internal_create_price"):
        return _create_price(event, plans_repository, platform_billing_mode(), opener, secret_key)

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
    if method == "POST" and path.endswith("/cancel"):
        return _set_cancellation(event, tenant_repository, mode, opener, secret_key, cancel=True)
    if method == "POST" and path.endswith("/resume"):
        return _set_cancellation(event, tenant_repository, mode, opener, secret_key, cancel=False)
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
    # THE PLAN YOU ARE ON IS ALWAYS SHOWN, even once it is retired. Retiring a plan hides it from
    # people who have not bought it; it does not end anybody's subscription, and Stripe keeps billing
    # the Price regardless. But showing only the plans a tenant could switch TO leaves a paying
    # subscriber looking at a screen where nothing is marked Current -- which reads as "you are not
    # subscribed" to the one person who definitely is.
    current_key = str(tenant.get("billing_plan_key") or "").strip()
    if current_key and not any(str(p.get("plan_key")) == current_key for p in plans):
        retired = platform_plan(mode, current_key, plans_repository)
        if retired:
            # Marked so the screen can say it plainly rather than leaving someone to wonder why their
            # plan is not on the list any more.
            plans = plans + [{**retired, "retired": True}]
    cards = [_public_plan(p) for p in plans]
    # EACH PAID TIER INHERITS THE ONE BELOW IT, said out loud. Without it every card repeats the whole
    # list or, worse, looks like it REPLACES what the cheaper one offered.
    previous = "Free"
    for card in cards:
        if not card.get("retired"):
            card["features"] = [f"Everything in {previous}, plus"] + list(card.get("features") or [])
            previous = card.get("label") or previous
    cards.insert(0, _free_plan(mode, plans_repository))

    # The promo box is shown only when a promo could possibly work. There are none in production, so
    # it was asking every tenant for a code that could not exist.
    try:
        promos = bool(plans_repository and getattr(plans_repository, "list_promos", None)
                      and plans_repository.list_promos(mode))
    except Exception:  # noqa: BLE001 - a promo listing that fails must not take the screen down
        promos = False

    return json_response({
        "platform_billing": {
            "mode": mode,
            "promos_available": promos,
            "plans": cards,
            "current": {
                "billing_status": tenant.get("billing_status") or "trial",
                "billing_plan_key": tenant.get("billing_plan_key") or "",
                "billing_exempt": bool(tenant.get("billing_exempt")),
                "current_period_end": tenant.get("current_period_end"),
                "trial_ends_at": tenant.get("trial_ends_at"),
                "has_subscription": bool(tenant.get("stripe_subscription_id")),
                "entitlements": sorted(tenant_entitlement_set(tenant)),
                # The tenant's live transaction-fee tier ("free" / "basic" $19 / "pro" $29) so the price-form
                # preview shows the rates this tenant actually pays.
                "tier_id": normalize_tier_id(tenant.get("tier_id")),
                # Pending in-app cancellation: premium runs to current_period_end, then Free.
                "cancel_at_period_end": bool(tenant.get("cancel_at_period_end")),
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


def _set_cancellation(event, tenant_repository, mode, opener, secret_key, *, cancel: bool):
    """In-app cancel (and resume) — no Stripe portal round-trip. Cancel sets cancel_at_period_end on the Stripe
    subscription: premium (features + pro fee) runs to the paid-through date, then the subscription.deleted
    webhook downgrades the tenant to the free tier (free-forever model, plans/TODO.md). Resume unsets it."""
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
    subscription_id = str(tenant.get("stripe_subscription_id") or "").strip()
    if not subscription_id:
        return error_response("No active subscription for this tenant.", status_code=409, code="no_subscription")

    key = secret_key or get_platform_secret_key(mode)
    if not key:
        return error_response("Platform Stripe secret is not configured.", status_code=503, code="platform_not_configured")
    try:
        subscription = stripe_request(
            "POST", f"/subscriptions/{subscription_id}", api_key=key, opener=opener,
            data={"cancel_at_period_end": "true" if cancel else "false"},
        )
    except StripeApiError as exc:
        return error_response(f"Stripe error: {exc}", status_code=502, code="stripe_error")

    # Reflect immediately (the subscription.updated webhook will confirm) so the Billing screen updates on reload.
    updates = {"cancel_at_period_end": bool(subscription.get("cancel_at_period_end"))}
    if isinstance(subscription.get("current_period_end"), int):
        updates["current_period_end"] = subscription["current_period_end"]
    _safe_put(tenant_repository, {**tenant, **updates})
    return json_response({"platform_billing": {
        "cancel_at_period_end": updates["cancel_at_period_end"],
        "current_period_end": updates.get("current_period_end") or tenant.get("current_period_end"),
    }})


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
