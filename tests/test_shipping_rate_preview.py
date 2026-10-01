"""Discovering real carrier services, instead of inventing codes that can never be quoted.

plans/SHIPPING_ELEMENT.md. The author, 2026-09-30: let a tenant pick products and a box, ask for rates, and
adopt one as a Service.

**What it is for is the service IDENTITY, not the price.** A code a tenant invents never matches a real rate --
Shippo's token for USPS ground is `usps_ground_advantage`, and "ground" can never be quoted, with nothing to
say so until a buyer sees no options. The amounts are context for setting a flat rate; they are deliberately
not written anywhere, because a rate is destination-specific and stale within days while the token is stable.
"""
import json
import unittest

import handlers.shipping as shipping
from handlers.shipping import preview_rates

SHIP_FROM = {"name": "Keith", "street1": "1 Main", "city": "Denver", "state": "CO",
             "postal_code": "80204", "country": "US"}
BOXES = [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15},
         {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}]
PRODUCT = {"product_id": "p1", "name": "Gummies",
           "fulfillment": {"requires_shipping": True, "weight_lb": 0.5,
                           "item_dimensions": {"length_in": 3, "width_in": 2, "height_in": 2,
                                               "weight_lb": 0.4}}}
UNMEASURED = {"product_id": "p2", "name": "Mystery", "fulfillment": {"requires_shipping": True}}
RATES = [
    {"carrier": "ups", "service": "2nd Day Air", "service_token": "ups_2nd_day_air",
     "amount": 1731, "currency": "usd", "estimated_days": 2, "rate_id": "r2"},
    {"carrier": "usps", "service": "Ground Advantage", "service_token": "usps_ground_advantage",
     "amount": 842, "currency": "usd", "estimated_days": 6, "rate_id": "r1"},
]


class ConfigRepo:
    def __init__(self, **overrides):
        self.config = {"ship_from_address": dict(SHIP_FROM), "boxes": [dict(b) for b in BOXES],
                       "provider": {"name": "shippo", "api_key_ref": "ref"}}
        self.config.update(overrides)

    def get(self, tenant_id):
        return self.config


class ProductRepo:
    def __init__(self, products=None):
        self.products = products or {"p1": PRODUCT, "p2": UNMEASURED}

    def get(self, tenant_id, product_id):
        return self.products.get(product_id)


class Cipher:
    def decrypt(self, ref, **kwargs):
        return "sk_test"


def call(payload, config=None, products=None, provider=None):
    captured = {}

    class Provider:
        def rates(self, **kwargs):
            captured.update(kwargs)
            if provider == "error":
                raise shipping.ProviderError("Shippo said no.")
            if provider == "boom":
                raise RuntimeError("socket")
            return [dict(r) for r in RATES]

    real = shipping.provider_for
    shipping.provider_for = lambda *args, **kwargs: Provider()
    try:
        response = preview_rates(
            {"httpMethod": "POST", "queryStringParameters": {"tenant_id": "t1"},
             "body": json.dumps(payload)},
            config or ConfigRepo(), Cipher(), products_repo=ProductRepo(products))
    finally:
        shipping.provider_for = real
    return response, json.loads(response["body"]), captured


class ItReturnsRealServiceTokens(unittest.TestCase):
    def test_rates_come_back_cheapest_first(self):
        _, body, _ = call({"product_ids": ["p1"]})
        self.assertEqual([r["amount"] for r in body["rates"]], [842, 1731])

    def test_each_rate_carries_the_carriers_OWN_service_token(self):
        """The whole point. A tenant cannot type `usps_ground_advantage` from memory, and `ground` -- which
        they would type -- never matches a rate."""
        _, body, _ = call({"product_ids": ["p1"]})
        self.assertEqual(body["rates"][0]["service_token"], "usps_ground_advantage")

    def test_it_reports_the_parcel_it_rated(self):
        _, body, _ = call({"product_ids": ["p1"]})
        self.assertEqual(body["parcel"]["box"], "Small")
        self.assertEqual(body["parcel_count"], 1)


class TheSampleDestination(unittest.TestCase):
    def test_it_defaults_to_the_tenants_own_ship_from(self):
        """A sample needs to be REAL -- a carrier will not quote a postcode that does not exist, and inventing
        one would fail in a way that looks like our bug."""
        _, body, captured = call({"product_ids": ["p1"]})
        self.assertEqual(captured["to_address"]["postal_code"], "80204")
        self.assertEqual(body["destination"], {"country": "US", "postal_code": "80204"})

    def test_a_typed_destination_overrides_it(self):
        _, body, captured = call({"product_ids": ["p1"],
                                  "to_address": {"country": "CA", "postal_code": "M5V 2T6"}})
        self.assertEqual(captured["to_address"]["postal_code"], "M5V 2T6")
        self.assertEqual(captured["to_address"]["country"], "CA")

    def test_a_partial_destination_keeps_the_rest_of_the_address(self):
        """A carrier needs a whole address; only the parts the tenant changed should move."""
        _, _, captured = call({"product_ids": ["p1"], "to_address": {"postal_code": "90210"}})
        self.assertEqual(captured["to_address"]["city"], "Denver")
        self.assertEqual(captured["to_address"]["postal_code"], "90210")

    def test_no_ship_from_is_refused_with_something_actionable(self):
        response, body, _ = call({"product_ids": ["p1"]}, ConfigRepo(ship_from_address={}))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"], "missing_ship_from")


class WhatItRates(unittest.TestCase):
    def test_quantities_are_honoured(self):
        _, _, captured = call({"product_ids": ["p1"], "quantities": {"p1": 12}})
        self.assertEqual(captured["parcel"]["box"], "Medium")

    def test_a_named_box_is_rated_rather_than_the_packers_preference(self):
        """A tenant comparing boxes wants THIS box priced."""
        _, body, _ = call({"product_ids": ["p1"], "box": "Medium"})
        self.assertEqual(body["parcel"]["box"], "Medium")

    def test_products_with_no_dimensions_are_refused_with_the_fix(self):
        response, body, _ = call({"product_ids": ["p2"]})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"], "no_dimensions")
        self.assertIn("Products", body["message"])

    def test_no_products_is_refused(self):
        response, body, _ = call({"product_ids": []})
        self.assertEqual(body["error"], "missing_products")

    def test_an_unknown_product_is_a_404(self):
        response, _, _ = call({"product_ids": ["nope"]})
        self.assertEqual(response["statusCode"], 404)


class FailuresAreAnswersNotFiveHundreds(unittest.TestCase):
    def test_no_provider_says_to_connect_one(self):
        response, body, _ = call({"product_ids": ["p1"]}, ConfigRepo(provider={}))
        self.assertEqual(body["error"], "missing_provider")

    def test_a_provider_error_is_relayed(self):
        response, body, _ = call({"product_ids": ["p1"]}, provider="error")
        self.assertEqual(response["statusCode"], 502)
        self.assertIn("Shippo", body["message"])

    def test_an_unexpected_failure_is_still_a_502(self):
        response, body, _ = call({"product_ids": ["p1"]}, provider="boom")
        self.assertEqual(response["statusCode"], 502)
        self.assertIn("RuntimeError", body["message"])


class ThePriceIsContextNotData(unittest.TestCase):
    SCREEN = None

    def setUp(self):
        import pathlib
        self.SCREEN = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"
                       / "Shipping.vue").read_text(encoding="utf-8")

    def test_adopting_a_rate_copies_the_service_not_the_amount(self):
        body = self.SCREEN.split("function adoptRate", 1)[1].split("\nfunction", 1)[0]
        self.assertIn("service_token: rate.service_token", body)
        self.assertIn("carrier:", body)
        self.assertNotIn("amount", body)


if __name__ == "__main__":
    unittest.main()
