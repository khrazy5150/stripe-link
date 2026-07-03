import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from handlers.upsell import handler
from stripe_link.domain.fees import clear_config_cache


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name):
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

    def put(self, document):
        key = (document["tenant_id"], document[self.id_field])
        self.documents[key] = dict(document)
        return self.documents[key]


class FakeStripeKeysRepository:
    def __init__(self, connect_account_id=None):
        self.connect_account_id = connect_account_id

    def get(self, tenant_id, mode="test"):
        keys = {"tenant_id": tenant_id, "mode": mode}
        if self.connect_account_id:
            keys["connect_account_id"] = self.connect_account_id
        else:
            keys["secret_key_ref"] = "sk_test_demo"
        return keys


class FakeCipher:
    def decrypt(self, secret_ref, *, tenant_id, mode, field):
        return secret_ref


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeStripeOpener:
    def __init__(self, responses):
        # responses: {(method, path): payload_dict_or_HTTPError}
        self.responses = responses
        self.requests = []

    def __call__(self, request, timeout=20):
        self.requests.append(request)
        parsed = urlparse(request.full_url)
        key = (request.get_method(), parsed.path)
        entry = self.responses.get(key)
        if entry is None:
            raise AssertionError(f"Unexpected request {key}")
        if isinstance(entry, HTTPError):
            raise entry
        return FakeHTTPResponse(entry)


def http_error(status, error_payload):
    body = json.dumps({"error": error_payload}).encode("utf-8")
    return HTTPError("https://api.stripe.com/v1/payment_intents", status, "error", {}, io.BytesIO(body))


class UpsellSessionTests(unittest.TestCase):
    def test_get_upsell_session_returns_customer_and_payment_details(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/checkout/sessions/cs_test_123"): {
                "id": "cs_test_123",
                "customer": {"id": "cus_123"},
                "customer_email": "ada@example.com",
                "payment_intent": {
                    "id": "pi_123",
                    "payment_method": {"id": "pm_123"},
                },
                "customer_details": {"name": "Ada Buyer", "email": "ada@example.com", "phone": "+15555550123"},
                "shipping_details": {"address": {"line1": "1 Main St", "city": "Austin", "country": "US"}},
            }
        })

        response = handler(
            {
                "httpMethod": "GET",
                "queryStringParameters": {"clientID": "tenant_demo", "session_id": "cs_test_123"},
            },
            None,
            stripe_repo=FakeStripeKeysRepository(),
            secret_cipher=FakeCipher(),
            opener=opener,
        )

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["session"]["customer_id"], "cus_123")
        self.assertEqual(body["session"]["payment_intent_id"], "pi_123")
        self.assertEqual(body["session"]["payment_method_id"], "pm_123")
        self.assertEqual(body["session"]["customer_email"], "ada@example.com")
        self.assertEqual(body["session"]["shipping_address"]["city"], "Austin")


class ProcessUpsellTests(unittest.TestCase):
    def setUp(self):
        self.offer = load_fixture("offer-creatine-upsell.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.tenant_repo = FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}])
        self.customers_repo = FakeRepository("customer_id", [{
            "tenant_id": "tenant_demo",
            "customer_id": "cus_123",
            "schema_version": "2026-05-29",
            "document_type": "customer",
            "contact": {"name": "Ada Buyer", "email": "ada@example.com"},
            "summary": {"total_orders": 1, "total_spent": 3709},
            "transaction_history": [{"transaction_id": "order_cs_test_123", "type": "order", "created_at": 1781230000}],
        }])
        self.orders_repo = FakeRepository("order_id", [])
        clear_config_cache()

    def tearDown(self):
        clear_config_cache()

    def base_event(self, **overrides):
        body = {
            "tenant_id": "tenant_demo",
            "session_id": "cs_test_123",
            "offer_id": "offer_creatine_upsell",
            "customer_id": "cus_123",
            "customer": {"name": "Ada Buyer", "email": "ada@example.com"},
        }
        body.update(overrides)
        return {"httpMethod": "POST", "body": json.dumps(body)}

    def handle(self, event, opener, stripe_repo=None):
        return handler(
            event,
            None,
            offers_repo=FakeRepository("offer_id", [self.offer]),
            products_repo=FakeRepository("product_id", [self.product]),
            stripe_repo=stripe_repo or FakeStripeKeysRepository(),
            tenant_repo=self.tenant_repo,
            orders_repo=self.orders_repo,
            customers_repo=self.customers_repo,
            secret_cipher=FakeCipher(),
            opener=opener,
        )

    def test_process_upsell_blocks_tenant_with_suspended_billing_status(self):
        suspended_tenant_repo = FakeRepository("tenant_id", [{"tenant_id": "tenant_demo", "billing_status": "suspended"}])

        response = handler(
            self.base_event(),
            None,
            offers_repo=FakeRepository("offer_id", [self.offer]),
            products_repo=FakeRepository("product_id", [self.product]),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=suspended_tenant_repo,
            orders_repo=self.orders_repo,
            customers_repo=self.customers_repo,
            secret_cipher=FakeCipher(),
            opener=FakeStripeOpener({}),
        )

        self.assertEqual(response["statusCode"], 402)
        self.assertEqual(json.loads(response["body"])["error"], "tenant_billing_hold")

    def test_process_upsell_charges_saved_payment_method_and_records_order(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/customers/cus_123"): {
                "id": "cus_123",
                "invoice_settings": {"default_payment_method": {"id": "pm_123"}},
            },
            ("POST", "/v1/payment_intents"): {"id": "pi_456", "status": "succeeded"},
        })

        response = self.handle(self.base_event(), opener)
        body = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(body["upsell"]["payment_intent_id"], "pi_456")
        self.assertEqual(body["upsell"]["status"], "succeeded")

        order = self.orders_repo.get("tenant_demo", "order_cs_test_123_upsell_1")
        self.assertIsNotNone(order)
        self.assertEqual(order["line_item_type"], "upsell")
        self.assertEqual(order["amount_total"], 2700)
        # physical/basic: stripe_fee = ceil(2700*2.9%)+30 = 109, platform_fee = round(2700*10%) = 270
        self.assertEqual(order["fees"], {
            "tenant_keyed_amount": 2700,
            "stripe_fee": 109,
            "platform_fee": 270,
            "net_payout": 2321,
        })

        pi_request = opener.requests[-1]
        pi_payload = parse_qs(pi_request.data.decode("utf-8"))
        self.assertEqual(pi_payload["payment_method"], ["pm_123"])
        self.assertEqual(pi_payload["off_session"], ["true"])
        self.assertNotIn("application_fee_amount", pi_payload)
        self.assertEqual(pi_request.headers.get("Idempotency-key"), "upsell:tenant_demo:cs_test_123:offer_creatine_upsell:1")

        customer = self.customers_repo.get("tenant_demo", "cus_123")
        self.assertEqual(customer["summary"]["total_orders"], 2)
        self.assertEqual(customer["summary"]["total_spent"], 3709 + 2700)
        self.assertEqual(len(customer["transaction_history"]), 2)

    def test_process_upsell_adds_application_fee_amount_for_connect_direct_charge(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/customers/cus_123"): {
                "id": "cus_123",
                "invoice_settings": {"default_payment_method": {"id": "pm_123"}},
            },
            ("POST", "/v1/payment_intents"): {"id": "pi_789", "status": "succeeded"},
        })

        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_platform"}, clear=False):
            response = self.handle(self.base_event(), opener, stripe_repo=FakeStripeKeysRepository(connect_account_id="acct_connected_123"))
        self.assertEqual(response["statusCode"], 201)

        pi_request = opener.requests[-1]
        pi_payload = parse_qs(pi_request.data.decode("utf-8"))
        self.assertEqual(pi_payload["application_fee_amount"], ["270"])
        self.assertEqual(pi_request.headers.get("Stripe-account"), "acct_connected_123")

    def test_process_upsell_falls_back_to_first_attached_card(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/customers/cus_123"): {"id": "cus_123", "invoice_settings": {}},
            ("GET", "/v1/payment_methods"): {"data": [{"id": "pm_fallback"}]},
            ("POST", "/v1/payment_intents"): {"id": "pi_999", "status": "succeeded"},
        })

        response = self.handle(self.base_event(), opener)
        self.assertEqual(response["statusCode"], 201)
        pi_request = opener.requests[-1]
        pi_payload = parse_qs(pi_request.data.decode("utf-8"))
        self.assertEqual(pi_payload["payment_method"], ["pm_fallback"])

    def test_process_upsell_returns_409_when_no_payment_method_available(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/customers/cus_123"): {"id": "cus_123", "invoice_settings": {}},
            ("GET", "/v1/payment_methods"): {"data": []},
        })

        response = self.handle(self.base_event(), opener)
        self.assertEqual(response["statusCode"], 409)

    def test_process_upsell_surfaces_card_decline_error(self):
        opener = FakeStripeOpener({
            ("GET", "/v1/customers/cus_123"): {
                "id": "cus_123",
                "invoice_settings": {"default_payment_method": {"id": "pm_123"}},
            },
            ("POST", "/v1/payment_intents"): http_error(402, {"message": "Your card was declined.", "code": "card_declined"}),
        })

        response = self.handle(self.base_event(), opener)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 402)
        self.assertEqual(body["error"], "card_declined")
        self.assertIn("declined", body["message"])
        self.assertIsNone(self.orders_repo.get("tenant_demo", "order_cs_test_123_upsell_1"))

    def test_process_upsell_rejects_inactive_offer(self):
        archived_offer = dict(self.offer, status="archived")
        response = handler(
            self.base_event(),
            None,
            offers_repo=FakeRepository("offer_id", [archived_offer]),
            products_repo=FakeRepository("product_id", [self.product]),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=self.tenant_repo,
            orders_repo=self.orders_repo,
            customers_repo=self.customers_repo,
            secret_cipher=FakeCipher(),
            opener=FakeStripeOpener({}),
        )
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
