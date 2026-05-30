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
        self.offer = load_fixture("offer-creatine-standard.json")

    def test_create_offer_persists_selectable_price_offer(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        item = body["offer"]["items"][0]
        self.assertEqual(item["default_price_id"], "price_2bottle")
        self.assertEqual(len(item["selectable_prices"]), 4)

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

    def test_create_offer_rejects_item_with_fixed_and_selectable_prices(self):
        self.offer["items"][0]["price_id"] = "price_2bottle"
        self.offer["items"][0]["quantity"] = 1

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_offer")


if __name__ == "__main__":
    unittest.main()
