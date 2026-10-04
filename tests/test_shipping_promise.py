"""What the thank-you page tells a buyer about their parcel.

plans/THANK_YOU_PAGE.md P2. It used to say "Free Shipping — your order will arrive within 5–7 business
days" to everyone, including an order that had just paid $39.59 to Vancouver. Both halves were false at
once, and neither could ever have been true for every buyer.

One place builds the sentence, because the element and the `{{arrival}}` token in a card both show the
same date and two implementations of one answer start disagreeing within a release.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from stripe_link.domain.shipping_promise import (
    arrival_phrase,
    promise_for,
    promise_sentence,
    service_label_for,
    transit_days_for,
)

DENVER = "America/Denver"
THU_10AM = int(datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo(DENVER)).timestamp())

QUOTE = {"options": [
    {"service_token": "usps_ground_advantage", "carrier": "USPS", "label": "Ground Advantage",
     "transit_days_min": 5, "transit_days_max": 5},
    {"service_token": "ups_ground_saver", "carrier": "UPS", "label": "Ground Saver",
     "transit_days_min": 2, "transit_days_max": 4},
]}
PAID_ORDER = {"created_at": THU_10AM, "shipping_amount": 611,
              "shipping_quote": {"service_token": "usps_ground_advantage"}}


def promise(order=None, quote=QUOTE, **kw):
    return promise_for(order or PAID_ORDER, quote, tz_name=DENVER, **kw)


class ItReadsTheServiceTheBuyerActuallyChoseTests(unittest.TestCase):
    def test_transit_days_come_from_that_option(self):
        self.assertEqual(transit_days_for(QUOTE, "ups_ground_saver"), (2, 4))

    def test_a_service_not_in_the_quote_borrows_nobody_elses(self):
        """An order placed before this shipped, or a quote that expired, has no days to promise."""
        self.assertEqual(transit_days_for(QUOTE, "fedex_overnight"), (None, None))
        self.assertEqual(transit_days_for(None, "usps_ground_advantage"), (None, None))

    def test_the_label_is_what_a_buyer_would_recognise(self):
        self.assertEqual(service_label_for(QUOTE, "usps_ground_advantage"), "USPS Ground Advantage")


class TheSentenceTests(unittest.TestCase):
    def test_an_exact_date_when_the_carrier_gives_one(self):
        self.assertEqual(promise_sentence(promise()), "Estimated to arrive Thursday, October 8.")

    def test_a_range_when_it_does_not(self):
        order = dict(PAID_ORDER, shipping_quote={"service_token": "ups_ground_saver"})
        # Thursday + 2 business days is Monday the 5th (Fri, Mon); + 4 is Wednesday the 7th.
        self.assertEqual(promise_sentence(promise(order)),
                         "Estimated arrival between Monday, October 5 and Wednesday, October 7.")

    def test_the_day_of_the_week_is_spelled_out(self):
        """A buyer reads a weekday faster than a number, and it is the day that tells them whether they
        will be home."""
        self.assertIn("Thursday", promise_sentence(promise()))

    def test_no_date_promises_none(self):
        # The sentence this module exists to delete is the one that invents a window.
        free = {"created_at": THU_10AM, "shipping_amount": 0}
        self.assertEqual(promise_sentence(promise(free, quote=None)),
                         "We'll email tracking details as soon as it ships.")

    def test_an_empty_promise_says_nothing_at_all(self):
        self.assertEqual(promise_sentence({}), "")
        self.assertEqual(promise_sentence(None), "")


class TheTokenReadsInsideATenantsOwnSentenceTests(unittest.TestCase):
    """It substitutes into "Wait for your package to arrive {{arrival}}." — so it carries its own
    preposition, and falls back to a phrase rather than a blank that would leave the clause hanging."""

    def test_it_carries_its_preposition(self):
        self.assertEqual(arrival_phrase(promise()), "on Thursday, October 8")

    def test_a_range_reads_as_one(self):
        order = dict(PAID_ORDER, shipping_quote={"service_token": "ups_ground_saver"})
        self.assertTrue(arrival_phrase(promise(order)).startswith("between "))

    def test_without_a_date_the_sentence_still_finishes(self):
        free = {"created_at": THU_10AM, "shipping_amount": 0}
        phrase = arrival_phrase(promise(free, quote=None))
        self.assertTrue(phrase and not phrase.startswith("on "))
        self.assertIn("soon", phrase)

    def test_it_never_returns_an_empty_string(self):
        for value in ({}, None, {"has_date": False}):
            self.assertTrue(arrival_phrase(value))


class WhenItMaySayFreeTests(unittest.TestCase):
    """Exactly three situations and no others (author, 2026-10-04): nothing could be rated, the tenant
    chose a free zone, or it is not a physical product — and the third shows no element at all."""

    def test_a_charged_order_is_not_free(self):
        self.assertEqual(promise()["cost"], "paid")
        self.assertEqual(promise()["amount"], 611)

    def test_an_unrateable_parcel_was_free_TO_THE_BUYER(self):
        # "Free" here is the buyer's truth, not the tenant's cost: an unmeasured parcel really did cost
        # them nothing, whatever it cost the seller.
        unmeasured = {"created_at": THU_10AM, "shipping_amount": 0}
        self.assertEqual(promise(unmeasured, quote=None)["cost"], "free")

    def test_a_free_zone_is_free(self):
        free_zone = {"created_at": THU_10AM, "shipping_amount": 0,
                     "shipping_quote": {"service_token": "usps_ground_advantage"}}
        out = promise(free_zone)
        self.assertEqual(out["cost"], "free")
        # ...and it still gets a date, because a free zone was still rated against a real service.
        self.assertTrue(out["has_date"])

    def test_a_non_physical_order_shows_NOTHING(self):
        """A thank-you page that reassures someone about a delivery they are not expecting is worse than
        one that says nothing."""
        self.assertEqual(promise(requires_shipping=False), {})
        self.assertEqual(promise_sentence(promise(requires_shipping=False)), "")


class TheOrderCARRIESThePromiseTests(unittest.TestCase):
    """Computed once, at order time, and stored. Not recomputed when the thank-you page is viewed: the
    buyer was told a date, and that date must not quietly change because the tenant edited their cutoff
    next week — or shift under them on a page refresh."""

    def _attach(self, order, *, quote=QUOTE, business=None):
        from handlers.stripe_webhook import attach_delivery_promise

        class Quotes:
            def get(self, _tenant, _id):
                return quote

        class Profiles:
            def get(self, tenant_id, user_id):
                return {"business": business} if business is not None else None

        attach_delivery_promise(order, tenant_id="t1", mode="test",
                                user_profiles_repo=Profiles(), quotes_repo=Quotes())
        return order

    def _order(self, **over):
        base = {"order_id": "order_cs_1", "created_at": THU_10AM, "shipping_amount": 611,
                "shipping_address": {"country": "US"},
                "shipping_quote": {"quote_id": "shq_1", "service_token": "usps_ground_advantage"}}
        base.update(over)
        return base

    def test_it_lands_on_the_order(self):
        order = self._attach(self._order(), business={"timezone": DENVER})
        self.assertEqual(order["delivery_estimate"]["arrives_on"], "2026-10-08")
        self.assertEqual(order["delivery_estimate"]["service"], "USPS Ground Advantage")

    def test_the_tenants_timezone_decides_the_cutoff(self):
        """4pm in Denver is past a 15:00 cutoff; the same instant in Los Angeles is 3pm, also past it —
        but at 3pm Denver the two part company, which is the whole reason the setting exists."""
        three_pm_denver = int(datetime(2026, 10, 1, 15, 0, tzinfo=ZoneInfo(DENVER)).timestamp())
        denver = self._attach(self._order(created_at=three_pm_denver), business={"timezone": DENVER})
        pacific = self._attach(self._order(created_at=three_pm_denver),
                               business={"timezone": "America/Los_Angeles"})
        self.assertNotEqual(denver["delivery_estimate"]["ships_on"],
                            pacific["delivery_estimate"]["ships_on"])

    def test_the_tenants_cutoff_hour_is_honoured(self):
        early = self._attach(self._order(), business={"timezone": DENVER, "shipping_cutoff_hour": 9})
        self.assertEqual(early["delivery_estimate"]["ships_on"], "2026-10-02")

    def test_an_order_with_no_address_gets_NOTHING(self):
        # Nothing shipped: no parcel, no promise, and the renderer then shows no element.
        order = self._attach(self._order(shipping_address=None, shipping_quote=None))
        self.assertNotIn("delivery_estimate", order)

    def test_a_missing_profile_still_produces_an_estimate(self):
        # Defaults (UTC, 15:00). A day that may not be the tenant's beats no date at all.
        order = self._attach(self._order(), business=None)
        self.assertIn("delivery_estimate", order)

    def test_an_expired_quote_leaves_a_dateless_promise(self):
        """The order still shipped and the buyer still paid, so the element renders -- it just says
        tracking is coming instead of inventing a window."""
        order = self._attach(self._order(), quote={})
        self.assertFalse(order["delivery_estimate"]["has_date"])
        self.assertEqual(order["delivery_estimate"]["cost"], "paid")

    def test_a_broken_lookup_never_costs_a_sale(self):
        from handlers.stripe_webhook import attach_delivery_promise

        class Exploding:
            def get(self, *a, **k):
                raise RuntimeError("dynamo down")

        order = self._order()
        attach_delivery_promise(order, tenant_id="t1", mode="test",
                                user_profiles_repo=Exploding(), quotes_repo=Exploding())
        self.assertNotIn("delivery_estimate", order)   # and no exception escaped
