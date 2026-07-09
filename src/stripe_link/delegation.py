"""Delegation side-effects for a booking: route its calendar event to the right calendar and
notify the assigned staff person. Both are best-effort — a calendar or email failure must never
break a booking. Shared by the booking handler and the Stripe webhook.
"""
from typing import Any

from stripe_link.calendar_sync import sync_appointment_event
from stripe_link.domain.booking import appointment_service_id
from stripe_link.domain.calendar_routing import delegation_status, resolve_write_connection
from stripe_link.domain.notifications_content import delegate_booking_email
from stripe_link.mailer import send_email


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


def notify_delegate(appointment, service, fulfiller, *, change, business_name="", support_email="", manage_url="", mailer_send=None):
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
        send(to=email, subject=content["subject"], html=content["html"], text=content["text"], from_name=business_name, reply_to=support_email)
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

        if fulfiller:
            profile = (tenant_repo.get(tenant_id, tenant_id) if tenant_repo else {}) or {}
            notify_delegate(
                appointment, service, fulfiller, change=change,
                business_name=str(profile.get("business_name") or ""), support_email=str(profile.get("support_email") or ""),
                mailer_send=mailer_send,
            )
    except Exception:  # noqa: BLE001 - delegation must never break a booking
        pass
    return appointment
