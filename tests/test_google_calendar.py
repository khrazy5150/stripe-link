import json
import unittest

from stripe_link.domain.calendar import busy_intervals, google_event_body
from stripe_link.google_calendar import GoogleCalendarClient, fetch_access_token

APPOINTMENT = {
    "appointment_id": "appt_1", "tenant_id": "t1",
    "services": [{"service_id": "svc_1", "service_name": "Massage", "price_id": "svcprice_svc_1", "duration_minutes": 60}],
    "starts_at": "2026-07-08T15:00:00Z", "ends_at": "2026-07-08T16:00:00Z",
    "customer": {"name": "Casey", "email": "c@e.com", "phone": "+15551234567"},
}


class _FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8") if payload is not None else b""

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return _FakeResponse(self.responses.pop(0))


class CalendarDomainTests(unittest.TestCase):
    def test_google_event_body(self):
        body = google_event_body(APPOINTMENT)
        self.assertEqual(body["summary"], "Massage — Casey")
        self.assertEqual(body["start"]["dateTime"], "2026-07-08T15:00:00Z")
        self.assertEqual(body["end"]["dateTime"], "2026-07-08T16:00:00Z")
        self.assertEqual(body["extendedProperties"]["private"]["appointment_id"], "appt_1")
        self.assertIn("+15551234567", body["description"])

    def test_busy_intervals(self):
        resp = {"calendars": {"primary": {"busy": [{"start": "2026-07-08T15:00:00Z", "end": "2026-07-08T16:00:00Z"}]}}}
        self.assertEqual(busy_intervals(resp), [{"start": "2026-07-08T15:00:00Z", "end": "2026-07-08T16:00:00Z"}])


class GoogleCalendarClientTests(unittest.TestCase):
    def test_fetch_access_token(self):
        opener = _FakeOpener({"access_token": "ya29.test", "expires_in": 3599})
        token = fetch_access_token("cid", "secret", "refresh", opener=opener)
        self.assertEqual(token, "ya29.test")
        self.assertEqual(self._method(opener.requests[0]), "POST")

    def test_create_event_posts_body(self):
        opener = _FakeOpener({"id": "evt_1"})
        client = GoogleCalendarClient("ya29.test", opener=opener)
        result = client.create_event(google_event_body(APPOINTMENT))
        self.assertEqual(result["id"], "evt_1")
        request = opener.requests[0]
        self.assertEqual(self._method(request), "POST")
        self.assertIn("/calendars/primary/events", request.full_url)
        self.assertEqual(request.headers["Authorization"], "Bearer ya29.test")

    def test_update_and_delete(self):
        opener = _FakeOpener({"id": "evt_1"}, None)
        client = GoogleCalendarClient("ya29.test", opener=opener)
        client.update_event("evt_1", {"summary": "x"})
        self.assertTrue(client.delete_event("evt_1"))
        self.assertEqual(self._method(opener.requests[0]), "PATCH")
        self.assertEqual(self._method(opener.requests[1]), "DELETE")

    def test_free_busy(self):
        opener = _FakeOpener({"calendars": {"primary": {"busy": [{"start": "a", "end": "b"}]}}})
        client = GoogleCalendarClient("ya29.test", opener=opener)
        resp = client.free_busy("2026-07-08T00:00:00Z", "2026-07-15T00:00:00Z")
        self.assertEqual(busy_intervals(resp), [{"start": "a", "end": "b"}])

    def _method(self, request):
        return request.get_method()


if __name__ == "__main__":
    unittest.main()
