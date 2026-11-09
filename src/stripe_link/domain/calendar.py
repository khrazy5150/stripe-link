"""Calendar domain — pure builders/parsers for the calendar sync (no I/O).

`google_event_body` turns an appointment into a Google Calendar event; `busy_intervals`
normalizes a free/busy response into {start, end} ISO windows the slot engine can subtract.
"""
from typing import Any

from stripe_link.domain.booking import appointment_service_name


def google_event_body(appointment: dict[str, Any]) -> dict[str, Any]:
    customer = appointment.get("customer") or {}
    who = customer.get("name") or customer.get("email") or "Customer"
    service = appointment_service_name(appointment) or "Appointment"
    lines = [f"Service: {service}", f"Customer: {who}"]
    if customer.get("email"):
        lines.append(f"Email: {customer['email']}")
    if customer.get("phone"):
        lines.append(f"Phone: {customer['phone']}")
    return {
        "summary": f"{service} — {who}",
        "description": "\n".join(lines),
        "start": {"dateTime": appointment.get("starts_at")},
        "end": {"dateTime": appointment.get("ends_at")},
        "extendedProperties": {
            "private": {
                "appointment_id": str(appointment.get("appointment_id") or ""),
                "tenant_id": str(appointment.get("tenant_id") or ""),
            }
        },
    }


def busy_intervals(freebusy_response: dict[str, Any], calendar_id="primary") -> list[dict[str, str]]:
    """Busy windows from a `freebusy.query` response, for one calendar id or several.

    `calendar_id` takes a list because bookings now live in a calendar of their own: availability has to
    subtract the merchant's real commitments AND our own appointments, which is several calendars in one
    response. Reading a single key would have quietly dropped all but one of them -- and the slot engine
    cannot tell "nothing is busy" from "we only looked at one calendar".

    The result is a plain concatenation, not a merge. Overlapping windows subtract identically, and the
    slot engine already handles overlap; merging here would only add a way to get it wrong.
    """
    ids = [calendar_id] if isinstance(calendar_id, str) else [str(c) for c in (calendar_id or [])]
    calendars = freebusy_response.get("calendars") or {}
    return [
        {"start": entry["start"], "end": entry["end"]}
        for cid in ids
        for entry in (calendars.get(cid) or {}).get("busy", [])
        if entry.get("start") and entry.get("end")
    ]
