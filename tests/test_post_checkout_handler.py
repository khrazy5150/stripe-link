import unittest
from urllib.parse import parse_qs, urlparse

from handlers.post_checkout import handler
from tests.fakes import FakeDocumentRepository


def entry_page(**post_checkout_overrides):
    post_checkout = {
        "thank_you_page": {"page_id": "page_thank_you"},
        "funnel_steps": [
            {"step_id": "upsell_1", "page_id": "page_upsell_1", "on_accept": "thank_you", "on_decline": "downsell_1"},
            {"step_id": "downsell_1", "page_id": "page_downsell_1", "on_accept": "thank_you", "on_decline": "thank_you"},
        ],
    }
    post_checkout.update(post_checkout_overrides)
    return {
        "tenant_id": "tenant_demo",
        "page_id": "page_entry",
        "post_checkout": post_checkout,
    }


class PostCheckoutHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("page_id")
        self.repository.put(entry_page())

    def call(self, outcome=None, step_id=None, session_id=None, pages_domain="pages.example.com"):
        params = {"tenant_id": "tenant_demo"}
        if outcome is not None:
            params["outcome"] = outcome
        if step_id is not None:
            params["step_id"] = step_id
        if session_id is not None:
            params["session_id"] = session_id
        return handler(
            {
                "httpMethod": "GET",
                "pathParameters": {"page_id": "page_entry"},
                "queryStringParameters": params,
            },
            None,
            repository=self.repository,
            pages_domain=pages_domain,
        )

    def test_first_hop_redirects_to_first_funnel_step_with_context(self):
        response = self.call(outcome="accept")
        self.assertEqual(response["statusCode"], 303)
        location = urlparse(response["headers"]["Location"])
        self.assertEqual(location.netloc, "pages.example.com")
        self.assertEqual(location.path, "/page_upsell_1/index.html")
        query = parse_qs(location.query)
        self.assertEqual(query["funnel_page"], ["page_entry"])
        self.assertEqual(query["funnel_step"], ["upsell_1"])

    def test_declining_upsell_redirects_to_downsell(self):
        response = self.call(outcome="decline", step_id="upsell_1")
        location = urlparse(response["headers"]["Location"])
        self.assertEqual(location.path, "/page_downsell_1/index.html")
        self.assertEqual(parse_qs(location.query)["funnel_step"], ["downsell_1"])

    def test_session_id_is_forwarded_through_intermediate_hops(self):
        response = self.call(outcome="decline", step_id="upsell_1", session_id="cs_test_123")
        location = urlparse(response["headers"]["Location"])
        query = parse_qs(location.query)
        self.assertEqual(query["session_id"], ["cs_test_123"])
        self.assertEqual(query["funnel_step"], ["downsell_1"])

    def test_session_id_is_forwarded_to_internal_thank_you_page(self):
        response = self.call(outcome="accept", step_id="upsell_1", session_id="cs_test_123")
        location = urlparse(response["headers"]["Location"])
        self.assertEqual(location.path, "/page_thank_you/index.html")
        query = parse_qs(location.query)
        self.assertEqual(query["session_id"], ["cs_test_123"])
        self.assertNotIn("funnel_step", query)

    def test_accepting_upsell_redirects_to_thank_you_without_funnel_context(self):
        response = self.call(outcome="accept", step_id="upsell_1")
        location = urlparse(response["headers"]["Location"])
        self.assertEqual(location.path, "/page_thank_you/index.html")
        self.assertEqual(location.query, "")

    def test_external_thank_you_url_redirects_directly(self):
        self.repository.put(entry_page(thank_you_page={"url": "https://example.com/thanks"}))
        response = self.call(outcome="accept", step_id="downsell_1")
        self.assertEqual(response["headers"]["Location"], "https://example.com/thanks")

    def test_missing_page_returns_404(self):
        response = handler(
            {
                "httpMethod": "GET",
                "pathParameters": {"page_id": "page_missing"},
                "queryStringParameters": {"tenant_id": "tenant_demo", "outcome": "accept"},
            },
            None,
            repository=self.repository,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)

    def test_missing_tenant_returns_400(self):
        response = handler(
            {
                "httpMethod": "GET",
                "pathParameters": {"page_id": "page_entry"},
                "queryStringParameters": {"outcome": "accept"},
            },
            None,
            repository=self.repository,
            pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 400)

    def test_invalid_outcome_returns_400(self):
        response = self.call(outcome="maybe")
        self.assertEqual(response["statusCode"], 400)

    def test_unconfigured_pages_domain_returns_500(self):
        response = self.call(outcome="accept", pages_domain="")
        self.assertEqual(response["statusCode"], 500)

    def test_rejects_unsupported_method(self):
        response = handler(
            {"httpMethod": "POST", "pathParameters": {"page_id": "page_entry"}},
            None,
            repository=self.repository,
        )
        self.assertEqual(response["statusCode"], 405)

    def test_options_returns_empty_response(self):
        response = handler({"httpMethod": "OPTIONS"}, None, repository=self.repository)
        self.assertEqual(response["statusCode"], 200)


class _FakeSitesRepo:
    def __init__(self, site):
        self.site = site

    def list_for_tenant(self, tenant_id):
        return [self.site] if tenant_id == self.site.get("tenant_id") else []


class PostCheckoutCustomDomainTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("page_id")
        self.repository.put(entry_page())

    def _site(self, verified=True):
        return {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": verified}},
            "pages": {"/": {"page_id": "page_entry"},
                      "/upsell-1": {"page_id": "page_upsell_1"},
                      "/thank-you": {"page_id": "page_thank_you"}},
        }

    def _call(self, outcome, verified):
        return handler(
            {"httpMethod": "GET", "pathParameters": {"page_id": "page_entry"},
             "queryStringParameters": {"tenant_id": "tenant_demo", "outcome": outcome, "session_id": "cs_1"}},
            None, repository=self.repository, pages_domain="pages.example.com",
            sites_repo=_FakeSitesRepo(self._site(verified=verified)),
        )

    def test_hop_serves_on_custom_domain_slug_when_verified(self):
        location = urlparse(self._call("accept", verified=True)["headers"]["Location"])
        self.assertEqual(location.netloc, "shop.example.com")
        self.assertEqual(location.path, "/upsell-1")
        self.assertEqual(parse_qs(location.query)["session_id"], ["cs_1"])

    def test_hop_falls_back_to_platform_artifact_when_domain_unverified(self):
        location = urlparse(self._call("accept", verified=False)["headers"]["Location"])
        self.assertEqual(location.netloc, "pages.example.com")
        self.assertEqual(location.path, "/page_upsell_1/index.html")


if __name__ == "__main__":
    unittest.main()
