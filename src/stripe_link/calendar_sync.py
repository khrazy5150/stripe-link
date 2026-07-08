"""Calendar sync — resolve a tenant's connected calendar and push/read against it.

All functions are best-effort: a calendar failure must never break a booking. sync_appointment_event
returns the new external_calendar_events list to persist (or None for "no change"); tenant_busy_intervals
returns busy windows for the slot engine (or [] when not connected / on error).
"""
import os
from typing import Any

from stripe_link.domain.calendar import busy_intervals, google_event_body
from stripe_link.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
    fetch_access_token,
    load_google_oauth_secret,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import calendar_connections_repository

KMS_MODE = "calendar"
KMS_FIELD = "google_refresh_token"


def _google_secret(google_secret):
    if google_secret is not None:
        return google_secret
    name = os.environ.get("GOOGLE_OAUTH_SECRET_NAME", "")
    if not name:
        raise GoogleCalendarError("GOOGLE_OAUTH_SECRET_NAME is not configured.")
    return load_google_oauth_secret(name)


def tenant_connections(connections_repo, tenant_id):
    """All of a tenant's calendar connections (any status)."""
    return list(connections_repo.list_for_tenant(tenant_id) or [])


def default_connection(connections_repo, tenant_id):
    """The tenant's default connected calendar: the one flagged is_default, else the earliest
    connected (deterministic). Legacy single-connection tenants resolve to their only connection.
    Returns None when the tenant has no connected calendar."""
    connected = [c for c in tenant_connections(connections_repo, tenant_id) if c.get("status") == "connected"]
    if not connected:
        return None
    for conn in connected:
        if conn.get("is_default"):
            return conn
    connected.sort(key=lambda c: (int(c.get("connected_at") or 0), str(c.get("connection_id") or "")))
    return connected[0]


def resolve_tenant_calendar(tenant_id, *, connections_repo=None, secret_cipher=None, google_secret=None, connection=None):
    """Return {connection_id, provider, client_id, client_secret, refresh_token, calendar_id} for a
    connected calendar (refresh token decrypted), or None if not connected. Resolves the tenant's
    default connection unless a specific `connection` document is supplied (Phase 2 routing)."""
    connections_repo = connections_repo or calendar_connections_repository()
    conn = connection or default_connection(connections_repo, tenant_id)
    if not conn or conn.get("status") != "connected":
        return None
    creds = _google_secret(google_secret)
    secret_cipher = secret_cipher or KmsSecretCipher()
    return {
        "connection_id": conn.get("connection_id"),
        "provider": conn.get("provider") or "google",
        "client_id": creds.get("client_id", ""),
        "client_secret": creds.get("client_secret", ""),
        "refresh_token": secret_cipher.decrypt(conn.get("refresh_token_ref", ""), tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD),
        "calendar_id": conn.get("calendar_id") or "primary",
    }


def _client_for(tenant_id, *, connections_repo, secret_cipher, google_secret, opener, connection=None):
    """Return (GoogleCalendarClient, connection_id) for the resolved calendar, or (None, None)."""
    creds = resolve_tenant_calendar(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, connection=connection)
    if not creds:
        return None, None
    token = fetch_access_token(creds["client_id"], creds["client_secret"], creds["refresh_token"], opener=opener)
    return GoogleCalendarClient(token, calendar_id=creds["calendar_id"], opener=opener), creds["connection_id"]


def _event_matches(entry, connection_id):
    """Match an external_calendar_events entry to the connection we're syncing. Prefers
    connection_id; falls back to provider for legacy entries written before ids existed."""
    if entry.get("connection_id"):
        return entry.get("connection_id") == connection_id
    return entry.get("provider") == "google"


def sync_appointment_event(appointment: dict[str, Any], *, action: str, connections_repo=None, secret_cipher=None, google_secret=None, opener=None, connection=None):
    """Best-effort push. action='upsert' creates or updates the event; action='delete' removes it.
    Returns the appointment's new external_calendar_events list to persist, or None (no change).
    A specific `connection` document may be supplied (Phase 2 routing); otherwise the tenant's
    default connection is used."""
    try:
        client, connection_id = _client_for(str(appointment.get("tenant_id") or ""), connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener, connection=connection)
        if client is None:
            return None
        existing = list(appointment.get("external_calendar_events") or [])
        current = next((e for e in existing if _event_matches(e, connection_id)), None)
        others = [e for e in existing if e is not current]

        if action == "delete":
            if not current:
                return None
            try:
                client.delete_event(current.get("event_id"))
            except GoogleCalendarError:
                pass
            return others

        body = google_event_body(appointment)
        if current:
            client.update_event(current.get("event_id"), body)
            return others + [{"provider": "google", "connection_id": connection_id, "calendar_id": client.calendar_id, "event_id": current.get("event_id")}]
        created = client.create_event(body)
        return others + [{"provider": "google", "connection_id": connection_id, "calendar_id": client.calendar_id, "event_id": created.get("id")}]
    except Exception:  # noqa: BLE001 - calendar sync must never break a booking
        return None


def tenant_busy_intervals(tenant_id, time_min: str, time_max: str, *, connections_repo=None, secret_cipher=None, google_secret=None, opener=None, connection=None):
    """Best-effort free/busy read -> [{start, end}] the slot engine subtracts; [] if not connected."""
    try:
        client, _ = _client_for(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener, connection=connection)
        if client is None:
            return []
        return busy_intervals(client.free_busy(time_min, time_max), calendar_id=client.calendar_id)
    except Exception:  # noqa: BLE001
        return []
