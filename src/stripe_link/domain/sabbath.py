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
    friday_sundown = sunset_utc(friday, latitude, longitude)
    saturday_sundown = sunset_utc(friday + datetime.timedelta(days=1), latitude, longitude)
    if friday_sundown is None or saturday_sundown is None:
        return None
    start = friday_sundown - datetime.timedelta(minutes=clamp_buffer(before_minutes, DEFAULT_BEFORE_MINUTES))
    end = saturday_sundown + datetime.timedelta(minutes=clamp_buffer(after_minutes, DEFAULT_AFTER_MINUTES))
    return start, end


def manual_window(local_now: datetime.datetime, *, weekday: int, hour: int, minute: int,
                  duration_hours: float) -> tuple[datetime.datetime, datetime.datetime]:
    """The tenant's own window, for a location where the sun does not set.

    Anchored on the same look-BACK rule as the solar one, so a window that runs past midnight still
    contains the moments after midnight.
    """
    day = (local_now - datetime.timedelta(days=(local_now.weekday() - int(weekday)) % 7)).date()
    start_local = local_now.tzinfo and datetime.datetime(
        day.year, day.month, day.day, int(hour), int(minute), tzinfo=local_now.tzinfo)
    hours = max(MIN_MANUAL_HOURS, min(MAX_MANUAL_HOURS, float(duration_hours)))
    return start_local, start_local + datetime.timedelta(hours=hours)


def is_closed(local_now: datetime.datetime, start: datetime.datetime, end: datetime.datetime) -> bool:
    """Is the store inside its closure window? Inclusive of both ends.

    Inclusive because the boundary is a moment a tenant chose, and a buyer who reaches checkout exactly
    at sundown should see the closure they asked for rather than slip through on a rounding.
    """
    return start <= local_now <= end
