import json
import os
import time
import unittest

from handlers.calendar import CONNECTION_ID, handler, resolve_tenant_calendar
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
    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, request, timeout=None):
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
            {"refresh_token": "tenant-rt", "access_token": "ya29", "scope": "https://www.googleapis.com/auth/calendar.events"},
            {"items": [{"id": "me@gmail.com", "primary": True}]},
        )
        resp = handler(event("GET", "/calendar/callback", tenant_id=None, params={"code": "AUTH", "state": "S1"}), None,
                       connections_repo=connections, states_repo=states, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("connected", resp["body"])
        conn = connections.get("t1", CONNECTION_ID)
        self.assertEqual(conn["status"], "connected")
        self.assertEqual(conn["account_email"], "me@gmail.com")
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


if __name__ == "__main__":
    unittest.main()
