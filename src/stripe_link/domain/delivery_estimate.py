"""When a parcel is actually due to arrive.

plans/THANK_YOU_PAGE.md P1. The thank-you page used to tell every buyer "Your order will arrive within
5-7 business days" — a sentence typed once by someone who could not know the destination, the service, or
the day of the week. This computes the real answer, and it is the only place that does: the page element
and the `{{arrival}}` token in a card both read from here, so a date cannot be worded two ways.

**Carrier transit days are BUSINESS days already.** Measured rather than assumed, against live Shippo
(2026-10-04):

    ups_second_day_air   estimated_days=2  "Delivery by the end of the second business day."
    ups_next_day_air     estimated_days=1  "Next business day delivery by 10:30 a.m. ..."

So the arrival is found by counting N business days FORWARD from the ship date. Adding N calendar days and
then nudging off a weekend would push nearly every estimate out by two days, which is the error this note
exists to prevent.

**The cutoff is a buffer, not a rule.** An order placed after it ships the next business day, because a
tenant who quietly ships same-day then beats the estimate — and setting expectations low and exceeding
them is the whole point of showing a date at all. Both the hour and the timezone are the tenant's to set
(author, 2026-10-04: *"we suggest but don't dictate"*); a seller may live in Pacific time and ship from a
warehouse in Mountain time, and only they know which is their working day.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone as _utc
from typing import Any

logger = logging.getLogger(__name__)

SATURDAY, SUNDAY = 5, 6
DEFAULT_CUTOFF_HOUR = 15          # 3pm, the author's suggestion and the default every tenant may change
DEFAULT_TIMEZONE = "UTC"


def _zone(name: str):
    """The tenant's timezone, or UTC with a LOUD complaint.

    `zoneinfo` is standard library but needs a tz database, which comes from the OS image or the `tzdata`
    package — and nothing in this codebase has depended on one before. A missing database must not crash a
    thank-you page, and must not silently shift every estimate by the offset either, so it degrades to UTC
    and says so. If this line ever appears in production the fix is one entry in `src/requirements.txt`.
    """
    wanted = str(name or "").strip() or DEFAULT_TIMEZONE
    if wanted == "UTC":
        return _utc.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(wanted)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delivery estimate falling back to UTC: timezone %r unavailable (%s: %s)",
                       wanted, type(exc).__name__, exc)
        return _utc.utc


def is_business_day(day: date) -> bool:
    """Weekends only. **Holidays are deliberately not modelled** — a carrier's own transit estimate
    already accounts for them, and layering our calendar on theirs would be wrong twice over. The buyer is
    told this is an estimate (author's call, 2026-10-04)."""
    return day.weekday() not in (SATURDAY, SUNDAY)


def next_business_day(day: date) -> date:
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def add_business_days(day: date, count: int) -> date:
    """`count` business days after `day`, not counting `day` itself.

    Zero is a real answer and means same-day, so it must not quietly become "tomorrow"."""
    out = day
    for _ in range(max(0, int(count))):
        out = next_business_day(out + timedelta(days=1))
    return out


def ship_date(ordered_at: Any, *, tz_name: str = DEFAULT_TIMEZONE,
              cutoff_hour: int = DEFAULT_CUTOFF_HOUR) -> date | None:
    """The day the parcel is expected to LEAVE, in the tenant's own working day.

    Three things move it: a weekend, the cutoff, or both. An order at 4pm on a Friday ships Monday.
    """
    try:
        stamp = int(ordered_at)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    placed = datetime.fromtimestamp(stamp, _zone(tz_name))
    day = placed.date()
    if placed.hour >= max(0, min(23, int(cutoff_hour))):
        day += timedelta(days=1)
    return next_business_day(day)


def estimate(ordered_at: Any, *, transit_days_min: Any, transit_days_max: Any = None,
             tz_name: str = DEFAULT_TIMEZONE,
             cutoff_hour: int = DEFAULT_CUTOFF_HOUR) -> dict[str, Any]:
    """`{ships_on, arrives_on, arrives_through, exact}` as ISO dates, or `{}` when it cannot be known.

    `{}` is a real answer and the caller must render it as such: an unmeasured product never reached a
    carrier, so it has no service and no transit days, and inventing "5-7 business days" for it is exactly
    the sentence this module replaced.
    """
    low = _whole(transit_days_min)
    high = _whole(transit_days_max if transit_days_max is not None else transit_days_min)
    if low is None:
        return {}
    if high is None or high < low:
        high = low
    ships = ship_date(ordered_at, tz_name=tz_name, cutoff_hour=cutoff_hour)
    if ships is None:
        return {}
    first = add_business_days(ships, low)
    last = add_business_days(ships, high)
    return {
        "ships_on": ships.isoformat(),
        "arrives_on": first.isoformat(),
        # None rather than a repeat of `arrives_on`: a caller deciding between one date and a range should
        # not have to compare two strings to find out which it has.
        "arrives_through": last.isoformat() if last != first else None,
        "exact": last == first,
    }


def _whole(value: Any) -> int | None:
    """Days, tolerating the `Decimal` a stored document hands back (`feedback_decimal_from_dynamo`)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None
