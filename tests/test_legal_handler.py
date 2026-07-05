import json
import unittest

from handlers.legal import handler as legal_handler
from stripe_link.domain.legal import LEGAL_CONFIG
from stripe_link.repositories.documents import PLATFORM_TENANT_ID
from tests.fakes import FakeDocumentRepository


def event(method="GET", *, page_id=None):
    evt = {"httpMethod": method}
    if page_id is not None:
        evt["pathParameters"] = {"page_id": page_id}
    return evt


class LegalListTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("page_id")

    def test_list_returns_default_pages_ordered(self):
        response = legal_handler(event("GET"), None, repository=self.repo)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        ids = [page["page_id"] for page in body["pages"]]
        self.assertEqual(ids, ["terms", "privacy", "refund"])  # by display_order 10/20/30
        self.assertEqual(body["pages"][0]["url"], "/legal/terms")
        self.assertEqual(body["company_name"], LEGAL_CONFIG["company_name"])


class LegalServeTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("page_id")

    def test_serves_default_terms_html(self):
        response = legal_handler(event("GET", page_id="terms"), None, repository=self.repo, year_fn=lambda: 2026)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("text/html", response["headers"]["Content-Type"])
        self.assertIn("Terms of Service", response["body"])
        self.assertIn(LEGAL_CONFIG["company_name"], response["body"])
        self.assertIn("&copy; 2026", response["body"])

    def test_stored_document_overrides_content(self):
        self.repo.put({
            "tenant_id": PLATFORM_TENANT_ID,
            "page_id": "privacy",
            "document_type": "legal_page",
            "content": "<p>Custom privacy body.</p>",
        })
        response = legal_handler(event("GET", page_id="privacy"), None, repository=self.repo, year_fn=lambda: 2026)
        self.assertIn("Custom privacy body.", response["body"])
        self.assertIn("Privacy Policy", response["body"])  # title still falls back to default

    def test_disabled_stored_page_returns_404(self):
        self.repo.put({
            "tenant_id": PLATFORM_TENANT_ID,
            "page_id": "refund",
            "document_type": "legal_page",
            "enabled": False,
        })
        response = legal_handler(event("GET", page_id="refund"), None, repository=self.repo)
        self.assertEqual(response["statusCode"], 404)

    def test_unknown_page_id_returns_404(self):
        response = legal_handler(event("GET", page_id="cookies"), None, repository=self.repo)
        self.assertEqual(response["statusCode"], 404)

    def test_options_preflight(self):
        self.assertEqual(legal_handler(event("OPTIONS"), None, repository=self.repo)["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
