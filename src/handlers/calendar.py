"""Per-tenant Google Calendar connection (OAuth).

- POST /calendar/connect      (tenant-auth)  -> returns the Google consent URL, stores a
                                                single-use state nonce.
- GET  /calendar/callback     (public)       -> Google redirects here; exchange the code,
                                                store the tenant's KMS-encrypted refresh token.
- GET/DELETE /calendar/connection (tenant-auth) -> status / disconnect.

Platform client_id/secret live in Secrets Manager; each tenant's refresh token is
KMS-encrypted (reusing the Stripe-keys KMS key). resolve_tenant_calendar() is the resolver
Phase C.1c uses to run the calendar client as any connected tenant.
"""
import os
import secrets
import time

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_calendar_connection
from stripe_link.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
    build_consent_url,
    exchange_code_for_tokens,
    load_google_oauth_secret,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    calendar_connections_repository,
    oauth_states_repository,
)

CONNECTION_ID = "google"
STATE_TTL_SECONDS = 600
KMS_MODE = "calendar"
KMS_FIELD = "google_refresh_token"


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
    if path.endswith("/calendar/connection") and method == "GET":
        return connection_status_route(event, connections_repo)
    if path.endswith("/calendar/connection") and method == "DELETE":
        return disconnect_route(event, connections_repo)
    return error_response("Unsupported calendar route.", status_code=404, code="not_found")


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
    connection = {
        "schema_version": "2026-05-29", "document_type": "calendar_connection", "tenant_id": tenant_id,
        "connection_id": CONNECTION_ID, "provider": "google", "calendar_id": account_email,
        "account_email": account_email, "scopes": (tokens.get("scope") or "").split(),
        "refresh_token_ref": secret_cipher.encrypt(refresh_token, tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD),
        "status": "connected", "connected_at": now, "updated_at": now,
    }
    try:
        validate_calendar_connection(connection)
        connections_repo.put(connection)
    except (DocumentValidationError, RepositoryError) as exc:
        return _html(f"Could not save the connection: {exc}", 500)
    return _html("Your Google Calendar is connected. You can close this tab and return to the dashboard.")


def connection_status_route(event, connections_repo):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    conn = connections_repo.get(tenant_id, CONNECTION_ID)
    if not conn:
        return json_response({"connected": False})
    return json_response({
        "connected": conn.get("status") == "connected",
        "provider": conn.get("provider"),
        "account_email": conn.get("account_email"),
        "calendar_id": conn.get("calendar_id"),
        "status": conn.get("status"),
        "connected_at": conn.get("connected_at"),
    })


def disconnect_route(event, connections_repo):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    connections_repo.delete(tenant_id, CONNECTION_ID)
    return json_response({"connected": False, "disconnected": True})


def resolve_tenant_calendar(tenant_id, *, connections_repo=None, secret_cipher=None, google_secret=None):
    """C.1c helper: return {client_id, client_secret, refresh_token, calendar_id} for a connected
    tenant (refresh token decrypted), or None if not connected."""
    connections_repo = connections_repo or calendar_connections_repository()
    conn = connections_repo.get(tenant_id, CONNECTION_ID)
    if not conn or conn.get("status") != "connected":
        return None
    creds = _google_creds(google_secret)
    secret_cipher = secret_cipher or KmsSecretCipher()
    return {
        "client_id": creds.get("client_id", ""),
        "client_secret": creds.get("client_secret", ""),
        "refresh_token": secret_cipher.decrypt(conn.get("refresh_token_ref", ""), tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD),
        "calendar_id": conn.get("calendar_id") or "primary",
    }


def _html(message, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": f"<!doctype html><meta charset=utf-8><title>Calendar</title>"
                f"<body style=\"font-family:sans-serif;padding:2rem;max-width:32rem;margin:auto\"><p>{message}</p></body>",
    }
