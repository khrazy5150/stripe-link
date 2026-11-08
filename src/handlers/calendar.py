"""Per-tenant calendar connections (OAuth). A tenant may connect many calendars.

- POST   /calendar/connect                    (tenant-auth) -> Google consent URL + state nonce.
- GET    /calendar/callback                    (public)     -> exchange code, store a connection
                                                               with a generated id + KMS-encrypted
                                                               refresh token (first one is default).
- GET    /calendar/connections                 (tenant-auth) -> list all connections.
- PATCH  /calendar/connections/{connection_id} (tenant-auth) -> rename / set default / pick calendar.
- DELETE /calendar/connections/{connection_id} (tenant-auth) -> disconnect one.
- GET/DELETE /calendar/connection              (tenant-auth) -> back-compat: the *default* connection.

Platform client_id/secret live in Secrets Manager; each tenant's refresh token is
KMS-encrypted (reusing the Stripe-keys KMS key). resolve_tenant_calendar() runs the calendar
client as any connected tenant; default_connection() picks the tenant's default calendar.
"""
import logging
import os
from html import escape as _escape
import secrets
import time
import uuid

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_calendar_connection
from stripe_link.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
    fetch_access_token,
    GoogleCalendarNotConfigured,
    GoogleCalendarReauthRequired,
    build_consent_url,
    exchange_code_for_tokens,
    load_google_oauth_secret,
)
from stripe_link.calendar_sync import KMS_FIELD, KMS_MODE, default_connection, resolve_tenant_calendar  # noqa: F401 (re-exported)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    calendar_connections_repository,
    oauth_states_repository,
)

STATE_TTL_SECONDS = 600


logger = logging.getLogger(__name__)


def handler(event, context, connections_repo=None, states_repo=None, secret_cipher=None, google_secret=None, opener=None):
    """Every calendar route, with the three Google failures told apart.

    They were one failure until 2026-11-06, and the one that mattered most did not even reach here: a
    missing credentials secret raised boto3's own exception, which is not a `GoogleCalendarError`, was
    caught nowhere, and became an unhandled 500. Prod had never had that secret, so the feature had never
    worked there and said nothing (`feedback_one_guess_hides_the_cause`).
    """
    try:
        return _route(event, context, connections_repo, states_repo, secret_cipher, google_secret, opener)
    except GoogleCalendarReauthRequired as exc:
        # THE TENANT'S to fix, and the only one with an action attached. 409 and a stable code so the
        # dashboard can offer a Reconnect button instead of printing an error.
        logger.info("calendar: reconnect required (%s)", exc)
        return error_response(
            "This Google Calendar connection has expired or been revoked. Reconnect the calendar to"
            " continue.", status_code=409, code="calendar_reconnect_required")
    except GoogleCalendarNotConfigured as exc:
        # OURS to fix, and no tenant can do anything about it. 503, logged with the secret name, because
        # the thing someone needs in order to fix this is WHICH credential is missing.
        logger.exception("calendar: not configured in this environment")
        return error_response(
            "Calendar connections are not available in this environment yet.", status_code=503,
            code="calendar_not_configured", extra={"detail": str(exc)})
    except GoogleCalendarError as exc:
        logger.exception("calendar: Google call failed")
        return error_response(str(exc), status_code=502, code="calendar_upstream_error")


def _route(event, context, connections_repo=None, states_repo=None, secret_cipher=None, google_secret=None, opener=None):
    connections_repo = connections_repo or calendar_connections_repository()
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")

    if method == "OPTIONS":
        return json_response({})
    if path.endswith("/calendar/connect") and method == "POST":
        return connect_route(event, states_repo or oauth_states_repository(), google_secret)
    if "/calendar/callback" in path and method == "GET":
        return callback_route(event, connections_repo, states_repo or oauth_states_repository(), secret_cipher or KmsSecretCipher(), google_secret, opener)
    if "/calendar/connections" in path:
        connection_id = path_params(event).get("connection_id")
        if method == "GET" and not connection_id:
            return list_connections_route(event, connections_repo)
        if method == "PATCH" and connection_id:
            return update_connection_route(event, connections_repo, connection_id)
        if method == "DELETE" and connection_id:
            return delete_connection_route(event, connections_repo, connection_id)
    if path.endswith("/calendar/connection") and method == "GET":
        return connection_status_route(event, connections_repo)
    if path.endswith("/calendar/connection") and method == "DELETE":
        return disconnect_route(event, connections_repo)
    return error_response("Unsupported calendar route.", status_code=404, code="not_found")


def _public_connection(conn):
    """A connection safe to return to the dashboard — never the encrypted token ref."""
    return {
        "connection_id": conn.get("connection_id"),
        "provider": conn.get("provider"),
        "display_name": conn.get("display_name") or conn.get("account_email") or "Calendar",
        "account_email": conn.get("account_email"),
        "calendar_id": conn.get("calendar_id"),
        "is_default": bool(conn.get("is_default")),
        "owner_fulfiller_id": conn.get("owner_fulfiller_id"),
        "connected": conn.get("status") == "connected",
        "status": conn.get("status"),
        "connected_at": conn.get("connected_at"),
    }


def _google_creds(google_secret):
    if google_secret is not None:
        return google_secret
    name = os.environ.get("GOOGLE_OAUTH_SECRET_NAME", "")
    if not name:
        raise GoogleCalendarNotConfigured("GOOGLE_OAUTH_SECRET_NAME is not configured.")
    return load_google_oauth_secret(name)


def _redirect_uri():
    uri = os.environ.get("CALENDAR_REDIRECT_URI", "")
    if not uri:
        raise GoogleCalendarNotConfigured("CALENDAR_REDIRECT_URI is not configured.")
    return uri


def connect_route(event, states_repo, google_secret):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        creds = _google_creds(google_secret)
        redirect_uri = _redirect_uri()
    except GoogleCalendarError as exc:
        # The subclasses carry a STATUS and an action; flattening them here is what made every cause look
        # like "not configured". The wrapper tells them apart.
        if isinstance(exc, (GoogleCalendarNotConfigured, GoogleCalendarReauthRequired)):
            raise
        return error_response(str(exc), status_code=502, code="calendar_upstream_error")

    now = int(time.time())
    state = secrets.token_urlsafe(24)
    states_repo.put({
        "schema_version": "2026-05-29", "document_type": "oauth_state", "tenant_id": tenant_id,
        "state_id": state, "created_at": now, "expires_at": now + STATE_TTL_SECONDS,
    })
    return json_response({"authorize_url": build_consent_url(creds.get("client_id", ""), redirect_uri, state)})


#: What a usable calendar connection needs. Google presents each of these as its OWN CHECKBOX, unticked
#: by default, with a "Select all" above them -- granular consent, which is mandatory for OAuth clients
#: created after 2019 and cannot be turned off. So a merchant can tick one, two, or none and still
#: complete the flow, and before 2026-11-08 we stored whatever came back as a working connection: green
#: badge in the dashboard, then 403 at the first availability check with a customer waiting.
REQUIRED_SCOPE_LABELS = {
    "https://www.googleapis.com/auth/calendar.events.owned":
        "See, create, change, and delete events on Google calendars you own",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly":
        "See the list of Google calendars you're subscribed to",
    "https://www.googleapis.com/auth/calendar.freebusy":
        "View your availability in your calendars",
}


def missing_scopes(granted) -> list[str]:
    """The scopes we asked for and did not get, as the LABELS Google showed the merchant.

    Named in Google's words, not ours: the merchant is about to go back to a screen with those exact
    sentences on it, and "calendar.freebusy was not granted" is not findable on that screen.
    """
    have = set(granted or [])
    return [label for scope, label in REQUIRED_SCOPE_LABELS.items() if scope not in have]


def callback_route(event, connections_repo, states_repo, secret_cipher, google_secret, opener):
    params = query_params(event)
    if params.get("error"):
        return _html("Calendar connection was cancelled. You can close this tab.", 400)
    code = str(params.get("code") or "").strip()
    state = str(params.get("state") or "").strip()
    if not code or not state:
        return _html("Missing authorization code.", 400)

    state_doc = states_repo.find_by_id(state)
    if not state_doc or int(state_doc.get("expires_at") or 0) < int(time.time()):
        return _html("This connection link has expired — please start again from the dashboard.", 400)
    tenant_id = str(state_doc.get("tenant_id") or "")
    try:
        states_repo.delete(tenant_id, state)  # single-use
    except Exception:  # noqa: BLE001
        pass

    try:
        creds = _google_creds(google_secret)
        tokens = exchange_code_for_tokens(creds.get("client_id", ""), creds.get("client_secret", ""), code, _redirect_uri(), opener=opener)
    except GoogleCalendarReauthRequired:
        return _html("That Google authorisation has already expired. Please start the connection again.",
                     409)
    except GoogleCalendarNotConfigured:
        # The tenant is staring at a browser page and can do nothing about this one.
        logger.exception("calendar: callback with no credentials configured")
        return _html("Calendar connections are not available yet. Please contact support.", 503)
    except GoogleCalendarError as exc:
        return _html(f"Could not connect your calendar: {exc}", 502)

    # REFUSED BEFORE IT IS STORED. A connection missing a permission is not a connection -- it looks
    # healthy in the dashboard and fails at the moment a customer is booking.
    absent = missing_scopes((tokens.get("scope") or "").split())
    if absent:
        items = "".join(f"<li>{_escape(label)}</li>" for label in absent)
        return _html(
            "<p>Junior Bay needs all three calendar permissions to manage bookings, and these were not "
            f"approved:</p><ul>{items}</ul><p>Start the connection again from your dashboard and tick "
            "every box (or use <strong>Select all</strong>) on the Google screen.</p>", 400)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return _html("Google did not return a refresh token. Remove this app under your Google account permissions and reconnect.", 400)

    account_email = "primary"
    try:
        for cal in GoogleCalendarClient(tokens.get("access_token", ""), opener=opener).calendar_list().get("items", []):
            if cal.get("primary"):
                account_email = cal.get("id") or "primary"
                break
    except GoogleCalendarError:
        pass

    now = int(time.time())
    existing = list(connections_repo.list_for_tenant(tenant_id) or [])
    # Reconnecting the same Google account updates that connection in place (also migrates the
    # legacy "google"-keyed record); a new account becomes a new connection with a generated id.
    match = next((c for c in existing if c.get("account_email") == account_email), None)
    has_default = any(c.get("is_default") and c.get("status") == "connected" for c in existing)
    connection_id = match.get("connection_id") if match else f"cal_{uuid.uuid4().hex[:12]}"
    is_default = bool(match.get("is_default")) if match else (not has_default)

    connection = {
        **(match or {}),
        "schema_version": "2026-05-29", "document_type": "calendar_connection", "tenant_id": tenant_id,
        "connection_id": connection_id, "provider": "google",
        "display_name": (match or {}).get("display_name") or account_email,
        "is_default": is_default,
        "calendar_id": (match or {}).get("calendar_id") or account_email,
        "account_email": account_email, "scopes": (tokens.get("scope") or "").split(),
        "refresh_token_ref": secret_cipher.encrypt(refresh_token, tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD),
        "status": "connected", "connected_at": (match or {}).get("connected_at") or now, "updated_at": now,
    }
    try:
        validate_calendar_connection(connection)
        connections_repo.put(connection)
    except (DocumentValidationError, RepositoryError) as exc:
        return _html(f"Could not save the connection: {exc}", 500)
    return _html("Your Google Calendar is connected. You can close this tab and return to the dashboard.")


def list_connections_route(event, connections_repo):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    connections = [_public_connection(c) for c in (connections_repo.list_for_tenant(tenant_id) or [])]
    connections.sort(key=lambda c: (not c["is_default"], c.get("connected_at") or 0))
    return json_response({"connections": connections, "count": len(connections)})


def owned_calendar_ids(tenant_id, conn, *, secret_cipher=None, google_secret=None, opener=None):
    """The ids of calendars this connection OWNS, or None when we could not ask.

    `accessRole` comes back on every `calendarList.list` entry; `owner` is the only role
    `calendar.events.owned` can write to. None (not an empty set) means the lookup failed, so the caller
    can tell "they own nothing" from "we do not know" and decline to refuse on a hiccup.
    """
    from stripe_link.calendar_sync import resolve_tenant_calendar

    try:
        creds = resolve_tenant_calendar(tenant_id, connection=conn, secret_cipher=secret_cipher,
                                        google_secret=google_secret)
        if not creds:
            return None
        token = fetch_access_token(creds["client_id"], creds["client_secret"], creds["refresh_token"],
                                   opener=opener)
        items = GoogleCalendarClient(token, opener=opener).calendar_list().get("items", [])
        return {str(c.get("id") or "") for c in items if c.get("accessRole") == "owner"}
    except GoogleCalendarError:
        raise
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("calendar: could not list owned calendars for %s", tenant_id)
        return None


def update_connection_route(event, connections_repo, connection_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    conn = connections_repo.get(tenant_id, connection_id)
    if not conn:
        return error_response("Connection not found.", status_code=404, code="not_found")
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    now = int(time.time())
    if "display_name" in body:
        conn["display_name"] = str(body.get("display_name") or "").strip() or conn.get("account_email") or "Calendar"
    if "calendar_id" in body and str(body.get("calendar_id") or "").strip():
        wanted = str(body["calendar_id"]).strip()
        # REFUSED HERE, not at the first booking. We request `calendar.events.owned`, which can only
        # write to calendars the merchant OWNS -- so a calendar merely shared with them would be
        # accepted happily now and 403 weeks later, when a customer books and nobody is watching.
        # `None` means we could not ask, and a lookup that hiccuped must not block a legitimate choice.
        owned = owned_calendar_ids(tenant_id, conn)
        if owned is not None and wanted not in owned:
            return error_response(
                "Bookings can only be written to a calendar you own. Choose one of your own calendars,"
                " or ask its owner to share ownership with you.",
                status_code=409, code="calendar_not_owned")
        conn["calendar_id"] = wanted
    if body.get("is_default") is True:
        for other in (connections_repo.list_for_tenant(tenant_id) or []):
            if other.get("connection_id") != connection_id and other.get("is_default"):
                connections_repo.put({**other, "is_default": False, "updated_at": now})
        conn["is_default"] = True
    conn["updated_at"] = now
    try:
        validate_calendar_connection(conn)
        connections_repo.put(conn)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_connection")
    return json_response({"connection": _public_connection(conn)})


def delete_connection_route(event, connections_repo, connection_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    removed = connections_repo.delete(tenant_id, connection_id)
    # If the default was removed, promote the next connected calendar so a default always exists.
    if removed and removed.get("is_default"):
        promote = default_connection(connections_repo, tenant_id)
        if promote and not promote.get("is_default"):
            connections_repo.put({**promote, "is_default": True, "updated_at": int(time.time())})
    return json_response({"disconnected": True, "connection_id": connection_id})


def connection_status_route(event, connections_repo):
    """Back-compat: report the tenant's default connection."""
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    conn = default_connection(connections_repo, tenant_id)
    if not conn:
        return json_response({"connected": False})
    return json_response(_public_connection(conn))


def disconnect_route(event, connections_repo):
    """Back-compat: disconnect the tenant's default connection."""
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    conn = default_connection(connections_repo, tenant_id)
    if conn:
        return delete_connection_route(event, connections_repo, conn.get("connection_id"))
    return json_response({"connected": False, "disconnected": True})


def _html(message, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": f"<!doctype html><meta charset=utf-8><title>Calendar</title>"
                f"<body style=\"font-family:sans-serif;padding:2rem;max-width:32rem;margin:auto\"><p>{message}</p></body>",
    }
