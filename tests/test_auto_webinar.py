"""Auto-webinar: a recording that starts on a schedule (plans/AUTO_WEBINAR.md P1).

The pure half. `elapsed_seconds` is the whole feature in one function -- where in the recording a visitor
lands -- and the thing it must never do is run past the end of the session, because the player would then
be asked to seek beyond the file.

`delivery` carries one decision worth testing explicitly: absent means AUTO, so every event saved before
the field existed becomes an auto-webinar. That is safe only because an auto event with no recording falls
back to the same honest block a live event with no join link already shows.
"""
import unittest

from stripe_link.domain.events import (
    DELIVERY_AUTO,
    DELIVERY_LIVE,
    delivery,
    elapsed_seconds,
    session_state,
)

HOUR = 3600
START = 1_800_000_000
EVENT = {"event_id": "evt_1", "duration_minutes": 90}
SITTING = {"occurrence_id": "occ_1", "starts_at": START}


class WhereInTheRecordingTests(unittest.TestCase):
    def test_before_the_start_there_is_nothing_to_play(self):
        self.assertEqual(elapsed_seconds(EVENT, SITTING, now=START - 60), 0)

    def test_at_the_start_it_begins_at_the_beginning(self):
        self.assertEqual(elapsed_seconds(EVENT, SITTING, now=START), 0)

    def test_arriving_late_joins_part_way_in(self):
        # Forty minutes late joins forty minutes in, exactly as a live broadcast would.
        self.assertEqual(elapsed_seconds(EVENT, SITTING, now=START + 40 * 60), 40 * 60)

    def test_it_never_runs_past_the_end_of_the_session(self):
        # A player asked to seek beyond the file is the failure this clamp exists for.
        self.assertEqual(elapsed_seconds(EVENT, SITTING, now=START + 10 * HOUR), 90 * 60)

    def test_a_sitting_with_no_start_has_no_position(self):
        self.assertEqual(elapsed_seconds(EVENT, {"occurrence_id": "occ_x"}, now=START), 0)

    def test_the_default_duration_bounds_an_event_that_names_none(self):
        # 90 minutes is domain/events.DEFAULT_DURATION_MINUTES, and it bounds the clamp too.
        self.assertEqual(elapsed_seconds({}, SITTING, now=START + 10 * HOUR), 90 * 60)

    def test_position_agrees_with_the_live_window(self):
        # The two functions answer different questions but must not contradict each other: whenever the
        # session is LIVE there is a position inside the recording, and when it has ENDED the position is
        # pinned to the end rather than still advancing.
        self.assertEqual(session_state(EVENT, SITTING, now=START + 30 * 60), "live")
        self.assertLess(elapsed_seconds(EVENT, SITTING, now=START + 30 * 60), 90 * 60)
        self.assertEqual(session_state(EVENT, SITTING, now=START + 5 * HOUR), "ended")
        self.assertEqual(elapsed_seconds(EVENT, SITTING, now=START + 5 * HOUR), 90 * 60)


class HowItIsDeliveredTests(unittest.TestCase):
    def test_auto_is_the_default(self):
        self.assertEqual(delivery({}), DELIVERY_AUTO)
        self.assertEqual(delivery(None), DELIVERY_AUTO)

    def test_an_event_saved_before_the_field_existed_is_an_auto_webinar(self):
        # The consequence of that default, stated outright so nobody "fixes" it by accident.
        self.assertEqual(delivery({"event_id": "evt_old", "join_url": "https://zoom.example/j/1"}),
                         DELIVERY_AUTO)

    def test_live_is_honoured_when_chosen(self):
        self.assertEqual(delivery({"delivery": "live"}), DELIVERY_LIVE)
        self.assertEqual(delivery({"delivery": "LIVE"}), DELIVERY_LIVE)

    def test_an_unrecognised_value_falls_back_rather_than_raising(self):
        # A malformed row must not take the page down, the same contract `occurrences` follows.
        self.assertEqual(delivery({"delivery": "webinarjam"}), DELIVERY_AUTO)


if __name__ == "__main__":
    unittest.main()
