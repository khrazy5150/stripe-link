"""The calendar-first slot picker, shared by every surface that sells a time.

Three pages let a customer choose an appointment: the standalone booking page (`booking_page.py`), the
inline booking island on a landing page (`html.py render_booking_cta`), and the reschedule picker on the
customer's own manage page (`manage_page.py`). All three had their OWN copy of the same flat list, and all
three hardcoded a 14-day window that the engine never asked for -- `scheduling.MAX_RANGE_DAYS` is 62. A
customer who wanted a date five weeks out was told, in three different fonts, that there was nothing.

So the picker lives here once and the three surfaces mount it. What it replaces printed every open slot in
the window at once: ~14 days x a dozen slots, hundreds of buttons, and a wall of availability reads as
desperation rather than choice.

TIMEZONE. Dates and times are the BUSINESS's, taken from the availability response, not the viewer's. This
is the same call `booking_email.py` makes and for the same reason: 8:00 AM is 8:00 AM when you turn up. It
also fixes a bug the flat list had been hiding -- grouping by the VIEWER's local date put a late slot on
the wrong day for anyone booking from another zone, and a calendar makes that visible as a date cell that
lights up on a day the business is shut. The zone is named on screen so a travelling customer can see it.

THEMING. One CSS body, driven by `--slp-*` custom properties each surface maps to its own tokens, and sized
in `em` throughout -- the landing page runs a 10px root while the standalone pages run 16px, so a shared
sheet in `rem` would render at two different scales. See `THEME_STANDALONE` / `THEME_LANDING`.
"""
from __future__ import annotations

# How far ahead a customer may browse. This is `scheduling.MAX_RANGE_DAYS`, NOT a new policy: the engine
# already refuses to compute past it (`range_end = min(range_end, range_start + MAX_RANGE_DAYS)`), so
# offering more months than this would draw a calendar whose later cells could never fill in. Deliberately
# not re-exported from `domain.scheduling`: `tests/envreach.py` follows imports transitively and the
# renderer must stay free of the scheduling engine. The test suite asserts the two numbers agree.
HORIZON_DAYS = 62

#: Maps the picker's own tokens onto the standalone booking/manage page palette.
THEME_STANDALONE = (
    ".slp{--slp-line:var(--line);--slp-accent:var(--accent);--slp-muted:var(--muted);"
    "--slp-surface:#fff;--slp-text:#111827;font-size:1rem}"
)

#: Maps them onto the landing page's published theme tokens.
THEME_LANDING = (
    "    .slp{--slp-line:var(--sl-price-card-border);--slp-accent:var(--sl-brand);"
    "--slp-muted:var(--sl-price-description);--slp-surface:var(--sl-background);"
    "--slp-text:var(--sl-text);font-size:1.4rem}"
)

PICKER_CSS = (
    ".slp{display:block;text-align:left;color:var(--slp-text)}"
    ".slp-head{display:flex;align-items:center;justify-content:space-between;gap:.5em;margin-bottom:.75em}"
    ".slp-month{font-weight:700;font-size:1.05em}"
    ".slp-nav{background:none;border:1px solid var(--slp-line);color:inherit;border-radius:.5em;"
    "width:2em;height:2em;line-height:1;cursor:pointer;font-size:1em}"
    ".slp-nav[disabled]{opacity:.35;cursor:not-allowed}"
    ".slp-week{display:grid;grid-template-columns:repeat(7,1fr);gap:.25em;margin-bottom:.25em}"
    ".slp-week span{text-align:center;font-size:.8em;color:var(--slp-muted)}"
    ".slp-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:.25em}"
    ".slp-day{aspect-ratio:1;border:1px solid transparent;background:none;color:inherit;border-radius:50%;"
    "cursor:pointer;font-size:.95em;font-variant-numeric:tabular-nums;padding:0}"
    ".slp-day[disabled]{color:var(--slp-muted);opacity:.4;cursor:default}"
    ".slp-day.is-open{border-color:var(--slp-line);font-weight:700}"
    ".slp-day.is-today{border-color:var(--slp-accent)}"
    ".slp-day.is-selected{background:var(--slp-accent);color:#fff;border-color:var(--slp-accent)}"
    ".slp-times{margin-top:1em}"
    ".slp-times-head{font-weight:700;margin-bottom:.5em}"
    ".slp-zone{color:var(--slp-muted);font-size:.8em;margin:.25em 0 0}"
    ".slp-chips{display:flex;flex-wrap:wrap;gap:.5em}"
    ".slp-chip{border:1px solid var(--slp-line);background:var(--slp-surface);color:var(--slp-text);"
    "border-radius:.6em;padding:.5em .8em;cursor:pointer;font-size:.95em}"
    ".slp-chip.is-selected{background:var(--slp-accent);color:#fff;border-color:var(--slp-accent)}"
    ".slp-note{color:var(--slp-muted)}"
    ".slp-note.is-error{color:#dc2626}"
)

# Defines window.slpMount(opts) -> { refresh() }.
#
# opts: host, apiBase, serviceId, mode, durationMinutes (optional), onSelect(slot|null, timeLabel, dayLabel).
# Raw string: the regexes below carry backslashes that Python would otherwise read as escapes.
PICKER_JS = r"""
window.slpMount = function (opts) {
  var host = opts.host;
  if (!host) { return null; }
  var apiBase = String(opts.apiBase || '').replace(/\/+$/, '');
  var serviceId = String(opts.serviceId || '');
  var mode = String(opts.mode || 'test');
  var duration = Number(opts.durationMinutes || 0);
  var onSelect = opts.onSelect || function () {};
  var HORIZON_DAYS = Number(opts.horizonDays || 62);
  var DAY_MS = 86400000;

  var now = new Date();
  var horizonEnd = new Date(now.getTime() + HORIZON_DAYS * DAY_MS);
  var tz = null;                 // the BUSINESS's zone, learned from the first response
  var cache = {};                // 'YYYY-MM' -> { byDate: { 'YYYY-MM-DD': [slot] } }
  var cursor = new Date(now.getFullYear(), now.getMonth(), 1);
  var selectedDate = null;
  var selectedSlot = null;
  var autoPicked = false;

  host.className = 'slp';

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function monthKey(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1); }

  // The business's calendar date for an instant. en-CA formats as YYYY-MM-DD, which sorts and compares
  // as a string -- the reason for the otherwise odd locale.
  function businessDate(iso) {
    var d = new Date(iso);
    if (tz) {
      try {
        return new Intl.DateTimeFormat('en-CA', {
          timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
        }).format(d);
      } catch (e) { /* unknown zone: fall through to the viewer's */ }
    }
    return ymd(d);
  }

  function timeLabel(iso) {
    var o = { hour: 'numeric', minute: '2-digit' };
    if (tz) { o.timeZone = tz; }
    try { return new Date(iso).toLocaleTimeString([], o); }
    catch (e) { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
  }

  function zoneLabel() {
    if (!tz) { return ''; }
    try {
      var parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
        .formatToParts(new Date());
      for (var i = 0; i < parts.length; i += 1) {
        if (parts[i].type === 'timeZoneName') { return parts[i].value; }
      }
    } catch (e) { /* fall through */ }
    return tz;
  }

  function dayLabel(key) {
    var p = key.split('-');
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return d.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  }

  function fetchMonth(key) {
    if (cache[key]) { return Promise.resolve(cache[key]); }
    var p = key.split('-');
    var monthStart = Date.UTC(Number(p[0]), Number(p[1]) - 1, 1);
    var monthEnd = Date.UTC(Number(p[0]), Number(p[1]), 1);
    // A day of padding each side: the month's edges are UTC here but the grouping below is the
    // business's, and those disagree by up to a day. Slots outside the month are simply never read.
    var from = Math.floor(Math.max(monthStart - DAY_MS, now.getTime()) / 1000);
    var to = Math.floor(Math.min(monthEnd + DAY_MS, horizonEnd.getTime()) / 1000);
    if (to <= from) { cache[key] = { byDate: {} }; return Promise.resolve(cache[key]); }
    var url = `${apiBase}/services/${encodeURIComponent(serviceId)}/availability?from=${from}&to=${to}&mode=${encodeURIComponent(mode)}`;
    if (duration > 0) { url += '&duration_minutes=' + duration; }
    return fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.timezone) { tz = d.timezone; }   // BEFORE grouping: businessDate() reads it
      var byDate = {};
      (d && d.slots ? d.slots : []).forEach(function (s) {
        var k = businessDate(s.start);
        (byDate[k] = byDate[k] || []).push(s);
      });
      cache[key] = { byDate: byDate };
      return cache[key];
    });
  }

  function clearSelection() {
    if (selectedSlot) { selectedSlot = null; onSelect(null, '', ''); }
  }

  function renderTimes(byDate) {
    var times = host.querySelector('[data-slp-times]');
    times.innerHTML = '';
    if (!selectedDate) {
      var hint = document.createElement('p');
      hint.className = 'slp-note';
      hint.textContent = 'Pick a date to see available times.';
      times.appendChild(hint);
      return;
    }
    var head = document.createElement('div');
    head.className = 'slp-times-head';
    head.textContent = dayLabel(selectedDate);
    times.appendChild(head);

    var slots = byDate[selectedDate] || [];
    if (!slots.length) {
      var none = document.createElement('p');
      none.className = 'slp-note';
      none.textContent = 'No times left on this day.';
      times.appendChild(none);
      return;
    }
    var chips = document.createElement('div');
    chips.className = 'slp-chips';
    slots.forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'slp-chip';
      b.textContent = timeLabel(s.start);
      if (selectedSlot && selectedSlot.start === s.start) { b.classList.add('is-selected'); }
      b.setAttribute('aria-pressed', selectedSlot && selectedSlot.start === s.start ? 'true' : 'false');
      b.addEventListener('click', function () {
        selectedSlot = s;
        chips.querySelectorAll('.slp-chip').forEach(function (el) {
          el.classList.remove('is-selected');
          el.setAttribute('aria-pressed', 'false');
        });
        b.classList.add('is-selected');
        b.setAttribute('aria-pressed', 'true');
        onSelect(s, b.textContent, dayLabel(selectedDate));
      });
      chips.appendChild(b);
    });
    times.appendChild(chips);

    var zone = zoneLabel();
    if (zone) {
      var z = document.createElement('p');
      z.className = 'slp-zone';
      z.textContent = 'All times ' + zone;
      times.appendChild(z);
    }
  }

  function render(byDate, note) {
    var todayKey = businessDate(now.toISOString());
    var first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    var gridStart = new Date(first);
    gridStart.setDate(1 - first.getDay());

    var prevDisabled = cursor.getFullYear() === now.getFullYear() && cursor.getMonth() === now.getMonth();
    var nextMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
    var nextDisabled = nextMonth.getTime() > horizonEnd.getTime();

    host.innerHTML = '';

    var head = document.createElement('div');
    head.className = 'slp-head';
    var prev = document.createElement('button');
    prev.type = 'button'; prev.className = 'slp-nav'; prev.textContent = '‹';
    prev.setAttribute('aria-label', 'Previous month');
    prev.disabled = prevDisabled;
    prev.addEventListener('click', function () { move(-1); });
    var label = document.createElement('span');
    label.className = 'slp-month';
    label.textContent = cursor.toLocaleDateString([], { month: 'long', year: 'numeric' });
    var next = document.createElement('button');
    next.type = 'button'; next.className = 'slp-nav'; next.textContent = '›';
    next.setAttribute('aria-label', 'Next month');
    next.disabled = nextDisabled;
    next.addEventListener('click', function () { move(1); });
    head.appendChild(prev); head.appendChild(label); head.appendChild(next);
    host.appendChild(head);

    var week = document.createElement('div');
    week.className = 'slp-week';
    ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach(function (w) {
      var s = document.createElement('span'); s.textContent = w; week.appendChild(s);
    });
    host.appendChild(week);

    var grid = document.createElement('div');
    grid.className = 'slp-grid';
    for (var i = 0; i < 42; i += 1) {
      var d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      var key = ymd(d);
      var inMonth = d.getMonth() === cursor.getMonth();
      var open = inMonth && !!(byDate[key] && byDate[key].length);
      var cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'slp-day' + (open ? ' is-open' : '') + (key === todayKey ? ' is-today' : '')
        + (key === selectedDate ? ' is-selected' : '');
      cell.textContent = inMonth ? String(d.getDate()) : '';
      cell.disabled = !open;
      if (open) {
        cell.setAttribute('aria-label', dayLabel(key) + ', ' + byDate[key].length + ' times available');
        (function (k) {
          cell.addEventListener('click', function () {
            selectedDate = k;
            clearSelection();
            render(byDate, note);
          });
        }(key));
      }
      grid.appendChild(cell);
    }
    host.appendChild(grid);

    var times = document.createElement('div');
    times.className = 'slp-times';
    times.setAttribute('data-slp-times', '');
    times.setAttribute('aria-live', 'polite');
    host.appendChild(times);

    if (note) {
      var n = document.createElement('p');
      n.className = 'slp-note is-error';
      n.textContent = note;
      host.appendChild(n);
    }
    renderTimes(byDate);
  }

  function show(note) {
    var key = monthKey(cursor);
    var cached = cache[key];
    render(cached ? cached.byDate : {}, note);
  }

  function load() {
    var key = monthKey(cursor);
    if (!cache[key]) {
      host.innerHTML = '<p class="slp-note">Loading available times…</p>';
    }
    return fetchMonth(key).then(function (m) {
      // Nothing at all this month: step forward ONCE so the customer does not meet an empty grid on
      // arrival. Once only -- a service with no availability must not walk the calendar to the horizon.
      var empty = !Object.keys(m.byDate).length;
      if (empty && !autoPicked && monthKey(cursor) === monthKey(now)) {
        var ahead = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
        if (ahead.getTime() <= horizonEnd.getTime()) {
          autoPicked = true;
          cursor = ahead;
          return load();
        }
      }
      if (!autoPicked || !selectedDate) {
        var keys = Object.keys(m.byDate).sort();
        if (keys.length) { selectedDate = keys[0]; }
        autoPicked = true;
      }
      show('');
      return m;
    }).catch(function () {
      show('Could not load available times. Please try again.');
    });
  }

  function move(step) {
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + step, 1);
    selectedDate = null;
    clearSelection();
    load();
  }

  load();

  return {
    refresh: function () { cache = {}; selectedDate = null; clearSelection(); load(); },
  };
};
"""
