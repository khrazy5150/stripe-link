"""Cancel and reschedule from the confirmation email: GET /booking/manage.

Asked for 2026-11-12. The API had been complete for months -- `manage/cancel`, `manage/reschedule`, and
an `_authorized_appointment` that searches both Stripe modes precisely so a customer-facing link would
work -- and nothing rendered a page, so the only way to move an appointment was to find a human.

Also here: the Appointments calendar never said WHAT was being performed, which is survivable with one
service and useless to a spa offering a 60-minute Thai and a 120-minute Swedish.
"""
import json
import os
import pathlib
import shutil
import subprocess
import unittest
from unittest import mock

from handlers.booking import handler
from stripe_link.delegation import appointment_manage_url
from stripe_link.domain.booking_email import booking_confirmation
from stripe_link.runtime.manage_page import (
    RESCHEDULABLE_STATUSES,
    appointment_service_label,
    render_manage_page,
)
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABEL = ROOT / "dashboard" / "src" / "utils" / "appointmentLabel.js"
PANEL = ROOT / "dashboard" / "src" / "components" / "services" / "AppointmentsPanel.vue"

TOKEN = "tok_abc123"


def appointment(**overrides):
    base = {
        "tenant_id": "t1", "appointment_id": "appt_1", "document_type": "appointment",
        "services": [{"service_id": "svc_1", "service_name": "60-Minute Thai Massage",
                      "price_id": "p1", "duration_minutes": 60,
                      "price": {"currency": "usd", "unit_amount": 7800}}],
        "duration_minutes": 60,
        "starts_at": "2026-11-12T08:00:00-07:00", "ends_at": "2026-11-12T09:00:00-07:00",
        "timezone": "America/Denver", "status": "booked", "payment_status": "unpaid",
        "booking_flow": "book_then_pay", "stripe_mode": "live",
        "customer": {"name": "Kelly", "email": "kelly@example.com"},
        "customer_manage_token": TOKEN,
    }
    base.update(overrides)
    return base


class ThePageSaysWhatAndWhen(unittest.TestCase):
    def test_it_names_the_service_and_the_moment(self):
        html = render_manage_page(appointment(), business_name="Luxe Wellness Spa",
                                  when="Thursday, November 12, 2026 at 8:00 AM MST",
                                  place="75 S 100 E, St. George, UT")
        self.assertIn("60-Minute Thai Massage", html)
        self.assertIn("Thursday, November 12, 2026 at 8:00 AM MST", html)
        self.assertIn("75 S 100 E, St. George, UT", html)
        self.assertIn("Luxe Wellness Spa", html)

    def test_every_line_is_named(self):
        """A visit can be a massage AND a facial; naming one of them is a different appointment."""
        two = appointment(services=[
            {"service_id": "a", "service_name": "60-Minute Thai Massage", "price_id": "p1", "duration_minutes": 60},
            {"service_id": "b", "service_name": "Express Facial", "price_id": "p2", "duration_minutes": 30},
        ])
        self.assertEqual(appointment_service_label(two), "60-Minute Thai Massage + Express Facial")
        self.assertIn("60-Minute Thai Massage + Express Facial", render_manage_page(two))

    def test_the_url_is_a_bearer_token_so_the_page_hides_from_crawlers_and_referrers(self):
        html = render_manage_page(appointment())
        self.assertIn('name="robots" content="noindex, nofollow"', html)
        self.assertIn('name="referrer" content="no-referrer"', html)

    def test_a_cancelled_appointment_offers_no_actions(self):
        html = render_manage_page(appointment(status="canceled"))
        self.assertIn("This appointment was cancelled.", html)
        self.assertIn('id="actions" hidden', html)

    def test_a_completed_appointment_cannot_be_rescheduled_either(self):
        html = render_manage_page(appointment(status="completed"))
        self.assertIn("This appointment is complete.", html)
        self.assertIn('id="actions" hidden', html)

    def test_the_reschedule_flag_follows_the_status(self):
        self.assertIn('var canReschedule = "1" === "1";',
                      render_manage_page(appointment(status="booked")))
        # Checked in: still cancellable, no longer movable -- the API would refuse, so the button goes.
        self.assertIn('var canReschedule = "" === "1";',
                      render_manage_page(appointment(status="checked_in")))

    def test_the_two_status_sets_agree_with_the_handler(self):
        """The renderer keeps its own copy so runtime/ never imports handlers/ (tests/envreach.py follows
        imports transitively). A copy that drifts offers a reschedule button the API then refuses."""
        import handlers.booking as booking_handler
        self.assertEqual(RESCHEDULABLE_STATUSES, booking_handler.RESCHEDULABLE_STATUSES)

    def test_it_posts_to_the_routes_that_already_existed(self):
        html = render_manage_page(appointment())
        self.assertIn("/services/appointments/manage/cancel", html)
        self.assertIn("/services/appointments/manage/reschedule", html)
        self.assertIn(TOKEN, html)


class TheRoute(unittest.TestCase):
    def _env(self, appt=None):
        appointments = FakeDocumentRepository("appointment_id")
        appointments.put(appt or appointment())
        return {"appointments_repo": appointments,
                "services_repo": FakeDocumentRepository("service_id"),
                "availability_repo": FakeDocumentRepository("availability_id"),
                "fulfillers_repo": FakeDocumentRepository("fulfiller_id"),
                "exceptions_repo": FakeDocumentRepository("exception_id")}

    def _get(self, params, **env_overrides):
        env = self._env()
        env.update(env_overrides)
        return handler({"httpMethod": "GET", "path": "/booking/manage", "pathParameters": {},
                        "queryStringParameters": params}, None, **env)

    def test_the_right_token_renders_the_page(self):
        response = self._get({"appointment_id": "appt_1", "manage_token": TOKEN})
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("text/html", response["headers"]["Content-Type"])
        self.assertIn("60-Minute Thai Massage", response["body"])
        # Rendered server-side, so the page already knows the moment rather than asking the API.
        self.assertIn("November 12, 2026", response["body"])

    def test_a_wrong_token_gets_html_a_person_can_read(self):
        """Not the API's JSON. A human opened this URL in a browser."""
        response = self._get({"appointment_id": "appt_1", "manage_token": "wrong"})
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("text/html", response["headers"]["Content-Type"])
        self.assertIn("could not find that appointment", response["body"])
        self.assertNotIn(TOKEN, response["body"])
        self.assertNotIn("60-Minute Thai Massage", response["body"])

    def test_no_token_at_all_leaks_nothing(self):
        response = self._get({"appointment_id": "appt_1"})
        self.assertEqual(response["statusCode"], 404)
        self.assertNotIn("60-Minute Thai Massage", response["body"])

    def test_it_is_never_cached_by_anything_in_between(self):
        response = self._get({"appointment_id": "appt_1", "manage_token": TOKEN})
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_the_json_manage_route_is_untouched(self):
        """Its own path: the dispatch matches by substring, and one path serving both would have to
        branch on a request header a mail client controls."""
        env = self._env()
        response = handler({"httpMethod": "GET", "path": "/services/appointments/manage",
                            "pathParameters": {},
                            "queryStringParameters": {"appointment_id": "appt_1", "manage_token": TOKEN}},
                           None, **env)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["can_reschedule"], True)


class TheLinkInTheEmail(unittest.TestCase):
    def test_it_carries_the_appointment_and_its_token(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_BASE_URL": "https://api.example.com/prod"}):
            url = appointment_manage_url(appointment())
        self.assertEqual(
            url, "https://api.example.com/prod/booking/manage?appointment_id=appt_1&manage_token=tok_abc123")

    def test_no_base_url_means_no_link_rather_than_a_broken_one(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_BASE_URL": ""}):
            self.assertEqual(appointment_manage_url(appointment()), "")

    def test_the_copy_follows_the_link(self):
        with_link = booking_confirmation(appointment(), None, business_name="X",
                                         manage_url="https://api.example.com/booking/manage?x=1")
        self.assertIn("Change or cancel this appointment", with_link["html"])
        self.assertIn("https://api.example.com/booking/manage?x=1", with_link["text"])
        self.assertNotIn("reply to this email", with_link["text"])

        without = booking_confirmation(appointment(), None, business_name="X")
        self.assertIn("reply to this email", without["text"])
        self.assertNotIn("Change or cancel this appointment", without["html"])


class TheCalendarSaysWhatIsBeingPerformed(unittest.TestCase):
    """`service_name` at the top level is a RESPONSE-ONLY mirror `_public_appointment` adds for the booking
    page. The dashboard list route returns raw documents, which carry no such field -- so every row read
    `a.service_name` and rendered nothing."""

    def _run(self, body):
        if not shutil.which("node"):
            self.skipTest("node not available")
        script = f"""
        import {{ appointmentServiceLabel }} from {json.dumps(str(LABEL))};
        {body}
        """
        proc = subprocess.run(["node", "--input-type=module", "-e", script],
                              capture_output=True, text=True, cwd=str(ROOT / "dashboard"), timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        return json.loads(proc.stdout)

    def test_it_reads_the_canonical_services_array(self):
        out = self._run("""
        console.log(JSON.stringify({
          stored: appointmentServiceLabel({services: [{service_name: '60-Minute Thai Massage'}]}),
          several: appointmentServiceLabel({services: [{service_name: 'Massage'}, {service_name: 'Facial'}]}),
          mirror: appointmentServiceLabel({service_name: 'From a booking-page response'}),
          id: appointmentServiceLabel({service_id: 'svc_1'}),
          nothing: appointmentServiceLabel({}),
        }));
        """)
        self.assertEqual(out["stored"], "60-Minute Thai Massage")
        self.assertEqual(out["several"], "Massage + Facial")
        self.assertEqual(out["mirror"], "From a booking-page response")
        self.assertEqual(out["id"], "svc_1")
        self.assertEqual(out["nothing"], "—")

    def test_neither_list_reads_the_missing_top_level_field(self):
        panel = PANEL.read_text()
        self.assertNotIn("a.service_name", panel,
                         "the field a stored appointment does not have")
        self.assertEqual(panel.count("appointmentServiceLabel(a)"), 2,
                         "the day list AND the table both have to say what the appointment is for")


if __name__ == "__main__":
    unittest.main()
