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

CONNECTION_ID = "google"
KMS_MODE = "calendar"
KMS_FIELD = "google_refresh_token"


def _google_secret(google_secret):
    if google_secret is not None:
        return google_secret
    name = os.environ.get("GOOGLE_OAUTH_SECRET_NAME", "")
    if not name:
        raise GoogleCalendarError("GOOGLE_OAUTH_SECRET_NAME is not configured.")
    return load_google_oauth_secret(name)


def resolve_tenant_calendar(tenant_id, *, connections_repo=None, secret_cipher=None, google_secret=None):
    """Return {client_id, client_secret, refresh_token, calendar_id} for a connected tenant
    (refresh token decrypted), or None if not connected."""
    connections_repo = connections_repo or calendar_connections_repository()
    conn = connections_repo.get(tenant_id, CONNECTION_ID)
    if not conn or conn.get("status") != "connected":
        return None
    creds = _google_secret(google_secret)
    secret_cipher = secret_cipher or KmsSecretCipher()
    return {
        "client_id": creds.get("client_id", ""),
        "client_secret": creds.get("client_secret", ""),
        "refresh_token": secret_cipher.decrypt(conn.get("refresh_token_ref", ""), tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD),
        "calendar_id": conn.get("calendar_id") or "primary",
    }


def _client_for(tenant_id, *, connections_repo, secret_cipher, google_secret, opener):
    creds = resolve_tenant_calendar(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret)
    if not creds:
        return None
    token = fetch_access_token(creds["client_id"], creds["client_secret"], creds["refresh_token"], opener=opener)
    return GoogleCalendarClient(token, calendar_id=creds["calendar_id"], opener=opener)


def sync_appointment_event(appointment: dict[str, Any], *, action: str, connections_repo=None, secret_cipher=None, google_secret=None, opener=None):
    """Best-effort push. action='upsert' creates or updates the event; action='delete' removes it.
    Returns the appointment's new external_calendar_events list to persist, or None (no change)."""
    try:
        client = _client_for(str(appointment.get("tenant_id") or ""), connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener)
        if client is None:
            return None
        existing = list(appointment.get("external_calendar_events") or [])
        google_ev = next((e for e in existing if e.get("provider") == "google"), None)

        if action == "delete":
            if not google_ev:
                return None
            try:
                client.delete_event(google_ev.get("event_id"))
            except GoogleCalendarError:
                pass
            return [e for e in existing if e.get("provider") != "google"]

        body = google_event_body(appointment)
        if google_ev:
            client.update_event(google_ev.get("event_id"), body)
            return existing
        created = client.create_event(body)
        return [e for e in existing if e.get("provider") != "google"] + [
            {"provider": "google", "calendar_id": client.calendar_id, "event_id": created.get("id")}
        ]
    except Exception:  # noqa: BLE001 - calendar sync must never break a booking
        return None


def tenant_busy_intervals(tenant_id, time_min: str, time_max: str, *, connections_repo=None, secret_cipher=None, google_secret=None, opener=None):
    """Best-effort free/busy read -> [{start, end}] the slot engine subtracts; [] if not connected."""
    try:
        client = _client_for(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener)
        if client is None:
            return []
        return busy_intervals(client.free_busy(time_min, time_max), calendar_id=client.calendar_id)
    except Exception:  # noqa: BLE001
        return []
