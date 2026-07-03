import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Callable

from stripe_link.common import error_response, header_value, json_response
from stripe_link.domain.fees import cached_billing_config, calculate_price
from stripe_link.repositories.documents import (
    RepositoryError,
    customers_repository,
    dynamodb_safe_document,
    invoices_repository,
    notifications_repository,
    stripe_keys_repository,
)
from stripe_link.stripe_platform_secrets import get_platform_webhook_secret


SIGNATURE_TOLERANCE_SECONDS = 300


def _request_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return str(body)


def _webhook_kind(event: dict[str, Any]) -> str:
    path = str(event.get("path") or event.get("rawPath") or "")
    return "preview" if path.rstrip("/").endswith("/stripe-preview") else "stable"


def _mode_for_environment() -> str:
    return "live" if os.environ.get("ENVIRONMENT") == "prod" else "test"


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    timestamp = 0
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = 0
        elif key == "v1" and value:
            signatures.append(value)
    return timestamp, signatures


def _signature_is_valid(
    *,
    body: str,
    signature_header: str,
    secret: str,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> bool:
    timestamp, signatures = _parse_signature_header(signature_header)
    if not timestamp or not signatures:
        return False
    if abs(now_fn() - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False

    signed_payload = f"{timestamp}.{body}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _metadata_tenant_id(stripe_event: dict[str, Any]) -> str:
    data_object = ((stripe_event.get("data") or {}).get("object") or {})
    metadata = data_object.get("metadata") if isinstance(data_object, dict) else {}
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("tenant_id") or metadata.get("client_id") or "").strip()


def _event_data_object(stripe_event: dict[str, Any]) -> dict[str, Any]:
    data_object = ((stripe_event.get("data") or {}).get("object") or {})
    return data_object if isinstance(data_object, dict) else {}


def handler(
    event,
    context,
    *,
    repository=None,
    checkout_sessions_table=None,
    orders_table=None,
    customers_repo=None,
    invoices_repo=None,
    notifications_repo=None,
    webhook_secret_loader: Callable[[str, str], str | None] = get_platform_webhook_secret,
    now_fn: Callable[[], int] = lambda: int(time.time()),
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
):
    method = event.get("httpMethod", "")
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response("Method not allowed.", 405, code="method_not_allowed")

    kind = _webhook_kind(event)
    mode = _mode_for_environment()
    secret = webhook_secret_loader(kind, mode)
    if not secret:
        return error_response(
            f"Stripe {kind} webhook signing secret is not configured for {mode}.",
            500,
            code="webhook_secret_not_configured",
        )

    body = _request_body(event)
    signature_header = header_value(event, "Stripe-Signature")
    if not _signature_is_valid(body=body, signature_header=signature_header, secret=secret, now_fn=now_fn):
        return error_response("Stripe webhook signature verification failed.", 400, code="invalid_signature")

    try:
        stripe_event = json.loads(body)
    except json.JSONDecodeError as exc:
        return error_response(f"Invalid JSON body: {exc}", 400, code="invalid_json")
    if not isinstance(stripe_event, dict):
        return error_response("Stripe webhook payload must be an object.", 400, code="invalid_json")

    account_id = str(stripe_event.get("account") or "").strip()
    tenant_document = None
    if account_id:
        try:
            tenant_document = (repository or stripe_keys_repository()).find_by_connect_account_id(account_id, mode)
        except RepositoryError as exc:
            return error_response(str(exc), 500, code="repository_error")

    tenant_id = str((tenant_document or {}).get("tenant_id") or "").strip() or _metadata_tenant_id(stripe_event)
    persistence = {}
    if stripe_event.get("type") == "checkout.session.completed" and tenant_id:
        persistence = persist_checkout_session_completed(
            stripe_event,
            tenant_id=tenant_id,
            checkout_sessions_table=checkout_sessions_table,
            orders_table=orders_table,
            customers_repo=customers_repo,
            invoices_repo=invoices_repo,
            notifications_repo=notifications_repo,
            now_fn=now_fn,
            billing_config_loader=billing_config_loader,
        )
    return json_response({
        "received": True,
        "webhook": {
            "kind": kind,
            "mode": mode,
            "event_id": stripe_event.get("id", ""),
            "type": stripe_event.get("type", ""),
            "api_version": stripe_event.get("api_version", ""),
            "livemode": bool(stripe_event.get("livemode")),
            "connect_account_id": account_id,
            "tenant_id": tenant_id,
            "tenant_status": "resolved" if tenant_id else "unknown",
            "persistence": persistence,
        },
    })


def persist_checkout_session_completed(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    checkout_sessions_table=None,
    orders_table=None,
    customers_repo=None,
    invoices_repo=None,
    notifications_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    session = _event_data_object(stripe_event)
    if not session:
        return {"status": "skipped", "reason": "missing_session"}

    now = int(now_fn())
    checkout_sessions_table = checkout_sessions_table or dynamodb_table(os.environ.get("CHECKOUT_SESSIONS_TABLE", ""))
    orders_table = orders_table or dynamodb_table(os.environ.get("ORDERS_TABLE", ""))
    customers_repo = customers_repo or (customers_repository() if os.environ.get("CUSTOMERS_TABLE") else None)
    invoices_repo = invoices_repo or (invoices_repository() if os.environ.get("INVOICES_TABLE") else None)
    notifications_repo = notifications_repo or (notifications_repository() if os.environ.get("NOTIFICATIONS_TABLE") else None)

    fees = fee_breakdown_from_session(session, billing_config_loader)
    session_record = checkout_session_record(stripe_event, session, tenant_id, now)
    order_record = order_record_from_session(session, tenant_id, now, fees)
    invoice_record = invoice_record_from_session(session, tenant_id, now, fees)
    customer_record = customer_record_from_session(session, tenant_id, now)
    notification_record = notification_record_from_session(session, tenant_id, order_record, invoice_record, now)

    written = []
    if checkout_sessions_table:
        checkout_sessions_table.put_item(Item=dynamodb_safe_document(session_record))
        written.append("checkout_session")
    if orders_table:
        orders_table.put_item(Item=dynamodb_safe_document(order_record))
        written.append("order")
    if invoice_record and invoices_repo:
        invoices_repo.put(invoice_record)
        written.append("invoice")
    if customer_record and customers_repo:
        customers_repo.put(customer_record)
        written.append("customer")
    if notification_record and notifications_repo:
        notifications_repo.put(notification_record)
        written.append("notification")

    return {
        "status": "stored",
        "session_id": session.get("id", ""),
        "invoice_id": invoice_record.get("invoice_id") if invoice_record else "",
        "order_id": order_record.get("order_id", ""),
        "written": written,
    }


def dynamodb_table(table_name: str):
    if not table_name:
        return None
    import boto3

    return boto3.resource("dynamodb").Table(table_name)


def checkout_session_record(stripe_event: dict[str, Any], session: dict[str, Any], tenant_id: str, now: int) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    return {
        "session_id": session.get("id", ""),
        "tenant_id": tenant_id,
        "stripe_event_id": stripe_event.get("id", ""),
        "stripe_account_id": stripe_event.get("account", ""),
        "mode": "live" if stripe_event.get("livemode") else "test",
        "status": session.get("status", ""),
        "payment_status": session.get("payment_status", ""),
        "amount_total": int(session.get("amount_total") or 0),
        "currency": session.get("currency") or "usd",
        "customer_id": session.get("customer", ""),
        "payment_intent_id": session.get("payment_intent", ""),
        "metadata": metadata,
        "raw": session,
        "created_at": int(session.get("created") or now),
        "updated_at": now,
    }


def fee_breakdown_from_session(
    session: dict[str, Any],
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    amount = int(session.get("amount_total") or 0)
    result = calculate_price(
        tenant_keyed_amount=amount,
        currency=session.get("currency") or "usd",
        product_type=metadata.get("product_type") or "physical",
        fee_handling="standard",
        pricing_model="recurring" if session.get("mode") == "subscription" else "one_time",
        tenant_plan=metadata.get("tenant_plan") or "basic",
        billing_config=cached_billing_config(billing_config_loader),
    )
    return result["breakdown"]


def order_record_from_session(session: dict[str, Any], tenant_id: str, now: int, fees: dict[str, Any]) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    details = customer_details(session)
    product_name = metadata.get("product_name") or "Checkout"
    created = int(session.get("created") or now)
    session_id = session.get("id", "")
    return {
        "tenant_id": tenant_id,
        "order_id": f"order_{session_id}",
        "schema_version": "2026-05-29",
        "document_type": "order",
        "session_id": session_id,
        "line_item_type": "checkout",
        "status": "paid" if session.get("payment_status") == "paid" else session.get("payment_status", "completed"),
        "amount_total": int(session.get("amount_total") or 0),
        "currency": session.get("currency") or "usd",
        "customer": {
            "name": details.get("name", ""),
            "email": details.get("email", ""),
            "phone": details.get("phone", ""),
            "stripe_customer_id": session.get("customer", ""),
        },
        "product": {
            "product_id": metadata.get("product_id", ""),
            "price_id": metadata.get("price_id", ""),
            "name": product_name,
        },
        "fees": fees,
        "attribution": attribution_from_metadata(metadata),
        "metadata": metadata,
        "created_at": str(created),
        "updated_at": now,
    }


def invoice_record_from_session(session: dict[str, Any], tenant_id: str, now: int, fees: dict[str, Any]) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    details = customer_details(session)
    email = details.get("email") or "unknown"
    amount = int(session.get("amount_total") or 0)
    currency = session.get("currency") or "usd"
    session_id = session.get("id", "")
    product_name = metadata.get("product_name") or "Checkout"
    created = int(session.get("created") or now)
    return {
        "schema_version": "2026-05-29",
        "document_type": "invoice",
        "tenant_id": tenant_id,
        "invoice_id": f"inv_{session_id}",
        "status": "paid" if session.get("payment_status") == "paid" else "open",
        "customer": {
            "name": details.get("name", ""),
            "email": email,
            "phone": details.get("phone", ""),
            "stripe_customer_id": session.get("customer", ""),
        },
        "line_items": [
            {
                "description": product_name,
                "quantity": 1,
                "unit_amount": amount,
                "product_id": metadata.get("product_id", ""),
                "price_id": metadata.get("price_id", ""),
            }
        ],
        "amounts": {
            "currency": currency,
            "subtotal": amount,
            "total": amount,
            "amount_due": 0 if session.get("payment_status") == "paid" else amount,
            "amount_paid": amount if session.get("payment_status") == "paid" else 0,
            "stripe_fee": fees.get("stripe_fee", 0),
            "platform_fee": fees.get("platform_fee", 0),
            "net_payout": fees.get("net_payout", 0),
        },
        "stripe": {
            "checkout_session_id": session_id,
            "payment_intent_id": session.get("payment_intent", ""),
        },
        "attribution": attribution_from_metadata(metadata),
        "created_at": created,
        "updated_at": now,
    }


def customer_record_from_session(session: dict[str, Any], tenant_id: str, now: int) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    details = customer_details(session)
    stripe_customer_id = str(session.get("customer") or "").strip()
    email = details.get("email") or ""
    customer_id = stripe_customer_id or (email.lower() if email else "")
    if not customer_id:
        return {}
    amount = int(session.get("amount_total") or 0)
    session_id = session.get("id", "")
    return {
        "schema_version": "2026-05-29",
        "document_type": "customer",
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "contact": {
            "name": details.get("name", ""),
            "email": email or "unknown",
            "phone": details.get("phone", ""),
        },
        "summary": {
            "total_orders": 1,
            "lifetime_value": amount,
            "currency": session.get("currency") or "usd",
            "last_order_at": int(session.get("created") or now),
        },
        "product_affinity": [
            {
                "product_id": metadata.get("product_id", ""),
                "product_name": metadata.get("product_name", ""),
            }
        ],
        "transaction_history": [
            {
                "transaction_id": session_id,
                "type": "checkout",
                "created_at": int(session.get("created") or now),
                "amount": amount,
                "currency": session.get("currency") or "usd",
                "attribution": attribution_from_metadata(metadata),
            }
        ],
        "updated_at": now,
    }


def notification_record_from_session(
    session: dict[str, Any],
    tenant_id: str,
    order_record: dict[str, Any],
    invoice_record: dict[str, Any],
    now: int,
) -> dict[str, Any]:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    details = customer_details(session)
    amount = int(session.get("amount_total") or 0)
    currency = str(session.get("currency") or "usd").upper()
    product_name = metadata.get("product_name") or "Checkout"
    customer_name = details.get("name") or details.get("email") or "Customer"
    return {
        "schema_version": "2026-05-29",
        "document_type": "notification",
        "tenant_id": tenant_id,
        "notification_id": f"notif_{session.get('id', '')}",
        "type": "order",
        "severity": "success",
        "title": "New order",
        "message": f"{customer_name} purchased {product_name} for {currency} {(amount / 100):.2f}.",
        "status": "unread",
        "sort_priority": 100,
        "related": {
            "invoice_id": invoice_record.get("invoice_id", ""),
            "order_id": order_record.get("order_id", ""),
            "customer_id": order_record.get("customer", {}).get("stripe_customer_id", ""),
            "page_id": metadata.get("page_id", ""),
            "offer_id": metadata.get("offer") or metadata.get("offer_id") or "",
        },
        "action": {
            "label": "View order",
            "route": "orders",
        },
        "created_at": int(session.get("created") or now),
        "read_at": None,
        "archived_at": None,
    }


def customer_details(session: dict[str, Any]) -> dict[str, str]:
    details = session.get("customer_details") if isinstance(session.get("customer_details"), dict) else {}
    return {
        "name": str(details.get("name") or ""),
        "email": str(details.get("email") or session.get("customer_email") or ""),
        "phone": str(details.get("phone") or ""),
    }


def attribution_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "offer_id": metadata.get("offer") or metadata.get("offer_id") or "",
        "page_id": metadata.get("page_id") or "",
        "funnel_id": metadata.get("funnel_id") or "",
        "order_bump_ids": compact_csv(metadata.get("order_bump_ids") or ""),
        "post_checkout_entry": metadata.get("post_checkout_entry") or "",
    }


def compact_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]
