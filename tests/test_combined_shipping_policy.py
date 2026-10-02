"""P5: extras ship free with the original order — as a stated decision, not a default.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md. For many sellers "add it, it ships with your order" is both true
and a selling point: a second item in a parcel that is already going often costs little. The failure today
was never that extras shipped free -- it is that nobody knew. The ledger records the real carrier cost
either way, so `shipping_margin` reports what the policy costs instead of hiding it.
"""
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_combined_shipping
from handlers.upsell import quote_upsell_shipping

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

ITEMS = [{"product_id": "p1", "quantity": 1}]
TO = {"country": "US", "postal_code": "80202", "state": "CO"}
MEASURED = {"product_id": "p1", "name": "Shaker", "product_type": "physical",
            "fulfillment": {"requires_shipping": True, "weight_lb": 1.0,
                            "item_dimensions": {"length_in": 4, "width_in": 3, "height_in": 2,
                                                "weight_lb": 1.0}}}


def config(**over):
    base = {"boxes": [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15}],
            "enabled_services": [{"service_token": "usps_ground", "label": "Ground"}],
            "ship_from_address": {"postal_code": "80301", "country": "US", "city": "Denver", "state": "CO"},
            "provider": {"name": "mock", "api_key_ref": "ref_1"},
            "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}}]}
    base.update(over)
    return base


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


def quote(cfg):
    import stripe_link.repositories.documents as docs

    class Repo:
        def get(self, tenant_id, doc_id=None):
            return cfg

    real = docs.shipping_config_repository
    docs.shipping_config_repository = lambda *a, **k: Repo()
    try:
        return quote_upsell_shipping("t1", ITEMS, {"p1": MEASURED}, destination=TO, mode="test",
                                     secret_cipher=Cipher())
    finally:
        docs.shipping_config_repository = real


class ThePolicyAppliesTests(unittest.TestCase):
    def test_without_it_an_upsell_is_charged(self):
        self.assertGreater(quote(config())["amount"], 0)

    def test_with_it_an_upsell_ships_free(self):
        result = quote(config(combined_shipping={"extras_ship_free": True}))
        self.assertEqual(result["amount"], 0)
        self.assertEqual(result["reason"], "combined_shipping")

    def test_it_short_circuits_before_any_carrier_call(self):
        # A policy that still spent a rate call to discard the answer would be slower for no reason.
        broken = config(combined_shipping={"extras_ship_free": True},
                        provider={"name": "mock", "api_key_ref": ""})
        self.assertEqual(quote(broken)["reason"], "combined_shipping")

    def test_off_is_the_same_as_absent(self):
        self.assertGreater(quote(config(combined_shipping={"extras_ship_free": False}))["amount"], 0)


class TheDocumentTests(unittest.TestCase):
    def test_absent_is_valid(self):
        validate_combined_shipping(None)

    def test_a_boolean_is_valid(self):
        validate_combined_shipping({"extras_ship_free": True})

    def test_anything_else_is_refused(self):
        for bad in ("yes", 1, [], {"extras_ship_free": "yes"}):
            with self.subTest(bad=bad):
                with self.assertRaises(DocumentValidationError):
                    validate_combined_shipping(bad)

    def test_the_config_validator_calls_it(self):
        source = (ROOT / "src/stripe_link/domain/documents.py").read_text(encoding="utf-8")
        self.assertIn('validate_combined_shipping(document.get("combined_shipping"))', source)


class TheControlTests(unittest.TestCase):
    def test_the_shipping_screen_can_set_it(self):
        self.assertIn("form.combined_shipping.extras_ship_free", SCREEN)
        self.assertIn("Extras ship free with the original order", SCREEN)

    def test_it_says_where_the_cost_shows_up(self):
        # A decision with a number attached, which is the whole point of it being a decision.
        self.assertIn("shipping margin on the Ledger shows what it actually costs you", SCREEN)

    def test_only_ON_is_persisted(self):
        # A stored `false` and an absent block mean the same thing; writing the default into every
        # document makes a decision look taken when it was not.
        block = SCREEN.split("if (form.combined_shipping.extras_ship_free)", 1)[1][:160]
        self.assertIn("extras_ship_free: true", block)

    def test_it_reads_back(self):
        self.assertIn("extras_ship_free: !!(config.combined_shipping || {}).extras_ship_free", SCREEN)
