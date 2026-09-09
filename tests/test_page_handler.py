import json
import unittest
from decimal import Decimal
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

    def test_published_page_cannot_be_modified(self):
        page = dict(self.page)
        page["status"] = "published"
        self.repository.put(page)
        edited = dict(page)
        edited["name"] = "Edited published page"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(edited),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Published pages cannot be modified", json.loads(response["body"])["message"])

    def test_published_page_can_be_unpublished(self):
        page = dict(self.page)
        page["status"] = "published"
        self.repository.put(page)
        unpublished = dict(page)
        unpublished["status"] = "draft"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(unpublished),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"])["page"]["status"], "draft")

    def test_a_cropped_page_can_still_be_unpublished(self):
        """A crop rect makes an UNCHANGED page look edited unless numbers are normalised.

        DynamoDB returns every number as a Decimal, the browser sends JSON floats, and
        Decimal('0.563') != 0.563 because the float is really 0.5629999999999999449. Comparing them raw
        made `lifecycle_only_change` false for any page carrying a fraction that is not a negative power
        of two -- so a page with a cropped image could never be unpublished, and therefore never edited
        again. The fakes store what they are given, so only an explicitly Decimal-valued document
        reproduces what the table actually hands back.
        """
        stored = dict(self.page)
        stored["status"] = "published"
        stored["elements"] = [{
            "type": "hero",
            "crop": {"x": Decimal("0.36797"), "y": Decimal("0.34192"),
                     "w": Decimal("0.563"), "h": Decimal("0.375"),
                     "ar": Decimal("1.3333333333")},
        }]
        self.repository.put(stored)

        # What the browser round-trips back: identical content, floats instead of Decimals.
        unpublished = json.loads(json.dumps(stored, default=float))
        unpublished["status"] = "draft"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(unpublished),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 201, json.loads(response["body"]).get("message"))
        self.assertEqual(json.loads(response["body"])["page"]["status"], "draft")

    def test_a_cropped_page_still_cannot_be_edited_while_published(self):
        # Normalising numbers must not weaken the guard: a real content change is still refused.
        stored = dict(self.page)
        stored["status"] = "published"
        stored["elements"] = [{"type": "hero", "crop": {"ar": Decimal("1.3333333333")}}]
        self.repository.put(stored)

        edited = json.loads(json.dumps(stored, default=float))
        edited["status"] = "draft"
        edited["name"] = "Edited while unpublishing"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(edited),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Published pages cannot be modified", json.loads(response["body"])["message"])

    def test_a_changed_crop_is_a_real_edit_not_a_lifecycle_flip(self):
        # The normalisation compares VALUES, so moving the crop must still count as a modification.
        stored = dict(self.page)
        stored["status"] = "published"
        stored["elements"] = [{"type": "hero", "crop": {"x": Decimal("0.36797")}}]
        self.repository.put(stored)

        moved = json.loads(json.dumps(stored, default=float))
        moved["status"] = "draft"
        moved["elements"] = [{"type": "hero", "crop": {"x": 0.5}}]

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(moved),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)

    def test_published_page_cannot_be_modified_during_unpublish(self):
        page = dict(self.page)
        page["status"] = "published"
        self.repository.put(page)
        unpublished = dict(page)
        unpublished["status"] = "draft"
        unpublished["name"] = "Edited while unpublishing"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(unpublished),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Published pages cannot be modified", json.loads(response["body"])["message"])


if __name__ == "__main__":
    unittest.main()
