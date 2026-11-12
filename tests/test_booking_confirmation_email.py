"""The customer's booking confirmation.

Reported from production 2026-11-12: a customer booked a massage from the landing page, the booking
appeared in the dashboard, on the tenant's calendar and in the bell — and the customer was emailed
nothing, while the page they had just used said "Your booking is confirmed — check your email for
details".

Nothing had ever sent it. `mailer_send` reached the booking flow only for the DELEGATE notice, and the
SMS reminders are a nudge before the appointment, not a confirmation of it.
"""
import pathlib
import re
import unittest

from stripe_link.delegation import apply_delegation, notify_customer_booked
from stripe_link.domain.booking_email import booking_confirmation
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = ROOT / "dashboard" / "src" / "components" / "services" / "AppointmentsPanel.vue"

ORGANIZATION = {"name": "Luxe Wellness Spa",
                "address": {"street": "75 S 100 E", "locality": "St. George", "region": "UT",
                            "postal_code": "84770", "country": "US"}}


def appointment(**overrides):
    base = {
        "tenant_id": "t1", "appointment_id": "appt_1", "document_type": "appointment",
        "services": [{"service_id": "svc_1", "service_name": "60-Minute Massage",
                      "price_id": "p1", "duration_minutes": 60,
                      "price": {"currency": "usd", "unit_amount": 7800}}],
        "duration_minutes": 60,
        "starts_at": "2026-11-12T08:00:00-07:00", "ends_at": "2026-11-12T09:00:00-07:00",
        "timezone": "America/Denver", "status": "booked", "payment_status": "unpaid",
        "booking_flow": "book_then_pay",
        "customer": {"name": "Kelly Hopper", "email": "kelly@example.com"},
    }
    base.update(overrides)
    return base


class WhatTheCustomerIsTold(unittest.TestCase):
    def test_the_time_is_in_the_subject_and_in_english(self):
        content = booking_confirmation(appointment(), {"name": "60-Minute Massage"},
                                       business_name="Luxe Wellness Spa", organization=ORGANIZATION)
        self.assertIn("60-Minute Massage", content["subject"])
        # A phone shows the subject and nothing else, so WHEN has to survive there.
        self.assertIn("Thursday, November 12, 2026", content["subject"])
        self.assertIn("8:00 AM", content["subject"])
        self.assertIn("Luxe Wellness Spa", content["subject"])
        # The appointment's zone, not the reader's: 8:00 AM is 8:00 AM when you turn up.
        self.assertIn("8:00 AM", content["text"])
        self.assertNotIn("15:00", content["text"])

    def test_it_says_where(self):
        content = booking_confirmation(appointment(), None, business_name="Luxe Wellness Spa",
                                       organization=ORGANIZATION)
        self.assertIn("75 S 100 E, St. George, UT, 84770", content["text"])
        self.assertIn("75 S 100 E", content["html"])

    def test_a_site_with_no_address_simply_omits_where(self):
        content = booking_confirmation(appointment(), None, business_name="X", organization={})
        self.assertNotIn("Where", content["text"])
        self.assertIn("60-Minute Massage", content["text"])

    def test_book_then_pay_says_an_invoice_is_coming(self):
        content = booking_confirmation(appointment(), None, business_name="X")
        self.assertIn("USD 78.00", content["text"])
        self.assertIn("invoice", content["text"])

    def test_a_paid_booking_says_paid_not_due(self):
        content = booking_confirmation(appointment(payment_status="paid", booking_flow="pay_then_book"),
                                       None, business_name="X")
        self.assertIn("Paid in full", content["text"])
        self.assertNotIn("invoice", content["text"])

    def test_a_free_booking_says_nothing_about_money(self):
        """A sentence about $0.00 only makes the reader wonder whether they have been charged."""
        free = appointment(services=[{"service_id": "svc_1", "service_name": "Intro Call",
                                      "price_id": "p1", "duration_minutes": 15,
                                      "price": {"currency": "usd", "unit_amount": 0}}])
        content = booking_confirmation(free, None, business_name="X")
        self.assertNotIn("0.00", content["text"])
        self.assertNotIn("due", content["text"])

    def test_it_offers_a_way_to_cancel_that_actually_exists(self):
        """No manage LINK: the routes exist but nothing renders a page for them, so a button here would
        be an invented URL. Reply-To is the tenant's verified address, so replying reaches a human."""
        content = booking_confirmation(appointment(), None, business_name="X")
        self.assertIn("reply to this email", content["text"])
        self.assertNotIn("/services/appointments/manage", content["html"])

    def test_no_readable_start_time_means_no_email(self):
        """Refusing is the safe answer. A confirmation whose whole job is to say WHEN, with no when in
        it, tells the customer they are booked and leaves them unable to turn up."""
        for broken in ({"starts_at": ""}, {"starts_at": "not-a-date"}, {"starts_at": "2026-11-12T08:00:00"}):
            with self.subTest(**broken):
                self.assertEqual(booking_confirmation(appointment(**broken), None)["subject"], "")


class WhoGetsSent(unittest.TestCase):
    def test_no_customer_email_is_a_no_op_not_a_crash(self):
        sent = []
        appt = appointment(customer={"name": "Walk-in"})
        self.assertFalse(notify_customer_booked(appt, None, mailer_send=lambda **kw: sent.append(kw)))
        self.assertEqual(sent, [])

    def test_a_refused_subject_is_honoured(self):
        sent = []
        self.assertFalse(notify_customer_booked(appointment(starts_at=""), None,
                                                mailer_send=lambda **kw: sent.append(kw)))
        self.assertEqual(sent, [])

    def test_a_delivery_failure_does_not_break_the_booking(self):
        def explode(**_kw):
            raise RuntimeError("SES is down")
        self.assertFalse(notify_customer_booked(appointment(), None, mailer_send=explode))


class ThroughTheRealTransition(unittest.TestCase):
    """`apply_delegation` is the one function every path to `status: "booked"` already calls, which is why
    the notice hangs off it rather than off three call sites that must agree."""

    def _repos(self):
        appointments = FakeDocumentRepository("appointment_id")
        services = FakeDocumentRepository("service_id")
        services.put({"service_id": "svc_1", "tenant_id": "t1", "name": "60-Minute Massage"})
        fulfillers = FakeDocumentRepository("fulfiller_id")
        tenants = FakeDocumentRepository("tenant_id")
        tenants.put({"tenant_id": "t1", "business_name": "Luxe Wellness Spa"})
        connections = FakeDocumentRepository("connection_id")
        return appointments, services, fulfillers, tenants, connections

    def _run(self, *, change):
        appointments, services, fulfillers, tenants, connections = self._repos()
        appt = appointment()
        appointments.put(appt)
        sent = []
        apply_delegation(appt, action="upsert", change=change, appointments_repo=appointments,
                         services_repo=services, fulfillers_repo=fulfillers,
                         connections_repo=connections, tenant_repo=tenants,
                         mailer_send=lambda **kw: sent.append(kw))
        return sent

    def test_a_booking_with_nobody_assigned_still_emails_the_customer(self):
        """The identity lookup used to sit INSIDE `if fulfiller:`. This tenant has no fulfillers at all --
        the state the reported booking was taken in -- so nothing resolved and nothing was sent."""
        sent = self._run(change="booked")
        self.assertEqual([m["to"] for m in sent], ["kelly@example.com"])
        self.assertIn("60-Minute Massage", sent[0]["subject"])

    def test_a_cancellation_does_not_send_a_confirmation(self):
        """Stated as a test because the alternative is worse than silence: telling someone their cancelled
        appointment is confirmed. A real cancellation email is not written yet."""
        for change in ("canceled", "rescheduled"):
            with self.subTest(change=change):
                self.assertEqual(self._run(change=change), [])


class TheDayListReadsForwards(unittest.TestCase):
    """The appointments table sorted newest-first, the way an orders table does. An order is a thing that
    HAPPENED; an appointment is a thing that is going to, so that put the end of the day at the top. It
    also disagreed with the day list directly above it on the same screen, which was already ascending."""

    def test_both_lists_sort_the_same_direction(self):
        source = PANEL.read_text()
        comparators = re.findall(r"\.sort\(\((\w+), (\w+)\) =>\s*String\((\w+)\.", source)
        self.assertTrue(comparators, "the appointment sorts are gone or were rewritten")
        for first, _second, compared in comparators:
            self.assertEqual(compared, first,
                             "ascending means comparing the FIRST argument first; this one is reversed")
