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


if __name__ == "__main__":
    unittest.main()
