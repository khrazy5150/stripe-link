"""Phase B — shareable test links (plans/SALES_FUNNELS.md): a page keeps a sticky snowflake short_code, the
publish stream registers a code->page route, and pages_resolve maps code (+ /sale //flash-sale view) to the
published artifact's origin_url for the test.juniorbay.com Worker to reverse-proxy."""

import json
import unittest

from handlers.pages import assign_short_code
from handlers.pages_resolve import handler as resolve_handler
from stripe_link.runtime.publishing import deregister_page_route, register_page_route
from tests.fakes import FakeDocumentRepository


class AssignShortCodeTests(unittest.TestCase):
    def test_assigns_on_first_publish(self):
        doc = {"status": "published"}
        assign_short_code(None, doc, code_fn=lambda: "CODE0000001")
        self.assertEqual(doc["short_code"], "CODE0000001")

    def test_no_code_for_a_draft(self):
        doc = {"status": "draft"}
        assign_short_code(None, doc, code_fn=lambda: "CODE0000001")
        self.assertNotIn("short_code", doc)

    def test_sticky_when_editing_a_page_that_has_one(self):
        doc = {"status": "draft"}  # an unpublish / edit round-trip that dropped the code
        assign_short_code({"short_code": "KEEP1234567"}, doc, code_fn=lambda: "NEW00000000")
        self.assertEqual(doc["short_code"], "KEEP1234567")

    def test_existing_code_wins_over_a_fresh_one_on_republish(self):
        doc = {"status": "published", "short_code": "KEEP1234567"}
        assign_short_code({"short_code": "KEEP1234567"}, doc, code_fn=lambda: "NEW00000000")
        self.assertEqual(doc["short_code"], "KEEP1234567")


class PageRouteRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("short_code")
        self.page = {"short_code": "C1", "tenant_id": "t1", "page_id": "page_1"}

    def test_register_creates_a_page_route(self):
        self.assertTrue(register_page_route(self.repo, self.page))
        route = self.repo.find_by_id("C1")
        self.assertEqual(route["target_type"], "page")
        self.assertEqual(route["target_page_id"], "page_1")
        self.assertEqual(route["tenant_id"], "t1")

    def test_register_is_idempotent(self):
        register_page_route(self.repo, self.page)
        self.assertFalse(register_page_route(self.repo, self.page))  # already registered

    def test_register_noop_without_a_short_code(self):
        self.assertFalse(register_page_route(self.repo, {"tenant_id": "t1", "page_id": "page_1"}))

    def test_deregister_removes_the_route(self):
        register_page_route(self.repo, self.page)
        self.assertTrue(deregister_page_route(self.repo, self.page))
        self.assertIsNone(self.repo.find_by_id("C1"))


class PagesResolveHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("short_code")
        self.repo.put({
            "tenant_id": "t1", "short_code": "C1", "document_type": "route",
            "target_type": "page", "target_page_id": "page_1",
        })

    def _resolve(self, query):
        return resolve_handler({"httpMethod": "GET", "queryStringParameters": query}, None,
                               repository=self.repo, pages_domain="d.cloudfront.net")

    def test_resolves_standard_view_to_base_artifact(self):
        resp = self._resolve({"code": "C1"})
        self.assertEqual(resp["statusCode"], 200)
        route = json.loads(resp["body"])["route"]
        self.assertEqual(route["type"], "origin_url")
        self.assertEqual(route["origin_url"], "https://d.cloudfront.net/page_1/index.html")

    def test_resolves_sale_view(self):
        route = json.loads(self._resolve({"code": "C1", "view": "sale"})["body"])["route"]
        self.assertEqual(route["origin_url"], "https://d.cloudfront.net/page_1/sale/index.html")

    def test_resolves_flash_view(self):
        route = json.loads(self._resolve({"code": "C1", "view": "flash-sale"})["body"])["route"]
        self.assertEqual(route["origin_url"], "https://d.cloudfront.net/page_1/flash-sale/index.html")

    def test_unknown_code_is_404(self):
        self.assertEqual(self._resolve({"code": "nope"})["statusCode"], 404)

    def test_unknown_view_is_404(self):
        self.assertEqual(self._resolve({"code": "C1", "view": "upsell"})["statusCode"], 404)

    def test_missing_code_is_400(self):
        self.assertEqual(self._resolve({})["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
