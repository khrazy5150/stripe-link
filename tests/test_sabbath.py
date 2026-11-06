"""Sabbath mode — the sundown maths and the closure window (plans/TODO.md "Sabbath mode").

The solar routine is the part that cannot be "roughly right": a store closing at the wrong time is the
whole feature failing, visibly, to the one tenant who cares most about it. So the reference cases below
are real places on real dates, checked against published sunset times, across both hemispheres.
"""
import datetime
import unittest
from zoneinfo import ZoneInfo

from stripe_link.domain.sabbath import (DEFAULT_AFTER_MINUTES, DEFAULT_BEFORE_MINUTES,
                                        MAX_BUFFER_MINUTES, SabbathClosedError, assert_open,
                                        clamp_buffer, config, coordinates, is_closed,
                                        manual_window, sunset_on_local_date, sunset_utc,
                                        validate_manual_window, wall_time, window)

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
    """For places where the sun does not set — above the Arctic Circle, not merely 'far north'.

    Utqiagvik AK (71.3N), Tromso (69.6N), Bodo (67.3N) and Murmansk (69.0N) need this. Anchorage,
    Fairbanks, Oslo, St Petersburg and Reykjavik do NOT: their sun still sets, however briefly.
    """

    OSLO = ZoneInfo("Europe/Oslo")

    def test_duration_is_bounded_to_the_length_of_a_sabbath(self):
        now = datetime.datetime(2026, 11, 6, 12, tzinfo=self.OSLO)
        start, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=200)
        self.assertEqual(end - start, datetime.timedelta(hours=25))
        start, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=1)
        self.assertEqual(end - start, datetime.timedelta(hours=24))

    def test_it_closes_the_store_over_its_window(self):
        now = datetime.datetime(2026, 11, 6, 19, tzinfo=self.OSLO)
        start, end = manual_window(now, weekday=4, hour=18, minute=0, duration_hours=24)
        self.assertTrue(is_closed(now, start, end))
        self.assertFalse(is_closed(datetime.datetime(2026, 11, 6, 17, tzinfo=self.OSLO), start, end))

    def test_the_duration_is_ABSOLUTE_hours_across_a_clock_change(self):
        """Adding a timedelta to an aware datetime does WALL-CLOCK arithmetic: Friday 18:00 + 24h is
        Saturday 18:00 even when the clocks changed in between, which is 23 or 25 real hours. The tenant
        asked for a span of time, and the Sabbath this stands in for is ~24 hours of actual time.

        Norway falls back on 2026-10-25, so this window spans the extra hour."""
        saturday = datetime.datetime(2026, 10, 24, 12, tzinfo=self.OSLO)
        start, end = manual_window(saturday, weekday=5, hour=18, minute=0, duration_hours=24)
        # Compared in UTC on purpose: subtracting two aware datetimes that share a `tzinfo` makes Python
        # ignore it and subtract the WALL CLOCKS, which reports 23 hours for a real 24. That is the same
        # trap `is_closed` converts away, and asserting it the naive way would have "proved" the bug.
        utc = datetime.timezone.utc
        self.assertEqual(end.astimezone(utc) - start.astimezone(utc), datetime.timedelta(hours=24),
                         "24 hours must mean 24 REAL hours")
        # The wall clock therefore differs by an hour, which is the correct consequence.
        self.assertNotEqual(start.strftime("%H:%M"), end.strftime("%H:%M"))

    def test_is_closed_is_not_fooled_by_a_repeated_wall_clock(self):
        """When two aware datetimes share a `tzinfo` Python ignores it and compares WALL CLOCKS, which
        are not monotonic: Norway's 02:00-03:00 happens twice on 2026-10-25.

        The window below ENDS at 02:30 inside that repeat. A moment at 02:15 in the SECOND pass is
        really 01:15 UTC -- 45 minutes AFTER the window closed -- but its wall clock reads earlier, so a
        naive comparison reports the store still shut. The store would stay closed for an extra hour,
        once a year, and only in the autumn.

        (My first attempt at this test used a window ending at 18:00 and passed with the bug present:
        both comparisons agreed there, so it proved nothing. The boundary has to be INSIDE the repeated
        hour for the two readings to differ.)
        """
        start, end = manual_window(datetime.datetime(2026, 10, 24, 12, tzinfo=self.OSLO),
                                   weekday=5, hour=2, minute=30, duration_hours=24)
        second_pass = datetime.datetime(2026, 10, 25, 2, 15, tzinfo=self.OSLO, fold=1)
        self.assertFalse(is_closed(second_pass, start, end),
                         "02:15 in the second pass is 45 minutes after the window closed")
        first_pass = datetime.datetime(2026, 10, 25, 2, 15, tzinfo=self.OSLO, fold=0)
        self.assertTrue(is_closed(first_pass, start, end),
                        "the same wall clock in the FIRST pass is still inside it")

    def test_a_start_time_that_does_not_EXIST_resolves_forward(self):
        """Norway springs forward on 2026-03-29: 02:00 jumps to 03:00, so 02:30 never happens. A closure
        that cannot begin when it was set for should begin as soon as it can, not an hour early."""
        got = wall_time(datetime.date(2026, 3, 29), 2, 30, self.OSLO)
        self.assertEqual(got.astimezone(datetime.timezone.utc).astimezone(self.OSLO), got)
        self.assertGreaterEqual(got.hour, 3, "must land after the gap, not before it")

    def test_an_AMBIGUOUS_start_time_takes_the_earlier_reading(self):
        """On 2026-10-25 Norway's 02:30 happens twice. For a closure START the earlier one closes sooner,
        which is the safe direction: nobody is harmed by shutting a little early."""
        got = wall_time(datetime.date(2026, 10, 25), 2, 30, self.OSLO)
        later = datetime.datetime(2026, 10, 25, 2, 30, tzinfo=self.OSLO, fold=1)
        self.assertLess(got.astimezone(datetime.timezone.utc), later.astimezone(datetime.timezone.utc))

    def test_an_ordinary_time_is_untouched(self):
        got = wall_time(datetime.date(2026, 11, 6), 18, 0, self.OSLO)
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M"), "2026-11-06 18:00")


class TheManualWindowValidatorTests(unittest.TestCase):
    def test_it_accepts_a_complete_setting(self):
        got = validate_manual_window({"weekday": 4, "hour": 18, "minute": 30, "duration_hours": 24.5})
        self.assertEqual(got, {"weekday": 4, "hour": 18, "minute": 30, "duration_hours": 24.5})

    def test_a_half_filled_setting_is_None_and_leaves_the_store_OPEN(self):
        """Closing a shop at a time nobody chose is the one outcome this must never produce."""
        for bad in (None, {}, "friday", {"hour": 18}, {"hour": 99, "minute": 0},
                    {"hour": 18, "minute": 61}, {"hour": "six", "minute": 0},
                    {"weekday": 9, "hour": 18, "minute": 0}):
            self.assertIsNone(validate_manual_window(bad), repr(bad))

    def test_duration_is_clamped_to_a_sabbath(self):
        self.assertEqual(validate_manual_window(
            {"hour": 18, "minute": 0, "duration_hours": 500})["duration_hours"], 25)
        self.assertEqual(validate_manual_window(
            {"hour": 18, "minute": 0, "duration_hours": 2})["duration_hours"], 24)


class ThePolarFallbackTests(unittest.TestCase):
    ARCTIC = {"geo": {"latitude": 69.6496, "longitude": 18.9560}}      # Tromso
    MIDSUMMER = datetime.datetime(2026, 6, 19, 20, tzinfo=ZoneInfo("Europe/Oslo"))

    def test_it_is_used_ONLY_when_the_sun_does_not_set(self):
        """A tenant in Denver who filled it in by accident should still be closed by their real sundown,
        which is the thing they actually observe."""
        profile = {"sabbath": {"enabled": True,
                               "manual": {"weekday": 0, "hour": 3, "minute": 0, "duration_hours": 24}}}
        # Monday 3am would close a Denver store by the MANUAL window; the solar one says Monday is open.
        assert_open(profile, {"geo": {"latitude": ST_GEORGE[0], "longitude": ST_GEORGE[1]}},
                    timezone_name="America/Denver",
                    now=datetime.datetime(2026, 11, 9, 4, tzinfo=ZoneInfo("America/Denver")))

    def test_a_polar_store_closes_on_its_manual_window(self):
        profile = {"sabbath": {"enabled": True,
                               "manual": {"weekday": 4, "hour": 18, "minute": 0, "duration_hours": 24}}}
        with self.assertRaises(SabbathClosedError):
            assert_open(profile, self.ARCTIC, timezone_name="Europe/Oslo", now=self.MIDSUMMER)

    def test_a_polar_store_with_a_BROKEN_manual_window_stays_open(self):
        profile = {"sabbath": {"enabled": True, "manual": {"weekday": 4}}}
        assert_open(profile, self.ARCTIC, timezone_name="Europe/Oslo", now=self.MIDSUMMER)


class TheStoredSettingTests(unittest.TestCase):
    def test_it_is_OFF_unless_explicitly_on(self):
        """Every other reading of a missing value closes someone's store for them."""
        for profile in ({}, None, {"sabbath": {}}, {"sabbath": None}, {"sabbath": "yes"}):
            self.assertFalse(config(profile)["enabled"], repr(profile))

    def test_buffers_default_and_clamp(self):
        got = config({"sabbath": {"enabled": True, "before_minutes": 999, "after_minutes": None}})
        self.assertEqual(got["before_minutes"], MAX_BUFFER_MINUTES)
        self.assertEqual(got["after_minutes"], DEFAULT_AFTER_MINUTES)

    def test_zero_survives_normalization(self):
        got = config({"sabbath": {"enabled": True, "before_minutes": 0, "after_minutes": 0}})
        self.assertEqual((got["before_minutes"], got["after_minutes"]), (0, 0))


class TheCoordinatesTests(unittest.TestCase):
    def test_it_reads_the_sites_geo(self):
        org = {"geo": {"latitude": 37.0965, "longitude": -113.5684}}
        self.assertEqual(coordinates(org), ST_GEORGE)

    def test_half_a_geo_is_no_geo(self):
        """Guessing the missing half would compute a sundown for a place nobody named."""
        self.assertIsNone(coordinates({"geo": {"latitude": 37.0}}))
        self.assertIsNone(coordinates({"geo": {}}))
        self.assertIsNone(coordinates({}))
        self.assertIsNone(coordinates(None))

    def test_a_decimal_from_dynamo_still_reads(self):
        """`isinstance(x, float)` is False for Decimal, and these come back from a stored document."""
        from decimal import Decimal
        got = coordinates({"geo": {"latitude": Decimal("37.0965"), "longitude": Decimal("-113.5684")}})
        self.assertEqual(got, ST_GEORGE)


class AssertOpenTests(unittest.TestCase):
    ORG = {"geo": {"latitude": ST_GEORGE[0], "longitude": ST_GEORGE[1]}}
    ON = {"sabbath": {"enabled": True, "before_minutes": 18, "after_minutes": 40}}

    def _at(self, day, hour):
        return datetime.datetime(2026, 11, day, hour, tzinfo=ZoneInfo("America/Denver"))

    def test_it_closes_during_the_window(self):
        with self.assertRaises(SabbathClosedError) as caught:
            assert_open(self.ON, self.ORG, timezone_name="America/Denver", now=self._at(6, 20))
        self.assertEqual(caught.exception.timezone_name, "America/Denver")
        self.assertGreater(caught.exception.resume_at, self._at(6, 20))

    def test_it_stays_open_outside_it(self):
        assert_open(self.ON, self.ORG, timezone_name="America/Denver", now=self._at(4, 12))

    def test_a_tenant_who_never_enabled_it_is_never_closed(self):
        assert_open({}, self.ORG, timezone_name="America/Denver", now=self._at(6, 20))

    def test_NO_COORDINATES_leaves_the_store_open(self):
        """Fails open on purpose. A store that closed because its Site had no geo would lose sales
        silently; one that stays open when the tenant expected otherwise gets reported."""
        assert_open(self.ON, {}, timezone_name="America/Denver", now=self._at(6, 20))

    def test_a_polar_tenant_with_no_manual_window_stays_open(self):
        org = {"geo": {"latitude": TROMSO[0], "longitude": TROMSO[1]}}
        assert_open(self.ON, org, timezone_name="Europe/Oslo",
                    now=datetime.datetime(2026, 6, 19, 20, tzinfo=ZoneInfo("Europe/Oslo")))

    def test_a_polar_tenant_WITH_a_manual_window_is_closed_by_it(self):
        org = {"geo": {"latitude": TROMSO[0], "longitude": TROMSO[1]}}
        profile = {"sabbath": {"enabled": True,
                               "manual": {"weekday": 4, "hour": 18, "minute": 0, "duration_hours": 24}}}
        with self.assertRaises(SabbathClosedError):
            assert_open(profile, org, timezone_name="Europe/Oslo",
                        now=datetime.datetime(2026, 6, 19, 20, tzinfo=ZoneInfo("Europe/Oslo")))

    def test_a_broken_setting_never_refuses_a_sale(self):
        """The whole module fails toward taking the money."""
        broken = {"sabbath": {"enabled": True, "manual": {"weekday": "friday"}}}
        assert_open(broken, {}, timezone_name="America/Denver", now=self._at(6, 20))


class ATimezoneIsAPoliticalChoiceNotALongitudeTests(unittest.TestCase):
    """Places whose clock is nowhere near their longitude.

    `sunset_utc` answers for the solar day beginning at 00:00 UTC, which lands on the right LOCAL date
    only where the offset roughly matches longitude/15. Kiritimati sits at 157 degrees WEST and keeps
    UTC+14; the Chathams keep +12:45 at 176 west. Computing "Friday's sundown" from the raw date gave
    Saturday's sundown locally, so the store closed Saturday evening and reopened Sunday — one whole day
    late, every week.

    Found 2026-11-05 by running the window in ten countries, NOT by a test: every northern-hemisphere and
    European case was already correct, which is exactly why it survived the first review.
    """

    FAR_EAST = (
        ("Pacific/Kiritimati", 1.8721, -157.4278),      # UTC+14 at 157W
        ("Pacific/Chatham", -43.95, -176.55),           # UTC+12:45
        ("Pacific/Apia", -13.8333, -171.7667),          # UTC+13
    )

    def test_the_window_still_runs_FRIDAY_to_SATURDAY(self):
        for zone, lat, lon in self.FAR_EAST:
            with self.subTest(zone=zone):
                tz = ZoneInfo(zone)
                start, end = window(datetime.datetime(2026, 11, 6, 12, tzinfo=tz),
                                    latitude=lat, longitude=lon)
                self.assertEqual(start.astimezone(tz).strftime("%a"), "Fri")
                self.assertEqual(end.astimezone(tz).strftime("%a"), "Sat")

    def test_sunset_on_local_date_returns_that_LOCAL_date(self):
        for zone, lat, lon in self.FAR_EAST:
            with self.subTest(zone=zone):
                tz = ZoneInfo(zone)
                day = datetime.date(2026, 11, 6)
                got = sunset_on_local_date(day, lat, lon, tz)
                self.assertIsNotNone(got)
                self.assertEqual(got.astimezone(tz).date(), day)

    def test_the_ordinary_cases_are_unchanged(self):
        """The correction must not move a place whose clock already matches its longitude."""
        tz = ZoneInfo("America/Denver")
        self.assertEqual(sunset_on_local_date(datetime.date(2026, 11, 6), *ST_GEORGE, tz),
                         sunset_utc(datetime.date(2026, 11, 6), *ST_GEORGE))

    def test_half_and_quarter_hour_offsets_work(self):
        """India +5:30, Nepal +5:45, Iran +3:30, Lord Howe's 30-MINUTE DST shift."""
        for zone, lat, lon in (("Asia/Kolkata", 19.0760, 72.8777),
                               ("Asia/Kathmandu", 27.7172, 85.3240),
                               ("Asia/Tehran", 35.6892, 51.3890),
                               ("Australia/Lord_Howe", -31.5553, 159.0821)):
            with self.subTest(zone=zone):
                tz = ZoneInfo(zone)
                start, end = window(datetime.datetime(2026, 11, 6, 12, tzinfo=tz),
                                    latitude=lat, longitude=lon)
                self.assertEqual(start.astimezone(tz).strftime("%a"), "Fri")
                self.assertEqual(end.astimezone(tz).strftime("%a"), "Sat")

    def test_jerusalem_matches_published_candle_lighting(self):
        """The most relevant city for this feature. Sundown 2026-11-06 is ~16:47 IST, so candle
        lighting at the 18-minute default is ~16:29."""
        tz = ZoneInfo("Asia/Jerusalem")
        start, _ = window(datetime.datetime(2026, 11, 6, 12, tzinfo=tz),
                          latitude=31.7683, longitude=35.2137, before_minutes=18, after_minutes=40)
        self.assertEqual(start.astimezone(tz).strftime("%H:%M"), "16:29")

    def test_southern_hemisphere_DST_does_not_shift_the_days(self):
        """Santiago and Lord Howe both change clocks on the opposite half of the year."""
        for zone, lat, lon in (("America/Santiago", -33.4489, -70.6693),
                               ("Australia/Lord_Howe", -31.5553, 159.0821)):
            with self.subTest(zone=zone):
                tz = ZoneInfo(zone)
                start, end = window(datetime.datetime(2026, 1, 9, 12, tzinfo=tz),  # a January Friday
                                    latitude=lat, longitude=lon)
                self.assertEqual(start.astimezone(tz).strftime("%a"), "Fri")
                self.assertEqual(end.astimezone(tz).strftime("%a"), "Sat")


class EveryPlaceThatTakesMoneyIsGatedTests(unittest.TestCase):
    """A closure enforced at three of four transaction points is worse than one enforced nowhere: the
    tenant believes their shop is shut while an upsell link quietly keeps selling."""

    PAYING_HANDLERS = ("checkout", "cart_checkout", "upsell", "booking")

    def test_all_four_call_the_shared_gate(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
        for name in self.PAYING_HANDLERS:
            with self.subTest(handler=name):
                source = (root / f"{name}.py").read_text()
                self.assertIn("assert_store_open", source,
                              f"handlers/{name}.py takes money but does not consult the Sabbath gate")

    def test_they_all_return_the_SAME_refusal(self):
        """One module decides the status and the error code, so a buyer who meets this at checkout and
        again on an upsell is not told two different things."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
        for name in self.PAYING_HANDLERS:
            with self.subTest(handler=name):
                source = (root / f"{name}.py").read_text()
                self.assertIn("sabbath_closed_response", source)

    def test_the_refusal_is_503_and_carries_the_resume_moment(self):
        import json
        from stripe_link.sabbath_gate import closed_response
        from stripe_link.domain.sabbath import SabbathClosedError
        resume = datetime.datetime(2026, 11, 7, 17, 26, tzinfo=ZoneInfo("America/Denver"))
        response = closed_response(SabbathClosedError(resume, "America/Denver"))
        self.assertEqual(response["statusCode"], 503)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "store_closed_sabbath")
        self.assertEqual(body["timezone"], "America/Denver")
        self.assertTrue(body["resume_at"].startswith("2026-11-07T17:26"))

    def test_the_gate_runs_AFTER_the_platforms_own_refusals(self):
        """A suspended store reported as merely observing the Sabbath would tell a shopper to come back
        on Sunday to a shop we closed. Checked by source order, because the ordering IS the contract."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
        for name in ("checkout", "cart_checkout", "upsell"):
            with self.subTest(handler=name):
                source = (root / f"{name}.py").read_text()
                self.assertLess(source.index("assert_not_suspended(_profile)"),
                                source.index("assert_store_open(_profile"),
                                f"{name}: the platform's refusals must come first")
