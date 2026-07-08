"""Scheduled sweep: deliver due appointment SMS reminders.

Runs on an EventBridge schedule (~every 15 minutes). Scans appointments, sends any
reminder that has come due, and stamps the outcome back onto the appointment's
``reminders[]`` for idempotency. Best-effort per reminder — one failure never blocks the
rest, and transient failures are retried on the next sweep (up to ``MAX_SEND_ATTEMPTS``).

This is the sweep-based delivery model (simple, self-healing, fully testable against a
fake). A per-booking EventBridge Scheduler one-shot is a future precision upgrade that
reuses the same ``domain/reminders.py`` planning — see plans/TODO.md.
"""
import time

from stripe_link.domain.reminders import FAILED, SENT, due_reminders, mark_reminder, reminder_sms_text
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    tenant_profiles_repository,
)
from stripe_link.sms import send_sms


def handler(event, context, *, appointments_repo=None, tenant_repo=None, sms_send=None, now_fn=None):
    appointments_repo = appointments_repo or appointments_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    sms_send = sms_send or send_sms
    now = int((now_fn or time.time)())

    appointments = appointments_repo.scan_type()
    business_names: dict[str, str] = {}
    scanned = len(appointments)
    sent = 0
    failed = 0

    for appointment in appointments:
        due = due_reminders(appointment, now=now)
        if not due:
            continue
        tenant_id = str(appointment.get("tenant_id") or "")
        if tenant_id not in business_names:
            profile = tenant_repo.get(tenant_id, tenant_id) or {}
            business_names[tenant_id] = str(profile.get("business_name") or "")
        phone = str((appointment.get("customer") or {}).get("phone") or "").strip()

        current = appointment
        for reminder in due:
            text = reminder_sms_text(current, business_name=business_names[tenant_id])
            try:
                result = sms_send(to=phone, body=text)
                message_id = result.get("MessageId") if isinstance(result, dict) else None
                current = {**current, "reminders": mark_reminder(current, reminder, status=SENT, now=now, message_id=message_id)}
                sent += 1
            except Exception as exc:  # noqa: BLE001 - one bad send must not stop the sweep
                current = {**current, "reminders": mark_reminder(current, reminder, status=FAILED, now=now, error=str(exc))}
                failed += 1
        try:
            appointments_repo.put(current)
        except RepositoryError:
            pass

    return {"scanned": scanned, "sent": sent, "failed": failed}
