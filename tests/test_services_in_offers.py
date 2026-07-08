"""Backend tests for the services-as-first-class-offer-inputs PRD (Phase 1)."""
import json
import time
import unittest
from datetime import datetime, timedelta, timezone

from handlers.booking import handler as booking_handler, build_booking_checkout_payload
from handlers.invoices import handler as invoices_handler
from handlers.stripe_webhook import persist_invoice_event, persist_service_purchase
from stripe_link.domain.booking import reserved_appointment
from stripe_link.domain.documents import DocumentValidationError, validate_offer_document, validate_service
from stripe_link.domain.fees import calculate_price, fee_class_for
from stripe_link.domain.invoicing import invoice_from_appointment
from stripe_link.domain.pricing import PricingError, load_offer_services, resolve_offer
from stripe_link.domain.service_pricing import (
    normalize_service_pricing,
    resolve_service_price,
    service_booking_flow,
    service_prices,
)
from tests.fakes import FakeDocumentRepository

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class FakeSlotLockRepository:
    def __init__(self):
        self.locks = {}

    def claim(self, tenant_id, fulfiller_id, slot_start, *, appointment_id, hold_expires_at, now):
        key = (tenant_id, fulfiller_id or "any", slot_start)
        if self.locks.get(key, 0) > int(now):
            return False
        self.locks[key] = int(hold_expires_at)
        return True

    def release(self, tenant_id, fulfiller_id, slot_start):
        self.locks.pop((tenant_id, fulfiller_id or "any", slot_start), None)


def legacy_service(**over):
    base = {"service_id": "svc_1", "tenant_id": "t1", "name": "Tax Prep", "duration_minutes": 60,
            "active": True, "price": {"currency": "usd", "unit_amount": 15000}}
    base.update(over)
    return base


def priced_service(fee_handling="standard", booking_flow="pay_then_book", unit_amount=15000):
    return {
        "schema_version": "2026-05-29", "document_type": "service",
        "service_id": "svc_1", "tenant_id": "t1", "name": "Tax Prep", "duration_minutes": 60, "active": True,
        "booking_flow": booking_flow,
        "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": unit_amount, "tenant_keyed_amount": unit_amount,
                    "context": "standard", "fee_handling": fee_handling, "pricing_model": "one_time", "quantity": 1}],
        "default_price_id": "p1",
    }


class ServicePricingAdapterTests(unittest.TestCase):
    def test_legacy_price_synthesizes_prices(self):
        prices = service_prices(legacy_service())
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["unit_amount"], 15000)
        self.assertEqual(prices[0]["fee_handling"], "standard")
        self.assertEqual(resolve_service_price(legacy_service())["unit_amount"], 15000)

    def test_normalize_writes_forward_and_drops_linked_product(self):
        svc = normalize_service_pricing({**legacy_service(), "linked_product": {"product_id": "prod_x"}})
        self.assertIn("prices", svc)
        self.assertEqual(svc["default_price_id"], svc["prices"][0]["price_id"])
        self.assertEqual(svc["booking_flow"], "pay_then_book")
        self.assertEqual(svc["price"], {"currency": "usd", "unit_amount": 15000})  # legacy mirror
        self.assertNotIn("linked_product", svc)  # retired

    def test_booking_flow_default_and_override(self):
        self.assertEqual(service_booking_flow(legacy_service()), "pay_then_book")
        self.assertEqual(service_booking_flow(legacy_service(booking_flow="book_then_pay")), "book_then_pay")

    def test_service_validates_with_prices_and_booking_flow(self):
        validate_service(normalize_service_pricing(priced_service()))  # no raise


class FeeClassTests(unittest.TestCase):
    def test_service_routes_to_digital(self):
        self.assertEqual(fee_class_for("service"), "digital")

    def test_net_guaranteed_grosses_up_service(self):
        std = calculate_price(tenant_keyed_amount=15000, product_type="service", fee_handling="standard")
        net = calculate_price(tenant_keyed_amount=15000, product_type="service", fee_handling="net_guaranteed")
        self.assertEqual(std["unit_amount"], 15000)
        self.assertGreater(net["unit_amount"], 15000)  # customer charged more
        self.assertGreaterEqual(net["breakdown"]["net_payout"], 15000)  # tenant nets the sticker


class OfferResolutionTests(unittest.TestCase):
    def _offer(self, items):
        return {"offer_id": "off_1", "tenant_id": "t1", "status": "active", "context": "standard", "items": items}

    def test_resolve_service_item(self):
        services = {"svc_1": priced_service()}
        resolved = resolve_offer(self._offer([{"service_id": "svc_1", "price_id": "p1", "quantity": 1}]), {}, services_by_id=services)
        item = resolved["items"][0]
        self.assertEqual(item["kind"], "service")
        self.assertEqual(item["service_id"], "svc_1")
        self.assertEqual(item["product_name"], "Tax Prep")
        self.assertEqual(item["unit_amount"], 15000)
        self.assertEqual(item["booking_flow"], "pay_then_book")

    def test_mixed_product_and_service_resolves(self):
        product = {"product_id": "prod_1", "name": "Guide", "status": "active",
                   "prices": [{"price_id": "pp", "currency": "usd", "unit_amount": 2000, "context": "standard"}]}
        offer = self._offer([
            {"product_id": "prod_1", "price_id": "pp", "quantity": 1},
            {"service_id": "svc_1", "price_id": "p1", "quantity": 1},
        ])
        resolved = resolve_offer(offer, {"prod_1": product}, services_by_id={"svc_1": priced_service()})
        kinds = [i["kind"] for i in resolved["items"]]
        self.assertEqual(kinds, ["product", "service"])
        self.assertEqual(resolved["subtotal"], 2000 + 15000)

    def test_load_offer_services_missing_repo_raises(self):
        with self.assertRaises(PricingError):
            load_offer_services("t1", self._offer([{"service_id": "svc_1", "price_id": "p1", "quantity": 1}]), None)


class OfferValidationTests(unittest.TestCase):
    def _offer(self, items):
        return {"schema_version": "2026-05-29", "document_type": "offer", "offer_id": "off_1", "tenant_id": "t1",
                "name": "O", "product_intent": "transaction", "stripe_mode": "test", "items": items,
                "checkout": {"mode": "payment"}, "discount": {"mode": "none"}}

    def test_service_item_valid(self):
        validate_offer_document(self._offer([{"service_id": "svc_1", "price_id": "p1", "quantity": 1}]))

    def test_exactly_one_ref_required(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(self._offer([{"product_id": "p", "service_id": "s", "price_id": "x", "quantity": 1}]))

    def test_multi_service_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(self._offer([
                {"service_id": "s1", "price_id": "p1", "quantity": 1},
                {"service_id": "s2", "price_id": "p2", "quantity": 1},
            ]))

    def test_service_item_requires_transaction_intent(self):
        offer = self._offer([{"service_id": "svc_1", "price_id": "p1", "quantity": 1}])
        offer["product_intent"] = "lead_gen"
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(offer)


class DirectBookingPricingTests(unittest.TestCase):
    def test_reserved_appointment_carries_fee_handling(self):
        appt = reserved_appointment(priced_service(fee_handling="net_guaranteed"), tenant_id="t1", appointment_id="a1",
                                    slot_start_iso="2026-07-10T17:00:00Z", tz_name="UTC", fulfiller_id=None,
                                    customer={"email": "c@e.com"}, manage_token="tok", hold_expires_at=0, now_epoch=0)
        self.assertEqual(appt["price"]["fee_handling"], "net_guaranteed")
        self.assertEqual(appt["price"]["tenant_keyed_amount"], 15000)
        self.assertEqual(appt["booking_flow"], "pay_then_book")
        self.assertEqual(appt["source"], "booking_page")

    def test_net_guaranteed_line_item_is_grossed_up(self):
        fee = calculate_price(tenant_keyed_amount=15000, product_type="service", fee_handling="net_guaranteed")
        appt = {"service_name": "Tax", "price": {"currency": "usd", "unit_amount": 15000}}
        payload = build_booking_checkout_payload(appt, "t1", success_url="s", cancel_url="c",
                                                 platform_fee=0, tenant_plan="basic", charged_unit_amount=fee["unit_amount"])
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], str(fee["unit_amount"]))
        self.assertGreater(fee["unit_amount"], 15000)


def _iso_tomorrow(hour=10):
    return (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


class PayThenBookWebhookTests(unittest.TestCase):
    def _event(self):
        return {"type": "checkout.session.completed", "data": {"object": {
            "id": "cs_123", "payment_intent": "pi_1", "amount_total": 15000, "currency": "usd",
            "customer_details": {"name": "Casey", "email": "c@e.com"},
            "metadata": {"service_id": "svc_1", "service_name": "Tax Prep", "booking_flow": "pay_then_book",
                         "offer_id": "off_1", "service_price_id": "p1"},
        }}}

    def test_creates_awaiting_schedule_appointment_idempotently(self):
        appts = FakeDocumentRepository("appointment_id")
        r1 = persist_service_purchase(self._event(), tenant_id="t1", mode="test", order_id="ord_1",
                                      appointments_repo=appts, now_fn=lambda: 1000)
        self.assertEqual(r1["status"], "awaiting_schedule")
        appt = appts.get("t1", r1["appointment_id"])
        self.assertTrue(appt["awaiting_schedule"])
        self.assertEqual(appt["payment_status"], "paid")
        self.assertEqual(appt["source"], "offer")
        self.assertEqual(appt["order_id"], "ord_1")
        self.assertIsNone(appt.get("starts_at"))  # no time yet
        # idempotent: a redelivered session does not create a second appointment
        r2 = persist_service_purchase(self._event(), tenant_id="t1", mode="test", appointments_repo=appts, now_fn=lambda: 1001)
        self.assertEqual(r2["status"], "skipped")
        self.assertEqual(len(appts.list_for_tenant("t1")), 1)


class ScheduleEndpointTests(unittest.TestCase):
    def _env(self):
        services = FakeDocumentRepository("service_id")
        services.put(normalize_service_pricing(priced_service()))
        availability = FakeDocumentRepository("availability_id")
        availability.put({"tenant_id": "t1", "availability_id": "default", "timezone": "UTC", "slot_interval_minutes": 60,
                          "lead_time_minutes": 0, "weekly_hours": [{"day": d, "enabled": True, "start_time": "00:00", "end_time": "23:00"} for d in DAYS]})
        appts = FakeDocumentRepository("appointment_id")
        appts.put({"schema_version": "2026-05-29", "document_type": "appointment", "tenant_id": "t1",
                   "appointment_id": "a1", "service_id": "svc_1", "service_name": "Tax Prep", "status": "booked",
                   "payment_status": "paid", "awaiting_schedule": True, "customer": {"email": "c@e.com"},
                   "customer_manage_token": "tok"})
        return services, availability, appts

    def test_schedule_sets_time_and_clears_flag(self):
        services, availability, appts = self._env()
        slot = _iso_tomorrow()
        event = {"httpMethod": "POST", "path": "/services/appointments/manage/schedule",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1", "manage_token": "tok", "slot_start": slot})}
        resp = booking_handler(event, None, services_repo=services, availability_repo=availability,
                               fulfillers_repo=FakeDocumentRepository("fulfiller_id"), exceptions_repo=FakeDocumentRepository("exception_id"),
                               appointments_repo=appts, slot_locks_repo=FakeSlotLockRepository(), connections_repo=None)
        self.assertEqual(resp["statusCode"], 200)
        stored = appts.get("t1", "a1")
        self.assertEqual(stored["starts_at"], slot)
        self.assertNotIn("awaiting_schedule", stored)

    def test_schedule_rejects_taken_slot(self):
        services, availability, appts = self._env()
        slot = _iso_tomorrow()
        locks = FakeSlotLockRepository()
        locks.claim("t1", None, slot, appointment_id="other", hold_expires_at=9999999999, now=0)  # already taken
        event = {"httpMethod": "POST", "path": "/services/appointments/manage/schedule",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1", "manage_token": "tok", "slot_start": slot})}
        resp = booking_handler(event, None, services_repo=services, availability_repo=availability,
                               fulfillers_repo=FakeDocumentRepository("fulfiller_id"), exceptions_repo=FakeDocumentRepository("exception_id"),
                               appointments_repo=appts, slot_locks_repo=locks, connections_repo=None)
        self.assertEqual(resp["statusCode"], 409)


class BookThenPayCheckoutTests(unittest.TestCase):
    def test_book_then_pay_confirms_unpaid_without_stripe(self):
        services = FakeDocumentRepository("service_id")
        services.put(normalize_service_pricing(priced_service(booking_flow="book_then_pay")))
        availability = FakeDocumentRepository("availability_id")
        availability.put({"tenant_id": "t1", "availability_id": "default", "timezone": "UTC", "slot_interval_minutes": 60,
                          "lead_time_minutes": 0, "weekly_hours": [{"day": d, "enabled": True, "start_time": "00:00", "end_time": "23:00"} for d in DAYS]})
        appts = FakeDocumentRepository("appointment_id")
        common = dict(services_repo=services, availability_repo=availability, fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
                      exceptions_repo=FakeDocumentRepository("exception_id"), appointments_repo=appts,
                      slot_locks_repo=FakeSlotLockRepository(), connections_repo=None)
        slot = _iso_tomorrow()
        reserve = booking_handler({"httpMethod": "POST", "path": "/services/appointments/reserve",
                                   "queryStringParameters": {"tenant_id": "t1"},
                                   "body": json.dumps({"service_id": "svc_1", "slot_start": slot, "customer": {"email": "c@e.com"}})},
                                  None, **common)
        token = json.loads(reserve["body"])["manage_token"]
        appt_id = json.loads(reserve["body"])["appointment"]["appointment_id"]
        checkout = booking_handler({"httpMethod": "POST", "path": "/services/appointments/checkout",
                                    "queryStringParameters": {"tenant_id": "t1"},
                                    "body": json.dumps({"appointment_id": appt_id, "manage_token": token})},
                                   None, **common)
        body = json.loads(checkout["body"])
        self.assertEqual(body["status"], "booked")
        self.assertEqual(body["payment_status"], "unpaid")  # book first, pay later via invoice
        self.assertEqual(appts.get("t1", appt_id)["status"], "booked")


class BookThenPayTests(unittest.TestCase):
    def test_invoice_from_appointment_links_source(self):
        appt = {"tenant_id": "t1", "appointment_id": "a1", "service_id": "svc_1", "service_name": "Tax Prep",
                "price": {"currency": "usd", "unit_amount": 15000, "tenant_keyed_amount": 15000}}
        inv = invoice_from_appointment(appt, invoice_id="inv_1", now=1000)
        self.assertEqual(inv["status"], "draft")
        self.assertEqual(inv["source"]["appointment_id"], "a1")
        self.assertEqual(inv["line_items"][0]["unit_amount"], 15000)
        self.assertEqual(inv["amounts"]["total"], 15000)

    def test_invoice_from_appointment_route(self):
        invoices = FakeDocumentRepository("invoice_id")
        appts = FakeDocumentRepository("appointment_id")
        appts.put({"tenant_id": "t1", "appointment_id": "a1", "service_id": "svc_1", "service_name": "Tax Prep",
                   "customer": {"email": "c@e.com", "name": "Casey"}, "price": {"currency": "usd", "unit_amount": 15000}})
        event = {"httpMethod": "POST", "path": "/invoices/from-appointment", "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"appointment_id": "a1"})}
        resp = invoices_handler(event, None, repository=invoices, appointments_repo=appts)
        self.assertEqual(resp["statusCode"], 201)
        body = json.loads(resp["body"])
        self.assertTrue(body["created"])
        # idempotent: second call returns the existing invoice
        resp2 = invoices_handler(event, None, repository=invoices, appointments_repo=appts)
        self.assertFalse(json.loads(resp2["body"])["created"])

    def test_invoice_paid_marks_appointment_paid(self):
        import os as _os
        invoices = FakeDocumentRepository("invoice_id")
        invoices.put({"tenant_id": "t1", "invoice_id": "inv_1", "status": "open", "document_type": "invoice",
                      "customer": {"email": "c@e.com"}, "amounts": {"currency": "usd", "total": 15000},
                      "source": {"appointment_id": "a1"}})
        appts = FakeDocumentRepository("appointment_id")
        appts.put({"tenant_id": "t1", "appointment_id": "a1", "payment_status": "unpaid", "status": "booked"})
        event = {"type": "invoice.paid", "data": {"object": {"metadata": {"invoice_id": "inv_1", "tenant_id": "t1"},
                 "payment_intent": "pi_1", "amount_paid": 15000, "currency": "usd"}}}
        _os.environ["SERVICES_TABLE"] = "jb-services-test"
        try:
            persist_invoice_event(event, tenant_id="t1", event_type="invoice.paid", mode="test",
                                  invoices_repo=invoices, appointments_repo=appts, now_fn=lambda: 1000)
        finally:
            _os.environ.pop("SERVICES_TABLE", None)
        self.assertEqual(appts.get("t1", "a1")["payment_status"], "paid")


if __name__ == "__main__":
    unittest.main()
