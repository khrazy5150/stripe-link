import json
import logging
from base64 import b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain.bnpl import checkout_payment_method_types
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.opportunities import STAGE_CHECKOUT, STAGE_POST_PURCHASE, stage_opportunities
from stripe_link.domain.pricing import (
    PricingError,
    find_price,
    load_offer_products,
    load_offer_services,
    resolve_offer,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.runtime.error_pages import render_error_page
from stripe_link.repositories.documents import (
    offers_repository,
    pages_repository,
    products_repository,
    services_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials


STRIPE_CHECKOUT_SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"

# Presentment currencies where we re-add Link to an explicit payment_method_types list (Link's established
# markets). Outside these we omit it to avoid a guaranteed retry; the fallback ladder also drops Link if an
# account lacks it. Link supports more over time — widen as needed.
LINK_CURRENCIES = {"usd", "eur", "gbp", "cad", "aud", "nzd"}


def handler(
    event,
    context,
    *,
    offers_repo=None,
    products_repo=None,
    services_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    pages_repo=None,
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

        # A checkout initiated from a page may only transact when that page is published. The preview render
        # already shows a "DRAFT" screen instead of a working CTA, but this is the authoritative server-side
        # guard: a draft/unknown page_id cannot start a real transaction even if the API is called directly.
        if page_id:
            pages_repo = pages_repo or pages_repository()
            page = pages_repo.get(tenant_id, page_id)
            if not page or page.get("status") != "published":
                # GET /checkout is the CTA's own href — a browser lands here directly — so serve the branded
                # error page rather than raw JSON. (POST is the fetch/API path and keeps the JSON error.)
                if method == "GET":
                    return {
                        "statusCode": 403,
                        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                        "body": render_error_page(
                            403, "This page has not been published yet. Transactions are only available on "
                            "published pages — publish it from the dashboard first.",
                            title="Not published", badge="Draft",
                        ),
                    }
                return error_response(
                    "This page is not published. Transactions are only available on published pages.",
                    status_code=403, code="page_not_published",
                )

        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        # Pre-purchase order bumps (offer.funnel.order_bumps) may reference products the offer's items don't
        # include — load them so build_checkout_payload can emit their synced price as an optional_item.
        for bump in stage_opportunities(offer, STAGE_CHECKOUT):
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
        # Direct-charge (Connect) tenants can offer their enabled BNPL methods; legacy own-key tenants keep their
        # own Stripe account's payment-method settings untouched (plans/BNPL_PAYMENT_METHODS.md).
        bnpl_types = checkout_payment_method_types(
            (stripe_keys.get("payment_methods") or {}).get("bnpl"), resolved.get("currency"),
        ) if stripe_account else []
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
            bnpl_payment_method_types=bnpl_types,
        )
        stripe_response = create_checkout_session_with_bnpl_fallback(
            checkout_payload,
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
            had_bnpl=bool(bnpl_types),
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
    for bump in stage_opportunities(offer, STAGE_CHECKOUT):
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
    bnpl_payment_method_types=None,
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
    # The bumps' STRIPE price ids offered, so fulfillment can flag which completed line items were bumps
    # (what was actually purchased comes from the session's line_items). plans/SALES_FUNNELS.md P2.
    payload["metadata[order_bump_ids]"] = ",".join(stripe_price_id for stripe_price_id, _price_id in order_bumps)
    payload["metadata[post_checkout_entry]"] = "thank_you"

    # One-click post-purchase upsells charge OFF-SESSION against the buyer's saved card, so when this offer has
    # a post-purchase opportunity the checkout must create a customer and save the payment method for reuse
    # (otherwise the upsell page has no customer to charge). Subscription mode already creates a customer +
    # saves the PM; only payment mode needs these flags (plans/OFFER_MODEL_REDESIGN.md §6).
    if payload.get("mode") == "payment" and stage_opportunities(offer, STAGE_POST_PURCHASE):
        payload["customer_creation"] = "always"
        # Save the PM for the one-click upsell, but SCOPE it to card/link. A top-level
        # payment_intent_data[setup_future_usage] is REJECTED by BNPL methods (Klarna/Afterpay/Zip) —
        # "setup_future_usage is unsupported for payment method afterpay_clearpay" — which 400s the whole
        # Checkout Session whenever we also offer installments, silently dropping every method to the account
        # defaults. Per-method options keep card/link reusable while letting BNPL coexist; BNPL buyers simply
        # aren't eligible for the one-click upsell (they can't be charged off-session anyway).
        payload["payment_method_options[card][setup_future_usage]"] = "off_session"
        payload["payment_method_options[link][setup_future_usage]"] = "off_session"

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

    # BNPL / installment methods the tenant enabled + that are capability-active + currency-eligible for this
    # session (plans/BNPL_PAYMENT_METHODS.md). Setting payment_method_types is explicit, so we must include card;
    # only override when there's at least one BNPL method to add, and only for one-time payment mode with NO
    # recurring line (BNPL doesn't do recurring — guard on both the mode AND any recurring price_data line).
    # Otherwise leave payment methods to the account's Stripe defaults, as before.
    has_recurring = any("[recurring]" in key for key in payload)
    if bnpl_payment_method_types and payload.get("mode") == "payment" and not has_recurring:
        # An explicit payment_method_types list SUPPRESSES Link (Stripe shows Link only when 'link' is listed);
        # without a list Link rides in via the account defaults. Since we only set an explicit list to add BNPL,
        # re-add 'link' here so enabling installments doesn't quietly drop Link (the fallback below removes it if
        # the account has no Link). Card first, then Link, then the BNPL methods.
        currency = str((resolved or {}).get("currency") or "").lower()
        lead = ["card"] + (["link"] if currency in LINK_CURRENCIES else [])
        types = lead + [t for t in bnpl_payment_method_types if t and t not in lead]
        for index, pmt in enumerate(types):
            payload[f"payment_method_types[{index}]"] = pmt
    return payload


def create_checkout_session_with_bnpl_fallback(payload, *, api_key, stripe_account="", opener=None, had_bnpl=False):
    """Create the Checkout Session with a retry ladder for the explicit payment_method_types list (card + Link +
    the tenant's BNPL). On failure we degrade in the order that keeps the most, so an edge account never crashes
    checkout and rarely loses more than necessary (plans/BNPL_PAYMENT_METHODS.md):
      1) drop 'link' — the account may not have Link enabled; keeps BNPL + platform control;
      2) drop the whole explicit list → the account's default methods (a BNPL method went ineligible at charge
         time, e.g. the merchant turned it off in their own dashboard, or a per-transaction Stripe rule)."""
    try:
        return create_stripe_checkout_session(payload, api_key=api_key, stripe_account=stripe_account, opener=opener)
    except Exception as original:
        # A retry here means an explicit method (a BNPL method that went ineligible, or Link) was rejected;
        # log it so a silent drop-to-defaults is visible in the checkout logs.
        logger.warning("checkout: retrying without some payment methods after error: %s", original)
        ladder = []
        without_link = _payload_without_payment_method_type(payload, "link")
        if without_link is not None:
            ladder.append(without_link)
        if had_bnpl:
            ladder.append({key: value for key, value in payload.items() if not key.startswith("payment_method_types[")})
        if not ladder:
            raise
        last_exc = original
        for attempt in ladder:
            try:
                return create_stripe_checkout_session(attempt, api_key=api_key, stripe_account=stripe_account, opener=opener)
            except Exception as exc:  # noqa: BLE001 - try the next rung; re-raise the last if all fail
                last_exc = exc
        raise last_exc


def _payload_without_payment_method_type(payload, drop):
    """A copy of `payload` with `drop` removed from the payment_method_types[i] list and the survivors re-indexed;
    None if `drop` isn't present (so the caller can skip that retry rung)."""
    def _index(key):
        return int(key[len("payment_method_types["):-1])
    keys = sorted((k for k in payload if k.startswith("payment_method_types[")), key=_index)
    values = [payload[k] for k in keys]
    if drop not in values:
        return None
    out = {k: v for k, v in payload.items() if not k.startswith("payment_method_types[")}
    for index, value in enumerate(v for v in values if v != drop):
        out[f"payment_method_types[{index}]"] = value
    return out


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
