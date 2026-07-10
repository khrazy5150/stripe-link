"""Lead capture: public ingest validates against the offer's product lead_capture.fields[], blocks
honeypot spam, is idempotent on retry, records (not blocks) duplicates, and emits a notification."""
import json
import unittest

from handlers.leads import handler
from stripe_link.domain.leads import (
    LeadValidationError,
    normalize_email,
    normalize_phone,
    validate_and_extract_fields,
)
from tests.fakes import FakeDocumentRepository


def _offer():
    return {
        "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
        "name": "Water Damage", "product_intent": "lead_gen", "stripe_mode": "test", "status": "active",
        "items": [{"product_id": "prod_lead", "price_id": "pr", "quantity": 1}],
        "presentation": {"cta": {"type": "email", "label": "Get Help"}},
    }


def _product(fields=None):
    return {
        "schema_version": "2026-05-29", "document_type": "product", "tenant_id": "t1", "product_id": "prod_lead",
        "product_intent": "lead_gen",
        "lead_capture": {
            "action": "capture_email_phone", "title": "Get help", "description": "We'll call you back.",
            "fields": fields if fields is not None else [
                {"name": "email", "type": "email", "required": True},
                {"name": "phone", "type": "phone", "required": False},
            ],
        },
    }


class LeadDomainTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_email("  Jane@Example.COM "), "jane@example.com")
        self.assertEqual(normalize_phone("+1 (213) 555-1212"), "+12135551212")

    def test_required_field_enforced(self):
        with self.assertRaises(LeadValidationError):
            validate_and_extract_fields({}, [{"name": "email", "type": "email", "required": True}])

    def test_email_type_checked_and_unknown_dropped(self):
        with self.assertRaises(LeadValidationError):
            validate_and_extract_fields({"email": "not-an-email"}, [{"name": "email", "type": "email", "required": True}])
        cleaned = validate_and_extract_fields(
            {"email": "a@b.com", "evil": "x"},
            [{"name": "email", "type": "email", "required": True}],
        )
        self.assertEqual(cleaned, {"email": "a@b.com"})  # unknown 'evil' dropped


class LeadIngestTests(unittest.TestCase):
    def setUp(self):
        self.leads = FakeDocumentRepository("lead_id")
        self.offers = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.notifications = FakeDocumentRepository("notification_id")
        self.offers.put(_offer())
        self.products.put(_product())

    def _post(self, body):
        return handler(
            {"httpMethod": "POST", "body": json.dumps(body),
             "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}},
            None,
            leads_repo=self.leads, offers_repo=self.offers, products_repo=self.products,
            notifications_repo=self.notifications, now_fn=lambda: 1000,
        )

    def test_valid_lead_is_captured_and_notifies(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "page_id": "pg_1",
                           "fields": {"email": "Jane@Example.com", "phone": "+1 (213) 555-1212"}})
        self.assertEqual(resp["statusCode"], 201)
        lead_id = json.loads(resp["body"])["lead_id"]
        stored = self.leads.get("t1", lead_id)
        self.assertEqual(stored["email_normalized"], "jane@example.com")
        self.assertEqual(stored["phone_normalized"], "+12135551212")
        self.assertEqual(stored["status"], "new")
        self.assertEqual(len(self.notifications.list_for_tenant("t1")), 1)

    def test_honeypot_is_silently_dropped(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "company_website": "http://spam",
                           "fields": {"email": "bot@spam.com"}})
        self.assertEqual(resp["statusCode"], 202)
        self.assertEqual(len(self.leads.list_for_tenant("t1")), 0)

    def test_missing_required_field_is_400(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "fields": {"phone": "213-555-1212"}})
        self.assertEqual(resp["statusCode"], 400)

    def test_unknown_offer_is_404(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "nope", "fields": {"email": "a@b.com"}})
        self.assertEqual(resp["statusCode"], 404)

    def test_idempotency_key_dedupes_retry(self):
        body = {"tenant_id": "t1", "offer_id": "off_1", "idempotency_key": "abc",
                "fields": {"email": "a@b.com"}}
        first = self._post(body)
        second = self._post(body)
        self.assertEqual(first["statusCode"], 201)
        self.assertEqual(second["statusCode"], 200)
        self.assertEqual(json.loads(second["body"])["status"], "duplicate")
        self.assertEqual(len(self.leads.list_for_tenant("t1")), 1)

    def test_same_person_no_key_records_two_leads(self):
        body = {"tenant_id": "t1", "offer_id": "off_1", "fields": {"email": "a@b.com"}}
        self._post(body)
        self._post(body)
        self.assertEqual(len(self.leads.list_for_tenant("t1")), 2)  # duplicates recorded, not blocked


class LeadManageTests(unittest.TestCase):
    def setUp(self):
        self.leads = FakeDocumentRepository("lead_id")
        self.leads.put({
            "schema_version": "2026-05-29", "document_type": "lead_submission", "tenant_id": "t1",
            "lead_id": "lead_1", "offer_id": "off_1", "fields": {"email": "a@b.com"},
            "status": "new", "created_at": 500,
        })

    def test_list_and_filter_and_patch_status(self):
        listed = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}}, None, leads_repo=self.leads)
        self.assertEqual(json.loads(listed["body"])["count"], 1)

        patched = handler(
            {"httpMethod": "PATCH", "pathParameters": {"lead_id": "lead_1"},
             "body": json.dumps({"status": "contacted", "tenant_id": "t1"})},
            None, leads_repo=self.leads, now_fn=lambda: 2000,
        )
        self.assertEqual(json.loads(patched["body"])["lead"]["status"], "contacted")

    def test_patch_rejects_bad_status(self):
        resp = handler(
            {"httpMethod": "PATCH", "pathParameters": {"lead_id": "lead_1"},
             "body": json.dumps({"status": "spam", "tenant_id": "t1"})},
            None, leads_repo=self.leads,
        )
        self.assertEqual(resp["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
