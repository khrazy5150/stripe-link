"""Events and their occurrences (plans/WEBINAR.md P1).

An event is the thing; an occurrence is one running of it. Registrations point at an occurrence, because
"which session did they sign up for" is what every reminder and join link has to answer.

The module is pure and takes `now`, so the renderer deciding what to show and the endpoint deciding what to
accept are literally the same function — a page cannot invite a registration the server will refuse.
"""
import unittest

from stripe_link.domain import events
from stripe_link.domain.documents import DocumentValidationError, validate_event

NOW = 1_800_000_000
SOON = NOW + 86_400
LATER = NOW + 86_400 * 7
PAST = NOW - 86_400


def event(*occurrences, **extra):
    return {"schema_version": "1.0.0", "document_type": "event", "tenant_id": "t", "event_id": "e",
            "title": "How to sell AI tools", "occurrences": list(occurrences), **extra}


def occ(occurrence_id="o1", starts=SOON, **extra):
    return {"occurrence_id": occurrence_id, "starts_at": starts, **extra}


class RegistrationState(unittest.TestCase):
    def test_a_future_occurrence_is_open(self):
        self.assertEqual(events.registration_state(occ(), now=NOW), events.OPEN)

    def test_a_past_one_has_passed(self):
        self.assertEqual(events.registration_state(occ(starts=PAST), now=NOW), events.PASSED)

    def test_the_exact_start_moment_counts_as_passed(self):
        """Registering as the host says hello helps nobody."""
        self.assertEqual(events.registration_state(occ(starts=NOW), now=NOW), events.PASSED)

    def test_a_full_one_is_full(self):
        self.assertEqual(events.registration_state(occ(capacity=2, registered_count=2), now=NOW), events.FULL)

    def test_cancelled_beats_every_other_reason(self):
        """It is the one a visitor needs explaining; "full" or "missed it" would both be misleading."""
        gone = occ(starts=PAST, capacity=1, registered_count=9, status="cancelled")
        self.assertEqual(events.registration_state(gone, now=NOW), events.CANCELLED)

    def test_past_beats_full(self):
        """"It is full" invites someone to wait for a seat that will never free up."""
        self.assertEqual(events.registration_state(occ(starts=PAST, capacity=1, registered_count=1), now=NOW),
                         events.PASSED)

    def test_an_occurrence_with_no_start_is_not_open(self):
        self.assertEqual(events.registration_state({"occurrence_id": "x"}, now=NOW), events.PASSED)


class CapacityIsOptional(unittest.TestCase):
    def test_absent_capacity_means_unlimited(self):
        self.assertIsNone(events.seats_left(occ()))
        self.assertTrue(events.is_open(occ(registered_count=10_000), now=NOW))

    def test_zero_also_means_unlimited(self):
        """A tenant who clears the field is saying "no limit", not "nobody may register"."""
        self.assertIsNone(events.seats_left(occ(capacity=0, registered_count=5)))

    def test_seats_left_counts_down(self):
        self.assertEqual(events.seats_left(occ(capacity=500, registered_count=3)), 497)

    def test_it_never_goes_negative(self):
        self.assertEqual(events.seats_left(occ(capacity=2, registered_count=9)), 0)

    def test_none_is_not_zero(self):
        """A page has to tell "unlimited" from "sold out"; these are the two states it most must not mix."""
        self.assertIsNone(events.seats_left(occ()))
        self.assertEqual(events.seats_left(occ(capacity=1, registered_count=1)), 0)


class ChoosingAnOccurrence(unittest.TestCase):
    def test_open_ones_come_back_soonest_first(self):
        e = event(occ("late", LATER), occ("soon", SOON), occ("gone", PAST))
        self.assertEqual([o["occurrence_id"] for o in events.open_occurrences(e, now=NOW)], ["soon", "late"])

    def test_sorting_does_not_trust_the_stored_order(self):
        """A tenant who adds a session out of sequence still gets a sensible picker."""
        e = event(occ("b", LATER), occ("a", SOON))
        self.assertEqual(events.next_occurrence(e, now=NOW)["occurrence_id"], "a")

    def test_nothing_open_is_none_not_an_error(self):
        self.assertIsNone(events.next_occurrence(event(occ(starts=PAST)), now=NOW))

    def test_a_cancelled_one_is_never_offered(self):
        e = event(occ("x", SOON, status="cancelled"), occ("y", LATER))
        self.assertEqual([o["occurrence_id"] for o in events.open_occurrences(e, now=NOW)], ["y"])

    def test_lookup_by_id(self):
        e = event(occ("a"), occ("b", LATER))
        self.assertEqual(events.occurrence_by_id(e, "b")["starts_at"], LATER)
        self.assertIsNone(events.occurrence_by_id(e, "nope"))
        self.assertIsNone(events.occurrence_by_id(e, ""))


class OneAnswerForThePageAndTheEndpoint(unittest.TestCase):
    def test_it_accepts_an_open_occurrence(self):
        self.assertEqual(events.accepts_registration(event(occ("a")), "a", now=NOW), (True, events.OPEN))

    def test_it_refuses_with_a_reason(self):
        e = event(occ("a", PAST), occ("b", SOON, capacity=1, registered_count=1))
        self.assertEqual(events.accepts_registration(e, "a", now=NOW), (False, events.PASSED))
        self.assertEqual(events.accepts_registration(e, "b", now=NOW), (False, events.FULL))

    def test_an_unknown_occurrence_is_refused_not_assumed(self):
        self.assertEqual(events.accepts_registration(event(occ("a")), "ghost", now=NOW), (False, "unknown"))

    def test_the_reason_is_a_state_not_a_sentence(self):
        """The wording belongs to whatever is showing it."""
        _, reason = events.accepts_registration(event(occ("a", PAST)), "a", now=NOW)
        self.assertEqual(reason, events.PASSED)
        self.assertNotIn(" ", reason)


class RecordingARegistration(unittest.TestCase):
    def test_it_increments_only_the_matching_occurrence(self):
        e = event(occ("a"), occ("b", LATER, registered_count=4))
        after = events.record_registration(e, "b")
        counts = {o["occurrence_id"]: events.registered_count(o) for o in events.occurrences(after)}
        self.assertEqual(counts, {"a": 0, "b": 5})

    def test_it_does_not_mutate_what_it_was_given(self):
        """The caller writes the result back; a function that edited the dict it was handed would make the
        write ordering impossible to follow."""
        e = event(occ("a", registered_count=1))
        events.record_registration(e, "a")
        self.assertEqual(events.registered_count(events.occurrences(e)[0]), 1)

    def test_an_unknown_occurrence_changes_nothing(self):
        e = event(occ("a"))
        self.assertEqual(events.occurrences(events.record_registration(e, "ghost")), events.occurrences(e))

    def test_it_closes_the_last_seat(self):
        e = event(occ("a", capacity=1))
        self.assertTrue(events.is_open(events.occurrences(e)[0], now=NOW))
        after = events.record_registration(e, "a")
        self.assertFalse(events.is_open(events.occurrences(after)[0], now=NOW))


class MalformedDataDoesNotTakeThePageDown(unittest.TestCase):
    def test_rows_that_are_not_objects_are_dropped(self):
        self.assertEqual(events.occurrences({"occurrences": ["x", None, {"occurrence_id": "a"}]}),
                         [{"occurrence_id": "a"}])

    def test_missing_or_rubbish_values_read_as_zero(self):
        for value in ("soon", None, [], {}):
            with self.subTest(value=value):
                self.assertEqual(events.starts_at({"starts_at": value}), 0)
                self.assertEqual(events.capacity({"capacity": value}), 0)
                self.assertEqual(events.registered_count({"registered_count": value}), 0)

    def test_an_absent_event_is_survivable(self):
        for value in (None, {}, "nope", []):
            with self.subTest(value=value):
                self.assertEqual(events.occurrences(value), [])
                self.assertIsNone(events.next_occurrence(value, now=NOW))


class TheDocumentValidator(unittest.TestCase):
    def test_a_minimal_event_validates(self):
        validate_event(event(occ()))

    def test_an_event_with_no_occurrences_yet_validates(self):
        """A tenant names the webinar before they have scheduled it."""
        validate_event(event())

    def test_a_title_is_required(self):
        with self.assertRaises(DocumentValidationError):
            validate_event({**event(occ()), "title": ""})

    def test_duplicate_occurrence_ids_are_refused(self):
        """Registrations point at an occurrence by id; a duplicate makes "which session" unanswerable and
        silently sends half of them the wrong reminder."""
        with self.assertRaises(DocumentValidationError) as caught:
            validate_event(event(occ("same"), occ("same", LATER)))
        self.assertIn("twice", str(caught.exception))

    def test_an_occurrence_needs_a_real_start(self):
        for bad in (0, -1, None):
            with self.subTest(starts=bad):
                with self.assertRaises(DocumentValidationError):
                    validate_event(event(occ(starts=bad)))

    def test_a_join_url_must_navigate(self):
        """A tenant types this and the page puts it in an href."""
        for bad in ("javascript:alert(1)", "/relative", "mailto:a@b.c", "ftp://x"):
            with self.subTest(url=bad):
                with self.assertRaises(DocumentValidationError):
                    validate_event(event(occ(), join_url=bad))

    def test_a_real_join_url_is_accepted(self):
        validate_event(event(occ(), join_url="https://zoom.us/j/123"))

    def test_an_absent_join_url_is_fine(self):
        """It is scheduled with the provider later; refusing the save would push it into a note."""
        validate_event(event(occ()))

    def test_an_unknown_provider_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_event(event(occ(), provider="carrier_pigeon"))

    def test_a_negative_capacity_is_refused(self):
        """A typo there would close registration permanently."""
        with self.assertRaises(DocumentValidationError):
            validate_event(event(occ(capacity=-5)))

    def test_the_occurrence_list_is_capped(self):
        with self.assertRaises(DocumentValidationError):
            validate_event(event(*[occ(f"o{i}", SOON + i) for i in range(30)]))


if __name__ == "__main__":
    unittest.main()


class TheSessionHasALiveWindow(unittest.TestCase):
    """A webinar is a free event whose point is that people WATCH it, so the page's job changes at the
    start time: collect a lead before, push them at the join URL during, say they missed it after.

    `session_state` is deliberately separate from `registration_state`. They disagree during the live
    window, which is the whole reason both exist -- a session that has started is no longer registerable in
    the ordinary sense, but that is exactly when someone needs the link put in front of them.
    """

    EVENT = {"duration_minutes": 90}

    def state(self, offset):
        return events.session_state(self.EVENT, occ(starts=NOW + offset), now=NOW)

    def test_before_it_starts(self):
        self.assertEqual(self.state(3600), events.UPCOMING)

    def test_the_moment_it_starts(self):
        """The old model called this "passed" -- the page said "you missed it" as the host said hello."""
        self.assertEqual(self.state(0), events.LIVE)

    def test_while_it_runs(self):
        self.assertEqual(self.state(-45 * 60), events.LIVE)

    def test_the_moment_it_ends(self):
        self.assertEqual(self.state(-90 * 60), events.ENDED)

    def test_after_it_ends(self):
        self.assertEqual(self.state(-180 * 60), events.ENDED)

    def test_cancelled_still_beats_everything(self):
        gone = occ(starts=NOW - 60, status="cancelled")
        self.assertEqual(events.session_state(self.EVENT, gone, now=NOW), events.CANCELLED)

    def test_an_event_with_no_duration_assumes_a_sensible_one(self):
        """Better than declaring a webinar over while the host is still talking."""
        self.assertEqual(events.duration_minutes({}), events.DEFAULT_DURATION_MINUTES)
        self.assertEqual(events.session_state({}, occ(starts=NOW - 60), now=NOW), events.LIVE)

    def test_a_stored_duration_wins(self):
        self.assertEqual(events.duration_minutes({"duration_minutes": 30}), 30)
        self.assertEqual(events.session_state({"duration_minutes": 30}, occ(starts=NOW - 31 * 60), now=NOW),
                         events.ENDED)

    def test_the_live_sitting_is_findable(self):
        e = event(occ("later", SOON), occ("now", NOW - 60), occ("done", NOW - 86_400))
        self.assertEqual(events.live_occurrence(e, now=NOW)["occurrence_id"], "now")

    def test_nothing_live_is_none(self):
        self.assertIsNone(events.live_occurrence(event(occ(starts=SOON)), now=NOW))

    def test_registration_and_session_states_disagree_during_the_window(self):
        """The property both functions exist for."""
        running = occ(starts=NOW - 60)
        self.assertEqual(events.registration_state(running, now=NOW), events.PASSED)
        self.assertEqual(events.session_state(self.EVENT, running, now=NOW), events.LIVE)
