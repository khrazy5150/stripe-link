"""Sabbath mode — the sundown maths and the closure window (plans/TODO.md "Sabbath mode").

The solar routine is the part that cannot be "roughly right": a store closing at the wrong time is the
whole feature failing, visibly, to the one tenant who cares most about it. So the reference cases below
are real places on real dates, checked against published sunset times, across both hemispheres.
"""
import datetime
import unittest
from zoneinfo import ZoneInfo

from stripe_link.domain.sabbath import (DEFAULT_AFTER_MINUTES, DEFAULT_BEFORE_MINUTES,
                                        MAX_BUFFER_MINUTES, clamp_buffer, is_closed, manual_window,
                                        sunset_utc, window)

ST_GEORGE = (37.0965, -113.5684)     # the tenant's own business address
TROMSO = (69.6496, 18.9560)          # inside the Arctic circle
SYDNEY = (-33.8688, 151.2093)        # southern hemisphere, seasons inverted


def _local(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%H:%M")


class TheSunsetMathsTests(unittest.TestCase):
    def test_london_midsummer(self):
        """~21:21 BST in reality. A minute's tolerance is the honest accuracy of this formula."""
        got = sunset_utc(datetime.date(2026, 6, 21), 51.5074, -0.1278)
        self.assertEqual(_local(got, "Europe/London"), "21:22")

    def test_sydney_in_both_seasons(self):
        """Southern hemisphere: December is SUMMER. A formula with a sign error passes the northern
        cases and fails here."""
        summer = sunset_utc(datetime.date(2026, 12, 21), *SYDNEY)
        winter = sunset_utc(datetime.date(2026, 6, 21), *SYDNEY)
        self.assertEqual(_local(summer, "Australia/Sydney"), "20:06")
        self.assertEqual(_local(winter, "Australia/Sydney"), "16:54")
        self.assertGreater(summer.hour % 24, 0)

    def test_the_equator_at_equinox_sets_at_about_six_in_the_evening(self):
        """THE HALF-DAY REGRESSION. J2000.0 is NOON, not midnight; the first version of this returned
        06:12 here — a plausible-looking time that was sunrise. Every other case looked 'about right'
        too, because being twelve hours out is invisible unless you know what noon should be."""
        got = sunset_utc(datetime.date(2026, 3, 20), 0.0, 0.0)
        self.assertEqual(got.strftime("%H:%M"), "18:12")

    def test_summer_sets_later_than_winter_in_the_north(self):
        summer = sunset_utc(datetime.date(2026, 6, 21), *ST_GEORGE)
        winter = sunset_utc(datetime.date(2026, 12, 21), *ST_GEORGE)
        self.assertEqual(_local(summer, "America/Denver"), "20:58")
        self.assertEqual(_local(winter, "America/Denver"), "17:21")

    def test_polar_summer_and_winter_have_NO_sunset(self):
        """None is a real answer, not a failure. The plan calls for the tenant's manual window here, and
        a formula that invented a time would close a store at a moment nobody chose."""
        self.assertIsNone(sunset_utc(datetime.date(2026, 6, 21), *TROMSO))
        self.assertIsNone(sunset_utc(datetime.date(2026, 12, 21), *TROMSO))

    def test_tromso_DOES_set_at_the_equinox(self):
        """The polar case must be seasonal, not a blanket refusal of high latitudes."""
        self.assertIsNotNone(sunset_utc(datetime.date(2026, 9, 21), *TROMSO))

    def test_nonsense_coordinates_return_None_rather_than_raising(self):
        for lat, lon in ((None, None), ("x", 0), (91.0, 0.0), (0.0, 181.0)):
            self.assertIsNone(sunset_utc(datetime.date(2026, 6, 21), lat, lon))


class TheBuffersTests(unittest.TestCase):
    def test_the_shipped_defaults_are_common_practice(self):
        """~18 min before (candle-lighting) and ~40 after (nightfall)."""
        self.assertEqual((DEFAULT_BEFORE_MINUTES, DEFAULT_AFTER_MINUTES), (18, 40))

    def test_out_of_range_is_clamped_not_refused(self):
        """A tenant who types 90 means "as much as you allow"."""
        self.assertEqual(clamp_buffer(90, 18), MAX_BUFFER_MINUTES)
        self.assertEqual(clamp_buffer(-5, 18), 0)

    def test_ZERO_is_a_real_setting_not_an_unset_one(self):
        """Zero on both means the store closes exactly at sundown and reopens exactly at sundown. Read
        as "unset" and replaced by a default, the tenant's explicit choice would be overruled."""
        self.assertEqual(clamp_buffer(0, 18), 0)

    def test_nonsense_falls_back_to_the_default(self):
        self.assertEqual(clamp_buffer("later", 18), 18)
        self.assertEqual(clamp_buffer(None, 40), 40)


class TheWindowTests(unittest.TestCase):
    def _friday(self, hour=12, tz="America/Denver"):
        # 2026-11-06 is a Friday.
        return datetime.datetime(2026, 11, 6, hour, tzinfo=ZoneInfo(tz))

    def test_it_runs_from_friday_sundown_minus_before_to_saturday_sundown_plus_after(self):
        start, end = window(self._friday(), latitude=ST_GEORGE[0], longitude=ST_GEORGE[1],
                            before_minutes=18, after_minutes=40)
        fri = sunset_utc(datetime.date(2026, 11, 6), *ST_GEORGE)
        sat = sunset_utc(datetime.date(2026, 11, 7), *ST_GEORGE)
        self.assertEqual(start, fri - datetime.timedelta(minutes=18))
        self.assertEqual(end, sat + datetime.timedelta(minutes=40))

    def test_it_uses_TWO_sundowns_not_one_plus_24_hours(self):
        """Friday's and Saturday's sundowns differ, by a little near the equinox and much more at high
        latitude. 'Sundown + 24h' would close at the wrong moment every week, drifting with the season."""
        start, end = window(self._friday(), latitude=ST_GEORGE[0], longitude=ST_GEORGE[1],
                            before_minutes=0, after_minutes=0)
        self.assertNotEqual(end - start, datetime.timedelta(hours=24))

    def test_zero_buffers_give_exactly_sundown_to_sundown(self):
        start, end = window(self._friday(), latitude=ST_GEORGE[0], longitude=ST_GEORGE[1],
                            before_minutes=0, after_minutes=0)
        self.assertEqual(start, sunset_utc(datetime.date(2026, 11, 6), *ST_GEORGE))
        self.assertEqual(end, sunset_utc(datetime.date(2026, 11, 7), *ST_GEORGE))

    def test_friday_lunchtime_is_OPEN(self):
        now = self._friday(hour=12)
        start, end = window(now, latitude=ST_GEORGE[0], longitude=ST_GEORGE[1])
        self.assertFalse(is_closed(now, start, end))

    def test_friday_evening_is_CLOSED(self):
        now = self._friday(hour=20)
        start, end = window(now, latitude=ST_GEORGE[0], longitude=ST_GEORGE[1])
        self.assertTrue(is_closed(now, start, end))

    def test_saturday_afternoon_is_CLOSED(self):
        now = datetime.datetime(2026, 11, 7, 14, tzinfo=ZoneInfo("America/Denver"))
        start, end = window(now, latitude=ST_GEORGE[0], longitude=ST_GEORGE[1])
        self.assertTrue(is_closed(now, start, end))

    def test_saturday_night_after_the_buffer_is_OPEN_again(self):
        now = datetime.datetime(2026, 11, 7, 22, tzinfo=ZoneInfo("America/Denver"))
        start, end = window(now, latitude=ST_GEORGE[0], longitude=ST_GEORGE[1])
        self.assertFalse(is_closed(now, start, end))

    def test_a_window_that_runs_past_MIDNIGHT_still_contains_the_small_hours(self):
        """THE LOOK-BACK RULE. At a high latitude the Saturday sundown plus a buffer can land after
        midnight. Searching FORWARD for the next Friday would find next week's Sabbath and report the
        store open during its own closure."""
        tz = ZoneInfo("Europe/Oslo")
        # Late May in Tromso: the sun still sets, but very late.
        friday = datetime.date(2026, 5, 15)
        sat_sundown = sunset_utc(friday + datetime.timedelta(days=1), *TROMSO)
        just_after = (sat_sundown + datetime.timedelta(minutes=30)).astimezone(tz)
        start, end = window(just_after, latitude=TROMSO[0], longitude=TROMSO[1],
                            before_minutes=0, after_minutes=60)
        self.assertTrue(is_closed(just_after, start, end),
                        "the Sabbath that began on Friday is still running")

    def test_a_polar_location_has_no_solar_window(self):
        now = datetime.datetime(2026, 6, 19, 12, tzinfo=ZoneInfo("Europe/Oslo"))
        self.assertIsNone(window(now, latitude=TROMSO[0], longitude=TROMSO[1]))

    def test_mid_week_is_open(self):
        for day in (2, 3, 4, 5):      # Mon-Thu of that week
            now = datetime.datetime(2026, 11, day, 12, tzinfo=ZoneInfo("America/Denver"))
            start, end = window(now, latitude=ST_GEORGE[0], longitude=ST_GEORGE[1])
            self.assertFalse(is_closed(now, start, end), f"2026-11-{day:02d} should be open")


class TheManualWindowTests(unittest.TestCase):
    def test_duration_is_bounded_to_the_length_of_a_sabbath(self):
        now = datetime.datetime(2026, 11, 6, 12, tzinfo=ZoneInfo("Europe/Oslo"))
        _, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=200)
        start, _ = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=200)
        self.assertEqual(end - start, datetime.timedelta(hours=25))
        start, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=1)
        self.assertEqual(end - start, datetime.timedelta(hours=24))

    def test_it_closes_the_store_over_its_window(self):
        tz = ZoneInfo("Europe/Oslo")
        now = datetime.datetime(2026, 11, 6, 19, tzinfo=tz)
        start, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=24)
        self.assertTrue(is_closed(now, start, end))
        self.assertFalse(is_closed(datetime.datetime(2026, 11, 6, 17, tzinfo=tz), start, end))
