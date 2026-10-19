"""A review belongs to the books its purchase was made in.

The last gap from the mode-decoupling sweep. Reviews are not mode-scoped in storage, so a review written
from a TEST purchase rendered on the LIVE page and was counted in its AggregateRating — a star rating in
the markup Google reads, made partly of purchases that never happened. For a system whose entire value is
that the rating is a true claim about real buyers (plans/REVIEWS.md), that is the one failure that cannot
be taken back.

No backfill was needed: a verified review carries `order_id`, and that id names its checkout session
(`order_cs_live_...`). The mode was always in the data; nothing was reading it.
"""
import unittest

from stripe_link.domain.reviews import aggregate_reviews, in_mode, markup_eligible, review_mode


def review(rating=5, **extra):
    return {"review_id": "r1", "tenant_id": "t1", "status": "approved", "source": "manual",
            "rating": rating, **extra}


class PlacingAReviewTests(unittest.TestCase):
    def test_the_stamp_is_used_when_present(self):
        self.assertEqual(review_mode(review(stripe_mode="test")), "test")

    def test_otherwise_the_order_id_places_it(self):
        """Every review written before the stamp came from an invite, and the invite carried the order."""
        self.assertEqual(review_mode(review(order_id="order_cs_live_abc")), "live")
        self.assertEqual(review_mode(review(order_id="order_cs_test_abc")), "test")

    def test_a_hand_entered_review_with_no_order_cannot_be_placed(self):
        self.assertEqual(review_mode(review()), "")

    def test_rubbish_is_not_a_mode(self):
        self.assertEqual(review_mode(review(stripe_mode="sandbox")), "")


class ThePublishedPageIsStrictTests(unittest.TestCase):
    """What a shopper sees, and what Google reads."""

    ROWS = [review(5, stripe_mode="live"), review(1, stripe_mode="test"), review(3)]

    def test_a_test_review_never_reaches_a_live_page(self):
        self.assertEqual([r["rating"] for r in in_mode(self.ROWS, "live", include_unplaceable=False)], [5])

    def test_nor_a_live_review_a_test_page(self):
        self.assertEqual([r["rating"] for r in in_mode(self.ROWS, "test", include_unplaceable=False)], [1])

    def test_an_unplaceable_review_is_WITHHELD(self):
        """Deliberately the strict direction here: a rating that cannot prove where it came from must not
        be shown to a shopper as if it could."""
        placed = in_mode(self.ROWS, "live", include_unplaceable=False)
        self.assertNotIn(3, [r["rating"] for r in placed])

    def test_the_star_rating_is_computed_from_the_right_set(self):
        """The number in the markup, not just the visible block."""
        live = aggregate_reviews(in_mode(self.ROWS, "live", include_unplaceable=False))
        self.assertEqual(live, {"rating_value": 5.0, "review_count": 1})

    def test_without_the_filter_the_rating_would_be_wrong(self):
        """What the bug actually looked like: one real 5-star purchase reported as 3.0 across three."""
        unfiltered = aggregate_reviews(markup_eligible(self.ROWS))
        self.assertEqual(unfiltered["review_count"], 3)
        self.assertNotEqual(unfiltered["rating_value"], 5.0)


class TheTenantsOwnListIsLenientTests(unittest.TestCase):
    def test_an_unplaceable_review_still_shows_in_the_dashboard(self):
        """Hiding a review a tenant typed in, in the screen they manage reviews from, is a bug report
        waiting to happen — and costs nothing but a moment's confusion."""
        rows = [review(3)]
        self.assertEqual(len(in_mode(rows, "live", include_unplaceable=True)), 1)
        self.assertEqual(len(in_mode(rows, "test", include_unplaceable=True)), 1)

    def test_but_the_other_mode_is_still_filtered_out(self):
        """Lenient about the unknown, not about the known."""
        rows = [review(1, stripe_mode="test")]
        self.assertEqual(in_mode(rows, "live", include_unplaceable=True), [])


if __name__ == "__main__":
    unittest.main()
