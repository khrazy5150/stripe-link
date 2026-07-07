"""Booking domain — build a reserved appointment from a chosen slot (pure, no I/O).

The reserved appointment holds the slot until ``hold_expires_at`` and carries a server-computed
price (the caller never trusts a client amount) and an opaque ``customer_manage_token`` for
self-serve cancel/reschedule.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

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
    price = service.get("price") or {}
    appointment: dict[str, Any] = {
        "schema_version": APPOINTMENT_SCHEMA_VERSION,
        "document_type": "appointment",
        "tenant_id": str(tenant_id),
        "appointment_id": str(appointment_id),
        "service_id": str(service.get("service_id") or ""),
        "service_name": str(service.get("name") or ""),
        "starts_at": _iso(start),
        "ends_at": _iso(end),
        "timezone": tz_name or "UTC",
        "status": "reserved",
        "payment_status": "unpaid",
        "customer": {
            key: value
            for key, value in {
                "name": customer.get("name"),
                "email": customer.get("email"),
                "phone": customer.get("phone"),
            }.items()
            if value
        },
        "price": {
            "currency": str(price.get("currency") or "usd").lower(),
            "unit_amount": int(price.get("unit_amount") or 0),
        },
        "customer_manage_token": str(manage_token),
        "hold_expires_at": int(hold_expires_at),
        "created_at": int(now_epoch),
        "updated_at": int(now_epoch),
    }
    if fulfiller_id:
        appointment["assigned_fulfiller_id"] = str(fulfiller_id)
    return appointment


def requires_payment(appointment: dict[str, Any]) -> bool:
    return int((appointment.get("price") or {}).get("unit_amount") or 0) > 0


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
