import json
import os
import unittest

import stripe_link.sms as sms
from handlers.reminders import handler as reminders_handler
from stripe_link.domain.reminders import (
    SCHEDULED,
    cancel_reminders,
    due_reminders,
    is_valid_e164,
    mark_reminder,
    plan_reminders,
    reminder_lead_minutes,
    reminder_sms_text,
)
from stripe_link.sms import SmsError, send_sms
from tests.fakes import FakeDocumentRepository

HOUR = 3600
DAY = 86400


def appointment(**overrides):
    base = {
        "schema_version": "2026-05-29",
        "document_type": "appointment",
        "tenant_id": "t1",
        "appointment_id": "appt_1",
        "services": [{"service_id": "svc_1", "service_name": "Consultation", "price_id": "svcprice_svc_1", "duration_minutes": 30}],
        "starts_at": "2026-07-10T17:00:00Z",
        "ends_at": "2026-07-10T17:30:00Z",
        "timezone": "UTC",
        "status": "booked",
        "customer": {"email": "c@e.com", "name": "Casey", "phone": "+14155550123"},
    }
    base.update(overrides)
    return base


# start epoch for 2026-07-10T17:00:00Z
START = 1783702800


class DomainTests(unittest.TestCase):
    def test_e164_validation(self):
        self.assertTrue(is_valid_e164("+14155550123"))
        self.assertFalse(is_valid_e164("4155550123"))
        self.assertFalse(is_valid_e164("+0155"))
        self.assertFalse(is_valid_e164(""))

    def test_lead_minutes_default_and_config(self):
        self.assertEqual(reminder_lead_minutes(None), [1440, 60])
        self.assertEqual(reminder_lead_minutes({"reminder_lead_minutes": [60, 1440, 60, -5]}), [1440, 60])

    def test_plan_schedules_future_leads_only(self):
        now = START - 90 * 60  # 90 minutes before start: 24h lead already passed, 1h lead is future
        reminders = plan_reminders(appointment(), now=now)
        leads = {r["lead_minutes"] for r in reminders}
        self.assertEqual(leads, {60})
        self.assertEqual(reminders[0]["status"], SCHEDULED)
        self.assertEqual(reminders[0]["send_at"], START - 60 * 60)

    def test_plan_schedules_both_when_far_out(self):
        reminders = plan_reminders(appointment(), now=START - 2 * DAY)
        self.assertEqual({r["lead_minutes"] for r in reminders}, {1440, 60})
        self.assertEqual([r["send_at"] for r in reminders], sorted(r["send_at"] for r in reminders))

    def test_plan_skips_without_phone_or_opt_out(self):
        self.assertEqual(plan_reminders(appointment(customer={"email": "c@e.com"}), now=START - 2 * DAY), [])
        appt = appointment(customer={"email": "c@e.com", "phone": "+14155550123", "sms_opted_out": True})
        self.assertEqual(plan_reminders(appt, now=START - 2 * DAY), [])

    def test_plan_preserves_sent_and_does_not_reschedule_it(self):
        appt = appointment(reminders=[{"lead_minutes": 1440, "channel": "sms", "status": "sent", "send_at": START - DAY, "sent_at": START - DAY}])
        reminders = plan_reminders(appt, now=START - 2 * HOUR)
        by_lead = {r["lead_minutes"]: r for r in reminders}
        self.assertEqual(by_lead[1440]["status"], "sent")
        self.assertEqual(by_lead[60]["status"], SCHEDULED)

    def test_reschedule_reanchors_scheduled_reminders(self):
        appt = appointment(reminders=plan_reminders(appointment(), now=START - 2 * DAY))
        moved = {**appt, "starts_at": "2026-07-11T17:00:00Z"}
        reminders = plan_reminders(moved, now=START - 2 * DAY)
        self.assertEqual(reminders[-1]["send_at"], START + DAY - 60 * 60)

    def test_cancel_marks_scheduled(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR}])
        self.assertEqual(cancel_reminders(appt)[0]["status"], "canceled")

    def test_due_filters_by_time_and_status(self):
        reminders = [
            {"lead_minutes": 1440, "channel": "sms", "status": SCHEDULED, "send_at": START - DAY},
            {"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR},
        ]
        appt = appointment(reminders=reminders)
        due = due_reminders(appt, now=START - 2 * HOUR)  # 24h due, 1h not yet
        self.assertEqual([r["lead_minutes"] for r in due], [1440])
        # canceled appointment: nothing due
        self.assertEqual(due_reminders({**appt, "status": "canceled"}, now=START - 2 * HOUR), [])
        # past appointments never remind
        self.assertEqual(due_reminders(appt, now=START + HOUR), [])

    def test_mark_sent_and_failed_retry(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR, "attempts": 0}])
        sent = mark_reminder(appt, appt["reminders"][0], status="sent", now=123, message_id="m1")
        self.assertEqual(sent[0]["status"], "sent")
        self.assertEqual(sent[0]["message_id"], "m1")
        # a single failure stays scheduled for retry
        failed = mark_reminder(appt, appt["reminders"][0], status="failed", now=123, error="boom")
        self.assertEqual(failed[0]["status"], SCHEDULED)
        self.assertEqual(failed[0]["attempts"], 1)

    def test_sms_text_has_service_and_stop(self):
        text = reminder_sms_text(appointment(), business_name="Acme")
        self.assertIn("Acme", text)
        self.assertIn("Consultation", text)
        self.assertIn("STOP", text)


class SmsAdapterTests(unittest.TestCase):
    def test_send_sms_builds_request(self):
        captured = {}

        class FakeClient:
            def send_text_message(self, **kwargs):
                captured.update(kwargs)
                return {"MessageId": "m1"}

        result = send_sms(to="+14155550123", body="hi", origination="pool-1", configuration_set="cs1", client=FakeClient())
        self.assertEqual(result["MessageId"], "m1")
        self.assertEqual(captured["DestinationPhoneNumber"], "+14155550123")
        self.assertEqual(captured["OriginationIdentity"], "pool-1")
        self.assertEqual(captured["ConfigurationSetName"], "cs1")

    def test_send_sms_requires_fields(self):
        with self.assertRaises(SmsError):
            send_sms(to="", body="hi", origination="pool-1")


class OriginationResolverTests(unittest.TestCase):
    def setUp(self):
        sms._ORIGINATION_CACHE.clear()
        self._saved = {k: os.environ.get(k) for k in ("SMS_ORIGINATION_IDENTITY", "SMS_CONFIGURATION_SET", "SMS_ORIGINATION_SECRET_NAME")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sms._ORIGINATION_CACHE.clear()

    class FakeSecrets:
        def __init__(self, payload, *, raise_on=False):
            self.payload = payload
            self.raise_on = raise_on
            self.calls = 0

        def get_secret_value(self, SecretId):
            self.calls += 1
            if self.raise_on:
                raise RuntimeError("no such secret")
            return {"SecretString": json.dumps(self.payload)}

    def test_env_override_wins_without_secret(self):
        os.environ["SMS_ORIGINATION_IDENTITY"] = "+18885550000"
        os.environ["SMS_CONFIGURATION_SET"] = "cs-env"
        self.assertEqual(sms.resolve_origination(), ("+18885550000", "cs-env"))

    def test_reads_from_secret(self):
        os.environ["SMS_ORIGINATION_SECRET_NAME"] = "jb/sms-origination/test"
        client = self.FakeSecrets({"origination_identity": "+18885551234", "configuration_set": "cs1"})
        self.assertEqual(sms.resolve_origination(secrets_client=client), ("+18885551234", "cs1"))

    def test_unconfigured_returns_empty_and_is_not_cached(self):
        os.environ["SMS_ORIGINATION_SECRET_NAME"] = "jb/sms-origination/test"
        empty = self.FakeSecrets({}, raise_on=True)
        self.assertEqual(sms.resolve_origination(secrets_client=empty), ("", ""))
        # a later populated read is picked up (empty result was not cached)
        populated = self.FakeSecrets({"origination_identity": "+18885551234"})
        self.assertEqual(sms.resolve_origination(secrets_client=populated)[0], "+18885551234")

    def test_send_sms_resolves_when_origination_omitted(self):
        os.environ["SMS_ORIGINATION_IDENTITY"] = "+18885550000"
        captured = {}

        class FakeSms:
            def send_text_message(self, **kwargs):
                captured.update(kwargs)
                return {"MessageId": "m1"}

        send_sms(to="+14155550123", body="hi", client=FakeSms())
        self.assertEqual(captured["OriginationIdentity"], "+18885550000")


class SweepHandlerTests(unittest.TestCase):
    def _repos(self, appt):
        appointments = FakeDocumentRepository("appointment_id")
        appointments.put(appt)
        tenants = FakeDocumentRepository("tenant_id")
        tenants.put({"tenant_id": "t1", "business_name": "Acme"})
        return appointments, tenants

    def test_sweep_sends_due_and_stamps(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR, "attempts": 0}])
        appointments, tenants = self._repos(appt)
        sent = []

        def fake_send(*, to, body):
            sent.append((to, body))
            return {"MessageId": "m9"}

        result = reminders_handler({}, None, appointments_repo=appointments, tenant_repo=tenants, sms_send=fake_send, now_fn=lambda: START - 30 * 60, origination_configured=True)
        self.assertEqual(result, {"scanned": 1, "sent": 1, "failed": 0})
        self.assertEqual(sent[0][0], "+14155550123")
        self.assertIn("Acme", sent[0][1])
        stored = appointments.get("t1", "appt_1")
        self.assertEqual(stored["reminders"][0]["status"], "sent")
        self.assertEqual(stored["reminders"][0]["message_id"], "m9")

    def test_sweep_idempotent_second_pass_sends_nothing(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR, "attempts": 0}])
        appointments, tenants = self._repos(appt)
        calls = {"n": 0}

        def fake_send(*, to, body):
            calls["n"] += 1
            return {"MessageId": "m9"}

        reminders_handler({}, None, appointments_repo=appointments, tenant_repo=tenants, sms_send=fake_send, now_fn=lambda: START - 30 * 60, origination_configured=True)
        second = reminders_handler({}, None, appointments_repo=appointments, tenant_repo=tenants, sms_send=fake_send, now_fn=lambda: START - 20 * 60, origination_configured=True)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(second["sent"], 0)

    def test_sweep_failure_keeps_scheduled_for_retry(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR, "attempts": 0}])
        appointments, tenants = self._repos(appt)

        def boom(*, to, body):
            raise SmsError("carrier down")

        result = reminders_handler({}, None, appointments_repo=appointments, tenant_repo=tenants, sms_send=boom, now_fn=lambda: START - 30 * 60, origination_configured=True)
        self.assertEqual(result["failed"], 1)
        stored = appointments.get("t1", "appt_1")
        self.assertEqual(stored["reminders"][0]["status"], SCHEDULED)
        self.assertEqual(stored["reminders"][0]["attempts"], 1)

    def test_sweep_skips_when_sms_unconfigured(self):
        appt = appointment(reminders=[{"lead_minutes": 60, "channel": "sms", "status": SCHEDULED, "send_at": START - HOUR, "attempts": 0}])
        appointments, tenants = self._repos(appt)
        calls = {"n": 0}

        def fake_send(*, to, body):
            calls["n"] += 1
            return {"MessageId": "m9"}

        result = reminders_handler({}, None, appointments_repo=appointments, tenant_repo=tenants, sms_send=fake_send, now_fn=lambda: START - 30 * 60, origination_configured=False)
        self.assertEqual(calls["n"], 0)
        self.assertEqual(result["skipped"], "sms_not_configured")
        # the scheduled reminder is untouched — not marked failed
        self.assertEqual(appointments.get("t1", "appt_1")["reminders"][0]["status"], SCHEDULED)


if __name__ == "__main__":
    unittest.main()
