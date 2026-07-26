import json
from base64 import b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.pricing import (
    PricingError,
    find_price,
    load_offer_products,
    load_offer_services,
    resolve_offer,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    offers_repository,
    products_repository,
    services_repository,
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
    services_repo=None,
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

    if not tenant_id:
        return error_response("clientID or tenant_id is required.", code="missing_tenant")
    if not offer_id:
        return error_response("offer is required.", code="missing_offer")
    if not success_url or not cancel_url:
        return error_response("success_url and cancel_url are required.", code="missing_redirect_url")

    offers_repo = offers_repo or offers_repository()
    products_repo = products_repo or products_repository()
    if services_repo is None:
        try:
            services_repo = services_repository()
        except Exception:  # noqa: BLE001 - services table optional; only needed for service offer items
            services_repo = None
    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen

    try:
        assert_billing_in_good_standing(tenant_repo.get(tenant_id, tenant_id))

        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        # Pre-purchase order bumps (offer.funnel.order_bumps) may reference products the offer's items don't
        # include — load them so build_checkout_payload can emit their synced price as an optional_item.
        for bump in (offer.get("funnel") or {}).get("order_bumps") or []:
            bump_product_id = str(bump.get("product_id") or "")
            if bump_product_id and bump_product_id not in products_by_id:
                bump_product = products_repo.get(tenant_id, bump_product_id)
                if bump_product:
                    products_by_id[bump_product_id] = bump_product
        services_by_id = load_offer_services(tenant_id, offer, services_repo)
        selected_prices = {product_id: price_id} if product_id and price_id else {}
        resolved = resolve_offer(offer, products_by_id, selected_prices, services_by_id=services_by_id)

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
    except BillingStatusError as exc:
        return error_response(str(exc), status_code=402, code="tenant_billing_hold")
    except PricingError as exc:
        return error_response(str(exc), code="checkout_error")
    except Exception as exc:
        return error_response(str(exc), status_code=500, code="checkout_error")


def order_bump_optional_items(offer, products_by_id, key_mode):
    """The offer's pre-purchase order bumps, resolved to Stripe optional_items (opt-in "add this?" lines on
    the hosted Checkout page). Each bump references a product + one of its prices in the order_bump context;
    Stripe forbids inline price_data for optional_items, so an un-synced bump (no matching-mode
    stripe_price_id) is SKIPPED with a warning — the dashboard guard flags it before publish
    (plans/SALES_FUNNELS.md P2). Returns [(stripe_price_id, price_id)] in order.

    Order bumps are PRE-purchase: they ride the initial Checkout session, unlike the post-purchase one-click
    upsell/downsell steps.
    """
    bumps = []
    for bump in (offer.get("funnel") or {}).get("order_bumps") or []:
        product = products_by_id.get(bump.get("product_id")) or {}
        price = find_price(product, bump.get("price_id") or "")
        stripe_price_id = price.get("stripe_price_id")
        product_mode = product.get("stripe_mode")
        if not stripe_price_id or (product_mode is not None and product_mode != key_mode):
            print(f"[checkout] skipping order bump product='{bump.get('product_id')}' price='{bump.get('price_id')}' "
                  f"— not Stripe-synced for mode '{key_mode}' (optional_items require a synced price)")
            continue
        bumps.append((stripe_price_id, str(bump.get("price_id") or "")))
    return bumps


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
):
    checkout = offer.get("checkout") or {}
    mode = checkout.get("mode") or "payment"
    # The Stripe key was chosen from the offer's stripe_mode, so that IS the active key's mode. A stored
    # stripe_price_id only belongs to the account of the same mode — if a product's own stripe_mode disagrees
    # (a wrong-environment id from a bad copy or manual tinkering), we must NOT send it (it 500s at Stripe).
    key_mode = "live" if offer.get("stripe_mode") == "live" else "test"
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
    service_items = []
    for index, item in enumerate(resolved.get("items") or []):
        prefix = f"line_items[{index}]"
        if item.get("kind") == "service" or item.get("service_id"):
            # First-class service line: no product doc; price comes straight from the resolved item.
            service_items.append(item)
            payload[f"{prefix}[price_data][currency]"] = item.get("currency") or "usd"
            payload[f"{prefix}[price_data][unit_amount]"] = str(int(item.get("unit_amount") or 0))
            payload[f"{prefix}[price_data][product_data][name]"] = item.get("label") or item.get("product_name") or "Service"
            payload[f"{prefix}[quantity]"] = str(int(item.get("quantity") or 1))
            if index == 0:
                first_product_name = item.get("product_name") or "Service"
            continue
        product = products_by_id.get(item.get("product_id")) or {}
        price = find_price(product, item.get("price_id") or "")
        if index == 0:
            first_product_id = item.get("product_id") or ""
            first_price_id = item.get("price_id") or ""
            first_product_name = product.get("name") or item.get("product_name") or "Product"
        stripe_price_id = price.get("stripe_price_id")
        # Only honor the id when the product's mode matches the active key's. Absent stripe_mode = trust it
        # (legacy docs); an EXPLICIT mismatch = a wrong-env id, so ignore it and price inline instead.
        product_mode = product.get("stripe_mode")
        if stripe_price_id and product_mode is not None and product_mode != key_mode:
            print(f"[checkout] ignoring cross-mode stripe_price_id for product '{item.get('product_id')}' "
                  f"(product stripe_mode={product_mode}, active key mode={key_mode}); pricing inline instead")
            stripe_price_id = ""
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

    # Booking metadata so the webhook can fan out 1..N appointments + no_booking invoice lines
    # (STORY-2.3). service_lines carries ALL service lines; service_booking_mode coordinates grouping.
    # (Stripe caps a metadata value at 500 chars — fine for the handful of services a real offer holds.)
    if service_items:
        first = service_items[0]
        payload["metadata[service_booking_mode]"] = str(offer.get("service_booking_mode") or "single_visit")
        payload["metadata[service_lines]"] = json.dumps([
            {
                "service_id": s.get("service_id") or "",
                "price_id": s.get("price_id") or "",
                "service_name": s.get("product_name") or s.get("label") or "Service",
                "unit_amount": int(s.get("unit_amount") or 0),
                "currency": s.get("currency") or "usd",
                "quantity": int(s.get("quantity") or 1),
                "booking_flow": s.get("booking_flow") or "pay_then_book",
                "fulfillment_mode": s.get("fulfillment_mode") or "scheduled",
                "duration_minutes": int(s.get("duration_minutes") or 0),
                "default_fulfiller_id": s.get("default_fulfiller_id") or "",
            }
            for s in service_items
        ], separators=(",", ":"))
        # Routing hint for the webhook dispatch (first line).
        payload["metadata[service_id]"] = first.get("service_id") or ""
        payload["metadata[service_price_id]"] = first.get("price_id") or ""
        payload["metadata[booking_flow]"] = first.get("booking_flow") or "pay_then_book"
        payload["metadata[service_name]"] = first.get("product_name") or first.get("label") or "Service"

    if collect_shipping and payload["mode"] == "payment":
        payload["shipping_address_collection[allowed_countries][0]"] = "US"
        payload["shipping_address_collection[allowed_countries][1]"] = "CA"
    # Pre-purchase order bumps → Stripe optional_items (opt-in on the hosted page; charged in the same
    # session if the buyer adds them). plans/SALES_FUNNELS.md P2.
    order_bumps = order_bump_optional_items(offer, products_by_id, key_mode)
    for index, (stripe_price_id, _price_id) in enumerate(order_bumps):
        payload[f"optional_items[{index}][price]"] = stripe_price_id
        payload[f"optional_items[{index}][quantity]"] = "1"

    payload["metadata[clientID]"] = tenant_id
    payload["metadata[client_id]"] = tenant_id
    payload["metadata[product_id]"] = first_product_id
    payload["metadata[price_id]"] = first_price_id
    payload["metadata[product_name]"] = first_product_name
    payload["metadata[page_id]"] = str(page_id or "")
    payload["metadata[funnel_id]"] = ""
    # The bump PRICE ids offered (what was actually purchased comes from the session's line_items at fulfillment).
    payload["metadata[order_bump_ids]"] = ",".join(price_id for _sid, price_id in order_bumps)
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
