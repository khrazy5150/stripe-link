"""The calendar-first slot picker shared by the three surfaces that sell a time.

Asked for 2026-11-11, looking at a landing page that printed every open slot for the next fortnight --
roughly 150 buttons -- and could not reach December at all. Three surfaces had three copies of that flat
list, each hardcoding a 14-day window the engine never imposed (`scheduling.MAX_RANGE_DAYS` is 62).

The picker runs in a browser, so most of this file runs it in one: a small DOM stands in for the document
and a stubbed `fetch` for the availability API. Parsing the file proves nothing about which days light up.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.scheduling import MAX_RANGE_DAYS
from stripe_link.runtime.booking_page import render_booking_page
from stripe_link.runtime.html import render_page_interactions_script
from stripe_link.runtime.manage_page import render_manage_page
from stripe_link.runtime.slot_picker import HORIZON_DAYS, PICKER_JS

ROOT = pathlib.Path(__file__).resolve().parents[1]

SERVICE = {"service_id": "svc_1", "tenant_id": "t1", "name": "60-Minute Massage",
           "duration_minutes": 60, "stripe_mode": "live",
           "price": {"currency": "usd", "unit_amount": 7800}}

APPOINTMENT = {
    "tenant_id": "t1", "appointment_id": "appt_1",
    "services": [{"service_id": "svc_1", "service_name": "60-Minute Massage", "duration_minutes": 60,
                  "price": {"currency": "usd", "unit_amount": 7800}}],
    "starts_at": "2026-11-12T08:00:00-07:00", "ends_at": "2026-11-12T09:00:00-07:00",
    "timezone": "America/Denver", "status": "booked", "payment_status": "unpaid",
    "booking_flow": "book_then_pay", "stripe_mode": "live",
    "customer": {"name": "Kelly", "email": "k@example.com"}, "customer_manage_token": "tok",
}

BOOKING_PAGE = {"page_id": "p1", "sections": [
    {"type": "checkout_cta", "cta": {"type": "booking", "target": "svc_1", "label": "Book Now"}}]}


# A DOM just large enough for the picker: elements, classes, text, a two-selector querySelector and
# clickable listeners. Deliberately tiny -- it exists to let the picker's own logic run, not to be a browser.
_DOM = r"""
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this._classes = [];
    this._text = ''; this._listeners = {}; this.disabled = false; this.type = ''; }
  get className() { return this._classes.join(' '); }
  set className(v) { this._classes = String(v).split(/\s+/).filter(Boolean); }
  get classList() { const self = this; return {
    add: (c) => { if (self._classes.indexOf(c) < 0) self._classes.push(c); },
    remove: (c) => { self._classes = self._classes.filter((x) => x !== c); },
    contains: (c) => self._classes.indexOf(c) >= 0 }; }
  get textContent() { return this._text || this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { this.children = []; this._text = String(v).replace(/<[^>]*>/g, ''); }
  get innerHTML() { return this._text; }
  appendChild(c) { this.children.push(c); this._text = ''; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  click() { (this._listeners.click || []).forEach((fn) => fn()); }
  matches(sel) {
    if (sel.startsWith('[') && sel.endsWith(']')) return Object.prototype.hasOwnProperty.call(this.attrs, sel.slice(1, -1));
    if (sel.startsWith('.')) return this._classes.indexOf(sel.slice(1)) >= 0;
    return this.tag === sel;
  }
  walk(out) { this.children.forEach((c) => { out.push(c); c.walk(out); }); return out; }
  querySelectorAll(sel) { return this.walk([]).filter((e) => e.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
global.document = { createElement: (t) => new El(t) };
global.window = global;
const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i += 1) await flush(); };
"""


def run_js(body, *, timezone="America/Denver", slots=None, viewer_tz=None):
    """Mount the picker against a stubbed availability API and return whatever `body` prints."""
    if not shutil.which("node"):
        raise unittest.SkipTest("node not available")
    payload = json.dumps({"timezone": timezone, "slots": slots or []})
    script = (
        _DOM
        + "global.fetch = (url) => { global.lastUrl = url; return Promise.resolve({ json: () => "
        + f"Promise.resolve({payload}) }}); }};\n"
        + PICKER_JS
        + "\n(async () => {\n" + body + "\n})();\n"
    )
    import os
    env = dict(os.environ)
    if viewer_tz:
        env["TZ"] = viewer_tz   # the VIEWER's machine zone, which must not move the appointment
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60, env=env)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


MOUNT = """
const host = new El('div');
const picked = [];
const picker = window.slpMount({ host, apiBase: 'https://api.example.com', serviceId: 'svc_1',
  mode: 'live', onSelect: (s, t, d) => picked.push({ start: s && s.start, time: t, day: d }) });
await settle();
"""


class TheDayIsTheBusinessDay(unittest.TestCase):
    """The flat list grouped by `new Date(iso).toDateString()` -- the VIEWER's zone. A calendar makes that
    visible as a date cell lighting up on a day the business is shut, so the picker asks the availability
    response for the business's zone and groups by that. Same call `booking_email.py` makes."""

    def test_a_late_slot_belongs_to_the_business_day_not_the_utc_one(self):
        # 02:00 UTC is 7:00 PM the PREVIOUS day in Denver. Grouping by UTC would file it a day late.
        out = run_js(MOUNT + """
        const d = new Date(Date.now() + 5 * 86400000);
        console.log(JSON.stringify({
          head: host.querySelector('[data-slp-times]').children[0].textContent,
          chips: host.querySelectorAll('.slp-chip').map((c) => c.textContent),
          zone: host.querySelectorAll('.slp-zone').map((c) => c.textContent),
        }));
        """, slots=_slots_at_utc_hour(2), viewer_tz="UTC")
        self.assertEqual(out["chips"], ["7:00 PM"], "the time must be the business's wall clock")
        expected_day = _business_day_label(2)
        self.assertIn(expected_day, out["head"],
                      f"grouped under the wrong day: {out['head']!r} should be {expected_day!r}")
        self.assertTrue(out["zone"] and ("MST" in out["zone"][0] or "MDT" in out["zone"][0]),
                        f"the zone has to be named on screen, got {out['zone']!r}")

    def test_the_viewer_zone_is_not_consulted(self):
        """Run the same mount on a machine set to Tokyo. A viewer's zone must not move the time."""
        out = run_js(MOUNT + """
        console.log(JSON.stringify({
          chips: host.querySelectorAll('.slp-chip').map((c) => c.textContent),
          head: host.querySelector('[data-slp-times]').children[0].textContent,
        }));
        """, slots=_slots_at_utc_hour(2), viewer_tz="Asia/Tokyo")
        self.assertEqual(out["chips"], ["7:00 PM"], "the viewer's zone leaked into the time")
        self.assertIn(_business_day_label(2), out["head"],
                      "the viewer's zone leaked into the day")


class TheGridOnlyOpensDaysThatHaveTimes(unittest.TestCase):
    def test_a_day_with_no_slots_is_disabled(self):
        out = run_js(MOUNT + """
        const cells = host.querySelectorAll('.slp-day');
        console.log(JSON.stringify({
          total: cells.length,
          open: cells.filter((c) => c.classList.contains('is-open')).length,
          openAllEnabled: cells.filter((c) => c.classList.contains('is-open')).every((c) => !c.disabled),
          closedAllDisabled: cells.filter((c) => !c.classList.contains('is-open')).every((c) => c.disabled),
        }));
        """, slots=_slots_at_utc_hour(16))
        self.assertEqual(out["total"], 42, "a month grid is six weeks")
        self.assertTrue(out["openAllEnabled"], "a day with times must be clickable")
        self.assertTrue(out["closedAllDisabled"], "a day with no times must not be")

    def test_no_availability_at_all_is_a_quiet_empty_calendar(self):
        out = run_js(MOUNT + """
        const cells = host.querySelectorAll('.slp-day');
        console.log(JSON.stringify({
          open: cells.filter((c) => c.classList.contains('is-open')).length,
          chips: host.querySelectorAll('.slp-chip').length,
          note: host.querySelectorAll('.slp-note').map((n) => n.textContent),
        }));
        """, slots=[])
        self.assertEqual(out["open"], 0)
        self.assertEqual(out["chips"], 0)
        self.assertTrue(any("Pick a date" in n for n in out["note"]),
                        f"an empty calendar still has to say what to do, got {out['note']!r}")


class TheHorizon(unittest.TestCase):
    def test_it_is_the_engines_own_limit(self):
        """Not a new policy. `available_slots` clamps to MAX_RANGE_DAYS, so a calendar that browsed
        further would draw months whose cells could never fill in."""
        self.assertEqual(HORIZON_DAYS, MAX_RANGE_DAYS)

    def test_browsing_forward_stops_at_the_horizon(self):
        out = run_js(MOUNT + """
        const nextBtn = () => host.querySelectorAll('.slp-nav')[1];
        let hops = 0;
        while (!nextBtn().disabled && hops < 8) { nextBtn().click(); await settle(); hops += 1; }
        console.log(JSON.stringify({ hops, stopped: nextBtn().disabled }));
        """, slots=_slots_at_utc_hour(16))
        self.assertTrue(out["stopped"], "the next arrow never switched off")
        self.assertLessEqual(out["hops"], 3, "62 days is at most three month hops")

    def test_you_cannot_browse_into_the_past(self):
        out = run_js(MOUNT + """
        console.log(JSON.stringify({ prevDisabled: host.querySelectorAll('.slp-nav')[0].disabled }));
        """, slots=_slots_at_utc_hour(16))
        self.assertTrue(out["prevDisabled"], "the current month is the first one")


class ChoosingATime(unittest.TestCase):
    def test_the_caller_is_handed_the_slot_and_both_labels(self):
        """The surfaces label their own confirm button and only the picker knows the business zone --
        re-deriving 'Book 8:00 AM' from the ISO through the viewer's locale contradicted the grid."""
        out = run_js(MOUNT + """
        host.querySelectorAll('.slp-chip')[0].click();
        console.log(JSON.stringify({ picked }));
        """, slots=_slots_at_utc_hour(16))
        self.assertEqual(len(out["picked"]), 1)
        chosen = out["picked"][0]
        self.assertTrue(chosen["start"])
        self.assertEqual(chosen["time"], "9:00 AM")
        self.assertIn(",", chosen["day"], f"a full day label, got {chosen['day']!r}")

    def test_moving_month_withdraws_the_selection(self):
        """A selection left standing after the calendar moved is a confirm button pointing at a time the
        customer can no longer see."""
        out = run_js(MOUNT + """
        host.querySelectorAll('.slp-chip')[0].click();
        host.querySelectorAll('.slp-nav')[1].click();
        await settle();
        console.log(JSON.stringify({ picked }));
        """, slots=_slots_at_utc_hour(16))
        self.assertEqual([p["start"] for p in out["picked"]][-1], None,
                         "the caller was never told the slot went away")


class EverySurfaceUsesIt(unittest.TestCase):
    """Three copies of the flat list is how the 14-day window survived three separate reviews."""

    def test_the_standalone_booking_page(self):
        page = render_booking_page(SERVICE)
        self._assert_wired(page, "booking page")

    def test_the_customers_manage_page(self):
        page = render_manage_page(APPOINTMENT, SERVICE, business_name="Luxe Wellness Spa",
                                  when="Thursday, November 12, 2026 at 8:00 AM MST")
        self._assert_wired(page, "manage page")

    def test_the_landing_page_island(self):
        self._assert_wired(render_page_interactions_script(BOOKING_PAGE), "landing island")

    def _assert_wired(self, doc, name):
        self.assertIn("window.slpMount", doc, f"{name}: does not mount the shared picker")
        self.assertIn(f"horizonDays: {HORIZON_DAYS}", doc, f"{name}: not browsing to the horizon")
        self.assertNotIn("14 * 86400", doc, f"{name}: still asking for a fortnight")
        self.assertNotIn("next two weeks", doc, f"{name}: still telling the customer about a fortnight")
        self.assertNotIn("__PICKER", doc, f"{name}: unreplaced template token")

    def test_a_page_that_does_not_book_does_not_carry_a_calendar(self):
        buy = {"page_id": "p2", "sections": [
            {"type": "checkout_cta", "cta": {"type": "buy", "target": "prod_1", "label": "Buy"}}]}
        self.assertNotIn("window.slpMount = function", render_page_interactions_script(buy))
        # ...but the island's call site still ships, so it must degrade rather than throw: this handler
        # is shared with the countdown, the carousels and the cart.
        self.assertIn("if (!window.slpMount)", render_page_interactions_script(buy))


def _slots_at_utc_hour(hour):
    """One slot, five days out, at a fixed UTC hour -- as the availability API returns them."""
    import datetime as _dt
    base = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=5)
    start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    return [{"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "end": (start + _dt.timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "fulfiller_id": None}]


def _business_day_label(hour):
    """How the picker should name that slot's day, in the business's zone."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    base = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=5)
    start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    local = start.astimezone(ZoneInfo("America/Denver"))
    return f"{local.strftime('%B')} {local.day}"


if __name__ == "__main__":
    unittest.main()
