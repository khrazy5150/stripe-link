import json
import unittest
from pathlib import Path

from handlers.pages import handler
from tests.fakes import FakeDocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class PageHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("page_id")
        self.page = load_fixture("page-creatine-standard.json")

    def test_create_page_persists_minimal_page_json(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.page),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        self.assertEqual(body["page"]["page_id"], "page_creatine_standard")
        self.assertEqual(body["page"]["offer_id"], "offer_creatine_standard")

    def test_get_and_list_pages(self):
        self.repository.put(self.page)

        get_response = handler({
            "httpMethod": "GET",
            "pathParameters": {"page_id": "page_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)
        list_response = handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(get_response["statusCode"], 200)
        self.assertEqual(json.loads(get_response["body"])["page"]["route"]["slug"], "creatine-gummies")
        self.assertEqual(json.loads(list_response["body"])["pages"][0]["page_id"], "page_creatine_standard")

    def test_create_page_rejects_missing_sections(self):
        self.page["sections"] = []

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.page),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_page")

    def test_delete_draft_page_removes_document(self):
        self.repository.put(self.page)

        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"page_id": "page_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["deleted"])
        self.assertIsNone(self.repository.get("tenant_demo", "page_creatine_standard"))

    def test_delete_published_page_requires_archive(self):
        page = dict(self.page)
        page["status"] = "published"
        self.repository.put(page)

        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"page_id": "page_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "published_page_requires_archive")


if __name__ == "__main__":
    unittest.main()
