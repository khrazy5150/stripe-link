import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_app_config,
    validate_global_billing_config,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_user_preferences,
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

    def test_accepts_universal_bundle_fixtures(self):
        validate_product_document(load_fixture("product-universal-bundle.json"))
        validate_offer_document(load_fixture("offer-universal-bundle.json"))
        validate_page_document(load_fixture("page-universal-bundle.json"))

    def test_accepts_app_config_fixture(self):
        validate_app_config(load_fixture("app-config.json"))

    def test_accepts_global_billing_config_fixture(self):
        validate_global_billing_config(load_fixture("global-billing-config.json"))

    def test_app_config_rejects_invalid_dev_api_base_url(self):
        config = load_fixture("app-config.json")
        config["environments"]["dev"]["api_base_url"] = "dev.juniorbay.com"

        with self.assertRaisesRegex(DocumentValidationError, "environments.dev.api_base_url"):
            validate_app_config(config)

    def test_global_billing_config_rejects_invalid_platform_fee_percent(self):
        config = load_fixture("global-billing-config.json")
        config["platform_fees"]["tiers"]["basic"]["physical"] = 101

        with self.assertRaisesRegex(DocumentValidationError, "platform_fees.tiers.basic.physical"):
            validate_global_billing_config(config)

    def test_accepts_dynamodb_decimal_integer_fields(self):
        product = load_fixture("product-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        for price in product["prices"]:
            price["unit_amount"] = Decimal(price["unit_amount"])
            price["tenant_keyed_amount"] = Decimal(price["tenant_keyed_amount"])
            price["quantity"] = Decimal(price["quantity"])
            price["compare_at_unit_amount"] = Decimal(price["compare_at_unit_amount"])
        for item in offer["items"]:
            if "quantity" in item:
                item["quantity"] = Decimal(item["quantity"])
            for price in item.get("selectable_prices", []):
                price["quantity"] = Decimal(price["quantity"])
                price["display_discount_pct"] = Decimal(price["display_discount_pct"])

        validate_product_document(product)
        validate_offer_document(offer)

    def test_product_rejects_invalid_price_amount_type(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["unit_amount"] = "3900"

        with self.assertRaisesRegex(DocumentValidationError, "price.unit_amount"):
            validate_product_document(product)

    def test_product_accepts_customer_chooses_price_without_unit_amount(self):
        product = copy.deepcopy(self.product)
        price = product["prices"][0]
        price["pricing_model"] = "customer_chooses"
        price.pop("unit_amount", None)
        price["min_amount"] = 500
        price["suggested_amount"] = 2500

        validate_product_document(product)

    def test_product_rejects_price_label(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["label"] = "One Bottle"

        with self.assertRaisesRegex(DocumentValidationError, "price.label"):
            validate_product_document(product)

    def test_product_rejects_price_nickname(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["nickname"] = "One Bottle"

        with self.assertRaisesRegex(DocumentValidationError, "price.nickname"):
            validate_product_document(product)

    def test_product_requires_canonical_marker(self):
        product = copy.deepcopy(self.product)
        product.pop("canonical")

        with self.assertRaisesRegex(DocumentValidationError, "canonical"):
            validate_product_document(product)

    def test_product_requires_tags(self):
        product = copy.deepcopy(self.product)
        product.pop("tags")

        with self.assertRaisesRegex(DocumentValidationError, "tags"):
            validate_product_document(product)

    def test_product_rejects_legacy_local_metadata(self):
        product = copy.deepcopy(self.product)
        product["local_metadata"] = {}

        with self.assertRaisesRegex(DocumentValidationError, "local_metadata"):
            validate_product_document(product)

    def test_product_rejects_legacy_top_level_shipping_fields(self):
        product = copy.deepcopy(self.product)
        product["requires_shipping"] = True
        product["package_dimensions"] = {"length": 10, "width": 8, "height": 4}

        with self.assertRaisesRegex(DocumentValidationError, "requires_shipping"):
            validate_product_document(product)

    def test_product_rejects_duplicate_price_ids(self):
        product = copy.deepcopy(self.product)
        product["prices"][1]["price_id"] = product["prices"][0]["price_id"]

        with self.assertRaisesRegex(DocumentValidationError, "Duplicate product price_id"):
            validate_product_document(product)

    def test_product_accepts_fulfillment_block(self):
        product = copy.deepcopy(self.product)
        product["fulfillment"] = {
            "requires_shipping": True,
            "ship_from": None,
            "weight_lb": None,
            "dimensions": {
                "length_in": None,
                "width_in": None,
                "height_in": None,
            },
        }

        validate_product_document(product)

    def test_product_rejects_invalid_fulfillment_weight(self):
        product = copy.deepcopy(self.product)
        product["fulfillment"] = {
            "requires_shipping": True,
            "ship_from": None,
            "weight_lb": "16",
            "dimensions": {
                "length_in": None,
                "width_in": None,
                "height_in": None,
            },
        }

        with self.assertRaisesRegex(DocumentValidationError, "fulfillment.weight_lb"):
            validate_product_document(product)

    def test_product_rejects_invalid_refund_policy(self):
        product = load_fixture("product-universal-bundle.json")
        product["refund_policy"].pop("full_policy")

        with self.assertRaisesRegex(DocumentValidationError, "refund_policy.full_policy"):
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

    def test_offer_rejects_invalid_offer_type(self):
        offer = load_fixture("offer-universal-bundle.json")
        offer["offer_type"] = "collection"

        with self.assertRaisesRegex(DocumentValidationError, "Offer offer_type"):
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

    def test_page_rejects_unsupported_theme_preset(self):
        page = load_fixture("page-universal-bundle.json")
        page["theme"]["preset"] = "unknown-theme"

        with self.assertRaisesRegex(DocumentValidationError, "theme.preset"):
            validate_page_document(page)

    def test_page_rejects_invalid_theme_token_color(self):
        page = load_fixture("page-universal-bundle.json")
        page["theme"]["tokens"] = {"brand": "green;background:url(javascript:alert(1))"}

        with self.assertRaisesRegex(DocumentValidationError, "theme.tokens"):
            validate_page_document(page)

    def test_page_accepts_custom_favicon_url(self):
        page = load_fixture("page-universal-bundle.json")
        page["seo"]["favicon_url"] = "https://cdn.example.com/favicon.png"

        validate_page_document(page)

    def test_page_rejects_invalid_favicon_url(self):
        page = load_fixture("page-universal-bundle.json")
        page["seo"]["favicon_url"] = "javascript:alert(1)"

        with self.assertRaisesRegex(DocumentValidationError, "seo.favicon_url"):
            validate_page_document(page)

    def test_page_accepts_theme_fonts(self):
        page = load_fixture("page-universal-bundle.json")
        page["theme"]["fonts"] = {
            "service": "junior-bay",
            "body": {"family": "Inter", "fallback": "sans-serif"},
            "heading": {"family": "Inter Tight", "fallback": "sans-serif"},
            "accent": {"family": "JB Mono", "fallback": "monospace"},
        }

        validate_page_document(page)

    def test_page_rejects_theme_font_injection(self):
        page = load_fixture("page-universal-bundle.json")
        page["theme"]["fonts"]["heading"]["family"] = "Inter;background:url(javascript:alert(1))"

        with self.assertRaisesRegex(DocumentValidationError, "theme.fonts.heading.family"):
            validate_page_document(page)

    def test_user_preferences_accepts_saved_theme_tokens_and_fonts(self):
        preferences = load_fixture("user-preferences-demo.json")
        preferences["landing_pages"]["custom_color_themes"] = [{
            "theme_id": "theme_cyber_variant",
            "name": "Cyber Variant",
            "tokens": {
                "background": "#0c0a1d",
                "card": "#1e1b4b",
                "cta_from": "#6366f1",
                "faq_summary": "#eef2ff",
            },
            "fonts": {
                "service": "junior-bay",
                "body": {"family": "Inter", "fallback": "sans-serif"},
                "heading": {"family": "Inter Tight", "fallback": "sans-serif"},
            },
        }]

        validate_user_preferences(preferences)

    def test_user_preferences_rejects_invalid_saved_theme_token(self):
        preferences = load_fixture("user-preferences-demo.json")
        preferences["landing_pages"]["custom_color_themes"] = [{
            "theme_id": "theme_bad",
            "name": "Bad Theme",
            "tokens": {"background": "red;background:url(javascript:alert(1))"},
        }]

        with self.assertRaisesRegex(DocumentValidationError, "custom color theme tokens"):
            validate_user_preferences(preferences)

    def test_user_preferences_rejects_invalid_saved_theme_font(self):
        preferences = load_fixture("user-preferences-demo.json")
        preferences["landing_pages"]["custom_color_themes"] = [{
            "theme_id": "theme_bad_font",
            "name": "Bad Font Theme",
            "tokens": {"background": "#0c0a1d"},
            "fonts": {"heading": {"family": "Inter;background:url(javascript:alert(1))"}},
        }]

        with self.assertRaisesRegex(DocumentValidationError, "custom color theme fonts.heading.family"):
            validate_user_preferences(preferences)

    def test_page_rejects_too_many_universal_bundle_badges(self):
        page = load_fixture("page-universal-bundle.json")
        badges = next(section for section in page["sections"] if section["type"] == "trust_badges")
        badges["badges"].append({"emoji": "⭐", "label": "Bonus badge"})

        with self.assertRaisesRegex(DocumentValidationError, "Trust badges"):
            validate_page_document(page)

    def test_page_rejects_invalid_faq_item(self):
        page = load_fixture("page-universal-bundle.json")
        faq = next(section for section in page["sections"] if section["type"] == "faq")
        faq["items"][0].pop("answer")

        with self.assertRaisesRegex(DocumentValidationError, "FAQ answer"):
            validate_page_document(page)


if __name__ == "__main__":
    unittest.main()
