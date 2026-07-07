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
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class GoogleCalendarError(RuntimeError):
    pass


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
        raise GoogleCalendarError(payload.get("error_description") or payload.get("error") or "authorization code exchange failed") from exc


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
        raise GoogleCalendarError(payload.get("error_description") or payload.get("error") or "token exchange failed") from exc
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
            payload = _error_payload(exc)
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else (error or f"HTTP {exc.code}")
            raise GoogleCalendarError(message) from exc

    def _cal(self) -> str:
        return quote(self.calendar_id, safe="")

    def create_event(self, body: dict) -> dict:
        return self._request("POST", f"/calendars/{self._cal()}/events", body=body)

    def update_event(self, event_id: str, body: dict) -> dict:
        return self._request("PATCH", f"/calendars/{self._cal()}/events/{quote(event_id, safe='')}", body=body)

    def delete_event(self, event_id: str) -> bool:
        self._request("DELETE", f"/calendars/{self._cal()}/events/{quote(event_id, safe='')}")
        return True

    def free_busy(self, time_min: str, time_max: str) -> dict:
        return self._request("POST", "/freeBusy", body={"timeMin": time_min, "timeMax": time_max, "items": [{"id": self.calendar_id}]})

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
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response.get("SecretString") or "{}")
