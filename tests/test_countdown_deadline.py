"""The countdown can count to a DATE, not just down from a number of minutes.

The author wanted days/hours/minutes/seconds — "a countdown that starts on Black Friday and ends on Cyber
Monday" — and said they could not see a clean way to do it.

The clean way was already half-built: `page.sale.ends_at` is an absolute epoch the sale machinery already
honours, set by the builder's "Expiration (optional — leave blank for a perpetual sale)". So a deadline
countdown with no date of its own DERIVES from it, which is what stops a banner reading "2 days left" over
pricing that expired on Monday.

The two modes are genuinely different and must not be mixed:
  duration — this visitor's own stopwatch, persisted in their browser, started when they arrived
  deadline — one moment, the same for every visitor, with nothing to persist and nothing to restart
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import countdown_deadline, render_countdown_timer

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
FIXTURE = ROOT / "schemas" / "examples" / "page-creatine-standard.json"
FUTURE = 1800000000


def page(section=None, **extra):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["sections"] = [{"type": "countdown_timer", "id": "countdown", **(section or {})}]
    doc.update(extra)
    return doc


class TheDeadlineIsDerivedWhenNotGiven(unittest.TestCase):
    def test_its_own_date_wins(self):
        self.assertEqual(countdown_deadline({"ends_at": FUTURE}, {"sale": {"ends_at": 1}}), FUTURE)

    def test_it_falls_back_to_the_sales_expiry(self):
        self.assertEqual(countdown_deadline({}, {"sale": {"ends_at": FUTURE}}), FUTURE)

    def test_no_date_anywhere_is_zero(self):
        for pg in ({}, {"sale": {}}, {"sale": {"ends_at": 0}}, {"sale": None}):
            with self.subTest(page=pg):
                self.assertEqual(countdown_deadline({}, pg), 0)

    def test_rubbish_does_not_raise(self):
        """A stored string or null must not 500 the renderer for every visitor."""
        for bad in ("soon", None, [], {}):
            with self.subTest(value=bad):
                self.assertEqual(countdown_deadline({"ends_at": bad}, {}), 0)
        self.assertEqual(countdown_deadline({}, {"sale": {"ends_at": "soon"}}), 0)


class ADeadlineWithNoDateRendersNothing(unittest.TestCase):
    """"Offer expires in" over an empty space reads as a broken page, not an unconfigured one."""

    def test_nothing_without_a_date(self):
        self.assertEqual(render_countdown_timer({"mode": "deadline"}, {}), "")

    def test_something_once_the_sale_has_one(self):
        self.assertIn("sl-countdown", render_countdown_timer({"mode": "deadline"}, {"sale": {"ends_at": FUTURE}}))


class TheModesStaySeparate(unittest.TestCase):
    def test_duration_is_the_default(self):
        self.assertIn('data-mode="duration"', render_countdown_timer({"duration_minutes": 15}, {}))

    def test_an_unknown_mode_falls_back_rather_than_breaking(self):
        self.assertIn('data-mode="duration"', render_countdown_timer({"mode": "sideways", "duration_minutes": 5}, {}))

    def test_the_deadline_is_published_for_the_island(self):
        html = render_countdown_timer({"mode": "deadline", "ends_at": FUTURE}, {})
        self.assertIn(f'data-ends-at="{FUTURE}"', html)

    def test_a_deadline_is_never_persisted(self):
        """localStorage holds THIS visitor's stopwatch. A stored duration must not override the tenant's
        date, and an absolute moment has nothing to restore."""
        self.assertIn("const persistent = !deadlineMode && section.dataset.persistent === 'true';", HTML)

    def test_a_deadline_is_never_re_armed_by_the_funnel(self):
        """The downsell restart sets `deadline = now + duration`. In deadline mode duration is 0, so it
        would expire instantly and fire the decline path again on a page that had simply reached its date."""
        restart = HTML[HTML.index("funnelCountdownRestarts.push"):][:600]
        self.assertIn("if (deadlineMode) return;", restart)


class TheDigitGrid(unittest.TestCase):
    def test_line_is_the_default(self):
        html = render_countdown_timer({"duration_minutes": 15}, {})
        self.assertIn('data-display="line"', html)
        self.assertNotIn("sl-countdown-digits", html)

    def test_the_boxes_render_server_side(self):
        """A page with no JS shows the boxes and their names, not an empty banner."""
        html = render_countdown_timer({"mode": "deadline", "ends_at": FUTURE, "display": "digits"}, {})
        for unit in ("days", "hours", "minutes", "seconds"):
            with self.subTest(unit=unit):
                self.assertIn(f"data-countdown-{unit}", html)
        self.assertIn("Days", html)
        self.assertIn("Seconds", html)

    def test_the_island_fills_every_unit(self):
        for unit in ("days", "hours", "minutes", "seconds"):
            with self.subTest(unit=unit):
                self.assertIn(f"set('{unit}'", HTML)

    def test_days_only_appear_once_there_are_days(self):
        """"0d 00:04:12" on the last afternoon of a sale reads as broken."""
        self.assertIn("display.textContent = d ? `${d}d ${body}` : body;", HTML)

    def test_the_digits_do_not_jitter(self):
        self.assertIn("font-variant-numeric:tabular-nums", HTML)


class ExpiryStillWithdrawsThePricing(unittest.TestCase):
    """A banner counting to the sale's end that keeps selling at the sale price afterwards is the bug."""

    def test_the_expired_branch_is_shared_by_both_modes(self):
        island = HTML[HTML.index("const pad = (n) => String(n).padStart(2, '0');"):][:2600]
        self.assertIn("expireDiscounts();", island)
        self.assertNotIn("if (deadlineMode) return;", island.split("remaining <= 0")[1][:400])


class TheDocumentValidatesIt(unittest.TestCase):
    def test_both_modes_save(self):
        for mode in ("duration", "deadline"):
            with self.subTest(mode=mode):
                validate_page_document(page({"mode": mode, "ends_at": FUTURE}))

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"mode": "sideways"}))

    def test_an_unknown_display_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"display": "hologram"}))

    def test_ends_at_must_be_a_number(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"mode": "deadline", "ends_at": "friday"}))

    def test_ends_at_stays_optional_so_it_can_derive(self):
        validate_page_document(page({"mode": "deadline"}))


class TheBuilderOffersIt(unittest.TestCase):
    def test_the_mode_and_display_round_trip(self):
        for fragment in ("builder.countdown.mode", "builder.countdown.display",
                         "countdownEndsAtLocal", 'mode: countdown.mode === "deadline"'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, BUILDER)

    def test_an_unset_date_is_omitted_rather_than_sent_as_zero(self):
        """0 is a date in 1970; omitting it is what lets the renderer derive from the sale."""
        self.assertIn('builder.countdown.mode === "deadline" && builder.countdown.ends_at', BUILDER)

    def test_it_says_which_date_it_will_use(self):
        self.assertIn("Counting to the sale's expiry", BUILDER)

    def test_it_warns_when_there_is_no_date_at_all(self):
        """Without one the banner renders nothing, and silence would look like a bug."""
        self.assertIn("with neither, the banner cannot render", BUILDER)


if __name__ == "__main__":
    unittest.main()
