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
from stripe_link.repositories.documents import RepositoryError, appointments_repository
from stripe_link.sender_identity import sending_identity
from stripe_link.sms import resolve_origination, send_sms


def handler(event, context, *, appointments_repo=None, sms_send=None, now_fn=None,
            origination_configured=None, sites_repo=None, pages_repo=None, profiles_repo=None):
    # No origination number yet (10DLC pending / secret unset) → do nothing rather than burn
    # retry attempts and prematurely mark real reminders failed before delivery is possible.
    # The identity is read from Secrets Manager at runtime, so this flips on with no redeploy.
    if origination_configured is None:
        origination_configured = bool(resolve_origination()[0])
    if not origination_configured:
        return {"scanned": 0, "sent": 0, "failed": 0, "skipped": "sms_not_configured"}

    # Live-only sweep: never send real reminders for test-mode appointments (the mode-scoped scan returns
    # only live appointments; plans/STRIPE_MODE_DECOUPLING.md).
    appointments_repo = appointments_repo or appointments_repository(mode="live")
    sms_send = sms_send or send_sms
    now = int((now_fn or time.time)())

    appointments = appointments_repo.scan_type()
    # Keyed by (tenant, PAGE). A reminder text names the business the appointment is WITH, and a tenant can
    # run several; the booking records the page it was taken on, which names the Site
    # (plans/SITE_AS_BUSINESS_IDENTITY.md §4).
    business_names: dict[tuple[str, str], str] = {}
    scanned = len(appointments)
    sent = 0
    failed = 0

    for appointment in appointments:
        due = due_reminders(appointment, now=now)
        if not due:
            continue
        tenant_id = str(appointment.get("tenant_id") or "")
        page_id = str(appointment.get("page_id") or "")
        if (tenant_id, page_id) not in business_names:
            # This read `TenantProfile.business_name`, which is empty on every tenant and in every
            # environment -- so every reminder text ever sent named no business at all, and the recipient
            # got an unsigned message about an appointment.
            business_names[(tenant_id, page_id)] = sending_identity(
                tenant_id, page_id=page_id, mode="live", profiles_repo=profiles_repo,
                sites_repo=sites_repo, pages_repo=pages_repo)["business_name"]
        phone = str((appointment.get("customer") or {}).get("phone") or "").strip()

        current = appointment
        for reminder in due:
            text = reminder_sms_text(current, business_name=business_names[(tenant_id, page_id)])
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
