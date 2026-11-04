"""Scheduled sweep: email abandoned-cart recovery nudges (plans/LISTICLE_AND_CART.md L2 Slice D2).

Runs on an EventBridge schedule (~every 15 min), mirroring the review-invite sweep. Scans open carts, and for
each one that is recovery-eligible (has an email + items + a page to return to, gone quiet past the threshold,
not opted out, under the send cap) mints an opaque recovery token, builds a rehydration link + unsubscribe
link, and emails the shopper. Best-effort per cart — one bad send never stops the sweep.
"""
import logging
import os
import secrets
import time
from urllib.parse import quote

from stripe_link.domain.cart import cart_token_doc, mark_recovery_sent, normalize_page_url, recoverable
from stripe_link.domain.cart_recovery import recovery_email
from stripe_link.mailer import EmailError, send_email
from stripe_link.repositories.documents import (cart_tokens_repository, carts_repository,
                                                pages_repository, sites_repository)
from stripe_link.sender_identity import sending_identity

logger = logging.getLogger(__name__)


def handler(event, context, *, carts_repo=None, cart_tokens_repo=None, sites_repo=None,
            mailer_send=None, now_fn=None, token_factory=None, profiles_repo=None, pages_repo=None):
    # Abandoned-cart recovery is a live-only sweep: never email real recovery nudges for test-mode carts
    # (plans/STRIPE_MODE_DECOUPLING.md). The mode-scoped scan returns only live carts.
    carts_repo = carts_repo or carts_repository(mode="live")
    cart_tokens_repo = cart_tokens_repo or cart_tokens_repository(mode="live")
    if sites_repo is None and os.environ.get("SITES_TABLE"):
        sites_repo = sites_repository(mode="live")
    if pages_repo is None and os.environ.get("PAGES_TABLE"):
        pages_repo = pages_repository(mode="live")  # the cart's page, to find WHICH business is selling
    mailer_send = mailer_send or send_email
    now = int((now_fn or time.time)())
    base_url = os.environ.get("PUBLIC_API_BASE_URL", "").rstrip("/")
    min_age = int(os.environ.get("CART_ABANDON_AFTER_SECONDS", str(60 * 60)))       # 1h quiet = abandoned
    max_attempts = int(os.environ.get("CART_RECOVERY_MAX_ATTEMPTS", "1"))            # one nudge by default
    token_factory = token_factory or (lambda: secrets.token_urlsafe(24))

    carts = carts_repo.scan_type()
    sent = failed = 0
    # Keyed by (tenant, PAGE): the business behind a recovery email is the one whose page holds the
    # abandoned cart, and a tenant can run several. A per-tenant cache would sign every nudge in the sweep
    # with whichever Site resolved first (plans/SITE_AS_BUSINESS_IDENTITY.md §1).
    identity_by_page: dict[tuple[str, str], dict] = {}
    for cart in carts:
        if not recoverable(cart, now, min_age_seconds=min_age, max_attempts=max_attempts):
            continue
        tenant_id = str(cart.get("tenant_id") or "")
        page_id = str(cart.get("page_id") or "")
        if (tenant_id, page_id) not in identity_by_page:
            identity_by_page[(tenant_id, page_id)] = sending_identity(
                tenant_id, page_id=page_id, mode="live", profiles_repo=profiles_repo,
                sites_repo=sites_repo, pages_repo=pages_repo)
        # One identity for the body and the envelope alike (plans/EMAIL_TEMPLATE.md).
        identity = identity_by_page.get((tenant_id, page_id), {})
        org = identity.get("organization") or {}
        business_name = identity.get("business_name", "")
        try:
            token = token_factory()
            cart_tokens_repo.put(cart_token_doc(
                tenant_id, token, str(cart.get("email") or ""), str(cart.get("offer_id") or ""),
                now, cart_id=str(cart.get("cart_id") or ""),
            ))
            recovery_url = _with_param(normalize_page_url(cart.get("page_url")), "ct", token)
            unsubscribe_url = f"{base_url}/cart/unsubscribe?tenant_id={quote(tenant_id)}&token={quote(token)}" if base_url else ""
            content = recovery_email(
                cart, recovery_url=recovery_url, unsubscribe_url=unsubscribe_url,
                organization={**org, "name": business_name}, reply_to=identity.get("reply_to", ""),
            )
            mailer_send(
                to=str(cart.get("email") or ""), subject=content["subject"],
                html=content["html"], text=content["text"], from_name=business_name,
                reply_to=identity.get("reply_to", ""), tenant_id=tenant_id,
            )
            carts_repo.put(mark_recovery_sent(cart, now))
            sent += 1
        except (EmailError, Exception) as exc:  # noqa: BLE001 — one bad send never stops the sweep
            logger.warning("Cart recovery send failed (%s): %s", cart.get("cart_id"), exc)
            failed += 1
    return {"scanned": len(carts), "sent": sent, "failed": failed}


def _with_param(url: str, key: str, value: str) -> str:
    if not url:
        return ""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{quote(key)}={quote(value)}"
