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
    dt = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
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


def checkout_event(appointment_id, manage_token):
    return {
        "httpMethod": "POST",
        "path": "/services/appointments/checkout",
        "pathParameters": {},
        "queryStringParameters": {},
        "body": json.dumps({"appointment_id": appointment_id, "manage_token": manage_token}),
    }


class CheckoutTests(unittest.TestCase):
    def _reserve(self, env, unit_amount):
        r = handler(reserve_event(next_valid_slot_iso()), None, **env)
        body = json.loads(r["body"])
        return body["appointment"]["appointment_id"], body["manage_token"]

    def test_free_checkout_confirms_booking(self):
        env = make_env(unit_amount=0)
        appt_id, token = self._reserve(env, 0)
        notifications = FakeDocumentRepository("notification_id")
        response = handler(checkout_event(appt_id, token), None, notifications_repo=notifications, **env)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["status"], "booked")
        self.assertFalse(body["requires_payment"])
        stored = env["appointments_repo"].get("t1", appt_id)
        self.assertEqual(stored["status"], "booked")
        self.assertNotIn("hold_expires_at", stored)
        self.assertEqual(len(notifications.list_for_tenant("t1")), 1)

    def test_checkout_wrong_token_forbidden(self):
        env = make_env(unit_amount=0)
        appt_id, _ = self._reserve(env, 0)
        response = handler(checkout_event(appt_id, "nope"), None, **env)
        self.assertEqual(response["statusCode"], 403)

    def test_checkout_unknown_appointment(self):
        env = make_env()
        response = handler(checkout_event("missing", "tok"), None, **env)
        self.assertEqual(response["statusCode"], 404)

    def test_build_booking_checkout_payload(self):
        from handlers.booking import build_booking_checkout_payload

        appt = {"appointment_id": "appt_1", "service_id": "svc_1", "service_name": "Massage",
                "price": {"currency": "usd", "unit_amount": 12000}, "customer": {"email": "c@e.com"}}
        payload = build_booking_checkout_payload(appt, "t1", success_url="s", cancel_url="c", platform_fee=500, tenant_plan="basic")
        self.assertEqual(payload["metadata[appointment_id]"], "appt_1")
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], "12000")
        self.assertEqual(payload["payment_intent_data[application_fee_amount]"], "500")
        self.assertEqual(payload["customer_email"], "c@e.com")


class WebhookBookingTests(unittest.TestCase):
    def test_persist_appointment_paid_records_booking_and_ledger(self):
        from handlers.stripe_webhook import persist_appointment_paid
        from tests.test_ledger import FakeLedgerRepository

        appointments = FakeDocumentRepository("appointment_id")
        appointments.put({
            "schema_version": "2026-05-29", "document_type": "appointment", "tenant_id": "t1",
            "appointment_id": "appt_1", "service_id": "svc_1", "service_name": "Massage",
            "starts_at": "2026-07-08T15:00:00Z", "ends_at": "2026-07-08T16:00:00Z", "timezone": "UTC",
            "status": "reserved", "payment_status": "unpaid", "customer": {"email": "c@e.com"},
            "price": {"currency": "usd", "unit_amount": 12000}, "hold_expires_at": 999,
        })
        ledger = FakeLedgerRepository()
        notifications = FakeDocumentRepository("notification_id")
        event = {"type": "checkout.session.completed", "data": {"object": {
            "metadata": {"appointment_id": "appt_1", "tenant_id": "t1", "product_type": "digital", "tenant_plan": "basic"},
            "payment_intent": "pi_x", "amount_total": 12000, "currency": "usd",
        }}}
        result = persist_appointment_paid(
            event, tenant_id="t1", appointment_id="appt_1", mode="test",
            appointments_repo=appointments, ledger_repo=ledger, notifications_repo=notifications,
            billing_config_loader=lambda: {}, now_fn=lambda: 1000,
        )
        self.assertEqual(result["status"], "booked")
        self.assertTrue(result["ledger_entry"])
        stored = appointments.get("t1", "appt_1")
        self.assertEqual(stored["status"], "booked")
        self.assertEqual(stored["payment_status"], "paid")
        self.assertNotIn("hold_expires_at", stored)
        entries = ledger.list_for_order("appt_1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["entry_type"], "sale")
        self.assertEqual(entries[0]["amounts"]["gross"], 12000)
        self.assertEqual(len(notifications.list_for_tenant("t1")), 1)


def manage_event(path, method, *, body=None, params=None):
    return {"httpMethod": method, "path": path, "pathParameters": {},
            "queryStringParameters": params or {},
            "body": json.dumps(body) if body is not None else None}


class ManageTests(unittest.TestCase):
    def _reserve(self, env):
        r = handler(reserve_event(next_valid_slot_iso()), None, **env)
        b = json.loads(r["body"])
        return b["appointment"]["appointment_id"], b["manage_token"]

    def test_manage_view_requires_token(self):
        env = make_env(unit_amount=0)
        appt_id, token = self._reserve(env)
        ok = handler(manage_event("/services/appointments/manage", "GET", params={"appointment_id": appt_id, "manage_token": token}), None, **env)
        self.assertEqual(ok["statusCode"], 200)
        self.assertTrue(json.loads(ok["body"])["can_cancel"])
        bad = handler(manage_event("/services/appointments/manage", "GET", params={"appointment_id": appt_id, "manage_token": "x"}), None, **env)
        self.assertEqual(bad["statusCode"], 403)

    def test_manage_cancel_releases_slot(self):
        env = make_env(unit_amount=0)
        appt_id, token = self._reserve(env)
        slot = env["appointments_repo"].get("t1", appt_id)["starts_at"]
        self.assertIn(("t1", "any", slot), env["slot_locks_repo"].locks)
        response = handler(manage_event("/services/appointments/manage/cancel", "POST", body={"appointment_id": appt_id, "manage_token": token}), None, **env)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(env["appointments_repo"].get("t1", appt_id)["status"], "canceled")
        self.assertNotIn(("t1", "any", slot), env["slot_locks_repo"].locks)  # lock released

    def test_manage_reschedule_moves_slot(self):
        env = make_env(unit_amount=0)
        appt_id, token = self._reserve(env)
        old_slot = env["appointments_repo"].get("t1", appt_id)["starts_at"]
        new_slot = (datetime.fromisoformat(old_slot.replace("Z", "+00:00")) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        response = handler(manage_event("/services/appointments/manage/reschedule", "POST", body={"appointment_id": appt_id, "manage_token": token, "slot_start": new_slot}), None, **env)
        self.assertEqual(response["statusCode"], 200)
        stored = env["appointments_repo"].get("t1", appt_id)
        self.assertEqual(stored["starts_at"], new_slot)
        self.assertNotIn(("t1", "any", old_slot), env["slot_locks_repo"].locks)  # old released
        self.assertIn(("t1", "any", new_slot), env["slot_locks_repo"].locks)  # new held


class CompensationSnapshotTests(unittest.TestCase):
    def test_service_override_wins(self):
        from stripe_link.domain.booking import compensation_snapshot

        service = {"allowed_fulfillers": [{"fulfiller_id": "ful_1", "tips_to_fulfiller": False,
                                           "compensation_override": {"type": "percent", "amount": 40}}]}
        fulfiller = {"fulfiller_id": "ful_1", "compensation": {"type": "flat_fee", "amount": 60, "tips_to_fulfiller": True}}
        snap = compensation_snapshot(service, fulfiller)
        self.assertEqual(snap["type"], "percent")
        self.assertEqual(snap["amount"], 40)
        self.assertFalse(snap["tips_to_fulfiller"])
        self.assertEqual(snap["source"], "service_override")

    def test_fulfiller_default_when_no_override(self):
        from stripe_link.domain.booking import compensation_snapshot

        snap = compensation_snapshot({}, {"fulfiller_id": "ful_1", "compensation": {"type": "flat_fee", "amount": 60}})
        self.assertEqual(snap["type"], "flat_fee")
        self.assertEqual(snap["amount"], 60)
        self.assertEqual(snap["source"], "fulfiller_default")

    def test_reserve_snapshots_compensation(self):
        env = make_env(unit_amount=0)
        env["services_repo"].put({"service_id": "svc_1", "tenant_id": "t1", "duration_minutes": 60, "active": True,
                                  "name": "Massage", "price": {"currency": "usd", "unit_amount": 0},
                                  "allowed_fulfillers": [{"fulfiller_id": "ful_1", "enabled": True}]})
        env["fulfillers_repo"].put({"fulfiller_id": "ful_1", "tenant_id": "t1",
                                    "availability": {"weekly_hours": [{"day": d, "enabled": True, "start_time": "00:00", "end_time": "23:00"} for d in DAYS]},
                                    "compensation": {"type": "flat_fee", "amount": 75}})
        r = handler(reserve_event(next_valid_slot_iso()), None, **env)
        appt_id = json.loads(r["body"])["appointment"]["appointment_id"]
        snapshot = env["appointments_repo"].get("t1", appt_id).get("rule_snapshot")
        self.assertEqual(snapshot["fulfiller_id"], "ful_1")
        self.assertEqual(snapshot["amount"], 75)


if __name__ == "__main__":
    unittest.main()
