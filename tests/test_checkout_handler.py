import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

from handlers.checkout import handler
from stripe_link.domain.fees import clear_config_cache


def order_bump_fixtures():
    product = {
        "schema_version": "2026-05-29",
        "document_type": "product",
        "tenant_id": "tenant_demo",
        "product_id": "prod_insulated_thermos",
        "name": "Insulated Thermos",
        "product_type": "physical",
        "status": "active",
        "prices": [
            {
                "price_id": "price_bump_thermos",
                "stripe_price_id": None,
                "currency": "usd",
                "unit_amount": 500,
                "quantity": 1,
                "context": "order_bump",
            }
        ],
    }
    offer = {
        "schema_version": "2026-05-29",
        "document_type": "offer",
        "tenant_id": "tenant_demo",
        "offer_id": "offer_bump_thermos",
        "slug": "insulated-thermos-bump",
        "name": "Insulated Thermos Add-On",
        "status": "active",
        "product_intent": "transaction",
        "stripe_mode": "test",
        "items": [{"product_id": "prod_insulated_thermos", "price_id": "price_bump_thermos", "quantity": 1}],
        "discount": {"mode": "none"},
        "eligibility": {"allowed_price_contexts": ["order_bump"]},
        "sync": {"status": "pending", "last_synced_at": None, "error": None},
        "created_at": 1780092000,
        "updated_at": 1780092000,
    }
    return offer, product


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


class FakeConnectStripeKeysRepository:
    def get(self, tenant_id, mode="test"):
        return {
            "tenant_id": tenant_id,
            "mode": mode,
            "connect_account_id": "acct_connected_123",
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
        clear_config_cache()

    def tearDown(self):
        clear_config_cache()

    def opener(self, request, timeout=20):
        self.requests.append(request)
        return FakeResponse()

    def test_checkout_blocks_tenant_with_past_due_billing_status(self):
        response = handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {
                    "clientID": "tenant_demo",
                    "offer": "offer_simple_coffee",
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
            tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo", "billing_status": "past_due"}]),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        self.assertEqual(response["statusCode"], 402)
        self.assertEqual(json.loads(response["body"])["error"], "tenant_billing_hold")
        self.assertEqual(self.requests, [])

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
            tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
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
        self.assertEqual(payload["metadata[product_type]"], ["physical"])
        self.assertEqual(payload["metadata[tenant_plan]"], ["basic"])
        self.assertNotIn("payment_intent_data[application_fee_amount]", payload)

    def test_checkout_adds_application_fee_amount_for_connect_direct_charge(self):
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_platform"}, clear=False):
            handler(
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
                stripe_repo=FakeConnectStripeKeysRepository(),
                tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
                secret_cipher=FakeCipher(),
                opener=self.opener,
            )

        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        # 1800 cents at the "basic" tier physical rate (10%) rounds to a 180 cent platform fee.
        self.assertEqual(payload["payment_intent_data[application_fee_amount]"], ["180"])
        self.assertEqual(payload["metadata[product_type]"], ["physical"])
        self.assertEqual(payload["metadata[tenant_plan]"], ["basic"])

    def test_checkout_includes_order_bump_as_additional_line_item(self):
        bump_offer, bump_product = order_bump_fixtures()

        handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {
                    "clientID": "tenant_demo",
                    "offer": "offer_simple_coffee",
                    "product_id": "prod_simple_coffee",
                    "price_id": "price_simple_coffee",
                    "order_bump_ids": "offer_bump_thermos",
                    "success_url": "https://pages.example.com/thanks",
                    "cancel_url": "https://pages.example.com/buy",
                },
            },
            None,
            offers_repo=FakeRepository("offer_id", [self.offer, bump_offer]),
            products_repo=FakeRepository("product_id", [self.product, bump_product]),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], ["1800"])
        self.assertEqual(payload["line_items[1][price_data][unit_amount]"], ["500"])
        self.assertEqual(payload["line_items[1][price_data][product_data][name]"], ["Insulated Thermos"])
        self.assertEqual(payload["line_items[1][quantity]"], ["1"])
        self.assertEqual(payload["metadata[order_bump_ids]"], ["offer_bump_thermos"])
        # Primary product still drives fee/metadata classification, e.g. product_id/price_id.
        self.assertEqual(payload["metadata[product_id]"], ["prod_simple_coffee"])

    def test_checkout_adds_application_fee_amount_including_order_bump_subtotal(self):
        bump_offer, bump_product = order_bump_fixtures()

        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_platform"}, clear=False):
            handler(
                {
                    "httpMethod": "GET",
                    "queryStringParameters": {
                        "clientID": "tenant_demo",
                        "offer": "offer_simple_coffee",
                        "product_id": "prod_simple_coffee",
                        "price_id": "price_simple_coffee",
                        "order_bump_ids": "offer_bump_thermos",
                        "success_url": "https://pages.example.com/thanks",
                        "cancel_url": "https://pages.example.com/buy",
                    },
                },
                None,
                offers_repo=FakeRepository("offer_id", [self.offer, bump_offer]),
                products_repo=FakeRepository("product_id", [self.product, bump_product]),
                stripe_repo=FakeConnectStripeKeysRepository(),
                tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
                secret_cipher=FakeCipher(),
                opener=self.opener,
            )

        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        # (1800 + 500) cents at the "basic" tier physical rate (10%) rounds to a 230 cent platform fee.
        self.assertEqual(payload["payment_intent_data[application_fee_amount]"], ["230"])

    def test_checkout_rejects_missing_order_bump_offer(self):
        response = handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {
                    "clientID": "tenant_demo",
                    "offer": "offer_simple_coffee",
                    "product_id": "prod_simple_coffee",
                    "price_id": "price_simple_coffee",
                    "order_bump_ids": "offer_bump_missing",
                    "success_url": "https://pages.example.com/thanks",
                    "cancel_url": "https://pages.example.com/buy",
                },
            },
            None,
            offers_repo=FakeRepository("offer_id", [self.offer]),
            products_repo=FakeRepository("product_id", [self.product]),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(self.requests, [])

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
            tenant_repo=FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

        payload = parse_qs(self.requests[0].data.decode("utf-8"))
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], ["14900"])
        self.assertEqual(payload["line_items[0][quantity]"], ["1"])


if __name__ == "__main__":
    unittest.main()
