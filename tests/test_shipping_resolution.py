"""Tenant zones -> offer override -> what the buyer may choose from.

plans/SHIPPING_ELEMENT.md phase 2. Before this, `offer.shipping.options[]` was the only place buyer-facing
shipping lived, so a tenant with forty offers configured it forty times. Now the tenant says it once in their
zones and an offer only DEPARTS from that — the default-then-override shape `domain/refund_policy.py` uses,
for the same reason: two places holding one fact is how they come to disagree.

The load-bearing tests here are the ones about what "no options" MEANS. Empty options with a `needs` is "not
answerable yet", never "free" — a caller that renders it as free ships for nothing.
"""
import unittest

from stripe_link.domain.shipping_charges import (
    CHARGED,
    FREE,
    offer_override,
    resolve_options,
    ships_at_all,
)

SERVICES = [
    {"service_token": "ground", "label": "Ground", "transit_days_min": 5, "transit_days_max": 7},
    {"service_token": "overnight", "label": "Overnight", "transit_days_min": 1, "transit_days_max": 1},
]
TENANT = {
    "enabled_services": SERVICES,
    "zones": [
        {"name": "US", "destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}},
        {"name": "CA", "destinations": [{"country": "CA"}],
         "rule": {"type": "flat", "amount": 1299, "services": ["ground"]}},
        {"name": "Rest", "destinations": [{"country": "*"}], "rule": {"type": "live"}},
    ],
}
# The amount a caller works out from packing (`packed_box_price`), not a box document: `resolve_options`
# is pure and knows nothing about boxes.
BOX_PRICE = 899
DOMESTIC_ONLY = {"enabled_services": [{"service_token": "ground", "label": "Ground"}],
                 "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "flat", "amount": 500}}]}


def resolve(offer=None, tenant=None, country="US", **kwargs):
    return resolve_options(offer or {}, tenant if tenant is not None else TENANT, country=country, **kwargs)


class ThePrecedenceChain(unittest.TestCase):
    def test_the_zone_is_the_normal_path(self):
        result = resolve(country="CA")
        self.assertEqual(result["source"], "zone")
        self.assertEqual([o["amount"] for o in result["options"]], [1299])

    def test_an_explicit_offer_table_still_wins(self):
        """It is what stripe_shipping_options already reads, it is deployed, and a tenant who hand-built one
        meant it."""
        offer = {"shipping": {"options": [{"label": "My rate", "amount": 700}]}}
        result = resolve(offer, box_amount=BOX_PRICE)
        self.assertEqual(result["source"], "offer_options")
        self.assertEqual([o["label"] for o in result["options"]], ["My rate"])

    def test_an_override_replaces_the_zone_rule(self):
        for kind, expected in (("free", 0), ("flat", 500)):
            offer = {"shipping": {"override": {"type": kind, "amount": 500}}}
            result = resolve(offer, country="CA")
            self.assertEqual(result["source"], "offer_override", kind)
            self.assertEqual(result["options"][0]["amount"], expected, kind)

    def test_an_override_cannot_grant_a_service_the_tenant_lacks(self):
        """Which speeds a tenant can ship is a CAPABILITY. The zone narrows Canada to ground, and an offer
        override changes the price, not what the carrier will carry."""
        offer = {"shipping": {"override": {"type": "flat", "amount": 500}}}
        result = resolve(offer, country="CA")
        self.assertEqual([o["service_token"] for o in result["options"]], ["ground"])

    def test_calculated_forces_rating_where_the_zone_said_flat(self):
        offer = {"shipping": {"override": {"type": "calculated"}}}
        self.assertEqual(resolve(offer, country="CA")["needs"], "carrier")
        # With a box price in hand it prices rather than asking for a carrier.
        priced = resolve(offer, country="CA", box_amount=BOX_PRICE)
        self.assertEqual(priced["needs"], "")
        self.assertEqual(priced["options"][0]["amount"], BOX_PRICE)

    def test_an_unknown_override_type_is_ignored_not_guessed(self):
        offer = {"shipping": {"override": {"type": "telepathy"}}}
        self.assertEqual(resolve(offer, country="CA")["source"], "zone")
        self.assertEqual(offer_override(offer), {})


class NoOptionsDoesNotMeanFree(unittest.TestCase):
    """The load-bearing distinction. A caller that treats these as free ships for nothing."""

    def test_a_live_zone_with_no_carrier_says_so(self):
        result = resolve(country="GB")
        self.assertEqual(result["options"], [])
        self.assertEqual(result["needs"], "carrier")
        self.assertEqual(result["mode"], CHARGED)

    def test_a_box_zone_with_no_priced_box_says_so(self):
        result = resolve(country="US")
        self.assertEqual(result["needs"], "box_price")
        self.assertEqual(result["options"], [])

    def test_the_same_zone_prices_once_the_box_has_a_price(self):
        result = resolve(country="US", box_amount=BOX_PRICE)
        self.assertEqual(result["needs"], "")
        self.assertEqual([o["amount"] for o in result["options"]], [899, 899])

    def test_an_unserved_destination_has_an_EMPTY_mode(self):
        """Not `free`. A caller switching on mode alone would read free as 'charge nothing and ship it',
        which for an unserved country means posting a parcel somewhere the tenant never agreed to send one."""
        result = resolve(tenant=DOMESTIC_ONLY, country="GB")
        self.assertEqual(result["mode"], "")
        self.assertEqual(result["source"], "unserved")
        self.assertEqual(result["needs"], "zone")

    def test_an_offer_that_does_not_ship_has_an_EMPTY_mode_too(self):
        """No shipping is a different fact from free shipping."""
        result = resolve({"shipping": {"eligibility": "none"}}, box_amount=BOX_PRICE)
        self.assertEqual(result["mode"], "")
        self.assertEqual(result["source"], "none")
        self.assertEqual(result["options"], [])

    def test_a_genuinely_free_zone_DOES_say_free(self):
        tenant = {"enabled_services": [{"service_token": "ground", "label": "Ground"}],
                  "zones": [{"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}
        result = resolve(tenant=tenant, country="GB")
        self.assertEqual(result["mode"], FREE)
        self.assertEqual(result["options"][0]["amount"], 0)
        self.assertEqual(result["needs"], "")


class Eligibility(unittest.TestCase):
    def test_absent_means_it_ships(self):
        self.assertTrue(ships_at_all({}))
        self.assertTrue(ships_at_all({"shipping": {}}))
        self.assertTrue(ships_at_all(None))

    def test_explicit_none_wins_over_the_tenants_zones(self):
        self.assertFalse(ships_at_all({"shipping": {"eligibility": "none"}}))

    def test_it_beats_even_an_explicit_options_table(self):
        """A tenant who says this offer does not ship means it, whatever else is configured."""
        offer = {"shipping": {"eligibility": "none", "options": [{"label": "Ground", "amount": 700}]}}
        self.assertEqual(resolve(offer)["options"], [])


class OneOptionPerService(unittest.TestCase):
    def test_a_flat_zone_charges_the_same_for_every_speed(self):
        """Differential pricing per speed is what live and flat_rate_box are for."""
        result = resolve(country="US", box_amount=BOX_PRICE)
        self.assertEqual({o["amount"] for o in result["options"]}, {899})
        self.assertEqual([o["label"] for o in result["options"]], ["Ground", "Overnight"])

    def test_transit_days_travel_from_the_tenants_service(self):
        option = resolve(country="US", box_amount=BOX_PRICE)["options"][0]
        self.assertEqual(option["transit_days_min"], 5)
        self.assertEqual(option["transit_days_max"], 7)

    def test_a_priced_zone_with_no_services_still_charges(self):
        """The buyer is simply not offered a choice of speed."""
        tenant = {"zones": [{"destinations": [{"country": "*"}], "rule": {"type": "flat", "amount": 800}}]}
        result = resolve(tenant=tenant, country="US")
        self.assertEqual([(o["label"], o["amount"]) for o in result["options"]], [("Shipping", 800)])

    def test_never_more_than_stripe_accepts(self):
        many = [{"service_token": f"s{i}", "label": f"Service {i}"} for i in range(9)]
        tenant = {"enabled_services": many,
                  "zones": [{"destinations": [{"country": "*"}], "rule": {"type": "flat", "amount": 100}}]}
        self.assertEqual(len(resolve(tenant=tenant, country="US")["options"]), 5)


if __name__ == "__main__":
    unittest.main()
