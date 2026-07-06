"""Refund execution for approved refund requests.

POST /refunds/{refund_request_id}/approve  -> status new/manual_review -> approved
POST /refunds/{refund_request_id}/reject   -> status -> rejected (resolved)
POST /refunds/{refund_request_id}/execute  -> issue the Stripe refund (approved only)

The refund is issued on the tenant's connected account by PaymentIntent; the platform
application fee is NOT reversed (legacy behavior). Idempotent on refund_request_id.
"""

import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    orders_repository,
    refund_requests_repository,
    stripe_keys_repository,
)
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

ACTIONS = {"approve", "reject", "execute"}


def _action(event) -> str:
    resource = str((event or {}).get("resource") or "")
    tail = resource.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail in ACTIONS else ""


def handler(
    event,
    context,
    *,
    requests_repo=None,
    orders_repo=None,
    stripe_repo=None,
    secret_cipher=None,
    caller=stripe_request,
    credentials_fn=checkout_credentials,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    action = _action(event)
    if not action:
        return error_response("Unsupported refund action.", status_code=404, code="unknown_action")
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    refund_request_id = str(path_params(event).get("refund_request_id") or "").strip()
    if not refund_request_id:
        return error_response("refund_request_id is required.", code="missing_request")

    requests_repo = requests_repo or refund_requests_repository()
    now = int(now_fn())
    try:
        request = requests_repo.get(tenant_id, refund_request_id)
        if not request:
            return error_response("Refund request not found.", status_code=404, code="not_found")

        if action == "approve":
            return _set_status(requests_repo, request, "approved", parse_json_body(event), now)
        if action == "reject":
            return _set_status(requests_repo, request, "rejected", parse_json_body(event), now, resolved=True)
        return _execute(
            request, tenant_id, now,
            requests_repo=requests_repo,
            orders_repo=orders_repo or orders_repository(),
            stripe_repo=stripe_repo or stripe_keys_repository(),
            secret_cipher=secret_cipher if secret_cipher is not None else KmsSecretCipher(),
            caller=caller,
            credentials_fn=credentials_fn,
        )
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")


def _set_status(repo, request, status, body, now, resolved=False):
    request["status"] = status
    reason = str((body or {}).get("reason") or "").strip()
    if reason:
        request["decision_reason"] = reason
    request["updated_at"] = now
    if resolved:
        request["resolved_at"] = now
    return json_response({"refund_request": repo.put(request)})


def _execute(request, tenant_id, now, *, requests_repo, orders_repo, stripe_repo, secret_cipher, caller, credentials_fn):
    if request.get("refund", {}).get("stripe_refund_id"):
        return json_response({"refund_request": request, "refund": {"status": "already_refunded"}})
    if request.get("status") != "approved":
        return error_response("Only approved refund requests can be executed.", code="not_approved")

    order = orders_repo.get(tenant_id, str(request.get("order_id") or ""))
    if not order:
        return error_response("Order for this refund request was not found.", status_code=404, code="order_not_found")
    payment_intent = str(order.get("payment_intent_id") or "").strip()
    if not payment_intent:
        return error_response("Order has no payment intent to refund.", code="no_payment_intent")

    mode = str(order.get("mode") or "test")
    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    api_key, stripe_account = credentials_fn(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return error_response(f"No Stripe key configured for {mode} mode.", code="stripe_not_configured")

    order_amount = int(order.get("amount_total") or 0)
    requested = int((request.get("amount") or {}).get("requested_amount") or 0)
    partial_amount = requested if 0 < requested < order_amount else 0  # 0 => full refund

    data = {
        "payment_intent": payment_intent,
        "reason": "requested_by_customer",
        "metadata": {"refund_request_id": request.get("refund_request_id", ""), "order_id": order.get("order_id", "")},
    }
    if partial_amount:
        data["amount"] = partial_amount

    try:
        refund = caller(
            "POST", "/refunds",
            api_key=api_key, stripe_account=stripe_account, data=data,
            idempotency_key=f"refund_{request.get('refund_request_id', '')}",
        )
    except StripeApiError as exc:
        return error_response(exc.message, status_code=502, code="stripe_error")

    refunded_amount = int(refund.get("amount") or partial_amount or order_amount)
    currency = str(order.get("currency") or "usd")
    refund_block = {
        "stripe_refund_id": refund.get("id", ""),
        "amount": refunded_amount,
        "currency": currency,
        "refunded_at": now,
    }

    request["status"] = "refunded"
    request["refund"] = refund_block
    request["resolved_at"] = now
    request["updated_at"] = now
    requests_repo.put(request)

    order["refund"] = {"stripe_refund_id": refund.get("id", ""), "amount": refunded_amount, "refunded_at": now}
    order["refunded_at"] = now
    order["status"] = "refunded" if refunded_amount >= order_amount else "partially_refunded"
    order["updated_at"] = now
    orders_repo.put(order)

    return json_response({
        "refund_request": request,
        "refund": {"status": "refunded", "stripe_refund_id": refund.get("id", ""), "amount": refunded_amount},
    })
