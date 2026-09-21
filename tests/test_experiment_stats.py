"""Reading an A/B result honestly (plans/AB_TESTING.md A3).

Nothing here gates or pauses anything: "enough evidence" is the tenant's judgement. These tests are mostly
about the cases where the right answer is "we cannot say" -- that is where a stats helper does its damage,
by returning a confident number instead.
"""
import unittest

from stripe_link.domain.experiment_stats import (
    days_remaining,
    summarize,
    verdict,
    views_needed_per_arm,
    z_score,
)


def arm(page_id, views, conversions, revenue=0):
    return {"page_id": page_id, "views": views, "conversions": conversions, "revenue": revenue}


class CannotSayTests(unittest.TestCase):
    def test_no_views_is_not_a_z_of_zero(self):
        # "no evidence either way" and "measured no difference" are different statements.
        self.assertIsNone(z_score(arm("a", 0, 0), arm("b", 100, 5)))
        self.assertIsNone(z_score(arm("a", 100, 5), arm("b", 0, 0)))

    def test_nobody_converted_yet(self):
        self.assertIsNone(z_score(arm("a", 500, 0), arm("b", 500, 0)))

    def test_everybody_converted(self):
        self.assertIsNone(z_score(arm("a", 10, 10), arm("b", 10, 10)))

    def test_insufficient_is_a_real_verdict(self):
        self.assertEqual(verdict(None), "insufficient")

    def test_no_difference_has_no_finite_sample_target(self):
        # delta == 0 needs an infinite sample; rendering that as a number would read as "nearly done".
        self.assertIsNone(views_needed_per_arm(arm("a", 1000, 50), arm("b", 1000, 50)))


class VerdictTests(unittest.TestCase):
    def test_a_big_gap_on_big_traffic_is_clear(self):
        z = z_score(arm("a", 5000, 250), arm("b", 5000, 400))
        self.assertEqual(verdict(z), "clear")

    def test_the_same_gap_on_tiny_traffic_is_not(self):
        # The point of the whole exercise: 5% vs 8% is the same LIFT, and means nothing at n=50.
        z = z_score(arm("a", 50, 2), arm("b", 50, 4))
        self.assertIn(verdict(z), ("too_close", "insufficient"))

    def test_a_dead_heat_is_too_close(self):
        self.assertEqual(verdict(z_score(arm("a", 2000, 100), arm("b", 2000, 102))), "too_close")

    def test_a_variant_that_is_clearly_worse_is_still_clear(self):
        # Direction is not the question; "is the gap bigger than the noise" is.
        z = z_score(arm("a", 5000, 400), arm("b", 5000, 250))
        self.assertEqual(verdict(z), "clear")
        self.assertLess(z, 0)


class HowMuchLongerTests(unittest.TestCase):
    def test_a_smaller_difference_needs_more_traffic(self):
        big = views_needed_per_arm(arm("a", 1000, 50), arm("b", 1000, 100))
        small = views_needed_per_arm(arm("a", 1000, 50), arm("b", 1000, 55))
        self.assertLess(big, small)

    def test_already_past_the_target_reads_as_zero_not_negative(self):
        self.assertEqual(days_remaining(views_so_far=10_000, needed_per_arm=500, days_elapsed=5), 0.0)

    def test_it_is_arithmetic_on_the_observed_rate(self):
        # 100 views in 2 days = 50/day; 150 more needed -> 3 days.
        self.assertAlmostEqual(days_remaining(100, 250, 2.0), 3.0)

    def test_no_elapsed_time_yields_no_estimate(self):
        self.assertIsNone(days_remaining(100, 250, 0.0))

    def test_no_target_yields_no_estimate(self):
        self.assertIsNone(days_remaining(100, None, 5.0))


class SummarizeTests(unittest.TestCase):
    def test_the_control_is_not_compared_with_itself(self):
        rows = summarize([arm("ctl", 1000, 50), arm("v", 1000, 80)], "ctl", days_elapsed=4)
        self.assertEqual([row["page_id"] for row in rows], ["v"])

    def test_lift_is_relative_to_the_control(self):
        rows = summarize([arm("ctl", 1000, 50), arm("v", 1000, 100)], "ctl", days_elapsed=4)
        self.assertAlmostEqual(rows[0]["lift"], 1.0)

    def test_no_control_rate_means_no_lift_rather_than_infinity(self):
        rows = summarize([arm("ctl", 1000, 0), arm("v", 1000, 40)], "ctl", days_elapsed=4)
        self.assertIsNone(rows[0]["lift"])

    def test_an_unknown_control_produces_nothing(self):
        self.assertEqual(summarize([arm("a", 10, 1)], "missing"), [])

    def test_every_arm_is_reported_even_when_it_cannot_be_judged(self):
        # A variant with no traffic must still appear, or it silently vanishes from the tenant's results.
        rows = summarize([arm("ctl", 1000, 50), arm("v", 0, 0)], "ctl", days_elapsed=4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "insufficient")

    def test_revenue_never_gets_a_verdict(self):
        # These are proportion tests; revenue per view has a much wider distribution. Claiming significance
        # on it with this machinery would be inventing a result.
        rows = summarize([arm("ctl", 1000, 50, revenue=500_00), arm("v", 1000, 50, revenue=5_000_00)], "ctl", 4)
        self.assertEqual(rows[0]["verdict"], "too_close")
        self.assertNotIn("revenue_verdict", rows[0])
