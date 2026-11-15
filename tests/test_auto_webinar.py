"""Auto-webinar: a recording that starts on a schedule (plans/AUTO_WEBINAR.md P1).

The pure half. `elapsed_seconds` is the whole feature in one function -- where in the recording a visitor
lands -- and the thing it must never do is run past the end of the session, because the player would then
be asked to seek beyond the file.

`delivery` carries one decision worth testing explicitly: absent means AUTO, so every event saved before
the field existed becomes an auto-webinar. That is safe only because an auto event with no recording falls
back to the same honest block a live event with no join link already shows.
"""
import pathlib
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



class ThePlayerReplacesTheJoinLinkTests(unittest.TestCase):
    """P2: when an auto event is live, the page plays rather than sending the visitor away."""

    def setUp(self):
        from stripe_link.runtime.html import render_event_live

        self.render = render_event_live
        self.auto = {**EVENT, "delivery": "auto", "video_url": "https://cdn.example/talk.mp4"}
        self.live = {**EVENT, "delivery": "live", "join_url": "https://zoom.example/j/1"}

    def test_an_auto_session_renders_a_player(self):
        markup = self.render(self.auto, SITTING, None)
        self.assertIn("data-event-player", markup)
        self.assertIn("https://cdn.example/talk.mp4", markup)

    def test_the_player_carries_the_window_not_a_baked_position(self):
        # The position is the VIEWER's clock minus the start. Baking a number would freeze playback at
        # whatever the publish time happened to be -- the bug this whole plan exists around.
        markup = self.render(self.auto, SITTING, None)
        self.assertIn(f'data-starts-at="{START}"', markup)
        self.assertIn(f'data-ends-at="{START + 90 * 60}"', markup)
        self.assertNotIn("currentTime", markup)

    def test_an_auto_session_does_not_also_send_them_away(self):
        both = {**self.auto, "join_url": "https://zoom.example/j/1"}
        markup = self.render(both, SITTING, None)
        self.assertIn("data-event-player", markup)
        self.assertNotIn("zoom.example", markup)

    def test_a_live_session_still_gets_its_join_link(self):
        markup = self.render(self.live, SITTING, None)
        self.assertIn("zoom.example", markup)
        self.assertNotIn("data-event-player", markup)

    def test_an_auto_session_with_no_recording_says_so_rather_than_playing_nothing(self):
        # Same contract a live event with no join_url already follows: never render a dead control.
        markup = self.render({**EVENT, "delivery": "auto"}, SITTING, None)
        self.assertNotIn("data-event-player", markup)
        self.assertIn("not posted the link yet", markup)


class TheViewersClockChoosesTests(unittest.TestCase):
    """AUTO_WEBINAR.md §1: the page used to freeze whichever state the publisher was standing in."""

    def _cta(self, starts):
        from stripe_link.runtime import html

        return html._wrap_event_states("FORM", {
            "sessions": [{"start": starts, "end": starts + 5400}],
            "live": "LIVE-BLOCK", "ended": "ENDED-BLOCK",
        })

    def test_all_three_blocks_are_in_the_markup(self):
        markup = self._cta(START)
        for block in ("upcoming", "live", "ended"):
            self.assertIn(f'data-event-block="{block}"', markup)
        self.assertIn("FORM", markup)
        self.assertIn("LIVE-BLOCK", markup)
        self.assertIn("ENDED-BLOCK", markup)

    def test_the_windows_ride_the_markup_for_the_island_to_choose_by(self):
        markup = self._cta(START)
        self.assertIn("data-event-sessions=", markup)
        self.assertIn(str(START), markup)
        self.assertIn(str(START + 5400), markup)

    def test_the_form_is_the_default_so_a_no_js_visitor_still_gets_one(self):
        # The server refuses a registration for a session that has started or filled, so the worst a
        # no-JS visitor meets is a refusal -- never a silent failure.
        markup = self._cta(START)
        upcoming = markup.index('data-event-block="upcoming"')
        self.assertNotIn("hidden", markup[upcoming:markup.index("FORM")])

    def test_a_page_with_no_event_is_untouched(self):
        from stripe_link.runtime import html

        self.assertEqual(html._wrap_event_states("FORM", {}), "FORM")

class TheTenantCanSetOneUpTests(unittest.TestCase):
    """P3. Asserted against the Vue source, the way the webinar tests already check the builder: these are
    the places a field is silently dropped if somebody adds the mode and forgets the form."""

    def setUp(self):
        import pathlib as _p

        self.screen = (_p.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"
                       / "Events.vue").read_text(encoding="utf-8")

    def test_automated_is_offered_before_live(self):
        # Author, 2026-11-15: auto is the first kind of webinar a tenant creates.
        self.assertLess(self.screen.index('value="auto"'), self.screen.index('value="live"'))

    def test_a_new_event_starts_on_automated(self):
        self.assertIn('delivery: "auto"', self.screen)

    def test_an_event_saved_before_the_field_opens_on_automated_too(self):
        # startEdit spreads the stored item over a default, so the select is never empty.
        self.assertIn('delivery: "auto", video_url: ""', self.screen)

    def test_both_fields_reach_the_saved_document(self):
        self.assertIn("delivery: editing.value.delivery === \"live\"", self.screen)
        self.assertIn("video_url: editing.value.delivery === \"live\"", self.screen)

    def test_the_other_modes_fields_are_dropped_rather_than_carried(self):
        # An auto event holding a stale join_url would name a room nobody is in, and the renderer prefers
        # the recording -- so it would sit in the document being wrong and never being seen.
        self.assertIn("join_url: editing.value.delivery === \"live\"", self.screen)

    def test_the_picker_offers_only_what_the_uploader_accepts(self):
        self.assertIn('accept="video/mp4,video/webm"', self.screen)
        self.assertNotIn("video/quicktime", self.screen)

    def test_the_size_ceiling_is_not_copied_into_this_repo(self):
        # It is a parameter on the image-processing stack (docs/EXTERNAL_SERVICES.md). A number here would
        # go stale the moment that stack raises it.
        self.assertNotIn("maxBytes", self.screen)

class TheLateJoinCutOffTests(unittest.TestCase):
    """Arriving two minutes before the close means seeing the ask without the argument."""

    def setUp(self):
        from stripe_link.domain.events import accepts_late_join, joinable_until

        self.accepts = accepts_late_join
        self.until = joinable_until

    def test_without_a_cut_off_the_whole_session_is_joinable(self):
        # What every event written before this field meant, and what a live webinar still wants.
        self.assertEqual(self.until(EVENT, SITTING), START + 90 * 60)
        self.assertTrue(self.accepts(EVENT, SITTING, now=START + 89 * 60))

    def test_a_cut_off_closes_the_door_while_the_session_runs_on(self):
        capped = {**EVENT, "late_join_minutes": 20}
        self.assertEqual(self.until(capped, SITTING), START + 20 * 60)
        self.assertTrue(self.accepts(capped, SITTING, now=START + 19 * 60))
        self.assertFalse(self.accepts(capped, SITTING, now=START + 21 * 60))
        # ...and the session is still LIVE at that moment. The two answers differ on purpose.
        self.assertEqual(session_state(capped, SITTING, now=START + 21 * 60), "live")

    def test_a_cut_off_longer_than_the_session_cannot_outlast_it(self):
        self.assertEqual(self.until({**EVENT, "late_join_minutes": 500}, SITTING), START + 90 * 60)

    def test_zero_and_nonsense_both_mean_no_limit(self):
        for value in (0, None, "", "soon", -5):
            with self.subTest(value=value):
                self.assertEqual(self.until({**EVENT, "late_join_minutes": value}, SITTING),
                                 START + 90 * 60)

    def test_the_page_carries_it_so_the_island_can_apply_it(self):
        from stripe_link.runtime import html

        source = (pathlib.Path(html.__file__)).read_text(encoding="utf-8")
        self.assertIn('"join_until": event_joinable_until', source)
        # Falls back to the end, so a page published before this field behaves exactly as it did.
        self.assertIn("(s.join_until || s.end)", source)


if __name__ == "__main__":
    unittest.main()
