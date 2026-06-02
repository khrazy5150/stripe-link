import copy
import json
import unittest
from pathlib import Path

from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
)


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class DocumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.product = load_fixture("product-creatine-gummies.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.page = load_fixture("page-creatine-standard.json")

    def test_accepts_canonical_product_offer_and_page_fixtures(self):
        validate_product_document(self.product)
        validate_offer_document(self.offer)
        validate_page_document(self.page)

    def test_product_rejects_invalid_price_amount_type(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["unit_amount"] = "3900"

        with self.assertRaisesRegex(DocumentValidationError, "price.unit_amount"):
            validate_product_document(product)

    def test_product_rejects_duplicate_price_ids(self):
        product = copy.deepcopy(self.product)
        product["prices"][1]["price_id"] = product["prices"][0]["price_id"]

        with self.assertRaisesRegex(DocumentValidationError, "Duplicate product price_id"):
            validate_product_document(product)

    def test_product_accepts_fulfillment_block(self):
        product = copy.deepcopy(self.product)
        product.pop("requires_shipping", None)
        product["fulfillment"] = {
            "requires_shipping": True,
            "ship_from": None,
            "weight_oz": None,
        }

        validate_product_document(product)

    def test_product_rejects_invalid_fulfillment_weight(self):
        product = copy.deepcopy(self.product)
        product["fulfillment"] = {"requires_shipping": True, "weight_oz": "16"}

        with self.assertRaisesRegex(DocumentValidationError, "fulfillment.weight_oz"):
            validate_product_document(product)

    def test_offer_rejects_invalid_selectable_price_quantity(self):
        offer = copy.deepcopy(self.offer)
        offer["items"][0]["selectable_prices"][0]["quantity"] = 0

        with self.assertRaisesRegex(DocumentValidationError, "selectable price quantity"):
            validate_offer_document(offer)

    def test_offer_rejects_invalid_checkout_mode(self):
        offer = copy.deepcopy(self.offer)
        offer["checkout"]["mode"] = "wire_transfer"

        with self.assertRaisesRegex(DocumentValidationError, "Offer checkout.mode"):
            validate_offer_document(offer)

    def test_page_rejects_unknown_section_type(self):
        page = copy.deepcopy(self.page)
        page["sections"][0]["type"] = "custom_html"

        with self.assertRaisesRegex(DocumentValidationError, "Page section type"):
            validate_page_document(page)

    def test_page_rejects_invalid_route_slug(self):
        page = copy.deepcopy(self.page)
        page["route"]["slug"] = "/Creatine Gummies"

        with self.assertRaisesRegex(DocumentValidationError, "route.slug"):
            validate_page_document(page)

    def test_page_rejects_selector_for_different_offer(self):
        page = copy.deepcopy(self.page)
        page["sections"][1]["offer_id"] = "offer_other"

        with self.assertRaisesRegex(DocumentValidationError, "must match page offer_id"):
            validate_page_document(page)

    def test_page_rejects_theme_color_injection(self):
        page = copy.deepcopy(self.page)
        page["theme"]["color"]["accent"] = "red;background:url(javascript:alert(1))"

        with self.assertRaisesRegex(DocumentValidationError, "theme.color.accent"):
            validate_page_document(page)

    def test_page_rejects_unsupported_template(self):
        page = copy.deepcopy(self.page)
        page["theme"]["template"] = "two_column"

        with self.assertRaisesRegex(DocumentValidationError, "theme.template"):
            validate_page_document(page)


if __name__ == "__main__":
    unittest.main()
