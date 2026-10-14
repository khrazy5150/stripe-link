"""The reminder sweep (plans/WEBINAR.md P2).

Driven by EVENTS, not by leads. Registrations are leads keyed by TENANT with no index on `occurrence_id`
(§10a), so finding "everyone registered for Wednesday" by scanning the lead table would mean reading every
tenant's entire lead history every fifteen minutes — a high-volume PII table, swept for the benefit of the
handful of sessions actually starting soon.
"""
import unittest

from handlers.event_reminders import handler
from stripe_link.domain import events
from tests.fakes import FakeDocumentRepository

NOW = 1_800_000_000
DAY = 86_400


def _event(*occurrences, event_id="ev_1", tenant="t1"):
    return {"schema_version": "1.0.0", "document_type": "event", "tenant_id": tenant,
            "event_id": event_id, "title": "Live training", "duration_minutes": 60,
            "join_url": "https://meet.example/x", "occurrences": list(occurrences)}


def _occ(occurrence_id="o1", starts=NOW + 3600, **extra):
    return {"occurrence_id": occurrence_id, "starts_at": starts, "timezone": "UTC", **extra}


def _lead(email, occurrence_id="o1", event_id="ev_1", tenant="t1", lead_id=None):
    return {"schema_version": "1.0.0", "document_type": "lead_submission", "tenant_id": tenant,
            "lead_id": lead_id or f"lead_{email}", "offer_id": "off_1", "created_at": NOW,
            "event_id": event_id, "occurrence_id": occurrence_id,
            "fields": {"email": email, "name": email.split("@")[0]}}


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.events = FakeDocumentRepository("event_id")
        self.leads = FakeDocumentRepository("lead_id")
        self.sent = []

    def run_sweep(self, now=NOW):
        return handler(None, None, events_repo=self.events, leads_repo=self.leads,
                       send_fn=lambda ev, occ, who, lead, tenant: self.sent.append(
                           (who["email"], lead, occ["occurrence_id"])),
                       now_fn=lambda: now)

    def test_it_emails_the_registrants_of_an_imminent_session(self):
        self.events.put(_event(_occ(starts=NOW + 1800)))
        self.leads.put(_lead("a@x.co"))
        self.leads.put(_lead("b@x.co"))
        self.run_sweep()
        self.assertEqual({who for who, _, _ in self.sent}, {"a@x.co", "b@x.co"})

    def test_it_does_not_remind_twice(self):
        """The outcome is stamped onto the occurrence, so a second sweep finds nothing due."""
        self.events.put(_event(_occ(starts=NOW + 1800)))
        self.leads.put(_lead("a@x.co"))
        self.run_sweep()
        before = len(self.sent)
        self.run_sweep()
        self.assertEqual(len(self.sent), before)

    def test_the_hour_notice_still_goes_after_the_day_notice(self):
        self.events.put(_event(_occ(starts=NOW + DAY - 60)))
        self.leads.put(_lead("a@x.co"))
        self.run_sweep()
        self.assertEqual([lead for _, lead, _ in self.sent], [1440])
        self.run_sweep(now=NOW + DAY - 1800)
        self.assertEqual([lead for _, lead, _ in self.sent], [1440, 60])

    def test_a_distant_session_is_skipped_without_listing_leads(self):
        """The horizon is what keeps this cheap: no lead read for a session three weeks out."""
        self.events.put(_event(_occ(starts=NOW + 21 * DAY)))
        class Exploding:
            def list_for_tenant(self, *_a):
                raise AssertionError("leads must not be listed for a distant session")
        handler(None, None, events_repo=self.events, leads_repo=Exploding(),
                send_fn=lambda *a: None, now_fn=lambda: NOW)

    def test_a_started_session_is_never_reminded(self):
        """A reminder arriving mid-session is noise; the page is already showing the join link."""
        self.events.put(_event(_occ(starts=NOW - 60)))
        self.leads.put(_lead("a@x.co"))
        self.run_sweep()
        self.assertEqual(self.sent, [])

    def test_a_cancelled_session_is_never_reminded(self):
        self.events.put(_event(_occ(starts=NOW + 1800, status="cancelled")))
        self.leads.put(_lead("a@x.co"))
        self.run_sweep()
        self.assertEqual(self.sent, [])

    def test_only_the_right_occurrences_registrants_are_mailed(self):
        """Two sittings of one event; the Australia crowd must not be told the USA session is starting."""
        self.events.put(_event(_occ("usa", NOW + 1800), _occ("aus", NOW + 20 * DAY)))
        self.leads.put(_lead("usa@x.co", occurrence_id="usa"))
        self.leads.put(_lead("aus@x.co", occurrence_id="aus"))
        self.run_sweep()
        self.assertEqual([who for who, _, _ in self.sent], ["usa@x.co"])

    def test_another_tenants_leads_are_never_mailed(self):
        self.events.put(_event(_occ(starts=NOW + 1800)))
        self.leads.put(_lead("mine@x.co"))
        self.leads.put(_lead("theirs@x.co", tenant="t2", lead_id="other"))
        self.run_sweep()
        self.assertEqual([who for who, _, _ in self.sent], ["mine@x.co"])

    def test_a_lead_for_a_different_event_is_ignored(self):
        self.events.put(_event(_occ(starts=NOW + 1800)))
        self.leads.put(_lead("ours@x.co"))
        self.leads.put(_lead("other@x.co", event_id="ev_other", lead_id="l_other"))
        self.run_sweep()
        self.assertEqual([who for who, _, _ in self.sent], ["ours@x.co"])

    def test_an_ordinary_lead_is_ignored(self):
        self.events.put(_event(_occ(starts=NOW + 1800)))
        plain = _lead("plain@x.co")
        plain["event_id"] = ""
        plain["occurrence_id"] = ""
        self.leads.put(plain)
        self.run_sweep()
        self.assertEqual(self.sent, [])

    def test_one_bad_address_does_not_stop_the_room(self):
        self.events.put(_event(_occ(starts=NOW + 1800)))
        for who in ("a@x.co", "boom@x.co", "c@x.co"):
            self.leads.put(_lead(who))
        delivered = []
        def flaky(ev, occ, registrant, lead, tenant):
            if registrant["email"] == "boom@x.co":
                raise RuntimeError("bounced")
            delivered.append(registrant["email"])
        result = handler(None, None, events_repo=self.events, leads_repo=self.leads,
                         send_fn=flaky, now_fn=lambda: NOW)
        self.assertEqual(sorted(delivered), ["a@x.co", "c@x.co"])
        self.assertEqual(result["failed"], 1)

    def test_a_session_with_no_registrants_is_still_marked(self):
        """Otherwise the leads are re-listed every fifteen minutes until the session starts."""
        self.events.put(_event(_occ(starts=NOW + 1800)))
        self.run_sweep()
        stored = self.events.get("t1", "ev_1")
        self.assertTrue(events.reminder_sent(events.occurrences(stored)[0], 60))


class TheScheduleIsDerivedNotStored(unittest.TestCase):
    """A stored schedule has to be rewritten whenever the tenant moves the session, and a missed sweep
    leaves it stale. Deriving from `starts_at` means a sweep that fails sends LATE rather than not at
    all."""

    EVENT = {"duration_minutes": 60}

    def test_moving_a_session_moves_its_reminders_with_no_rewrite(self):
        occurrence = _occ(starts=NOW + 10 * DAY)
        self.assertEqual(events.due_reminder_leads(self.EVENT, occurrence, now=NOW), [])
        moved = {**occurrence, "starts_at": NOW + 1800}
        # Most imminent first: the caller sends [0] and supersedes the rest.
        self.assertEqual(events.due_reminder_leads(self.EVENT, moved, now=NOW), [60, 1440])

    def test_a_late_sweep_still_sends(self):
        occurrence = _occ(starts=NOW + 600)
        self.assertIn(60, events.due_reminder_leads(self.EVENT, occurrence, now=NOW))

    def test_the_most_imminent_notice_sorts_first(self):
        """Both are due at once on a session created ten minutes before it runs. "Starts tomorrow" about a
        session starting in ten minutes is not a duplicate, it is WRONG -- so the hour notice leads and the
        day notice is superseded rather than queued."""
        self.assertEqual(events.due_reminder_leads(self.EVENT, _occ(starts=NOW + 600), now=NOW), [60, 1440])

    def test_a_superseded_notice_never_comes_back(self):
        occurrence = _occ(starts=NOW + 600)
        settled = events.record_reminder(occurrence, 1440, now=NOW, status="superseded")
        self.assertNotIn(1440, events.due_reminder_leads(self.EVENT, settled, now=NOW))


class TheHandlerIsSeparateFromTheSmsSweep(unittest.TestCase):
    def test_it_does_not_depend_on_an_origination_number(self):
        """`handlers/reminders.py` returns early when no 10DLC number is configured. Folding email into it
        would have made these silently depend on an SMS registration they have nothing to do with."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
                  / "event_reminders.py").read_text(encoding="utf-8")
        # The CODE, not the prose: the docstring explains the separation and naturally says the word.
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        code = code[code.index('"""', code.index('"""') + 3):]
        self.assertNotIn("resolve_origination", code)
        self.assertNotIn("send_sms", code)
        self.assertNotIn("sms_not_configured", code)


if __name__ == "__main__":
    unittest.main()
