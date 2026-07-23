"""Scheduled sweep: send due post-purchase review invites (plans/REVIEWS.md, Phase 2).

Runs on an EventBridge schedule (~every 15 min), mirroring the appointment-reminders sweep. Scans the
review_invite records, sends any step that has come due (one email per step), and marks it sent. Invites are
canceled the moment the customer reviews, so a reviewed buyer is never emailed again. Best-effort per invite —
one bad send never stops the sweep.
"""
import logging
import os
import time

from stripe_link.domain.review_invites import due_steps, invite_email, invite_sendable, mark_step_sent
from stripe_link.mailer import EmailError, send_email
from stripe_link.repositories.documents import review_invites_repository, sites_repository

logger = logging.getLogger(__name__)


def handler(event, context, *, invites_repo=None, sites_repo=None, mailer_send=None, now_fn=None):
    invites_repo = invites_repo or review_invites_repository()
    if sites_repo is None and os.environ.get("SITES_TABLE"):
        sites_repo = sites_repository()
    mailer_send = mailer_send or send_email
    now = int((now_fn or time.time)())
    base_url = os.environ.get("PUBLIC_API_BASE_URL", "")

    invites = invites_repo.scan_type()
    sent = failed = 0
    org_by_tenant: dict[str, dict] = {}
    for invite in invites:
        if not invite_sendable(invite):
            continue
        due = due_steps(invite, now)
        if not due:
            continue
        tenant_id = str(invite.get("tenant_id") or "")
        if tenant_id not in org_by_tenant:
            org_by_tenant[tenant_id] = _tenant_organization(sites_repo, tenant_id)
        org = org_by_tenant.get(tenant_id, {})
        current = invite
        for step in due:
            try:
                content = invite_email(current, base_url=base_url, organization=org)
                mailer_send(
                    to=(current.get("customer") or {}).get("email", ""),
                    subject=content["subject"], html=content["html"], text=content["text"],
                    from_name=str(org.get("name") or ""),
                )
                current = mark_step_sent(current, step["day"], now)
                sent += 1
            except (EmailError, Exception) as exc:  # noqa: BLE001 — never let one send stop the sweep
                logger.warning("Review invite send failed (%s): %s", invite.get("invite_id"), exc)
                failed += 1
        try:
            invites_repo.put(current)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist invite %s: %s", invite.get("invite_id"), exc)
    return {"scanned": len(invites), "sent": sent, "failed": failed}


def _tenant_organization(sites_repo, tenant_id):
    """The tenant's business identity for the invite email — name (from-address) + entity_type/place_id/
    review_destination (routing). First Site with an organization; multi-Site precision is a future refinement."""
    if not sites_repo or not tenant_id:
        return {}
    try:
        for site in sites_repo.list_for_tenant(tenant_id):
            org = (site or {}).get("organization")
            if isinstance(org, dict) and str(org.get("name") or "").strip():
                return org
    except Exception:  # noqa: BLE001
        pass
    return {}
