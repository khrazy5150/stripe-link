"""P3 operations: who is coming, and telling them when it is off (plans/WEBINAR.md §12.3).

A registration is a lead carrying its session. Until this phase the Leads screen had no idea events
existed, so two sittings of one event were indistinguishable and "who is coming on Wednesday" — the
question a host asks on the morning of a session — was unanswerable in the UI.
"""
import json
import pathlib
import unittest

from handlers.events import handler
from stripe_link.domain.registration_email import registration_cancelled
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEADS_SCREEN = (ROOT / "dashboard" / "src" / "components" / "Leads.vue").read_text(encoding="utf-8")
LEADS_STORE = (ROOT / "dashboard" / "src" / "stores" / "leads.js").read_text(encoding="utf-8")

NOW = 2_000_000_000
SOON = NOW + 86_400
LATER = NOW + 86_400 * 7
PAST = NOW - 86_400


def _event(*occurrences):
    return {"schema_version": "1.0.0", "document_type": "event", "tenant_id": "t1", "event_id": "ev_1",
            "title": "Live training", "duration_minutes": 60, "occurrences": list(occurrences)}


def _occ(occurrence_id="o1", starts=SOON, status="scheduled"):
    return {"occurrence_id": occurrence_id, "starts_at": starts, "timezone": "UTC", "status": status}


def _lead(email, occurrence_id="o1", event_id="ev_1"):
    return {"schema_version": "1.0.0", "document_type": "lead_submission", "tenant_id": "t1",
            "lead_id": f"lead_{email}", "offer_id": "off_1", "created_at": NOW,
            "event_id": event_id, "occurrence_id": occurrence_id,
            "fields": {"email": email, "name": email.split("@")[0]}}


class CancellingASessionTellsThePeopleInIt(unittest.TestCase):
    def setUp(self):
        self.events = FakeDocumentRepository("event_id")
        self.leads = FakeDocumentRepository("lead_id")
        self.told = []

    def save(self, document):
        return handler(
            {"httpMethod": "POST", "body": json.dumps(document)}, None,
            events_repo=self.events, leads_repo=self.leads, now_fn=lambda: NOW,
            notify_fn=lambda ev, occ, who, replacement, tenant: self.told.append(
                (who["email"], occ["occurrence_id"], (replacement or {}).get("occurrence_id"))),
        )

    def test_registrants_are_told(self):
        self.events.put(_event(_occ()))
        self.leads.put(_lead("a@x.co"))
        self.leads.put(_lead("b@x.co"))
        self.save(_event(_occ(status="cancelled")))
        self.assertEqual({who for who, _, _ in self.told}, {"a@x.co", "b@x.co"})

    def test_only_the_cancelled_sessions_registrants(self):
        """Two sittings; cancelling one must not alarm the other."""
        self.events.put(_event(_occ("keep"), _occ("drop", LATER)))
        self.leads.put(_lead("keep@x.co", occurrence_id="keep"))
        self.leads.put(_lead("drop@x.co", occurrence_id="drop"))
        self.save(_event(_occ("keep"), _occ("drop", LATER, status="cancelled")))
        self.assertEqual([who for who, _, _ in self.told], ["drop@x.co"])

    def test_resaving_does_not_re_send(self):
        """Only a session that changed TO cancelled. Editing the title afterwards must not re-announce it."""
        self.events.put(_event(_occ(status="cancelled")))
        self.leads.put(_lead("a@x.co"))
        self.save({**_event(_occ(status="cancelled")), "title": "Renamed"})
        self.assertEqual(self.told, [])

    def test_a_session_that_already_ran_is_not_announced(self):
        """Telling someone a session they attended is cancelled is worse than silence."""
        self.events.put(_event(_occ(starts=PAST)))
        self.leads.put(_lead("a@x.co"))
        self.save(_event(_occ(starts=PAST, status="cancelled")))
        self.assertEqual(self.told, [])

    def test_a_remaining_session_is_offered_as_the_alternative(self):
        self.events.put(_event(_occ("drop"), _occ("keep", LATER)))
        self.leads.put(_lead("a@x.co", occurrence_id="drop"))
        self.save(_event(_occ("drop", status="cancelled"), _occ("keep", LATER)))
        self.assertEqual([replacement for _, _, replacement in self.told], ["keep"])

    def test_cancelling_everything_offers_nothing(self):
        """A tenant cancelling both sittings must not have one offered back as the replacement."""
        self.events.put(_event(_occ("a"), _occ("b", LATER)))
        self.leads.put(_lead("x@x.co", occurrence_id="a"))
        self.save(_event(_occ("a", status="cancelled"), _occ("b", LATER, status="cancelled")))
        self.assertEqual([replacement for _, _, replacement in self.told], [None])

    def test_an_ordinary_save_notifies_nobody(self):
        self.events.put(_event(_occ()))
        self.leads.put(_lead("a@x.co"))
        self.save(_event(_occ(), _occ("second", LATER)))
        self.assertEqual(self.told, [])

    def test_a_brand_new_event_notifies_nobody(self):
        """There is no previous document to compare, and nobody has registered."""
        self.save(_event(_occ(status="cancelled")))
        self.assertEqual(self.told, [])

    def test_the_save_still_succeeds(self):
        self.events.put(_event(_occ()))
        response = self.save(_event(_occ(status="cancelled")))
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(
            self.events.get("t1", "ev_1")["occurrences"][0]["status"], "cancelled")


class TheCancellationEmail(unittest.TestCase):
    EVENT = {"title": "Live training", "duration_minutes": 60}
    OCC = {"occurrence_id": "o1", "starts_at": SOON, "timezone": "UTC"}

    def test_it_says_so_in_the_subject(self):
        """The one email nobody wants to receive; burying it would be worse."""
        message = registration_cancelled(self.EVENT, self.OCC, name="Jane")
        self.assertTrue(message["subject"].startswith("Cancelled:"))

    def test_it_offers_the_alternative_when_there_is_one(self):
        other = {"occurrence_id": "o2", "starts_at": LATER, "timezone": "UTC"}
        message = registration_cancelled(self.EVENT, self.OCC, replacement=other)
        self.assertIn("running it again", message["text"])
        self.assertIn("not transferred automatically", message["text"])

    def test_it_does_not_pretend_there_is_one(self):
        message = registration_cancelled(self.EVENT, self.OCC)
        self.assertNotIn("running it again", message["text"])
        self.assertIn("Sorry", message["text"])

    def test_it_escapes_the_tenants_words(self):
        message = registration_cancelled({**self.EVENT, "title": "<script>"}, self.OCC)
        self.assertIn("&lt;script&gt;", message["html"])


class TheLeadsScreenKnowsAboutSessions(unittest.TestCase):
    def test_a_registration_shows_which_session(self):
        self.assertIn("sessionLabel(lead)", LEADS_SCREEN)

    def test_the_list_can_be_filtered_to_one(self):
        self.assertIn("store.filterSession", LEADS_SCREEN)
        self.assertIn("filterSession", LEADS_STORE)

    def test_the_filter_offers_only_sessions_that_have_registrations(self):
        """A dropdown listing every sitting a tenant ever ran is a filter nobody can find theirs in."""
        self.assertIn("const sessionOptions = computed", LEADS_SCREEN)
        options = LEADS_SCREEN[LEADS_SCREEN.index("const sessionOptions = computed"):][:700]
        self.assertIn("for (const lead of store.leads)", options)

    def test_the_export_carries_the_event_and_the_session(self):
        """The registrant list is the thing most likely to be handed to whoever runs the webinar."""
        self.assertIn('"event", "session"', LEADS_SCREEN)
        self.assertIn("eventTitle(lead), sessionWhen(lead)", LEADS_SCREEN)

    def test_an_ordinary_lead_is_unaffected(self):
        """These helpers all return "" without an event, so a non-registration row looks as it did."""
        for helper in ("function eventTitle(lead)", "function sessionWhen(lead)", "function sessionLabel(lead)"):
            with self.subTest(helper=helper):
                self.assertIn(helper, LEADS_SCREEN)
        self.assertIn("if (!lead?.event_id) return \"\";", LEADS_SCREEN)


if __name__ == "__main__":
    unittest.main()
