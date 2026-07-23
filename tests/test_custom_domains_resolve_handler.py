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

    def test_www_redirect_record_returns_redirect_route(self):
        # A paired www→apex record carries a redirect_to; the resolver 301s to the canonical apex.
        self.index_repo.put({
            "tenant_id": "tenant_demo",
            "domain": "www.example.com",
            "redirect_to": "example.com",
            "status": "active",
        })
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "www.example.com", "path": "/shop"}},
            None,
            index_repo=self.index_repo,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 200)
        route = json.loads(response["body"])["route"]
        self.assertEqual(route["type"], "redirect")
        self.assertEqual(route["location"], "https://example.com")

    def test_well_known_path_resolves_to_sibling_artifact(self):
        self.index_repo.put({"tenant_id": "tenant_demo", "domain": "shop.example.com", "target_page_id": "page_1", "status": "active"})
        for path, expected in (("/sitemap.xml", "https://pages.example.com/page_1/sitemap.xml"),
                               ("/robots.txt", "https://pages.example.com/page_1/robots.txt"),
                               ("/abc123.txt", "https://pages.example.com/page_1/abc123.txt")):
            response = handler(
                {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": path}},
                None, index_repo=self.index_repo, pages_domain="pages.example.com",
            )
            self.assertEqual(json.loads(response["body"])["route"]["origin_url"], expected)

    def test_legacy_record_without_routes_serves_homepage_for_any_path(self):
        # A domain-index record written before path-aware routing has no `routes` table: every path serves the
        # homepage, preserving pre-2.6 behavior.
        self.index_repo.put({"tenant_id": "tenant_demo", "domain": "shop.example.com", "target_page_id": "page_1", "status": "active"})
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": "/../secret"}},
            None, index_repo=self.index_repo, pages_domain="pages.example.com",
        )
        self.assertEqual(json.loads(response["body"])["route"]["origin_url"], "https://pages.example.com/page_1/index.html")

    def _put_funnel_site(self):
        self.index_repo.put({
            "tenant_id": "tenant_demo", "domain": "shop.example.com", "status": "active", "target_page_id": "page_home",
            "routes": {
                "/": {"page_id": "page_home", "enabled": True},
                "/upsell-1": {"page_id": "page_up", "enabled": True},
                "/thank-you": {"page_id": "page_ty", "enabled": True},
                "/retired": {"page_id": "page_old", "enabled": False},
            },
        })

    def test_routes_table_maps_each_slug_to_its_page(self):
        self._put_funnel_site()
        for path, expected_page in (("", "page_home"), ("/", "page_home"), ("/upsell-1", "page_up"),
                                    ("/thank-you", "page_ty"), ("/thank-you/", "page_ty"), ("/UPSELL-1", "page_up")):
            response = handler(
                {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": path}},
                None, index_repo=self.index_repo, pages_domain="pages.example.com",
            )
            self.assertEqual(response["statusCode"], 200, path)
            self.assertEqual(json.loads(response["body"])["route"]["origin_url"], f"https://pages.example.com/{expected_page}/index.html", path)

    def test_unknown_slug_returns_404(self):
        self._put_funnel_site()
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": "/nope"}},
            None, index_repo=self.index_repo, pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)

    def test_disabled_slug_returns_404(self):
        self._put_funnel_site()
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": "/retired"}},
            None, index_repo=self.index_repo, pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)

    def test_well_known_file_served_under_homepage_even_with_routes(self):
        self._put_funnel_site()
        response = handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": "/sitemap.xml"}},
            None, index_repo=self.index_repo, pages_domain="pages.example.com",
        )
        self.assertEqual(json.loads(response["body"])["route"]["origin_url"], "https://pages.example.com/page_home/sitemap.xml")

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
