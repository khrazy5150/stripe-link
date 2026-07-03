from base64 import b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.pricing import (
    PricingError,
    find_price,
    load_offer_products,
    merge_resolved_offers,
    resolve_offer,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    offers_repository,
    products_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials


STRIPE_CHECKOUT_SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"


def handler(
    event,
    context,
    *,
    offers_repo=None,
    products_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"GET", "POST"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    params = query_params(event)
    tenant_id = tenant_id_from_event(event) or str(params.get("clientID") or "").strip()
    offer_id = str(params.get("offer") or params.get("offer_id") or "").strip()
    product_id = str(params.get("product_id") or "").strip()
    price_id = str(params.get("price_id") or "").strip()
    page_id = str(params.get("page_id") or "").strip()
    success_url = str(params.get("success_url") or "").strip()
    cancel_url = str(params.get("cancel_url") or "").strip()
    order_bump_offer_ids = [
        bump_id.strip() for bump_id in str(params.get("order_bump_ids") or "").split(",") if bump_id.strip()
    ]

    if not tenant_id:
        return error_response("clientID or tenant_id is required.", code="missing_tenant")
    if not offer_id:
        return error_response("offer is required.", code="missing_offer")
    if not success_url or not cancel_url:
        return error_response("success_url and cancel_url are required.", code="missing_redirect_url")

    offers_repo = offers_repo or offers_repository()
    products_repo = products_repo or products_repository()
    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen

    try:
        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        selected_prices = {product_id: price_id} if product_id and price_id else {}
        resolved = resolve_offer(offer, products_by_id, selected_prices)

        resolved, products_by_id = resolve_order_bumps(
            tenant_id=tenant_id,
            resolved=resolved,
            products_by_id=products_by_id,
            order_bump_offer_ids=order_bump_offer_ids,
            offers_repo=offers_repo,
            products_repo=products_repo,
        )
        mode = "live" if offer.get("stripe_mode") == "live" else "test"
        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
        api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
        if not api_key:
            return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

        fee_context = build_fee_context(
            tenant_id=tenant_id,
            offer=offer,
            products_by_id=products_by_id,
            resolved=resolved,
            tenant_repo=tenant_repo,
            billing_config_loader=billing_config_loader,
        )
        checkout_payload = build_checkout_payload(
            tenant_id=tenant_id,
            offer=offer,
            products_by_id=products_by_id,
            resolved=resolved,
            success_url=success_url,
            cancel_url=cancel_url,
            page_id=page_id,
            fee_context=fee_context,
            apply_application_fee=bool(stripe_account),
            order_bump_offer_ids=order_bump_offer_ids,
        )
        stripe_response = create_stripe_checkout_session(
            checkout_payload,
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
        )
        checkout_url = stripe_response.get("url")
        if not checkout_url:
            return error_response("Stripe did not return a checkout URL.", status_code=502, code="checkout_error")
        return redirect_response(checkout_url)
    except PricingError as exc:
        return error_response(str(exc), code="checkout_error")
    except Exception as exc:
        return error_response(str(exc), status_code=500, code="checkout_error")


def resolve_order_bumps(*, tenant_id, resolved, products_by_id, order_bump_offer_ids, offers_repo, products_repo):
    """Fold optional order-bump offers into the same checkout session as extra line items.

    Each order-bump offer_id references a distinct Offer document (context/price-context
    "order_bump"), resolved the same way as any other offer so its own active/eligibility
    checks apply. Unlike a one-click upsell, order bumps join the *initial* checkout session
    rather than triggering a separate follow-up charge.
    """
    if not order_bump_offer_ids:
        return resolved, products_by_id

    merged_products_by_id = dict(products_by_id)
    resolved_bumps = []
    for bump_offer_id in order_bump_offer_ids:
        bump_offer = offers_repo.get(tenant_id, bump_offer_id)
        if not bump_offer:
            raise PricingError(f"Order bump offer '{bump_offer_id}' was not found.")
        bump_products_by_id = load_offer_products(tenant_id, bump_offer, products_repo)
        bump_resolved = resolve_offer(bump_offer, bump_products_by_id)
        resolved_bumps.append(bump_resolved)
        merged_products_by_id.update(bump_products_by_id)

    return merge_resolved_offers(resolved, resolved_bumps), merged_products_by_id


def build_checkout_payload(
    *,
    tenant_id,
    offer,
    products_by_id,
    resolved,
    success_url,
    cancel_url,
    page_id="",
    fee_context=None,
    apply_application_fee=False,
    order_bump_offer_ids=None,
):
    checkout = offer.get("checkout") or {}
    mode = checkout.get("mode") or "payment"
    payload = {
        "mode": "subscription" if mode == "subscription" else "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "billing_address_collection": "required",
        "metadata[tenant_id]": tenant_id,
        "metadata[offer_id]": offer.get("offer_id") or "",
    }
    if checkout.get("allow_promotion_codes") is True:
        payload["allow_promotion_codes"] = "true"

    collect_shipping = False
    first_product_id = ""
    first_price_id = ""
    first_product_name = ""
    for index, item in enumerate(resolved.get("items") or []):
        product = products_by_id.get(item.get("product_id")) or {}
        price = find_price(product, item.get("price_id") or "")
        if index == 0:
            first_product_id = item.get("product_id") or ""
            first_price_id = item.get("price_id") or ""
            first_product_name = product.get("name") or item.get("product_name") or "Product"
        prefix = f"line_items[{index}]"
        stripe_price_id = price.get("stripe_price_id")
        if stripe_price_id:
            payload[f"{prefix}[price]"] = stripe_price_id
        else:
            payload[f"{prefix}[price_data][currency]"] = item.get("currency") or "usd"
            payload[f"{prefix}[price_data][unit_amount]"] = str(int(item.get("unit_amount") or 0))
            payload[f"{prefix}[price_data][product_data][name]"] = product.get("name") or item.get("product_name") or "Product"
            if product.get("description"):
                payload[f"{prefix}[price_data][product_data][description]"] = product.get("description")
            recurring = price.get("recurring") or {}
            if recurring:
                payload[f"{prefix}[price_data][recurring][interval]"] = recurring.get("interval") or "month"
                payload[f"{prefix}[price_data][recurring][interval_count]"] = str(int(recurring.get("interval_count") or 1))
        payload[f"{prefix}[quantity]"] = str(int(item.get("quantity") or 1))
        collect_shipping = collect_shipping or product.get("product_type") == "physical"

    if collect_shipping and payload["mode"] == "payment":
        payload["shipping_address_collection[allowed_countries][0]"] = "US"
        payload["shipping_address_collection[allowed_countries][1]"] = "CA"
    payload["metadata[clientID]"] = tenant_id
    payload["metadata[client_id]"] = tenant_id
    payload["metadata[product_id]"] = first_product_id
    payload["metadata[price_id]"] = first_price_id
    payload["metadata[product_name]"] = first_product_name
    payload["metadata[page_id]"] = str(page_id or "")
    payload["metadata[funnel_id]"] = ""
    payload["metadata[order_bump_ids]"] = ",".join(order_bump_offer_ids or [])
    payload["metadata[post_checkout_entry]"] = "thank_you"

    if fee_context:
        payload["metadata[product_type]"] = fee_context.get("product_type", "")
        payload["metadata[tenant_plan]"] = fee_context.get("tenant_plan", "")
        platform_fee = int(fee_context.get("platform_fee") or 0)
        subtotal = int(fee_context.get("subtotal") or 0)
        if apply_application_fee and platform_fee > 0 and subtotal > 0:
            if payload["mode"] == "subscription":
                percent = (platform_fee / subtotal) * 100
                payload["subscription_data[application_fee_percent]"] = f"{percent:.4f}"
            else:
                payload["payment_intent_data[application_fee_amount]"] = str(platform_fee)
    return payload


def create_stripe_checkout_session(payload, *, api_key, stripe_account="", opener=None):
    opener = opener or urlopen
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    request = Request(
        STRIPE_CHECKOUT_SESSIONS_URL,
        data=urlencode(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with opener(request, timeout=20) as response:
        import json

        return json.loads(response.read().decode("utf-8"))


def redirect_response(url):
    return {
        "statusCode": 303,
        "headers": {
            "Location": url,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
        },
        "body": "",
    }
