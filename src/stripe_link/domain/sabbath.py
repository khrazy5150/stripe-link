"""Sabbath mode — an opt-in weekly store closure (plans/TODO.md "Sabbath mode").

A tenant may close their store from **Friday sundown − a buffer** to **Saturday sundown + a buffer**.
Off by default; this is a TENANT's choice about their own shop, which is why it does not conflict with
the free-forever "never block a sale" rule — nobody else is deciding it for them.

**The sundown is computed here, not fetched.** The 2020 attempt at this feature died when the external
sunset API it depended on went away, and the plan is explicit: *"Do not reach for an external sunset
service. That dependency is precisely what killed the 2020 version."* Sundown is pure maths from latitude,
longitude and date, so it is implemented below with no network call and nothing to go down.

**NOAA, not `astral`.** The plan suggests the `astral` package *or* the NOAA formula. `src/requirements.txt`
is intentionally empty — a dependency there is bundled into every one of ~49 function packages, and the
last time boto3 was listed it cost ~6.5s of cold start. A fifty-line solar routine is the cheaper side of
that trade, and `astral` would be carried by functions that never compute a sunset.

**TWO sundowns, never one plus 24 hours.** Friday's sundown and Saturday's sundown are different times —
by a minute or two near the equinoxes and much more at high latitude — so the window is built from both.
Treating the Sabbath as "sundown plus 24h" would close the store at the wrong moment every week, in a way
that drifts with the season and is worst exactly where the days change fastest.
"""
from __future__ import annotations

import datetime
import math
from typing import Any

#: Jewish practice commonly lights candles ~18 min before sundown and ends the Sabbath at nightfall,
#: ~40 min after (some customs ~50). Those are the shipped defaults; the maximum is an hour either side.
#: ZERO ON BOTH is a real setting, and means the store closes exactly at sundown and reopens exactly at
#: sundown — not an "unset" value to be replaced by a default.
DEFAULT_BEFORE_MINUTES = 18
DEFAULT_AFTER_MINUTES = 40
MIN_BUFFER_MINUTES = 0
MAX_BUFFER_MINUTES = 60

#: The manual window a polar tenant supplies instead. The Sabbath is ~24h sundown-to-sundown, so a manual
#: stand-in is bounded either side of that rather than left free.
MIN_MANUAL_HOURS = 24
MAX_MANUAL_HOURS = 25

#: Friday, as `datetime.weekday()` numbers it (Monday is 0).
_FRIDAY = 4

#: The sun's centre is this far below the horizon at apparent sunset — the standard correction for
#: atmospheric refraction and the sun's own radius. Omitting it puts sundown a few minutes early.
_SUNSET_ZENITH_DEGREES = -0.833


def clamp_buffer(value: Any, default: int) -> int:
    """A buffer in minutes, 0-60. Out of range is CLAMPED, not refused.

    A tenant who types 90 means "as much as you allow", and an error message about a maximum they cannot
    see while typing is worse than the maximum applied. Nonsense that is not a number falls back to the
    default, because a store closing at an unparseable time is the one outcome nobody chose.
    """
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(MIN_BUFFER_MINUTES, min(MAX_BUFFER_MINUTES, minutes))


def _julian_day(date: datetime.date) -> float:
    """The Julian day number for 00:00 UTC on `date`."""
    y, m, d = date.year, date.month, date.day
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5)


def sunset_utc(date: datetime.date, latitude: float, longitude: float) -> datetime.datetime | None:
    """Apparent sunset on `date` at (lat, lon), as an aware UTC datetime. None when the sun does not set.

    The standard NOAA sunrise/sunset equation. **None is a real answer, not a failure**: above the Arctic
    circle in summer and below the Antarctic circle in winter there is no sunset for weeks, and the plan
    calls for the tenant's manual window in exactly that case. A formula that returned "something" there
    would close a store at an invented time.
    """
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None

    # +0.5 because J2000.0 (JD 2451545.0) is 2000-01-01 at NOON, while `_julian_day` returns midnight.
    # Without it every transit lands twelve hours early and the routine returns sunrise-ish times that
    # look plausible in isolation — the equator at equinox came out 06:12 instead of 18:12.
    # The 0.0008 is the usual leap-second fudge and is unrelated.
    n = (_julian_day(date) + 0.5) - 2451545.0 + 0.0008
    mean_solar_noon = n - lon / 360.0
    mean_anomaly = (357.5291 + 0.98560028 * mean_solar_noon) % 360.0
    m_rad = math.radians(mean_anomaly)
    center = 1.9148 * math.sin(m_rad) + 0.0200 * math.sin(2 * m_rad) + 0.0003 * math.sin(3 * m_rad)
    ecliptic_longitude = (mean_anomaly + center + 180.0 + 102.9372) % 360.0
    lam = math.radians(ecliptic_longitude)
    transit = (2451545.0 + mean_solar_noon + 0.0053 * math.sin(m_rad) - 0.0069 * math.sin(2 * lam))

    sin_declination = math.sin(lam) * math.sin(math.radians(23.4397))
    declination = math.asin(sin_declination)
    lat_rad = math.radians(lat)
    denominator = math.cos(lat_rad) * math.cos(declination)
    if abs(denominator) < 1e-12:
        return None
    cos_hour_angle = ((math.sin(math.radians(_SUNSET_ZENITH_DEGREES)) - math.sin(lat_rad) * sin_declination)
                      / denominator)
    if cos_hour_angle > 1.0 or cos_hour_angle < -1.0:
        # Polar day or polar night: the sun never crosses the horizon on this date.
        return None

    julian_set = transit + math.degrees(math.acos(cos_hour_angle)) / 360.0
    # Julian date -> UTC. Unix epoch is JD 2440587.5.
    seconds = (julian_set - 2440587.5) * 86400.0
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)


def sunset_on_local_date(date: datetime.date, latitude: float, longitude: float,
                         tzinfo: datetime.tzinfo) -> datetime.datetime | None:
    """The sunset whose LOCAL calendar date is `date`, in `tzinfo`. None when the sun does not set.

    **A timezone is a political choice, not a longitude.** `sunset_utc` answers for the solar day that
    begins at 00:00 UTC, which lands on the right local date only where the offset roughly matches
    longitude/15. Some places are nowhere near that: Kiritimati sits at 157 degrees WEST and keeps
    UTC+14, a discrepancy of about a day, and the Chatham Islands keep +12:45 at 176 degrees west. For
    both, "Friday's sundown" computed from the raw date is Saturday's sundown locally — so the store
    closed on Saturday evening and reopened on Sunday, one whole day late, every week.

    Found 2026-11-05 by running the window at ten international locations rather than by a test; the
    northern-hemisphere and European cases were all correct, which is exactly why it survived.

    Searches the neighbouring days rather than computing an offset, because the thing being matched is a
    calendar date in a zone whose rules (including DST) only `tzinfo` knows.
    """
    for shift in (0, -1, 1):
        candidate = sunset_utc(date + datetime.timedelta(days=shift), latitude, longitude)
        if candidate is not None and candidate.astimezone(tzinfo).date() == date:
            return candidate
    return None


def _friday_on_or_before(local_now: datetime.datetime) -> datetime.date:
    """The Friday of the Sabbath this moment could belong to.

    Looking BACK rather than forward is what makes a window that runs past midnight work: at 00:05 on
    Sunday, after a late northern sundown, the Sabbath that is still running began on the Friday two days
    ago. Searching forward would find next week's and report the store open.
    """
    return (local_now - datetime.timedelta(days=(local_now.weekday() - _FRIDAY) % 7)).date()


def window(local_now: datetime.datetime, *, latitude: float, longitude: float,
           before_minutes: int = DEFAULT_BEFORE_MINUTES,
           after_minutes: int = DEFAULT_AFTER_MINUTES
           ) -> tuple[datetime.datetime, datetime.datetime] | None:
    """The closure window around `local_now`, as aware UTC datetimes, or None if sundown is unavailable.

    `local_now` must be timezone-aware in the STORE's zone: which calendar day it is, and therefore which
    Friday the Sabbath belongs to, is a local question. Handing this a UTC clock would pick the wrong day
    for every store west of Greenwich for part of each evening.
    """
    friday = _friday_on_or_before(local_now)
    # Resolved against the STORE's zone, not the raw date: see `sunset_on_local_date`.
    tz = local_now.tzinfo or datetime.timezone.utc
    friday_sundown = sunset_on_local_date(friday, latitude, longitude, tz)
    saturday_sundown = sunset_on_local_date(friday + datetime.timedelta(days=1), latitude, longitude, tz)
    if friday_sundown is None or saturday_sundown is None:
        return None
    start = friday_sundown - datetime.timedelta(minutes=clamp_buffer(before_minutes, DEFAULT_BEFORE_MINUTES))
    end = saturday_sundown + datetime.timedelta(minutes=clamp_buffer(after_minutes, DEFAULT_AFTER_MINUTES))
    return start, end


def wall_time(day: datetime.date, hour: int, minute: int,
              tz: datetime.tzinfo) -> datetime.datetime:
    """A local wall-clock moment, resolved through a DST transition.

    Two days a year a wall time is not a moment. On the spring-forward the named time may not EXIST
    (02:30 where the clock jumps 02:00 to 03:00); on the autumn fall-back it happens TWICE. Both are
    silent: Python will hand back a datetime either way, and it is only wrong later.

    - **Nonexistent** -> the first real moment after the gap. A closure that cannot begin at the time it
      was set for should begin as soon as it can, not an hour early.
    - **Ambiguous** -> the EARLIER of the two (`fold=0`). For a closure START the earlier reading closes
      sooner, which is the safe direction for an observance; nobody is harmed by a shop shutting a little
      early, and the opposite choice would keep it open during a window the tenant meant to be closed.

    Narrow but real: above the Arctic Circle the polar night and the DST change do not usually overlap --
    but Svalbard's runs 26 Oct to 15 Feb, straight through Norway's late-October transition.
    """
    naive = datetime.datetime(day.year, day.month, day.day, int(hour), int(minute))
    aware = naive.replace(tzinfo=tz, fold=0)
    rendered = aware.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None)
    if rendered != naive:
        # The named time fell in a spring-forward gap; `fold=0` already resolves to the instant just
        # after it, which is the first real moment. Re-derive it rather than trusting the naive value.
        return aware.astimezone(datetime.timezone.utc).astimezone(tz)
    return aware


def manual_window(local_now: datetime.datetime, *, weekday: int, hour: int, minute: int,
                  duration_hours: float) -> tuple[datetime.datetime, datetime.datetime]:
    """The tenant's own window, for a place where the sun does not set.

    Anchored on the same look-BACK rule as the solar one, so a window running past midnight still
    contains the moments after midnight.

    **The duration is ABSOLUTE hours, not wall-clock hours.** Adding a `timedelta` to an aware datetime
    does WALL-CLOCK arithmetic -- Friday 18:00 plus 24h is Saturday 18:00 even when the clocks changed in
    between, which is 23 or 25 real hours. The tenant asked for a span of time, and the Sabbath this
    stands in for is ~24 hours of actual time, so the arithmetic is done in UTC and converted back.
    """
    tz = local_now.tzinfo or datetime.timezone.utc
    day = (local_now - datetime.timedelta(days=(local_now.weekday() - int(weekday)) % 7)).date()
    start = wall_time(day, hour, minute, tz)
    hours = max(MIN_MANUAL_HOURS, min(MAX_MANUAL_HOURS, float(duration_hours)))
    end_utc = start.astimezone(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    return start, end_utc.astimezone(tz)


def validate_manual_window(manual: Any) -> dict[str, Any] | None:
    """A stored manual window, normalized, or None if it is not usable.

    None rather than an exception, and None leaves the store OPEN: a half-filled polar setting should not
    close a shop at a time nobody chose, which is the same direction everything else here fails in.
    """
    if not isinstance(manual, dict):
        return None
    try:
        weekday, hour, minute = int(manual.get("weekday", _FRIDAY)), int(manual["hour"]), int(manual["minute"])
        hours = float(manual.get("duration_hours", MIN_MANUAL_HOURS))
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= weekday <= 6 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return {"weekday": weekday, "hour": hour, "minute": minute,
            "duration_hours": max(MIN_MANUAL_HOURS, min(MAX_MANUAL_HOURS, hours))}


def is_closed(local_now: datetime.datetime, start: datetime.datetime,
              end: datetime.datetime) -> bool:
    """Is the store inside its closure window? Inclusive of both ends.

    **Compared in UTC, deliberately.** When two aware datetimes share the same `tzinfo` object Python
    ignores it and compares the WALL CLOCKS -- documented behaviour, and a trap here, because wall clocks
    are not monotonic: on a fall-back 01:30 happens twice, so a naive comparison can order a later moment
    before an earlier one. The solar window arrives in UTC and `local_now` in the store's zone, so that
    path was already safe; a MANUAL window arrives in the store's zone and would have been compared
    naively against a clock in the same zone. Converting first makes both paths the same.

    Inclusive because the boundary is a moment a tenant chose, and a buyer reaching checkout exactly at
    sundown should see the closure they asked for rather than slip through on a rounding.
    """
    utc = datetime.timezone.utc
    return start.astimezone(utc) <= local_now.astimezone(utc) <= end.astimezone(utc)
# --- The stored setting, and the question a caller actually asks -------------------------------------


class SabbathClosedError(Exception):
    """The store is inside its own Sabbath window. Carries what the closure page has to say.

    An exception rather than a boolean because the one caller that matters -- checkout -- already refuses
    this way for suspension and billing (`assert_not_suspended`), and a third shape for "this store is not
    taking orders right now" would be a third thing to remember at every new transaction point.
    """

    def __init__(self, resume_at: datetime.datetime, timezone_name: str) -> None:
        super().__init__("This store is closed for the Sabbath.")
        self.resume_at = resume_at
        self.timezone_name = timezone_name


def config(profile: Any) -> dict[str, Any]:
    """The tenant's Sabbath setting, normalized. Always returns a usable dict; never raises.

    **On the TENANT, not the Site** (plans/TODO.md: *"the closure is a store (tenant) property ... so
    every login sees the same state"*). Observing the Sabbath is a fact about the person who runs the
    shops, not about any one storefront, so a tenant with three Sites closes all three. The COORDINATES
    are resolved separately and per-Site, because where a business is really can differ.

    OFF unless explicitly on. Every other reading of a missing value would close someone's store for
    them, which is the one direction this must never fail.
    """
    stored = (profile or {}).get("sabbath") if isinstance(profile, dict) else None
    stored = stored if isinstance(stored, dict) else {}
    manual = validate_manual_window(stored.get("manual"))
    return {
        "enabled": bool(stored.get("enabled")),
        "before_minutes": clamp_buffer(stored.get("before_minutes"), DEFAULT_BEFORE_MINUTES),
        "after_minutes": clamp_buffer(stored.get("after_minutes"), DEFAULT_AFTER_MINUTES),
        "manual": manual,
    }


def coordinates(organization: Any) -> tuple[float, float] | None:
    """(lat, lon) from a Site's `organization.geo`, or None when it has none.

    Both coordinates or neither: a geo carrying only a latitude is a half-filled form, and guessing the
    other half would compute a sundown for a place nobody named.
    """
    geo = (organization or {}).get("geo") if isinstance(organization, dict) else None
    if not isinstance(geo, dict):
        return None
    try:
        lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
    except (TypeError, ValueError):
        return None
    return (lat, lon)


def assert_open(profile: Any, organization: Any, *, timezone_name: str = "",
                now: datetime.datetime | None = None) -> None:
    """Raise `SabbathClosedError` if this tenant's store is closed right now. Otherwise return.

    **FAILS OPEN at every missing input**, and the asymmetry is deliberate: refusing a sale the tenant did
    not ask to refuse is worse than taking one during a window we could not compute. A tenant who turns
    this on and sees their store stay open will tell us; a tenant whose store closed because their Site
    had no coordinates would lose sales silently and have nothing to look at.

    So: off by default, open when there are no coordinates, open when the sun does not set and no manual
    window was given, and open if anything at all goes wrong in the maths.
    """
    setting = config(profile)
    if not setting["enabled"]:
        return
    zone_name = str(timezone_name or "UTC")
    try:
        from stripe_link.domain.store_timezone import load_zone

        local_now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(load_zone(zone_name))
        span = None
        here = coordinates(organization)
        if here is not None:
            span = window(local_now, latitude=here[0], longitude=here[1],
                          before_minutes=setting["before_minutes"],
                          after_minutes=setting["after_minutes"])
        if span is None:
            # ONLY when the sun does not set. The manual window is the polar fallback, not a second way
            # to configure an ordinary store -- a tenant in Denver who filled it in by accident should
            # still be closed by their real sundown, which is the thing they actually observe.
            manual = validate_manual_window(setting["manual"])
            if manual:
                span = manual_window(local_now, **manual)
        if span is None:
            return
        start, end = span
    except Exception:  # noqa: BLE001 - see the docstring; a broken clock must not refuse a sale
        import logging

        logging.getLogger(__name__).exception("sabbath: could not resolve the window; leaving the store open")
        return
    if is_closed(local_now, start, end):
        raise SabbathClosedError(end.astimezone(local_now.tzinfo), zone_name)
