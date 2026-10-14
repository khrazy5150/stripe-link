"""The Date element: a target date, spelled out in plain English.

The author: "allows customers to see the actual Date in plain English on the landing page: 'Saturday,
October 31, 2026' ... If no target date is set, then there is nothing to show."

Rendered at PUBLISH rather than by a script, because the answer never changes: a fixed moment in a fixed
zone is the same sentence forever.

The zone belongs to the EVENT, not the store. The references label the host's zone ("7PM EST", "9:30 AM
AEST") rather than converting to the reader's — that label is part of what is being announced. It is also
the only reachable answer: `business.timezone` lives on the USER profile and the renderer is handed the
TENANT profile.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.domain.store_timezone import load_zone
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, format_event_date, render_event_date

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
FIXTURE = ROOT / "schemas" / "examples" / "page-creatine-standard.json"
# 2026-10-31 20:00 America/New_York
HALLOWEEN = 1793491200


def page(section):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["sections"] = [{"type": "event_date", "id": "d", **section}]
    return doc


class ItReadsAsEnglish(unittest.TestCase):
    def test_the_authors_own_example(self):
        self.assertEqual(format_event_date(HALLOWEEN, "America/New_York", with_time=False),
                         "Saturday, October 31, 2026")

    def test_the_time_and_zone_are_appended(self):
        said = format_event_date(HALLOWEEN, "America/New_York", with_time=True)
        self.assertTrue(said.startswith("Saturday, October 31, 2026 at "))
        self.assertIn("8:00 PM", said)

    def test_the_zone_is_resolved_not_assumed(self):
        """Late October is DAYLIGHT time in New York. A fixed offset would have printed EST and been an
        hour out; zoneinfo knows which side of the change the date falls on."""
        self.assertIn("EDT", format_event_date(HALLOWEEN, "America/New_York", with_time=True))

    def test_the_same_moment_reads_differently_elsewhere(self):
        sydney = format_event_date(HALLOWEEN, "Australia/Sydney", with_time=True)
        self.assertIn("Sunday, November 1, 2026", sydney)

    def test_midnight_and_noon_do_not_print_as_zero(self):
        """`hour % 12` is 0 at both, and "0:00 AM" is not a time anyone writes."""
        for offset, expected in ((0, "12:00 AM"), (12 * 3600, "12:00 PM")):
            with self.subTest(expected=expected):
                midnight = 1793491200 - (20 * 3600) + offset   # that day's 00:00 / 12:00 in NY
                self.assertIn(expected, format_event_date(midnight, "America/New_York", with_time=True))

    def test_an_unknown_zone_degrades_to_utc_rather_than_raising(self):
        self.assertIn("2026", format_event_date(HALLOWEEN, "Mars/Olympus", with_time=True))

    def test_a_single_digit_day_is_not_zero_padded(self):
        """Built by hand because %-d is a glibc extension. In Sydney this moment is the 1st, and the day
        must read "November 1", never "November 01"."""
        said = format_event_date(HALLOWEEN, "Australia/Sydney", with_time=False)
        self.assertIn("November 1, 2026", said)
        self.assertNotIn("November 01", said)


class NoDateMeansNoElement(unittest.TestCase):
    def test_nothing_renders_without_one(self):
        for value in (None, 0, "", "soon", -5):
            with self.subTest(value=value):
                self.assertEqual(render_event_date({"date": value, "label": "x"}), "")

    def test_the_builder_refuses_to_store_an_empty_one(self):
        self.assertIn("if (!element.date) return null;", BUILDER)

    def test_the_builder_says_so_rather_than_leaving_it_silent(self):
        self.assertIn("Without a date this element shows nothing", BUILDER)


class TheMarkupIsBothReadableAndParseable(unittest.TestCase):
    def test_it_emits_a_machine_readable_time(self):
        html = render_event_date({"date": HALLOWEEN, "timezone": "America/New_York"})
        self.assertIn('<time class="sl-event-date-value" datetime="2026-10-31T20:00:00-04:00"', html)

    def test_the_icon_is_decorative(self):
        html = render_event_date({"date": HALLOWEEN, "icon": "📅"})
        self.assertIn('class="sl-event-date-icon" aria-hidden="true"', html)

    def test_optional_parts_leave_no_empty_tags(self):
        html = render_event_date({"date": HALLOWEEN})
        self.assertNotIn("sl-event-date-icon", html)
        self.assertNotIn("sl-event-date-label", html)

    def test_the_label_is_escaped(self):
        self.assertIn("&lt;script&gt;", render_event_date({"date": HALLOWEEN, "label": "<script>"}))


class TheTwoStyles(unittest.TestCase):
    def test_band_is_the_default(self):
        self.assertIn("is-band", render_event_date({"date": HALLOWEEN}))

    def test_card_is_selectable(self):
        self.assertIn("is-card", render_event_date({"date": HALLOWEEN, "presentation": "card"}))

    def test_an_unknown_style_falls_back(self):
        self.assertIn("is-band", render_event_date({"date": HALLOWEEN, "presentation": "neon"}))

    def test_the_band_uses_the_tenants_own_highlight_colours(self):
        """The amber strip in the reference, without hardcoding a colour the theme cannot reach."""
        rule = next(r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                    if isinstance(r, str) and ".sl-event-date.is-band{" in r)
        self.assertIn("var(--sl-highlight-bg)", rule)
        self.assertIn("var(--sl-highlight-bg-text)", rule)


class TheZoneLoaderIsShared(unittest.TestCase):
    def test_it_falls_back_to_utc(self):
        self.assertEqual(str(load_zone("Nowhere/Real")), "UTC")
        self.assertEqual(str(load_zone("")), "UTC")

    def test_a_real_zone_loads(self):
        self.assertEqual(str(load_zone("Australia/Sydney")), "Australia/Sydney")


class ItIsRegisteredAndValidated(unittest.TestCase):
    def test_catalog_entry(self):
        spec = RULES["elements"]["event_date"]
        self.assertEqual(spec["ui"], "add")
        # The references print the same date twice on one page: a band at the top, a card by the sign-up.
        self.assertTrue(spec["repeatable"])

    def test_a_minimal_section_validates(self):
        validate_page_document(page({"date": HALLOWEEN}))

    def test_it_validates_with_no_date_at_all(self):
        """A tenant may add the element before they know the date; the renderer simply shows nothing."""
        validate_page_document(page({}))

    def test_an_unknown_style_is_refused_on_save(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"date": HALLOWEEN, "presentation": "neon"}))

    def test_the_timezone_is_not_checked_against_a_list(self):
        """Same rule as business.timezone: the renderer degrades loudly, and refusing a save over a tz
        database somewhere would lock a tenant out of their own page."""
        validate_page_document(page({"date": HALLOWEEN, "timezone": "Some/Zone"}))

    def test_the_builder_round_trips_every_field(self):
        for fragment in ('type === "event_date"', 'element.type === "event_date"',
                         'section.type === "event_date"', "element.timezone",
                         "element.show_time", "element.presentation", "timeZoneOptions"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, BUILDER)

    def test_the_builder_prefills_the_store_zone(self):
        self.assertIn("profileStore.business?.timezone", BUILDER)


if __name__ == "__main__":
    unittest.main()
