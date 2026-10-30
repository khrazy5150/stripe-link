"""Whether a shipping price can be produced for an offer at all, and what the page does about it.

The shipping element is the ONLY thing on a page that collects a postal code. Without one, a quote
returns `needs: postal_code`, Stripe is given no shipping option, and the buyer pays nothing to post --
a real order shipped a Large box for $7.83 that way (2026-10-06, `default_visible`). So the element
defaults ON for anything that ships, and anything that removes it has to be certain.

An unmeasured product is NOT certain on its own. Measured against a product carrying no dimensions at
all, through `resolve_options`:

    free           1 option, mode=free        charged correctly
    flat $7        1 option, mode=charged     charged correctly, $7
    flat_rate_box  0 options, needs=box_price
    live           0 options, needs=carrier

Half the rule types never read a dimension, and `dimensions_consequence` already tells those tenants so
("info", not "warning"). Hiding the element for them would take the postcode field off a page that was
charging correctly, which is the 2026-10-06 failure exactly.
"""

import json
import pathlib
import subprocess
import unittest

from stripe_link.domain.shipping import (
    dimensions_consequence,
    product_is_measured,
    rules_need_dimensions,
    shipping_is_quotable,
)
from stripe_link.domain.shipping_charges import resolve_options

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "shippingQuotable.js"

BARE = {"product_id": "p1", "fulfillment": {"requires_shipping": True}}
MEASURED = {"product_id": "p2", "fulfillment": {
    "requires_shipping": True,
    "item_dimensions": {"length_in": 6, "width_in": 4, "height_in": 4, "weight_lb": 1}}}
DIGITAL = {"product_id": "p3", "fulfillment": {"requires_shipping": False}}


def zones(rule_type, **rule):
    return {"zones": [{"name": "US", "destinations": [{"country": "US"}],
                       "rule": {"type": rule_type, **rule}}]}


class TheMeasurementOnlyMattersForSomeRulesTests(unittest.TestCase):
    """The premise the whole gate rests on. If this ever stops being true, the gate is wrong."""

    SERVICES = [{"label": "Standard", "service_token": "std"}]

    def _options(self, rule_type, **rule):
        offer = {"offer_id": "o1", "items": [{"product_id": "p1"}]}
        config = zones(rule_type, services=self.SERVICES, **rule)
        return resolve_options(offer, config, country="US", merchandise_amount=4376, item_count=1)

    def test_free_and_flat_price_an_unmeasured_product(self):
        """No dimensions anywhere, and both still return a priced option -- flat at the full amount."""
        self.assertEqual(len(self._options("free")["options"]), 1)
        flat = self._options("flat", amount=700)
        self.assertEqual(len(flat["options"]), 1)
        self.assertEqual(flat["mode"], "charged")

    def test_the_size_based_rules_cannot(self):
        for rule_type, needs in (("live", "carrier"), ("flat_rate_box", "box_price")):
            with self.subTest(rule=rule_type):
                result = self._options(rule_type)
                self.assertEqual(result["options"], [])
                self.assertEqual(result["needs"], needs)

    def test_the_product_screen_already_agrees(self):
        """`dimensions_consequence` is the tenant-facing half of this same fact, and it must not say
        one thing while the element does another."""
        self.assertEqual(dimensions_consequence(zones("flat"))["severity"], "info")
        self.assertEqual(dimensions_consequence(zones("free"))["severity"], "info")
        self.assertEqual(dimensions_consequence(zones("live"))["severity"], "warning")
        self.assertEqual(dimensions_consequence(zones("flat_rate_box"))["severity"], "warning")


class QuotabilityTests(unittest.TestCase):
    def test_a_size_based_zone_with_nothing_measured_is_not_quotable(self):
        for rule_type in ("live", "flat_rate_box"):
            with self.subTest(rule=rule_type):
                self.assertFalse(shipping_is_quotable([BARE], zones(rule_type)))

    def test_a_flat_or_free_zone_always_is(self):
        """The half of the rule set that never reads a dimension. Hiding the element here is the
        2026-10-06 failure: the page charges correctly and loses its postcode field."""
        for rule_type in ("flat", "free"):
            with self.subTest(rule=rule_type):
                self.assertTrue(shipping_is_quotable([BARE], zones(rule_type)))

    def test_one_measured_product_is_enough_to_keep_it(self):
        """That order still cannot be packed -- but the honest failure is an empty option list the
        tenant can fix, not a parcel posted for free."""
        self.assertTrue(shipping_is_quotable([BARE, MEASURED], zones("live")))

    def test_an_offer_that_ships_nothing_is_quotable(self):
        self.assertTrue(shipping_is_quotable([DIGITAL], zones("live")))

    def test_no_zones_configured_is_quotable(self):
        """A tenant who has not configured shipping has made no decision to act on."""
        self.assertTrue(shipping_is_quotable([BARE], {}))
        self.assertTrue(shipping_is_quotable([BARE], None))

    def test_nothing_at_all_is_quotable(self):
        self.assertTrue(shipping_is_quotable(None, None))

    def test_measurement_needs_all_three_sides_and_a_weight(self):
        self.assertTrue(product_is_measured(MEASURED))
        self.assertFalse(product_is_measured(BARE))
        for missing in ("length_in", "width_in", "height_in", "weight_lb"):
            with self.subTest(missing=missing):
                dims = dict(MEASURED["fulfillment"]["item_dimensions"])
                dims.pop(missing)
                self.assertFalse(product_is_measured(
                    {"fulfillment": {"requires_shipping": True, "item_dimensions": dims}}))

    def test_a_zero_dimension_is_not_a_measurement(self):
        self.assertFalse(product_is_measured({"fulfillment": {
            "requires_shipping": True,
            "item_dimensions": {"length_in": 0, "width_in": 4, "height_in": 4, "weight_lb": 1}}}))

    def test_only_the_two_size_based_rules_need_dimensions(self):
        self.assertTrue(rules_need_dimensions(zones("live")))
        self.assertTrue(rules_need_dimensions(zones("flat_rate_box")))
        self.assertFalse(rules_need_dimensions(zones("flat")))
        self.assertFalse(rules_need_dimensions(zones("free")))


class TheRendererHidesItOnlyWhenToldTests(unittest.TestCase):
    """`render_page` takes the answer from its CALLER, because neither it nor the publisher loads the
    tenant's zones -- the rule type is tenant-level and changes independently of the page and the offer,
    so it cannot be denormalised onto either without going stale."""

    def test_the_default_changes_nothing(self):
        """Every caller with no opinion, and every test that renders a page in isolation, must compose
        exactly as before."""
        import inspect
        from stripe_link.runtime.html import render_page
        self.assertIs(inspect.signature(render_page).parameters["shipping_quotable"].default, True)

    def test_it_is_anded_with_whether_anything_ships(self):
        source = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        self.assertIn("ships_physical = shipping_quotable and any(", source)

    def test_publish_and_preview_both_decide_it(self):
        """A preview that drew the element while publish dropped it would show the tenant a page their
        visitors never get."""
        publishing = (ROOT / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")
        self.assertIn("shipping_quotable=shipping_quotable", publishing)
        render = (ROOT / "src" / "handlers" / "page_render.py").read_text(encoding="utf-8")
        self.assertIn("shipping_quotable=_shipping_quotable(", render)

    def test_an_unreadable_config_leaves_the_element_alone(self):
        """Every uncertain path answers True. Hiding the only postcode field is the expensive mistake."""
        publishing = (ROOT / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")
        block = publishing.split("shipping_quotable = True", 1)[1].split("def _render", 1)[0]
        self.assertIn("except Exception", block)


class TheBuilderAgreesWithThePublisherTests(unittest.TestCase):
    """Two implementations of one rule, run over the same cases. The JS copy exists because the builder
    has the tenant's zones in hand and does not share a runtime with publish."""

    CASES = [
        ("live, nothing measured", [BARE], "live", False),
        ("box, nothing measured", [BARE], "flat_rate_box", False),
        ("flat, nothing measured", [BARE], "flat", True),
        ("free, nothing measured", [BARE], "free", True),
        ("live, one measured", [BARE, MEASURED], "live", True),
        ("live, all measured", [MEASURED], "live", True),
        ("live, nothing ships", [DIGITAL], "live", True),
    ]

    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node is not available")

    def test_both_implementations_give_the_same_answer(self):
        payload = [{"products": products, "config": zones(rule)} for _, products, rule, _ in self.CASES]
        script = (f"import {{ shippingIsQuotable }} from {json.dumps(str(MODULE))};"
                  f"const cases = {json.dumps(payload)};"
                  "console.log(JSON.stringify(cases.map((c) => shippingIsQuotable(c.products, c.config))));")
        out = subprocess.run(["node", "--input-type=module", "-e", script],
                             capture_output=True, text=True, cwd=ROOT, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        from_js = json.loads(out.stdout)
        for (name, products, rule, expected), js in zip(self.CASES, from_js):
            with self.subTest(case=name):
                self.assertEqual(shipping_is_quotable(products, zones(rule)), expected)
                self.assertEqual(js, expected)

    def test_the_builder_ands_it_with_shipping(self):
        vue = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertIn("builderShipsPhysical.value", vue)
        self.assertIn("shippingIsQuotable(builderOfferProducts.value || [], shippingConfig.value)", vue)
