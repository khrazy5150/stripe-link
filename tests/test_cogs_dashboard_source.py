"""The dashboard side of COGS: a cost can be entered, and an unsupportable profit is not shown.

There is no JS test runner in this repo, so these are static guards in the same shape as
`test_dashboard_revenue_source.py`. A real unit test would be better; a static guard is better than
nothing and costs no toolchain.

The thing being defended is one rule in two places: **blank is not zero.** The form holds dollars as a
STRING so `""` and `"0"` stay different, and the payload omits the key entirely rather than sending 0 —
because the ledger reads an absent cost as "unknown" and a zero as "genuinely free", and sending the
wrong one hands the tenant an inflated margin with full confidence.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
STORE = ROOT / "stores" / "products.js"
FIELD = ROOT / "components" / "products" / "ProductUnitCostField.vue"
FORM = ROOT / "components" / "Products.vue"
REPORTS = ROOT / "components" / "Reports.vue"


class TheTenantCanRecordACost(unittest.TestCase):
    def test_the_field_exists_and_is_reachable_from_both_forms(self):
        """The wizard and the edit form, or tenants who created a product earlier can never cost it."""
        self.assertTrue(FIELD.exists())
        self.assertEqual(FORM.read_text().count("<ProductUnitCostField"), 2,
                         "the create wizard AND the edit form")

    def test_it_asks_in_the_tenants_words_not_the_ledgers(self):
        text = FIELD.read_text()
        self.assertIn("What this costs you", text)
        self.assertNotIn("COGS", text.replace("cogs", ""), "'cost of goods sold' is our jargon")

    def test_it_says_the_cost_is_private(self):
        """A seller asked to type their margin into a web form deserves to be told who sees it."""
        self.assertIn("never shown to customers", FIELD.read_text())


class BlankIsNotZero(unittest.TestCase):
    def test_the_converter_returns_undefined_for_blank(self):
        body = _function(STORE.read_text(), "unitCostCents")
        self.assertIn("return undefined", body)
        self.assertIn('=== ""', body, "blank is tested for explicitly")

    def test_the_payload_omits_the_key_rather_than_sending_zero(self):
        text = STORE.read_text()
        self.assertIn("unitCostCents(form.unit_cost) === undefined ? {} : { unit_cost:", text,
                      "an unanswered cost must not reach the document at all")

    def test_the_shared_cents_helper_is_not_used_for_this(self):
        """`cents()` in stores/pricing.js coerces "" to 0, which is exactly the bug here."""
        body = _function(STORE.read_text(), "unitCostCents")
        self.assertNotIn("cents(", body.replace("unitCostCents(", ""))

    def test_loading_a_product_with_no_cost_shows_blank(self):
        body = _function(STORE.read_text(), "unitCostToInput")
        self.assertIn('return ""', body)
        self.assertIn("undefined", body, "absent must not render as 0.00")

    def test_the_form_defaults_to_blank(self):
        self.assertIn('unit_cost: "",', FORM.read_text(),
                      "a new product starts uncosted, not free")

    def test_the_tenant_is_told_how_to_say_genuinely_free(self):
        """Otherwise 'why is Profit blank' is a support question with no discoverable answer."""
        # Whitespace-collapsed: the copy is line-wrapped in the template, and a guard that breaks when a
        # sentence is re-flowed tests the indentation rather than the message.
        self.assertIn("costs you nothing", _words(FIELD.read_text()))


class ProfitIsWithheldNotGuessed(unittest.TestCase):
    def test_the_profit_row_declares_when_it_is_knowable(self):
        text = REPORTS.read_text()
        self.assertIn("profit_known", text)

    def test_a_partial_answer_is_shown_WITH_its_scope(self):
        """All-or-nothing cost a month of silence: start recording costs today and the figure still hid
        behind every older uncosted sale in the window, because an entry already written can never gain
        a cost. The scoped figure replaced that -- and it may never appear without the scope beside it,
        or it reads as covering the whole period (2026-10-12)."""
        text = REPORTS.read_text()
        self.assertIn("costed_profit", text)
        self.assertIn("costed_sales", text)
        self.assertIn("sale_count", text, "the scope is a fraction, so it needs both halves")

    def test_the_scope_replaces_the_period_comparison(self):
        """Comparing a partial figure against a period whose coverage was different is a number nobody
        can act on."""
        text = REPORTS.read_text()
        self.assertIn('card.scope ? "" :', text.replace("\n", " ").replace("  ", " ")
                      ) if "card.scope ?" in text else self.assertIn("v-else-if=\"card.known && previous\"", text)

    def test_an_unknown_value_renders_a_dash_not_a_number(self):
        text = REPORTS.read_text()
        self.assertIn("row.known", text)
        self.assertIn("reports-unknown", text)

    def test_the_delta_is_also_withheld(self):
        """A change between two figures is meaningless if either is unknown, and showing one would imply
        both were measured."""
        self.assertIn("deltaKnown", REPORTS.read_text())

    def test_the_note_tells_the_tenant_what_to_do(self):
        self.assertIn("no cost recorded", REPORTS.read_text())

    def test_other_rows_are_unaffected(self):
        """`known` is absent on every other line and must read as knowable, or the whole report blanks."""
        self.assertIn("line.known ? line.known(now) : true", REPORTS.read_text())


def _words(text):
    """The text with runs of whitespace collapsed, so an assertion survives re-wrapping."""
    return " ".join(text.split())


def _function(text, name):
    """The body of a JS function, so an assertion cannot be satisfied by a comment elsewhere."""
    start = text.index(f"function {name}(")
    depth, opened = 0, text.index("{", start)
    for index in range(opened, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opened:index + 1]
    raise AssertionError(f"could not find the body of {name}")


class TheGuardCanFail(unittest.TestCase):
    def test_extracting_a_function_body_really_works(self):
        body = _function(STORE.read_text(), "unitCostCents")
        self.assertTrue(body.startswith("{") and body.endswith("}"), body[:60])
        self.assertLess(len(body), 500, "this should be the function, not half the file")


if __name__ == "__main__":
    unittest.main()


class ReportsSitsOnTheSamePageWrapperAsEveryOtherScreen(unittest.TestCase):
    """Reports had no left or right padding, and its Change column ran off the right of the screen.

    The cause was not a missing rule but a missing CLASS: it was the only component of 23 using
    `class="screen"`, which is defined nowhere in styles.css. Every other screen uses `.page`, which
    carries the 3.2rem page padding and the 2.4rem grid gap. So Reports inherited neither — it was not
    styled differently, it was unstyled.
    """

    import pathlib as _pathlib
    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    VIEW = (ROOT / "dashboard/src/components/Reports.vue").read_text(encoding="utf-8")
    CSS = (ROOT / "dashboard/src/styles.css").read_text(encoding="utf-8")

    def test_it_uses_the_wrapper_the_other_screens_use(self):
        self.assertIn('<section class="page">', self.VIEW)
        self.assertIn('<header class="page-header">', self.VIEW)

    def test_it_uses_no_undefined_wrapper_class(self):
        for ghost in ('class="screen"', 'class="screen-header"', 'class="screen-subtitle"',
                      'class="page-subtitle"'):
            self.assertNotIn(ghost, self.VIEW, f"{ghost} is defined nowhere in styles.css")

    def test_every_wrapper_class_it_uses_actually_exists(self):
        """The general form of the bug: a class that does not exist styles nothing and says nothing."""
        import re
        for name in ("page", "page-header", "reports-panel", "reports-headline", "period-chip"):
            self.assertTrue(re.search(rf"\.{re.escape(name)}[\s,{{:]", self.CSS),
                            f".{name} is used in the template but defined nowhere")

    def test_the_statement_has_a_surface_to_sit_on(self):
        """Edge-to-edge rows had nothing holding them, and the last column had nowhere to go."""
        self.assertIn('<div v-if="summary" class="reports-panel">', self.VIEW)
        panel = self.CSS[self.CSS.index(".reports-panel {"):][:400]
        self.assertIn("padding:", panel)
        self.assertIn("overflow-x: auto", panel, "a statement must not drop a column to fit")


class TodayMeansTheCalendarDayNotTheLastTwentyFourHours(unittest.TestCase):
    """A chip labelled "Today" was reaching back into most of yesterday.

    `days: 1` meant `now - 86400`, so yesterday's subscription renewals were reported as today's sales
    and the scoped profit read "On 2 of 4 sales" when two of those four were not today's at all
    (reported 2026-10-12). Every other window is legitimately rolling — "Last 7 days" does mean the
    last seven — but a calendar word has to mean the calendar thing.
    """

    import pathlib as _pathlib
    VIEW = (_pathlib.Path(__file__).resolve().parents[1]
            / "dashboard/src/components/Reports.vue").read_text(encoding="utf-8")

    def _window_fn(self):
        body = self.VIEW[self.VIEW.index("function windowFor(spec) {"):]
        return body[:body.index("\n}") + 2]

    def test_today_is_flagged_as_a_calendar_day(self):
        self.assertIn('{ key: "today", label: "Today", days: 1, calendarDay: true }', self.VIEW)

    def test_it_starts_at_local_midnight(self):
        """LOCAL, not UTC: a tenant's today is the one on their own wall, and the ledger stores epoch
        seconds so the browser is the only place that knows which that is."""
        body = self._window_fn()
        self.assertIn("setHours(0, 0, 0, 0)", body)
        self.assertIn("spec.calendarDay", body)

    def test_its_comparison_is_yesterday_whole(self):
        """A whole day against a part of one — what every sales dashboard means by "vs yesterday"."""
        body = self._window_fn()
        self.assertIn("previousFrom: from - 86400", body)
        self.assertIn("previousTo: from - 1", body)

    def test_the_rolling_windows_are_untouched(self):
        """"Last 7 days" genuinely means the last seven, and should not become a calendar week."""
        body = self._window_fn()
        self.assertIn("now - spec.days * 86400", body)
        self.assertIn("now - spec.days * 2 * 86400", body)

    def test_all_time_still_has_nothing_before_it(self):
        body = self._window_fn()
        self.assertIn("if (!spec.days) return { from: null, previousFrom: null, previousTo: null };", body)
