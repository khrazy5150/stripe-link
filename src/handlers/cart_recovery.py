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
from stripe_link.repositories.documents import cart_tokens_repository, carts_repository, sites_repository

logger = logging.getLogger(__name__)


def handler(event, context, *, carts_repo=None, cart_tokens_repo=None, sites_repo=None,
            mailer_send=None, now_fn=None, token_factory=None):
    carts_repo = carts_repo or carts_repository()
    cart_tokens_repo = cart_tokens_repo or cart_tokens_repository()
    if sites_repo is None and os.environ.get("SITES_TABLE"):
        sites_repo = sites_repository()
    mailer_send = mailer_send or send_email
    now = int((now_fn or time.time)())
    base_url = os.environ.get("PUBLIC_API_BASE_URL", "").rstrip("/")
    min_age = int(os.environ.get("CART_ABANDON_AFTER_SECONDS", str(60 * 60)))       # 1h quiet = abandoned
    max_attempts = int(os.environ.get("CART_RECOVERY_MAX_ATTEMPTS", "1"))            # one nudge by default
    token_factory = token_factory or (lambda: secrets.token_urlsafe(24))

    carts = carts_repo.scan_type()
    sent = failed = 0
    org_by_tenant: dict[str, dict] = {}
    for cart in carts:
        if not recoverable(cart, now, min_age_seconds=min_age, max_attempts=max_attempts):
            continue
        tenant_id = str(cart.get("tenant_id") or "")
        if tenant_id not in org_by_tenant:
            org_by_tenant[tenant_id] = _tenant_organization(sites_repo, tenant_id)
        org = org_by_tenant.get(tenant_id, {})
        try:
            token = token_factory()
            cart_tokens_repo.put(cart_token_doc(
                tenant_id, token, str(cart.get("email") or ""), str(cart.get("offer_id") or ""),
                now, cart_id=str(cart.get("cart_id") or ""),
            ))
            recovery_url = _with_param(normalize_page_url(cart.get("page_url")), "ct", token)
            unsubscribe_url = f"{base_url}/cart/unsubscribe?tenant_id={quote(tenant_id)}&token={quote(token)}" if base_url else ""
            content = recovery_email(cart, recovery_url=recovery_url, unsubscribe_url=unsubscribe_url, organization=org)
            mailer_send(
                to=str(cart.get("email") or ""), subject=content["subject"],
                html=content["html"], text=content["text"], from_name=str(org.get("name") or ""),
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


def _tenant_organization(sites_repo, tenant_id):
    """The tenant's business identity for the from-name — first Site with an organization (multi-Site
    precision is a future refinement, same as the review-invite sweep)."""
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
