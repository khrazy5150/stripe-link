import json
import unittest
from pathlib import Path

from handlers.offers import handler
from tests.fakes import FakeDocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OfferCrudHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products.put(self.product)

    def test_create_offer_persists_selectable_price_offer(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        item = body["offer"]["items"][0]
        self.assertEqual(item["default_price_id"], "price_2bottle")
        self.assertEqual(len(item["selectable_prices"]), 4)

    def test_update_offer_status_archives_and_restores(self):
        self.repository.put(self.offer)
        tenant_id = self.offer["tenant_id"]
        offer_id = self.offer["offer_id"]

        def patch(status):
            return handler({
                "httpMethod": "PATCH",
                "pathParameters": {"offer_id": offer_id},
                "body": json.dumps({"status": status, "tenant_id": tenant_id}),
            }, None, repository=self.repository, products_repo=self.products)

        archived = patch("archived")
        self.assertEqual(archived["statusCode"], 200)
        self.assertEqual(self.repository.get(tenant_id, offer_id)["status"], "archived")
        restored = patch("active")
        self.assertEqual(json.loads(restored["body"])["offer"]["status"], "active")

    def test_update_offer_status_rejects_invalid_status(self):
        self.repository.put(self.offer)
        response = handler({
            "httpMethod": "PATCH",
            "pathParameters": {"offer_id": self.offer["offer_id"]},
            "body": json.dumps({"status": "deleted", "tenant_id": self.offer["tenant_id"]}),
        }, None, repository=self.repository, products_repo=self.products)
        self.assertEqual(response["statusCode"], 400)

    def test_get_and_list_offers(self):
        self.repository.put(self.offer)

        get_response = handler({
            "httpMethod": "GET",
            "pathParameters": {"offer_id": "offer_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)
        list_response = handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(get_response["statusCode"], 200)
        self.assertEqual(json.loads(get_response["body"])["offer"]["offer_id"], "offer_creatine_standard")
        self.assertEqual(json.loads(list_response["body"])["offers"][0]["offer_id"], "offer_creatine_standard")

    def test_delete_offer_removes_document(self):
        self.repository.put(self.offer)

        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"offer_id": "offer_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["deleted"])
        self.assertIsNone(self.repository.get("tenant_demo", "offer_creatine_standard"))

    def test_delete_offer_returns_404_when_missing(self):
        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"offer_id": "missing_offer"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(json.loads(response["body"])["error"], "not_found")

    def test_create_offer_rejects_item_with_fixed_and_selectable_prices(self):
        self.offer["items"][0]["price_id"] = "price_2bottle"
        self.offer["items"][0]["quantity"] = 1

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_offer")

    def test_create_offer_rejects_mixed_product_intents(self):
        lead_product = load_fixture("product-lead-capture-email.json")
        self.products.put(lead_product)
        self.offer["items"].append({
            "product_id": lead_product["product_id"],
            "price_id": lead_product["default_price_id"],
            "quantity": 1,
            "presentation_context": "primary",
        })

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "invalid_offer")
        self.assertIn("product_intent", body["message"])


if __name__ == "__main__":
    unittest.main()
