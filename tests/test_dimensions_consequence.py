"""What leaving a product unmeasured costs THIS tenant, given the zones they configured.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0b. The obvious warning -- "leaving this blank will prevent you
from charging shipping" -- is true for two of the four zone rules and false for the other two. A tenant on
flat zones who is told they cannot charge shipping, and then finds that they can, learns to ignore every
other warning the product shows. This repo has removed four of those already.
"""
import pathlib
import unittest

from stripe_link.domain.shipping import dimensions_consequence

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELD = (ROOT / "dashboard/src/components/products/ProductVariantsField.vue").read_text(encoding="utf-8")
SCREEN = (ROOT / "dashboard/src/components/Products.vue").read_text(encoding="utf-8")


def config(*rule_types):
    return {"zones": [{"destinations": [{"country": "US"}], "rule": {"type": t}} for t in rule_types]}


class TheMessageFollowsTheZonesTests(unittest.TestCase):
    def test_live_rates_lose_a_real_charge(self):
        result = dimensions_consequence(config("live"))
        self.assertEqual(result["severity"], "warning")
        self.assertIn("ship free", result["message"])

    def test_by_box_pricing_loses_a_real_charge(self):
        result = dimensions_consequence(config("flat_rate_box"))
        self.assertEqual(result["severity"], "warning")
        self.assertIn("matched to a box", result["message"])

    def test_a_flat_zone_still_charges_and_must_not_be_told_otherwise(self):
        # $7 is $7 whether or not anyone measured the goods.
        result = dimensions_consequence(config("flat"))
        self.assertEqual(result["severity"], "info")
        self.assertIn("buyers are still charged", result["message"])
        self.assertNotIn("ship free", result["message"])

    def test_a_free_zone_says_the_same_milder_thing(self):
        self.assertEqual(dimensions_consequence(config("free"))["severity"], "info")

    def test_what_is_lost_for_flat_tenants_is_LABELS_not_charges(self):
        self.assertIn("buy labels", dimensions_consequence(config("flat"))["message"])

    def test_one_live_zone_among_flat_ones_is_still_a_warning(self):
        # A catch-all on live rates means SOME buyers ship free. The strongest true statement wins.
        self.assertEqual(dimensions_consequence(config("flat", "live"))["severity"], "warning")

    def test_no_zones_says_nothing_at_all(self):
        # Step 2 of 5, no shipping decision made. Silence is the honest answer, not a default warning.
        result = dimensions_consequence(config())
        self.assertEqual((result["severity"], result["message"]), ("", ""))

    def test_no_config_at_all_says_nothing(self):
        for empty in (None, {}, {"zones": None}):
            with self.subTest(empty=empty):
                self.assertEqual(dimensions_consequence(empty)["message"], "")


class TheEndpointServesItTests(unittest.TestCase):
    def test_both_the_read_and_the_save_carry_it(self):
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('"dimensions_consequence": dimensions_consequence('), 2)


class TheFormShowsItTests(unittest.TestCase):
    def test_the_banner_is_driven_by_the_server_not_the_component(self):
        # The rule lives beside the zones it reads. A component that decided this would be a second
        # place the zone vocabulary has to be kept in step.
        self.assertIn("consequence: { type: Object", FIELD)
        self.assertIn("body?.dimensions_consequence", SCREEN)

    def test_it_shows_only_while_the_fields_are_blank(self):
        # A solved problem is not a notice.
        self.assertIn('v-if="unmeasured && consequence.message"', FIELD)

    def test_blank_means_any_of_the_four_is_missing(self):
        # A carrier needs three sides AND a weight; three of four rates nothing.
        block = FIELD.split("const unmeasured = computed", 1)[1][:260]
        for field in ("item_length_in", "item_width_in", "item_height_in", "item_weight_lb"):
            self.assertIn(field, block)

    def test_severity_decides_whether_it_shouts(self):
        self.assertIn("consequence.severity === 'warning' ? 'keys-status-banner warning' : 'field-hint'",
                      FIELD)

    def test_the_optional_badge_tells_the_truth_for_this_tenant(self):
        # Optional to SAVE, required to QUOTE -- and which applies depends on their zones.
        self.assertIn("needed to charge shipping", FIELD)
        self.assertIn('{{ sizeBadge }}', FIELD)

    def test_a_failed_lookup_shows_no_warning_at_all(self):
        # A warning this screen could not verify is exactly the kind it exists to stop showing.
        block = SCREEN.split("async function loadShippingConsequence", 1)[1][:420]
        self.assertIn("shippingConsequence.value = {}", block)

    def test_both_the_wizard_and_the_edit_modal_get_it(self):
        self.assertEqual(SCREEN.count(':consequence="shippingConsequence"'), 2)
