import json
import unittest
from pathlib import Path

from handlers.products import handler
from tests.fakes import FakeDocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ProductHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("product_id")
        self.product = load_fixture("product-creatine-gummies.json")

    def test_options_returns_cors_headers(self):
        response = handler({"httpMethod": "OPTIONS"}, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
        self.assertIn("X-Tenant-Id", response["headers"]["Access-Control-Allow-Headers"])
        self.assertIn("POST", response["headers"]["Access-Control-Allow-Methods"])

    def test_create_product_persists_canonical_json(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.product),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        product = body["product"]
        stored = self.repository.get("tenant_demo", "prod_creatine_gummies")
        self.assertEqual(product["product_id"], "prod_creatine_gummies")
        self.assertEqual(product["default_price_id"], "price_2bottle")
        self.assertEqual(body["stripe_sync"], {"status": "skipped", "reason": "document not canonical"})
        self.assertEqual(list(product)[:4], ["schema_version", "document_type", "tenant_id", "product_id"])
        self.assertEqual(list(product)[-1], "tags")
        self.assertEqual(list(stored)[-1], "tags")
        self.assertEqual(stored["default_price_id"], "price_2bottle")

    def test_get_product_requires_tenant(self):
        response = handler({
            "httpMethod": "GET",
            "pathParameters": {"product_id": "prod_creatine_gummies"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)

    def test_get_and_list_products(self):
        self.repository.put(self.product)

        get_response = handler({
            "httpMethod": "GET",
            "pathParameters": {"product_id": "prod_creatine_gummies"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)
        list_response = handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(get_response["statusCode"], 200)
        get_product = json.loads(get_response["body"])["product"]
        list_product = json.loads(list_response["body"])["products"][0]
        self.assertEqual(get_product["product_id"], "prod_creatine_gummies")
        self.assertEqual(list_product["product_id"], "prod_creatine_gummies")
        self.assertEqual(list(get_product)[-1], "tags")
        self.assertEqual(list(list_product)[-1], "tags")

    def test_create_product_rejects_mixed_stripe_modes(self):
        self.product["prices"][0]["stripe_mode"] = "live"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.product),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_product")


if __name__ == "__main__":
    unittest.main()
