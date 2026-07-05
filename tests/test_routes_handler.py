import json
import os
import unittest
from unittest.mock import patch

from handlers.routes import handler as routes_handler
from handlers.routes_resolve import handler as resolve_handler
from tests.fakes import FakeDocumentRepository


def event(method, *, tenant_id=None, body=None, short_code=None, query=None):
    params = dict(query or {})
    if tenant_id:
        params["tenant_id"] = tenant_id
    evt = {"httpMethod": method, "queryStringParameters": params}
    if body is not None:
        evt["body"] = json.dumps(body)
    if short_code is not None:
        evt["pathParameters"] = {"short_code": short_code}
    return evt


class RoutesCrudTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("short_code")

    def create(self, body, code="abc123XYZ00"):
        return routes_handler(
            event("POST", tenant_id="tenant_demo", body=body),
            None,
            repository=self.repo,
            now_fn=lambda: 1781230000,
            code_fn=lambda: code,
        )

    def test_create_page_route_returns_short_url(self):
        with patch.dict(os.environ, {"SHORT_URL_HOST": "go.jbay.uk"}, clear=False):
            response = self.create({"target_type": "page", "target_page_id": "page_1", "label": "Coffee promo"})
        self.assertEqual(response["statusCode"], 201)
        route = json.loads(response["body"])["route"]
        self.assertEqual(route["short_code"], "abc123XYZ00")
        self.assertEqual(route["short_url"], "https://go.jbay.uk/abc123XYZ00")
        self.assertEqual(route["target_page_id"], "page_1")
        self.assertEqual(route["label"], "Coffee promo")

    def test_create_url_route(self):
        response = self.create({"target_type": "url", "target_url": "https://example.com/promo"})
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"])["route"]["target_url"], "https://example.com/promo")

    def test_create_page_route_missing_page_id_rejected(self):
        response = self.create({"target_type": "page"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_route")

    def test_create_retries_on_short_code_collision(self):
        self.repo.put({"tenant_id": "tenant_demo", "short_code": "taken", "document_type": "route", "target_type": "url", "target_url": "https://x"})
        codes = iter(["taken", "fresh123"])
        response = routes_handler(
            event("POST", tenant_id="tenant_demo", body={"target_type": "url", "target_url": "https://y"}),
            None,
            repository=self.repo,
            now_fn=lambda: 1781230000,
            code_fn=lambda: next(codes),
        )
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"])["route"]["short_code"], "fresh123")

    def test_list_and_delete(self):
        self.create({"target_type": "url", "target_url": "https://example.com"})
        listed = routes_handler(event("GET", tenant_id="tenant_demo"), None, repository=self.repo)
        self.assertEqual(json.loads(listed["body"])["count"], 1)

        deleted = routes_handler(event("DELETE", tenant_id="tenant_demo", short_code="abc123XYZ00"), None, repository=self.repo)
        self.assertEqual(deleted["statusCode"], 200)
        again = routes_handler(event("GET", tenant_id="tenant_demo"), None, repository=self.repo)
        self.assertEqual(json.loads(again["body"])["count"], 0)

    def test_missing_tenant_rejected(self):
        response = routes_handler(event("GET"), None, repository=self.repo)
        self.assertEqual(response["statusCode"], 400)


class RoutesResolveTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("short_code")

    def resolve(self, code):
        return resolve_handler(
            event("GET", query={"code": code}),
            None,
            repository=self.repo,
            pages_domain="pages.example.com",
            api_base_url="https://api.example.com/prod",
        )

    def test_resolves_page_to_published_url(self):
        self.repo.put({"tenant_id": "tenant_demo", "short_code": "pg1", "document_type": "route", "target_type": "page", "target_page_id": "page_1"})
        body = json.loads(self.resolve("pg1")["body"])
        self.assertEqual(body["route"]["destination_url"], "https://pages.example.com/page_1/index.html")

    def test_resolves_url(self):
        self.repo.put({"tenant_id": "tenant_demo", "short_code": "u1", "document_type": "route", "target_type": "url", "target_url": "https://example.com/x"})
        body = json.loads(self.resolve("u1")["body"])
        self.assertEqual(body["route"]["destination_url"], "https://example.com/x")

    def test_resolves_experiment_to_resolver(self):
        self.repo.put({"tenant_id": "tenant_demo", "short_code": "e1", "document_type": "route", "target_type": "experiment", "target_experiment_id": "exp_1"})
        body = json.loads(self.resolve("e1")["body"])
        self.assertEqual(body["route"]["destination_url"], "https://api.example.com/prod/experiments/exp_1/resolve")

    def test_unknown_code_404(self):
        self.assertEqual(self.resolve("nope")["statusCode"], 404)

    def test_missing_code_400(self):
        response = resolve_handler(event("GET"), None, repository=self.repo, pages_domain="pages.example.com")
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
