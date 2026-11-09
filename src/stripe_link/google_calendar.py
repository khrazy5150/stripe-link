"""Google Calendar client — refresh-token -> access-token exchange plus event CRUD and
free/busy, over stdlib urllib (injectable opener for tests). Platform OAuth app credentials
+ the refresh token come from the caller (Secrets Manager for the platform test credential,
per-tenant CalendarConnection later)."""
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
#: ONE SCOPE PER METHOD WE CALL, and none that can reach a calendar the merchant already had
#: (plans/GOOGLE_CALENDAR_APP_CREATED.md, 2026-11-08).
#:
#:   calendar.app.created           -> calendars.insert/get + events.insert/update/delete, on calendars
#:                                     THIS APP CREATED and no others
#:   calendar.freebusy              -> freebusy.query, across the merchant's real calendars
#:   calendar.calendarlist.readonly -> calendarList.list: WHICH calendars count toward availability, and
#:                                     the account email we display
#:
#: `calendar.events.owned` is deliberately absent. Bookings live in a calendar the app creates, so no
#: write ever needs to reach a calendar the merchant already had -- which turns "we only touch our own
#: events" from a promise a reviewer must take on trust into a property of the API.
#:
#: calendarlist.readonly is NOT optional, however it reads: with bookings in their own calendar, a
#: free/busy query against that calendar alone would see only our own appointments and none of the
#: merchant's real commitments, which is the opposite of the point.
#:
#: CHANGING THIS FORCES EVERY CONNECTED TENANT TO RE-CONSENT.

#: The one scope that can make a calendar. Checked against a connection's STORED `scopes` before we try
#: to create one, because a connection granted before this change holds `calendar.events.owned` instead
#: and `calendars.insert` would 403 -- silently, since calendar sync swallows its own failures.
APP_CREATED_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"

DEFAULT_SCOPES = [
    APP_CREATED_SCOPE,
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


class GoogleCalendarError(RuntimeError):
    """Something went wrong talking to Google. The two subclasses below are the cases a CALLER can act
    on differently, and collapsing them into this one is how both became a 500."""


class GoogleCalendarNotConfigured(GoogleCalendarError):
    """This ENVIRONMENT has no Google credentials. Nobody's calendar works here, and no tenant can fix it.

    Found in prod on 2026-11-06: `template.yaml` points every environment at
    `jb/google-oauth/${Environment}`, and only `jb/google-oauth/dev` was ever created. So prod asked
    Secrets Manager for a secret that did not exist, boto3 raised `ResourceNotFoundException` -- which is
    not a `GoogleCalendarError` and was caught nowhere -- and every tenant who pressed "Connect Google
    Calendar" in production got an unhandled 500. The feature had never worked there, and nothing said so.
    """


class GoogleCalendarNotFound(GoogleCalendarError):
    """A 404 from Google. The CALLER decides what it means, because it has two meanings:

      * the bookings CALENDAR is gone -- the merchant deleted it outside the software, and the answer is
        to create another and store its id;
      * an EVENT is gone -- for a cancellation that is success, since the goal was for it not to exist.

    Both used to arrive as a bare `GoogleCalendarError`, so a cancellation that had already achieved what
    it asked for was reported as a failure.
    """


class GoogleCalendarReauthRequired(GoogleCalendarError):
    """This TENANT's refresh token is dead -- expired or revoked -- and only they can fix it, by
    reconnecting. Distinct from every other failure because it is the one with a user action attached.

    Google reports it as `invalid_grant`. It arrives routinely: a user revoking access in their Google
    account, a password change, and -- while the OAuth app is in `Testing` publishing status -- every
    refresh token simply expiring after seven days.
    """


def build_consent_url(client_id: str, redirect_uri: str, state: str, scopes: list[str] | None = None) -> str:
    """Build the Google OAuth consent URL. access_type=offline + prompt=consent guarantees a
    refresh token even if the account previously authorized the app."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes or DEFAULT_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str, redirect_uri: str, *, opener=None) -> dict:
    opener = opener or urlopen
    data = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    request = Request(GOOGLE_TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = _error_payload(exc)
        code_ = str(payload.get("error") or "")
        message = payload.get("error_description") or code_ or "authorization code exchange failed"
        # Same `invalid_grant`, different cause: here the one-time AUTH CODE is stale (already used, or
        # the tenant sat on the consent screen too long), not a refresh token. The remedy is the same --
        # start the connection again -- so it carries the same type.
        if code_ == "invalid_grant":
            raise GoogleCalendarReauthRequired(message) from exc
        raise GoogleCalendarError(message) from exc


def fetch_access_token(client_id: str, client_secret: str, refresh_token: str, *, opener=None) -> str:
    opener = opener or urlopen
    data = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = Request(GOOGLE_TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = _error_payload(exc)
        code = str(payload.get("error") or "")
        message = payload.get("error_description") or code or "token exchange failed"
        # `invalid_grant` is the one failure a TENANT can resolve, so it must not arrive looking like the
        # ones they cannot. Everything else here is ours or Google's.
        if code == "invalid_grant":
            raise GoogleCalendarReauthRequired(message) from exc
        raise GoogleCalendarError(message) from exc
    token = payload.get("access_token")
    if not token:
        raise GoogleCalendarError("Google did not return an access token.")
    return token


class GoogleCalendarClient:
    def __init__(self, access_token: str, *, calendar_id: str = "primary", opener=None):
        self.access_token = access_token
        self.calendar_id = calendar_id
        self.opener = opener or urlopen

    def _request(self, method: str, path: str, *, body=None, base: str = GOOGLE_CALENDAR_API):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{base}{path}", data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if exc.code == 404:
                raise GoogleCalendarNotFound(_error_payload(exc).get("error", {}).get("message")
                                             or "not found") from exc
            payload = _error_payload(exc)
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else (error or f"HTTP {exc.code}")
            raise GoogleCalendarError(message) from exc

    def _cal(self, calendar_id: str = "") -> str:
        """The calendar an operation addresses: an explicit id when given, else the connection's.

        **An existing event is addressed where it LIVES, not where we write today.** Moving the write
        target (as the app-created bookings calendar does) silently redirects every update and delete of
        an event created before the move, so the real event is never touched and the call reports success
        against a calendar it was never in.
        """
        return quote(calendar_id or self.calendar_id, safe="")

    def create_event(self, body: dict) -> dict:
        return self._request("POST", f"/calendars/{self._cal()}/events", body=body)

    def update_event(self, event_id: str, body: dict, calendar_id: str = "") -> dict:
        return self._request("PATCH", f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id, safe='')}",
                             body=body)

    def delete_event(self, event_id: str, calendar_id: str = "") -> bool:
        self._request("DELETE", f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id, safe='')}")
        return True

    def free_busy(self, time_min: str, time_max: str, calendar_ids=None) -> dict:
        """Busy intervals for one or more calendars in a single query.

        `calendar_ids` matters now that bookings live in their OWN calendar. Querying only that calendar
        would see our appointments and none of the merchant's real commitments -- the opposite of the
        point -- so the caller passes their real calendars AND the bookings calendar. `freebusy.query`
        takes them all at once, so this stays one request.
        """
        ids = [c for c in (calendar_ids or [self.calendar_id]) if c]
        return self._request("POST", "/freeBusy", body={
            "timeMin": time_min, "timeMax": time_max, "items": [{"id": c} for c in ids]})

    def get_calendar(self, calendar_id: str) -> dict:
        """One calendar by id. Raises `GoogleCalendarNotFound` when it is gone -- which is how we learn
        the merchant deleted the bookings calendar outside the software."""
        return self._request("GET", f"/calendars/{quote(calendar_id, safe='')}")

    def create_calendar(self, summary: str, time_zone: str = "") -> dict:
        """A secondary calendar owned by the connected account. `calendar.app.created` can only ever
        reach calendars created this way, which is the whole point of the scope."""
        body = {"summary": summary}
        if time_zone:
            body["timeZone"] = time_zone
        return self._request("POST", "/calendars", body=body)

    def calendar_list(self) -> dict:
        return self._request("GET", "/users/me/calendarList?maxResults=50")


def _error_payload(exc: HTTPError) -> dict:
    try:
        return json.loads(exc.read().decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        return {}


def load_google_oauth_secret(secret_name: str, *, client=None) -> dict:
    """Load {client_id, client_secret, refresh_token} from a Secrets Manager JSON secret."""
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION") or "us-west-2")
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except Exception as exc:  # noqa: BLE001 - absent, denied or unreadable all mean the same thing here
        # NAMED, not raised raw. The boto3 exception is not a GoogleCalendarError, so it escaped every
        # handler and became a 500 that said nothing about credentials.
        raise GoogleCalendarNotConfigured(
            f"No Google OAuth credentials are available in this environment (secret '{secret_name}')."
        ) from exc
    return json.loads(response.get("SecretString") or "{}")
