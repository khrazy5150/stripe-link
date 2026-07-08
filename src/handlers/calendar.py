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
import os
import secrets
import time
import uuid

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_calendar_connection
from stripe_link.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
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


def handler(event, context, connections_repo=None, states_repo=None, secret_cipher=None, google_secret=None, opener=None):
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
        raise GoogleCalendarError("GOOGLE_OAUTH_SECRET_NAME is not configured.")
    return load_google_oauth_secret(name)


def _redirect_uri():
    uri = os.environ.get("CALENDAR_REDIRECT_URI", "")
    if not uri:
        raise GoogleCalendarError("CALENDAR_REDIRECT_URI is not configured.")
    return uri


def connect_route(event, states_repo, google_secret):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        creds = _google_creds(google_secret)
        redirect_uri = _redirect_uri()
    except GoogleCalendarError as exc:
        return error_response(str(exc), status_code=500, code="calendar_not_configured")

    now = int(time.time())
    state = secrets.token_urlsafe(24)
    states_repo.put({
        "schema_version": "2026-05-29", "document_type": "oauth_state", "tenant_id": tenant_id,
        "state_id": state, "created_at": now, "expires_at": now + STATE_TTL_SECONDS,
    })
    return json_response({"authorize_url": build_consent_url(creds.get("client_id", ""), redirect_uri, state)})


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
    except GoogleCalendarError as exc:
        return _html(f"Could not connect your calendar: {exc}", 502)

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
        conn["calendar_id"] = str(body["calendar_id"]).strip()
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
