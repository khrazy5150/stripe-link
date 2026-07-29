import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from stripe_link.domain.documents import (
    canonical_product_document,
    DocumentValidationError,
    normalize_country,
    normalize_e164,
    validate_app_config,
    validate_global_billing_config,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_site,
    validate_user_preferences,
    validate_user_profile,
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

    def test_offer_accepts_a_well_formed_semantic_model_cache(self):
        # P4.0: offer.semantic_model is reserved (server-owned). When present it must be a valid model.
        from stripe_link.domain.semantic import analyze_offer
        offer = copy.deepcopy(self.offer)
        offer["semantic_model"] = analyze_offer(offer, {self.product["product_id"]: self.product})
        validate_offer_document(offer)  # no raise

    def test_offer_rejects_a_malformed_semantic_model_cache(self):
        offer = copy.deepcopy(self.offer)
        offer["semantic_model"] = {"facts": {}, "interpretation": {"source": "vibes"}}
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(offer)

    def test_accepts_universal_bundle_fixtures(self):
        validate_product_document(load_fixture("product-universal-bundle.json"))
        validate_offer_document(load_fixture("offer-universal-bundle.json"))
        validate_page_document(load_fixture("page-universal-bundle.json"))

    def test_accepts_lead_capture_product_fixture(self):
        validate_product_document(load_fixture("product-lead-capture-email.json"))

    def test_accepts_product_identifier_fields(self):
        self.product.update({"brand": "Apple", "mpn": "MPXQ2LL/A", "gtin": "0190198611086"})
        validate_product_document(self.product)

    def test_rejects_invalid_gtin_check_digit(self):
        self.product["gtin"] = "0190198611087"  # bad check digit
        with self.assertRaises(DocumentValidationError):
            validate_product_document(self.product)

    def test_rejects_overlong_brand(self):
        self.product["brand"] = "A" * 71
        with self.assertRaises(DocumentValidationError):
            validate_product_document(self.product)

    def test_accepts_optional_image_dims_sidecar(self):
        self.product["image_dims"] = {"https://images.juniorbay.com/products/ABC123": [1920, 1280]}
        validate_product_document(self.product)

    def _user_profile(self):
        return {
            "schema_version": "2026-05-29", "document_type": "user_profile",
            "tenant_id": "t1", "user_id": "u1", "email": "a@b.com", "display_name": "Ada",
        }

    def test_accepts_business_identity_block(self):
        doc = self._user_profile()
        doc["business"] = {
            "name": "Luxe Spa", "brands": ["Luxe", "Luxe Wellness"], "phone": "+1 555 0100",
            "address": {"street": "75 S 100 E", "locality": "St. George", "region": "UT",
                        "postal_code": "84770", "country": "US"},
        }
        validate_user_profile(doc)

    def test_accepts_profile_without_business(self):
        validate_user_profile(self._user_profile())

    def test_rejects_malformed_business_identity(self):
        for bad in ({"brands": "Luxe"}, {"brands": [1, 2]}, {"address": "75 S 100 E"}, {"name": 5}):
            doc = self._user_profile()
            doc["business"] = bad
            with self.assertRaises(DocumentValidationError):
                validate_user_profile(doc)

    def test_normalize_e164_strips_formatting_and_recovers_country_code(self):
        self.assertEqual(normalize_e164("+1 (206) 565-4418"), "+12065654418")
        self.assertEqual(normalize_e164("0044 20 7946 0018"), "+442079460018")
        self.assertEqual(normalize_e164("12065654418"), "+12065654418")  # NANP: 1 + 10 digits → +1
        self.assertEqual(normalize_e164("(206) 565-4418"), "+12065654418")  # bare 10-digit NANP → +1
        self.assertEqual(normalize_e164(""), "")
        self.assertEqual(normalize_e164("5554418"), "5554418")  # too short for NANP → left for validation

    def test_business_phone_is_normalized_in_place_to_e164(self):
        doc = self._user_profile()
        doc["business"] = {"name": "Luxe Spa", "phone": "12065654418"}  # legacy value the user reported
        validate_user_profile(doc)
        self.assertEqual(doc["business"]["phone"], "+12065654418")

    def test_business_phone_that_is_not_recoverable_is_rejected(self):
        # A fragment too short to be a NANP number (and no +) can't be attributed to a country.
        doc = self._user_profile()
        doc["business"] = {"name": "Luxe Spa", "phone": "555-4418"}
        with self.assertRaises(DocumentValidationError):
            validate_user_profile(doc)

    def test_site_organization_telephone_is_normalized_to_e164(self):
        site = self._site(organization={"name": "Axel Mart", "telephone": "+1 206-565-4418"})
        validate_site(site)
        self.assertEqual(site["organization"]["telephone"], "+12065654418")

    def test_site_organization_telephone_rejects_non_e164(self):
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(organization={"name": "Axel Mart", "telephone": "555-4418"}))

    def test_normalize_country_maps_to_alpha2(self):
        self.assertEqual(normalize_country("United States"), "US")
        self.assertEqual(normalize_country("U.S.A."), "US")
        self.assertEqual(normalize_country("united kingdom"), "GB")
        self.assertEqual(normalize_country("us"), "US")
        self.assertEqual(normalize_country("US"), "US")
        self.assertEqual(normalize_country(""), "")
        self.assertEqual(normalize_country("Freedonia"), "Freedonia")  # unknown passes through unchanged

    def test_business_address_country_is_normalized_to_alpha2(self):
        doc = self._user_profile()
        doc["business"] = {"name": "Axel Mart", "address": {"locality": "Denver", "country": "United States"}}
        validate_user_profile(doc)
        self.assertEqual(doc["business"]["address"]["country"], "US")

    def test_site_organization_address_country_is_normalized_to_alpha2(self):
        site = self._site(organization={"name": "Axel Mart", "address": {"locality": "Denver", "country": "United States"}})
        validate_site(site)
        self.assertEqual(site["organization"]["address"]["country"], "US")

    def test_site_organization_local_fields_accept_valid_data(self):
        validate_site(self._site(organization={
            "name": "Luxe Spa", "geo": {"latitude": 39.7, "longitude": -104.9},
            "place_id": "ChIJ123", "gbp_url": "https://maps.google.com/?cid=1",
            "opening_hours": [{"days": ["Monday", "Friday"], "opens": "09:00", "closes": "17:30"}],
        }))

    def test_site_organization_rejects_bad_hours_and_gbp_url(self):
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(organization={"name": "X", "opening_hours": [{"days": ["Monday"], "opens": "9am", "closes": "5pm"}]}))
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(organization={"name": "X", "opening_hours": [{"days": ["Funday"], "opens": "09:00", "closes": "17:00"}]}))
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(organization={"name": "X", "gbp_url": "not-a-url"}))

    def test_site_organization_business_type_accepts_and_rejects(self):
        validate_site(self._site(organization={"name": "X", "entity_type": "HealthAndBeautyBusiness", "business_type": "Dentist"}))
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(organization={"name": "X", "business_type": "NotARealType"}))

    def test_accepts_offer_presentation_brand(self):
        self.offer.setdefault("presentation", {})["brand"] = "Luxe Wellness"
        validate_offer_document(self.offer)

    def test_accepts_image_dims_from_dynamodb_as_decimals(self):
        # Numbers round-tripped through DynamoDB come back as Decimal — publish validates that shape.
        from decimal import Decimal
        self.product["image_dims"] = {"https://images.juniorbay.com/products/ABC123": [Decimal("1920"), Decimal("1280")]}
        validate_product_document(self.product)

    def test_rejects_malformed_image_dims(self):
        for bad in ([1920], [1920, "tall"], [0, 100], [1920, 1280, 1], "1920x1280", [True, 100]):
            self.product["image_dims"] = {"https://images.juniorbay.com/products/ABC123": bad}
            with self.assertRaises(DocumentValidationError):
                validate_product_document(self.product)
        self.product["image_dims"] = ["not", "a", "map"]
        with self.assertRaises(DocumentValidationError):
            validate_product_document(self.product)

    def _site(self, **kw):
        site = {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_ABC123",
            "tenant_id": "t1", "environment": "live", "name": "Axel Mart", "status": "active",
            "hosting": {"type": "platform", "platform_hostname": "axel-mart.jbay.uk", "custom_domain": None},
            "organization": {"name": "Axel Mart", "entity_type": "OnlineStore"},
            "indexing": {"eligibility": "blocked"},
            "pages": {"/": {"page_id": "page_home01", "page_type": "landing", "enabled": True}},
            "created_at": 1, "updated_at": 1,
        }
        site.update(kw)
        return site

    def test_same_as_host_whitelist_and_cap(self):
        validate_site(self._site(organization={"name": "X", "entity_type": "OnlineStore",
                                               "same_as": [{"url": "https://instagram.com/x", "verified": True}]}))
        with self.assertRaisesRegex(DocumentValidationError, "not an allowed profile host"):
            validate_site(self._site(organization={"name": "X", "entity_type": "OnlineStore",
                                                   "same_as": [{"url": "https://evil.example.com/x"}]}))
        with self.assertRaisesRegex(DocumentValidationError, "at most 6"):
            validate_site(self._site(organization={"name": "X", "entity_type": "OnlineStore",
                                                   "same_as": [{"url": f"https://instagram.com/{i}"} for i in range(7)]}))

    def test_accepts_platform_and_custom_sites(self):
        validate_site(self._site())
        validate_site(self._site(
            hosting={"type": "custom", "platform_hostname": "a.jbay.uk", "custom_domain": "axelmart.com",
                     "verification": {"verified": True}},
            indexing={"eligibility": "eligible"}))

    def test_rejects_custom_hosting_without_domain(self):
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(hosting={"type": "custom", "platform_hostname": "a.jbay.uk", "custom_domain": None}))

    def test_accepts_site_with_decimal_timestamps_from_dynamodb(self):
        # A Site read back from DynamoDB (then re-validated on domain connect) carries Decimal timestamps.
        from decimal import Decimal
        validate_site(self._site(created_at=Decimal("1784600000"), updated_at=Decimal("1784600000")))
        with self.assertRaises(DocumentValidationError):
            validate_site(self._site(created_at=Decimal("1784600000.5")))

    def test_accepts_site_with_no_pages(self):
        # The Site is the aggregate root; it can exist before any pages attach.
        validate_site(self._site(pages={}))
        site = self._site()
        del site["pages"]
        validate_site(site)

    def test_rejects_bad_site_shapes(self):
        for bad in ({"status": "live"}, {"environment": "prod"}, {"pages": "not-a-map"},
                    {"pages": {"/": {"page_id": "nope"}}}, {"site_id": "s_1"}):
            with self.assertRaises(DocumentValidationError):
                validate_site(self._site(**bad))

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

    def test_product_accepts_archived_status(self):
        product = copy.deepcopy(self.product)
        product["status"] = "archived"

        validate_product_document(product)

    def test_product_requires_status(self):
        product = copy.deepcopy(self.product)
        product.pop("status")

        with self.assertRaisesRegex(DocumentValidationError, "Product status"):
            validate_product_document(product)

    def test_product_rejects_invalid_status(self):
        product = copy.deepcopy(self.product)
        product["status"] = "inactive"

        with self.assertRaisesRegex(DocumentValidationError, "Product status"):
            validate_product_document(product)

    def test_product_requires_category(self):
        product = copy.deepcopy(self.product)
        product["product_category"] = ""

        with self.assertRaisesRegex(DocumentValidationError, "product_category"):
            validate_product_document(product)

    def test_product_accepts_transaction_intent(self):
        product = copy.deepcopy(self.product)
        product["product_intent"] = "transaction"

        validate_product_document(product)

    def test_product_rejects_legacy_transactional_intent(self):
        product = copy.deepcopy(self.product)
        product["product_intent"] = "transactional"

        with self.assertRaisesRegex(DocumentValidationError, "product_intent"):
            validate_product_document(product)

    def test_product_requires_lead_capture_for_lead_gen(self):
        product = copy.deepcopy(self.product)
        product["product_intent"] = "lead_gen"

        with self.assertRaisesRegex(DocumentValidationError, "lead_capture"):
            validate_product_document(product)

    def test_product_accepts_lead_capture_target_action(self):
        product = copy.deepcopy(self.product)
        product["product_intent"] = "lead_gen"
        product["lead_capture"] = {
            "action": "external_url",
            "title": "Learn more on our website",
            "description": "You'll be taken to an external page.",
            "target": {
                "type": "url",
                "value": "https://example.com/landing",
                "open": "new_tab",
            },
        }

        validate_product_document(product)

    def test_product_rejects_incomplete_lead_capture_target(self):
        product = copy.deepcopy(self.product)
        product["product_intent"] = "lead_gen"
        product["lead_capture"] = {
            "action": "call_number",
            "title": "Talk to someone now",
            "description": "Tap to call our team directly.",
            "target": {
                "type": "phone",
            },
        }

        with self.assertRaisesRegex(DocumentValidationError, "lead_capture.target.value"):
            validate_product_document(product)

    def test_product_rejects_legacy_active(self):
        product = copy.deepcopy(self.product)
        product["active"] = True

        with self.assertRaisesRegex(DocumentValidationError, "Product active"):
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

    def test_product_rejects_redundant_price_product_id(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["product_id"] = product["product_id"]

        with self.assertRaisesRegex(DocumentValidationError, "price.product_id"):
            validate_product_document(product)

    def test_product_rejects_redundant_price_stripe_mode(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["stripe_mode"] = "test"

        with self.assertRaisesRegex(DocumentValidationError, "price.stripe_mode"):
            validate_product_document(product)

    def test_product_rejects_price_active(self):
        product = copy.deepcopy(self.product)
        product["prices"][0]["active"] = True

        with self.assertRaisesRegex(DocumentValidationError, "price.active"):
            validate_product_document(product)

    def test_product_canonicalizer_strips_legacy_runtime_fields(self):
        product = copy.deepcopy(self.product)
        product["active"] = True
        product["prices"][0]["product_id"] = product["product_id"]
        product["prices"][0]["stripe_mode"] = "test"
        product["prices"][0]["active"] = True
        product["prices"][0]["metadata"] = {"items": str(product["prices"][0]["quantity"])}

        canonical = canonical_product_document(product)

        self.assertNotIn("active", canonical)
        self.assertEqual(canonical["status"], "active")
        self.assertNotIn("product_id", canonical["prices"][0])
        self.assertNotIn("stripe_mode", canonical["prices"][0])
        self.assertNotIn("active", canonical["prices"][0])
        self.assertNotIn("metadata", canonical["prices"][0])

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

    def test_offer_accepts_funnel_block(self):
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {
            "order_bumps": [{"product_id": "prod_x", "price_id": "price_x"}],
            "upsells": [{"product_id": "prod_y", "price_id": "price_y"}],
        }
        validate_offer_document(offer)  # no raise

    def test_offer_rejects_funnel_entry_missing_price(self):
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"order_bumps": [{"product_id": "prod_x"}]}
        with self.assertRaisesRegex(DocumentValidationError, "order_bumps price_id"):
            validate_offer_document(offer)

    def _opportunity_offer(self, opportunities):
        offer = copy.deepcopy(self.offer)
        offer.pop("items", None)
        offer["purchase_opportunities"] = opportunities
        return offer

    def test_offer_accepts_purchase_opportunities_instead_of_items(self):
        validate_offer_document(self._opportunity_offer([
            {"stage": "landing", "placement": {"surface": "primary"}, "product_id": "p", "price_id": "pr", "quantity": 1},
            {"stage": "checkout", "placement": {"surface": "order_bump"}, "product_id": "b", "price_id": "pb", "quantity": 1},
        ]))  # no raise

    def test_offer_requires_items_or_opportunities(self):
        offer = copy.deepcopy(self.offer)
        offer.pop("items", None)
        with self.assertRaisesRegex(DocumentValidationError, "purchase_opportunities or a non-empty items"):
            validate_offer_document(offer)

    def test_opportunity_rejects_bad_stage(self):
        with self.assertRaisesRegex(DocumentValidationError, "stage"):
            validate_offer_document(self._opportunity_offer([{"stage": "wat", "product_id": "p", "price_id": "pr", "quantity": 1}]))

    def test_opportunity_rejects_bad_placement_surface(self):
        with self.assertRaisesRegex(DocumentValidationError, "surface"):
            validate_offer_document(self._opportunity_offer([
                {"stage": "checkout", "placement": {"surface": "wat"}, "product_id": "p", "price_id": "pr", "quantity": 1},
            ]))

    def test_offer_rejects_ui_only_fields(self):
        offer = load_fixture("offer-universal-bundle.json")
        offer["offer_type"] = "single_product"
        offer["intentLabel"] = "Transaction"
        offer["image"] = "https://images.example.com/offer.webp"
        offer["productSummary"] = "prod_demo"

        with self.assertRaisesRegex(DocumentValidationError, "UI-only fields"):
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

    def test_page_accepts_sale_and_flash_sale_blocks(self):
        page = copy.deepcopy(self.page)
        page["sale"] = {"enabled": True}  # no ends_at = perpetual
        page["flash_sale"] = {"enabled": True, "starts_on": 1000, "ends_at": 2000}
        validate_page_document(page)

    def test_page_flash_sale_enabled_requires_expiration(self):
        page = copy.deepcopy(self.page)
        page["flash_sale"] = {"enabled": True}
        with self.assertRaisesRegex(DocumentValidationError, "must set an expiration date"):
            validate_page_document(page)

    def test_page_flash_sale_start_must_precede_end(self):
        page = copy.deepcopy(self.page)
        page["flash_sale"] = {"enabled": True, "starts_on": 5000, "ends_at": 2000}
        with self.assertRaisesRegex(DocumentValidationError, "starts_on must be before ends_at"):
            validate_page_document(page)

    def test_page_flash_sale_disabled_needs_no_expiration(self):
        page = copy.deepcopy(self.page)
        page["flash_sale"] = {"enabled": False}  # a saved-but-off flash sale is fine
        validate_page_document(page)

    def test_page_sale_must_be_object(self):
        page = copy.deepcopy(self.page)
        page["sale"] = "yes"
        with self.assertRaisesRegex(DocumentValidationError, "Page sale must be an object"):
            validate_page_document(page)

    def test_page_rejects_selector_for_different_offer(self):
        page = copy.deepcopy(self.page)
        page["sections"][1]["offer_id"] = "offer_other"

        with self.assertRaisesRegex(DocumentValidationError, "must match page offer_id"):
            validate_page_document(page)

    def test_storefront_page_with_catalog_grid_needs_no_offer_id(self):
        page = copy.deepcopy(self.page)
        page.pop("offer_id", None)
        page["sections"] = [
            {"id": "h", "type": "brand_hero", "headline": "My Store", "tagline": "Great stuff"},
            {"id": "g", "type": "catalog_grid", "heading": "Shop", "items": [{"offer_id": "offer_x", "slug": "/thing"}]},
        ]
        validate_page_document(page)  # offer-less catalog page is valid

    def test_catalog_grid_item_requires_offer_id(self):
        page = copy.deepcopy(self.page)
        page.pop("offer_id", None)
        page["sections"] = [{"id": "g", "type": "catalog_grid", "items": [{"slug": "/thing"}]}]
        with self.assertRaisesRegex(DocumentValidationError, "item offer_id"):
            validate_page_document(page)

    def test_non_catalog_page_still_requires_offer_id(self):
        page = copy.deepcopy(self.page)
        page.pop("offer_id", None)
        with self.assertRaisesRegex(DocumentValidationError, "offer_id"):
            validate_page_document(page)

    def test_page_rejects_preview_status(self):
        page = copy.deepcopy(self.page)
        page["status"] = "preview"

        with self.assertRaisesRegex(DocumentValidationError, "status"):
            validate_page_document(page)

    def test_page_accepts_inline_post_checkout_routing(self):
        page = copy.deepcopy(self.page)
        page["post_checkout"] = {
            "thank_you_page": {"page_id": "page_thank_you"},
            "funnel_steps": [
                {
                    "step_id": "upsell_1",
                    "page_id": "page_upsell_1",
                    "on_accept": "upsell_2",
                    "on_decline": "thank_you",
                },
                {
                    "step_id": "upsell_2",
                    "page_id": "page_upsell_2",
                    "on_accept": "thank_you",
                    "on_decline": "thank_you",
                },
            ],
        }

        validate_page_document(page)

    def test_page_accepts_external_funnel_post_checkout_routing(self):
        page = copy.deepcopy(self.page)
        page["post_checkout"] = {"funnel_id": "funnel_summer_bundle"}

        validate_page_document(page)

    def test_page_rejects_mixed_post_checkout_routing(self):
        page = copy.deepcopy(self.page)
        page["post_checkout"] = {
            "funnel_id": "funnel_summer_bundle",
            "thank_you_page": {"page_id": "page_thank_you"},
        }

        with self.assertRaisesRegex(DocumentValidationError, "either funnel_id or inline"):
            validate_page_document(page)

    def test_page_rejects_unknown_funnel_step_target(self):
        page = copy.deepcopy(self.page)
        page["post_checkout"] = {
            "thank_you_page": {"page_id": "page_thank_you"},
            "funnel_steps": [
                {
                    "step_id": "upsell_1",
                    "page_id": "page_upsell_1",
                    "on_accept": "missing_step",
                    "on_decline": "thank_you",
                }
            ],
        }

        with self.assertRaisesRegex(DocumentValidationError, "missing_step"):
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

    def test_page_accepts_hex_and_rgba_theme_tokens(self):
        # Advanced Color Settings overrides: hex + rgba (preset tokens aren't all hex) are both valid.
        page = load_fixture("page-universal-bundle.json")
        page["theme"]["tokens"] = {"brand": "#0077b5", "trust_badge_bg": "rgba(0,119,181,.1)", "cta_from": "#005582"}
        validate_page_document(page)  # must not raise

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

    def test_page_accepts_a_supported_goal(self):
        # The goal axis: offer_type x goal composition (plans/LANDING_PAGE_GOAL_COMPOSITION.md).
        page = load_fixture("page-creatine-standard.json")
        page["goal"] = "search_seo"
        validate_page_document(page)

    def test_page_rejects_an_unknown_goal(self):
        page = load_fixture("page-creatine-standard.json")
        page["goal"] = "carrier_pigeon"
        with self.assertRaisesRegex(DocumentValidationError, "Page goal"):
            validate_page_document(page)

    def test_page_without_a_goal_is_still_valid(self):
        # Pages created before the goal axis must keep validating — goal is optional, never backfilled.
        page = load_fixture("page-creatine-standard.json")
        page.pop("goal", None)
        validate_page_document(page)

    def test_page_rejects_invalid_faq_item(self):
        page = load_fixture("page-universal-bundle.json")
        faq = next(section for section in page["sections"] if section["type"] == "faq")
        faq["items"][0].pop("answer")

        with self.assertRaisesRegex(DocumentValidationError, "FAQ answer"):
            validate_page_document(page)


if __name__ == "__main__":
    unittest.main()
