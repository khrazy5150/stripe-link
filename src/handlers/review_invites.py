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
from stripe_link.sender_identity import sending_identity
from stripe_link.repositories.documents import (pages_repository, review_invites_repository,
                                                sites_repository)

logger = logging.getLogger(__name__)


def handler(event, context, *, invites_repo=None, sites_repo=None, mailer_send=None, now_fn=None,
            profiles_repo=None, pages_repo=None):
    # LIVE ONLY, exactly like the abandoned-cart sweep: this sends email to a real customer, and a
    # test-mode purchase must never cause a real person to be asked about a product they never bought.
    invites_repo = invites_repo or review_invites_repository(mode="live")
    if sites_repo is None and os.environ.get("SITES_TABLE"):
        sites_repo = sites_repository(mode="live")  # live only, same reason as the invites repo
    if pages_repo is None and os.environ.get("PAGES_TABLE"):
        pages_repo = pages_repository(mode="live")  # the invite's page, to find WHICH business sells it
    mailer_send = mailer_send or send_email
    now = int((now_fn or time.time)())
    base_url = os.environ.get("PUBLIC_API_BASE_URL", "")

    invites = invites_repo.scan_type()
    sent = failed = 0
    # Keyed by (tenant, PAGE), not by tenant: one tenant can run several businesses, and the business an
    # invite is from is the one whose page sold the product. A per-tenant cache would sign every invite in
    # the sweep with whichever Site resolved first -- the reported bug, one layer down
    # (plans/SITE_AS_BUSINESS_IDENTITY.md §1).
    identity_by_page: dict[tuple[str, str], dict] = {}
    for invite in invites:
        if not invite_sendable(invite):
            continue
        due = due_steps(invite, now)
        if not due:
            continue
        tenant_id = str(invite.get("tenant_id") or "")
        page_id = str(invite.get("page_id") or "")
        if (tenant_id, page_id) not in identity_by_page:
            identity_by_page[(tenant_id, page_id)] = sending_identity(
                tenant_id, page_id=page_id, mode="live", profiles_repo=profiles_repo,
                sites_repo=sites_repo, pages_repo=pages_repo)
        # Resolved ONCE and used for both the body and the envelope. The two used to be read from
        # different places, which is how a message could name one business in its From line and another
        # (or none) in its content.
        identity = identity_by_page.get((tenant_id, page_id), {})
        org = identity.get("organization") or {}
        business_name = identity.get("business_name", "")
        current = invite
        for step in due:
            try:
                content = invite_email(
                    current, base_url=base_url, organization={**org, "name": business_name},
                    reply_to=identity.get("reply_to", ""),
                )
                mailer_send(
                    to=(current.get("customer") or {}).get("email", ""),
                    subject=content["subject"], html=content["html"], text=content["text"],
                    from_name=business_name, reply_to=identity.get("reply_to", ""),
                    tenant_id=tenant_id,
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
