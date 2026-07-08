import json
import unittest

from stripe_link.calendar_sync import sync_appointment_event, tenant_busy_intervals
from tests.fakes import FakeDocumentRepository

GOOGLE_SECRET = {"client_id": "cid", "client_secret": "sec"}
APPOINTMENT = {
    "tenant_id": "t1", "appointment_id": "appt_1", "service_name": "Massage",
    "starts_at": "2026-07-08T15:00:00Z", "ends_at": "2026-07-08T16:00:00Z",
    "customer": {"name": "Casey", "email": "c@e.com"},
}


class FakeCipher:
    def decrypt(self, ref, *, tenant_id, mode, field):
        return ref[4:] if ref.startswith("enc:") else ref


class _FakeResp:
    def __init__(self, payload):
        self._d = json.dumps(payload).encode("utf-8") if payload is not None else b""

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


def connected_repo():
    repo = FakeDocumentRepository("connection_id")
    repo.put({"tenant_id": "t1", "connection_id": "google", "status": "connected",
              "calendar_id": "me@gmail.com", "refresh_token_ref": "enc:rt"})
    return repo


def sync(appointment, action, opener):
    return sync_appointment_event(appointment, action=action, connections_repo=connected_repo(),
                                  secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)


class SyncAppointmentEventTests(unittest.TestCase):
    def test_upsert_creates_event(self):
        events = sync(APPOINTMENT, "upsert", _FakeOpener({"access_token": "ya29"}, {"id": "evt_1"}))
        self.assertEqual(events, [{"provider": "google", "connection_id": "google", "calendar_id": "me@gmail.com", "event_id": "evt_1"}])

    def test_upsert_updates_existing_event(self):
        appt = {**APPOINTMENT, "external_calendar_events": [{"provider": "google", "calendar_id": "me@gmail.com", "event_id": "evt_1"}]}
        events = sync(appt, "upsert", _FakeOpener({"access_token": "ya29"}, {"id": "evt_1"}))
        self.assertEqual(events[0]["event_id"], "evt_1")

    def test_delete_removes_event(self):
        appt = {**APPOINTMENT, "external_calendar_events": [{"provider": "google", "calendar_id": "me@gmail.com", "event_id": "evt_1"}]}
        events = sync(appt, "delete", _FakeOpener({"access_token": "ya29"}, None))
        self.assertEqual(events, [])

    def test_delete_without_event_is_noop(self):
        self.assertIsNone(sync(APPOINTMENT, "delete", _FakeOpener({"access_token": "ya29"})))

    def test_not_connected_returns_none(self):
        result = sync_appointment_event(APPOINTMENT, action="upsert",
                                        connections_repo=FakeDocumentRepository("connection_id"),
                                        secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=_FakeOpener())
        self.assertIsNone(result)

    def test_failure_is_swallowed(self):
        class Boom:
            def __call__(self, *a, **k):
                raise RuntimeError("network down")
        # token fetch raises -> best-effort returns None, never propagates
        self.assertIsNone(sync(APPOINTMENT, "upsert", Boom()))

    def test_tenant_busy_intervals(self):
        opener = _FakeOpener({"access_token": "ya29"}, {"calendars": {"me@gmail.com": {"busy": [{"start": "a", "end": "b"}]}}})
        busy = tenant_busy_intervals("t1", "2026-07-08T00:00:00Z", "2026-07-15T00:00:00Z",
                                     connections_repo=connected_repo(), secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET, opener=opener)
        self.assertEqual(busy, [{"start": "a", "end": "b"}])


if __name__ == "__main__":
    unittest.main()
