import json
import unittest

from stripe_link.delegation import apply_delegation
from stripe_link.domain.calendar_routing import (
    candidate_fulfiller_ids,
    delegation_status,
    fulfiller_busy_connection,
    resolve_write_connection,
    service_busy_connection,
)
from stripe_link.domain.notifications_content import delegate_booking_email
from stripe_link.domain.scheduling import available_slots
from tests.fakes import FakeDocumentRepository


def conn(cid, *, default=False, status="connected", owner=None, calendar_id=None):
    return {"tenant_id": "t1", "connection_id": cid, "provider": "google", "status": status,
            "is_default": default, "owner_fulfiller_id": owner, "calendar_id": calendar_id or f"{cid}@x",
            "refresh_token_ref": f"enc:rt-{cid}", "connected_at": 100}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.default = conn("cal_default", default=True)
        self.svc = conn("cal_service")
        self.jane = conn("cal_jane", owner="f_jane")
        self.connections = [self.default, self.svc, self.jane]

    def test_write_precedence_fulfiller_over_service_over_default(self):
        appt = {"assigned_fulfiller_id": "f_jane"}
        # fulfiller override wins
        self.assertEqual(resolve_write_connection(appt, {"calendar_connection_id": "cal_service"}, {"calendar_connection_id": "cal_jane"}, self.connections)["connection_id"], "cal_jane")
        # no fulfiller cal -> service
        self.assertEqual(resolve_write_connection(appt, {"calendar_connection_id": "cal_service"}, {}, self.connections)["connection_id"], "cal_service")
        # neither -> default
        self.assertEqual(resolve_write_connection(appt, {}, {}, self.connections)["connection_id"], "cal_default")
        # nothing connected -> None
        self.assertIsNone(resolve_write_connection(appt, {}, {}, []))

    def test_delegation_status(self):
        jane = {"calendar_connection_id": "cal_jane"}
        self.assertEqual(delegation_status(self.jane, jane), "written")
        self.assertEqual(delegation_status(self.default, jane), "unavailable")  # fell back off their calendar
        self.assertIsNone(delegation_status(self.default, {}))  # not a delegation scenario

    def test_busy_connection_helpers(self):
        self.assertEqual(service_busy_connection({"calendar_connection_id": "cal_service"}, self.connections)["connection_id"], "cal_service")
        self.assertEqual(service_busy_connection({}, self.connections)["connection_id"], "cal_default")  # default fallback
        self.assertEqual(fulfiller_busy_connection({"calendar_connection_id": "cal_jane"}, self.connections)["connection_id"], "cal_jane")
        self.assertIsNone(fulfiller_busy_connection({"calendar_connection_id": "missing"}, self.connections))

    def test_candidate_fulfiller_ids(self):
        service = {"allowed_fulfillers": [{"fulfiller_id": "a", "enabled": True}, {"fulfiller_id": "b", "enabled": False}], "default_fulfiller_id": "d"}
        self.assertEqual(candidate_fulfiller_ids(service), ["a"])  # only enabled
        self.assertEqual(candidate_fulfiller_ids(service, "x"), ["x"])  # explicit
        self.assertEqual(candidate_fulfiller_ids({"default_fulfiller_id": "d"}), ["d"])


class DelegateEmailTests(unittest.TestCase):
    def test_content_written(self):
        appt = {"service_name": "Consult", "starts_at": "2026-07-10T17:00:00Z", "timezone": "UTC", "customer": {"name": "Casey", "email": "c@e.com"}, "delegation_calendar": "written"}
        c = delegate_booking_email(appt, {"name": "Consult"}, {"display_name": "Jane", "email": "j@x.com"}, business_name="Acme", calendar_written=True, change="booked")
        self.assertIn("New booking", c["subject"])
        self.assertIn("Consult", c["html"])
        self.assertIn("added to your calendar", c["text"])

    def test_content_unavailable(self):
        c = delegate_booking_email({"service_name": "Consult"}, None, {"display_name": "Jane"}, calendar_written=False, change="booked")
        self.assertIn("could not add", c["text"])


class PerFulfillerBusyTests(unittest.TestCase):
    def _service(self):
        return {"service_id": "s1", "tenant_id": "t1", "duration_minutes": 60,
                "allowed_fulfillers": [{"fulfiller_id": "f1", "enabled": True}, {"fulfiller_id": "f2", "enabled": True}]}

    def _availability(self):
        hours = [{"day": d, "enabled": True, "start_time": "09:00", "end_time": "17:00"} for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
        return {"timezone": "UTC", "slot_interval_minutes": 60, "weekly_hours": hours}

    def test_own_calendar_blocks_only_that_fulfiller(self):
        # f1 busy 10:00-11:00 on their own calendar; f2 has no calendar entry -> not blocked there.
        busy = {"f1": [{"start": "2026-07-08T10:00:00Z", "end": "2026-07-08T11:00:00Z"}]}
        slots = available_slots(self._service(), self._availability(), [], [], [],
                                now_epoch=1783468800, range_start_epoch=1783468800, range_end_epoch=1783468800 + 86400,
                                external_busy_by_fulfiller=busy)
        at_ten = [s for s in slots if s["start"] == "2026-07-08T10:00:00Z"]
        # f2 can still be booked at 10:00; f1 cannot
        self.assertTrue(any(s["fulfiller_id"] == "f2" for s in at_ten))
        self.assertFalse(any(s["fulfiller_id"] == "f1" for s in at_ten))

    def test_global_none_blocks_fulfiller_without_own(self):
        busy = {None: [{"start": "2026-07-08T10:00:00Z", "end": "2026-07-08T11:00:00Z"}]}
        slots = available_slots(self._service(), self._availability(), [], [], [],
                                now_epoch=1783468800, range_start_epoch=1783468800, range_end_epoch=1783468800 + 86400,
                                external_busy_by_fulfiller=busy)
        self.assertFalse(any(s["start"] == "2026-07-08T10:00:00Z" for s in slots))  # blocked for everyone


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


class FakeCipher:
    def decrypt(self, ref, *, tenant_id, mode, field):
        return ref[4:] if ref.startswith("enc:") else ref


GOOGLE_SECRET = {"client_id": "cid", "client_secret": "sec"}


class ApplyDelegationTests(unittest.TestCase):
    def _env(self, *, fulfiller_cal="cal_jane", connections=None):
        appointments = FakeDocumentRepository("appointment_id")
        appt = {"tenant_id": "t1", "appointment_id": "appt_1",
                "services": [{"service_id": "s1", "service_name": "Consult", "price_id": "svcprice_s1", "duration_minutes": 30}],
                "starts_at": "2026-07-10T17:00:00Z", "ends_at": "2026-07-10T17:30:00Z", "timezone": "UTC",
                "status": "booked", "assigned_fulfiller_id": "f_jane", "customer": {"name": "Casey", "email": "c@e.com"}}
        appointments.put(appt)
        services = FakeDocumentRepository("service_id"); services.put({"service_id": "s1", "tenant_id": "t1", "name": "Consult"})
        fulfillers = FakeDocumentRepository("fulfiller_id")
        fulfillers.put({"tenant_id": "t1", "fulfiller_id": "f_jane", "display_name": "Jane", "email": "jane@x.com", "calendar_connection_id": fulfiller_cal})
        tenants = FakeDocumentRepository("tenant_id"); tenants.put({"tenant_id": "t1", "business_name": "Acme"})
        conns = FakeDocumentRepository("connection_id")
        for c in (connections if connections is not None else [conn("cal_jane", owner="f_jane"), conn("cal_default", default=True)]):
            conns.put(c)
        return appt, appointments, services, fulfillers, tenants, conns

    def test_delegated_write_and_email(self):
        appt, appointments, services, fulfillers, tenants, conns = self._env()
        sent = {}

        def fake_mail(*, to, subject, html, text, from_name, reply_to):
            sent.update({"to": to, "subject": subject})

        apply_delegation(appt, action="upsert", change="booked", appointments_repo=appointments,
                         services_repo=services, fulfillers_repo=fulfillers, connections_repo=conns, tenant_repo=tenants,
                         mailer_send=fake_mail, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET,
                         opener=_FakeOpener({"access_token": "ya29"}, {"id": "evt_1"}))
        self.assertEqual(appt["delegation_calendar"], "written")
        self.assertEqual(appt["external_calendar_events"][0]["connection_id"], "cal_jane")
        self.assertEqual(sent["to"], "jane@x.com")
        self.assertIn("Consult", sent["subject"])

    def test_delegate_without_calendar_falls_back_unavailable(self):
        # Jane names a calendar that isn't connected; only a tenant default exists.
        appt, appointments, services, fulfillers, tenants, conns = self._env(
            fulfiller_cal="cal_missing", connections=[conn("cal_default", default=True)])
        sent = {}

        def fake_mail(*, to, subject, html, text, from_name, reply_to):
            sent.update({"to": to})

        apply_delegation(appt, action="upsert", change="booked", appointments_repo=appointments,
                         services_repo=services, fulfillers_repo=fulfillers, connections_repo=conns, tenant_repo=tenants,
                         mailer_send=fake_mail, secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET,
                         opener=_FakeOpener({"access_token": "ya29"}, {"id": "evt_2"}))
        self.assertEqual(appt["delegation_calendar"], "unavailable")  # wrote to default, not Jane's
        self.assertEqual(sent["to"], "jane@x.com")  # still notified


if __name__ == "__main__":
    unittest.main()
