"""Calendar domain — pure builders/parsers for the calendar sync (no I/O).

`google_event_body` turns an appointment into a Google Calendar event; `busy_intervals`
normalizes a free/busy response into {start, end} ISO windows the slot engine can subtract.
"""
from typing import Any


def google_event_body(appointment: dict[str, Any]) -> dict[str, Any]:
    customer = appointment.get("customer") or {}
    who = customer.get("name") or customer.get("email") or "Customer"
    service = appointment.get("service_name") or "Appointment"
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


def busy_intervals(freebusy_response: dict[str, Any], calendar_id: str = "primary") -> list[dict[str, str]]:
    calendar = (freebusy_response.get("calendars") or {}).get(calendar_id, {})
    return [
        {"start": entry["start"], "end": entry["end"]}
        for entry in calendar.get("busy", [])
        if entry.get("start") and entry.get("end")
    ]
