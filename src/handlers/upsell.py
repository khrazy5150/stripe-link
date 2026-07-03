import json
import time
from base64 import b64encode
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.pricing import PricingError, load_offer_products, resolve_offer
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    customers_repository,
    offers_repository,
    orders_repository,
    products_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials


STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_VERSION = "2024-06-20"


class StripeApiError(Exception):
    def __init__(self, status_code, message, stripe_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.stripe_code = stripe_code


class UpsellError(Exception):
    pass


def handler(
    event,
    context,
    *,
    offers_repo=None,
    products_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    orders_repo=None,
    customers_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"GET", "POST"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    stripe_repo = stripe_repo or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen

    if method == "GET":
        return get_upsell_session(event, stripe_repo=stripe_repo, secret_cipher=secret_cipher, opener=opener)

    return process_upsell(
        event,
        offers_repo=offers_repo or offers_repository(),
        products_repo=products_repo or products_repository(),
        stripe_repo=stripe_repo,
        tenant_repo=tenant_repo or tenant_profiles_repository(),
        orders_repo=orders_repo or orders_repository(),
        customers_repo=customers_repo or customers_repository(),
        secret_cipher=secret_cipher,
        opener=opener,
        billing_config_loader=billing_config_loader,
        now_fn=now_fn,
    )


def get_upsell_session(event, *, stripe_repo, secret_cipher, opener):
    params = query_params(event)
    tenant_id = tenant_id_from_event(event) or str(params.get("clientID") or "").strip()
    session_id = str(params.get("session_id") or "").strip()
    mode = "live" if str(params.get("mode") or "").strip() == "live" else "test"

    if not tenant_id:
        return error_response("clientID or tenant_id is required.", code="missing_tenant")
    if not session_id:
        return error_response("session_id is required.", code="missing_session")

    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

    try:
        session = stripe_request(
            "GET",
            f"/checkout/sessions/{session_id}",
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
            params=[
                ("expand[]", "customer"),
                ("expand[]", "payment_intent"),
                ("expand[]", "payment_intent.payment_method"),
            ],
        )
    except StripeApiError as exc:
        return error_response(exc.message, status_code=exc.status_code or 502, code="stripe_error")

    customer = session.get("customer")
    customer_id = customer.get("id") if isinstance(customer, dict) else (customer or "")
    payment_intent = session.get("payment_intent")
    payment_intent_id = payment_intent.get("id") if isinstance(payment_intent, dict) else (payment_intent or "")
    payment_method = payment_intent.get("payment_method") if isinstance(payment_intent, dict) else None
    payment_method_id = payment_method.get("id") if isinstance(payment_method, dict) else (payment_method or "")

    customer_details = session.get("customer_details") or {}
    shipping_details = session.get("shipping_details") or {}

    return json_response({
        "session": {
            "session_id": session_id,
            "customer_id": customer_id,
            "payment_intent_id": payment_intent_id,
            "payment_method_id": payment_method_id,
            "customer_email": customer_details.get("email") or session.get("customer_email") or "",
            "customer_name": customer_details.get("name") or "",
            "customer_phone": customer_details.get("phone") or "",
            "shipping_address": shipping_details.get("address"),
        }
    })


def process_upsell(
    event,
    *,
    offers_repo,
    products_repo,
    stripe_repo,
    tenant_repo,
    orders_repo,
    customers_repo,
    secret_cipher,
    opener,
    billing_config_loader,
    now_fn,
):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_json")

    tenant_id = tenant_id_from_event(event, body)
    session_id = str(body.get("session_id") or "").strip()
    offer_id = str(body.get("offer_id") or "").strip()
    product_id = str(body.get("product_id") or "").strip()
    price_id = str(body.get("price_id") or "").strip()
    customer_id = str(body.get("customer_id") or "").strip()
    sequence = int(body.get("sequence") or 1)
    mode = "live" if str(body.get("mode") or "").strip() == "live" else "test"
    customer_info = body.get("customer") if isinstance(body.get("customer"), dict) else {}

    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not session_id:
        return error_response("session_id is required.", code="missing_session")
    if not offer_id:
        return error_response("offer_id is required.", code="missing_offer")
    if not customer_id:
        return error_response("customer_id is required.", code="missing_customer")

    try:
        assert_billing_in_good_standing(tenant_repo.get(tenant_id, tenant_id))

        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        selected_prices = {product_id: price_id} if product_id and price_id else {}
        resolved = resolve_offer(offer, products_by_id, selected_prices)

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

        payment_method_id = resolve_customer_payment_method(
            customer_id,
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
        )
    except BillingStatusError as exc:
        return error_response(str(exc), status_code=402, code="tenant_billing_hold")
    except PricingError as exc:
        return error_response(str(exc), code="upsell_error")
    except UpsellError as exc:
        return error_response(str(exc), status_code=409, code="payment_method_unavailable")
    except StripeApiError as exc:
        return error_response(exc.message, status_code=exc.status_code or 502, code="stripe_error")

    subtotal = int(resolved.get("subtotal") or 0)
    currency = resolved.get("currency") or "usd"
    idempotency_key = f"upsell:{tenant_id}:{session_id}:{offer_id}:{sequence}"

    pi_params = {
        "amount": str(subtotal),
        "currency": currency,
        "customer": customer_id,
        "payment_method": payment_method_id,
        "confirmation_method": "automatic",
        "confirm": "true",
        "off_session": "true",
        "description": "One-click upsell",
        "metadata[tenant_id]": tenant_id,
        "metadata[upsell]": "true",
        "metadata[original_session_id]": session_id,
        "metadata[offer_id]": offer_id,
        "metadata[product_type]": fee_context["product_type"],
        "metadata[tenant_plan]": fee_context["tenant_plan"],
    }
    platform_fee = int(fee_context.get("platform_fee") or 0)
    if stripe_account and subtotal > 0 and platform_fee > 0:
        pi_params["application_fee_amount"] = str(platform_fee)

    try:
        payment_intent = stripe_request(
            "POST",
            "/payment_intents",
            api_key=api_key,
            stripe_account=stripe_account,
            data=pi_params,
            opener=opener,
            idempotency_key=idempotency_key,
        )
    except StripeApiError as exc:
        status_code = exc.status_code if exc.status_code and exc.status_code < 500 else 502
        code = "card_declined" if exc.stripe_code == "card_declined" else "stripe_error"
        return error_response(exc.message, status_code=status_code, code=code)

    now = int(now_fn())
    order_id = f"order_{session_id}_upsell_{sequence}"
    primary_item = (resolved.get("items") or [{}])[0]
    product = products_by_id.get(primary_item.get("product_id")) or {}
    product_name = product.get("name") or primary_item.get("product_name") or "Upsell"

    order_record = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "schema_version": "2026-05-29",
        "document_type": "order",
        "session_id": session_id,
        "line_item_type": "upsell",
        "status": "paid" if payment_intent.get("status") == "succeeded" else payment_intent.get("status", "pending"),
        "amount_total": subtotal,
        "currency": currency,
        "customer": {
            "name": customer_info.get("name", ""),
            "email": customer_info.get("email", ""),
            "phone": customer_info.get("phone", ""),
            "stripe_customer_id": customer_id,
        },
        "product": {
            "product_id": primary_item.get("product_id", ""),
            "price_id": primary_item.get("price_id", ""),
            "name": product_name,
        },
        "fees": fee_context["fees"],
        "attribution": {
            "offer_id": offer_id,
            "page_id": "",
            "funnel_id": "",
            "order_bump_ids": [],
            "post_checkout_entry": "upsell",
        },
        "metadata": {"upsell_sequence": str(sequence)},
        "created_at": str(now),
        "updated_at": now,
    }
    orders_repo.put(order_record)

    update_customer_after_upsell(
        customers_repo,
        tenant_id=tenant_id,
        customer_id=customer_id,
        amount=subtotal,
        currency=currency,
        product_name=product_name,
        order_id=order_id,
        now=now,
    )

    return json_response({
        "upsell": {
            "order_id": order_id,
            "payment_intent_id": payment_intent.get("id", ""),
            "status": payment_intent.get("status", ""),
        }
    }, status_code=201)


def resolve_customer_payment_method(customer_id, *, api_key, stripe_account, opener):
    """Only use payment methods already attached to the customer, matching legacy behavior.

    Reusing a PaymentIntent's raw payment method without customer attachment triggers a
    Stripe error, so we always resolve through the customer's own attached methods.
    """
    customer = stripe_request(
        "GET",
        f"/customers/{customer_id}",
        api_key=api_key,
        stripe_account=stripe_account,
        opener=opener,
        params=[("expand[]", "invoice_settings.default_payment_method")],
    )
    default_pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
    if isinstance(default_pm, dict) and default_pm.get("id"):
        return default_pm["id"]
    if isinstance(default_pm, str) and default_pm:
        return default_pm

    payment_methods = stripe_request(
        "GET",
        "/payment_methods",
        api_key=api_key,
        stripe_account=stripe_account,
        opener=opener,
        params=[("customer", customer_id), ("type", "card")],
    )
    data = payment_methods.get("data") or []
    if data:
        return data[0].get("id", "")
    raise UpsellError("No saved payment method is attached to this customer.")


def update_customer_after_upsell(customers_repo, *, tenant_id, customer_id, amount, currency, product_name, order_id, now):
    if not customers_repo or not customer_id:
        return None
    existing = customers_repo.get(tenant_id, customer_id)
    if not existing:
        return None

    summary = dict(existing.get("summary") or {})
    summary["total_orders"] = int(summary.get("total_orders") or 0) + 1
    summary["total_spent"] = int(summary.get("total_spent") or 0) + amount
    summary["last_purchase_at"] = now
    summary["last_product_name"] = product_name

    transaction_history = list(existing.get("transaction_history") or [])
    transaction_history.append({
        "transaction_id": order_id,
        "type": "order",
        "order_id": order_id,
        "amount": amount,
        "currency": currency,
        "created_at": now,
    })

    updated = {**existing, "summary": summary, "transaction_history": transaction_history, "updated_at": now}
    return customers_repo.put(updated)


def stripe_request(method, path, *, api_key, stripe_account="", params=None, data=None, opener=None, idempotency_key=None):
    opener = opener or urlopen
    url = f"{STRIPE_API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Stripe-Version": STRIPE_API_VERSION,
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(data).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = {}
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        error = payload.get("error") or {}
        raise StripeApiError(exc.code, error.get("message") or str(exc), error.get("code")) from exc
