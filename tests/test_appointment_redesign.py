"""Phase 1 success tests for the Appointment-as-multi-service-primitive PRD (appointment-redesign).

Covers STORY-1.1 (services[] canonical + validation + duration rollup), STORY-1.2
(Service.fulfillment_mode), and STORY-1.3 (reserve builds a one-line services[] appointment).
"""
import json
import unittest

from handlers.stripe_webhook import persist_invoice_event, persist_service_purchase
from stripe_link.domain.booking import (
    appointment_duration_minutes,
    appointment_price,
    appointment_service_id,
    reserved_appointment,
)
from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_appointment,
    validate_offer_document,
    validate_service,
)
from stripe_link.domain.pricing import booking_groups_for
from tests.fakes import FakeDocumentRepository


def _appointment(services, **overrides):
    doc = {
        "schema_version": "2026-05-29",
        "document_type": "appointment",
        "tenant_id": "t1",
        "appointment_id": "a1",
        "services": services,
        "starts_at": "2026-07-10T17:00:00Z",
        "ends_at": "2026-07-10T18:15:00Z",
        "timezone": "UTC",
        "status": "booked",
        "customer": {"email": "c@e.com"},
    }
    doc.update(overrides)
    return doc


def _service(**overrides):
    doc = {
        "schema_version": "2026-05-29",
        "document_type": "service",
        "tenant_id": "t1",
        "service_id": "svc_1",
        "name": "Tax Prep",
        "duration_minutes": 60,
        "price": {"currency": "usd", "unit_amount": 15000},
        "prices": [{"price_id": "svcprice_svc_1", "currency": "usd", "unit_amount": 15000, "context": "standard"}],
        "default_price_id": "svcprice_svc_1",
    }
    doc.update(overrides)
    return doc


# --- STORY-1.1: Appointment services[] canonical ---------------------------------------------
class ServicesArrayTests(unittest.TestCase):
    def test_two_line_appointment_validates_and_duration_is_sum(self):
        appt = _appointment([
            {"service_id": "svc_1", "price_id": "svcprice_svc_1", "duration_minutes": 60},
            {"service_id": "svc_2", "price_id": "svcprice_svc_2", "duration_minutes": 15},
        ])
        validate_appointment(appt)  # does not raise
        self.assertEqual(appointment_duration_minutes(appt), 75)

    def test_empty_services_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_appointment(_appointment([]))

    def test_line_missing_price_id_or_duration_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_appointment(_appointment([{"service_id": "svc_1", "duration_minutes": 60}]))
        with self.assertRaises(DocumentValidationError):
            validate_appointment(_appointment([{"service_id": "svc_1", "price_id": "svcprice_svc_1"}]))


# --- STORY-1.2: Service.fulfillment_mode -----------------------------------------------------
class FulfillmentModeTests(unittest.TestCase):
    def test_no_booking_service_without_duration_validates(self):
        svc = _service(fulfillment_mode="no_booking")
        svc.pop("duration_minutes")
        validate_service(svc)  # does not raise

    def test_scheduled_service_without_duration_is_rejected(self):
        svc = _service()  # fulfillment_mode absent → defaults to scheduled
        svc.pop("duration_minutes")
        with self.assertRaises(DocumentValidationError):
            validate_service(svc)

    def test_invalid_fulfillment_mode_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_service(_service(fulfillment_mode="whenever"))


# --- STORY-1.3: reserve builds a one-line services[] appointment -----------------------------
class ReserveShapeTests(unittest.TestCase):
    def test_single_service_reserve_produces_one_line(self):
        appt = reserved_appointment(
            _service(), tenant_id="t1", appointment_id="a1", slot_start_iso="2026-07-10T17:00:00Z",
            tz_name="UTC", fulfiller_id=None, customer={"email": "c@e.com"}, manage_token="tok",
            hold_expires_at=0, now_epoch=0,
        )
        self.assertNotIn("service_id", appt)  # no scalar
        self.assertEqual(len(appt["services"]), 1)
        line = appt["services"][0]
        self.assertEqual(line["service_id"], "svc_1")
        self.assertEqual(line["price_id"], "svcprice_svc_1")
        self.assertEqual(line["duration_minutes"], 60)
        self.assertEqual(appt["duration_minutes"], 60)  # rollup == sum of one line
        self.assertEqual(appointment_service_id(appt), "svc_1")
        self.assertEqual(appointment_price(appt)["unit_amount"], 15000)
        validate_appointment(appt)  # the built appointment is valid


# --- Phase 2 helpers -------------------------------------------------------------------------
def _sched_line(service_id, duration, amount=10000):
    return {"service_id": service_id, "price_id": f"p_{service_id}", "service_name": service_id,
            "unit_amount": amount, "currency": "usd", "quantity": 1, "booking_flow": "pay_then_book",
            "fulfillment_mode": "scheduled", "duration_minutes": duration}


def _nobooking_line(service_id, amount=2000, fulfiller_id=""):
    return {"service_id": service_id, "price_id": f"p_{service_id}", "service_name": service_id,
            "unit_amount": amount, "currency": "usd", "quantity": 1, "booking_flow": "pay_then_book",
            "fulfillment_mode": "no_booking", "duration_minutes": 0, "default_fulfiller_id": fulfiller_id}


def _purchase_event(service_lines, mode="single_visit", session_id="cs_1"):
    return {"type": "checkout.session.completed", "data": {"object": {
        "id": session_id, "payment_intent": "pi_1",
        "amount_total": sum(int(l["unit_amount"]) for l in service_lines), "currency": "usd",
        "customer_details": {"name": "Casey", "email": "c@e.com"},
        "metadata": {"service_id": service_lines[0]["service_id"], "service_booking_mode": mode,
                     "booking_flow": "pay_then_book", "offer_id": "off_1", "service_lines": json.dumps(service_lines)},
    }}}


def _service_offer(items, mode=None):
    offer = {"schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
             "name": "Bundle", "product_intent": "transaction", "stripe_mode": "test",
             "items": items, "discount": {"mode": "none"}, "checkout": {"mode": "payment"}}
    if mode is not None:
        offer["service_booking_mode"] = mode
    return offer


# --- STORY-2.1: Offer.service_booking_mode + N service items ---------------------------------
class OfferBookingModeTests(unittest.TestCase):
    def _items(self):
        return [{"service_id": "s1", "price_id": "p1", "quantity": 1},
                {"service_id": "s2", "price_id": "p2", "quantity": 1}]

    def test_two_service_items_with_single_visit_validate(self):
        validate_offer_document(_service_offer(self._items(), "single_visit"))

    def test_service_booking_mode_optional(self):
        validate_offer_document(_service_offer(self._items()))  # absent → default, still valid

    def test_invalid_service_booking_mode_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(_service_offer(self._items(), "whenever"))


# --- STORY-2.2: booking_groups_for -----------------------------------------------------------
class BookingGroupsTests(unittest.TestCase):
    def _svcs(self, modes):
        return {sid: {"service_id": sid, "fulfillment_mode": mode} for sid, mode in modes.items()}

    def test_single_visit_one_group(self):
        offer = {"service_booking_mode": "single_visit", "items": [{"service_id": "s1"}, {"service_id": "s2"}]}
        groups = booking_groups_for(offer, self._svcs({"s1": "scheduled", "s2": "scheduled"}))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_separate_visits_group_per_item(self):
        offer = {"service_booking_mode": "separate_visits", "items": [{"service_id": "s1"}, {"service_id": "s2"}]}
        groups = booking_groups_for(offer, self._svcs({"s1": "scheduled", "s2": "scheduled"}))
        self.assertEqual([len(g) for g in groups], [1, 1])

    def test_no_booking_excluded(self):
        offer = {"service_booking_mode": "single_visit", "items": [{"service_id": "s1"}, {"service_id": "s2"}]}
        groups = booking_groups_for(offer, self._svcs({"s1": "scheduled", "s2": "no_booking"}))
        self.assertEqual(len(groups), 1)
        self.assertEqual([i["service_id"] for i in groups[0]], ["s1"])


# --- STORY-2.4: webhook fan-out --------------------------------------------------------------
class WebhookFanOutTests(unittest.TestCase):
    def test_single_visit_one_appointment_two_lines(self):
        appts = FakeDocumentRepository("appointment_id")
        r = persist_service_purchase(_purchase_event([_sched_line("s1", 60), _sched_line("s2", 15)], "single_visit"),
                                     tenant_id="t1", mode="test", appointments_repo=appts, now_fn=lambda: 1000)
        self.assertEqual(len(r["appointment_ids"]), 1)
        appt = appts.get("t1", r["appointment_ids"][0])
        self.assertEqual(len(appt["services"]), 2)
        self.assertEqual(appt["duration_minutes"], 75)
        self.assertTrue(appt["awaiting_schedule"])
        self.assertEqual(appt["payment_status"], "paid")

    def test_separate_visits_two_appointments(self):
        appts = FakeDocumentRepository("appointment_id")
        r = persist_service_purchase(_purchase_event([_sched_line("s1", 60), _sched_line("s2", 15)], "separate_visits"),
                                     tenant_id="t1", mode="test", appointments_repo=appts, now_fn=lambda: 1000)
        self.assertEqual(len(r["appointment_ids"]), 2)
        self.assertEqual(len(appts.list_for_tenant("t1")), 2)

    def test_no_booking_only_zero_appointments_and_invoice_line(self):
        appts = FakeDocumentRepository("appointment_id")
        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({"tenant_id": "t1", "invoice_id": "inv_cs_2", "document_type": "invoice", "status": "paid",
                      "customer": {"email": "c@e.com"}, "line_items": [], "amounts": {"currency": "usd"}})
        r = persist_service_purchase(_purchase_event([_nobooking_line("np", fulfiller_id="f1")], "single_visit", session_id="cs_2"),
                                     tenant_id="t1", mode="test", appointments_repo=appts, invoices_repo=invoices, now_fn=lambda: 1000)
        self.assertEqual(r["appointment_ids"], [])
        self.assertEqual(len(appts.list_for_tenant("t1")), 0)
        inv = invoices.get("t1", "inv_cs_2")
        self.assertEqual(inv["source"]["appointment_ids"], [])
        nb = [li for li in inv["line_items"] if li.get("fulfillment") == "no_booking"]
        self.assertEqual(len(nb), 1)
        self.assertEqual(nb[0]["fulfiller_id"], "f1")
        self.assertEqual(nb[0]["fulfillment_status"], "fulfilled")

    def test_idempotent_redelivery(self):
        appts = FakeDocumentRepository("appointment_id")
        event = _purchase_event([_sched_line("s1", 60), _sched_line("s2", 15)], "separate_visits")
        persist_service_purchase(event, tenant_id="t1", mode="test", appointments_repo=appts, now_fn=lambda: 1000)
        persist_service_purchase(event, tenant_id="t1", mode="test", appointments_repo=appts, now_fn=lambda: 1001)
        self.assertEqual(len(appts.list_for_tenant("t1")), 2)  # no duplicates


# --- STORY-2.5: invoice.paid fan-out ---------------------------------------------------------
class InvoicePaidFanOutTests(unittest.TestCase):
    def _paid_event(self, invoice_id="inv_1"):
        return {"type": "invoice.paid", "data": {"object": {"metadata": {"invoice_id": invoice_id, "tenant_id": "t1"},
                "payment_intent": "pi_1", "amount_paid": 15000, "currency": "usd"}}}

    def test_paid_marks_all_linked_appointments(self):
        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({"tenant_id": "t1", "invoice_id": "inv_1", "status": "open", "document_type": "invoice",
                      "customer": {"email": "c@e.com"}, "amounts": {"currency": "usd", "total": 15000},
                      "source": {"appointment_ids": ["a1", "a2"]}})
        appts = FakeDocumentRepository("appointment_id")
        appts.put({"tenant_id": "t1", "appointment_id": "a1", "payment_status": "unpaid", "status": "booked"})
        appts.put({"tenant_id": "t1", "appointment_id": "a2", "payment_status": "unpaid", "status": "booked"})
        persist_invoice_event(self._paid_event(), tenant_id="t1", event_type="invoice.paid", mode="test",
                              invoices_repo=invoices, appointments_repo=appts, now_fn=lambda: 1000)
        self.assertEqual(appts.get("t1", "a1")["payment_status"], "paid")
        self.assertEqual(appts.get("t1", "a2")["payment_status"], "paid")

    def test_no_booking_only_invoice_paid_touches_no_appointment(self):
        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({"tenant_id": "t1", "invoice_id": "inv_1", "status": "open", "document_type": "invoice",
                      "customer": {"email": "c@e.com"}, "amounts": {"currency": "usd", "total": 2000},
                      "source": {"appointment_ids": []}})
        appts = FakeDocumentRepository("appointment_id")
        result = persist_invoice_event(self._paid_event(), tenant_id="t1", event_type="invoice.paid", mode="test",
                                       invoices_repo=invoices, appointments_repo=appts, now_fn=lambda: 1000)
        self.assertEqual(result["status"], "paid")
        self.assertEqual(len(appts.list_for_tenant("t1")), 0)


# --- Phase 3 helpers -------------------------------------------------------------------------
from handlers.booking import handler as booking_handler  # noqa: E402
from handlers.invoices import handler as invoices_handler  # noqa: E402
from stripe_link.domain.booking import slot_end_iso  # noqa: E402
from stripe_link.domain.invoicing import invoice_from_order  # noqa: E402
from tests.test_services_in_offers import DAYS, FakeSlotLockRepository, _iso_tomorrow, priced_service  # noqa: E402


def _open_availability():
    repo = FakeDocumentRepository("availability_id")
    repo.put({"tenant_id": "t1", "availability_id": "default", "timezone": "UTC", "slot_interval_minutes": 60,
              "lead_time_minutes": 0, "weekly_hours": [{"day": d, "enabled": True, "start_time": "00:00", "end_time": "23:00"} for d in DAYS]})
    return repo


def _combined_appt(status="booked", awaiting=True, starts_at=None):
    appt = {"schema_version": "2026-05-29", "document_type": "appointment", "tenant_id": "t1", "appointment_id": "a1",
            "services": [{"service_id": "svc_1", "service_name": "Tax Prep", "price_id": "p1", "duration_minutes": 60},
                         {"service_id": "svc_2", "service_name": "Notary", "price_id": "p2", "duration_minutes": 15}],
            "duration_minutes": 75, "status": status, "payment_status": "paid", "customer": {"email": "c@e.com"},
            "customer_manage_token": "tok"}
    if awaiting:
        appt["awaiting_schedule"] = True
    if starts_at:
        appt["starts_at"] = starts_at
        appt["ends_at"] = slot_end_iso(starts_at, 75)
        appt["timezone"] = "UTC"
    return appt


def _booking_env(appt):
    services = FakeDocumentRepository("service_id"); services.put(priced_service())
    appts = FakeDocumentRepository("appointment_id"); appts.put(appt)
    return dict(services_repo=services, availability_repo=_open_availability(),
                fulfillers_repo=FakeDocumentRepository("fulfiller_id"), exceptions_repo=FakeDocumentRepository("exception_id"),
                appointments_repo=appts, connections_repo=None), appts


# --- STORY-3.1: schedule a combined appointment against the summed duration ------------------
class CombinedScheduleTests(unittest.TestCase):
    def test_combined_slot_uses_summed_duration(self):
        env, appts = _booking_env(_combined_appt())
        slot = _iso_tomorrow()
        event = {"httpMethod": "POST", "path": "/services/appointments/manage/schedule",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1", "manage_token": "tok", "slot_start": slot})}
        resp = booking_handler(event, None, slot_locks_repo=FakeSlotLockRepository(), **env)
        self.assertEqual(resp["statusCode"], 200)
        stored = appts.get("t1", "a1")
        self.assertEqual(stored["starts_at"], slot)
        self.assertEqual(stored["ends_at"], slot_end_iso(slot, 75))  # 60 + 15
        self.assertNotIn("awaiting_schedule", stored)

    def test_taken_slot_rejected(self):
        env, appts = _booking_env(_combined_appt())
        slot = _iso_tomorrow()
        locks = FakeSlotLockRepository()
        locks.claim("t1", None, slot, appointment_id="other", hold_expires_at=9999999999, now=0)
        event = {"httpMethod": "POST", "path": "/services/appointments/manage/schedule",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1", "manage_token": "tok", "slot_start": slot})}
        resp = booking_handler(event, None, slot_locks_repo=locks, **env)
        self.assertEqual(resp["statusCode"], 409)


# --- STORY-3.2: availability accepts a combined-duration override ----------------------------
class CombinedAvailabilityTests(unittest.TestCase):
    def _query(self, params):
        services = FakeDocumentRepository("service_id"); services.put(priced_service())
        event = {"httpMethod": "GET", "path": "/services/svc_1/availability",
                 "pathParameters": {"service_id": "svc_1"}, "queryStringParameters": {"tenant_id": "t1", **params}}
        resp = booking_handler(event, None, services_repo=services, availability_repo=_open_availability(),
                               fulfillers_repo=FakeDocumentRepository("fulfiller_id"), exceptions_repo=FakeDocumentRepository("exception_id"),
                               appointments_repo=FakeDocumentRepository("appointment_id"), slot_locks_repo=FakeSlotLockRepository(), connections_repo=None)
        return json.loads(resp["body"])

    def test_override_drives_slot_length(self):
        body = self._query({"duration_minutes": "75"})
        self.assertEqual(body["duration_minutes"], 75)
        first = body["slots"][0]
        self.assertEqual(first["end"], slot_end_iso(first["start"], 75))

    def test_default_is_service_duration(self):
        body = self._query({})
        self.assertEqual(body["duration_minutes"], 60)  # the service's own duration, unchanged


# --- STORY-3.3: invoice_from_order ----------------------------------------------------------
class InvoiceFromOrderTests(unittest.TestCase):
    def _appt(self, appt_id, amount):
        return {"tenant_id": "t1", "appointment_id": appt_id, "order_id": "ord_1", "customer": {"email": "c@e.com"},
                "services": [{"service_id": f"s_{appt_id}", "service_name": appt_id, "price_id": "p", "duration_minutes": 30,
                              "price": {"currency": "usd", "unit_amount": amount}}]}

    def test_two_appointments_one_invoice_two_lines(self):
        inv = invoice_from_order([self._appt("a1", 10000), self._appt("a2", 5000)], invoice_id="inv_1", now=1000)
        self.assertEqual(len(inv["line_items"]), 2)
        self.assertEqual(inv["source"]["appointment_ids"], ["a1", "a2"])
        self.assertEqual(inv["amounts"]["total"], 15000)

    def test_no_booking_only_empty_appointment_ids(self):
        nb = [{"type": "service", "description": "Top-off", "quantity": 1, "unit_amount": 2000, "currency": "usd",
               "fulfillment": "no_booking", "fulfillment_status": "fulfilled"}]
        inv = invoice_from_order([], invoice_id="inv_2", now=1000, no_booking_lines=nb, tenant_id="t1", customer={"email": "c@e.com"})
        self.assertEqual(inv["source"]["appointment_ids"], [])
        self.assertEqual(len(inv["line_items"]), 1)
        self.assertEqual(inv["line_items"][0]["fulfillment"], "no_booking")

    def test_from_order_route_idempotent(self):
        invoices = FakeDocumentRepository("invoice_id")
        appts = FakeDocumentRepository("appointment_id")
        appts.put(self._appt("a1", 10000)); appts.put(self._appt("a2", 5000))
        event = {"httpMethod": "POST", "path": "/invoices/from-order", "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"order_id": "ord_1"})}
        r1 = invoices_handler(event, None, repository=invoices, appointments_repo=appts)
        self.assertEqual(r1["statusCode"], 201)
        self.assertTrue(json.loads(r1["body"])["created"])
        r2 = invoices_handler(event, None, repository=invoices, appointments_repo=appts)
        self.assertFalse(json.loads(r2["body"])["created"])


# --- STORY-3.4: reschedule a combined appointment against the summed duration ----------------
class CombinedRescheduleTests(unittest.TestCase):
    def test_reschedule_uses_summed_duration(self):
        first = _iso_tomorrow(hour=10)
        env, appts = _booking_env(_combined_appt(status="booked", awaiting=False, starts_at=first))
        new_slot = _iso_tomorrow(hour=14)
        event = {"httpMethod": "POST", "path": "/services/appointments/manage/reschedule",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1", "manage_token": "tok", "slot_start": new_slot})}
        resp = booking_handler(event, None, slot_locks_repo=FakeSlotLockRepository(), **env)
        self.assertEqual(resp["statusCode"], 200)
        stored = appts.get("t1", "a1")
        self.assertEqual(stored["starts_at"], new_slot)
        self.assertEqual(stored["ends_at"], slot_end_iso(new_slot, 75))


if __name__ == "__main__":
    unittest.main()
