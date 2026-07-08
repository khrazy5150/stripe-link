"""Public booking API (resolve-style, like experiments_resolve / custom_domains_resolve).

Tenant is derived from the service, not an admin session. B.1 ships the availability endpoint;
resolve / reserve / checkout / manage land in later Phase B steps.
"""
import os
import secrets
import time
import uuid

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params
from stripe_link.domain.appointments import AppointmentTransitionError, transition_appointment
from stripe_link.domain.booking import compensation_snapshot, requires_payment, reserved_appointment, slot_end_iso
from stripe_link.domain.documents import DocumentValidationError, validate_appointment
from stripe_link.domain.fees import cached_billing_config, calculate_price, normalize_tier_id
from stripe_link.domain.scheduling import available_slots
from stripe_link.calendar_sync import sync_appointment_event, tenant_busy_intervals
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.runtime.booking_page import render_booking_page
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    availability_exceptions_repository,
    fulfillers_repository,
    notifications_repository,
    services_repository,
    slot_locks_repository,
    stripe_keys_repository,
    tenant_availability_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials

DEFAULT_WINDOW_DAYS = 14
HOLD_MINUTES = 10
SERVICE_FEE_PRODUCT_TYPE = "digital"


def handler(
    event,
    context,
    services_repo=None,
    availability_repo=None,
    fulfillers_repo=None,
    exceptions_repo=None,
    appointments_repo=None,
    slot_locks_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    notifications_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
):
    services_repo = services_repo or services_repository()
    availability_repo = availability_repo or tenant_availability_repository()
    fulfillers_repo = fulfillers_repo or fulfillers_repository()
    exceptions_repo = exceptions_repo or availability_exceptions_repository()
    appointments_repo = appointments_repo or appointments_repository()
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")
    repos = (services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo)

    if method == "OPTIONS":
        return json_response({})
    if path.startswith("/book/") and method == "GET":
        return booking_page_route(event, services_repo)
    if "/appointments/reserve" in path and method == "POST":
        return reserve_route(event, repos, slot_locks_repo or slot_locks_repository())
    if "/appointments/checkout" in path and method == "POST":
        return checkout_route(
            event, appointments_repo,
            stripe_repo=stripe_repo, tenant_repo=tenant_repo, notifications_repo=notifications_repo,
            secret_cipher=secret_cipher, opener=opener, billing_config_loader=billing_config_loader,
        )
    if "/appointments/manage/cancel" in path and method == "POST":
        return manage_cancel_route(event, appointments_repo, slot_locks_repo or slot_locks_repository())
    if "/appointments/manage/reschedule" in path and method == "POST":
        return manage_reschedule_route(event, repos, slot_locks_repo or slot_locks_repository())
    if "/appointments/manage" in path and method == "GET":
        return manage_view_route(event, appointments_repo)
    if "/availability" in path and method == "GET":
        return availability_route(event, *repos)
    return error_response("Unsupported booking route.", status_code=404, code="not_found")


def reserve_route(event, repos, slot_locks_repo):
    services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo = repos
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    service_id = str(body.get("service_id") or "").strip()
    slot_start = str(body.get("slot_start") or "").strip()
    customer = body.get("customer") if isinstance(body.get("customer"), dict) else {}
    if not service_id or not slot_start:
        return error_response("service_id and slot_start are required.", code="missing_fields")
    if not str(customer.get("email") or "").strip():
        return error_response("customer.email is required.", code="missing_customer_email")

    service = services_repo.find_by_id(service_id)
    if not service or service.get("active") is False:
        return error_response("Service not found.", status_code=404, code="not_found")
    tenant_id = str(service.get("tenant_id") or "")
    requested_fulfiller = str(body.get("fulfiller_id") or "").strip() or None

    now = int(time.time())
    duration = max(1, int(service.get("duration_minutes") or 60))
    start_epoch = _iso_to_epoch(slot_start)
    if start_epoch is None:
        return error_response("slot_start must be an ISO-8601 timestamp.", code="invalid_slot_start")

    tenant_availability = availability_repo.get(tenant_id, "default") or {}
    fulfillers = fulfillers_repo.list_for_tenant(tenant_id)
    exceptions = exceptions_repo.list_for_tenant(tenant_id)
    appointments = appointments_repo.list_for_tenant(tenant_id)

    # Re-validate the slot against live availability (advisory); the lock is the real guard.
    open_slots = available_slots(
        service, tenant_availability, fulfillers, exceptions, appointments,
        now_epoch=now, range_start_epoch=start_epoch, range_end_epoch=start_epoch + duration * 60,
        fulfiller_id=requested_fulfiller,
    )
    match = next((s for s in open_slots if s["start"] == slot_start), None)
    if not match:
        return error_response("That slot is no longer available.", status_code=409, code="slot_unavailable")
    fulfiller_id = requested_fulfiller or match.get("fulfiller_id")

    hold_expires_at = now + HOLD_MINUTES * 60
    appointment_id = f"appt_{uuid.uuid4().hex[:12]}"
    manage_token = secrets.token_urlsafe(24)

    try:
        claimed = slot_locks_repo.claim(
            tenant_id, fulfiller_id, slot_start,
            appointment_id=appointment_id, hold_expires_at=hold_expires_at, now=now,
        )
    except RepositoryError as exc:
        return error_response(str(exc), status_code=502, code="lock_failed")
    if not claimed:
        return error_response("That slot was just taken.", status_code=409, code="slot_taken")

    appointment = reserved_appointment(
        service, tenant_id=tenant_id, appointment_id=appointment_id, slot_start_iso=slot_start,
        tz_name=str(tenant_availability.get("timezone") or "UTC"), fulfiller_id=fulfiller_id,
        customer=customer, manage_token=manage_token, hold_expires_at=hold_expires_at, now_epoch=now,
    )
    if fulfiller_id:
        fulfiller_doc = next((f for f in fulfillers if f.get("fulfiller_id") == fulfiller_id), None)
        if fulfiller_doc:
            appointment["rule_snapshot"] = compensation_snapshot(service, fulfiller_doc)
    try:
        validate_appointment(appointment)
        appointments_repo.put(appointment)
    except (DocumentValidationError, RepositoryError) as exc:
        slot_locks_repo.release(tenant_id, fulfiller_id, slot_start)
        return error_response(str(exc), code="reserve_failed")

    return json_response({
        "appointment": _public_appointment(appointment),
        "manage_token": manage_token,
        "hold_expires_at": hold_expires_at,
        "requires_payment": requires_payment(appointment),
    }, status_code=201)


def checkout_route(event, appointments_repo, *, stripe_repo, tenant_repo, notifications_repo, secret_cipher, opener, billing_config_loader):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    appointment_id = str(body.get("appointment_id") or "").strip()
    manage_token = str(body.get("manage_token") or "").strip()
    if not appointment_id:
        return error_response("appointment_id is required.", code="missing_appointment_id")

    appointment = appointments_repo.find_by_id(appointment_id)
    if not appointment:
        return error_response("Appointment not found.", status_code=404, code="not_found")
    if str(appointment.get("customer_manage_token") or "") != manage_token or not manage_token:
        return error_response("Invalid manage token.", status_code=403, code="forbidden")
    if appointment.get("status") != "reserved":
        return error_response("Appointment is not awaiting checkout.", status_code=409, code="not_reservable")

    tenant_id = str(appointment.get("tenant_id") or "")
    now = int(time.time())

    # Free / lead-gen booking: confirm immediately, no Stripe.
    if not requires_payment(appointment):
        confirmed = {**appointment, "status": "booked", "updated_at": now}
        confirmed.pop("hold_expires_at", None)
        appointments_repo.put(confirmed)
        _emit_booked_notification(notifications_repo or (notifications_repository() if os.environ.get("NOTIFICATIONS_TABLE") else None), confirmed, tenant_id, now)
        _sync_calendar(appointments_repo, confirmed, "upsert")
        return json_response({"appointment": _public_appointment(confirmed), "status": "booked", "requires_payment": False})

    success_url = str(body.get("success_url") or "").strip()
    cancel_url = str(body.get("cancel_url") or "").strip()
    if not success_url or not cancel_url:
        return error_response("success_url and cancel_url are required.", code="missing_redirect_url")

    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    mode = "live" if os.environ.get("ENVIRONMENT") == "prod" else "test"

    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

    tenant_plan = normalize_tier_id((tenant_repo.get(tenant_id, tenant_id) or {}).get("tier_id"))
    price = appointment.get("price") or {}
    fee = calculate_price(
        tenant_keyed_amount=int(price.get("unit_amount") or 0),
        currency=str(price.get("currency") or "usd"),
        product_type=SERVICE_FEE_PRODUCT_TYPE,
        tenant_plan=tenant_plan,
        billing_config=cached_billing_config(billing_config_loader),
    )
    platform_fee = int(fee.get("breakdown", {}).get("platform_fee") or 0) if stripe_account else 0

    payload = build_booking_checkout_payload(
        appointment, tenant_id, success_url=success_url, cancel_url=cancel_url,
        platform_fee=platform_fee, tenant_plan=tenant_plan,
    )
    try:
        from handlers.checkout import create_stripe_checkout_session

        session = create_stripe_checkout_session(payload, api_key=api_key, stripe_account=stripe_account, opener=opener)
    except Exception as exc:  # noqa: BLE001
        return error_response(str(exc), status_code=502, code="checkout_error")
    checkout_url = session.get("url")
    if not checkout_url:
        return error_response("Stripe did not return a checkout URL.", status_code=502, code="checkout_error")
    return json_response({"checkout_url": checkout_url, "appointment_id": appointment_id, "requires_payment": True})


RESCHEDULABLE_STATUSES = {"reserved", "booked", "paid"}


def _authorized_appointment(appointments_repo, appointment_id, manage_token):
    appointment = appointments_repo.find_by_id(appointment_id) if appointment_id else None
    if not appointment:
        return None, error_response("Appointment not found.", status_code=404, code="not_found")
    if not manage_token or str(appointment.get("customer_manage_token") or "") != manage_token:
        return None, error_response("Invalid manage token.", status_code=403, code="forbidden")
    return appointment, None


def manage_view_route(event, appointments_repo):
    params = query_params(event)
    appointment, err = _authorized_appointment(appointments_repo, str(params.get("appointment_id") or "").strip(), str(params.get("manage_token") or "").strip())
    if err:
        return err
    return json_response({
        "appointment": _public_appointment(appointment),
        "can_cancel": appointment.get("status") not in {"completed", "canceled", "no_show"},
        "can_reschedule": appointment.get("status") in RESCHEDULABLE_STATUSES,
    })


def manage_cancel_route(event, appointments_repo, slot_locks_repo):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")
    appointment, err = _authorized_appointment(appointments_repo, str(body.get("appointment_id") or "").strip(), str(body.get("manage_token") or "").strip())
    if err:
        return err
    try:
        canceled = transition_appointment(appointment, "cancel", now_epoch=int(time.time()))
    except AppointmentTransitionError as exc:
        return error_response(str(exc), status_code=409, code="invalid_transition")
    appointments_repo.put(canceled)
    _release_lock(slot_locks_repo, canceled)
    _sync_calendar(appointments_repo, canceled, "delete")
    return json_response({"appointment": _public_appointment(canceled), "status": "canceled"})


def manage_reschedule_route(event, repos, slot_locks_repo):
    services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo = repos
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    appointment, err = _authorized_appointment(appointments_repo, str(body.get("appointment_id") or "").strip(), str(body.get("manage_token") or "").strip())
    if err:
        return err
    if appointment.get("status") not in RESCHEDULABLE_STATUSES:
        return error_response("This appointment can no longer be rescheduled.", status_code=409, code="not_reschedulable")
    new_slot = str(body.get("slot_start") or "").strip()
    if not new_slot:
        return error_response("slot_start is required.", code="missing_slot_start")

    tenant_id = str(appointment.get("tenant_id") or "")
    service = services_repo.find_by_id(str(appointment.get("service_id") or ""))
    if not service:
        return error_response("Service not found.", status_code=404, code="not_found")
    now = int(time.time())
    duration = max(1, int(service.get("duration_minutes") or 60))
    start_epoch = _iso_to_epoch(new_slot)
    if start_epoch is None:
        return error_response("slot_start must be an ISO-8601 timestamp.", code="invalid_slot_start")

    fulfiller_id = appointment.get("assigned_fulfiller_id")
    open_slots = available_slots(
        service, availability_repo.get(tenant_id, "default") or {}, fulfillers_repo.list_for_tenant(tenant_id),
        exceptions_repo.list_for_tenant(tenant_id), appointments_repo.list_for_tenant(tenant_id),
        now_epoch=now, range_start_epoch=start_epoch, range_end_epoch=start_epoch + duration * 60, fulfiller_id=fulfiller_id,
    )
    if not any(s["start"] == new_slot for s in open_slots):
        return error_response("That slot is no longer available.", status_code=409, code="slot_unavailable")

    try:
        claimed = slot_locks_repo.claim(tenant_id, fulfiller_id, new_slot, appointment_id=appointment["appointment_id"], hold_expires_at=now + HOLD_MINUTES * 60, now=now)
    except RepositoryError as exc:
        return error_response(str(exc), status_code=502, code="lock_failed")
    if not claimed:
        return error_response("That slot was just taken.", status_code=409, code="slot_taken")

    old_start = appointment.get("starts_at")
    updated = {**appointment, "starts_at": new_slot, "ends_at": slot_end_iso(new_slot, duration), "updated_at": now}
    appointments_repo.put(updated)
    if old_start and old_start != new_slot:
        slot_locks_repo.release(tenant_id, fulfiller_id, old_start)
    _sync_calendar(appointments_repo, updated, "upsert")
    return json_response({"appointment": _public_appointment(updated), "status": "rescheduled"})


def _release_lock(slot_locks_repo, appointment):
    try:
        slot_locks_repo.release(str(appointment.get("tenant_id") or ""), appointment.get("assigned_fulfiller_id"), appointment.get("starts_at"))
    except Exception:  # noqa: BLE001 - lock release is best-effort
        pass


def build_booking_checkout_payload(appointment, tenant_id, *, success_url, cancel_url, platform_fee, tenant_plan):
    price = appointment.get("price") or {}
    name = appointment.get("service_name") or "Service booking"
    payload = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][price_data][currency]": str(price.get("currency") or "usd"),
        "line_items[0][price_data][unit_amount]": str(int(price.get("unit_amount") or 0)),
        "line_items[0][price_data][product_data][name]": name,
        "line_items[0][quantity]": "1",
        "metadata[tenant_id]": tenant_id,
        "metadata[appointment_id]": appointment.get("appointment_id") or "",
        "metadata[service_id]": appointment.get("service_id") or "",
        "metadata[product_name]": name,
        "metadata[product_type]": SERVICE_FEE_PRODUCT_TYPE,
        "metadata[tenant_plan]": tenant_plan,
    }
    email = (appointment.get("customer") or {}).get("email")
    if email:
        payload["customer_email"] = email
    if platform_fee > 0:
        payload["payment_intent_data[application_fee_amount]"] = str(int(platform_fee))
    return payload


def _emit_booked_notification(notifications_repo, appointment, tenant_id, now):
    if not notifications_repo:
        return
    customer = appointment.get("customer") or {}
    who = customer.get("name") or customer.get("email") or "A customer"
    service = appointment.get("service_name") or appointment.get("service_id") or "a service"
    try:
        notifications_repo.put({
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
        })
    except Exception:  # noqa: BLE001 - notification must not fail the booking
        pass


def _public_appointment(appointment):
    return {
        key: appointment.get(key)
        for key in ("appointment_id", "service_id", "service_name", "starts_at", "ends_at",
                    "timezone", "status", "payment_status", "price", "assigned_fulfiller_id")
    }


def _iso_to_epoch(value):
    from stripe_link.domain.booking import _parse_iso

    try:
        return int(_parse_iso(value).timestamp())
    except (ValueError, TypeError):
        return None


def _epoch_to_iso(epoch):
    import datetime

    return datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sync_calendar(appointments_repo, appointment, action):
    """Best-effort push to the tenant's calendar; persist the returned event links if changed."""
    events = sync_appointment_event(appointment, action=action)
    if events is not None:
        appointment["external_calendar_events"] = events
        try:
            appointments_repo.put(appointment)
        except RepositoryError:
            pass


def booking_page_route(event, services_repo):
    service_id = path_params(event).get("service")
    service = services_repo.find_by_id(service_id) if service_id else None
    if not service or service.get("active") is False:
        return _html_response("<!doctype html><meta charset=utf-8><title>Not available</title><p style=\"font-family:sans-serif;padding:2rem\">This service is not available for booking.</p>", status_code=404)
    return _html_response(render_booking_page(service))


def _html_response(html: str, status_code: int = 200):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": html,
    }


def availability_route(event, services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo):
    service_id = path_params(event).get("service_id")
    if not service_id:
        return error_response("service_id is required.", code="missing_service_id")
    service = services_repo.find_by_id(service_id)
    if not service or service.get("active") is False:
        return error_response("Service not found.", status_code=404, code="not_found")

    tenant_id = str(service.get("tenant_id") or "")
    params = query_params(event)
    now = int(time.time())
    range_start = _epoch(params.get("from"), default=now)
    range_end = _epoch(params.get("to"), default=now + DEFAULT_WINDOW_DAYS * 86400)
    fulfiller_id = str(params.get("fulfiller_id") or "").strip() or None

    tenant_availability = availability_repo.get(tenant_id, "default") or {}
    fulfillers = fulfillers_repo.list_for_tenant(tenant_id)
    exceptions = exceptions_repo.list_for_tenant(tenant_id)
    appointments = appointments_repo.list_for_tenant(tenant_id)
    external_busy = tenant_busy_intervals(tenant_id, _epoch_to_iso(range_start), _epoch_to_iso(range_end))

    slots = available_slots(
        service,
        tenant_availability,
        fulfillers,
        exceptions,
        appointments,
        now_epoch=now,
        range_start_epoch=range_start,
        range_end_epoch=range_end,
        fulfiller_id=fulfiller_id,
        external_busy=external_busy,
    )
    return json_response({
        "service_id": service_id,
        "timezone": tenant_availability.get("timezone") or "UTC",
        "duration_minutes": int(service.get("duration_minutes") or 60),
        "slots": slots,
        "count": len(slots),
    })


def _epoch(value, *, default: int) -> int:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else default
