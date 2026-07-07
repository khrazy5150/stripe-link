"""Public booking API (resolve-style, like experiments_resolve / custom_domains_resolve).

Tenant is derived from the service, not an admin session. B.1 ships the availability endpoint;
resolve / reserve / checkout / manage land in later Phase B steps.
"""
import secrets
import time
import uuid

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params
from stripe_link.domain.booking import requires_payment, reserved_appointment
from stripe_link.domain.documents import DocumentValidationError, validate_appointment
from stripe_link.domain.scheduling import available_slots
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    availability_exceptions_repository,
    fulfillers_repository,
    services_repository,
    slot_locks_repository,
    tenant_availability_repository,
)

DEFAULT_WINDOW_DAYS = 14
HOLD_MINUTES = 10


def handler(
    event,
    context,
    services_repo=None,
    availability_repo=None,
    fulfillers_repo=None,
    exceptions_repo=None,
    appointments_repo=None,
    slot_locks_repo=None,
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
    if "/appointments/reserve" in path and method == "POST":
        return reserve_route(event, repos, slot_locks_repo or slot_locks_repository())
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
