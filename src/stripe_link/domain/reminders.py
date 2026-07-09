"""Appointment SMS reminders — pure scheduling and formatting logic.

The booking lifecycle plans reminders when an appointment is confirmed; a periodic
sweep sends the ones that come due. Records live on the appointment as ``reminders[]``
for idempotency and audit, so the adapter (``sms.py``) and the sweep handler stay thin.

A reminder record::

    {"lead_minutes": 1440, "channel": "sms", "send_at": <epoch>,
     "status": "scheduled" | "sent" | "canceled" | "failed",
     "sent_at": <epoch|null>, "message_id": <str>, "attempts": <int>}
"""
from __future__ import annotations

import datetime
import re
from typing import Any

from stripe_link.domain.booking import appointment_service_name

DEFAULT_LEAD_MINUTES = [1440, 60]  # 24h and 1h before start
SMS_CHANNEL = "sms"
MAX_SEND_ATTEMPTS = 5

SCHEDULED = "scheduled"
SENT = "sent"
CANCELED = "canceled"
FAILED = "failed"

ACTIVE_STATUSES = {"booked", "paid", "checked_in"}

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def is_valid_e164(phone: Any) -> bool:
    return bool(_E164.match(str(phone or "").strip()))


def _parse_iso_epoch(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return int(parsed.timestamp())


def reminder_lead_minutes(config: dict[str, Any] | None) -> list[int]:
    """Resolve configured lead times (descending, de-duped, positive), defaulting to 24h + 1h."""
    raw = (config or {}).get("reminder_lead_minutes")
    if not isinstance(raw, list):
        return list(DEFAULT_LEAD_MINUTES)
    leads = sorted({int(m) for m in raw if isinstance(m, (int, float)) and int(m) > 0}, reverse=True)
    return leads or list(DEFAULT_LEAD_MINUTES)


def customer_opted_out(appointment: dict[str, Any]) -> bool:
    return bool((appointment.get("customer") or {}).get("sms_opted_out")) or bool(appointment.get("sms_opted_out"))


def _phone(appointment: dict[str, Any]) -> str:
    return str((appointment.get("customer") or {}).get("phone") or "").strip()


def plan_reminders(appointment: dict[str, Any], *, now: int, lead_minutes: list[int] | None = None, channel: str = SMS_CHANNEL) -> list[dict[str, Any]]:
    """Return the ``reminders[]`` list for a confirmed appointment.

    One reminder per *future* lead time is (re)scheduled; leads whose send time has already
    passed are skipped, and already sent/failed records are preserved for audit. Returns the
    existing list unchanged when the customer has no valid phone or has opted out.
    """
    existing = [dict(r) for r in (appointment.get("reminders") or []) if isinstance(r, dict)]
    start_epoch = _parse_iso_epoch(appointment.get("starts_at"))
    if start_epoch is None or not is_valid_e164(_phone(appointment)) or customer_opted_out(appointment):
        return existing

    leads = lead_minutes if lead_minutes is not None else DEFAULT_LEAD_MINUTES
    kept = [r for r in existing if r.get("status") != SCHEDULED]  # drop stale scheduled; re-plan below
    settled_leads = {int(r["lead_minutes"]) for r in kept if r.get("lead_minutes") is not None}

    planned = list(kept)
    for lead in sorted({int(m) for m in leads if int(m) > 0}, reverse=True):
        if lead in settled_leads:
            continue  # already sent/failed for this lead — don't re-remind
        send_at = start_epoch - lead * 60
        if send_at <= now:
            continue  # too late to be meaningful
        planned.append({
            "lead_minutes": lead,
            "channel": channel,
            "send_at": send_at,
            "status": SCHEDULED,
            "sent_at": None,
            "attempts": 0,
        })
    planned.sort(key=lambda r: r.get("send_at") or 0)
    return planned


def cancel_reminders(appointment: dict[str, Any]) -> list[dict[str, Any]]:
    """Mark every still-scheduled reminder canceled (used on cancel / terminal transitions)."""
    result = []
    for reminder in (appointment.get("reminders") or []):
        if isinstance(reminder, dict) and reminder.get("status") == SCHEDULED:
            result.append({**reminder, "status": CANCELED})
        elif isinstance(reminder, dict):
            result.append(reminder)
    return result


def due_reminders(appointment: dict[str, Any], *, now: int) -> list[dict[str, Any]]:
    """Reminders that should be sent now: scheduled, past their send_at, for an active
    appointment whose start is still in the future, with a valid phone and no opt-out."""
    if appointment.get("status") not in ACTIVE_STATUSES:
        return []
    start_epoch = _parse_iso_epoch(appointment.get("starts_at"))
    if start_epoch is None or start_epoch <= now:
        return []
    if not is_valid_e164(_phone(appointment)) or customer_opted_out(appointment):
        return []
    return [
        reminder
        for reminder in (appointment.get("reminders") or [])
        if isinstance(reminder, dict) and reminder.get("status") == SCHEDULED and int(reminder.get("send_at") or 0) <= now
    ]


def mark_reminder(appointment: dict[str, Any], reminder: dict[str, Any], *, status: str, now: int, message_id: str | None = None, error: str | None = None) -> list[dict[str, Any]]:
    """Return a new ``reminders[]`` list with the matching record (by lead_minutes + channel)
    updated. On a failure the record stays ``scheduled`` (so the next sweep retries) until
    ``MAX_SEND_ATTEMPTS`` is reached, then flips to ``failed``."""
    lead = reminder.get("lead_minutes")
    channel = reminder.get("channel")
    result = []
    for current in (appointment.get("reminders") or []):
        if not (isinstance(current, dict) and current.get("lead_minutes") == lead and current.get("channel") == channel):
            result.append(current)
            continue
        updated = dict(current)
        if status == SENT:
            updated["status"] = SENT
            updated["sent_at"] = now
            if message_id:
                updated["message_id"] = message_id
        elif status == FAILED:
            attempts = int(updated.get("attempts") or 0) + 1
            updated["attempts"] = attempts
            updated["status"] = FAILED if attempts >= MAX_SEND_ATTEMPTS else SCHEDULED
            if error:
                updated["error"] = str(error)[:300]
        else:
            updated["status"] = status
        result.append(updated)
    return result


def reminder_sms_text(appointment: dict[str, Any], *, business_name: str = "") -> str:
    """Compose the reminder body. Kept short (single SMS segment where possible) and always
    carries the STOP hint that US A2P 10DLC compliance expects."""
    service = appointment_service_name(appointment) or "your appointment"
    prefix = f"{str(business_name).strip()}: " if str(business_name).strip() else ""
    body = f"{prefix}Reminder — {service} {_format_when(appointment)}."
    return f"{body} Reply STOP to opt out."[:320]


def _format_when(appointment: dict[str, Any]) -> str:
    start_epoch = _parse_iso_epoch(appointment.get("starts_at"))
    if start_epoch is None:
        return "is coming up"
    tz_name = str(appointment.get("timezone") or "UTC")
    try:
        from zoneinfo import ZoneInfo

        moment = datetime.datetime.fromtimestamp(start_epoch, tz=ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001 - missing tz data falls back to UTC
        moment = datetime.datetime.fromtimestamp(start_epoch, tz=datetime.timezone.utc)
    hour = moment.strftime("%I").lstrip("0") or "12"
    return f"on {moment.strftime('%a %b')} {moment.day} at {hour}:{moment.strftime('%M %p %Z')}"
