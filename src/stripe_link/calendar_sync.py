"""Calendar sync — resolve a tenant's connected calendar and push/read against it.

All functions are best-effort: a calendar failure must never break a booking. sync_appointment_event
returns the new external_calendar_events list to persist (or None for "no change"); tenant_busy_intervals
returns busy windows for the slot engine (or [] when not connected / on error).
"""
import logging
import os
import time
from typing import Any

from stripe_link.domain.calendar import busy_intervals, google_event_body
from stripe_link.google_calendar import (
    APP_CREATED_SCOPE,
    GoogleCalendarClient,
    GoogleCalendarError,
    GoogleCalendarNotFound,
    GoogleCalendarReauthRequired,
    fetch_access_token,
    load_google_oauth_secret,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import calendar_connections_repository

logger = logging.getLogger(__name__)

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
        # Empty for a connection made before bookings got their own calendar. The ABSENCE is meaningful:
        # it is how the read path tells a legacy connection (events in `calendar_id`) from a current one,
        # so it must not be defaulted to anything.
        "bookings_calendar_id": conn.get("bookings_calendar_id") or "",
        "connection": conn,
    }


#: What the merchant sees in their calendar list. Human-readable on purpose -- a slug like
#: "junior-bay-booking" is an internal name leaking onto a user-facing surface.
BOOKINGS_CALENDAR_SUMMARY = "Junior Bay Bookings"


def resolve_bookings_calendar(client, conn, connections_repo=None) -> tuple[str, bool]:
    """The id of this connection's bookings calendar, creating it if there is not one. `(id, created)`.

    **Resolved by STORED ID, never by name.** A merchant who renames it to "Appointments" would otherwise
    get a second calendar on the next connect, and bookings would split across two with no sign of it.

    A 404 on the stored id means the merchant deleted the calendar outside the software. There is nothing
    to clean up -- it is already gone -- so we create another and store the new id. Appointments booked
    before the deletion keep event ids that now point nowhere; cancelling one later is handled by the
    event-404 rule, which treats "already absent" as the success it is.
    """
    stored = str((conn or {}).get("bookings_calendar_id") or "").strip()
    if stored:
        try:
            client.get_calendar(stored)
            return stored, False
        except GoogleCalendarNotFound:
            logger.info("calendar: bookings calendar %s is gone; creating another", stored)
    created = client.create_calendar(BOOKINGS_CALENDAR_SUMMARY)
    calendar_id = str(created.get("id") or "")
    if not calendar_id:
        raise GoogleCalendarError("Google did not return an id for the new calendar.")
    if connections_repo is not None and conn:
        try:
            connections_repo.put({**conn, "bookings_calendar_id": calendar_id,
                                  "updated_at": int(time.time())})
        except Exception:  # noqa: BLE001 - the calendar exists; failing to record it must not lose it
            logger.exception("calendar: created %s but could not store it on the connection", calendar_id)
    return calendar_id, True


#: `accessRole` values that mean "this is the merchant's own time". A merchant is typically subscribed to
#: read-only public calendars -- "Holidays in United States", "Phases of the Moon" -- whose all-day events
#: would otherwise mark whole days busy and close the business on every public holiday by accident.
#: `reader` and `freeBusyReader` are calendars they WATCH; `owner` and `writer` are calendars they keep.
BUSY_ACCESS_ROLES = frozenset({"owner", "writer"})


def availability_calendar_ids(client, bookings_calendar_id: str = "") -> list[str]:
    """The calendars a free/busy query must cover: the merchant's own, plus the bookings calendar.

    Both halves are needed and for opposite reasons. Without the merchant's real calendars we would offer
    a slot they are already committed for; without the bookings calendar two customers could take the same
    slot. Querying only the bookings calendar -- the naive reading of "bookings live in their own
    calendar" -- gets exactly the second half and loses the first.

    The bookings calendar is appended explicitly rather than trusted to appear in `calendarList`, because
    whether an app-created calendar is listed under these scopes is not something to find out from a
    double booking.
    """
    ids: list[str] = []
    try:
        for cal in (client.calendar_list().get("items") or []):
            cid = str(cal.get("id") or "")
            if cid and cal.get("accessRole") in BUSY_ACCESS_ROLES:
                ids.append(cid)
    except GoogleCalendarError:
        # Say which half we lost. Falling back silently to the bookings calendar alone looks like a
        # working availability check and offers slots the merchant is busy for.
        logger.exception("calendar: could not list calendars for availability; "
                         "only the bookings calendar will block slots")
    if bookings_calendar_id and bookings_calendar_id not in ids:
        ids.append(bookings_calendar_id)
    return ids


def mark_revoked(tenant_id: str, connection_id: str, connections_repo=None) -> bool:
    """Record that Google has rejected this connection's refresh token, and DROP the token.

    Google reports a revoked or expired grant as `invalid_grant`. Until 2026-11-08 nothing acted on it:
    the call failed, the booking did not sync, and the dead credential stayed encrypted in our table
    indefinitely -- so the privacy policy's claim that revoking access leads to deletion was simply not
    true. Now revocation is observed the first time we try to use the connection, and the credential is
    removed at that moment rather than waiting for the merchant to press disconnect.

    `status: "revoked"` (the schema already allowed it) stops `resolve_tenant_calendar` resolving this
    connection, so nothing keeps retrying a token Google has refused.

    Idempotent, and best-effort: this runs inside an exception path that is about to re-raise, and
    failing to record the revocation must not replace the error the caller needs to see.
    """
    try:
        repo = connections_repo or calendar_connections_repository()
        conn = repo.get(tenant_id, connection_id)
        if not conn or conn.get("status") == "revoked":
            return False
        conn["status"] = "revoked"
        # The token is the thing worth deleting. It is useless -- Google has refused it -- and keeping a
        # credential we cannot use is exactly what the policy says we do not do.
        conn["refresh_token_ref"] = ""
        conn["revoked_at"] = int(time.time())
        conn["updated_at"] = conn["revoked_at"]
        repo.put(conn)
        return True
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("calendar: could not mark %s/%s revoked", tenant_id, connection_id)
        return False


def _client_for(tenant_id, *, connections_repo, secret_cipher, google_secret, opener, connection=None,
                create_bookings_calendar=True):
    """Return (client, connection_id, bookings_calendar_id) for the resolved calendar, or (None, None, "").

    The client's `calendar_id` is **where new events go**: the bookings calendar once a connection has
    one, the legacy `calendar_id` while it does not.

    `create_bookings_calendar=False` is for read-only callers. Creating a calendar is a write, and the
    availability check runs on a public page every time a customer opens the slot picker -- a concurrent
    pair of those with nothing stored yet would create two calendars. A connection with no bookings
    calendar also has no bookings in one, so there is nothing for a read to miss by not creating it.
    """
    connections_repo = connections_repo or calendar_connections_repository()
    creds = resolve_tenant_calendar(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, connection=connection)
    if not creds:
        return None, None, ""
    try:
        token = fetch_access_token(creds["client_id"], creds["client_secret"], creds["refresh_token"], opener=opener)
    except GoogleCalendarReauthRequired:
        # The merchant revoked us, or the grant expired. Record it and drop the dead credential HERE --
        # this is the only moment we learn of it, since Google does not tell us.
        mark_revoked(tenant_id, creds["connection_id"], connections_repo)
        raise
    client = GoogleCalendarClient(token, calendar_id=creds["calendar_id"], opener=opener)
    bookings_calendar_id = creds["bookings_calendar_id"]
    # ONLY IF THE MERCHANT ACTUALLY GRANTED IT. A connection made before this change holds
    # `calendar.events.owned` and writes to `calendar_id`; asking it to create a calendar gets a 403 that
    # `sync_appointment_event` swallows, so its bookings would stop reaching any calendar at all and
    # nothing would say so. Absent `scopes` counts as not granted -- the conservative branch.
    if create_bookings_calendar and APP_CREATED_SCOPE in set(creds["connection"].get("scopes") or []):
        bookings_calendar_id, _ = resolve_bookings_calendar(client, creds["connection"], connections_repo)
    if bookings_calendar_id:
        client.calendar_id = bookings_calendar_id
    return client, creds["connection_id"], bookings_calendar_id


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
        # A cancellation never needs a calendar CREATED: if there is no bookings calendar there is no
        # event in one to remove.
        client, connection_id, _ = _client_for(str(appointment.get("tenant_id") or ""), connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener, connection=connection, create_bookings_calendar=(action != "delete"))
        if client is None:
            return None
        existing = list(appointment.get("external_calendar_events") or [])
        current = next((e for e in existing if _event_matches(e, connection_id)), None)
        others = [e for e in existing if e is not current]
        # WHERE THE EVENT LIVES, which is not necessarily where we write today: an appointment booked
        # before this connection moved to an app-created bookings calendar holds the old calendar's id.
        lives_in = str((current or {}).get("calendar_id") or "")

        if action == "delete":
            if not current:
                return None
            try:
                client.delete_event(current.get("event_id"), calendar_id=lives_in)
            except GoogleCalendarNotFound:
                # Already absent, which is exactly what a cancellation wanted. Not a failure.
                pass
            except GoogleCalendarError:
                # Anything else -- a 403 on a calendar the current scopes can no longer reach, say -- and
                # the event is still sitting in the merchant's calendar. We drop the reference either way
                # because retrying will not help, but this must be findable rather than silent.
                logger.exception("calendar: could not delete event %s from %s; it may still be in the "
                                 "merchant's calendar", current.get("event_id"), lives_in or client.calendar_id)
            return others

        body = google_event_body(appointment)
        if current:
            try:
                client.update_event(current.get("event_id"), body, calendar_id=lives_in)
                return others + [{"provider": "google", "connection_id": connection_id, "calendar_id": lives_in or client.calendar_id, "event_id": current.get("event_id")}]
            except GoogleCalendarNotFound:
                # The event is gone -- the merchant deleted it, or it lived in a bookings calendar that
                # has since been deleted. A reschedule should put the appointment back, not fail because
                # the thing it meant to move is missing. Recreated in the CURRENT calendar, not the one
                # it used to live in.
                logger.info("calendar: event %s is gone; recreating it", current.get("event_id"))
            except GoogleCalendarError:
                if lives_in == client.calendar_id:
                    raise
                # It lives in a calendar we can no longer write to -- a pre-migration event in the
                # merchant's primary calendar, now that our only grant reaches the app's own calendar.
                # Recreate it where we CAN write. The old event is orphaned there and we cannot remove
                # it, which is visible and fixable; the alternative is a silent no-op that leaves their
                # calendar showing the old time while the platform shows the new one, and they turn up
                # at the wrong one.
                logger.warning("calendar: cannot reach event %s in %s; recreating the booking in %s and "
                               "leaving the original behind", current.get("event_id"), lives_in,
                               client.calendar_id)
        created = client.create_event(body)
        return others + [{"provider": "google", "connection_id": connection_id, "calendar_id": client.calendar_id, "event_id": created.get("id")}]
    except Exception:  # noqa: BLE001 - calendar sync must never break a booking
        return None


def tenant_busy_intervals(tenant_id, time_min: str, time_max: str, *, connections_repo=None, secret_cipher=None, google_secret=None, opener=None, connection=None):
    """Best-effort free/busy read -> [{start, end}] the slot engine subtracts; [] if not connected."""
    try:
        client, _, bookings_calendar_id = _client_for(tenant_id, connections_repo=connections_repo, secret_cipher=secret_cipher, google_secret=google_secret, opener=opener, connection=connection, create_bookings_calendar=False)
        if client is None:
            return []
        if not bookings_calendar_id:
            # A legacy connection: its events are in `calendar_id` and that is the whole picture. Left
            # exactly as it was rather than widened to every owned calendar, so moving to the new design
            # cannot quietly start closing slots on a tenant who has not reconnected.
            ids = [client.calendar_id]
        else:
            ids = availability_calendar_ids(client, bookings_calendar_id)
        return busy_intervals(client.free_busy(time_min, time_max, ids), calendar_id=ids)
    except Exception:  # noqa: BLE001
        return []
