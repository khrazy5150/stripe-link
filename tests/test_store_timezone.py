"""Suggesting a store's timezone, and never insisting on it.

plans/THANK_YOU_PAGE.md P1. The shipping cutoff needs to know whose afternoon it is, and Sabbath mode will
need the same answer for when Friday sundown falls — so this is a property of the store, not of either
feature.

The author's framing, which is the whole design: a seller may live in Pacific time (Las Vegas) and ship
from a warehouse in Mountain time (St. George), and either can be the right answer depending on which they
consider their working day. *"Just like everything else in this software, we suggest but don't dictate."*
"""
import unittest

from stripe_link.domain.store_timezone import COMMON_ZONES, FALLBACK, store_timezone, suggest_timezone


class ItSuggestsFromTheAddressTests(unittest.TestCase):
    def test_a_us_state_decides_it(self):
        self.assertEqual(suggest_timezone({"region": "CO", "country": "US"}), "America/Denver")
        self.assertEqual(suggest_timezone({"region": "NY", "country": "US"}), "America/New_York")

    def test_the_FULL_state_name_works_too(self):
        """The profile form stores what the tenant typed, and the Business Address screen shows
        "Colorado", not "CO"."""
        self.assertEqual(suggest_timezone({"region": "Colorado", "country": "US"}), "America/Denver")
        self.assertEqual(suggest_timezone({"region": "California", "country": "US"}), "America/Los_Angeles")

    def test_a_name_is_never_TRUNCATED_to_a_code(self):
        """The bug this was caught on. Two letters of a state name is a DIFFERENT state: Nevada -> NE ->
        Nebraska -> Central, when Nevada is Pacific — and Nevada was the author's own example. Montana ->
        MO -> Missouri, Minnesota -> MI -> Michigan."""
        self.assertEqual(suggest_timezone({"region": "Nevada", "country": "US"}), "America/Los_Angeles")
        self.assertEqual(suggest_timezone({"region": "Montana", "country": "US"}), "America/Denver")
        self.assertEqual(suggest_timezone({"region": "Minnesota", "country": "US"}), "America/Chicago")

    def test_canadian_provinces_resolve_by_name_or_code(self):
        self.assertEqual(suggest_timezone({"region": "BC", "country": "CA"}), "America/Vancouver")
        self.assertEqual(suggest_timezone({"region": "British Columbia", "country": "CA"}),
                         "America/Vancouver")

    def test_a_single_zone_country_needs_no_region(self):
        self.assertEqual(suggest_timezone({"country": "DE"}), "Europe/Berlin")
        self.assertEqual(suggest_timezone({"country": "GB"}), "Europe/London")

    def test_an_unknown_country_gets_an_OBVIOUS_placeholder(self):
        """UTC rather than a nearby-sounding zone, deliberately: a tenant scanning their profile corrects
        an obvious placeholder and accepts a plausible wrong answer without looking."""
        self.assertEqual(suggest_timezone({"country": "ZZ"}), FALLBACK)
        self.assertEqual(suggest_timezone({}), FALLBACK)
        self.assertEqual(suggest_timezone(None), FALLBACK)


class TheTenantsOwnChoiceWinsTests(unittest.TestCase):
    def test_an_explicit_timezone_beats_the_suggestion(self):
        # Lives in Las Vegas, ships from St. George. Only they know which is their working day.
        business = {"timezone": "America/Los_Angeles", "address": {"region": "UT", "country": "US"}}
        self.assertEqual(store_timezone(business), "America/Los_Angeles")

    def test_without_one_the_address_answers(self):
        self.assertEqual(store_timezone({"address": {"region": "UT", "country": "US"}}), "America/Denver")

    def test_a_blank_choice_is_not_a_choice(self):
        self.assertEqual(store_timezone({"timezone": "   ", "address": {"region": "UT", "country": "US"}}),
                         "America/Denver")

    def test_an_empty_business_still_answers(self):
        self.assertEqual(store_timezone({}), FALLBACK)
        self.assertEqual(store_timezone(None), FALLBACK)

    def test_a_zone_we_never_listed_is_still_accepted(self):
        # The picker is a convenience, not a whitelist. Nothing validates against COMMON_ZONES.
        self.assertEqual(store_timezone({"timezone": "Indian/Christmas"}), "Indian/Christmas")


class ThePickerIsUsableTests(unittest.TestCase):
    def test_the_zones_are_grouped_and_non_empty(self):
        self.assertTrue(COMMON_ZONES)
        for label, zones in COMMON_ZONES:
            self.assertTrue(label and zones)

    def test_every_suggestion_appears_in_the_picker(self):
        """Otherwise a tenant opens the dropdown and cannot find the value already selected."""
        offered = {zone for _label, zones in COMMON_ZONES for zone in zones}
        for region, country in (("CO", "US"), ("NV", "US"), ("NY", "US"), ("BC", "CA"), ("", "DE"),
                                ("", "GB"), ("", "AU"), ("", "ZZ")):
            self.assertIn(suggest_timezone({"region": region, "country": country}), offered,
                          f"{region}/{country} suggests a zone the picker does not list")


class TheProfileAcceptsItTests(unittest.TestCase):
    def test_the_validator_takes_a_timezone(self):
        from stripe_link.domain.documents import validate_business_identity

        validate_business_identity({"name": "Shop", "timezone": "America/Denver"})

    def test_it_does_not_police_the_value(self):
        """`delivery_estimate` already degrades to UTC with a loud warning for a name it cannot load.
        Refusing the SAVE would lock a tenant out of their own profile over a timezone."""
        from stripe_link.domain.documents import validate_business_identity

        validate_business_identity({"timezone": "Somewhere/Odd"})


class TheScreenCanActuallySaveItTests(unittest.TestCase):
    """A field that renders and does not persist is worse than no field. `cleanBusiness` builds the saved
    document from an explicit list, so a value absent from that list is dropped silently on save — the
    same shape as the catch-all Remove button, which looked like it worked and undid itself on reload."""

    import pathlib as _pathlib

    PROFILE_VUE = (_pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard" / "src" / "components" / "Profile.vue").read_text()
    STORE_JS = (_pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "stores" / "profile.js").read_text()

    def test_the_save_carries_it(self):
        block = self.PROFILE_VUE.split("function cleanBusiness", 1)[1].split("\n}", 1)[0]
        self.assertIn("result.timezone = business.timezone", block)

    def test_an_unchosen_timezone_is_NOT_written_back(self):
        """Blank means "follow my address", which keeps working if the tenant moves. Persisting the
        suggestion would freeze a guess into a decision they never made."""
        block = self.PROFILE_VUE.split("function cleanBusiness", 1)[1].split("\n}", 1)[0]
        self.assertIn("if (business.timezone)", block)

    def test_the_form_reads_it_back(self):
        block = self.PROFILE_VUE.split("function applyProfile", 1)[1].split("\n}", 1)[0]
        self.assertIn('timezone: business.timezone || ""', block)

    def test_the_suggestion_comes_from_the_server(self):
        # One inference, not a JS copy of the state table that would drift from the Python one.
        self.assertIn("body.timezone_suggested", self.PROFILE_VUE)
        self.assertIn("timezone_suggested", self.STORE_JS)

    def test_the_picker_offers_every_zone_the_browser_knows(self):
        # Not a list we maintain: Intl.supportedValuesOf is the complete IANA set and stays current.
        self.assertIn('Intl.supportedValuesOf("timeZone")', self.PROFILE_VUE)

    def test_the_endpoint_sends_the_suggestion(self):
        source = (self._pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "profile.py").read_text()
        self.assertIn("timezone_suggested", source)
        self.assertIn("suggest_timezone(", source)


class TheCutoffHourIsTheTenantsTooTests(unittest.TestCase):
    """15:00 is a suggestion. Some stores cut off at noon, and the point of the buffer is that a tenant
    who quietly ships same-day then beats their own estimate."""

    def test_the_default_is_three_pm(self):
        from stripe_link.domain.store_timezone import store_cutoff_hour

        self.assertEqual(store_cutoff_hour({}), 15)
        self.assertEqual(store_cutoff_hour(None), 15)

    def test_a_tenants_hour_is_used(self):
        from stripe_link.domain.store_timezone import store_cutoff_hour

        self.assertEqual(store_cutoff_hour({"shipping_cutoff_hour": 12}), 12)

    def test_midnight_is_a_real_answer_not_a_missing_one(self):
        from stripe_link.domain.store_timezone import store_cutoff_hour

        self.assertEqual(store_cutoff_hour({"shipping_cutoff_hour": 0}), 0)

    def test_nonsense_falls_back_rather_than_raising(self):
        from stripe_link.domain.store_timezone import store_cutoff_hour

        for bad in (99, -1, "noon", True, None):
            self.assertEqual(store_cutoff_hour({"shipping_cutoff_hour": bad}), 15)

    def test_the_validator_refuses_an_hour_that_is_not_one(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_business_identity

        validate_business_identity({"shipping_cutoff_hour": 23})
        with self.assertRaises(DocumentValidationError):
            validate_business_identity({"shipping_cutoff_hour": 24})

    def test_the_screen_saves_it_only_when_chosen(self):
        """`null` means "use the suggested 3pm" and must stay absent, for the same reason a blank timezone
        does: a default nobody chose should not look like a decision."""
        source = (self._pathlib.Path(__file__).resolve().parents[1]
                  / "dashboard" / "src" / "components" / "Profile.vue").read_text()
        self.assertIn("Number.isInteger(business.shipping_cutoff_hour)", source)
        self.assertIn("result.shipping_cutoff_hour = business.shipping_cutoff_hour", source)

    _pathlib = __import__("pathlib")
