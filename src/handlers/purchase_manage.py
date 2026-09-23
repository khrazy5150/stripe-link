"""Self-service for ONE purchase: /purchase/manage.

plans/PURCHASE_SELF_SERVICE.md v1. A customer who wants to stop paying, or wants their money back, has had
two routes: find our email, or find the seller. This is the third, reached from a link at the bottom of the
page next to the refund policy — because that is where someone goes when they want the money to stop.

Three states on one path, which keeps the API surface (and the number of pages a stranger can probe) small:

    GET  ?tenant=      the form: an email or phone, and optionally roughly when
    GET  ?t=<token>    the ONE transaction that token names, and the actions it allows
    POST               lookup | cancel | refund, by the form's `action` field

Two rules run through all of it. **Never enumerate** — one transaction, the latest or the nearest to the
date given; a list behind an emailed link is both a privacy target and the screen that ends three
subscriptions instead of the one they came for. And **the answer to a lookup is identical whether or not
anything matched**, or the form becomes an oracle for "did that person buy from this creator".

Scoped to one tenant (v1): once the tenant is known, finding the order is a query on that tenant, so there
is no cross-tenant index and no platform-wide buyer graph. See plan §5a for widening it later.
"""

import os
import secrets
import time
from urllib.parse import parse_qs, urlencode
from urllib.request import urlopen

from stripe_link.common import error_response, query_params
from stripe_link.domain.leads import HONEYPOT_FIELD, is_spam
from stripe_link.domain.purchase_lookup import (
    contact_key,
    purchase_summary,
    purchase_token_doc,
    refund_request_doc,
    select_order,
    subscription_id,
)
from stripe_link.domain.request_throttle import (
    CONTACT_LIMIT,
    CONTACT_WINDOW_SECONDS,
    TENANT_LIMIT,
    TENANT_WINDOW_SECONDS,
    is_over_limit,
    next_count,
    throttle_doc,
    throttle_id,
)
from stripe_link.ids import generate_id
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.domain.email_layout import button, paragraph, render_email
from stripe_link.mailer import send_email, tenant_email_identity
from stripe_link.repositories.documents import (
    RepositoryError,
    notifications_repository,
    orders_repository,
    purchase_throttles_repository,
    purchase_tokens_repository,
    refund_requests_repository,
    stripe_keys_repository,
)
from stripe_link.runtime.error_pages import render_error_page
from stripe_link.runtime.purchase_pages import (
    render_cancelled,
    render_lookup_form,
    render_lookup_sent,
    render_refund_requested,
    render_transaction,
)
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

_EXPIRED_HTML = render_error_page(
    404, "This link has expired or is no longer valid. Start again from the page you bought from, or reply "
    "to your receipt and we will help.",
    title="Link expired", badge="Manage a purchase",
)
_UNAVAILABLE_HTML = render_error_page(
    503, "We could not do that just now. Please try again in a minute.",
    title="Temporarily unavailable", badge="Manage a purchase",
)


def _html(body, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
        "body": body,
    }


def _form_body(event) -> dict:
    """A browser form POST, not JSON — these pages are plain HTML so they work with scripting disabled."""
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        from base64 import b64decode

        raw = b64decode(raw).decode("utf-8", "replace")
    return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _manage_url() -> str:
    return f"{os.environ.get('PUBLIC_API_BASE_URL', '').rstrip('/')}/purchase/manage"


def handler(
    event,
    context,
    *,
    orders_repo=None,
    tokens_repo=None,
    refunds_repo=None,
    notifications_repo=None,
    stripe_repo=None,
    secret_cipher=None,
    throttles_repo=None,
    mailer_send=None,
    opener=None,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return _html("", 200)

    if method == "GET":
        params = query_params(event)
        token = str(params.get("t") or "").strip()
        tenant_id = str(params.get("tenant") or "").strip()
        if token:
            return _transaction_page(token, tokens_repo=tokens_repo, orders_repo=orders_repo)
        if tenant_id:
            return _html(render_lookup_form(_manage_url(), tenant_id,
                                            business=_business_name(tenant_id),
                                            honeypot_field=HONEYPOT_FIELD))
        return _html(_EXPIRED_HTML, 404)

    if method != "POST":
        return error_response("Unsupported method.", status_code=405, code="method_not_allowed")

    body = _form_body(event)
    action = str(body.get("action") or "").strip()
    if action == "lookup":
        return _lookup(body, orders_repo=orders_repo, tokens_repo=tokens_repo,
                       throttles_repo=throttles_repo, mailer_send=mailer_send, now_fn=now_fn)
    if action in {"cancel", "refund"}:
        return _act(action, body, tokens_repo=tokens_repo, orders_repo=orders_repo,
                    refunds_repo=refunds_repo, notifications_repo=notifications_repo,
                    stripe_repo=stripe_repo, secret_cipher=secret_cipher, opener=opener, now_fn=now_fn)
    return _html(_EXPIRED_HTML, 404)


def _business_name(tenant_id: str) -> str:
    """Best-effort branding. A missing name costs a sentence, never the page."""
    try:
        from stripe_link.repositories.documents import tenant_profiles_repository

        profile = tenant_profiles_repository().get(tenant_id, tenant_id) or {}
        return str((profile.get("business") or {}).get("name") or profile.get("business_name") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _orders_for(tenant_id, orders_repo, mode):
    repo = orders_repo or orders_repository(mode=mode)
    return repo.list_for_tenant(tenant_id)


def _lookup(body, *, orders_repo, tokens_repo, throttles_repo, mailer_send, now_fn):
    """Find ONE order and email a link to it — answering identically either way.

    This endpoint is unauthenticated and, unthrottled, amplifies one HTTP request into a full read of a
    tenant's order list plus an outbound email — with the tenant id available in a public footer URL. The
    gates below run BEFORE any of that, so a blocked request costs two gets and nothing else.
    """
    tenant_id = str(body.get("tenant") or "").strip()
    key = contact_key(body.get("contact") or "")
    when = _parse_date(body.get("when") or "")
    # The same honeypot the lead forms use: one hidden field, one name across the product, and a bot that
    # fills every input gets nothing. Silently — telling it would only teach it to leave the field alone.
    if not tenant_id or not key or is_spam(body):
        return _html(render_lookup_sent())

    now = int(now_fn())
    if _throttled(tenant_id, key, throttles_repo, now):
        return _html(render_lookup_sent())
    try:
        # Both modes: a tenant testing their own page has test orders, and a real buyer has live ones. The
        # token records which, so the action taken later runs against the right Stripe account.
        for mode in ("live", "test"):
            orders = _orders_for(tenant_id, orders_repo, mode)
            order = select_order(orders, key, approximate_date=when)
            if not order:
                continue
            token = secrets.token_urlsafe(24)
            repo = tokens_repo or purchase_tokens_repository(mode=mode)
            repo.put(purchase_token_doc(
                tenant_id, token,
                order_id=str(order.get("order_id") or ""),
                email=str((order.get("customer") or {}).get("email") or ""),
                mode=mode, now=now,
            ))
            _send_link(order, token, tenant_id, mailer_send)
            break
    except Exception:  # noqa: BLE001 - a lookup failure must look exactly like a miss, never like an error
        pass
    return _html(render_lookup_sent())


def _throttled(tenant_id, key, throttles_repo, now) -> bool:
    """Two counters, checked before any work and recorded after.

    Per (tenant, contact) so one address cannot be mailed repeatedly and one contact cannot make us re-read
    the orders; per tenant so enumerating DIFFERENT addresses — which the first gate cannot see — is capped
    too.

    Fails OPEN. A throttle table that is unavailable must not take the cancel-my-subscription path down with
    it: the cost of being wrong here is some extra reads, and the cost of being wrong the other way is a
    customer who cannot stop a recurring charge.
    """
    repo = throttles_repo
    if repo is None:
        if not os.environ.get("CARTS_TABLE"):
            return False
        repo = purchase_throttles_repository()
    contact_id = throttle_id("contact", tenant_id, key)
    tenant_bucket = throttle_id("tenant", tenant_id)
    try:
        contact_row = repo.get(tenant_id, contact_id)
        tenant_row = repo.get(tenant_id, tenant_bucket)
        if is_over_limit(contact_row, now=now, window_seconds=CONTACT_WINDOW_SECONDS, limit=CONTACT_LIMIT):
            return True
        if is_over_limit(tenant_row, now=now, window_seconds=TENANT_WINDOW_SECONDS, limit=TENANT_LIMIT):
            return True
        repo.put(throttle_doc(tenant_id, contact_id, now=now, window_seconds=CONTACT_WINDOW_SECONDS,
                              count=next_count(contact_row, now=now, window_seconds=CONTACT_WINDOW_SECONDS)))
        repo.put(throttle_doc(tenant_id, tenant_bucket, now=now, window_seconds=TENANT_WINDOW_SECONDS,
                              count=next_count(tenant_row, now=now, window_seconds=TENANT_WINDOW_SECONDS)))
    except Exception:  # noqa: BLE001 - see the docstring: this gate fails open on purpose
        return False
    return False


def _send_link(order, token, tenant_id, mailer_send):
    email = str((order.get("customer") or {}).get("email") or "").strip()
    if not email:
        return
    url = f"{_manage_url()}?{urlencode({'t': token})}"
    business = _business_name(tenant_id) or "the seller"
    text = (
        f"Here is the link to your purchase from {business}.\n\n{url}\n\n"
        "From there you can stop future payments or ask for a refund. The link works for seven days.\n\n"
        "If you did not ask for this, you can ignore it — nothing has changed."
    )
    identity = tenant_email_identity(tenant_id)
    html = render_email(
        business_name=identity.get("business_name") or (business if business != "the seller" else ""),
        title=f"Your purchase from {business}",
        body=(
            paragraph("Here is the link to your purchase. From there you can stop future payments or "
                      "ask for a refund.")
            + button("Manage this purchase", url)
            + paragraph("The link works for seven days. If you did not ask for this, you can ignore it "
                        "— nothing has changed.", muted=True)
        ),
        preheader="Your secure link to manage this purchase.",
        reply_to=identity.get("reply_to", ""),
    )
    (mailer_send or send_email)(
        to=email,
        subject=f"Your purchase from {business}",
        html=html,
        text=text,
        tenant_id=tenant_id,
    )


def _parse_date(value: str):
    try:
        from datetime import datetime, timezone

        return int(datetime.strptime(str(value).strip(), "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def _resolve(token, tokens_repo, orders_repo):
    """(record, order, mode) for a token, or (None, None, "")."""
    for mode in ("live", "test"):
        repo = tokens_repo or purchase_tokens_repository(mode=mode)
        try:
            record = repo.find_by_id(token)
        except RepositoryError:
            record = None
        if record:
            tenant_id = str(record.get("tenant_id") or "")
            order_repo = orders_repo or orders_repository(mode=str(record.get("stripe_mode") or mode))
            order = order_repo.get(tenant_id, str(record.get("order_id") or ""))
            return record, order, str(record.get("stripe_mode") or mode)
        if tokens_repo is not None:
            break
    return None, None, ""


def _transaction_page(token, *, tokens_repo, orders_repo):
    record, order, _ = _resolve(token, tokens_repo, orders_repo)
    if not record or not order:
        return _html(_EXPIRED_HTML, 404)
    tenant_id = str(record.get("tenant_id") or "")
    business = _business_name(tenant_id)
    policy = str(((order.get("refund_policy") or {}).get("short_label")) or "")
    return _html(render_transaction(
        purchase_summary(order), _manage_url(), token,
        business=business, policy=policy,
        lookup_url=f"{_manage_url()}?{urlencode({'tenant': tenant_id})}",
    ))


def _act(action, body, *, tokens_repo, orders_repo, refunds_repo, notifications_repo,
         stripe_repo, secret_cipher, opener, now_fn):
    record, order, mode = _resolve(str(body.get("t") or "").strip(), tokens_repo, orders_repo)
    if not record or not order:
        return _html(_EXPIRED_HTML, 404)
    tenant_id = str(record.get("tenant_id") or "")
    business = _business_name(tenant_id)

    if action == "cancel":
        return _cancel(order, tenant_id, mode, business,
                       stripe_repo=stripe_repo, secret_cipher=secret_cipher, opener=opener)
    return _request_refund(order, tenant_id, business, str(body.get("reason") or ""),
                           refunds_repo=refunds_repo, notifications_repo=notifications_repo, now_fn=now_fn)


def _cancel(order, tenant_id, mode, business, *, stripe_repo, secret_cipher, opener):
    """Self-serve, immediately: stopping future charges costs the seller nothing, and refusing it only
    sends the customer to their bank instead — which costs the seller a dispute fee and their ratio."""
    subscription = subscription_id(order)
    if not subscription:
        return _html(_EXPIRED_HTML, 404)
    try:
        stripe_keys = (stripe_repo or stripe_keys_repository()).get(tenant_id, mode=mode) or {}
    except RepositoryError:
        return _html(_UNAVAILABLE_HTML, 503)
    api_key, stripe_account = checkout_credentials(
        tenant_id, mode, stripe_keys, secret_cipher or KmsSecretCipher())
    if not api_key:
        return _html(_UNAVAILABLE_HTML, 503)
    try:
        # cancel_at_period_end, not an immediate delete: they paid for the period they are in, and taking it
        # away is a refund nobody asked for.
        stripe_request(
            "POST", f"/subscriptions/{subscription}",
            api_key=api_key, stripe_account=stripe_account, opener=opener or urlopen,
            data={"cancel_at_period_end": True},
        )
    except StripeApiError:
        return _html(_UNAVAILABLE_HTML, 503)
    return _html(render_cancelled(business))


def _request_refund(order, tenant_id, business, reason, *, refunds_repo, notifications_repo, now_fn):
    """A REQUEST. The money is the seller's to return, so this lands in the queue their Refunds screen
    already knows how to answer, and notifies them it arrived."""
    now = int(now_fn())
    document = refund_request_doc(
        {**order, "tenant_id": tenant_id}, reason=reason, now=now,
        request_id=f"rr_{generate_id()}",
    )
    try:
        saved = (refunds_repo or refund_requests_repository()).put(document)
    except RepositoryError:
        return _html(_UNAVAILABLE_HTML, 503)
    try:
        from handlers.notifications import _emit_refund_notification

        _emit_refund_notification(
            notifications_repo or notifications_repository(), saved, now)
    except Exception:  # noqa: BLE001 - the request is saved; a missing bell must not undo it
        pass
    return _html(render_refund_requested(business))
