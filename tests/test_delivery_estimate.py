"""When a parcel is actually due to arrive.

plans/THANK_YOU_PAGE.md P1. The thank-you page told every buyer "Your order will arrive within 5-7
business days" — typed once by someone who could not know the destination, the service, or the day of the
week — on an order that had just paid $39.59 to Vancouver under a card headed "Free Shipping".

The one fact this rests on was MEASURED rather than assumed, against live Shippo (2026-10-04):

    ups_second_day_air   estimated_days=2  "Delivery by the end of the second business day."
    ups_next_day_air     estimated_days=1  "Next business day delivery by 10:30 a.m. ..."

Carrier transit days are already BUSINESS days. So arrival counts N business days forward; adding N
calendar days and then nudging off a weekend would push nearly every estimate out by two days.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from stripe_link.domain.delivery_estimate import (
    DEFAULT_CUTOFF_HOUR,
    add_business_days,
    estimate,
    is_business_day,
    next_business_day,
    ship_date,
)

DENVER = "America/Denver"
TZ = ZoneInfo(DENVER)


def at(year, month, day, hour):
    return int(datetime(year, month, day, hour, 0, tzinfo=TZ).timestamp())


# 2026-10-01 is a Thursday; 10-03 a Saturday; 10-05 the Monday after.
THU_10AM = at(2026, 10, 1, 10)
THU_4PM = at(2026, 10, 1, 16)
FRI_10AM = at(2026, 10, 2, 10)
FRI_4PM = at(2026, 10, 2, 16)
SAT_10AM = at(2026, 10, 3, 10)


class TheCutoffIsABufferTests(unittest.TestCase):
    """An order placed after it ships the next business day. A tenant who quietly ships same-day then
    beats the estimate, which is the whole point of showing a date."""

    def test_before_the_cutoff_ships_today(self):
        self.assertEqual(ship_date(THU_10AM, tz_name=DENVER).isoformat(), "2026-10-01")

    def test_after_the_cutoff_ships_tomorrow(self):
        self.assertEqual(ship_date(THU_4PM, tz_name=DENVER).isoformat(), "2026-10-02")

    def test_the_hour_is_the_tenants_to_set(self):
        # Some stores cut off at noon. 3pm is a default, not a rule.
        self.assertEqual(ship_date(THU_10AM, tz_name=DENVER, cutoff_hour=9).isoformat(), "2026-10-02")
        self.assertEqual(DEFAULT_CUTOFF_HOUR, 15)

    def test_the_timezone_decides_whose_afternoon_it_is(self):
        """A seller may live in Pacific time and ship from a warehouse in Mountain time. 4pm Denver is
        3pm Los Angeles, which is still the cutoff hour there, so the two disagree by a day."""
        self.assertEqual(ship_date(THU_4PM, tz_name=DENVER).isoformat(), "2026-10-02")
        self.assertEqual(ship_date(THU_4PM, tz_name="America/Los_Angeles").isoformat(), "2026-10-02")
        # An hour earlier they part company: 3pm Denver is 2pm LA, before the LA cutoff.
        three_pm_denver = at(2026, 10, 1, 15)
        self.assertEqual(ship_date(three_pm_denver, tz_name=DENVER).isoformat(), "2026-10-02")
        self.assertEqual(ship_date(three_pm_denver, tz_name="America/Los_Angeles").isoformat(), "2026-10-01")


class WeekendsAreNotShippingDaysTests(unittest.TestCase):
    def test_friday_after_the_cutoff_ships_monday(self):
        self.assertEqual(ship_date(FRI_4PM, tz_name=DENVER).isoformat(), "2026-10-05")

    def test_an_order_placed_on_a_saturday_ships_monday(self):
        self.assertEqual(ship_date(SAT_10AM, tz_name=DENVER).isoformat(), "2026-10-05")

    def test_friday_morning_still_ships_friday(self):
        self.assertEqual(ship_date(FRI_10AM, tz_name=DENVER).isoformat(), "2026-10-02")

    def test_the_weekend_itself(self):
        self.assertFalse(is_business_day(datetime(2026, 10, 3).date()))   # Saturday
        self.assertFalse(is_business_day(datetime(2026, 10, 4).date()))   # Sunday
        self.assertTrue(is_business_day(datetime(2026, 10, 5).date()))    # Monday


class TransitDaysAreCountedNotAddedTests(unittest.TestCase):
    """The measured fact, held as a test. `estimated_days=2` means "by the end of the second BUSINESS
    day", so two business days are counted forward. Adding two calendar days and then pushing off a
    weekend would land on the wrong date for every order placed Thursday or Friday."""

    def test_two_business_days_from_a_thursday_is_monday(self):
        self.assertEqual(add_business_days(datetime(2026, 10, 1).date(), 2).isoformat(), "2026-10-05")

    def test_calendar_addition_would_have_said_saturday(self):
        # The error this guards: Oct 1 + 2 calendar days = Oct 3, a Saturday.
        self.assertNotEqual(add_business_days(datetime(2026, 10, 1).date(), 2).isoformat(), "2026-10-03")

    def test_zero_days_means_today_not_tomorrow(self):
        self.assertEqual(add_business_days(datetime(2026, 10, 1).date(), 0).isoformat(), "2026-10-01")

    def test_next_business_day_leaves_a_weekday_alone(self):
        self.assertEqual(next_business_day(datetime(2026, 10, 1).date()).isoformat(), "2026-10-01")


class TheWholeEstimateTests(unittest.TestCase):
    def test_an_exact_date_when_the_carrier_gives_one(self):
        # Ground Advantage came back 5/5 and Ground Saver 2/2 on real quotes -- min == max is the common
        # case, so a buyer usually gets a day rather than a window.
        out = estimate(THU_10AM, transit_days_min=2, tz_name=DENVER)
        self.assertEqual(out["arrives_on"], "2026-10-05")
        self.assertIsNone(out["arrives_through"])
        self.assertTrue(out["exact"])

    def test_a_range_when_the_carrier_gives_one(self):
        out = estimate(THU_10AM, transit_days_min=5, transit_days_max=7, tz_name=DENVER)
        self.assertEqual((out["arrives_on"], out["arrives_through"]), ("2026-10-08", "2026-10-12"))
        self.assertFalse(out["exact"])

    def test_the_cutoff_moves_the_arrival_too(self):
        after = estimate(THU_4PM, transit_days_min=2, tz_name=DENVER)
        self.assertEqual(after["arrives_on"], "2026-10-06")

    def test_arrives_through_is_None_rather_than_a_repeat(self):
        """A caller choosing between one date and a range should not have to compare two strings."""
        self.assertIsNone(estimate(THU_10AM, transit_days_min=3, transit_days_max=3,
                                   tz_name=DENVER)["arrives_through"])

    def test_a_backwards_range_is_not_a_date_in_the_past(self):
        out = estimate(THU_10AM, transit_days_min=5, transit_days_max=2, tz_name=DENVER)
        self.assertTrue(out["exact"])
        self.assertEqual(out["arrives_on"], "2026-10-08")


class NotKnowingIsAnAnswerTests(unittest.TestCase):
    """An unmeasured product never reached a carrier, so it has no service and no transit days. Inventing
    "5-7 business days" for it is precisely the sentence this module replaced, so `{}` has to travel all
    the way to the caller rather than being filled in with something plausible."""

    def test_no_transit_days_means_no_estimate(self):
        self.assertEqual(estimate(THU_10AM, transit_days_min=None), {})

    def test_no_order_time_means_no_estimate(self):
        self.assertEqual(estimate(None, transit_days_min=2), {})
        self.assertEqual(estimate(0, transit_days_min=2), {})
        self.assertEqual(estimate("not a timestamp", transit_days_min=2), {})

    def test_a_decimal_from_dynamo_is_still_a_number(self):
        from decimal import Decimal

        out = estimate(Decimal(THU_10AM), transit_days_min=Decimal("2"), tz_name=DENVER)
        self.assertEqual(out["arrives_on"], "2026-10-05")

    def test_a_booleans_days_are_not_days(self):
        self.assertEqual(estimate(THU_10AM, transit_days_min=True), {})


class AMissingTimezoneDatabaseDegradesLoudlyTests(unittest.TestCase):
    """`zoneinfo` is standard library but needs a tz database, and nothing in this codebase depended on
    one before. A missing database must not crash a thank-you page and must not silently shift every
    estimate by the offset either."""

    def test_an_unknown_zone_falls_back_rather_than_raising(self):
        with self.assertLogs("stripe_link.domain.delivery_estimate", level="WARNING") as logs:
            out = estimate(THU_10AM, transit_days_min=2, tz_name="Mars/Olympus_Mons")
        self.assertTrue(out)
        self.assertIn("falling back to UTC", "".join(logs.output))

    def test_utc_needs_no_database_at_all(self):
        with self.assertNoLogs("stripe_link.domain.delivery_estimate", level="WARNING"):
            self.assertTrue(estimate(THU_10AM, transit_days_min=2, tz_name="UTC"))
