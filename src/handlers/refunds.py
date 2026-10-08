"""Refund execution for approved refund requests.

POST /refunds/{refund_request_id}/approve  -> status new/manual_review -> approved
POST /refunds/{refund_request_id}/reject   -> status -> rejected (resolved)
POST /refunds/{refund_request_id}/execute  -> issue the Stripe refund (approved only)
POST /refunds/{refund_request_id}/received -> the goods came back; releases the refund

**If a product requires a physical return, no refund is issued until the product is received**
(plans/ORDER_FULFILMENT.md R1). Approval of such a request lands on `return_pending` rather than
`approved`, so `approved` goes back to meaning "the claim is valid" instead of "the money is going back
now". The terms are snapshotted at approval: a tenant editing their policy must not retroactively change
a return already in flight.

The refund is issued on the tenant's connected account by PaymentIntent; the platform
application fee is NOT reversed (legacy behavior). Idempotent on refund_request_id.
"""

import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.fulfilment import product_index, resolve_order_lines
from stripe_link.domain.refund_ledger import build_refund_entry, set_refund_aggregates
from stripe_link.domain.tips import refund_amount as tip_refund_amount
from stripe_link.domain.returns import (
    RETURN_PENDING,
    RETURN_RECEIVED,
    RETURN_STATES,
    can_release_refund,
    next_status_after_approval,
    policy_snapshot,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    orders_repository,
    products_repository,
    refund_requests_repository,
    refunds_repository,
    stripe_keys_repository,
)
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

ACTIONS = {"approve", "reject", "execute", "received"}


def _action(event) -> str:
    """The action this request is asking for, from the route's `{action}` path parameter.

    It used to come from the tail of `resource`, which for `/refunds/{refund_request_id}/{action}` is the
    literal string "{action}" -- so every approve and reject answered "Unsupported refund action." for as
    long as the route has existed. The tests passed because their fixture interpolated the action into
    `resource` while leaving the id a template, a shape API Gateway cannot produce.

    The `resource` tail is still honoured, for a route that names its action in the path.
    """
    action = str(path_params(event).get("action") or "").strip().lower()
    if action in ACTIONS:
        return action
    tail = str((event or {}).get("resource") or "").rstrip("/").rsplit("/", 1)[-1]
    return tail if tail in ACTIONS else ""


def handler(
    event,
    context,
    *,
    requests_repo=None,
    orders_repo=None,
    refunds_repo=None,
    stripe_repo=None,
    secret_cipher=None,
    products_repo=None,
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
            return _approve(requests_repo, request, tenant_id, parse_json_body(event), now,
                            orders_repo=orders_repo or orders_repository(mode=resolve_stripe_mode(event)),
                            products_repo=products_repo, mode=resolve_stripe_mode(event))
        if action == "reject":
            return _set_status(requests_repo, request, "rejected", parse_json_body(event), now, resolved=True)
        if action == "received":
            return _mark_received(requests_repo, request, parse_json_body(event), now)
        return _execute(
            request, tenant_id, now,
            requests_repo=requests_repo,
            orders_repo=orders_repo or orders_repository(mode=resolve_stripe_mode(event)),
            refunds_repo=refunds_repo or refunds_repository(mode=resolve_stripe_mode(event)),
            stripe_repo=stripe_repo or stripe_keys_repository(),
            secret_cipher=secret_cipher if secret_cipher is not None else KmsSecretCipher(),
            caller=caller,
            credentials_fn=credentials_fn,
        )
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")


def _approve(repo, request, tenant_id, body, now, *, orders_repo, products_repo=None, mode="test"):
    """Approve the CLAIM, and decide whether the money waits for the goods.

    The snapshot is taken here, once, and everything downstream reads it rather than re-deriving from a
    policy that may have changed in the meantime.
    """
    products = []
    try:
        # The MODE matters here: an unmoded read used to find nothing, the snapshot concluded "no
        # return required", and every refund skipped its gate. That is why the repository now refuses it.
        repo_products = products_repo or products_repository(mode=mode)
        products = repo_products.list_for_tenant(tenant_id) or []
    except Exception:  # noqa: BLE001 - an unreadable catalogue must not block a refund decision
        products = []
    by_id = {str(p.get("product_id") or ""): p for p in products if p.get("product_id")}

    order = None
    try:
        order = orders_repo.get(tenant_id, str(request.get("order_id") or ""))
    except Exception:  # noqa: BLE001
        order = None
    lines = resolve_order_lines(order or {}, product_index(products))

    snapshot = policy_snapshot(
        lines, by_id,
        order_total=int((order or {}).get("amount_total") or request.get("amount") or 0),
        keep_it_below=_keep_it_below(by_id, lines))
    request["policy_snapshot"] = {**(request.get("policy_snapshot") or {}), **snapshot}
    status = next_status_after_approval(snapshot)
    if status == RETURN_PENDING:
        request["return_started_at"] = now
    return _set_status(repo, request, status, body, now)


def _keep_it_below(products_by_id, lines):
    """The lowest keep-it threshold among the products being returned.

    Lowest, not highest: a tenant who says "do not bother returning my $5 item" has not thereby said it
    about the $200 one in the same order.
    """
    thresholds = []
    for line in lines or []:
        policy = (products_by_id.get(str(line.get("product_id") or "")) or {}).get("refund_policy") or {}
        value = policy.get("keep_it_below")
        if isinstance(value, int) and value > 0:
            thresholds.append(value)
    return min(thresholds) if thresholds else None


def _mark_received(repo, request, body, now):
    """The tenant says the goods are back. A DECISION, not a carrier scan.

    A delivery scan says a box arrived; it does not say the right item was in it or what condition it was
    in. So this is the tenant's act, and it is where the refund can still be reduced or refused.
    """
    if str(request.get("status") or "") not in RETURN_STATES:
        return error_response("This refund request is not waiting on a return.", code="not_returning")
    note = str((body or {}).get("note") or "").strip()
    if note:
        request["return_note"] = note
    amount = (body or {}).get("amount")
    if amount is not None:
        # Decided at RECEIPT, not fixed at approval: an item back damaged, used, or not the item sent is
        # a partial refund. Restocking fees and non-refundable outbound postage land here too.
        try:
            request["amount"] = int(amount)
        except (TypeError, ValueError):
            return error_response("Refund amount must be a whole number of cents.", code="invalid_amount")
    request["return_received_at"] = now
    return _set_status(repo, request, RETURN_RECEIVED, body, now)


def _set_status(repo, request, status, body, now, resolved=False):
    request["status"] = status
    reason = str((body or {}).get("reason") or "").strip()
    if reason:
        request["decision_reason"] = reason
    request["updated_at"] = now
    if resolved:
        request["resolved_at"] = now
    return json_response({"refund_request": repo.put(request)})


def _execute(request, tenant_id, now, *, requests_repo, orders_repo, refunds_repo, stripe_repo, secret_cipher, caller, credentials_fn):
    if request.get("refund", {}).get("stripe_refund_id"):
        return json_response({"refund_request": request, "refund": {"status": "already_refunded"}})
    # THE GATE. A function of this request's own recorded state, never of the policy as it stands today:
    # a policy edited mid-return must not release a refund for goods still in the post.
    allowed, why_not, code = can_release_refund(request)
    if not allowed:
        return error_response(why_not, code=code)

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

    charged = int(order.get("amount_total") or 0)
    # A TIP refunds the tip, not the charge (plans/PAY_WHAT_YOU_WANT.md §5f). Under net_guaranteed the
    # supporter paid the fees on top, so refunding the charge would leave the creator paying back more
    # than they ever received -- out of pocket for having accepted a gift. Every other order refunds its
    # total, so this is a no-op outside tips.
    order_amount = tip_refund_amount(order)
    requested = int((request.get("amount") or {}).get("requested_amount") or 0)
    partial_amount = requested if 0 < requested < order_amount else 0  # 0 => full refund

    data = {
        "payment_intent": payment_intent,
        "reason": "requested_by_customer",
        "metadata": {"refund_request_id": request.get("refund_request_id", ""), "order_id": order.get("order_id", "")},
    }
    if partial_amount:
        data["amount"] = partial_amount
    elif order_amount and order_amount < charged:
        # A full refund of a tip is a PARTIAL refund at Stripe: it returns the tip out of a larger charge.
        data["amount"] = order_amount

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
    stripe_refund_id = str(refund.get("id") or "")
    charge_id = str(refund.get("charge") or "")

    # Append an immutable ledger row (refund_id == stripe_refund_id so the webhook dedupes on it).
    if refunds_repo and stripe_refund_id:
        try:
            refunds_repo.put(build_refund_entry(
                refund_id=stripe_refund_id,
                tenant_id=tenant_id,
                order_id=str(order.get("order_id") or ""),
                payment_intent_id=payment_intent,
                charge_id=charge_id,
                amount=refunded_amount,
                currency=currency,
                reason="requested_by_customer",
                initiated_by="admin",
                stripe_refund_id=stripe_refund_id,
                status=str(refund.get("status") or "succeeded"),
                created_at=now,
            ))
        except RepositoryError:
            pass  # refund already issued; ledger write is best-effort

    # Update order aggregates.
    total_refunded = int(order.get("amount_refunded") or 0) + refunded_amount
    updated_order = set_refund_aggregates(
        order, amount_refunded=total_refunded, refund_count=int(order.get("refund_count") or 0) + 1, at=now,
    )
    orders_repo.put(updated_order)

    request["status"] = "refunded"
    request["refund"] = {"stripe_refund_id": stripe_refund_id, "amount": refunded_amount, "currency": currency, "refunded_at": now}
    request["resolved_at"] = now
    request["updated_at"] = now
    requests_repo.put(request)

    return json_response({
        "refund_request": request,
        "refund": {
            "status": "refunded",
            "stripe_refund_id": stripe_refund_id,
            "amount": refunded_amount,
            "payment_status": updated_order.get("payment_status"),
        },
    })
