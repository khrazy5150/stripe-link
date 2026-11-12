"""The confirmation a CUSTOMER receives when their appointment is booked.

Pure: builds the subject and both bodies and returns them. Nothing here sends.

Separate from `notifications_content.delegate_booking_email`, which is scoped to the staff person the
work is assigned to. The two audiences want opposite things. A delegate is told who is coming and is
handed the customer's phone number; a customer already knows who they are and wants four facts — that it
is confirmed, when, where, and what they owe. So this one never prints the fulfiller's name, never prints
the other party's contact details, and leads with the time.

The time is given in the APPOINTMENT's zone, which is the business's. A massage at 8:00 AM in St. George
is 8:00 AM when you turn up; converting it to the reader's device zone would be a different, wronger
sentence for anyone who booked while travelling.

There is deliberately NO cancel/reschedule link. The routes exist (`/services/appointments/manage`) but
nothing renders a page for them, so a link here would be an invented URL. Instead the message says to
reply — Reply-To is the tenant's verified address, so that reaches a human who can act. When a manage
page exists, this is where its button goes.
"""
from __future__ import annotations

from typing import Any

from stripe_link.domain.booking import (
    appointment_duration_minutes,
    appointment_service_name,
    appointment_total_amount,
)
from stripe_link.domain.email_layout import paragraph, render_email, rows_table
from stripe_link.domain.receipts import format_money


def appointment_when(appointment: dict[str, Any]) -> str:
    """"Thursday, November 12, 2026 at 8:00 AM MST", or "" when the moment cannot be read.

    Imported lazily from the renderer for the same reason `registration_email` does it: `format_event_date`
    is the one place this codebase spells a moment in English, and it lives with the page renderer.
    """
    starts_at = str(appointment.get("starts_at") or "").strip()
    if not starts_at:
        return ""
    from datetime import datetime

    from ..runtime.html import format_event_date

    try:
        moment = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    return format_event_date(int(moment.timestamp()), str(appointment.get("timezone") or "UTC"),
                             with_time=True)


def _place(organization: dict[str, Any] | None) -> str:
    """The street address, as a person would write it on an envelope. Empty when the Site has none."""
    address = (organization or {}).get("address") or {}
    if not isinstance(address, dict):
        return ""
    return ", ".join(
        part for part in (str(address.get(field) or "").strip()
                          for field in ("street", "locality", "region", "postal_code"))
        if part
    )


def _payment_line(appointment: dict[str, Any]) -> str:
    """What the customer still owes, said once and plainly.

    Three real cases, and the silence in the fourth is deliberate: a free booking has nothing to say about
    money, and a sentence about $0.00 only makes the reader wonder whether they have been charged.
    """
    amount = int(appointment_total_amount(appointment) or 0)
    if amount <= 0:
        return ""
    currency = str(((appointment.get("services") or [{}])[0].get("price") or {}).get("currency") or "usd")
    money = format_money(amount, currency)
    if str(appointment.get("payment_status") or "") == "paid":
        return f"Paid in full — {money}."
    if str(appointment.get("booking_flow") or "") == "book_then_pay":
        return f"{money} is due for this appointment. We'll send you an invoice."
    return f"{money} is due for this appointment."


def booking_confirmation(
    appointment: dict[str, Any],
    service: dict[str, Any] | None = None,
    *,
    business_name: str = "",
    organization: dict[str, Any] | None = None,
) -> dict[str, str]:
    """`{subject, html, text}` for one confirmed appointment.

    An empty subject means there is nothing worth sending, and the caller must not send it. That happens
    when the appointment has no readable start time — a confirmation whose whole job is to say WHEN, with
    no when in it, is worse than no email: it tells the customer they are booked and leaves them unable to
    turn up.
    """
    when = appointment_when(appointment)
    if not when:
        return {"subject": "", "html": "", "text": ""}

    service_name = (str((service or {}).get("name") or "").strip()
                    or str(appointment_service_name(appointment) or "").strip()
                    or "your appointment")
    business = str(business_name or "").strip()
    customer_name = str((appointment.get("customer") or {}).get("name") or "").strip()
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"
    minutes = int(appointment_duration_minutes(appointment) or 0)
    place = _place(organization)
    payment = _payment_line(appointment)

    # The WHEN in the subject, because a phone shows the subject and nothing else. The business name comes
    # last: the customer is looking for the appointment, not for us.
    subject = f"Booking confirmed: {service_name} — {when}" + (f" ({business})" if business else "")

    rows = [
        ("Service", service_name),
        ("When", when),
        ("How long", f"{minutes} minutes" if minutes else ""),
        ("Where", place),
    ]
    rows = [(label, value) for label, value in rows if value]

    lines = [greeting, "", f"Your booking for {service_name} is confirmed.", "", f"When: {when}"]
    if minutes:
        lines.append(f"How long: {minutes} minutes")
    if place:
        lines.append(f"Where: {place}")
    if payment:
        lines += ["", payment]
    lines += ["", "Need to change or cancel? Just reply to this email."]
    if business:
        lines += ["", f"— {business}"]
    text = "\n".join(lines)

    html = render_email(
        business_name=business,
        title="Booking confirmed",
        body=(
            paragraph(f"{greeting} your booking for {service_name} is confirmed.")
            + rows_table(rows)
            + (paragraph(payment) if payment else "")
            + paragraph("Need to change or cancel? Just reply to this email.", muted=True)
        ),
        preheader=f"{service_name} — {when}",
    )
    return {"subject": subject, "html": html, "text": text}
