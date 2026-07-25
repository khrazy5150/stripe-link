"""Phase B — shareable test links (plans/SALES_FUNNELS.md): a page keeps a sticky snowflake short_code, the
publish stream registers a code->page route, and pages_resolve maps code (+ /sale //flash-sale view) to the
published artifact's origin_url for the test.juniorbay.com Worker to reverse-proxy."""

import unittest

from handlers.pages import assign_short_code
from handlers.test_page_serve import handler as serve_handler
from stripe_link.runtime.publishing import deregister_page_route, register_page_route
from tests.fakes import FakeDocumentRepository


class _FakeS3Body:
    def __init__(self, text):
        self._bytes = text.encode("utf-8")

    def read(self):
        return self._bytes


class _FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _FakeS3Body(self.objects[Key])}


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


class TestPageServeHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("short_code")
        self.repo.put({
            "tenant_id": "t1", "short_code": "C1", "document_type": "route",
            "target_type": "page", "target_page_id": "page_1",
        })
        self.s3 = _FakeS3({
            "page_1/index.html": "<html>standard view</html>",
            "page_1/sale/index.html": "<html>sale view</html>",
            "page_1/flash-sale/index.html": "<html>flash view</html>",
        })

    def _serve(self, code, view=None):
        params = {"code": code}
        if view is not None:
            params["view"] = view
        return serve_handler({"httpMethod": "GET", "pathParameters": params}, None,
                             repository=self.repo, s3_client=self.s3, pages_bucket="b")

    def test_serves_standard_view(self):
        resp = self._serve("C1")
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("standard view", resp["body"])
        self.assertEqual(resp["headers"]["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("noindex", resp["headers"]["X-Robots-Tag"])

    def test_serves_sale_view(self):
        self.assertIn("sale view", self._serve("C1", "sale")["body"])

    def test_serves_flash_view(self):
        self.assertIn("flash view", self._serve("C1", "flash-sale")["body"])

    def test_unknown_code_is_404(self):
        self.assertEqual(self._serve("nope")["statusCode"], 404)

    def test_unknown_view_is_404(self):
        self.assertEqual(self._serve("C1", "upsell")["statusCode"], 404)

    def test_missing_artifact_is_404(self):
        # Valid code, but this page has no sale artifact (e.g. no sale price) -> 404, not a 500.
        self.repo.put({
            "tenant_id": "t1", "short_code": "C2", "document_type": "route",
            "target_type": "page", "target_page_id": "page_2",
        })
        self.assertEqual(self._serve("C2", "sale")["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
