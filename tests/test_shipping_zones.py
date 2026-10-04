"""What buyers pay, by destination. Ordered zones, first match wins.

plans/SHIPPING_ELEMENT.md, contract locked by the author 2026-09-30. Country is the V1 granularity, and
`destinations[]` carries an unused `regions` key so subdivisions can be added later without a second field or a
dual-read fallback.

The validation tests carry the weight here, because every rule they enforce protects against a SILENT fault: a
duplicate country is dead config the tenant believes is live, a misplaced catch-all makes later zones
unreachable, and a rule that prices nothing fails at the moment a buyer is deciding.
"""
import unittest

from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_shipping_config,
    validate_shipping_zones,
)
from stripe_link.domain.shipping_zones import (
    offerable_countries,
    ANYWHERE,
    allowed_countries,
    flat_rate_for_box,
    is_catch_all,
    resolved_amount,
    rule_for,
    services_for,
    ships_to,
    zone_countries,
    zone_for,
)

US = {"name": "United States", "destinations": [{"country": "US"}], "rule": {"type": "live"}}
CA = {"name": "Canada", "destinations": [{"country": "CA"}],
      "rule": {"type": "flat", "amount": 1299, "services": ["ground"]}}
ELSEWHERE = {"name": "Everywhere Else", "destinations": [{"country": ANYWHERE}], "rule": {"type": "free"}}

CONFIG = {
    "enabled_services": [
        {"service_token": "ground", "label": "Ground (5-7 days)"},
        {"service_token": "overnight", "label": "Overnight"},
    ],
    "zones": [US, CA, ELSEWHERE],
    "boxes": [{"name": "Medium", "length": 11, "width": 8, "height": 5,
               "template": "usps_medium_flat_rate_box", "flat_rate": {"US": 899, "CA": 1499}}],
}


class Matching(unittest.TestCase):
    def test_the_first_matching_zone_wins(self):
        self.assertEqual(zone_for(CONFIG, "US")["name"], "United States")
        self.assertEqual(zone_for(CONFIG, "CA")["name"], "Canada")

    def test_the_catch_all_takes_everything_else(self):
        self.assertEqual(zone_for(CONFIG, "GB")["name"], "Everywhere Else")
        self.assertEqual(zone_for(CONFIG, "AU")["name"], "Everywhere Else")

    def test_country_codes_are_normalised(self):
        for given in ("us", "US", " us ", "usa"):
            self.assertEqual(zone_for(CONFIG, given)["name"], "United States", given)

    def test_no_zones_means_no_rule(self):
        self.assertEqual(rule_for({}, "US"), {})
        self.assertEqual(rule_for(None, "US"), {})

    def test_an_unlisted_country_with_no_catch_all_is_NOT_served(self):
        """Returning None is a real answer. Inventing 'free' or 'live' on the tenant's behalf would be the
        implicit commercial promise this plan family exists to stop."""
        domestic_only = {"zones": [US]}
        self.assertIsNone(zone_for(domestic_only, "GB"))
        self.assertFalse(ships_to(domestic_only, "GB"))
        self.assertTrue(ships_to(domestic_only, "US"))

    def test_a_catch_all_placed_early_does_not_shadow_a_real_zone(self):
        """The schema requires it last, but a hand-written document must still resolve sensibly rather than
        make every later zone dead."""
        misordered = {"zones": [ELSEWHERE, US]}
        self.assertEqual(zone_for(misordered, "US")["name"], "United States")
        self.assertEqual(zone_for(misordered, "GB")["name"], "Everywhere Else")

    def test_an_unknown_rule_type_is_ignored_not_guessed(self):
        self.assertEqual(rule_for({"zones": [{"destinations": [{"country": "US"}],
                                              "rule": {"type": "telepathy"}}]}, "US"), {})

    def test_zone_countries_and_catch_all_detection(self):
        self.assertEqual(zone_countries(US), ["US"])
        self.assertTrue(is_catch_all(ELSEWHERE))
        self.assertFalse(is_catch_all(US))


class Pricing(unittest.TestCase):
    def test_free_is_zero(self):
        self.assertEqual(resolved_amount(CONFIG, "GB"), 0)

    def test_flat_is_its_amount(self):
        self.assertEqual(resolved_amount(CONFIG, "CA"), 1299)

    def test_live_is_NOT_answerable_from_the_destination(self):
        """None is not zero. A caller treating it as zero ships for free."""
        self.assertIsNone(resolved_amount(CONFIG, "US"))

    def test_flat_rate_box_is_not_answerable_either(self):
        config = {"zones": [{"destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}},
                            ELSEWHERE]}
        self.assertIsNone(resolved_amount(config, "US"))

    def test_an_unserved_destination_has_no_amount(self):
        self.assertIsNone(resolved_amount({"zones": [US]}, "GB"))

    def test_a_box_is_priced_per_country(self):
        box = CONFIG["boxes"][0]
        self.assertEqual(flat_rate_for_box(box, "US"), 899)
        self.assertEqual(flat_rate_for_box(box, "CA"), 1499)

    def test_an_unpriced_country_is_None_not_free(self):
        """An unpriced box is not a free box."""
        self.assertIsNone(flat_rate_for_box(CONFIG["boxes"][0], "GB"))
        self.assertIsNone(flat_rate_for_box({"name": "Plain"}, "US"))

    def test_decimal_box_prices_from_dynamo(self):
        from decimal import Decimal
        self.assertEqual(flat_rate_for_box({"flat_rate": {"US": Decimal("899")}}, "US"), 899)


class ServicesNarrowNeverWiden(unittest.TestCase):
    """The author's rule: a customer must not be able to ask for overnight when the tenant does not ship it."""

    def test_a_zone_with_no_service_list_offers_everything_enabled(self):
        self.assertEqual([s["service_token"] for s in services_for(CONFIG, "US")],
                         ["ground", "overnight"])

    def test_a_zone_narrows_the_set(self):
        self.assertEqual([s["service_token"] for s in services_for(CONFIG, "CA")], ["ground"])

    def test_a_zone_cannot_widen_beyond_enabled_services(self):
        config = dict(CONFIG, zones=[
            {"destinations": [{"country": "US"}],
             "rule": {"type": "live", "services": ["ground", "teleport"]}}, ELSEWHERE])
        self.assertEqual([s["service_token"] for s in services_for(config, "US")], ["ground"])

    def test_no_enabled_services_offers_nothing(self):
        self.assertEqual(services_for({"zones": [US, ELSEWHERE]}, "US"), [])


class AllowedCountriesComeFromTheZones(unittest.TestCase):
    """checkout.py hardcodes US and CA. A tenant who adds a zone must be able to receive that order, or it is a
    rule the tenant wrote and the platform ignored."""

    def test_it_lists_every_named_country(self):
        self.assertEqual(allowed_countries({"zones": [US, CA]}), ["US", "CA"])

    def test_the_catch_all_contributes_nothing_to_STRIPES_list(self):
        """Stripe is handed one set of `shipping_options` BEFORE the buyer picks a country, so a list
        spanning destinations that disagree on price has no correct option in it. Widening this one would
        not open up international selling -- it would turn every catch-all tenant's domestic postage into
        zero, which the unanimity tests caught on the first attempt (2026-10-04)."""
        self.assertEqual(allowed_countries({"zones": [ELSEWHERE]}), [])

    def test_no_zones_means_no_countries(self):
        self.assertEqual(allowed_countries({}), [])


class OfferableCountriesAreWhatTheBUYERSees(unittest.TestCase):
    """The page can honour the whole world where Stripe cannot, because it re-quotes on every change: the
    buyer names a country, that country alone is rated, and checkout is then told that one country.

    A tenant whose zones read "United States" and "Everywhere else" was shown a dropdown holding only the
    United States -- the platform silently refusing a rule the tenant wrote (author, 2026-10-04: *"someone
    in Mexico, Canada, or the European Union cannot purchase the item when the system says that they
    can"*)."""

    def test_a_catch_all_expands(self):
        out = offerable_countries({"zones": [ELSEWHERE]})
        self.assertGreater(len(out), 200)
        for code in ("US", "CA", "MX", "DE", "GB", "JP", "AU"):
            self.assertIn(code, out)

    def test_named_countries_keep_their_place_at_the_front(self):
        """Their order is the tenant's statement about where they mainly sell; the expansion fills in
        behind it rather than burying them alphabetically."""
        out = offerable_countries(CONFIG)
        self.assertEqual(out[:2], ["US", "CA"])
        self.assertGreater(len(out), 200)
        self.assertEqual(len(out), len(set(out)), "a named country must not appear twice")

    def test_it_never_offers_a_country_stripe_will_reject(self):
        # The buyer picks here and pays at Stripe, so an offerable country must also be one Stripe accepts.
        # Sending a rejected code is a 400 that takes checkout down for EVERY buyer, not just that one.
        out = set(offerable_countries({"zones": [ELSEWHERE]}))
        for code in ("CU", "IR", "KP", "SY", "VI", "MP"):
            self.assertNotIn(code, out)

    def test_without_a_catch_all_it_matches_the_stripe_list_exactly(self):
        # The expansion is the CATCH-ALL's doing. A tenant who named two countries ships to two, and the
        # buyer's dropdown and Stripe's address form then agree by construction.
        named = {"zones": [US, CA]}
        self.assertEqual(offerable_countries(named), allowed_countries(named))
        self.assertEqual(offerable_countries(named), ["US", "CA"])


class Validation(unittest.TestCase):
    def test_a_valid_set_passes(self):
        validate_shipping_zones([US, CA, ELSEWHERE], CONFIG["boxes"])

    def test_absent_zones_pass(self):
        validate_shipping_zones(None)

    def test_a_duplicate_country_is_refused(self):
        """With first-match-wins a duplicate is not an error the tenant sees -- it is dead configuration they
        believe is live."""
        with self.assertRaises(DocumentValidationError) as caught:
            validate_shipping_zones([US, dict(US, rule={"type": "free"}), ELSEWHERE])
        self.assertIn("never apply", str(caught.exception))

    def test_a_catch_all_before_the_end_is_refused(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_shipping_zones([ELSEWHERE, US])
        self.assertIn("unreachable", str(caught.exception))

    def test_a_missing_catch_all_is_refused(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_shipping_zones([US])
        self.assertIn("everywhere else", str(caught.exception))

    def test_flat_without_an_amount_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_zones([{"destinations": [{"country": "CA"}], "rule": {"type": "flat"}},
                                     ELSEWHERE])

    def test_flat_rate_box_WITHOUT_a_priced_box_still_saves(self):
        """Reported 2026-10-01 as "zones are not being saved". It refused the whole document, so a tenant
        could not record "the US is priced by box" and then go and price the boxes -- which is the obvious
        order, and the one the screen's layout suggests, since Boxes sits below Zones.

        A validator refuses INCOHERENT data, not INCOMPLETE configuration. The gap is reported where it
        matters: resolve_options answers `needs: box_price` and the screen says so while they work.
        """
        validate_shipping_zones([{"destinations": [{"country": "CA"}],
                                  "rule": {"type": "flat_rate_box"}}, ELSEWHERE], boxes=[])

    def test_flat_rate_box_with_a_priced_box_passes(self):
        validate_shipping_zones([{"destinations": [{"country": "CA"}], "rule": {"type": "flat_rate_box"}},
                                 ELSEWHERE], boxes=CONFIG["boxes"])

    def test_an_unpriced_by_box_zone_is_reported_at_RATING_time_instead(self):
        """Where the tenant can act on it, and where a buyer would otherwise be mispriced."""
        from stripe_link.domain.shipping_charges import resolve_options

        config = {"enabled_services": [{"service_token": "ground", "label": "Ground"}],
                  "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}},
                            ELSEWHERE],
                  "boxes": []}
        result = resolve_options({}, config, country="US", box_amount=None)
        self.assertEqual(result["needs"], "box_price")
        self.assertEqual(result["options"], [])

    def test_a_zone_needs_a_destination(self):
        for zone in ({"rule": {"type": "free"}}, {"destinations": [], "rule": {"type": "free"}}):
            with self.assertRaises(DocumentValidationError):
                validate_shipping_zones([zone, ELSEWHERE])

    def test_a_zone_needs_a_rule(self):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_zones([{"destinations": [{"country": "US"}]}, ELSEWHERE])

    def test_an_unknown_rule_type_is_refused_on_write(self):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_zones([{"destinations": [{"country": "US"}],
                                      "rule": {"type": "telepathy"}}, ELSEWHERE])

    def test_regions_are_accepted_but_unused_in_V1(self):
        """The shape carries them so subdivisions are purely additive later -- no second field, no migration."""
        validate_shipping_zones([{"destinations": [{"country": "US", "regions": ["CA", "OR"]}],
                                  "rule": {"type": "live"}}, ELSEWHERE])

    def test_it_runs_as_part_of_the_config_validator(self):
        document = {"schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
                    "provider": {"name": "shippo"}, "zones": [US]}
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(document)
        document["zones"] = [US, ELSEWHERE]
        validate_shipping_config(document)


if __name__ == "__main__":
    unittest.main()
