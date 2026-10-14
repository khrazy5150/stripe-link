"""Registering for a webinar (plans/WEBINAR.md P1).

A registration is a LEAD carrying `event_id` + `occurrence_id`: one list of people, one export, one consent
story, one place PII lives.

The point of these tests is that the SERVER decides whether a session can still be registered for. The page
asks the same function at publish time, but a published page is a cached artifact and the visitor's copy may
be hours old — so a page offering a closed session must not be able to create a registration.
"""
import json
import unittest

from handlers.leads import handler
from stripe_link.domain import events
from tests.fakes import FakeDocumentRepository
from tests.test_lead_capture import _offer, _product

NOW = 1_800_000_000
SOON = NOW + 86_400
PAST = NOW - 86_400


def _event(*occurrences, event_id="ev_1"):
    return {"schema_version": "1.0.0", "document_type": "event", "tenant_id": "t1", "event_id": event_id,
            "title": "Live training", "occurrences": list(occurrences)}


def _occ(occurrence_id="o1", starts=SOON, **extra):
    return {"occurrence_id": occurrence_id, "starts_at": starts, **extra}


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.leads = FakeDocumentRepository("lead_id")
        self.offers = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.notifications = FakeDocumentRepository("notification_id")
        self.events = FakeDocumentRepository("event_id")
        self.offers.put(_offer())
        self.products.put(_product())

    def _post(self, body):
        return handler(
            {"httpMethod": "POST", "body": json.dumps(body),
             "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}},
            None,
            leads_repo=self.leads, offers_repo=self.offers, products_repo=self.products,
            notifications_repo=self.notifications, events_repo=self.events, now_fn=lambda: NOW,
        )

    def _register(self, **overrides):
        body = {"tenant_id": "t1", "offer_id": "off_1", "page_id": "pg_1",
                "fields": {"email": "jane@example.com"},
                "event_id": "ev_1", "occurrence_id": "o1"}
        body.update(overrides)
        return self._post(body)

    def test_an_open_session_accepts_the_registration(self):
        self.events.put(_event(_occ()))
        response = self._register()
        self.assertEqual(response["statusCode"], 201)
        lead = self.leads.list_for_tenant("t1")[0]
        self.assertEqual((lead["event_id"], lead["occurrence_id"]), ("ev_1", "o1"))

    def test_it_takes_a_seat(self):
        self.events.put(_event(_occ(capacity=2)))
        self._register()
        stored = self.events.get("t1", "ev_1")
        self.assertEqual(events.registered_count(events.occurrences(stored)[0]), 1)
        self.assertEqual(events.seats_left(events.occurrences(stored)[0]), 1)

    def test_a_session_that_has_started_is_refused(self):
        self.events.put(_event(_occ(starts=PAST)))
        response = self._register()
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "registration_passed")
        self.assertEqual(self.leads.list_for_tenant("t1"), [])

    def test_a_full_session_is_refused(self):
        self.events.put(_event(_occ(capacity=1, registered_count=1)))
        response = self._register()
        self.assertEqual(json.loads(response["body"])["error"], "registration_full")

    def test_a_cancelled_session_is_refused(self):
        self.events.put(_event(_occ(status="cancelled")))
        self.assertEqual(json.loads(self._register()["body"])["error"], "registration_cancelled")

    def test_the_refusal_says_which_so_the_page_can_explain(self):
        """"That session has already started" is actionable; "no" is not."""
        self.events.put(_event(_occ(starts=PAST)))
        self.assertIn("already started", json.loads(self._register()["body"])["message"])

    def test_an_unknown_occurrence_is_refused(self):
        self.events.put(_event(_occ("o1")))
        self.assertEqual(json.loads(self._register(occurrence_id="ghost")["body"])["error"],
                         "registration_unknown")

    def test_an_unknown_event_is_404(self):
        self.assertEqual(self._register()["statusCode"], 404)

    def test_the_last_seat_closes_the_session(self):
        """The check and the count are the same mechanism, so this must hold end to end."""
        self.events.put(_event(_occ(capacity=1)))
        self.assertEqual(self._register()["statusCode"], 201)
        second = self._register(fields={"email": "sam@example.com"})
        self.assertEqual(json.loads(second["body"])["error"], "registration_full")


class TheTwoIdsTravelTogether(unittest.TestCase):
    """An occurrence without its event cannot be resolved; an event without an occurrence does not say
    which session."""

    def setUp(self):
        RegistrationTests.setUp(self)

    _post = RegistrationTests._post

    def test_an_occurrence_alone_is_refused(self):
        response = self._post({"tenant_id": "t1", "offer_id": "off_1", "fields": {"email": "a@b.co"},
                               "occurrence_id": "o1"})
        self.assertEqual(json.loads(response["body"])["error"], "invalid_registration")

    def test_an_event_alone_is_refused(self):
        response = self._post({"tenant_id": "t1", "offer_id": "off_1", "fields": {"email": "a@b.co"},
                               "event_id": "ev_1"})
        self.assertEqual(json.loads(response["body"])["error"], "invalid_registration")

    def test_the_document_validator_agrees(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_lead_submission
        from stripe_link.domain.leads import build_lead_submission
        half = build_lead_submission(tenant_id="t", lead_id="l", offer_id="o", page_id="p",
                                     fields={"email": "a@b.co"}, consent={}, provenance={},
                                     idempotency_key="", now=NOW, event_id="ev_1")
        with self.assertRaises(DocumentValidationError):
            validate_lead_submission(half)


class AnOrdinaryLeadIsUnaffected(unittest.TestCase):
    def setUp(self):
        RegistrationTests.setUp(self)

    _post = RegistrationTests._post

    def test_no_event_means_no_event_fields_and_no_events_table(self):
        """The common path must not depend on a table it has no business knowing about: this call passes
        no events repository at all, so building one would raise."""
        response = handler(
            {"httpMethod": "POST", "requestContext": {"identity": {"sourceIp": "1.2.3.4"}},
             "body": json.dumps({"tenant_id": "t1", "offer_id": "off_1",
                                 "fields": {"email": "jane@example.com"}})},
            None,
            leads_repo=self.leads, offers_repo=self.offers, products_repo=self.products,
            notifications_repo=self.notifications, now_fn=lambda: NOW,
        )
        self.assertEqual(response["statusCode"], 201)
        lead = self.leads.list_for_tenant("t1")[0]
        self.assertEqual((lead["event_id"], lead["occurrence_id"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
