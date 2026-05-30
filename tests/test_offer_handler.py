import json
import unittest
from pathlib import Path

from handlers.offers import resolve_handler


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OfferHandlerTests(unittest.TestCase):
    def test_resolve_handler_returns_resolved_offer(self):
        product = load_fixture("product-creatine-gummies.json")
        offer = load_fixture("offer-creatine-standard.json")

        response = resolve_handler({
            "body": json.dumps({
                "offer": offer,
                "products": [product],
            })
        }, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["resolved_offer"]["subtotal"], 6700)
        self.assertEqual(body["resolved_offer"]["items"][0]["price_id"], "price_2bottle")

    def test_resolve_handler_uses_selected_price(self):
        product = load_fixture("product-creatine-gummies.json")
        offer = load_fixture("offer-creatine-standard.json")

        response = resolve_handler({
            "body": json.dumps({
                "offer": offer,
                "products": [product],
                "selected_prices": {
                    "prod_creatine_gummies": "price_6bottle"
                }
            })
        }, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["resolved_offer"]["subtotal"], 14900)
        self.assertEqual(body["resolved_offer"]["items"][0]["price_id"], "price_6bottle")

    def test_resolve_handler_returns_pricing_error(self):
        product = load_fixture("product-creatine-gummies.json")
        offer = load_fixture("offer-creatine-standard.json")

        response = resolve_handler({
            "body": json.dumps({
                "offer": offer,
                "products": [product],
                "selected_prices": {
                    "prod_creatine_gummies": "missing"
                }
            })
        }, None)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "pricing_error")


if __name__ == "__main__":
    unittest.main()
