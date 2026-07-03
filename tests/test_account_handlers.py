import hashlib
import hmac
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from handlers.app_config import handler as app_config_handler
from handlers.auth import handler as auth_handler
from handlers.billing import connect_card_handler
from handlers.config import handler as config_handler
from handlers.customers import handler as customers_handler
from handlers.invoices import handler as invoices_handler
from handlers.notifications import handler as notifications_handler
from handlers.preferences import handler as preferences_handler
from handlers.profile import handler as profile_handler
from handlers.registration import handler as registration_handler
from handlers.services import handler as services_handler
from handlers.shipping import handler as shipping_handler
from handlers.stripe_connect import callback_handler, start_handler, status_handler
from handlers.stripe_keys import handler as stripe_keys_handler
from handlers.stripe_webhook import handler as stripe_webhook_handler
from stripe_link.domain.fees import default_billing_config
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import dynamodb_safe_document
from tests.fakes import FakeAppConfigRepository, FakeDocumentRepository, FakeSimpleRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class AccountHandlerTests(unittest.TestCase):
    def test_auth_register_creates_cognito_user_and_profiles(self):
        class FakeCognito:
            def __init__(self):
                self.sign_up_payload = None

            def sign_up(self, **kwargs):
                self.sign_up_payload = kwargs
                return {
                    "UserSub": "user-sub-1",
                    "CodeDeliveryDetails": {
                        "Destination": "k***@example.com",
                        "DeliveryMedium": "EMAIL",
                        "AttributeName": "email",
                    },
                }

        cognito = FakeCognito()
        tenants = FakeDocumentRepository("tenant_id")
        users = FakeDocumentRepository("user_id")

        with patch.dict(os.environ, {"COGNITO_USER_POOL_CLIENT_ID": "client-app"}, clear=False):
            response = auth_handler({
                "httpMethod": "POST",
                "path": "/auth/register",
                "body": json.dumps({
                    "client_id": "client_demo",
                    "first_name": "Keith",
                    "last_name": "De Costa",
                    "email": "Keith@example.com",
                    "phone_number": "+12065550100",
                    "password": "password123",
                }),
            }, None, cognito=cognito, tenant_repository=tenants, user_repository=users)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(body["client_id"], "client_demo")
        self.assertEqual(cognito.sign_up_payload["Username"], "keith@example.com")
        self.assertNotIn({"Name": "custom:client_id", "Value": "client_demo"}, cognito.sign_up_payload["UserAttributes"])
        self.assertEqual(tenants.get("client_demo", "client_demo")["auth"]["status"], "pending_confirmation")
        self.assertEqual(tenants.get("client_demo", "client_demo")["tier_id"], "basic")
        self.assertEqual(tenants.get("client_demo", "client_demo")["billing_status"], "trial")
        self.assertEqual(users.get("client_demo", "user-sub-1")["role"], "owner")

    def test_auth_register_writes_initial_tenant_profile_to_dev_and_prod(self):
        class FakeCognito:
            def sign_up(self, **kwargs):
                return {"UserSub": "user-sub-1"}

        dev_tenants = FakeDocumentRepository("tenant_id")
        prod_tenants = FakeDocumentRepository("tenant_id")
        users = FakeDocumentRepository("user_id")

        with patch.dict(os.environ, {"COGNITO_USER_POOL_CLIENT_ID": "client-app"}, clear=False):
            response = auth_handler({
                "httpMethod": "POST",
                "path": "/auth/register",
                "body": json.dumps({
                    "client_id": "client_demo",
                    "first_name": "Keith",
                    "last_name": "De Costa",
                    "email": "Keith@example.com",
                    "password": "password123",
                }),
            }, None,
                cognito=FakeCognito(),
                tenant_repository=dev_tenants,
                tenant_registration_repositories=[dev_tenants, prod_tenants],
                user_repository=users,
            )

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(dev_tenants.get("client_demo", "client_demo")["tier_id"], "basic")
        self.assertEqual(prod_tenants.get("client_demo", "client_demo")["tier_id"], "basic")
        self.assertEqual(dev_tenants.get("client_demo", "client_demo")["billing_status"], "trial")
        self.assertEqual(prod_tenants.get("client_demo", "client_demo")["billing_status"], "trial")

    def test_auth_register_defaults_client_id_to_cognito_sub(self):
        class FakeCognito:
            def sign_up(self, **kwargs):
                return {"UserSub": "user-sub-default"}

        tenants = FakeDocumentRepository("tenant_id")
        users = FakeDocumentRepository("user_id")

        with patch.dict(os.environ, {"COGNITO_USER_POOL_CLIENT_ID": "client-app"}, clear=False):
            response = auth_handler({
                "httpMethod": "POST",
                "path": "/auth/register",
                "body": json.dumps({
                    "first_name": "Keith",
                    "last_name": "De Costa",
                    "email": "keith@example.com",
                    "password": "password123",
                }),
            }, None, cognito=FakeCognito(), tenant_repository=tenants, user_repository=users)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(body["client_id"], "user-sub-default")
        self.assertEqual(tenants.get("user-sub-default", "user-sub-default")["tenant_id"], "user-sub-default")

    def test_auth_login_returns_client_session(self):
        class FakeCognito:
            def initiate_auth(self, **kwargs):
                return {
                    "AuthenticationResult": {
                        "IdToken": "id-token",
                        "AccessToken": "access-token",
                        "RefreshToken": "refresh-token",
                        "ExpiresIn": 3600,
                        "TokenType": "Bearer",
                    }
                }

            def admin_get_user(self, **kwargs):
                return {
                    "Username": "keith@example.com",
                    "UserAttributes": [
                        {"Name": "sub", "Value": "user-sub-1"},
                        {"Name": "email", "Value": "keith@example.com"},
                        {"Name": "given_name", "Value": "Keith"},
                        {"Name": "family_name", "Value": "De Costa"},
                        {"Name": "custom:client_id", "Value": "client_demo"},
                        {"Name": "email_verified", "Value": "true"},
                    ],
                }

        tenants = FakeDocumentRepository("tenant_id")
        users = FakeDocumentRepository("user_id")
        tenants.put({
            "schema_version": "2026-05-29",
            "document_type": "tenant_profile",
            "tenant_id": "client_demo",
            "owner": {"first_name": "Keith", "last_name": "De Costa", "email": "keith@example.com"},
        })
        users.put({
            "schema_version": "2026-05-29",
            "document_type": "user_profile",
            "tenant_id": "client_demo",
            "user_id": "user-sub-1",
            "email": "keith@example.com",
            "display_name": "Keith De Costa",
        })

        with patch.dict(os.environ, {
            "COGNITO_USER_POOL_ID": "pool",
            "COGNITO_USER_POOL_CLIENT_ID": "client-app",
        }, clear=False):
            response = auth_handler({
                "httpMethod": "POST",
                "path": "/auth/login",
                "body": json.dumps({"email": "keith@example.com", "password": "password123"}),
            }, None, cognito=FakeCognito(), tenant_repository=tenants, user_repository=users)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["session"]["client_id"], "client_demo")
        self.assertEqual(body["session"]["tenant_id"], "client_demo")
        self.assertEqual(body["session"]["access_token"], "access-token")

    def test_billing_connect_card_uses_tenant_tier_and_billing_config(self):
        class FakeStripeRepository:
            def get(self, tenant_id, mode="test"):
                return {
                    "schema_version": "2026-05-29",
                    "document_type": "stripe_keys",
                    "tenant_id": tenant_id,
                    "mode": mode,
                    "connect_status": "connected",
                    "connect_account_id": "acct_test_demo",
                    "secret_key_ref": "kms:v1:hidden",
                }

        tenants = FakeDocumentRepository("tenant_id")
        tenants.put({
            "schema_version": "2026-05-29",
            "document_type": "tenant_profile",
            "tenant_id": "tenant_demo",
            "tier_id": "basic",
            "billing_status": "trial",
            "owner": {"email": "owner@example.com"},
        })

        response = connect_card_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo", "mode": "test"},
        }, None,
            tenant_repository=tenants,
            stripe_repository=FakeStripeRepository(),
            billing_config_loader=lambda: load_fixture("global-billing-config.json"),
            now_fn=lambda: 1000,
        )

        body = json.loads(response["body"])
        card = body["stripe_connect_card"]
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(card["tier_id"], "basic")
        self.assertEqual(card["platform_fees"]["rates"]["physical"], 10.0)
        self.assertEqual(card["stripe_connect"]["connect_account_id"], "acct_test_demo")

    def test_kms_secret_cipher_encrypts_and_decrypts_with_context(self):
        class FakeKmsClient:
            def __init__(self):
                self.context = None

            def encrypt(self, KeyId, Plaintext, EncryptionContext):
                self.context = EncryptionContext
                return {"CiphertextBlob": b"wrapped:" + Plaintext}

            def decrypt(self, CiphertextBlob, EncryptionContext):
                self.context = EncryptionContext
                return {"Plaintext": CiphertextBlob.removeprefix(b"wrapped:")}

        client = FakeKmsClient()
        cipher = KmsSecretCipher(key_id="key-demo", client=client)
        wrapped = cipher.encrypt("sk_test_plain", tenant_id="tenant_demo", mode="test", field="secret_key_ref")

        self.assertTrue(wrapped.startswith("kms:v1:"))
        self.assertEqual(cipher.decrypt(wrapped, tenant_id="tenant_demo", mode="test", field="secret_key_ref"), "sk_test_plain")
        self.assertEqual(client.context["tenant_id"], "tenant_demo")

    def test_app_config_create_and_get_api_base_url(self):
        repository = FakeAppConfigRepository()
        document = load_fixture("app-config.json")

        saved = app_config_handler({
            "httpMethod": "PUT",
            "pathParameters": {"config_key": "app_config"},
            "body": json.dumps(document),
        }, None, repository=repository)
        fetched = app_config_handler({
            "httpMethod": "GET",
            "pathParameters": {"config_key": "app_config"},
            "queryStringParameters": {"environment": "global"},
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(
            json.loads(fetched["body"])["app_config"]["environments"]["dev"]["api_base_url"],
            "https://dev.juniorbay.com",
        )

    def test_app_config_rejects_invalid_api_base_url(self):
        repository = FakeAppConfigRepository()
        document = load_fixture("app-config.json")
        document["environments"]["dev"]["api_base_url"] = "dev.juniorbay.com"

        response = app_config_handler({
            "httpMethod": "PUT",
            "pathParameters": {"config_key": "app_config"},
            "body": json.dumps(document),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_app_config")

    def test_dynamodb_document_converts_float_values(self):
        document = {"rate": 0.1}
        item = dynamodb_safe_document(document)

        self.assertEqual(item["rate"], Decimal("0.1"))

    def test_registration_create_and_get(self):
        repository = FakeDocumentRepository("tenant_id")
        prod_repository = FakeDocumentRepository("tenant_id")
        tenant = load_fixture("tenant-profile-demo.json")

        created = registration_handler({
            "httpMethod": "POST",
            "body": json.dumps(tenant),
        }, None, repository=repository, registration_repositories=[repository, prod_repository])
        fetched = registration_handler({
            "httpMethod": "GET",
            "pathParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(created["statusCode"], 201)
        self.assertEqual(fetched["statusCode"], 200)
        self.assertEqual(json.loads(fetched["body"])["tenant"]["business_name"], "Demo Supplements")
        self.assertEqual(prod_repository.get("tenant_demo", "tenant_demo")["tier_id"], "basic")

    def test_stripe_keys_are_redacted_on_write_and_read(self):
        repository = FakeSimpleRepository("tenant_id")
        keys = load_fixture("stripe-keys-demo.json")

        created = stripe_keys_handler({
            "httpMethod": "PUT",
            "body": json.dumps(keys),
        }, None, repository=repository)
        fetched = stripe_keys_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(created["statusCode"], 201)
        self.assertEqual(json.loads(created["body"])["stripe_keys"]["test"]["secret_key_ref"], "********")
        self.assertEqual(json.loads(fetched["body"])["stripe_keys"]["test"]["webhook_secret_ref"], "********")

    def test_stripe_keys_batch_save_routes_test_and_live_modes(self):
        class FakeModeRepository:
            def __init__(self):
                self.documents = {}

            def put(self, document):
                self.documents[(document["mode"], document["tenant_id"])] = dict(document)
                return self.documents[(document["mode"], document["tenant_id"])]

            def get(self, tenant_id, mode="test"):
                document = self.documents.get((mode, tenant_id))
                return dict(document) if document else None

        class FakeSecretCipher:
            def encrypt(self, plaintext, *, tenant_id, mode, field):
                return f"kms:v1:{mode}:{field}:{plaintext}"

        repository = FakeModeRepository()
        response = stripe_keys_handler({
            "httpMethod": "PUT",
            "body": json.dumps({
                "schema_version": "2026-05-29",
                "document_type": "stripe_keys",
                "tenant_id": "tenant_demo",
                "modes": {
                    "test": {
                        "publishable_key": "pk_test_demo",
                        "secret_key_ref": "sk_test_plain",
                        "webhook_secret_ref": "whsec_test_plain",
                    },
                    "live": {
                        "publishable_key": "pk_live_demo",
                        "secret_key_ref": "sk_live_plain",
                        "webhook_secret_ref": "whsec_live_plain",
                    },
                },
            }),
        }, None, repository=repository, secret_cipher=FakeSecretCipher())
        body = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(repository.get("tenant_demo", "test")["publishable_key"], "pk_test_demo")
        self.assertEqual(repository.get("tenant_demo", "live")["publishable_key"], "pk_live_demo")
        self.assertTrue(repository.get("tenant_demo", "test")["secret_key_ref"].startswith("kms:v1:test"))
        self.assertTrue(repository.get("tenant_demo", "live")["secret_key_ref"].startswith("kms:v1:live"))
        self.assertEqual(body["stripe_keys"]["test"]["secret_key_ref"], "********")
        self.assertEqual(body["stripe_keys"]["live"]["secret_key_ref"], "********")

    def test_stripe_key_secrets_are_encrypted_before_persistence(self):
        class FakeSecretCipher:
            def encrypt(self, plaintext, *, tenant_id, mode, field):
                return f"kms:v1:{tenant_id}:{mode}:{field}:{plaintext[::-1]}"

        repository = FakeSimpleRepository("tenant_id")
        keys = {
            "schema_version": "2026-05-29",
            "document_type": "stripe_keys",
            "tenant_id": "tenant_demo",
            "mode": "test",
            "publishable_key": "pk_test_demo",
            "secret_key_ref": "sk_test_plain",
            "webhook_secret_ref": "whsec_plain",
        }

        created = stripe_keys_handler({
            "httpMethod": "PUT",
            "body": json.dumps(keys),
        }, None, repository=repository, secret_cipher=FakeSecretCipher())
        stored = repository.get("tenant_demo")

        self.assertEqual(created["statusCode"], 201)
        self.assertEqual(json.loads(created["body"])["stripe_keys"]["test"]["secret_key_ref"], "********")
        self.assertNotEqual(stored["secret_key_ref"], "sk_test_plain")
        self.assertNotEqual(stored["webhook_secret_ref"], "whsec_plain")
        self.assertTrue(stored["secret_key_ref"].startswith("kms:v1:"))

    def test_stripe_key_blank_secret_inputs_preserve_existing_encrypted_values(self):
        class FakeSecretCipher:
            def encrypt(self, plaintext, *, tenant_id, mode, field):
                return f"kms:v1:{field}:{plaintext}"

        repository = FakeSimpleRepository("tenant_id")
        repository.put({
            "schema_version": "2026-05-29",
            "document_type": "stripe_keys",
            "tenant_id": "tenant_demo",
            "mode": "test",
            "publishable_key": "pk_test_old",
            "secret_key_ref": "kms:v1:existing-secret",
            "webhook_secret_ref": "kms:v1:existing-webhook",
        })

        response = stripe_keys_handler({
            "httpMethod": "PUT",
            "body": json.dumps({
                "schema_version": "2026-05-29",
                "document_type": "stripe_keys",
                "tenant_id": "tenant_demo",
                "mode": "test",
                "publishable_key": "pk_test_new",
                "secret_key_ref": "",
                "webhook_secret_ref": "********",
            }),
        }, None, repository=repository, secret_cipher=FakeSecretCipher())
        stored = repository.get("tenant_demo")

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(stored["publishable_key"], "pk_test_new")
        self.assertEqual(stored["secret_key_ref"], "kms:v1:existing-secret")
        self.assertEqual(stored["webhook_secret_ref"], "kms:v1:existing-webhook")

    def test_stripe_preview_webhook_verifies_signature_and_resolves_connected_account(self):
        class FakeStripeKeysRepository:
            def find_by_connect_account_id(self, account_id, mode="test"):
                return {
                    "tenant_id": "tenant_demo",
                    "mode": mode,
                    "connect_account_id": account_id,
                }

        payload = {
            "id": "evt_preview_1",
            "type": "checkout.session.completed",
            "account": "acct_connected_123",
            "api_version": "2026-05-27.preview",
            "livemode": False,
            "data": {"object": {"id": "cs_test_123"}},
        }
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = 1781230000
        signature = hmac.new(
            b"whsec_preview_test",
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=False):
            response = stripe_webhook_handler({
                "httpMethod": "POST",
                "path": "/webhook/stripe-preview",
                "headers": {"Stripe-Signature": f"t={timestamp},v1={signature}"},
                "body": body,
            }, None,
                repository=FakeStripeKeysRepository(),
                webhook_secret_loader=lambda kind, mode: "whsec_preview_test",
                now_fn=lambda: timestamp,
            )

        response_body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response_body["webhook"]["kind"], "preview")
        self.assertEqual(response_body["webhook"]["mode"], "test")
        self.assertEqual(response_body["webhook"]["tenant_id"], "tenant_demo")
        self.assertEqual(response_body["webhook"]["connect_account_id"], "acct_connected_123")

    def test_stripe_webhook_persists_checkout_session_completed(self):
        class FakeTable:
            def __init__(self):
                self.items = []

            def put_item(self, Item):
                self.items.append(Item)
                return {}

        class FakeRepo:
            def __init__(self):
                self.documents = []

            def put(self, document):
                self.documents.append(document)
                return document

        checkout_sessions_table = FakeTable()
        orders_table = FakeTable()
        customers_repo = FakeRepo()
        invoices_repo = FakeRepo()
        notifications_repo = FakeRepo()
        payload = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "api_version": "2026-05-27.preview",
            "livemode": False,
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "object": "checkout.session",
                    "created": 1781230000,
                    "status": "complete",
                    "payment_status": "paid",
                    "amount_total": 3709,
                    "currency": "usd",
                    "customer": "cus_123",
                    "payment_intent": "pi_123",
                    "customer_details": {
                        "name": "Ada Buyer",
                        "email": "ada@example.com",
                        "phone": "+15555550123",
                    },
                    "metadata": {
                        "tenant_id": "tenant_demo",
                        "clientID": "tenant_demo",
                        "offer_id": "offer_demo",
                        "page_id": "page_demo",
                        "product_id": "prod_demo",
                        "price_id": "price_demo",
                        "product_name": "Demo Product",
                    },
                }
            },
        }
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = 1781230000
        signature = hmac.new(
            b"whsec_stable_test",
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=False):
            response = stripe_webhook_handler({
                "httpMethod": "POST",
                "path": "/webhook/stripe",
                "headers": {"Stripe-Signature": f"t={timestamp},v1={signature}"},
                "body": body,
            }, None,
                checkout_sessions_table=checkout_sessions_table,
                orders_table=orders_table,
                customers_repo=customers_repo,
                invoices_repo=invoices_repo,
                notifications_repo=notifications_repo,
                webhook_secret_loader=lambda kind, mode: "whsec_stable_test",
                now_fn=lambda: timestamp,
                billing_config_loader=lambda: default_billing_config(),
            )

        response_body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response_body["webhook"]["persistence"]["written"], ["checkout_session", "order", "invoice", "customer", "notification"])
        self.assertEqual(checkout_sessions_table.items[0]["session_id"], "cs_test_123")
        self.assertEqual(orders_table.items[0]["product"]["name"], "Demo Product")
        self.assertEqual(invoices_repo.documents[0]["status"], "paid")
        self.assertEqual(invoices_repo.documents[0]["amounts"]["amount_paid"], 3709)
        self.assertEqual(customers_repo.documents[0]["contact"]["email"], "ada@example.com")
        self.assertEqual(notifications_repo.documents[0]["type"], "order")
        self.assertEqual(notifications_repo.documents[0]["title"], "New order")
        self.assertEqual(notifications_repo.documents[0]["related"]["page_id"], "page_demo")
        # Standard fee handling, "basic" tier, "physical" product_type (both metadata defaults):
        # stripe_fee = ceil(3709 * 2.9%) + 30 = 138, platform_fee = round(3709 * 10%) = 371.
        self.assertEqual(orders_table.items[0]["fees"], {
            "tenant_keyed_amount": 3709,
            "stripe_fee": 138,
            "platform_fee": 371,
            "net_payout": 3200,
        })
        self.assertEqual(invoices_repo.documents[0]["amounts"]["stripe_fee"], 138)
        self.assertEqual(invoices_repo.documents[0]["amounts"]["platform_fee"], 371)
        self.assertEqual(invoices_repo.documents[0]["amounts"]["net_payout"], 3200)

    def test_stripe_webhook_rejects_invalid_signature(self):
        body = json.dumps({"id": "evt_bad", "type": "invoice.paid"})
        timestamp = 1781230000

        response = stripe_webhook_handler({
            "httpMethod": "POST",
            "path": "/webhook/stripe",
            "headers": {"Stripe-Signature": f"t={timestamp},v1=bad"},
            "body": body,
        }, None,
            webhook_secret_loader=lambda kind, mode: "whsec_stable_test",
            now_fn=lambda: timestamp,
        )

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_signature")

    def test_stripe_webhook_reports_missing_signing_secret(self):
        response = stripe_webhook_handler({
            "httpMethod": "POST",
            "path": "/webhook/stripe-preview",
            "headers": {},
            "body": "{}",
        }, None, webhook_secret_loader=lambda kind, mode: None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(json.loads(response["body"])["error"], "webhook_secret_not_configured")

    def test_stripe_keys_verify_decrypts_and_checks_stripe_account(self):
        class FakeSecretCipher:
            def decrypt(self, secret_ref, *, tenant_id, mode, field):
                return "sk_test_plain"

        repository = FakeSimpleRepository("tenant_id")
        repository.put({
            "schema_version": "2026-05-29",
            "document_type": "stripe_keys",
            "tenant_id": "tenant_demo",
            "mode": "test",
            "publishable_key": "pk_test_demo",
            "secret_key_ref": "kms:v1:secret",
        })

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"id": "acct_verified", "livemode": False}).encode("utf-8")

        with patch("handlers.stripe_keys.urlopen", return_value=FakeResponse()):
            response = stripe_keys_handler({
                "httpMethod": "POST",
                "path": "/stripe/keys/verify",
                "body": json.dumps({"tenant_id": "tenant_demo", "mode": "test"}),
            }, None, repository=repository, secret_cipher=FakeSecretCipher())

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["stripe_keys_verification"]["valid"])
        self.assertEqual(body["stripe_keys_verification"]["account_id"], "acct_verified")

    def test_config_create_and_get(self):
        repository = FakeSimpleRepository("tenant_id")
        config = load_fixture("tenant-config-demo.json")

        saved = config_handler({
            "httpMethod": "PUT",
            "body": json.dumps(config),
        }, None, repository=repository)
        fetched = config_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["config"]["default_currency"], "usd")
        self.assertEqual(json.loads(fetched["body"])["config"]["page_defaults"]["upsell"]["headline"], "Wait! Before You Go...")
        self.assertEqual(json.loads(fetched["body"])["config"]["custom_domains"]["dns_target"], "domains.jbay.be")

    def test_config_rejects_invalid_custom_domain_shape(self):
        repository = FakeSimpleRepository("tenant_id")
        config = load_fixture("tenant-config-demo.json")
        config["custom_domains"]["domains"][0].pop("target_page_id")

        response = config_handler({
            "httpMethod": "PUT",
            "body": json.dumps(config),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_config")

    def test_preferences_create_and_get(self):
        repository = FakeDocumentRepository("user_id")
        preferences = load_fixture("user-preferences-demo.json")

        saved = preferences_handler({
            "httpMethod": "PUT",
            "body": json.dumps(preferences),
        }, None, repository=repository)
        fetched = preferences_handler({
            "httpMethod": "GET",
            "queryStringParameters": {
                "tenant_id": "tenant_demo",
                "user_id": "owner@example.com",
            },
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["preferences"]["default_stripe_mode"], "test")
        self.assertEqual(
            json.loads(fetched["body"])["preferences"]["authoring_defaults"]["refund_policies"]["physical"]["short_label"],
            "30-day money-back",
        )

    def test_preferences_rejects_too_many_custom_themes(self):
        repository = FakeDocumentRepository("user_id")
        preferences = load_fixture("user-preferences-demo.json")
        preferences["landing_pages"]["custom_color_themes"] = [
            {"theme_id": f"theme_{index}", "name": f"Theme {index}", "tokens": {"primary": "#111827"}}
            for index in range(11)
        ]

        response = preferences_handler({
            "httpMethod": "PUT",
            "body": json.dumps(preferences),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_preferences")

    def test_user_profile_create_and_get(self):
        repository = FakeDocumentRepository("user_id")
        profile = load_fixture("user-profile-demo.json")

        saved = profile_handler({
            "httpMethod": "PUT",
            "body": json.dumps(profile),
        }, None, repository=repository)
        fetched = profile_handler({
            "httpMethod": "GET",
            "queryStringParameters": {
                "tenant_id": "tenant_demo",
                "user_id": "keithdecosta@gmail.com",
            },
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["profile"]["display_name"], "Keith De Costa")
        self.assertEqual(json.loads(fetched["body"])["profile"]["profile_images"]["max_images"], 10)

    def test_user_profile_rejects_too_many_profile_images(self):
        repository = FakeDocumentRepository("user_id")
        profile = load_fixture("user-profile-demo.json")
        profile["profile_images"]["images"] = [
            {"image_id": f"img_{index}", "url": f"https://example.com/{index}.png", "uploaded_at": 1780092000}
            for index in range(11)
        ]

        response = profile_handler({
            "httpMethod": "PUT",
            "body": json.dumps(profile),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_profile")

    def test_notification_create_and_list(self):
        notifications_repository = FakeDocumentRepository("notification_id")
        refund_repository = FakeDocumentRepository("refund_request_id")
        notification = load_fixture("notification-paid-invoice-demo.json")

        saved = notifications_handler({
            "httpMethod": "PUT",
            "path": "/notifications",
            "body": json.dumps(notification),
        }, None, notifications_repo=notifications_repository, refund_requests_repo=refund_repository)
        listed = notifications_handler({
            "httpMethod": "GET",
            "path": "/notifications",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, notifications_repo=notifications_repository, refund_requests_repo=refund_repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(listed["body"])["notifications"][0]["type"], "paid_invoice")

    def test_refund_request_create_and_filter(self):
        notifications_repository = FakeDocumentRepository("notification_id")
        refund_repository = FakeDocumentRepository("refund_request_id")
        refund_request = load_fixture("refund-request-demo.json")

        saved = notifications_handler({
            "httpMethod": "PUT",
            "path": "/notifications/refund-requests",
            "body": json.dumps(refund_request),
        }, None, notifications_repo=notifications_repository, refund_requests_repo=refund_repository)
        listed = notifications_handler({
            "httpMethod": "GET",
            "path": "/notifications/refund-requests",
            "queryStringParameters": {
                "tenant_id": "tenant_demo",
                "status": "manual_review",
                "risk_level": "low",
            },
        }, None, notifications_repo=notifications_repository, refund_requests_repo=refund_repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(listed["body"])["count"], 1)
        self.assertEqual(json.loads(listed["body"])["refund_requests"][0]["refund_request_id"], "refund_req_demo123")

    def test_shipping_config_create_and_get(self):
        repository = FakeSimpleRepository("tenant_id")
        config = load_fixture("shipping-config-demo.json")

        saved = shipping_handler({
            "httpMethod": "PUT",
            "body": json.dumps(config),
        }, None, repository=repository)
        fetched = shipping_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["shipping_config"]["provider"]["name"], "mock")
        self.assertEqual(json.loads(fetched["body"])["shipping_config"]["default_parcel"]["mass_unit"], "oz")

    def test_shipping_config_rejects_missing_ship_from_address(self):
        repository = FakeSimpleRepository("tenant_id")
        config = load_fixture("shipping-config-demo.json")
        config["ship_from_address"].pop("street1")

        response = shipping_handler({
            "httpMethod": "PUT",
            "body": json.dumps(config),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_shipping_config")

    def test_customer_create_get_and_filter(self):
        repository = FakeDocumentRepository("customer_id")
        customer = load_fixture("customer-demo.json")

        saved = customers_handler({
            "httpMethod": "PUT",
            "body": json.dumps(customer),
        }, None, repository=repository)
        fetched = customers_handler({
            "httpMethod": "GET",
            "pathParameters": {"customer_id": "cus_local_marco_rubio"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)
        listed = customers_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo", "customer": "marco"},
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["customer"]["contact"]["email"], "mrubio@gmail.com")
        self.assertEqual(json.loads(listed["body"])["count"], 1)

    def test_customer_rejects_missing_email(self):
        repository = FakeDocumentRepository("customer_id")
        customer = load_fixture("customer-demo.json")
        customer["contact"].pop("email")

        response = customers_handler({
            "httpMethod": "PUT",
            "body": json.dumps(customer),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_customer")

    def test_service_create_get_and_list(self):
        services_repository = FakeDocumentRepository("service_id")
        fulfillers_repository = FakeDocumentRepository("fulfiller_id")
        availability_repository = FakeDocumentRepository("availability_id")
        exceptions_repository = FakeDocumentRepository("exception_id")
        appointments_repository = FakeDocumentRepository("appointment_id")
        service = load_fixture("service-massage-demo.json")

        saved = services_handler({
            "httpMethod": "PUT",
            "path": "/services",
            "body": json.dumps(service),
        }, None, services_repository, fulfillers_repository, availability_repository, exceptions_repository, appointments_repository)
        listed = services_handler({
            "httpMethod": "GET",
            "path": "/services",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, services_repository, fulfillers_repository, availability_repository, exceptions_repository, appointments_repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(listed["body"])["services"][0]["duration_minutes"], 60)

    def test_services_reject_invalid_appointment_status(self):
        services_repository = FakeDocumentRepository("service_id")
        fulfillers_repository = FakeDocumentRepository("fulfiller_id")
        availability_repository = FakeDocumentRepository("availability_id")
        exceptions_repository = FakeDocumentRepository("exception_id")
        appointments_repository = FakeDocumentRepository("appointment_id")
        appointment = load_fixture("appointment-demo.json")
        appointment["status"] = "lost"

        response = services_handler({
            "httpMethod": "PUT",
            "path": "/services/appointments",
            "body": json.dumps(appointment),
        }, None, services_repository, fulfillers_repository, availability_repository, exceptions_repository, appointments_repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_appointment")

    def test_services_save_fulfiller_and_tenant_availability(self):
        services_repository = FakeDocumentRepository("service_id")
        fulfillers_repository = FakeDocumentRepository("fulfiller_id")
        availability_repository = FakeDocumentRepository("availability_id")
        exceptions_repository = FakeDocumentRepository("exception_id")
        appointments_repository = FakeDocumentRepository("appointment_id")
        fulfiller = load_fixture("fulfiller-demo.json")
        availability = load_fixture("tenant-availability-demo.json")

        saved_fulfiller = services_handler({
            "httpMethod": "PUT",
            "path": "/services/fulfillers",
            "body": json.dumps(fulfiller),
        }, None, services_repository, fulfillers_repository, availability_repository, exceptions_repository, appointments_repository)
        saved_availability = services_handler({
            "httpMethod": "PUT",
            "path": "/services/availability/defaults",
            "body": json.dumps(availability),
        }, None, services_repository, fulfillers_repository, availability_repository, exceptions_repository, appointments_repository)

        self.assertEqual(saved_fulfiller["statusCode"], 201)
        self.assertEqual(saved_availability["statusCode"], 201)

    def test_invoice_create_get_and_list(self):
        repository = FakeDocumentRepository("invoice_id")
        invoice = load_fixture("invoice-service-demo.json")

        saved = invoices_handler({
            "httpMethod": "PUT",
            "body": json.dumps(invoice),
        }, None, repository=repository)
        fetched = invoices_handler({
            "httpMethod": "GET",
            "pathParameters": {"invoice_id": "inv_local_demo123"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)
        listed = invoices_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo", "status": "paid"},
        }, None, repository=repository)

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(fetched["body"])["invoice"]["customer"]["email"], "mrubio@gmail.com")
        self.assertEqual(json.loads(listed["body"])["count"], 1)

    def test_invoice_rejects_missing_line_items(self):
        repository = FakeDocumentRepository("invoice_id")
        invoice = load_fixture("invoice-service-demo.json")
        invoice["line_items"] = []

        response = invoices_handler({
            "httpMethod": "PUT",
            "body": json.dumps(invoice),
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_invoice")

    def test_stripe_connect_start_returns_oauth_url(self):
        with patch.dict(os.environ, {
            "STRIPE_CLIENT_ID_TEST": "ca_test_demo",
            "STRIPE_CONNECT_REDIRECT_URI": "https://api.example.com/connect/callback",
        }):
            response = start_handler({
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "mode": "test",
                }
            }, None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("connect.stripe.com/oauth/authorize", body["connect_url"])
        self.assertEqual(body["state"], "tenant_demo:test:single:existing:test")
        self.assertEqual(body["oauth_mode"], "test")

    def test_stripe_connect_start_requires_test_client_for_test_mode(self):
        with patch.dict(os.environ, {
            "STRIPE_CLIENT_ID": "ca_demo",
            "STRIPE_CONNECT_REDIRECT_URI": "https://api.example.com/connect/callback",
        }, clear=True):
            response = start_handler({
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "mode": "test",
                }
            }, None)

        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(json.loads(response["body"])["error"], "connect_not_configured")

    def test_stripe_connect_start_uses_test_client_when_configured(self):
        with patch.dict(os.environ, {
            "STRIPE_CLIENT_ID": "ca_live_demo",
            "STRIPE_CLIENT_ID_TEST": "ca_test_demo",
            "STRIPE_CONNECT_REDIRECT_URI": "https://api.example.com/connect/callback",
        }):
            response = start_handler({
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "mode": "test",
                }
            }, None)

        body = json.loads(response["body"])
        query = parse_qs(urlparse(body["connect_url"]).query)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["oauth_mode"], "test")
        self.assertEqual(query["client_id"], ["ca_test_demo"])
        self.assertEqual(query["state"], ["tenant_demo:test:single:existing:test"])

    def test_stripe_connect_start_prefills_owner_email(self):
        tenants = FakeDocumentRepository("tenant_id")
        tenants.put({
            "schema_version": "2026-05-29",
            "document_type": "tenant_profile",
            "tenant_id": "tenant_demo",
            "owner_email": "owner@example.com",
            "owner": {"email": "fallback@example.com"},
        })

        with patch.dict(os.environ, {
            "STRIPE_CLIENT_ID_TEST": "ca_test_demo",
            "STRIPE_CONNECT_REDIRECT_URI": "https://api.example.com/connect/callback",
        }):
            response = start_handler({
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "mode": "test",
                }
            }, None, tenant_repository=tenants)

        body = json.loads(response["body"])
        query = parse_qs(urlparse(body["connect_url"]).query)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(query["stripe_user[email]"], ["owner@example.com"])

    def test_stripe_connect_callback_uses_oauth_mode_for_exchange_and_storage(self):
        class FakeStripeRepository:
            def __init__(self):
                self.documents = {}

            def get(self, tenant_id, mode="test"):
                return self.documents.get((tenant_id, mode))

            def put(self, document):
                self.documents[(document["tenant_id"], document["mode"])] = dict(document)
                return document

        class FakeSecretCipher:
            def encrypt(self, value, **kwargs):
                return f"kms:{kwargs['mode']}:{kwargs['field']}:{value}"

        repository = FakeStripeRepository()
        with patch("handlers.stripe_connect._exchange_oauth_code", return_value={
            "stripe_user_id": "acct_live_demo",
            "stripe_publishable_key": "pk_live_demo",
            "access_token": "sk_live_connected",
            "refresh_token": "rt_live_connected",
            "scope": "read_write",
            "livemode": True,
        }) as exchange:
            response = callback_handler({
                "queryStringParameters": {
                    "code": "ac_demo",
                    "state": "tenant_demo:test:both:existing:live",
                },
            }, None, repository=repository, secret_cipher=FakeSecretCipher())

        self.assertEqual(response["statusCode"], 302)
        exchange.assert_called_once_with("ac_demo", "live")
        document = repository.get("tenant_demo", "live")
        self.assertEqual(document["mode"], "live")
        self.assertEqual(document["connect_requested_mode"], "test")
        self.assertEqual(document["connect_oauth_mode"], "live")
        self.assertEqual(document["connect_account_id"], "acct_live_demo")
        self.assertIsNone(repository.get("tenant_demo", "test"))

    def test_stripe_connect_status_disconnects_connected_account(self):
        class FakeStripeRepository:
            def __init__(self):
                self.document = {
                    "schema_version": "2026-05-29",
                    "document_type": "stripe_keys",
                    "tenant_id": "tenant_demo",
                    "mode": "live",
                    "publishable_key": "pk_live_demo",
                    "connect_account_id": "acct_live_demo",
                    "connect_access_token_ref": "kms:token",
                    "connect_status": "connected",
                    "created_at": 123,
                }

            def get(self, tenant_id, mode="test"):
                return dict(self.document) if tenant_id == "tenant_demo" and mode == "live" else None

            def put(self, document):
                self.document = dict(document)
                return self.document

        repository = FakeStripeRepository()
        with patch("handlers.stripe_connect._deauthorize_connected_account") as deauthorize:
            response = status_handler({
                "httpMethod": "DELETE",
                "queryStringParameters": {
                    "tenant_id": "tenant_demo",
                    "mode": "live",
                },
            }, None, repository=repository)

        self.assertEqual(response["statusCode"], 200)
        deauthorize.assert_called_once_with("acct_live_demo", "live")
        body = json.loads(response["body"])
        self.assertEqual(body["stripe_connect"]["connect_status"], "not_connected")
        self.assertNotIn("connect_account_id", repository.document)
        self.assertNotIn("publishable_key", repository.document)
        self.assertEqual(repository.document["created_at"], 123)

    def test_stripe_connect_status_defaults_to_not_connected(self):
        class FakeStripeRepository:
            def get(self, tenant_id, mode="test"):
                return None

        response = status_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=FakeStripeRepository())

        self.assertEqual(json.loads(response["body"])["stripe_connect"]["connect_status"], "not_connected")


if __name__ == "__main__":
    unittest.main()
