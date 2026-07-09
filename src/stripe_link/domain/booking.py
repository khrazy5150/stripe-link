"""Booking domain — build a reserved appointment from a chosen slot (pure, no I/O).

The reserved appointment holds the slot until ``hold_expires_at`` and carries a server-computed
price (the caller never trusts a client amount) and an opaque ``customer_manage_token`` for
self-serve cancel/reschedule.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from stripe_link.domain.service_pricing import price_tenant_keyed_amount, resolve_service_price, service_booking_flow

APPOINTMENT_SCHEMA_VERSION = "2026-05-29"


def _parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def reserved_appointment(
    service: dict[str, Any],
    *,
    tenant_id: str,
    appointment_id: str,
    slot_start_iso: str,
    tz_name: str,
    fulfiller_id: str | None,
    customer: dict[str, Any],
    manage_token: str,
    hold_expires_at: int,
    now_epoch: int,
) -> dict[str, Any]:
    duration = max(1, int(service.get("duration_minutes") or 60))
    start = _parse_iso(slot_start_iso)
    end = start + timedelta(minutes=duration)
    service_line = service_line_from(service)
    appointment: dict[str, Any] = {
        "schema_version": APPOINTMENT_SCHEMA_VERSION,
        "document_type": "appointment",
        "tenant_id": str(tenant_id),
        "appointment_id": str(appointment_id),
        # services[] is the single canonical shape; a single service is a one-element array.
        "services": [service_line],
        "duration_minutes": int(service_line.get("duration_minutes") or duration),
        "starts_at": _iso(start),
        "ends_at": _iso(end),
        "timezone": tz_name or "UTC",
        "status": "reserved",
        "payment_status": "unpaid",
        "booking_flow": service_booking_flow(service),
        "source": "booking_page",
        "customer": {
            key: value
            for key, value in {
                "name": customer.get("name"),
                "email": customer.get("email"),
                "phone": customer.get("phone"),
            }.items()
            if value
        },
        "customer_manage_token": str(manage_token),
        "hold_expires_at": int(hold_expires_at),
        "created_at": int(now_epoch),
        "updated_at": int(now_epoch),
    }
    if fulfiller_id:
        appointment["assigned_fulfiller_id"] = str(fulfiller_id)
    return appointment


def service_line_from(service: dict[str, Any]) -> dict[str, Any]:
    """Build a single appointment.services[] line from a service document. The line carries its own
    price_id, duration, display name, and the resolved Price primitive (net-guaranteed aware)."""
    duration = max(1, int(service.get("duration_minutes") or 60))
    resolved = resolve_service_price(service) or {}
    tenant_keyed = price_tenant_keyed_amount(resolved)
    price_id = str(resolved.get("price_id") or f"svcprice_{service.get('service_id') or 'default'}")
    line_price = {
        "currency": str(resolved.get("currency") or "usd").lower(),
        "unit_amount": tenant_keyed,
        "tenant_keyed_amount": tenant_keyed,
        "fee_handling": str(resolved.get("fee_handling") or "standard"),
        "pricing_model": str(resolved.get("pricing_model") or "one_time"),
        "context": str(resolved.get("context") or "standard"),
        "price_id": price_id,
    }
    return {
        "service_id": str(service.get("service_id") or ""),
        "service_name": str(service.get("name") or ""),
        "price_id": price_id,
        "duration_minutes": duration,
        "price": line_price,
    }


def service_lines(appointment: dict[str, Any]) -> list[dict[str, Any]]:
    lines = appointment.get("services")
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def primary_service_line(appointment: dict[str, Any]) -> dict[str, Any]:
    """The representative line (services[0]); readers use this instead of a scalar service_id."""
    lines = service_lines(appointment)
    return lines[0] if lines else {}


def appointment_service_id(appointment: dict[str, Any]) -> str:
    return str(primary_service_line(appointment).get("service_id") or "")


def appointment_service_name(appointment: dict[str, Any]) -> str:
    return str(primary_service_line(appointment).get("service_name") or "")


def appointment_price(appointment: dict[str, Any]) -> dict[str, Any]:
    return primary_service_line(appointment).get("price") or {}


def appointment_total_amount(appointment: dict[str, Any]) -> int:
    return sum(int((line.get("price") or {}).get("unit_amount") or 0) for line in service_lines(appointment))


def appointment_duration_minutes(appointment: dict[str, Any]) -> int:
    """The visit duration is the sum of the service lines' durations (single fulfiller ⇒ sequential)."""
    return sum(int(line.get("duration_minutes") or 0) for line in service_lines(appointment))


def group_purchased_service_lines(
    purchased_lines: list[dict[str, Any]], service_booking_mode: str
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split a purchase's service lines into (scheduled_groups, no_booking_lines). single_visit puts
    all scheduled lines in one group (one appointment); separate_visits gives each its own group."""
    scheduled, no_booking = [], []
    for line in purchased_lines or []:
        if str(line.get("fulfillment_mode") or "scheduled") == "no_booking":
            no_booking.append(line)
        else:
            scheduled.append(line)
    if str(service_booking_mode or "single_visit") == "separate_visits":
        groups = [[line] for line in scheduled]
    else:
        groups = [scheduled] if scheduled else []
    return groups, no_booking


def appointment_line_from_purchase(purchased_line: dict[str, Any], currency: str) -> dict[str, Any]:
    """Turn a purchased service line (from checkout metadata) into an appointment.services[] line."""
    service_id = str(purchased_line.get("service_id") or "")
    price_id = str(purchased_line.get("price_id") or "") or f"svcprice_{service_id or 'default'}"
    amount = int(purchased_line.get("unit_amount") or 0)
    return {
        "service_id": service_id,
        "service_name": str(purchased_line.get("service_name") or "Service"),
        "price_id": price_id,
        # The real slot duration is applied from the service at schedule time; carry a sensible default.
        "duration_minutes": int(purchased_line.get("duration_minutes") or 0) or 60,
        "price": {"currency": currency, "unit_amount": amount, "price_id": price_id},
    }


def no_booking_invoice_line(purchased_line: dict[str, Any], currency: str, *, rule_snapshot: dict | None = None) -> dict[str, Any]:
    """Turn a no_booking service line into an invoice line item: fulfilled without an appointment,
    carrying fulfiller_id + rule_snapshot for payout when a fulfiller is assigned, else tenant revenue."""
    line = {
        "type": "service",
        "service_id": str(purchased_line.get("service_id") or ""),
        "description": str(purchased_line.get("service_name") or "Service"),
        "price_id": str(purchased_line.get("price_id") or ""),
        "quantity": int(purchased_line.get("quantity") or 1),
        "unit_amount": int(purchased_line.get("unit_amount") or 0),
        "currency": currency,
        "fulfillment": "no_booking",
        "fulfillment_status": "fulfilled",
    }
    fulfiller_id = str(purchased_line.get("default_fulfiller_id") or "")
    if fulfiller_id:
        line["fulfiller_id"] = fulfiller_id
        if rule_snapshot:
            line["rule_snapshot"] = rule_snapshot
    return line


def requires_payment(appointment: dict[str, Any]) -> bool:
    return appointment_total_amount(appointment) > 0


def slot_end_iso(slot_start_iso: str, duration_minutes: int) -> str:
    return _iso(_parse_iso(slot_start_iso) + timedelta(minutes=max(1, int(duration_minutes))))


def compensation_snapshot(service: dict[str, Any], fulfiller: dict[str, Any]) -> dict[str, Any]:
    """Freeze the fulfiller's effective compensation for this service at booking time, so later
    payout reporting uses what was true then. A service-level allowed_fulfillers override wins
    over the fulfiller's default."""
    fulfiller = fulfiller or {}
    base = fulfiller.get("compensation") or {}
    fulfiller_id = str(fulfiller.get("fulfiller_id") or "")
    snapshot = {
        "fulfiller_id": fulfiller_id,
        "type": base.get("type") or "flat_fee",
        "amount": float(base.get("amount") or 0),
        "tips_to_fulfiller": base.get("tips_to_fulfiller", True),
        "source": "fulfiller_default",
    }
    for entry in service.get("allowed_fulfillers") or []:
        if str(entry.get("fulfiller_id")) != fulfiller_id:
            continue
        if "tips_to_fulfiller" in entry:
            snapshot["tips_to_fulfiller"] = bool(entry.get("tips_to_fulfiller"))
        override = entry.get("compensation_override") or {}
        if override.get("type") in {"flat_fee", "percent"}:
            snapshot["type"] = override["type"]
            snapshot["amount"] = float(override.get("amount") or 0)
            snapshot["source"] = "service_override"
        break
    return snapshot
