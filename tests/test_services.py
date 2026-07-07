import json
import unittest

from handlers.services import handler
from stripe_link.domain.appointments import AppointmentTransitionError, transition_appointment
from tests.fakes import FakeDocumentRepository


def appointment(**overrides):
    base = {
        "schema_version": "2026-05-29",
        "document_type": "appointment",
        "tenant_id": "tenant-1",
        "appointment_id": "appt_1",
        "service_id": "svc_1",
        "starts_at": "2026-07-10T15:00:00Z",
        "ends_at": "2026-07-10T16:00:00Z",
        "timezone": "America/Denver",
        "status": "booked",
        "customer": {"email": "c@example.com"},
    }
    base.update(overrides)
    return base


def event(method, path, *, tenant_id="tenant-1", path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": {"tenant_id": tenant_id},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
    }


class TransitionAppointmentTests(unittest.TestCase):
    def test_check_in_from_booked(self):
        result = transition_appointment(appointment(status="booked"), "check-in", now_epoch=1_800_000_000)
        self.assertEqual(result["status"], "checked_in")
        self.assertIn("checked_in_at", result)
        self.assertEqual(result["updated_at"], 1_800_000_000)

    def test_illegal_transition_raises(self):
        with self.assertRaises(AppointmentTransitionError):
            transition_appointment(appointment(status="completed"), "check-in", now_epoch=1)

    def test_cancel_allowed_from_reserved(self):
        result = transition_appointment(appointment(status="reserved"), "cancel", now_epoch=1)
        self.assertEqual(result["status"], "canceled")
        self.assertIn("canceled_at", result)

    def test_assign_sets_fulfiller_without_status_change(self):
        result = transition_appointment(
            appointment(status="booked"), "assign", now_epoch=1, assigned_fulfiller_id="ful_9"
        )
        self.assertEqual(result["assigned_fulfiller_id"], "ful_9")
        self.assertEqual(result["status"], "booked")

    def test_assign_requires_fulfiller(self):
        with self.assertRaises(AppointmentTransitionError):
            transition_appointment(appointment(), "assign", now_epoch=1)

    def test_unknown_action_raises(self):
        with self.assertRaises(AppointmentTransitionError):
            transition_appointment(appointment(), "teleport", now_epoch=1)


class ServicesHandlerTests(unittest.TestCase):
    def make_repos(self):
        return {
            "services_repo": FakeDocumentRepository("service_id"),
            "fulfillers_repo": FakeDocumentRepository("fulfiller_id"),
            "availability_repo": FakeDocumentRepository("availability_id"),
            "exceptions_repo": FakeDocumentRepository("exception_id"),
            "appointments_repo": FakeDocumentRepository("appointment_id"),
        }

    def test_delete_fulfiller_by_path_id(self):
        repos = self.make_repos()
        repos["fulfillers_repo"].put({"tenant_id": "tenant-1", "fulfiller_id": "ful_1", "document_type": "fulfiller"})
        response = handler(
            event("DELETE", "/services/fulfillers/ful_1", path_params={"fulfiller_id": "ful_1"}),
            None,
            **repos,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["deleted"])
        self.assertIsNone(repos["fulfillers_repo"].get("tenant-1", "ful_1"))

    def test_delete_missing_returns_404(self):
        repos = self.make_repos()
        response = handler(
            event("DELETE", "/services/availability/exceptions/exc_x", path_params={"exception_id": "exc_x"}),
            None,
            **repos,
        )
        self.assertEqual(response["statusCode"], 404)

    def test_appointment_action_check_in(self):
        repos = self.make_repos()
        repos["appointments_repo"].put(appointment(status="booked"))
        response = handler(
            event("POST", "/services/appointments/appt_1/check-in", path_params={"appointment_id": "appt_1", "action": "check-in"}),
            None,
            **repos,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["appointment"]["status"], "checked_in")

    def test_appointment_action_illegal_returns_400(self):
        # completed is terminal, so cancel is not a legal transition.
        repos = self.make_repos()
        repos["appointments_repo"].put(appointment(status="completed"))
        response = handler(
            event("POST", "/services/appointments/appt_1/cancel", path_params={"appointment_id": "appt_1", "action": "cancel"}),
            None,
            **repos,
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_transition")

    def test_appointment_action_missing_returns_404(self):
        repos = self.make_repos()
        response = handler(
            event("POST", "/services/appointments/nope/cancel", path_params={"appointment_id": "nope", "action": "cancel"}),
            None,
            **repos,
        )
        self.assertEqual(response["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
