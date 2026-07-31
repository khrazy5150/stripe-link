import json
import unittest

from handlers.collections import handler
from tests.fakes import FakeDocumentRepository


def base_collection(**overrides):
    doc = {
        "tenant_id": "tenant_demo",
        "site_id": "site_x",
        "name": "Supplements",
        "rule": "manual",
        "members": ["page_a", "page_b"],
        "presentation": {"heading": "Shop supplements"},
    }
    doc.update(overrides)
    return doc


class CollectionsHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("collection_id")

    def _post(self, doc):
        return handler({"httpMethod": "POST", "body": json.dumps(doc)}, None, repository=self.repo)

    def test_create_generates_id_and_persists(self):
        resp = self._post(base_collection())
        self.assertEqual(resp["statusCode"], 201)
        c = json.loads(resp["body"])["collection"]
        self.assertRegex(c["collection_id"], r"^coll_[A-Za-z0-9]+$")
        self.assertEqual(c["document_type"], "collection")
        self.assertTrue(c["created_at"] and c["updated_at"])
        self.assertEqual(c["members"], ["page_a", "page_b"])

    def test_create_requires_name_and_site(self):
        self.assertEqual(self._post(base_collection(name=""))["statusCode"], 400)
        self.assertEqual(self._post(base_collection(site_id=""))["statusCode"], 400)

    def test_category_rule_requires_category(self):
        self.assertEqual(self._post(base_collection(rule="category", members=[]))["statusCode"], 400)
        ok = self._post(base_collection(rule="category", category="supplements", members=[]))
        self.assertEqual(ok["statusCode"], 201)

    def test_all_rule_needs_no_members(self):
        resp = self._post(base_collection(rule="all", members=[]))
        self.assertEqual(resp["statusCode"], 201)

    def test_bad_rule_rejected(self):
        self.assertEqual(self._post(base_collection(rule="whatever"))["statusCode"], 400)

    def test_upsert_same_id_updates(self):
        created = json.loads(self._post(base_collection(collection_id="coll_AAA1"))["body"])["collection"]
        again = self._post({**created, "name": "Renamed"})
        self.assertEqual(again["statusCode"], 201)
        self.assertEqual(json.loads(again["body"])["collection"]["name"], "Renamed")

    def test_get_and_list_filtered_by_site(self):
        self._post(base_collection(collection_id="coll_AAA1", site_id="site_x"))
        self._post(base_collection(collection_id="coll_BBB2", site_id="site_y", name="Gear"))
        got = handler({"httpMethod": "GET", "pathParameters": {"collection_id": "coll_AAA1"},
                       "queryStringParameters": {"tenant_id": "tenant_demo"}}, None, repository=self.repo)
        self.assertEqual(got["statusCode"], 200)
        listed = handler({"httpMethod": "GET",
                          "queryStringParameters": {"tenant_id": "tenant_demo", "site_id": "site_x"}}, None, repository=self.repo)
        body = json.loads(listed["body"])
        self.assertEqual([c["collection_id"] for c in body["collections"]], ["coll_AAA1"])  # site_y excluded

    def test_delete(self):
        self._post(base_collection(collection_id="coll_AAA1"))
        deleted = handler({"httpMethod": "DELETE", "pathParameters": {"collection_id": "coll_AAA1"},
                           "queryStringParameters": {"tenant_id": "tenant_demo"}}, None, repository=self.repo)
        self.assertEqual(deleted["statusCode"], 200)
        self.assertIsNone(self.repo.get("tenant_demo", "coll_AAA1"))

    def test_unsupported_method(self):
        self.assertEqual(handler({"httpMethod": "PUT"}, None, repository=self.repo)["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()
