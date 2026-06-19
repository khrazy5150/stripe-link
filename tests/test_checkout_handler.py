import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs

from handlers.checkout import handler


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeRepository:
    def __init__(self, id_field, documents):
        self.id_field = id_field
        self.documents = {
            (document["tenant_id"], document[id_field]): document
            for document in documents
        }

    def get(self, tenant_id, document_id):
        return self.documents.get((tenant_id, document_id))


class FakeStripeKeysRepository:
    def get(self, tenant_id, mode="test"):
        return {
            "tenant_id": tenant_id,
            "mode": mode,
            "secret_key_ref": "sk_test_demo",
        }


class FakeCipher:
    def decrypt(self, secret_ref, *, tenant_id, mode, field):
        return secret_ref


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({"url": "https://checkout.stripe.com/c/pay/session"}).encode("utf-8")


class CheckoutHandlerTests(unittest.TestCase):
    def setUp(self):
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.requests = []

    def opener(self, request, timeout=20):
        self.requests.append(request)
        return FakeResponse()

    def test_checkout_redirects_to_stripe_session_for_local_offer_price(self):
        response = handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {
                    "clientID": "tenant_demo",
                    "offer": "offer_simple_coffee",
                    "page_id": "page_simple_coffee",
                    "product_id": "prod_simple_coffee",
                    "price_id": "price_simple_coffee",
                    "success_url": "https://pages.example.com/thanks",
                    "cancel_url": "https://pages.example.com/buy",
                },
            },
            None,
            offers_repo=FakeRepository("offer_id", [self.offer]),
            products_repo=FakeRepository("product_id", [self.product]),
            stripe_repo=FakeStripeKeysRepository(),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        self.assertEqual(response["statusCode"], 303)
        self.assertEqual(response["headers"]["Location"], "https://checkout.stripe.com/c/pay/session")
        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        self.assertEqual(payload["mode"], ["payment"])
        self.assertEqual(payload["success_url"], ["https://pages.example.com/thanks"])
        self.assertEqual(payload["line_items[0][price_data][product_data][name]"], ["Simple Coffee"])
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], ["1800"])
        self.assertEqual(payload["line_items[0][quantity]"], ["1"])
        self.assertEqual(payload["metadata[clientID]"], ["tenant_demo"])
        self.assertEqual(payload["metadata[page_id]"], ["page_simple_coffee"])
        self.assertEqual(payload["metadata[offer_id]"], ["offer_simple_coffee"])
        self.assertEqual(payload["metadata[product_id]"], ["prod_simple_coffee"])
        self.assertEqual(payload["metadata[price_id]"], ["price_simple_coffee"])

    def test_checkout_uses_selected_price_for_selectable_offer(self):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")

        handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "offer": "offer_creatine_standard",
                    "product_id": "prod_creatine_gummies",
                    "price_id": "price_6bottle",
                    "success_url": "https://pages.example.com/thanks",
                    "cancel_url": "https://pages.example.com/buy",
                },
            },
            None,
            offers_repo=FakeRepository("offer_id", [offer]),
            products_repo=FakeRepository("product_id", [product]),
            stripe_repo=FakeStripeKeysRepository(),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], ["14900"])
        self.assertEqual(payload["line_items[0][quantity]"], ["1"])


if __name__ == "__main__":
    unittest.main()
