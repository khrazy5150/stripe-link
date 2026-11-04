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
from stripe_link.domain.sites import find_site_for_page
from stripe_link.mailer import EmailError, send_email, tenant_email_identity
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
    org_by_page: dict[tuple[str, str], dict] = {}
    identity_by_tenant: dict[str, dict] = {}
    for invite in invites:
        if not invite_sendable(invite):
            continue
        due = due_steps(invite, now)
        if not due:
            continue
        tenant_id = str(invite.get("tenant_id") or "")
        page_id = str(invite.get("page_id") or "")
        if (tenant_id, page_id) not in org_by_page:
            org_by_page[(tenant_id, page_id)] = _invite_organization(sites_repo, pages_repo, tenant_id,
                                                                     page_id)
        if tenant_id not in identity_by_tenant:
            identity_by_tenant[tenant_id] = tenant_email_identity(tenant_id, profiles_repo)
        org = org_by_page.get((tenant_id, page_id), {})
        # Resolved ONCE and used for both the body and the envelope. The two used to be read from
        # different places, which is how a message could name one business in its From line and another
        # (or none) in its content.
        identity = identity_by_tenant.get(tenant_id, {})
        # The SITE WINS (plans/SITE_AS_BUSINESS_IDENTITY.md §1). The tenant profile's business name is one
        # name for a tenant who may sell several businesses, so letting it win signed a Quill customer's
        # invite "Poliaxis Nutrition". The profile is now only the fallback for an invite whose Site has no
        # organization yet, and it disappears entirely when §P4 removes that field.
        business_name = str(org.get("name") or "").strip() or identity.get("business_name", "")
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


def _invite_organization(sites_repo, pages_repo, tenant_id, page_id):
    """The business identity to sign this invite with — name (From line) plus entity_type/place_id/
    review_destination (where the review is routed).

    Resolved PER INVITE from the page the order came from, because one tenant can run several businesses
    and each lives on its own Site. The invite carries its `page_id`; the page carries its `site_id`
    reverse edge, so this is two keyed reads (plans/SITE_AS_BUSINESS_IDENTITY.md §3.1 and §4).

    Falls back to the first Site that has an organization, which is what this did for every invite before
    the edge existed: invites written before `page_id` was stored have no page to resolve from, and a
    single-Site tenant gets the same answer either way. Never raises — branding is worth less than
    delivery.
    """
    if not sites_repo or not tenant_id:
        return {}
    if page_id and pages_repo is not None:
        try:
            page = pages_repo.get(tenant_id, page_id) or {}
            site = find_site_for_page(sites_repo, tenant_id, page_id, page=page)
            org = (site or {}).get("organization")
            if isinstance(org, dict) and str(org.get("name") or "").strip():
                return org
        except Exception:  # noqa: BLE001
            pass
    try:
        for site in sites_repo.list_for_tenant(tenant_id):
            org = (site or {}).get("organization")
            if isinstance(org, dict) and str(org.get("name") or "").strip():
                return org
    except Exception:  # noqa: BLE001
        pass
    return {}
