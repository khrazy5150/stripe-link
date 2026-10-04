"""A seller who ships to the United States and nowhere else must be able to say so.

The Shipping screen's "Everywhere else" zone had no Remove button, and three separate things made it
structurally mandatory rather than merely default:

1. the template hid Remove for the catch-all;
2. `zonesFromDocument` appended one on every load, so removing it and saving would silently undo itself;
3. the document validator REFUSED a zone set that did not end in one.

The third was the real one, and its stated reason was wrong: *"without one, a buyer from an unlisted
country reaches undefined behaviour at the moment of purchase."* A country no zone claims is not
undefined, it is UNSERVED, and every layer already answers it that way. What the rule actually did was
decide a commercial policy on the tenant's behalf (author, 2026-10-04: *"so that tenants can force the
shipping element to ship within the United States only"*).
"""
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_shipping_zones
from stripe_link.domain.shipping_charges import resolve_options
from stripe_link.domain.shipping_zones import allowed_countries, offerable_countries, rule_for, ships_to

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIPPING_VUE = (ROOT / "dashboard" / "src" / "components" / "Shipping.vue").read_text()

US = {"name": "United States", "destinations": [{"country": "US"}], "rule": {"type": "live"}}
ELSEWHERE = {"name": "Everywhere else", "destinations": [{"country": "*"}], "rule": {"type": "free"}}
OFFER = {"shipping": {"eligible": True}, "items": [{"product_id": "p1", "quantity": 1}]}


class DomesticOnlyIsAValidPolicyTests(unittest.TestCase):
    def test_the_validator_accepts_it(self):
        validate_shipping_zones([US])

    def test_a_catch_all_out_of_place_is_still_refused(self):
        # The rule that remains is about INCOHERENT data: every zone after a catch-all is unreachable.
        with self.assertRaises(DocumentValidationError):
            validate_shipping_zones([ELSEWHERE, US])


class AnUnlistedCountryIsUNSERVEDNotUndefinedTests(unittest.TestCase):
    """The premise the old rule rested on, checked at every layer that would have had to be ambiguous for
    it to be true."""

    CONFIG = {"enabled_services": [{"service_token": "usps_ground_advantage", "label": "Ground"}],
              "zones": [US]}

    def test_no_zone_claims_it(self):
        self.assertEqual(rule_for(self.CONFIG, "CA"), {})
        self.assertFalse(ships_to(self.CONFIG, "CA"))

    def test_the_buyer_is_never_offered_it(self):
        self.assertEqual(offerable_countries(self.CONFIG), ["US"])

    def test_stripe_is_never_told_to_collect_it(self):
        self.assertEqual(allowed_countries(self.CONFIG), ["US"])

    def test_the_pricer_refuses_to_call_it_free(self):
        """`mode: ""` rather than `free` is the whole safeguard: a caller switching on mode alone would
        read "free" as "charge nothing and ship it", which for an unserved country means posting a parcel
        somewhere the tenant never agreed to send one."""
        out = resolve_options(OFFER, self.CONFIG, country="CA")
        self.assertEqual(out["options"], [])
        self.assertEqual(out["mode"], "")
        self.assertEqual(out["source"], "unserved")

    def test_and_the_served_country_still_works(self):
        out = resolve_options(OFFER, self.CONFIG, country="US")
        self.assertEqual(out["source"], "zone")


class TheScreenCanActuallyRemoveItTests(unittest.TestCase):
    """Backend permission is not enough: all three blockers had to go, and the second is the one that
    would have made the button look like it worked."""

    def test_the_remove_button_is_not_hidden_for_the_catch_all(self):
        header = SHIPPING_VUE.split('<div class="zone-actions">', 1)[1].split("</div>", 1)[0]
        self.assertIn(">Remove</button>", header)
        self.assertNotIn('v-if="!isCatchAllZone(zone)" class="secondary-action compact" type="button"\n'
                         '                      @click="form.zones.splice', header)

    def test_reloading_does_not_put_it_back(self):
        """`zonesFromDocument` appended a catch-all whenever the stored document had none. With that in
        place the tenant removes it, saves, reloads, and finds it back with nothing to explain why."""
        body = SHIPPING_VUE.split("function zonesFromDocument", 1)[1].split("\n}", 1)[0]
        self.assertIn("catchAll.length ? [...specific, catchAll[0]] : specific", body)
        self.assertNotIn("catchAll[0] || catchAllZone()", body)

    def test_there_is_a_way_back(self):
        # Removing it must not be a one-way door.
        self.assertIn("function addCatchAll()", SHIPPING_VUE)
        self.assertIn('v-if="!hasCatchAll"', SHIPPING_VUE)

    def test_adding_a_zone_still_lands_before_the_catch_all(self):
        # ...and must not crash or mis-place when there is no catch-all to land before.
        body = SHIPPING_VUE.split("function addZone()", 1)[1].split("\n}", 1)[0]
        self.assertIn("isCatchAllZone(last)", body)

    def test_the_tenant_is_told_what_removing_it_means(self):
        self.assertIn("cannot check out", SHIPPING_VUE)

    def test_the_header_no_longer_promises_every_buyer_an_answer(self):
        # That copy was only true while the catch-all was mandatory.
        self.assertNotIn("so every buyer has an answer", SHIPPING_VUE)
