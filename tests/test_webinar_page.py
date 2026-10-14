"""What a registration page shows (plans/WEBINAR.md §5, §9).

The page asks the SAME `accepts_registration`/`open_occurrences` the endpoint uses, so it cannot offer a
session the server will refuse. That is a consistency property, not a security one — the server still
checks, because a published page is a cached artifact and a visitor's copy may be hours old.
"""
import re
import time
import unittest

from stripe_link.runtime import html
from stripe_link.runtime.html import render_event_closed, render_occurrence_picker

NOW = int(time.time())
SOON = NOW + 86_400
LATER = NOW + 86_400 * 3
PAST = NOW - 86_400


def occ(occurrence_id="o1", starts=SOON, **extra):
    return {"occurrence_id": occurrence_id, "starts_at": starts, "timezone": "America/New_York", **extra}


class ThePicker(unittest.TestCase):
    def test_one_session_is_a_hidden_field_not_a_question(self):
        """Asking "which session?" with one answer is a question nobody should have to read — but the
        value still has to travel, because the server needs to know which."""
        markup = render_occurrence_picker([occ()])
        self.assertIn('type="hidden"', markup)
        self.assertIn('name="occurrence_id"', markup)
        self.assertIn('value="o1"', markup)
        self.assertNotIn("<fieldset", markup)

    def test_several_sessions_become_radios(self):
        markup = render_occurrence_picker([occ("a"), occ("b", LATER)])
        self.assertEqual(len(re.findall(r'type="radio"', markup)), 2)
        self.assertIn("<legend>Choose a session</legend>", markup)

    def test_the_first_is_preselected(self):
        """A radio group with nothing chosen submits nothing, which reads as the form being broken."""
        markup = render_occurrence_picker([occ("a"), occ("b", LATER)])
        self.assertEqual(len(re.findall(r"checked", markup)), 1)
        self.assertIn('value="a" checked', markup)

    def test_each_option_carries_its_date_and_zone(self):
        """A one-line <select> truncates exactly that on a phone, which is why these are radios."""
        markup = render_occurrence_picker([occ("a"), occ("b", LATER)])
        self.assertIn("EDT", markup)
        self.assertRegex(markup, r"<span>\w+day, \w+ \d+, \d{4} at ")

    def test_seats_show_only_when_nearly_gone(self):
        """"497 seats left" is not scarcity, it is arithmetic."""
        plenty = render_occurrence_picker([occ("a", capacity=500, registered_count=3), occ("b", LATER)])
        self.assertNotIn("sl-occurrence-seats", plenty)
        nearly = render_occurrence_picker([occ("a", capacity=500, registered_count=490), occ("b", LATER)])
        self.assertIn("10 left", nearly)

    def test_an_uncapped_session_never_shows_a_count(self):
        self.assertNotIn("sl-occurrence-seats", render_occurrence_picker([occ("a"), occ("b", LATER)]))


class TheClosedState(unittest.TestCase):
    def test_the_form_is_replaced_not_disabled(self):
        """A disabled form invites people to try. There is no input to fill in at all."""
        markup = render_event_closed({}, {}, title="Live training", description="")
        self.assertNotIn("<input", markup)
        self.assertNotIn("data-lead-form", markup)
        self.assertIn('data-event-closed="true"', markup)

    def test_it_says_what_happened(self):
        markup = render_event_closed({}, {}, title="", description="")
        self.assertIn("Registration has closed", markup)
        self.assertIn("already taken place", markup)

    def test_the_tenant_can_word_it(self):
        markup = render_event_closed({}, {"closed_title": "You missed it", "closed_text": "Next one in May."},
                                     title="", description="")
        self.assertIn("You missed it", markup)
        self.assertIn("Next one in May.", markup)

    def test_the_wording_is_escaped(self):
        markup = render_event_closed({}, {"closed_title": "<script>"}, title="", description="")
        self.assertIn("&lt;script&gt;", markup)


class TheRenderScopedIndex(unittest.TestCase):
    """Events reach the lead CTA through a render-scoped index, like the image dims and the preferences —
    the CTA is six frames down and threading a signature through every one is what these exist to avoid."""

    def test_it_exists_and_starts_empty(self):
        self.assertEqual(html._RENDER_EVENTS, {})

    def test_it_is_cleared_after_a_render(self):
        """One tenant's sessions must never leak into another's page on a warm container. The clear is in
        the SAME finally as the other indexes, so a raising render cannot strand them."""
        source = html.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        finally_block = text[text.index("    finally:\n        _RENDER_DIMS_INDEX.clear()"):][:600]
        self.assertIn("_RENDER_EVENTS.clear()", finally_block)


class ThePublisherLoadsThemSafely(unittest.TestCase):
    def test_a_missing_event_does_not_jam_the_publish_stream(self):
        """A product pointing at a deleted session renders without a picker rather than failing."""
        from stripe_link.runtime.publishing import _load_events_for_products

        class Missing:
            def get(self, *_a, **_k):
                return None

        products = {"p1": {"lead_capture": {"event_id": "gone"}}}
        self.assertEqual(_load_events_for_products("t1", products, Missing()), {})

    def test_a_failing_read_does_not_either(self):
        from stripe_link.runtime.publishing import _load_events_for_products

        class Broken:
            def get(self, *_a, **_k):
                raise RuntimeError("table on fire")

        products = {"p1": {"lead_capture": {"event_id": "ev_1"}}}
        self.assertEqual(_load_events_for_products("t1", products, Broken()), {})

    def test_no_repository_means_no_events_rather_than_a_crash(self):
        from stripe_link.runtime.publishing import _load_events_for_products
        self.assertEqual(_load_events_for_products("t1", {"p": {"lead_capture": {"event_id": "e"}}}, None), {})

    def test_it_loads_what_the_products_point_at(self):
        from stripe_link.runtime.publishing import _load_events_for_products

        class One:
            def get(self, tenant_id, event_id):
                return {"event_id": event_id, "tenant_id": tenant_id, "title": "Live"}

        products = {"p1": {"lead_capture": {"event_id": "ev_1"}},
                    "p2": {"lead_capture": {"event_id": "ev_1"}},   # same event twice
                    "p3": {"name": "an ordinary product"}}
        found = _load_events_for_products("t1", products, One())
        self.assertEqual(list(found), ["ev_1"])


if __name__ == "__main__":
    unittest.main()


class TheLiveState(unittest.TestCase):
    """"The landing page's job is to collect these leads and push them to the URL at the appropriate time."
    During the session that job is the link, and nothing else."""

    def test_the_join_link_replaces_the_form(self):
        """A visitor arriving mid-session does not want to fill anything in, they want the room."""
        markup = html.render_event_live({"join_url": "https://zoom.us/j/1"}, {}, {}, title="")
        self.assertIn("https://zoom.us/j/1", markup)
        self.assertNotIn("<input", markup)
        self.assertIn('data-event-live="true"', markup)

    def test_it_opens_in_a_new_tab_without_leaking_the_opener(self):
        markup = html.render_event_live({"join_url": "https://zoom.us/j/1"}, {}, {}, title="")
        self.assertIn('target="_blank"', markup)
        self.assertIn('rel="noopener"', markup)

    def test_a_dangerous_join_url_is_refused(self):
        """A tenant types this and the page puts it in an href."""
        markup = html.render_event_live({"join_url": "javascript:alert(1)"}, {}, {}, title="")
        self.assertNotIn("javascript:", markup)
        self.assertIn("not posted the link yet", markup)

    def test_no_link_says_so_rather_than_rendering_a_dead_button(self):
        markup = html.render_event_live({}, {}, {}, title="")
        self.assertNotIn("sl-event-join", markup)
        self.assertIn("not posted the link yet", markup)

    def test_the_tenant_can_word_it(self):
        markup = html.render_event_live({"join_url": "https://zoom.us/j/1"}, {},
                                        {"live_title": "Doors are open", "live_label": "Enter the room"},
                                        title="")
        self.assertIn("Doors are open", markup)
        self.assertIn("Enter the room", markup)

    def test_the_live_check_comes_before_the_registration_check(self):
        """A form shown while the host is already talking is the page failing at the only moment that
        matters."""
        source = open(html.__file__, encoding="utf-8").read()
        cta = source[source.index("    if scheduled_event is not None:"):][:1400]
        self.assertLess(cta.index("event_live_occurrence"), cta.index("event_open_occurrences"))
