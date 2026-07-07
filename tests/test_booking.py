import json
import time
import unittest
from datetime import datetime, timedelta, timezone

from handlers.booking import handler
from stripe_link.domain.documents import validate_appointment
from tests.fakes import FakeDocumentRepository

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class FakeSlotLockRepository:
    def __init__(self):
        self.locks = {}

    def claim(self, tenant_id, fulfiller_id, slot_start, *, appointment_id, hold_expires_at, now):
        key = (tenant_id, fulfiller_id or "any", slot_start)
        existing = self.locks.get(key)
        if existing and int(existing) > int(now):
            return False
        self.locks[key] = int(hold_expires_at)
        return True

    def release(self, tenant_id, fulfiller_id, slot_start):
        self.locks.pop((tenant_id, fulfiller_id or "any", slot_start), None)


def all_day_availability():
    return {
        "tenant_id": "t1",
        "availability_id": "default",
        "timezone": "UTC",
        "slot_interval_minutes": 60,
        "lead_time_minutes": 0,
        "weekly_hours": [{"day": d, "enabled": True, "start_time": "00:00", "end_time": "23:00"} for d in DAYS],
    }


def next_valid_slot_iso():
    dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    while dt.hour == 23:
        dt += timedelta(hours=1)
    return dt.isoformat().replace("+00:00", "Z")


def make_env(unit_amount=12000):
    services = FakeDocumentRepository("service_id")
    services.put({"service_id": "svc_1", "tenant_id": "t1", "duration_minutes": 60, "active": True,
                  "name": "Massage", "price": {"currency": "usd", "unit_amount": unit_amount}})
    availability = FakeDocumentRepository("availability_id")
    availability.put(all_day_availability())
    return {
        "services_repo": services,
        "availability_repo": availability,
        "fulfillers_repo": FakeDocumentRepository("fulfiller_id"),
        "exceptions_repo": FakeDocumentRepository("exception_id"),
        "appointments_repo": FakeDocumentRepository("appointment_id"),
        "slot_locks_repo": FakeSlotLockRepository(),
    }


def reserve_event(slot_start, *, email="c@example.com", service_id="svc_1"):
    return {
        "httpMethod": "POST",
        "path": "/services/appointments/reserve",
        "pathParameters": {},
        "queryStringParameters": {},
        "body": json.dumps({"service_id": service_id, "slot_start": slot_start,
                            "customer": {"email": email, "name": "Casey"}}),
    }


class ReserveTests(unittest.TestCase):
    def test_reserve_success_paid(self):
        env = make_env(unit_amount=12000)
        slot = next_valid_slot_iso()
        response = handler(reserve_event(slot), None, **env)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(body["appointment"]["status"], "reserved")
        self.assertTrue(body["requires_payment"])
        self.assertTrue(body["manage_token"])
        # the stored appointment is schema-valid and holds the slot
        stored = env["appointments_repo"].list_for_tenant("t1")[0]
        validate_appointment(stored)
        self.assertEqual(stored["hold_expires_at"], body["hold_expires_at"])

    def test_reserve_free_service(self):
        env = make_env(unit_amount=0)
        response = handler(reserve_event(next_valid_slot_iso()), None, **env)
        self.assertEqual(response["statusCode"], 201)
        self.assertFalse(json.loads(response["body"])["requires_payment"])

    def test_reserve_missing_email(self):
        env = make_env()
        response = handler(reserve_event(next_valid_slot_iso(), email=""), None, **env)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "missing_customer_email")

    def test_reserve_unavailable_slot(self):
        env = make_env()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        response = handler(reserve_event(past.isoformat().replace("+00:00", "Z")), None, **env)
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "slot_unavailable")

    def test_reserve_slot_taken_when_locked(self):
        env = make_env()
        slot = next_valid_slot_iso()
        # A live lock already holds this slot (no appointment yet — the race the lock guards).
        env["slot_locks_repo"].locks[("t1", "any", slot)] = int(time.time()) + 600
        response = handler(reserve_event(slot), None, **env)
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "slot_taken")


if __name__ == "__main__":
    unittest.main()
