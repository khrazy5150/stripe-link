"""A catch-all zone that could price no country on earth.

The tenant's zones read "United States" and "Everywhere else", both rating live. The author tried to buy
from outside the US and could not (2026-10-04): *"someone in Mexico, Canada, or the European Union cannot
purchase the item when the system says that they can."*

Two layers, and fixing only the first moves the lie later rather than removing it:

1. `allowed_countries` dropped the catch-all, so the page's dropdown offered the United States alone.
2. Even reaching the carrier, every international service was filtered out. `enabled_services` is populated
   by adopting rows from the Shipping screen's rate preview; a tenant previews the address they ship to
   most; so a US seller's adopted list is US-domestic by construction, and an international quote returns
   entirely different service tokens. Narrowing by that list leaves nothing, every time, for every tenant.

Measured against live Shippo while diagnosing it: the carrier returned 11 services for Denver and 4
survived narrowing; it returned 3 each for Toronto, Mexico City and Berlin, and 0 survived.
"""
import pathlib
import re
import unittest

from stripe_link.domain.shipping_charges import resolve_options
from stripe_link.domain.shipping_countries import ISO_COUNTRIES, shippable_countries
from stripe_link.domain.shipping_rating import apply_tenant_services, carrier_menu

ROOT = pathlib.Path(__file__).resolve().parents[1]

DOMESTIC = [{"service_token": "usps_ground_advantage", "label": "Ground Advantage"},
            {"service_token": "ups_ground_saver", "label": "Ground Saver"}]
# What Shippo really returns for a US -> anywhere-abroad parcel.
INTERNATIONAL = [
    {"service_token": "usps_first_class_package_international_service",
     "service": "First-Class Package International", "amount": 2899, "carrier": "usps"},
    {"service_token": "usps_priority_mail_international",
     "service": "Priority Mail International", "amount": 5214, "carrier": "usps"},
    {"service_token": "usps_priority_mail_express_international",
     "service": "Priority Mail Express International", "amount": 7812, "carrier": "usps"},
]
OFFER = {"shipping": {"eligible": True}, "items": [{"product_id": "p1", "quantity": 1}]}


def config(*zones):
    return {"enabled_services": DOMESTIC, "zones": list(zones)}


US_ZONE = {"destinations": [{"country": "US"}], "rule": {"type": "live"}}
CATCH_ALL = {"destinations": [{"country": "*"}], "rule": {"type": "live"}}
GB_ZONE = {"destinations": [{"country": "GB"}], "rule": {"type": "live"}}


class TheNarrowingLeftNothingTests(unittest.TestCase):
    def test_no_adopted_service_survives_an_international_quote(self):
        # The measurement the whole fix rests on, held as a fact rather than a memory.
        self.assertEqual(apply_tenant_services(INTERNATIONAL, DOMESTIC), [])


class ACatchAllFallsBackToTheCarriersMenuTests(unittest.TestCase):
    """Where the tenant expressed no preference, the carrier's menu is the honest answer, and the
    alternative is refusing a sale the tenant asked for."""

    def test_a_catch_all_destination_is_priced(self):
        out = resolve_options(OFFER, config(US_ZONE, CATCH_ALL), country="DE",
                              live_options=INTERNATIONAL)
        self.assertEqual(out["needs"], "")
        self.assertEqual(len(out["options"]), 3)

    def test_it_offers_the_cheapest_first(self):
        out = resolve_options(OFFER, config(US_ZONE, CATCH_ALL), country="MX",
                              live_options=INTERNATIONAL)
        self.assertEqual([o["amount"] for o in out["options"]], [2899, 5214, 7812])

    def test_every_option_is_named_in_the_carriers_own_words(self):
        # `normalize_option` DROPS a nameless option, and a dropped option is a service the buyer is never
        # offered -- the silent-zero pattern. The carrier's own service name is the fallback label.
        out = resolve_options(OFFER, config(US_ZONE, CATCH_ALL), country="CA",
                              live_options=INTERNATIONAL)
        self.assertEqual([o["label"] for o in out["options"]],
                         ["First-Class Package International", "Priority Mail International",
                          "Priority Mail Express International"])

    def test_a_NAMED_zone_still_reports_a_settings_gap(self):
        """There the tenant chose the country and had every chance to adopt services for it, so an empty
        result is a real gap with a real answer in the Shipping screen. Quietly widening it would be the
        overnight-shipping problem the narrowing rule exists to stop."""
        out = resolve_options(OFFER, config(GB_ZONE), country="GB", live_options=INTERNATIONAL)
        self.assertEqual(out["needs"], "services")
        self.assertEqual(out["options"], [])

    def test_the_tenants_own_choice_still_wins_where_they_made_one(self):
        # Domestic is unchanged: the adopted services match, so the fallback never runs and the tenant's
        # labels are what the buyer reads.
        domestic_rates = [{"service_token": "usps_ground_advantage", "service": "USPS Ground Advantage",
                           "amount": 611},
                          {"service_token": "ups_next_day_air", "service": "Next Day Air", "amount": 2504}]
        out = resolve_options(OFFER, config(US_ZONE, CATCH_ALL), country="US",
                              live_options=domestic_rates)
        self.assertEqual([o["label"] for o in out["options"]], ["Ground Advantage"])

    def test_carrier_menu_keeps_the_token_so_the_label_can_be_bought(self):
        menu = carrier_menu(INTERNATIONAL)
        self.assertEqual([o["service_token"] for o in menu],
                         [o["service_token"] for o in INTERNATIONAL])


class TheCountryListsMustAgreeTests(unittest.TestCase):
    """The buyer picks on our page and pays at Stripe. A code in one list and not the other is a country
    they can choose and then cannot enter an address for."""

    def test_python_and_the_dashboard_hold_the_same_codes(self):
        js = (ROOT / "dashboard" / "src" / "utils" / "countries.js").read_text()
        block = js.split("const CODES = [", 1)[1].split("];", 1)[0]
        self.assertEqual(sorted(set(re.findall(r'"([A-Z]{2})"', block))), sorted(ISO_COUNTRIES))

    def test_the_codes_are_unique_and_sorted(self):
        self.assertEqual(list(ISO_COUNTRIES), sorted(set(ISO_COUNTRIES)))

    def test_the_countries_stripe_refuses_are_excluded(self):
        self.assertNotIn("CU", shippable_countries())
        self.assertLess(len(shippable_countries()), len(ISO_COUNTRIES))
