"""Carrier quote retrieval for a BUYER: every parcel, summed, narrowed to what the tenant sells.

plans/LIVE_SHIPPING_RATES.md phase 2. `preview_rates` rates the first parcel because a tenant comparing
boxes wants one box's price. A buyer is quoted for the whole order, so the rules that differ are here.
"""
import unittest

from stripe_link.domain.shipping_charges import resolve_options, stripe_option_payload
from stripe_link.domain.shipping_rating import apply_tenant_services, rate_parcels

OFFER = {"shipping": {"eligible": True}, "items": [{"product_id": "p1"}]}


class FakeProvider:
    """Answers per parcel, so the summing and the every-parcel rule can be driven precisely."""

    def __init__(self, answers, error=None):
        self.answers, self.error, self.calls = answers, error, []

    def rates(self, *, from_address, to_address, parcel):
        self.calls.append(parcel)
        if self.error:
            raise self.error
        return self.answers[len(self.calls) - 1]


def rate(token, amount, days=None, carrier="ups", service="Ground"):
    out = {"service_token": token, "amount": amount, "carrier": carrier, "service": service}
    if days is not None:
        out["estimated_days"] = days
    return out


class RateParcelsTests(unittest.TestCase):
    def test_a_multi_box_order_sums_every_parcel(self):
        # Carriers bill per parcel. Quoting one box's price for a two-box order undercharges by a box.
        provider = FakeProvider([[rate("ups_ground", 900)], [rate("ups_ground", 1100)]])
        result = rate_parcels(provider, from_address={}, to_address={},
                              parcels=[{"weight": 2}, {"weight": 5}])
        self.assertEqual(result["options"][0]["amount"], 2000)
        self.assertEqual(len(provider.calls), 2)

    def test_a_service_only_one_parcel_can_travel_by_is_not_offered(self):
        # Offering the half the carrier quoted would charge for one box and ship two.
        provider = FakeProvider([
            [rate("ups_ground", 900), rate("ups_next_day", 3000)],
            [rate("ups_ground", 1100)],
        ])
        result = rate_parcels(provider, from_address={}, to_address={},
                              parcels=[{"weight": 2}, {"weight": 5}])
        self.assertEqual([o["service_token"] for o in result["options"]], ["ups_ground"])

    def test_the_slowest_parcel_decides_the_estimate(self):
        # The order is not delivered until the last box arrives.
        provider = FakeProvider([[rate("ups_ground", 900, days=2)], [rate("ups_ground", 1100, days=6)]])
        result = rate_parcels(provider, from_address={}, to_address={},
                              parcels=[{"weight": 2}, {"weight": 5}])
        self.assertEqual(result["options"][0]["estimated_days"], 6)

    def test_options_come_back_cheapest_first(self):
        provider = FakeProvider([[rate("b", 1200), rate("a", 500), rate("c", 800)]])
        result = rate_parcels(provider, from_address={}, to_address={}, parcels=[{"weight": 1}])
        self.assertEqual([o["amount"] for o in result["options"]], [500, 800, 1200])

    def test_a_rate_with_no_service_token_is_unusable_and_dropped(self):
        # The token is what a buyer's pick is validated against later and what a label is bought with.
        provider = FakeProvider([[{"amount": 900, "carrier": "ups", "service": "Ground"}]])
        result = rate_parcels(provider, from_address={}, to_address={}, parcels=[{"weight": 1}])
        self.assertEqual(result["options"], [])

    def test_a_carrier_failure_is_returned_not_raised(self):
        # This runs in the BUYER's path. A carrier having a bad minute must not 500 a landing page.
        provider = FakeProvider([], error=RuntimeError("UPS timed out"))
        result = rate_parcels(provider, from_address={}, to_address={}, parcels=[{"weight": 1}])
        self.assertEqual(result["options"], [])
        self.assertIn("UPS timed out", result["error"])

    def test_nothing_to_pack_is_its_own_answer(self):
        self.assertEqual(rate_parcels(FakeProvider([]), from_address={}, to_address={},
                                      parcels=[])["error"], "no_parcels")


class TenantServiceNarrowingTests(unittest.TestCase):
    def test_a_carrier_service_the_tenant_never_adopted_is_not_offered(self):
        options = [rate("ups_ground", 900), rate("fedex_overnight", 4200, carrier="fedex")]
        narrowed = apply_tenant_services(options, [{"service_token": "ups_ground"}])
        self.assertEqual([o["service_token"] for o in narrowed], ["ups_ground"])

    def test_the_tenants_own_words_win_over_the_carriers(self):
        narrowed = apply_tenant_services(
            [rate("ups_ground", 900, service="UPS Ground Saver")],
            [{"service_token": "ups_ground", "label": "Standard delivery"}])
        self.assertEqual(narrowed[0]["label"], "Standard delivery")

    def test_a_live_estimate_becomes_a_single_day_figure(self):
        # "Estimated 4 business days" -- min == max, which is also what Stripe's delivery_estimate wants.
        narrowed = apply_tenant_services([rate("ups_ground", 900, days=4)],
                                         [{"service_token": "ups_ground"}])
        self.assertEqual((narrowed[0]["transit_days_min"], narrowed[0]["transit_days_max"]), (4, 4))

    def test_a_configured_range_fills_in_only_where_the_carrier_gave_none(self):
        narrowed = apply_tenant_services(
            [rate("usps_ga", 718)],
            [{"service_token": "usps_ga", "transit_days_min": 3, "transit_days_max": 5}])
        self.assertEqual((narrowed[0]["transit_days_min"], narrowed[0]["transit_days_max"]), (3, 5))

    def test_a_live_estimate_outranks_a_typed_one(self):
        # Destination-specific beats a figure typed once in settings.
        narrowed = apply_tenant_services(
            [rate("usps_ga", 718, days=2)],
            [{"service_token": "usps_ga", "transit_days_min": 3, "transit_days_max": 5}])
        self.assertEqual((narrowed[0]["transit_days_min"], narrowed[0]["transit_days_max"]), (2, 2))

    def test_no_enabled_services_offers_nothing(self):
        self.assertEqual(apply_tenant_services([rate("ups_ground", 900)], []), [])


class ResolveOptionsLiveBranchTests(unittest.TestCase):
    CONFIG = {
        "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}}],
        "enabled_services": [{"service_token": "ups_ground", "label": "UPS Ground Saver"}],
    }
    LIVE = [rate("ups_ground", 642, days=4), rate("fedex_overnight", 4200, carrier="fedex")]

    def test_a_live_zone_can_finally_be_priced(self):
        result = resolve_options(OFFER, self.CONFIG, country="US", live_options=self.LIVE)
        self.assertEqual(result["needs"], "")
        self.assertEqual(result["options"][0]["amount"], 642)
        self.assertEqual(result["mode"], "charged")

    def test_each_live_service_keeps_its_own_price(self):
        # Unlike a flat zone, where every service shares one amount.
        config = dict(self.CONFIG, enabled_services=[{"service_token": "ups_ground"},
                                                     {"service_token": "usps_ga"}])
        result = resolve_options(OFFER, config, country="US",
                                 live_options=[rate("ups_ground", 642), rate("usps_ga", 718)])
        self.assertEqual(sorted(o["amount"] for o in result["options"]), [642, 718])

    def test_without_rates_it_still_says_needs_carrier(self):
        # The old behaviour, deliberately preserved: no postal code yet, or no carrier connected.
        result = resolve_options(OFFER, self.CONFIG, country="US")
        self.assertEqual((result["options"], result["needs"]), ([], "carrier"))

    def test_rates_that_survive_no_enabled_service_say_so_distinctly(self):
        # Fixed in the Shipping screen, not by connecting a carrier -- so "carrier" would be wrong advice.
        result = resolve_options(OFFER, dict(self.CONFIG, enabled_services=[]),
                                 country="US", live_options=self.LIVE)
        self.assertEqual((result["options"], result["needs"]), ([], "services"))

    def test_a_live_zone_never_renders_as_free(self):
        for live in (None, [], self.LIVE):
            with self.subTest(live=live):
                result = resolve_options(OFFER, dict(self.CONFIG, enabled_services=[]),
                                         country="US", live_options=live)
                self.assertNotEqual(result["mode"], "free")

    def test_the_live_estimate_reaches_stripes_delivery_estimate(self):
        result = resolve_options(OFFER, self.CONFIG, country="US", live_options=self.LIVE)
        payload = stripe_option_payload(result["options"])
        estimate = payload[0]["shipping_rate_data"]["delivery_estimate"]
        self.assertEqual(estimate["minimum"]["value"], 4)
        self.assertEqual(estimate["maximum"]["value"], 4)
