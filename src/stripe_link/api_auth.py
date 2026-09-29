"""Who is allowed to call what, written down once.

`tenant_id` is read from the request today -- body, query string, or an `X-Tenant-Id` header -- and nothing
verifies the caller. Anyone who knows a tenant_id can act as that tenant (plans/API_AUTHENTICATION.md, and
the TODO entry it came from). The fix is an authorizer at the API, but the hard part is not the authorizer:
it is knowing WHICH routes must keep working without a token, because getting that wrong stops buyers
checking out.

So the boundary lives here, as data, per METHOD rather than per path -- several paths are both. `POST
/leads` is a stranger filling in a form on a published page; `GET /leads` returns those strangers' email
addresses to the tenant. Same path, opposite answers.

**Fail closed.** An unclassified route is PRIVATE. A new endpoint that nobody thought about is protected by
default and a test names it, rather than being quietly reachable by anyone.
"""
from typing import Any

PUBLIC = "public"
PRIVATE = "private"

# Reached WITHOUT a dashboard session, by a buyer, a visitor, Stripe, or a browser mid-OAuth. Each entry is
# (method, path) exactly as template.yaml declares it; "ANY" is spelled out rather than assumed.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    # --- Stripe and platform webhooks: authenticated by SIGNATURE, not by a token ---
    ("POST", "/webhook/stripe"): "Stripe signs it; the handler verifies that signature",
    ("POST", "/webhook/stripe-preview"): "same, preview API version",
    ("POST", "/webhook/platform-billing"): "same, platform's own billing account",

    # --- Getting a session in the first place ---
    ("POST", "/auth/login"): "there is no token before login",
    ("POST", "/auth/refresh"): "the refresh token is the credential; an expired access token cannot renew itself",
    ("POST", "/auth/register"): "nor before registration",
    ("POST", "/auth/confirm"): "email confirmation, follows a link",
    ("POST", "/auth/forgot"): "password reset request",
    ("POST", "/auth/reset"): "password reset completion",
    ("POST", "/register"): "tenant registration",

    # --- A buyer purchasing from a published page ---
    ("GET", "/checkout"): "the published page's own checkout",
    ("POST", "/checkout"): "the published page's own checkout",
    ("GET", "/cart"): "a shopper's cart on a published page",
    ("POST", "/cart"): "a shopper's cart on a published page",
    ("PATCH", "/cart/items/{line_id}"): "changing a cart line",
    ("DELETE", "/cart/items/{line_id}"): "removing a cart line",
    ("POST", "/cart/checkout"): "cart checkout",
    ("GET", "/cart/unsubscribe"): "abandoned-cart opt-out, from an emailed link",
    ("POST", "/upsell/charge"): "one-click upsell, off-session, from the funnel page",
    ("GET", "/upsell/session"): "the funnel page reading its own session",
    ("GET", "/pages/{page_id}/post-checkout/next"): "where the funnel sends the buyer next",
    ("POST", "/prices/calculate"): "a published page pricing what it displays",
    ("POST", "/offers/resolve"): "a published page resolving what it displays",
    ("GET", "/download"): "a buyer collecting what they paid for",
    ("POST", "/downloads/lead"): "a visitor collecting a lead magnet",

    # --- A buyer managing what they already bought, by opaque-token link (no accounts by design) ---
    ("GET", "/purchase/manage"): "buyer self-service, reached from a link in their receipt",
    ("POST", "/purchase/manage"): "buyer self-service",
    ("GET", "/tips/manage"): "supporter cancelling a recurring tip",
    ("GET", "/services/appointments/manage"): "buyer managing their own appointment",
    ("POST", "/services/appointments/manage/cancel"): "buyer cancelling it",
    ("POST", "/services/appointments/manage/reschedule"): "buyer rescheduling it",
    ("POST", "/services/appointments/manage/schedule"): "buyer scheduling it",

    # --- A visitor booking in the first place ---
    ("GET", "/book/{service}"): "the public booking page",
    ("GET", "/services/{service_id}/availability"): "what a visitor can book",
    ("POST", "/services/appointments/reserve"): "holding a slot before paying",
    ("POST", "/services/appointments/checkout"): "paying for it",

    # --- Serving and resolving published pages ---
    ("GET", "/published/{code}"): "a published page",
    ("GET", "/published/{code}/{view}"): "a published page's funnel view",
    ("GET", "/preview/{code}"): "a preview reached by opaque code",
    ("GET", "/preview/{code}/{view}"): "a preview's funnel view",
    ("GET", "/routes/resolve"): "short-link resolution, called by the edge",
    ("GET", "/custom-domains/resolve"): "hostname resolution, called by the Cloudflare worker",
    ("GET", "/experiments/{experiment_id}/resolve"): "which variant this visitor sees",
    ("POST", "/experiments/{experiment_id}/view"): "recording that they saw it",
    ("GET", "/t/view"): "page-view tracking from a published page",
    ("POST", "/t/view"): "page-view tracking from a published page",
    ("GET", "/legal"): "platform legal pages",
    ("GET", "/legal/{page_id}"): "platform legal pages",
    ("GET", "/manifest"): "the PWA manifest",
    ("GET", "/health"): "liveness",

    # --- A stranger contributing something ---
    ("POST", "/leads"): "a visitor filling in a lead form -- the whole point is that they are anonymous",
    ("GET", "/review"): "the public review form",
    ("POST", "/review"): "a buyer leaving a review, from an emailed invite link",
    ("GET", "/report"): "abuse report form (plans/CREATOR_LINK_POLICY.md)",
    ("POST", "/report"): "abuse report submission",
    ("POST", "/support/contact"): "the public contact form",

    # --- A browser mid-OAuth, redirected back by the provider ---
    ("GET", "/stripe/connect/callback"): "Stripe redirects the browser here with a code",
    ("GET", "/calendar/callback"): "Google redirects the browser here with a code",
    ("GET", "/stripe/connect/start"): "begins the redirect; carries no secret of its own",
}

# Paths that are public for one method and tenant-scoped for another. Documented because the same path
# answering differently by method is exactly where a reviewer's eye slides past a hole. A test DERIVES the
# real set from the table and asserts this matches, so it cannot quietly drift.
ASYMMETRIC = {
    "/leads": "POST is a stranger submitting a form; GET returns those strangers' email addresses",
}


def route_key(event: dict[str, Any]) -> tuple[str, str]:
    """`(METHOD, resource-path)` for an API Gateway event.

    Uses `resource` -- the TEMPLATED path (`/orders/{order_id}`) -- not `path`, which carries the actual
    id. Matching on the real path would need a router here and would let `/orders/anything` miss the table.
    """
    method = str((event or {}).get("httpMethod") or "").upper()
    resource = str((event or {}).get("resource") or (event or {}).get("path") or "")
    return method, resource


def classify(event: dict[str, Any]) -> str:
    """PUBLIC or PRIVATE. Anything not named public is private -- an endpoint nobody classified must not be
    reachable by everybody."""
    method, resource = route_key(event)
    if method == "OPTIONS":
        return PUBLIC  # a CORS preflight carries no credentials by definition
    return PUBLIC if (method, resource) in PUBLIC_ROUTES else PRIVATE


def bearer_token(event: dict[str, Any]) -> str:
    """The raw token the caller sent, or "". Header names are case-insensitive over the wire."""
    headers = (event or {}).get("headers") or {}
    for name, value in headers.items():
        if str(name).lower() == "authorization":
            raw = str(value or "").strip()
            return raw[7:].strip() if raw[:7].lower() == "bearer " else ""
    return ""


def verified_claims(event: dict[str, Any]) -> dict[str, Any]:
    """Claims API Gateway has ALREADY verified, when an authorizer is attached.

    This is the only trustworthy source of identity in a Lambda: the signature check happened upstream.
    Empty until the authorizer is attached, which is why enforcement waits for it.
    """
    context = ((event or {}).get("requestContext") or {}).get("authorizer") or {}
    claims = context.get("claims")
    return claims if isinstance(claims, dict) else {}


def unverified_claims(event: dict[str, Any]) -> dict[str, Any]:
    """The token's payload, decoded WITHOUT checking its signature.

    **Not a security control, and never to be used as one.** It exists to measure the gap before anything
    is enforced: how many real requests carry a token at all, and does the identity in it match the
    tenant_id the request asks for. Anyone can mint one of these; that is the entire point of verifying.
    """
    import base64
    import json

    token = bearer_token(event)
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:  # noqa: BLE001 - a malformed token is a measurement, not an error
        return {}


def caller_tenant(claims: dict[str, Any]) -> str:
    """The tenant a set of claims speaks for.

    `custom:client_id` is what `auth.py` puts on the Cognito user and is authoritative when present. It is
    absent from an ACCESS token (only an id token carries custom attributes), so `sub` is the fallback --
    and today that is exactly right: every user_profile in dev and prod has `user_id == tenant_id`
    (6 of 6, measured 2026-09-25). That equality is a property of the data, not a guarantee of the schema,
    so it is written here once where a real user->tenant lookup can replace it.
    """
    claims = claims or {}
    for field in ("custom:client_id", "custom:tenant_id"):
        value = str(claims.get(field) or "").strip()
        if value:
            return value
    return str(claims.get("sub") or "").strip()
