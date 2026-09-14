"""GET /tips/manage?t=<token> — a supporter opens their own Stripe billing portal and cancels a tip.

plans/PAY_WHAT_YOU_WANT.md §5g. Junior Bay asks supporters for NO account, which is a deliberate product
decision and not an omission: Patreon, Ko-fi and Buy Me a Coffee all require one, and their account is a
directory and a feed — cancellation is merely the thing it happens to make possible. Account recovery is
email recovery anyway, so the login buys less than it looks.

What it does buy is a place to cancel, and that is not optional: a recurring charge nobody can stop is a
chargeback generator, and under direct charges the dispute fee AND the ratio land on the TENANT's account.
So the link is the surface. It carries an opaque token that dereferences server-side (the `cart_token`
precedent — no customer id, no email in the URL), and hands the supporter to Stripe's own portal on the
connected account, where the subscription actually lives.

Public and unauthenticated by design. The token IS the credential, and the action behind it is fail-safe:
the worst a leaked link does is stop a donation that the supporter can start again.
"""

import os
from urllib.request import urlopen

from stripe_link.common import error_response, query_params
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    stripe_keys_repository,
    tip_tokens_repository,
)
from stripe_link.runtime.error_pages import render_error_page
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

_GONE_HTML = render_error_page(
    404, "This link is no longer valid. Ask for a new one from the page you tipped from, or reply to your "
    "receipt and we will cancel it for you.",
    title="Link expired", badge="Manage your tip",
)
_UNAVAILABLE_HTML = render_error_page(
    503, "We could not open your billing page just now. Please try again in a minute.",
    title="Temporarily unavailable", badge="Manage your tip",
)


def _html(body: str, status_code: int):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
        "body": body,
    }


def handler(event, context, *, tokens_repo=None, stripe_repo=None, secret_cipher=None, opener=None):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return _html("", 200)
    if method != "GET":
        return error_response("Unsupported method.", status_code=405, code="method_not_allowed")

    token = str(query_params(event).get("t") or "").strip()
    if not token:
        return _html(_GONE_HTML, 404)

    # Look up in BOTH modes: the token is minted in whichever mode the tip was taken, and a supporter's link
    # carries no mode of its own. A live token is the common case; a test one only exists for the tenant's
    # own trial runs.
    record = None
    for mode in ("live", "test"):
        repo = tokens_repo or tip_tokens_repository(mode=mode)
        try:
            record = repo.find_by_id(token)
        except RepositoryError:
            record = None
        if record or tokens_repo is not None:
            break
    if not record:
        return _html(_GONE_HTML, 404)

    tenant_id = str(record.get("tenant_id") or "")
    customer_id = str(record.get("stripe_customer_id") or "")
    mode = "live" if str(record.get("stripe_mode") or "live") == "live" else "test"
    if not tenant_id or not customer_id:
        return _html(_GONE_HTML, 404)

    stripe_repo = stripe_repo or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    try:
        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    except RepositoryError:
        return _html(_UNAVAILABLE_HTML, 503)
    api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return _html(_UNAVAILABLE_HTML, 503)

    # The subscription lives on the CONNECTED account (direct charges), so the portal session is created
    # there — the same call the platform makes for its own billing, with stripe_account set.
    try:
        session = stripe_request(
            "POST", "/billing_portal/sessions",
            api_key=api_key, stripe_account=stripe_account, opener=opener or urlopen,
            data={"customer": customer_id, "return_url": _return_url(record)},
        )
    except StripeApiError:
        return _html(_UNAVAILABLE_HTML, 503)

    url = str(session.get("url") or "")
    if not url:
        return _html(_UNAVAILABLE_HTML, 503)
    return {"statusCode": 302, "headers": {"Location": url, "Cache-Control": "no-store"}, "body": ""}


def _return_url(record) -> str:
    """Where Stripe sends the supporter when they are done. The platform's own site, not the tenant's page:
    the page a tip came from may be unpublished, renamed or gone by the time someone cancels a year later."""
    return str(record.get("return_url") or os.environ.get("PUBLIC_SITE_URL") or "https://juniorbay.com/")
