import json
import unittest
from datetime import datetime, timezone

from handlers.booking import handler
from stripe_link.domain.scheduling import available_slots
from tests.fakes import FakeDocumentRepository

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def epoch(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


def weekly(start="09:00", end="17:00", enabled_days=("mon", "tue", "wed", "thu", "fri")):
    return [{"day": d, "enabled": d in enabled_days, "start_time": start, "end_time": end} for d in DAYS]


def tenant_avail(**overrides):
    base = {
        "timezone": "America/Denver",
        "slot_interval_minutes": 60,
        "lead_time_minutes": 0,
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0,
        "weekly_hours": weekly(),
    }
    base.update(overrides)
    return base


SERVICE = {"service_id": "svc_1", "tenant_id": "t1", "duration_minutes": 60, "active": True}
# 2026-07-08 is a Wednesday; Denver is MDT (UTC-6), so 09:00 local == 15:00Z.
WED_START = epoch(2026, 7, 8, 0, 0)
WED_END = epoch(2026, 7, 9, 12, 0)


def appt(start, end, status="booked", **extra):
    return {"appointment_id": "a", "status": status, "starts_at": start, "ends_at": end, **extra}


class SlotEngineTests(unittest.TestCase):
    def slots(self, service=SERVICE, availability=None, fulfillers=None, exceptions=None, appointments=None,
              now=WED_START, start=WED_START, end=WED_END, fulfiller_id=None):
        return available_slots(
            service, availability or tenant_avail(), fulfillers or [], exceptions or [], appointments or [],
            now_epoch=now, range_start_epoch=start, range_end_epoch=end, fulfiller_id=fulfiller_id,
        )

    def test_basic_weekday_hours(self):
        slots = self.slots()
        self.assertEqual(len(slots), 8)  # 09:00..16:00
        self.assertEqual(slots[0]["start"], "2026-07-08T15:00:00Z")
        self.assertEqual(slots[0]["end"], "2026-07-08T16:00:00Z")

    def test_lead_time_pushes_to_next_day(self):
        slots = self.slots(availability=tenant_avail(lead_time_minutes=24 * 60), end=epoch(2026, 7, 10, 0, 0))
        self.assertTrue(slots)
        self.assertTrue(all(s["start"].startswith("2026-07-09") for s in slots))

    def test_existing_appointment_blocks_its_slot(self):
        # Denver 10:00-11:00 == 16:00-17:00Z
        slots = self.slots(appointments=[appt("2026-07-08T16:00:00Z", "2026-07-08T17:00:00Z")])
        self.assertEqual(len(slots), 7)
        self.assertNotIn("2026-07-08T16:00:00Z", [s["start"] for s in slots])

    def test_buffers_expand_blocked_window(self):
        slots = self.slots(
            availability=tenant_avail(buffer_before_minutes=15, buffer_after_minutes=15),
            appointments=[appt("2026-07-08T16:00:00Z", "2026-07-08T17:00:00Z")],
        )
        # 09:00, 10:00, 11:00 local all collide with the 15-min-buffered window
        self.assertEqual(len(slots), 5)

    def test_block_exception_removes_slots(self):
        # Denver 13:00-15:00 == 19:00-21:00Z
        slots = self.slots(exceptions=[{"type": "block", "fulfiller_scope": "all",
                                        "starts_at": "2026-07-08T19:00:00Z", "ends_at": "2026-07-08T21:00:00Z"}])
        starts = [s["start"] for s in slots]
        self.assertNotIn("2026-07-08T19:00:00Z", starts)
        self.assertNotIn("2026-07-08T20:00:00Z", starts)
        self.assertEqual(len(slots), 6)

    def test_expired_reserved_hold_does_not_block(self):
        active = self.slots(appointments=[appt("2026-07-08T16:00:00Z", "2026-07-08T17:00:00Z", status="reserved", hold_expires_at=WED_END)])
        expired = self.slots(appointments=[appt("2026-07-08T16:00:00Z", "2026-07-08T17:00:00Z", status="reserved", hold_expires_at=WED_START - 10)])
        self.assertEqual(len(active), 7)   # active hold blocks
        self.assertEqual(len(expired), 8)  # expired hold does not

    def test_canceled_appointment_does_not_block(self):
        slots = self.slots(appointments=[appt("2026-07-08T16:00:00Z", "2026-07-08T17:00:00Z", status="canceled")])
        self.assertEqual(len(slots), 8)

    def test_fulfiller_hours_override_tenant(self):
        service = {**SERVICE, "allowed_fulfillers": [{"fulfiller_id": "ful_1", "enabled": True}]}
        fulfillers = [{"fulfiller_id": "ful_1", "availability": {"weekly_hours": weekly(start="09:00", end="12:00")}}]
        slots = self.slots(service=service, fulfillers=fulfillers)
        self.assertEqual(len(slots), 3)  # 09,10,11
        self.assertTrue(all(s["fulfiller_id"] == "ful_1" for s in slots))

    def test_weekend_disabled(self):
        sat = epoch(2026, 7, 11, 0, 0)  # Saturday
        slots = self.slots(now=sat, start=sat, end=epoch(2026, 7, 12, 0, 0))
        self.assertEqual(slots, [])


class BookingHandlerTests(unittest.TestCase):
    def test_availability_endpoint(self):
        services = FakeDocumentRepository("service_id")
        services.put({**SERVICE})
        availability = FakeDocumentRepository("availability_id")
        availability.put({"tenant_id": "t1", "availability_id": "default",
                          **tenant_avail(weekly_hours=weekly(start="00:00", end="23:00", enabled_days=tuple(DAYS)))})
        event = {"httpMethod": "GET", "path": "/services/svc_1/availability",
                 "pathParameters": {"service_id": "svc_1"}, "queryStringParameters": {}}
        response = handler(event, None, services_repo=services, availability_repo=availability,
                           fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
                           exceptions_repo=FakeDocumentRepository("exception_id"),
                           appointments_repo=FakeDocumentRepository("appointment_id"))
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["count"] > 0)
        self.assertEqual(body["duration_minutes"], 60)
        self.assertIn("start", body["slots"][0])

    def test_unknown_service_404(self):
        event = {"httpMethod": "GET", "path": "/services/nope/availability",
                 "pathParameters": {"service_id": "nope"}, "queryStringParameters": {}}
        response = handler(event, None, services_repo=FakeDocumentRepository("service_id"),
                           availability_repo=FakeDocumentRepository("availability_id"),
                           fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
                           exceptions_repo=FakeDocumentRepository("exception_id"),
                           appointments_repo=FakeDocumentRepository("appointment_id"))
        self.assertEqual(response["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
