"""Side-effects for a booking transition: route its calendar event to the right calendar, and tell the
people who need to know — the assigned staff person, and the CUSTOMER.

All of it is best-effort — a calendar or email failure must never break a booking. Shared by the booking
handler and the Stripe webhook, which is the reason it lives here rather than in either: `apply_delegation`
is the one function every path to `status: "booked"` already calls, so a notice added here cannot be
forgotten by the next path that is written. The alternative was three call sites that must agree, which is
the shape of bug this codebase keeps producing.
"""
from typing import Any

from stripe_link.calendar_sync import sync_appointment_event
from stripe_link.domain.booking import appointment_service_id
from stripe_link.domain.calendar_routing import delegation_status, resolve_write_connection
from stripe_link.domain.booking_email import booking_confirmation
from stripe_link.domain.notifications_content import delegate_booking_email
from stripe_link.mailer import send_email
from stripe_link.sender_identity import sending_identity


def route_and_sync(appointment, *, service, fulfiller, connections, action, connections_repo=None, secret_cipher=None, google_secret=None, opener=None):
    """Write the appointment's event to the routed calendar (fulfiller override > service >
    default). Returns (external_calendar_events | None, delegation_calendar | None) where the
    delegation status is 'written'/'unavailable' only when the appointment is delegated to a
    fulfiller who names a calendar."""
    conn = resolve_write_connection(appointment, service, fulfiller, connections)
    if conn is None:
        return None, delegation_status(None, fulfiller)
    events = sync_appointment_event(
        appointment, action=action, connection=conn, connections_repo=connections_repo,
        secret_cipher=secret_cipher, google_secret=google_secret, opener=opener,
    )
    status = delegation_status(conn, fulfiller)
    if status == "written" and events is None and action != "delete":
        status = "unavailable"  # routed to their calendar but nothing was written
    return events, status


def notify_delegate(appointment, service, fulfiller, *, change, business_name="", support_email="", manage_url="", tenant_id="", mailer_send=None):
    """Email the assigned staff person their booking. Returns True if an email was sent. No-op
    when there is no assigned fulfiller or they have no email."""
    email = str((fulfiller or {}).get("email") or "").strip()
    if not fulfiller or not email:
        return False
    delegation = appointment.get("delegation_calendar")
    calendar_written = True if delegation == "written" else (False if delegation == "unavailable" else None)
    content = delegate_booking_email(
        appointment, service, fulfiller,
        business_name=business_name, manage_url=manage_url, calendar_written=calendar_written, change=change,
    )
    send = mailer_send or send_email
    try:
        send(to=email, subject=content["subject"], html=content["html"], text=content["text"],
             from_name=business_name, reply_to=support_email, tenant_id=tenant_id)
        return True
    except Exception:  # noqa: BLE001 - a delivery failure must not break the booking
        return False


def notify_customer_booked(appointment, service, *, business_name="", reply_to="", organization=None,
                           tenant_id="", mailer_send=None):
    """Email the customer that their appointment is confirmed. Returns True if an email was sent.

    No-op when the booking carries no email address. It normally does -- `reserve_route` refuses a booking
    without one -- but an appointment created any other way must not take the booking down with it.

    Until 2026-11-12 nothing sent this at all, while the booking widget's own success message read "Your
    booking is confirmed — check your email for details". The customer got a calendar invite only if the
    tenant had connected a calendar, and even then only the tenant's own; the person who had just given up
    a Saturday morning was told nothing.
    """
    email = str((appointment.get("customer") or {}).get("email") or "").strip()
    if not email:
        return False
    content = booking_confirmation(appointment, service, business_name=business_name,
                                   organization=organization)
    # An empty subject is the content module refusing to send -- see booking_confirmation. Honour it: a
    # confirmation with no time in it leaves the customer unable to turn up.
    if not content["subject"]:
        return False
    send = mailer_send or send_email
    try:
        send(to=email, subject=content["subject"], html=content["html"], text=content["text"],
             from_name=business_name, reply_to=reply_to, tenant_id=tenant_id)
        return True
    except Exception:  # noqa: BLE001 - a delivery failure must not break the booking
        return False


def apply_delegation(appointment: dict[str, Any], *, action, change, services_repo, fulfillers_repo, connections_repo, tenant_repo, appointments_repo=None, persist=True, mailer_send=None, secret_cipher=None, google_secret=None, opener=None):
    """Full delegation flow for a completed booking transition: resolve the write calendar, sync
    the event, stamp delegation_calendar, optionally persist, and email the delegate. Best-effort
    end to end — never raises. Returns the (possibly mutated) appointment."""
    try:
        tenant_id = str(appointment.get("tenant_id") or "")
        service = services_repo.find_by_id(appointment_service_id(appointment)) if services_repo else None
        fulfiller = None
        fulfiller_id = str(appointment.get("assigned_fulfiller_id") or "")
        if fulfiller_id and fulfillers_repo:
            fulfiller = fulfillers_repo.get(tenant_id, fulfiller_id)
        connections = []
        try:
            connections = list((connections_repo.list_for_tenant(tenant_id)) or []) if connections_repo else []
        except Exception:  # noqa: BLE001
            connections = []

        events, status = route_and_sync(
            appointment, service=service, fulfiller=fulfiller, connections=connections, action=action,
            connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener,
        )
        changed = False
        if events is not None:
            appointment["external_calendar_events"] = events
            changed = True
        if status is not None and appointment.get("delegation_calendar") != status:
            appointment["delegation_calendar"] = status
            changed = True
        if changed and persist and appointments_repo is not None:
            try:
                appointments_repo.put(appointment)
            except Exception:  # noqa: BLE001
                pass

        # WHO these messages are from, through the one resolver (plans/SITE_AS_BUSINESS_IDENTITY.md §4).
        # This read `TenantProfile.business_name` / `support_email` -- empty on every tenant and in every
        # environment -- so the person being assigned work was told about it by nobody in particular. A
        # booking taken through checkout records its page, which names the business; one taken any other
        # way falls back.
        #
        # Hoisted out of `if fulfiller:` on 2026-11-12, when the customer confirmation started needing the
        # same answer: a booking with nobody assigned yet still has a customer waiting to be told, and the
        # `organization` it carries is where the email gets the address to print.
        identity = sending_identity(
            tenant_id, page_id=str(appointment.get("page_id") or ""),
            mode=str(appointment.get("stripe_mode") or "live"))

        if fulfiller:
            notify_delegate(
                appointment, service, fulfiller, change=change,
                business_name=identity["business_name"], support_email=identity["reply_to"],
                tenant_id=tenant_id, mailer_send=mailer_send,
            )

        # Only on "booked". A reschedule or a cancellation deserves a customer email too, and neither is
        # written yet -- stated here rather than silently covered by a confirmation that would tell someone
        # their cancelled appointment is confirmed.
        if change == "booked":
            notify_customer_booked(
                appointment, service, business_name=identity["business_name"],
                reply_to=identity["reply_to"], organization=identity.get("organization"),
                tenant_id=tenant_id, mailer_send=mailer_send,
            )
    except Exception:  # noqa: BLE001 - delegation must never break a booking
        pass
    return appointment
