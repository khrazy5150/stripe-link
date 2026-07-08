import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Callable

from stripe_link.common import error_response, header_value, json_response
from stripe_link.domain.documents import validate_appointment
from stripe_link.domain.downloads import digital_download_links
from stripe_link.domain.fees import cached_billing_config, calculate_price
from stripe_link.delegation import apply_delegation
from stripe_link.domain.ledger import refund_entry as build_ledger_refund_entry, sale_entry, sale_entry_from_order
from stripe_link.domain.receipts import receipt_content
from stripe_link.domain.reminders import plan_reminders
from stripe_link.domain.refund_ledger import build_refund_entry, initial_payment_aggregates, set_refund_aggregates
from stripe_link.mailer import send_email
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    calendar_connections_repository,
    customers_repository,
    dynamodb_safe_document,
    fulfillers_repository,
    invoices_repository,
    ledger_repository,
    notifications_repository,
    orders_repository,
    platform_config_repository,
    products_repository,
    refunds_repository,
    services_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
    webhook_events_repository,
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
    products_repo=None,
    refunds_repo=None,
    webhook_events_repo=None,
    orders_repo=None,
    webhook_secret_loader: Callable[[str, str], str | None] = get_platform_webhook_secret,
    now_fn: Callable[[], int] = lambda: int(time.time()),
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
    receipt_mailer: Callable[..., Any] | None = None,
    email_context_loader: Callable[[str], dict[str, str]] | None = None,
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
    event_type = stripe_event.get("type")
    event_id = str(stripe_event.get("id") or "").strip()

    # Idempotency: Stripe redelivers events; skip any we've already processed.
    events_repo = webhook_events_repo or (webhook_events_repository() if os.environ.get("WEBHOOK_EVENTS_TABLE") else None)
    if event_id and events_repo:
        try:
            if events_repo.get(event_id):
                return json_response({
                    "received": True,
                    "duplicate": True,
                    "webhook": {"event_id": event_id, "type": event_type, "tenant_id": tenant_id},
                })
        except RepositoryError:
            events_repo = None  # never block processing on the idempotency store

    persistence = {}
    if event_type == "charge.refunded" and tenant_id:
        persistence = reconcile_charge_refunded(
            stripe_event, tenant_id=tenant_id, orders_repo=orders_repo, refunds_repo=refunds_repo, now_fn=now_fn,
        )
    elif event_type == "charge.dispute.created" and tenant_id:
        persistence = reconcile_dispute(stripe_event, tenant_id=tenant_id, orders_repo=orders_repo, now_fn=now_fn)
    elif event_type == "checkout.session.completed" and tenant_id:
        session = _event_data_object(stripe_event)
        session_metadata = session.get("metadata") or {}
        appointment_id = str(session_metadata.get("appointment_id") or "").strip()
        service_id = str(session_metadata.get("service_id") or "").strip()
        if appointment_id:
            persistence = persist_appointment_paid(
                stripe_event, tenant_id=tenant_id, appointment_id=appointment_id, mode=mode,
                notifications_repo=notifications_repo, now_fn=now_fn, billing_config_loader=billing_config_loader,
            )
        else:
            persistence = persist_checkout_session_completed(
                stripe_event,
                tenant_id=tenant_id,
                checkout_sessions_table=checkout_sessions_table,
                orders_table=orders_table,
                customers_repo=customers_repo,
                invoices_repo=invoices_repo,
                notifications_repo=notifications_repo,
                products_repo=products_repo,
                now_fn=now_fn,
                billing_config_loader=billing_config_loader,
                receipt_mailer=receipt_mailer,
                email_context_loader=email_context_loader,
            )
            # A paid service-offer purchase (pay_then_book) also creates an awaiting_schedule
            # appointment the customer schedules later (STORY-5.1 / STORY-6.2).
            if service_id and str(session_metadata.get("booking_flow") or "pay_then_book") == "pay_then_book":
                persist_service_purchase(
                    stripe_event, tenant_id=tenant_id, mode=mode,
                    order_id=str((persistence or {}).get("order_id") or ""),
                    notifications_repo=notifications_repo, now_fn=now_fn,
                )
    elif event_type and event_type.startswith("invoice.") and tenant_id:
        persistence = persist_invoice_event(
            stripe_event, tenant_id=tenant_id, event_type=event_type, mode=mode,
            invoices_repo=invoices_repo, notifications_repo=notifications_repo,
            now_fn=now_fn, billing_config_loader=billing_config_loader,
        )

    if event_id and events_repo:
        try:
            events_repo.put(dynamodb_safe_document({
                "schema_version": "2026-05-29",
                "document_type": "webhook_event",
                "event_id": event_id,
                "event_type": event_type or "",
                "tenant_id": tenant_id,
                "processed_at": int(now_fn()),
                "result": persistence,
                "payload": stripe_event,
            }))
        except RepositoryError:
            pass

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
    products_repo=None,
    ledger_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
    receipt_mailer: Callable[..., Any] | None = None,
    email_context_loader: Callable[[str], dict[str, str]] | None = None,
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
    products_repo = products_repo or (products_repository() if os.environ.get("PRODUCTS_TABLE") else None)
    ledger_repo = ledger_repo or (ledger_repository() if os.environ.get("LEDGER_TABLE") else None)

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

    if ledger_repo and record_sale_ledger_entry(order_record, ledger_repo, now):
        written.append("ledger_entry")

    download_links = resolve_download_links(order_record, tenant_id, products_repo)
    receipt = send_order_receipt(
        order_record, tenant_id,
        mailer_send=receipt_mailer, context_loader=email_context_loader, download_links=download_links,
    )

    return {
        "status": "stored",
        "session_id": session.get("id", ""),
        "invoice_id": invoice_record.get("invoice_id") if invoice_record else "",
        "order_id": order_record.get("order_id", ""),
        "written": written,
        "receipt": receipt,
    }


def persist_service_purchase(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    mode: str,
    order_id: str = "",
    appointments_repo=None,
    notifications_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """A paid service-offer purchase (pay_then_book): create a paid, awaiting_schedule appointment
    the customer schedules later. Idempotent on the checkout session id (STORY-5.1 / STORY-6.2)."""
    import secrets as _secrets

    session = _event_data_object(stripe_event)
    metadata = session.get("metadata") or {}
    service_id = str(metadata.get("service_id") or "").strip()
    if not service_id:
        return {"status": "skipped", "reason": "no_service_id"}
    appointments_repo = appointments_repo or (appointments_repository() if os.environ.get("SERVICES_TABLE") else None)
    if not appointments_repo:
        return {"status": "skipped", "reason": "appointments_repo_unavailable"}

    session_id = str(session.get("id") or "").strip()
    appointment_id = f"appt_svc_{session_id}" if session_id else f"appt_svc_{str(session.get('payment_intent') or '')}"
    if appointments_repo.get(tenant_id, appointment_id):
        return {"status": "skipped", "reason": "already_created", "appointment_id": appointment_id}

    now = int(now_fn())
    details = session.get("customer_details") or {}
    customer = {k: v for k, v in {"name": details.get("name"), "email": details.get("email"), "phone": details.get("phone")}.items() if v}
    amount_total = int(session.get("amount_total") or 0)
    currency = str(session.get("currency") or "usd").lower()
    appointment = {
        "schema_version": "2026-05-29",
        "document_type": "appointment",
        "tenant_id": tenant_id,
        "appointment_id": appointment_id,
        "service_id": service_id,
        "service_name": str(metadata.get("service_name") or "Service"),
        "status": "booked",
        "payment_status": "paid",
        "awaiting_schedule": True,
        "customer": customer,
        "price": {"currency": currency, "unit_amount": amount_total, "price_id": str(metadata.get("service_price_id") or "")},
        "source": "offer",
        "offer_id": str(metadata.get("offer_id") or ""),
        "page_id": str(metadata.get("page_id") or ""),
        "order_id": order_id,
        "payment_intent_id": str(session.get("payment_intent") or ""),
        "customer_manage_token": _secrets.token_urlsafe(24),
        "stripe_mode": mode,
        "created_at": now,
        "updated_at": now,
    }
    try:
        validate_appointment(appointment)
        appointments_repo.put(appointment)
    except Exception:  # noqa: BLE001 - never fail the webhook on booking side effects
        return {"status": "error", "reason": "appointment_save_failed"}

    if notifications_repo:
        try:
            notifications_repo.put({
                "schema_version": "2026-05-29", "document_type": "notification", "tenant_id": tenant_id,
                "notification_id": f"notif_appt_{appointment_id}", "type": "order", "severity": "success",
                "title": "New booking (awaiting schedule)",
                "message": f"{customer.get('name') or customer.get('email') or 'A customer'} purchased {appointment['service_name']} and needs to pick a time.",
                "status": "unread", "sort_priority": 100,
                "related": {"appointment_id": appointment_id}, "action": {"label": "View appointments", "route": "services"},
                "created_at": now, "read_at": None, "archived_at": None,
            })
        except Exception:  # noqa: BLE001
            pass
    return {"status": "awaiting_schedule", "appointment_id": appointment_id}


def persist_appointment_paid(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    appointment_id: str,
    mode: str,
    appointments_repo=None,
    ledger_repo=None,
    notifications_repo=None,
    services_repo=None,
    fulfillers_repo=None,
    connections_repo=None,
    tenant_repo=None,
    mailer_send=None,
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """A paid booking's checkout session completed: mark the appointment booked/paid, drop the
    hold, append a ledger sale entry, route the calendar event to the delegate's calendar, email
    the delegate, and emit the booked notification."""
    session = _event_data_object(stripe_event)
    appointments_repo = appointments_repo or (appointments_repository() if os.environ.get("SERVICES_TABLE") else None)
    if not appointments_repo:
        return {"status": "skipped", "reason": "appointments_repo_unavailable"}
    appointment = appointments_repo.get(tenant_id, appointment_id)
    if not appointment:
        return {"status": "skipped", "reason": "appointment_not_found"}

    now = int(now_fn())
    fees = fee_breakdown_from_session(session, billing_config_loader)
    payment_intent = str(session.get("payment_intent") or "").strip()
    amount_total = int(session.get("amount_total") or (appointment.get("price") or {}).get("unit_amount") or 0)
    currency = str(session.get("currency") or (appointment.get("price") or {}).get("currency") or "usd")

    updated = {**appointment, "status": "booked", "payment_status": "paid", "updated_at": now}
    if payment_intent:
        updated["payment_intent_id"] = payment_intent
    updated.pop("hold_expires_at", None)  # confirmed booking outlives the reserve hold
    updated["reminders"] = plan_reminders(updated, now=now)
    appointments_repo.put(updated)

    # Route the calendar event to the assigned delegate's calendar + email them (best-effort).
    services_repo = services_repo or (services_repository() if os.environ.get("SERVICES_TABLE") else None)
    fulfillers_repo = fulfillers_repo or (fulfillers_repository() if os.environ.get("SERVICES_TABLE") else None)
    connections_repo = connections_repo or (calendar_connections_repository() if os.environ.get("CALENDAR_CONNECTIONS_TABLE") else None)
    tenant_repo = tenant_repo or (tenant_profiles_repository() if os.environ.get("TENANT_PROFILES_TABLE") else None)
    apply_delegation(
        updated, action="upsert", change="booked", appointments_repo=appointments_repo,
        services_repo=services_repo, fulfillers_repo=fulfillers_repo, connections_repo=connections_repo,
        tenant_repo=tenant_repo, mailer_send=mailer_send,
    )

    ledger_written = False
    ledger_repo = ledger_repo or (ledger_repository() if os.environ.get("LEDGER_TABLE") else None)
    if ledger_repo and amount_total and payment_intent:
        try:
            ledger_repo.append(sale_entry(
                tenant_id=tenant_id,
                entry_id=f"le_sale_{payment_intent}",
                occurred_at=now,
                mode=mode,
                currency=currency,
                gross=amount_total,
                stripe_fee=int(fees.get("stripe_fee") or 0),
                platform_fee=int(fees.get("platform_fee") or 0),
                idempotency_key=f"sale:{payment_intent}",
                order_id=appointment_id,
                customer=appointment.get("customer") if isinstance(appointment.get("customer"), dict) else None,
                stripe={"payment_intent_id": payment_intent},
                source="webhook",
                description=f"Booking: {appointment.get('service_name') or appointment.get('service_id')}",
                now_epoch=now,
            ))
            ledger_written = True
        except Exception:  # noqa: BLE001 - ledger must not fail the webhook
            pass

    if notifications_repo:
        try:
            notifications_repo.put(appointment_notification(updated, tenant_id, now))
        except Exception:  # noqa: BLE001 - notification must not fail the webhook
            pass

    return {"status": "booked", "appointment_id": appointment_id, "ledger_entry": ledger_written}


def appointment_notification(appointment: dict[str, Any], tenant_id: str, now: int) -> dict[str, Any]:
    customer = appointment.get("customer") or {}
    who = customer.get("name") or customer.get("email") or "A customer"
    service = appointment.get("service_name") or appointment.get("service_id") or "a service"
    return {
        "schema_version": "2026-05-29",
        "document_type": "notification",
        "tenant_id": tenant_id,
        "notification_id": f"notif_appt_{appointment.get('appointment_id', '')}",
        "type": "order",
        "severity": "success",
        "title": "New booking",
        "message": f"{who} booked {service} for {appointment.get('starts_at', '')}.",
        "status": "unread",
        "sort_priority": 100,
        "related": {"appointment_id": appointment.get("appointment_id", "")},
        "action": {"label": "View appointments", "route": "services"},
        "created_at": int(now),
        "read_at": None,
        "archived_at": None,
    }


INVOICE_EVENT_STATUS = {
    "invoice.paid": "paid",
    "invoice.payment_succeeded": "paid",
    "invoice.finalized": "open",
    "invoice.payment_failed": "open",
    "invoice.voided": "void",
    "invoice.marked_uncollectible": "uncollectible",
}


def persist_invoice_event(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    event_type: str,
    mode: str,
    invoices_repo=None,
    ledger_repo=None,
    notifications_repo=None,
    appointments_repo=None,
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """Sync a Stripe invoice.* event onto our Invoice doc; on paid, append a sale ledger entry and
    emit a notification. Only invoices we created (metadata.invoice_id) are tracked."""
    new_status = INVOICE_EVENT_STATUS.get(event_type)
    if not new_status:
        return {"status": "ignored", "event": event_type}
    stripe_invoice = _event_data_object(stripe_event)
    metadata = stripe_invoice.get("metadata") if isinstance(stripe_invoice.get("metadata"), dict) else {}
    invoice_id = str(metadata.get("invoice_id") or "").strip()
    if not invoice_id:
        return {"status": "skipped", "reason": "not_a_tracked_invoice"}

    invoices_repo = invoices_repo or (invoices_repository() if os.environ.get("INVOICES_TABLE") else None)
    if not invoices_repo:
        return {"status": "skipped", "reason": "invoices_repo_unavailable"}
    invoice = invoices_repo.get(tenant_id, invoice_id)
    if not invoice:
        return {"status": "skipped", "reason": "invoice_not_found"}

    now = int(now_fn())
    payment = dict(invoice.get("payment") or {})
    if stripe_invoice.get("hosted_invoice_url"):
        payment["hosted_invoice_url"] = stripe_invoice["hosted_invoice_url"]
    if stripe_invoice.get("invoice_pdf"):
        payment["invoice_pdf_url"] = stripe_invoice["invoice_pdf"]
    payment_intent = str(stripe_invoice.get("payment_intent") or "").strip()
    if payment_intent:
        payment["payment_intent_id"] = payment_intent

    ledger_written = False
    if new_status == "paid":
        payment["paid_at"] = now
        amount_paid = int(stripe_invoice.get("amount_paid") or 0)
        currency = str(stripe_invoice.get("currency") or (invoice.get("amounts") or {}).get("currency") or "usd")
        ledger_repo = ledger_repo or (ledger_repository() if os.environ.get("LEDGER_TABLE") else None)
        if ledger_repo and amount_paid and payment_intent:
            try:
                fees = fee_breakdown_from_session({"amount_total": amount_paid, "currency": currency, "metadata": metadata}, billing_config_loader)
                ledger_repo.append(sale_entry(
                    tenant_id=tenant_id, entry_id=f"le_sale_{payment_intent}", occurred_at=now, mode=mode, currency=currency,
                    gross=amount_paid, stripe_fee=int(fees.get("stripe_fee") or 0), platform_fee=int(fees.get("platform_fee") or 0),
                    idempotency_key=f"sale:{payment_intent}", order_id=invoice_id,
                    customer=invoice.get("customer") if isinstance(invoice.get("customer"), dict) else None,
                    stripe={"payment_intent_id": payment_intent}, source="webhook", description=f"Invoice {invoice_id}", now_epoch=now,
                ))
                ledger_written = True
            except Exception:  # noqa: BLE001
                pass

    updated = {**invoice, "status": new_status, "payment": payment, "updated_at": now}
    if new_status in {"void"}:
        updated["voided_at"] = now
    invoices_repo.put(updated)

    # book_then_pay: a paid invoice linked to an appointment marks that appointment paid (STORY-5.2).
    linked_appointment_id = str(((invoice.get("source") or {}).get("appointment_id")) or "").strip()
    appointments_repo = appointments_repo or (appointments_repository() if os.environ.get("SERVICES_TABLE") else None)
    if new_status == "paid" and linked_appointment_id and appointments_repo:
        try:
            appt = appointments_repo.get(tenant_id, linked_appointment_id)
            if appt and appt.get("payment_status") != "paid":
                appointments_repo.put({**appt, "payment_status": "paid", "invoice_id": invoice_id, "updated_at": now})
        except Exception:  # noqa: BLE001 - appointment sync must not fail the webhook
            pass

    if new_status == "paid" and notifications_repo:
        try:
            notifications_repo.put(invoice_paid_notification(updated, tenant_id, now))
        except Exception:  # noqa: BLE001
            pass

    return {"status": new_status, "invoice_id": invoice_id, "ledger_entry": ledger_written}


def invoice_paid_notification(invoice: dict[str, Any], tenant_id: str, now: int) -> dict[str, Any]:
    customer = invoice.get("customer") or {}
    who = customer.get("name") or customer.get("email") or "A customer"
    return {
        "schema_version": "2026-05-29",
        "document_type": "notification",
        "tenant_id": tenant_id,
        "notification_id": f"notif_invpaid_{invoice.get('invoice_id', '')}",
        "type": "paid_invoice",
        "severity": "success",
        "title": "Invoice paid",
        "message": f"{who} paid invoice {invoice.get('invoice_id', '')}.",
        "status": "unread",
        "sort_priority": 100,
        "related": {"invoice_id": invoice.get("invoice_id", "")},
        "action": {"label": "View invoices", "route": "invoices"},
        "created_at": int(now),
        "read_at": None,
        "archived_at": None,
    }


def record_sale_ledger_entry(order: dict[str, Any], ledger_repo, now: int) -> bool:
    """Best-effort append of a sale entry to the transaction ledger. Never fails the webhook."""
    try:
        entry = sale_entry_from_order(order, now_epoch=now)
        if not entry:
            return False
        ledger_repo.append(entry)
        return True
    except Exception:  # noqa: BLE001 - ledger recording must not break checkout persistence
        return False


def record_refund_ledger_entry(ledger_repo, *, tenant_id: str, order: dict[str, Any], refund: dict[str, Any], payment_intent: str, charge_id: str, now: int) -> bool:
    """Best-effort append of a refund entry. Idempotent (deterministic entry id per stripe refund)."""
    try:
        stripe_refund_id = str(refund.get("id") or "").strip()
        if not stripe_refund_id:
            return False
        customer = order.get("customer") if isinstance(order.get("customer"), dict) else None
        entry = build_ledger_refund_entry(
            tenant_id=tenant_id,
            entry_id=f"le_refund_{stripe_refund_id}",
            occurred_at=now,
            mode="live" if order.get("mode") == "live" else "test",
            currency=str(order.get("currency") or "usd"),
            refund_amount=int(refund.get("amount") or 0),
            idempotency_key=f"refund:{stripe_refund_id}",
            order_id=str(order.get("order_id") or "") or None,
            customer=customer,
            stripe={"refund_id": stripe_refund_id, "charge_id": charge_id, "payment_intent_id": payment_intent},
            source="reconciliation",
            now_epoch=now,
        )
        ledger_repo.append(entry)
        return True
    except Exception:  # noqa: BLE001 - ledger recording must not break refund reconciliation
        return False


def reconcile_charge_refunded(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    orders_repo=None,
    refunds_repo=None,
    ledger_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """Reflect a Stripe refund on the local order and append ledger rows.

    Resolves the order from the charge's PaymentIntent via the orders GSI (works for both our
    refunds and Stripe-dashboard refunds), dedupes each Stripe refund against the ledger, and
    sets the order's authoritative refund aggregates from charge.amount_refunded.
    """
    charge = _event_data_object(stripe_event)
    payment_intent = str(charge.get("payment_intent") or "").strip()
    charge_id = str(charge.get("id") or "").strip()

    orders_repo = orders_repo or (orders_repository() if os.environ.get("ORDERS_TABLE") else None)
    if not orders_repo:
        return {"status": "skipped", "reason": "orders_repo_unavailable"}
    order = orders_repo.find_by_payment_intent(payment_intent) if payment_intent else None
    if not order:
        return {"status": "skipped", "reason": "order_not_found"}
    order_id = str(order.get("order_id") or "")
    currency = str(order.get("currency") or "usd")

    now = int(now_fn())
    refunds_repo = refunds_repo or (refunds_repository() if os.environ.get("REFUNDS_TABLE") else None)
    ledger_repo = ledger_repo or (ledger_repository() if os.environ.get("LEDGER_TABLE") else None)
    refunds = ((charge.get("refunds") or {}).get("data")) or []
    ledger_written = 0
    for refund in refunds:
        stripe_refund_id = str(refund.get("id") or "").strip()
        if not stripe_refund_id:
            continue
        # Ledger refund entries are idempotent by deterministic id, so record them regardless of
        # whether the refunds table already has this refund (e.g. our own execute path recorded it).
        if ledger_repo:
            record_refund_ledger_entry(ledger_repo, tenant_id=tenant_id, order=order, refund=refund, payment_intent=payment_intent, charge_id=charge_id, now=now)
        if refunds_repo:
            try:
                if refunds_repo.find_by_stripe_refund(stripe_refund_id):
                    continue  # our execute path or a prior delivery already recorded it
                refund_metadata = refund.get("metadata") if isinstance(refund.get("metadata"), dict) else {}
                initiated_by = "admin" if refund_metadata.get("refund_request_id") else "stripe_dashboard"
                refunds_repo.put(build_refund_entry(
                    refund_id=stripe_refund_id,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    payment_intent_id=payment_intent,
                    charge_id=charge_id,
                    amount=int(refund.get("amount") or 0),
                    currency=currency,
                    reason=str(refund.get("reason") or ""),
                    initiated_by=initiated_by,
                    stripe_refund_id=stripe_refund_id,
                    status=str(refund.get("status") or "succeeded"),
                    created_at=now,
                ))
                ledger_written += 1
            except RepositoryError:
                continue

    total_refunded = int(charge.get("amount_refunded") or 0)
    updated = set_refund_aggregates(order, amount_refunded=total_refunded, refund_count=len(refunds), at=now)
    orders_repo.put(updated)
    return {
        "status": "reconciled",
        "order_id": order_id,
        "amount_refunded": total_refunded,
        "ledger_written": ledger_written,
    }


def reconcile_dispute(
    stripe_event: dict[str, Any],
    *,
    tenant_id: str,
    orders_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """Flag the order as disputed when a chargeback is opened."""
    dispute = _event_data_object(stripe_event)
    payment_intent = str(dispute.get("payment_intent") or "").strip()
    orders_repo = orders_repo or (orders_repository() if os.environ.get("ORDERS_TABLE") else None)
    if not orders_repo or not payment_intent:
        return {"status": "skipped", "reason": "no_pi_or_repo"}
    order = orders_repo.find_by_payment_intent(payment_intent)
    if not order:
        return {"status": "skipped", "reason": "order_not_found"}
    now = int(now_fn())
    order["payment_status"] = "disputed"
    order["updated_at"] = now
    orders_repo.put(order)
    return {"status": "disputed", "order_id": order.get("order_id", "")}


def resolve_download_links(order: dict[str, Any], tenant_id: str, products_repo) -> list[dict[str, str]]:
    """Download links for any digital product on the order (for the receipt). Best-effort."""
    try:
        product_id = str((order.get("product") or {}).get("product_id") or "")
        if not product_id or not products_repo:
            return []
        product = products_repo.get(tenant_id, product_id)
        if not product:
            return []
        return digital_download_links(order, product, os.environ.get("PUBLIC_API_BASE_URL", ""))
    except Exception:  # noqa: BLE001 - download links must not fail the webhook
        return []


def load_tenant_email_context(tenant_id: str) -> dict[str, str]:
    """Business name (TenantProfile) + support email (TenantConfig) for receipt branding."""
    business_name = ""
    support_email = ""
    if os.environ.get("TENANT_PROFILES_TABLE"):
        profile = tenant_profiles_repository().get(tenant_id, tenant_id) or {}
        business_name = str(profile.get("business_name") or "").strip()
    if os.environ.get("PLATFORM_CONFIG_TABLE"):
        config = platform_config_repository().get(tenant_id) or {}
        support_email = str(((config.get("support") or {}).get("email")) or "").strip()
    return {"business_name": business_name, "support_email": support_email}


def send_order_receipt(
    order: dict[str, Any],
    tenant_id: str,
    *,
    mailer_send: Callable[..., Any] | None = None,
    context_loader: Callable[[str], dict[str, str]] | None = None,
    download_links: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Best-effort receipt email. Never raises -- Stripe would retry and duplicate writes."""
    if mailer_send is None and not os.environ.get("EMAIL_FROM_ADDRESS"):
        return {"status": "skipped", "reason": "email_not_configured"}
    email = str(((order.get("customer") or {}).get("email")) or "").strip()
    if not email:
        return {"status": "skipped", "reason": "no_customer_email"}
    try:
        context = (context_loader or load_tenant_email_context)(tenant_id)
        content = receipt_content(
            order,
            business_name=context.get("business_name", ""),
            support_email=context.get("support_email", ""),
            download_links=download_links,
        )
        (mailer_send or send_email)(
            to=email,
            subject=content["subject"],
            html=content["html"],
            text=content["text"],
            from_name=context.get("business_name", ""),
            reply_to=context.get("support_email", ""),
        )
        return {"status": "sent", "to": email}
    except Exception as exc:  # noqa: BLE001 - receipt failure must not fail the webhook
        return {"status": "failed", "error": str(exc)}


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
        "payment_intent_id": session.get("payment_intent", ""),
        "mode": "live" if session.get("livemode") else "test",
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
        **initial_payment_aggregates(int(session.get("amount_total") or 0)),
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
