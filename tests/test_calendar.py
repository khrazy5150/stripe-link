import json
import os
import time
import unittest

from handlers.calendar import handler, resolve_tenant_calendar
from stripe_link.google_calendar import DEFAULT_SCOPES
from tests.fakes import FakeDocumentRepository

GOOGLE_SECRET = {"client_id": "cid", "client_secret": "sec", "refresh_token": "platform-rt"}


class FakeCipher:
    def encrypt(self, plaintext, *, tenant_id, mode, field):
        return f"enc:{plaintext}"

    def decrypt(self, ref, *, tenant_id, mode, field):
        return ref[4:] if ref.startswith("enc:") else ref


class _FakeResp:
    def __init__(self, payload):
        self._d = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeOpener:
    """Answers the token exchange and calendarList from a queue, and `calendars.insert` by URL.

    Creating the bookings calendar is a POST to /calendars in the middle of the connect flow. A pure
    positional queue handed it the calendarList response and every later call the wrong one -- order is
    not what these tests are asserting, so the one call that is about to be added is routed by URL.
    """

    def __init__(self, *responses, calendar=None):
        self.responses = list(responses)
        self.calendar = calendar if calendar is not None else {"id": "jb_bookings@group.calendar.google.com"}
        self.seen = []

    def __call__(self, request, timeout=None):
        self.seen.append((request.method, request.full_url))
        if request.full_url.rsplit("?", 1)[0].rstrip("/").endswith("/calendars"):
            return _FakeResp(self.calendar)          # calendars.insert
        if "/calendars/" in request.full_url and request.method == "GET":
            return _FakeResp(self.calendar)          # calendars.get -- the stored id still exists
        return _FakeResp(self.responses.pop(0))


def event(method, path, *, tenant_id="t1", params=None):
    q = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    q.update(params or {})
    return {"httpMethod": method, "path": path, "queryStringParameters": q}


class CalendarConnectTests(unittest.TestCase):
    def setUp(self):
        os.environ["CALENDAR_REDIRECT_URI"] = "https://dev.example.com/calendar/callback"

    def test_connect_returns_url_and_stores_state(self):
        states = FakeDocumentRepository("state_id")
        resp = handler(event("POST", "/calendar/connect"), None,
                       connections_repo=FakeDocumentRepository("connection_id"), states_repo=states, google_secret=GOOGLE_SECRET)
        body = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("accounts.google.com", body["authorize_url"])
        self.assertIn("access_type=offline", body["authorize_url"])
        self.assertEqual(len(states.list_for_tenant("t1")), 1)

    def test_callback_stores_connection(self):
        states = FakeDocumentRepository("state_id")
        connections = FakeDocumentRepository("connection_id")
        states.put({"tenant_id": "t1", "state_id": "S1", "document_type": "oauth_state", "expires_at": int(time.time()) + 600})
        opener = _FakeOpener(
            {"refresh_token": "tenant-rt", "access_token": "ya29", "scope": "https://www.googleapis.com/auth/calendar.app.created https://www.googleapis.com/auth/calendar.calendarlist.readonly https://www.googleapis.com/auth/calendar.freebusy"},
            {"items": [{"id": "me@gmail.com", "primary": True}]},
        )
        resp = handler(event("GET", "/calendar/callback", tenant_id=None, params={"code": "AUTH", "state": "S1"}), None,
                       connections_repo=connections, states_repo=states, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("connected", resp["body"])
        stored = connections.list_for_tenant("t1")
        self.assertEqual(len(stored), 1)
        conn = stored[0]
        self.assertTrue(conn["connection_id"].startswith("cal_"))  # generated id, not hardcoded
        self.assertTrue(conn["is_default"])  # first connection is the default
        self.assertEqual(conn["status"], "connected")
        self.assertEqual(conn["account_email"], "me@gmail.com")
        self.assertEqual(conn["display_name"], "me@gmail.com")
        self.assertEqual(conn["refresh_token_ref"], "enc:tenant-rt")
        self.assertIsNone(states.get("t1", "S1"))  # single-use consumed

    def test_callback_expired_state(self):
        states = FakeDocumentRepository("state_id")
        states.put({"tenant_id": "t1", "state_id": "S1", "document_type": "oauth_state", "expires_at": int(time.time()) - 1})
        resp = handler(event("GET", "/calendar/callback", tenant_id=None, params={"code": "c", "state": "S1"}), None,
                       connections_repo=FakeDocumentRepository("connection_id"), states_repo=states, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=_FakeOpener())
        self.assertEqual(resp["statusCode"], 400)

    def test_callback_missing_refresh_token(self):
        states = FakeDocumentRepository("state_id")
        states.put({"tenant_id": "t1", "state_id": "S1", "document_type": "oauth_state", "expires_at": int(time.time()) + 600})
        resp = handler(event("GET", "/calendar/callback", tenant_id=None, params={"code": "c", "state": "S1"}), None,
                       connections_repo=FakeDocumentRepository("connection_id"), states_repo=states, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=_FakeOpener({"access_token": "ya29"}))
        self.assertEqual(resp["statusCode"], 400)

    def test_status_and_disconnect(self):
        connections = FakeDocumentRepository("connection_id")
        connections.put({"tenant_id": "t1", "connection_id": "google", "provider": "google", "status": "connected",
                         "account_email": "me@gmail.com", "calendar_id": "me@gmail.com"})
        status = handler(event("GET", "/calendar/connection"), None, connections_repo=connections)
        self.assertTrue(json.loads(status["body"])["connected"])
        disc = handler(event("DELETE", "/calendar/connection"), None, connections_repo=connections)
        self.assertTrue(json.loads(disc["body"])["disconnected"])
        self.assertIsNone(connections.get("t1", "google"))

    def test_resolve_tenant_calendar_decrypts(self):
        connections = FakeDocumentRepository("connection_id")
        connections.put({"tenant_id": "t1", "connection_id": "google", "provider": "google", "status": "connected",
                         "calendar_id": "me@gmail.com", "refresh_token_ref": "enc:tenant-rt"})
        creds = resolve_tenant_calendar("t1", connections_repo=connections, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET)
        self.assertEqual(creds["refresh_token"], "tenant-rt")
        self.assertEqual(creds["calendar_id"], "me@gmail.com")
        self.assertEqual(creds["client_id"], "cid")

    def test_resolve_returns_none_when_not_connected(self):
        self.assertIsNone(resolve_tenant_calendar("t1", connections_repo=FakeDocumentRepository("connection_id"), secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET))


def _connect(connections, account_email, calendar=None):
    """Run the OAuth callback for a given account, returning the stored connection."""
    states = FakeDocumentRepository("state_id")
    states.put({"tenant_id": "t1", "state_id": "S", "document_type": "oauth_state", "expires_at": int(time.time()) + 600})
    opener = _FakeOpener(
        {"refresh_token": f"rt-{account_email}", "access_token": "ya29", "scope": "https://www.googleapis.com/auth/calendar.app.created https://www.googleapis.com/auth/calendar.calendarlist.readonly https://www.googleapis.com/auth/calendar.freebusy"},
        {"items": [{"id": account_email, "primary": True}]},
        calendar=calendar,
    )
    handler(event("GET", "/calendar/callback", tenant_id=None, params={"code": "AUTH", "state": "S"}), None,
            connections_repo=connections, states_repo=states, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)
    return next(c for c in connections.list_for_tenant("t1") if c["account_email"] == account_email)


class MultiConnectionTests(unittest.TestCase):
    def setUp(self):
        os.environ["CALENDAR_REDIRECT_URI"] = "https://dev.example.com/calendar/callback"

    def test_second_account_is_new_non_default_connection(self):
        connections = FakeDocumentRepository("connection_id")
        first = _connect(connections, "a@gmail.com")
        second = _connect(connections, "b@gmail.com")
        self.assertNotEqual(first["connection_id"], second["connection_id"])
        self.assertTrue(first["is_default"])
        self.assertFalse(second["is_default"])
        self.assertEqual(len(connections.list_for_tenant("t1")), 2)

    def test_reconnect_same_account_updates_in_place(self):
        connections = FakeDocumentRepository("connection_id")
        first = _connect(connections, "a@gmail.com")
        again = _connect(connections, "a@gmail.com")
        self.assertEqual(first["connection_id"], again["connection_id"])
        self.assertEqual(len(connections.list_for_tenant("t1")), 1)

    def test_connecting_stores_the_bookings_calendar_id(self):
        """Resolved during the callback so it lands in the SAME write as the rest of the connection -- a
        second write afterwards is a second chance to half-finish."""
        connections = FakeDocumentRepository("connection_id")
        conn = _connect(connections, "a@gmail.com")
        self.assertEqual(conn["bookings_calendar_id"], "jb_bookings@group.calendar.google.com")

    def test_reconnecting_reuses_the_calendar_instead_of_making_a_second_one(self):
        """Keyed on the stored id, never the name: a merchant who renames it to "Appointments" would
        otherwise get a second calendar and bookings split across two with no sign of it."""
        connections = FakeDocumentRepository("connection_id")
        first = _connect(connections, "a@gmail.com")
        again = _connect(connections, "a@gmail.com", calendar={"id": "SHOULD-NOT-BE-USED"})
        self.assertEqual(again["bookings_calendar_id"], first["bookings_calendar_id"])

    def test_the_merchant_is_told_where_bookings_go(self):
        """The one real cost of a separate calendar is that a phone may not show a newly added one until
        it is switched on there. Said now, not learned weeks later from a booking that never appeared."""
        states = FakeDocumentRepository("state_id")
        states.put({"tenant_id": "t1", "state_id": "S", "document_type": "oauth_state",
                    "expires_at": int(time.time()) + 600})
        opener = _FakeOpener(
            {"refresh_token": "rt", "access_token": "ya29", "scope": " ".join(DEFAULT_SCOPES)},
            {"items": [{"id": "a@gmail.com", "primary": True}]},
        )
        resp = handler(event("GET", "/calendar/callback", tenant_id=None,
                             params={"code": "AUTH", "state": "S"}), None,
                       connections_repo=FakeDocumentRepository("connection_id"), states_repo=states,
                       secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("Junior Bay Bookings", resp["body"])
        self.assertIn("switch that calendar on", resp["body"])

    def test_list_returns_connections_without_token_ref(self):
        connections = FakeDocumentRepository("connection_id")
        _connect(connections, "a@gmail.com")
        resp = handler(event("GET", "/calendar/connections"), None, connections_repo=connections)
        body = json.loads(resp["body"])
        self.assertEqual(body["count"], 1)
        self.assertNotIn("refresh_token_ref", body["connections"][0])
        self.assertTrue(body["connections"][0]["is_default"])

    def test_patch_sets_default_and_clears_prior(self):
        connections = FakeDocumentRepository("connection_id")
        first = _connect(connections, "a@gmail.com")
        second = _connect(connections, "b@gmail.com")
        resp = handler({**event("PATCH", "/calendar/connections/x"), "pathParameters": {"connection_id": second["connection_id"]},
                        "body": json.dumps({"is_default": True, "display_name": "Salon B"})}, None, connections_repo=connections)
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(connections.get("t1", second["connection_id"])["is_default"])
        self.assertFalse(connections.get("t1", first["connection_id"])["is_default"])
        self.assertEqual(connections.get("t1", second["connection_id"])["display_name"], "Salon B")

    def test_delete_default_promotes_next(self):
        connections = FakeDocumentRepository("connection_id")
        first = _connect(connections, "a@gmail.com")
        second = _connect(connections, "b@gmail.com")
        handler({**event("DELETE", "/calendar/connections/x"), "pathParameters": {"connection_id": first["connection_id"]}},
                None, connections_repo=connections)
        self.assertIsNone(connections.get("t1", first["connection_id"]))
        self.assertTrue(connections.get("t1", second["connection_id"])["is_default"])  # promoted

    def test_resolve_prefers_is_default(self):
        connections = FakeDocumentRepository("connection_id")
        connections.put({"tenant_id": "t1", "connection_id": "cal_a", "provider": "google", "status": "connected",
                         "calendar_id": "a@gmail.com", "refresh_token_ref": "enc:rt-a", "connected_at": 100})
        connections.put({"tenant_id": "t1", "connection_id": "cal_b", "provider": "google", "status": "connected",
                         "calendar_id": "b@gmail.com", "refresh_token_ref": "enc:rt-b", "is_default": True, "connected_at": 200})
        creds = resolve_tenant_calendar("t1", connections_repo=connections, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET)
        self.assertEqual(creds["connection_id"], "cal_b")
        self.assertEqual(creds["calendar_id"], "b@gmail.com")


if __name__ == "__main__":
    unittest.main()
