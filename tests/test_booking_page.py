import unittest

from handlers.booking import handler
from stripe_link.runtime.booking_page import render_booking_page
from tests.fakes import FakeDocumentRepository

SERVICE = {
    "service_id": "svc_1",
    "tenant_id": "t1",
    "name": "60-Minute Massage",
    "description": "Deep tissue.",
    "duration_minutes": 60,
    "price": {"currency": "usd", "unit_amount": 12000},
    "active": True,
}


class BookingPageRenderTests(unittest.TestCase):
    def test_renders_service_and_embeds_id(self):
        html = render_booking_page(SERVICE)
        self.assertIn("60-Minute Massage", html)
        self.assertIn("$120.00", html)
        self.assertIn("1 hr", html)
        self.assertIn('var serviceId = "svc_1"', html)
        # the script drives the public API on the same origin
        self.assertIn("/services/appointments/reserve", html)
        self.assertIn("/services/appointments/checkout", html)

    def test_shows_sms_consent_line(self):
        html = render_booking_page(SERVICE)
        self.assertIn("SMS appointment reminders", html)
        self.assertIn("reply STOP to opt out", html)

    def test_free_service_shows_free(self):
        html = render_booking_page({**SERVICE, "price": {"currency": "usd", "unit_amount": 0}})
        self.assertIn("Free", html)

    def test_escapes_service_name(self):
        html = render_booking_page({**SERVICE, "name": "<script>x</script>"})
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)


class BookingPageRouteTests(unittest.TestCase):
    def _services(self):
        repo = FakeDocumentRepository("service_id")
        repo.put({**SERVICE})
        return repo

    def test_page_route_returns_html(self):
        event = {"httpMethod": "GET", "path": "/book/svc_1", "pathParameters": {"service": "svc_1"}}
        response = handler(event, None, services_repo=self._services(),
                           availability_repo=FakeDocumentRepository("availability_id"),
                           fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
                           exceptions_repo=FakeDocumentRepository("exception_id"),
                           appointments_repo=FakeDocumentRepository("appointment_id"))
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("text/html", response["headers"]["Content-Type"])
        self.assertIn("60-Minute Massage", response["body"])

    def test_unknown_service_returns_404_html(self):
        event = {"httpMethod": "GET", "path": "/book/nope", "pathParameters": {"service": "nope"}}
        response = handler(event, None, services_repo=FakeDocumentRepository("service_id"),
                           availability_repo=FakeDocumentRepository("availability_id"),
                           fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
                           exceptions_repo=FakeDocumentRepository("exception_id"),
                           appointments_repo=FakeDocumentRepository("appointment_id"))
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("text/html", response["headers"]["Content-Type"])


if __name__ == "__main__":
    unittest.main()
