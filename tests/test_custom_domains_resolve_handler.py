import json
import unittest

from handlers.custom_domains_resolve import handler
from tests.fakes import FakeDocumentRepository


class CustomDomainsResolveHandlerTests(unittest.TestCase):
    def setUp(self):
        self.index_repo = FakeDocumentRepository("domain")

    def test_resolves_active_domain_to_published_page_url(self):
        self.index_repo.put({
            "tenant_id": "tenant_demo",
            "domain": "shop.example.com",
            "target_page_id": "page_1",
            "status": "active",
        })

        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["route"]["type"], "origin_url")
        self.assertEqual(body["route"]["origin_url"], "https://pages.example.com/page_1/index.html")

    def test_normalizes_host_before_lookup(self):
        self.index_repo.put({
            "tenant_id": "tenant_demo",
            "domain": "shop.example.com",
            "target_page_id": "page_1",
            "status": "active",
        })

        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "HTTPS://Shop.Example.com/"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )

        self.assertEqual(response["statusCode"], 200)

    def test_falls_back_to_host_header_when_no_query_param(self):
        self.index_repo.put({
            "tenant_id": "tenant_demo",
            "domain": "shop.example.com",
            "target_page_id": "page_1",
            "status": "active",
        })

        response = handler(
            {"httpMethod": "GET", "headers": {"Host": "shop.example.com"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )

        self.assertEqual(response["statusCode"], 200)

    def test_returns_404_for_unknown_domain(self):
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "unknown.example.com"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)

    def test_returns_404_for_inactive_domain(self):
        self.index_repo.put({
            "tenant_id": "tenant_demo",
            "domain": "shop.example.com",
            "target_page_id": "page_1",
            "status": "pending_dns",
        })

        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)

    def test_requires_host(self):
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 400)

    def test_options_returns_empty_response(self):
        response = handler({"httpMethod": "OPTIONS"}, None, index_repo=self.index_repo)
        self.assertEqual(response["statusCode"], 200)

    def test_rejects_unsupported_method(self):
        response = handler({"httpMethod": "POST"}, None, index_repo=self.index_repo)
        self.assertEqual(response["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()
