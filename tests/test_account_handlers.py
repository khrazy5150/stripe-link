import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from handlers.app_config import handler as app_config_handler
from handlers.config import handler as config_handler
from handlers.customers import handler as customers_handler
from handlers.invoices import handler as invoices_handler
from handlers.notifications import handler as notifications_handler
from handlers.preferences import handler as preferences_handler
from handlers.profile import handler as profile_handler
from handlers.registration import handler as registration_handler
from handlers.services import handler as services_handler
from handlers.shipping import handler as shipping_handler
from handlers.stripe_connect import start_handler, status_handler
from handlers.stripe_keys import handler as stripe_keys_handler
from stripe_link.repositories.documents import dynamodb_safe_document
from tests.fakes import FakeAppConfigRepository, FakeDocumentRepository, FakeSimpleRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class AccountHandlerTests(unittest.TestCase):
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
        tenant = load_fixture("tenant-profile-demo.json")

        created = registration_handler({
            "httpMethod": "POST",
            "body": json.dumps(tenant),
        }, None, repository=repository)
        fetched = registration_handler({
            "httpMethod": "GET",
            "pathParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(created["statusCode"], 201)
        self.assertEqual(fetched["statusCode"], 200)
        self.assertEqual(json.loads(fetched["body"])["tenant"]["business_name"], "Demo Supplements")

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
        self.assertEqual(json.loads(created["body"])["stripe_keys"]["secret_key_ref"], "********")
        self.assertEqual(json.loads(fetched["body"])["stripe_keys"]["webhook_secret_ref"], "********")

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
            "STRIPE_CLIENT_ID": "ca_demo",
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
        self.assertEqual(body["state"], "tenant_demo:test")

    def test_stripe_connect_status_defaults_to_not_connected(self):
        repository = FakeSimpleRepository("tenant_id")
        response = status_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(json.loads(response["body"])["stripe_connect"]["connect_status"], "not_connected")


if __name__ == "__main__":
    unittest.main()
