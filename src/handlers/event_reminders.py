"""Scheduled sweep: email registrants before their session (plans/WEBINAR.md P2).

**Driven by EVENTS, not by leads.** Registrations are leads keyed by TENANT with no index on
`occurrence_id` (plans/WEBINAR.md §10a), so finding "everyone registered for Wednesday" by scanning the
lead table would mean reading every tenant's entire lead history every fifteen minutes — a high-volume PII
table, swept for the benefit of the handful of sessions actually starting soon.

Inverting it costs nothing and avoids the missing index entirely: the events table is small, a sweep reads
it, and only a tenant with a session inside the reminder window has their leads listed at all.

A SEPARATE handler from `handlers/reminders.py` on purpose. That one is appointment SMS and returns early
when no origination number is configured — folding webinar email into it would have made these reminders
silently depend on a 10DLC registration they have nothing to do with.

Best-effort per session: one failure never blocks the rest, and because what is due is DERIVED from
`starts_at` rather than planned and stored, a sweep that fails simply sends late on the next run.
"""
import logging
import time

from stripe_link.domain.events import (
    due_reminder_leads,
    occurrences,
    record_reminder,
    starts_at as occurrence_starts_at,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    events_repository,
    leads_repository,
)

logger = logging.getLogger(__name__)

# A session cannot be reminded about more than a day ahead, so anything further out is skipped without
# listing a single lead.
HORIZON_SECONDS = 86_400 + 3_600


def handler(event, context, *, events_repo=None, leads_repo=None, send_fn=None, now_fn=None):
    events_repo = events_repo or events_repository()
    leads_repo = leads_repo or leads_repository()
    send_fn = send_fn or _send_reminder
    now = int((now_fn or time.time)())

    scheduled = events_repo.scan_type()
    sent = 0
    failed = 0
    sessions = 0

    for record in scheduled:
        tenant_id = str(record.get("tenant_id") or "")
        if not tenant_id:
            continue
        registrants = None          # listed lazily: most events have nothing due
        changed = False

        for occurrence in occurrences(record):
            start = occurrence_starts_at(occurrence)
            if not start or start - now > HORIZON_SECONDS:
                continue
            leads_due = due_reminder_leads(record, occurrence, now=now)
            if not leads_due:
                continue
            if registrants is None:
                try:
                    registrants = _registrants_for(leads_repo, tenant_id, record.get("event_id"))
                except RepositoryError as exc:
                    logger.warning("event reminders: could not list leads for %s: %s", tenant_id, exc)
                    registrants = {}
            audience = registrants.get(str(occurrence.get("occurrence_id") or "")) or []
            # Only the MOST IMMINENT notice is sent. The rest are superseded rather than queued: telling
            # someone a session starts "tomorrow" when it starts in thirty minutes is wrong, not merely
            # redundant. Recording them is what stops them firing on the next sweep.
            lead_minutes, superseded = leads_due[0], leads_due[1:]
            sessions += 1
            delivered = 0
            for registrant in audience:
                try:
                    send_fn(record, occurrence, registrant, lead_minutes, tenant_id)
                    delivered += 1
                except Exception as exc:  # noqa: BLE001 — one bad address must not stop the room
                    failed += 1
                    logger.warning("event reminder failed for %s: %s", registrant.get("email"), exc)
            sent += delivered
            # Marked even when the audience was empty: the question this answers is "has this notice gone
            # out", and for nobody it has. Leaving it unmarked would re-list the leads every fifteen
            # minutes until the session started.
            occurrence.update(record_reminder(occurrence, lead_minutes, now=now, recipients=delivered))
            for stale in superseded:
                occurrence.update(record_reminder(occurrence, stale, now=now, status="superseded"))
            changed = True

        if changed:
            try:
                events_repo.put(record)
            except RepositoryError as exc:
                # The reminders went out; only the bookkeeping failed. Logged loudly because the next
                # sweep will send them AGAIN, which is the one duplicate this design can produce.
                logger.warning("event reminders sent but not recorded for %s: %s", record.get("event_id"), exc)

    return {"events": len(scheduled), "notices": sessions, "sent": sent, "failed": failed}


def _registrants_for(leads_repo, tenant_id: str, event_id) -> dict[str, list[dict]]:
    """This tenant's registrations for one event, grouped by occurrence.

    One tenant-scoped list, filtered in memory. That is the cost of there being no index on
    `occurrence_id`, and it is only paid for a tenant with a session starting inside the horizon.
    """
    wanted = str(event_id or "")
    grouped: dict[str, list[dict]] = {}
    for lead in leads_repo.list_for_tenant(tenant_id):
        if str(lead.get("event_id") or "") != wanted:
            continue
        email = str((lead.get("fields") or {}).get("email") or "").strip()
        if not email:
            continue
        grouped.setdefault(str(lead.get("occurrence_id") or ""), []).append(
            {"email": email, "name": str((lead.get("fields") or {}).get("name") or "")}
        )
    return grouped


def _send_reminder(record, occurrence, registrant, lead_minutes, tenant_id):
    from stripe_link.domain.registration_email import registration_reminder
    from stripe_link.mailer import send_email

    message = registration_reminder(record, occurrence, lead_minutes,
                                    name=registrant.get("name") or "")
    if not message["subject"]:
        return
    send_email(to=registrant["email"], subject=message["subject"], html=message["html"],
               text=message["text"], tenant_id=tenant_id)
