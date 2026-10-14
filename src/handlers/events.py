"""Scheduled events — tenant-scoped CRUD (plans/WEBINAR.md P1, P3).

Mostly `document_route`, the shared CRUD the services handler already used. The one thing it cannot do is
notice that something CHANGED, and cancelling a session is exactly that: the people who registered are
expecting to attend, and a cancellation nobody is told about is the same as not cancelling.
"""
import logging

from stripe_link.common import json_response, parse_json_body
from stripe_link.document_route import document_route
from stripe_link.domain.documents import validate_event
from stripe_link.domain.events import (
    CANCELLED,
    UPCOMING,
    next_occurrence,
    occurrence_by_id,
    occurrences,
    session_state,
)
from stripe_link.repositories.documents import RepositoryError, events_repository, leads_repository

logger = logging.getLogger(__name__)


def handler(event, context, events_repo=None, leads_repo=None, notify_fn=None, now_fn=None):
    events_repo = events_repo or events_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    previous = None
    if method in {"POST", "PUT"}:
        # Read BEFORE the write, so the save can be compared with what it replaced. Failing to read is not
        # a reason to refuse the save -- it only means this save cannot notify anyone.
        try:
            incoming = parse_json_body(event)
            previous = events_repo.get(str(incoming.get("tenant_id") or ""),
                                       str(incoming.get("event_id") or ""))
        except Exception:  # noqa: BLE001 — document_route re-parses and reports a bad body properly
            previous = None

    response = document_route(event, method, events_repo, "event", validate_event, "events",
                              id_param="event_id")

    if previous is not None and str(response.get("statusCode")) == "201":
        import time
        _announce_cancellations(previous, parse_json_body(event),
                                leads_repo or leads_repository(), notify_fn or _notify_cancelled,
                                now=int((now_fn or time.time)()))
    return response


def _announce_cancellations(previous, saved, leads_repo, notify_fn, *, now):
    """Email the registrants of any session that was just cancelled.

    Only sessions that changed TO cancelled, and only ones that had not already run: re-saving an event
    must not re-send, and telling someone a session they already attended is cancelled is worse than
    silence.

    Best-effort and synchronous. A webinar's registrant list is small enough that this is not worth a
    queue, and the alternative -- a tenant cancelling and nobody being told until a sweep ran -- is the
    failure this exists to prevent.
    """
    tenant_id = str(saved.get("tenant_id") or "")
    newly_cancelled = [
        row for row in occurrences(saved)
        if str(row.get("status") or "") == "cancelled"
        and str((occurrence_by_id(previous, row.get("occurrence_id")) or {}).get("status") or "scheduled") != "cancelled"
    ]
    if not newly_cancelled:
        return

    # Offered as the alternative, resolved once: the next sitting still open AFTER the cancellations are
    # applied, so a tenant cancelling both sittings does not have one of them offered as the replacement.
    replacement = next_occurrence(saved, now=now)

    try:
        registrants = _registrants_by_occurrence(leads_repo, tenant_id, saved.get("event_id"))
    except RepositoryError as exc:
        logger.warning("event cancelled but registrants not listed for %s: %s", tenant_id, exc)
        return

    for occurrence in newly_cancelled:
        # A session that already ran cannot be "cancelled" to anyone who was there.
        if session_state(saved, {**occurrence, "status": "scheduled"}, now=now) != UPCOMING:
            continue
        for registrant in registrants.get(str(occurrence.get("occurrence_id") or "")) or []:
            try:
                notify_fn(saved, occurrence, registrant, replacement, tenant_id)
            except Exception as exc:  # noqa: BLE001 — one bad address must not silence the rest
                logger.warning("cancellation notice failed for %s: %s", registrant.get("email"), exc)


def _registrants_by_occurrence(leads_repo, tenant_id, event_id):
    """This tenant's registrations for one event, grouped by occurrence. One tenant-scoped list filtered in
    memory -- the cost of there being no index on `occurrence_id` (plans/WEBINAR.md §10a)."""
    wanted = str(event_id or "")
    grouped: dict[str, list[dict]] = {}
    for lead in leads_repo.list_for_tenant(tenant_id):
        if str(lead.get("event_id") or "") != wanted:
            continue
        email = str((lead.get("fields") or {}).get("email") or "").strip()
        if email:
            grouped.setdefault(str(lead.get("occurrence_id") or ""), []).append(
                {"email": email, "name": str((lead.get("fields") or {}).get("name") or "")})
    return grouped


def _notify_cancelled(saved, occurrence, registrant, replacement, tenant_id):
    from stripe_link.domain.registration_email import registration_cancelled
    from stripe_link.mailer import send_email

    message = registration_cancelled(saved, occurrence, name=registrant.get("name") or "",
                                     replacement=replacement)
    if not message["subject"]:
        return
    send_email(to=registrant["email"], subject=message["subject"], html=message["html"],
               text=message["text"], tenant_id=tenant_id)


__all__ = ["handler", "CANCELLED"]
