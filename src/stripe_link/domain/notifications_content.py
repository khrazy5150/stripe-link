"""Delegate-facing notification rendering (pure -- no I/O).

When a booking is assigned to a staff person (a "delegate"), we email them the appointment
details. Kept pure so it is trivially testable; the handler resolves the recipient and sends.
"""

from html import escape

from stripe_link.domain.email_layout import button, paragraph, render_email, rows_table
from typing import Any

from stripe_link.domain.booking import appointment_service_name


def _when(appointment: dict[str, Any]) -> str:
    starts = str(appointment.get("starts_at") or "").strip()
    tz = str(appointment.get("timezone") or "").strip()
    return f"{starts}{(' ' + tz) if tz else ''}" if starts else "(time to be confirmed)"


def delegate_booking_email(
    appointment: dict[str, Any],
    service: dict[str, Any] | None = None,
    fulfiller: dict[str, Any] | None = None,
    *,
    business_name: str = "",
    manage_url: str = "",
    calendar_written: bool | None = None,
    change: str = "booked",
) -> dict[str, str]:
    """Render the delegate email. `change` is one of booked/rescheduled/canceled;
    `calendar_written` (True/False/None) drives the calendar-added-or-not line."""
    business = str(business_name or "").strip()
    fulfiller_name = str((fulfiller or {}).get("display_name") or (fulfiller or {}).get("first_name") or "there").strip() or "there"
    service_name = str((service or {}).get("name") or appointment_service_name(appointment) or "a service").strip()
    customer = appointment.get("customer") or {}
    customer_name = str(customer.get("name") or customer.get("email") or "A customer").strip()
    when = _when(appointment)

    verb = {"booked": "New booking", "rescheduled": "Booking rescheduled", "canceled": "Booking canceled"}.get(change, "Booking update")
    subject = f"{verb}: {service_name} — {when}" + (f" ({business})" if business else "")

    lines = [
        f"Hi {fulfiller_name},",
        "",
        {"booked": f"You have a new booking for {service_name}.",
         "rescheduled": f"A booking for {service_name} was rescheduled.",
         "canceled": f"A booking for {service_name} was canceled."}.get(change, f"A booking for {service_name} was updated."),
        "",
        f"Service: {service_name}",
        f"When: {when}",
        f"Customer: {customer_name}",
    ]
    if customer.get("email"):
        lines.append(f"Email: {customer['email']}")
    if customer.get("phone"):
        lines.append(f"Phone: {customer['phone']}")
    if change != "canceled":
        if calendar_written is True:
            lines += ["", "This appointment has been added to your calendar."]
        elif calendar_written is False:
            lines += ["", "We could not add this to your calendar — please connect your calendar in the dashboard so future bookings sync automatically."]
    if manage_url:
        lines += ["", f"Manage: {manage_url}"]
    text = "\n".join(lines)

    detail_rows = [
        (label, value)
        for label, value in [
            ("Service", service_name),
            ("When", when),
            ("Customer", customer_name),
            ("Email", str(customer.get("email") or "")),
            ("Phone", str(customer.get("phone") or "")),
        ]
        if value
    ]
    calendar_note = ""
    if change != "canceled" and calendar_written is True:
        calendar_note = paragraph("This appointment has been added to your calendar.", muted=True)
    elif change != "canceled" and calendar_written is False:
        calendar_note = paragraph(
            "We could not add this to your calendar — connect your calendar in the dashboard so future "
            "bookings sync automatically.", muted=True)

    html = render_email(
        business_name=str(business_name or ""),
        title=verb,
        body=(
            paragraph(f"Hi {fulfiller_name}, here are the details:")
            + rows_table(detail_rows)
            + calendar_note
            + (button("View / manage this appointment", manage_url) if manage_url else "")
        ),
        preheader=verb,
    )
    return {"subject": subject, "html": html, "text": text}


def calendar_revoked_notification(tenant_id: str, connection: dict[str, Any], now: int) -> dict[str, Any]:
    """The dashboard record that a calendar connection has stopped working.

    Google does not tell us when a merchant or a delegate removes the app; we learn of it the first time
    we try to use the connection. Until 2026-11-10 that moment produced a status change and a log line
    and nothing else -- so the only way to notice was that bookings had quietly stopped appearing in a
    calendar. This notice has an action attached (reconnect, or reassign the work), which is the test a
    notification has to pass.
    """
    who = str(connection.get("display_name") or connection.get("account_email") or "A calendar")
    return {
        "schema_version": "2026-05-29",
        "document_type": "notification",
        "tenant_id": tenant_id,
        # Keyed on the connection so a repeating failure cannot repeat the alarm.
        "notification_id": f"notif_calrevoked_{connection.get('connection_id', '')}",
        "type": "calendar_revoked",
        "severity": "warning",
        "title": "A calendar connection stopped working",
        "message": (f"{who} no longer has access to Google Calendar, so bookings are not being written "
                    "to it and its busy times no longer block slots. Reconnect it, or reassign anyone "
                    "who relies on it."),
        "status": "unread",
        "sort_priority": 200,
        "related": {"connection_id": connection.get("connection_id", "")},
        "action": {"label": "Open Calendar Sync", "route": "services"},
        "created_at": int(now),
        "read_at": None,
        "archived_at": None,
    }


def calendar_revoked_email(connection: dict[str, Any], *, business_name: str = "",
                           dashboard_url: str = "") -> dict[str, str]:
    """The same news by EMAIL, because the dashboard bell is only seen by someone already looking.

    The failure this reports is invisible by construction: nothing breaks loudly, bookings simply stop
    reaching a calendar and a delegate's commitments stop blocking slots. A merchant who is not watching
    the dashboard finds out when two customers arrive at once.
    """
    who = str(connection.get("display_name") or connection.get("account_email") or "A calendar")
    body = paragraph(f"{escape(who)} no longer has access to Google Calendar.")
    body += paragraph("Until it is reconnected, bookings are not written to that calendar, and the busy "
                      "times on it no longer block slots on your booking page.", muted=True)
    body += paragraph("This usually means the account removed Junior Bay from its Google permissions.",
                      muted=True)
    if dashboard_url:
        body += button("Reconnect the calendar", dashboard_url)
    return {
        "subject": f"Action needed: {who} lost access to Google Calendar",
        "html": render_email(business_name=business_name or "Junior Bay",
                             title="A calendar connection stopped working",
                             preheader=f"{who} lost access to Google Calendar",
                             body=body),
        "text": (f"{who} no longer has access to Google Calendar.\n\n"
                 "Until it is reconnected, bookings are not written to that calendar and its busy times "
                 "no longer block slots on your booking page.\n"
                 + (f"\n{dashboard_url}\n" if dashboard_url else "")),
    }
