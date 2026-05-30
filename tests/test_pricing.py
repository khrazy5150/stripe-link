import json
import unittest
from pathlib import Path

from stripe_link.domain.pricing import PricingError, resolve_offer


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class PricingResolutionTests(unittest.TestCase):
    def setUp(self):
        self.product = load_fixture("product-creatine-gummies.json")
        self.products = {self.product["product_id"]: self.product}

    def test_standard_offer_selects_standard_price_from_canonical_product(self):
        offer = load_fixture("offer-creatine-standard.json")

        resolved = resolve_offer(offer, self.products)

        self.assertEqual(resolved["offer_id"], "offer_creatine_standard")
        self.assertEqual(resolved["subtotal"], 6700)
        self.assertEqual(resolved["items"][0]["product_id"], "prod_creatine_gummies")
        self.assertEqual(resolved["items"][0]["price_id"], "price_2bottle")
        self.assertEqual(resolved["items"][0]["price_quantity"], 2)
        self.assertEqual(resolved["items"][0]["context"], "standard")
        self.assertTrue(resolved["items"][0]["selectable"])

    def test_standard_offer_accepts_customer_selected_price(self):
        offer = load_fixture("offer-creatine-standard.json")

        resolved = resolve_offer(offer, self.products, {
            "prod_creatine_gummies": "price_6bottle",
        })

        self.assertEqual(resolved["subtotal"], 14900)
        self.assertEqual(resolved["items"][0]["price_id"], "price_6bottle")
        self.assertEqual(resolved["items"][0]["price_quantity"], 6)
        self.assertEqual(resolved["items"][0]["label"], "6 Bottles")

    def test_upsell_offer_selects_upsell_price_from_same_product(self):
        offer = load_fixture("offer-creatine-upsell.json")

        resolved = resolve_offer(offer, self.products)

        self.assertEqual(resolved["offer_id"], "offer_creatine_upsell")
        self.assertEqual(resolved["subtotal"], 2700)
        self.assertEqual(resolved["items"][0]["product_id"], "prod_creatine_gummies")
        self.assertEqual(resolved["items"][0]["price_id"], "price_upsell_1bottle")
        self.assertEqual(resolved["items"][0]["context"], "upsell")
        self.assertFalse(resolved["items"][0]["selectable"])

    def test_offer_rejects_price_context_mismatch(self):
        offer = load_fixture("offer-creatine-standard.json")

        with self.assertRaises(PricingError):
            resolve_offer(offer, self.products, {
                "prod_creatine_gummies": "price_upsell_1bottle",
            })

    def test_offer_rejects_non_selectable_price(self):
        offer = load_fixture("offer-creatine-standard.json")

        with self.assertRaises(PricingError):
            resolve_offer(offer, self.products, {
                "prod_creatine_gummies": "price_missing",
            })

    def test_product_rejects_mixed_stripe_modes(self):
        offer = load_fixture("offer-creatine-standard.json")
        self.product["prices"][0]["stripe_mode"] = "live"

        with self.assertRaises(PricingError):
            resolve_offer(offer, self.products)


if __name__ == "__main__":
    unittest.main()
