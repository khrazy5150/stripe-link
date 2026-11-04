"""Each business keeps its own working day (plans/SHIPPING_PER_SITE.md §S1).

A delivery estimate says "ships Tuesday" and means it in SOMEBODY's timezone, past SOMEBODY's cutoff. With
the working day on the account, a tenant running two shops had both buyers told the first shop's hours — so
a buyer from the second was promised a day that business does not ship on.

Two properties carry it, and the second is the one that is easy to get wrong:

1. **Site before account, PER FIELD.** A shop may keep the account's timezone and close earlier, or sit in
   another zone and keep the same cutoff. Resolving the whole document would make setting either field
   silently adopt the default of the other.
2. **An explicit answer beats a guess, at either level.** `suggest_timezone` never returns "" — it answers
   UTC for an address it cannot place — so chaining the guess per source would let an empty Site address
   swallow the account's real timezone.
"""
import json
import pathlib
import unittest

from stripe_link.domain.delivery_estimate import DEFAULT_CUTOFF_HOUR
from stripe_link.domain.store_timezone import working_day

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACCOUNT = {"timezone": "US/Eastern", "shipping_cutoff_hour": 15,
           "address": {"country": "US", "region": "NY"}}


class PerFieldPrecedenceTests(unittest.TestCase):
    def test_the_site_overrides_BOTH(self):
        self.assertEqual(working_day({"timezone": "US/Pacific", "shipping_cutoff_hour": 12}, ACCOUNT),
                         ("US/Pacific", 12))

    def test_the_site_overrides_the_TIMEZONE_ONLY(self):
        """And keeps the account's cutoff — not the platform default, which is what document-level
        resolution would have given it."""
        self.assertEqual(working_day({"timezone": "US/Pacific"}, ACCOUNT), ("US/Pacific", 15))

    def test_the_site_overrides_the_CUTOFF_ONLY(self):
        self.assertEqual(working_day({"shipping_cutoff_hour": 12}, ACCOUNT), ("US/Eastern", 12))

    def test_a_site_that_says_nothing_inherits_everything(self):
        self.assertEqual(working_day({}, ACCOUNT), ("US/Eastern", 15))

    def test_MIDNIGHT_is_a_real_choice_not_an_absence(self):
        """Hour 0 is falsy. A `or` anywhere in this chain reads it as "unset" and silently returns 3pm."""
        self.assertEqual(working_day({"shipping_cutoff_hour": 0}, ACCOUNT)[1], 0)
        self.assertEqual(working_day({}, {"shipping_cutoff_hour": 0})[1], 0)

    def test_a_BOOLEAN_cutoff_is_not_an_hour(self):
        """`True` is an int in Python and is not a quantity. It falls through to the account rather than
        being read as 1 o'clock."""
        self.assertEqual(working_day({"shipping_cutoff_hour": True}, ACCOUNT)[1], 15)


class TheGuessIsMadeONCETests(unittest.TestCase):
    def test_a_site_address_is_guessed_from_when_nobody_stated_a_zone(self):
        self.assertEqual(working_day({"address": {"country": "US", "region": "WA"}},
                                     {"shipping_cutoff_hour": 9}),
                         ("America/Los_Angeles", 9))

    def test_an_EMPTY_site_address_does_not_swallow_the_accounts_zone(self):
        """The trap: `suggest_timezone({})` is "UTC", not "". Guessing per source would answer UTC here
        and quietly move the business to Greenwich."""
        self.assertEqual(working_day({"address": {}}, ACCOUNT)[0], "US/Eastern")

    def test_an_explicit_ACCOUNT_zone_beats_a_SITE_address_guess(self):
        """Stated beats inferred, whichever level stated it."""
        self.assertEqual(working_day({"address": {"country": "US", "region": "WA"}}, ACCOUNT)[0],
                         "US/Eastern")

    def test_a_BARE_COUNTRY_site_address_is_a_FORM_ARTIFACT_not_an_answer(self):
        """Found on live dev data, not by a test. The Sites editor defaults `country` to "US" and saves
        whatever is non-empty, so a Site nobody has given an address stores `{"country": "US"}`. Treated as
        stated it beat the account's real US/WA with the country default (America/New_York) — a Seattle
        business told it keeps New York hours."""
        self.assertEqual(working_day({"address": {"country": "US"}}, ACCOUNT)[0], "US/Eastern")
        self.assertEqual(working_day({"address": {"country": "US"}},
                                     {"address": {"country": "US", "region": "WA"}})[0],
                         "America/Los_Angeles")

    def test_PLACEABLE_means_what_the_GUESSER_reads_and_nothing_more(self):
        """A postal code is not consulted by `suggest_timezone`, so counting it would mark an address
        placeable while leaving the guess at the country default — the same bug wearing a postcode."""
        account = {"address": {"country": "US", "region": "WA"}}
        self.assertEqual(working_day({"address": {"country": "US", "postal_code": "73301"}}, account)[0],
                         "America/Los_Angeles")
        self.assertEqual(working_day({"address": {"country": "US", "region": "TX"}}, account)[0],
                         "America/Chicago")

    def test_either_region_or_state_counts(self):
        """`suggest_timezone` reads both keys; so must the predicate in front of it."""
        account = {"address": {"country": "US", "region": "WA"}}
        self.assertEqual(working_day({"address": {"country": "US", "state": "TX"}}, account)[0],
                         "America/Chicago")

    def test_the_accounts_address_is_used_when_the_site_has_none(self):
        self.assertEqual(working_day({}, {"address": {"country": "US", "region": "CO"}})[0],
                         "America/Denver")

    def test_nothing_anywhere_is_UTC_and_the_default_hour(self):
        """UTC rather than a plausible-sounding guess: a tenant corrects an obvious placeholder and accepts
        a plausible wrong answer without looking."""
        self.assertEqual(working_day(), ("UTC", DEFAULT_CUTOFF_HOUR))

    def test_None_at_either_level_does_not_raise(self):
        """An order with no Site, and a Site on an account whose profile was never filled in."""
        self.assertEqual(working_day(None, ACCOUNT), ("US/Eastern", 15))
        self.assertEqual(working_day({"timezone": "UTC"}, None), ("UTC", DEFAULT_CUTOFF_HOUR))


class TheDeliveryEstimateAsksTheSELLINGBusinessTests(unittest.TestCase):
    SOURCE = (ROOT / "src/handlers/stripe_webhook.py").read_text(encoding="utf-8")

    def _block(self):
        return self.SOURCE.split("def attach_delivery_promise(", 1)[1].split("\ndef ", 1)[0]

    def test_it_resolves_the_site_from_the_orders_own_page(self):
        block = self._block()
        self.assertIn("site_organization(", block)
        self.assertIn('(order_record.get("attribution") or {}).get("page_id")', block)

    def test_it_passes_the_MODE(self):
        """A Site lives at SITE#<mode>#<site_id>; resolving a test-mode order against live finds nothing."""
        self.assertIn("mode=mode", self._block())

    def test_the_site_comes_FIRST_and_the_account_second(self):
        block = self._block()
        self.assertIn('working_day(organization, owner.get("business"))', block)

    def test_the_old_tenant_only_accessors_are_GONE_from_this_path(self):
        block = self._block()
        for dead in ("store_timezone(business)", "store_cutoff_hour(business)"):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, block)

    def test_a_failure_still_leaves_the_order_saved(self):
        """An estimate must never cost a sale — and `site_organization` never raises, so a Site that cannot
        be read costs the override rather than the estimate."""
        self.assertIn("except Exception as exc:", self._block())


class TheSiteEditorCanSetThemTests(unittest.TestCase):
    SCREEN = (ROOT / "dashboard/src/components/Sites.vue").read_text(encoding="utf-8")

    def test_both_controls_exist(self):
        self.assertIn('v-model="form.org.timezone"', self.SCREEN)
        self.assertIn('v-model="form.org.shipping_cutoff_hour"', self.SCREEN)

    def test_inheritance_is_SHOWN_not_hidden(self):
        """An override UI that hides inheritance produces a tenant who thinks they changed one warehouse's
        hours and changed none."""
        self.assertIn("Use account setting", self.SCREEN)
        self.assertIn("accountTimezoneLabel", self.SCREEN)

    def test_MIDNIGHT_survives_the_save(self):
        """`|| undefined` would eat hour 0. "" is the only "inherit"."""
        block = self.SCREEN.split("async function saveEdit(", 1)[1][:1600]
        self.assertIn('form.org.shipping_cutoff_hour === "" ? undefined', block)

    def test_a_stored_ZERO_reads_back_as_chosen_not_blank(self):
        block = self.SCREEN.split("function openEdit(", 1)[1][:2200]
        self.assertIn("org.shipping_cutoff_hour === null || org.shipping_cutoff_hour === undefined", block)

    def test_the_picker_reuses_the_SHARED_zone_list(self):
        self.assertIn("timeZoneOptions", self.SCREEN)
        self.assertNotIn("Intl.supportedValuesOf", self.SCREEN)


class TheSchemaDeclaresThemTests(unittest.TestCase):
    def test_nullable_because_absent_means_inherit(self):
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        org = schema["properties"]["organization"]["properties"]
        self.assertIn("null", org["timezone"]["type"])
        self.assertIn("null", org["shipping_cutoff_hour"]["type"])

    def test_the_hour_is_BOUNDED(self):
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        hour = schema["properties"]["organization"]["properties"]["shipping_cutoff_hour"]
        self.assertEqual((hour["minimum"], hour["maximum"]), (0, 23))


if __name__ == "__main__":
    unittest.main()
