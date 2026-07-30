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


class SequenceRoutingTests(unittest.TestCase):
    """Offer-derived, sequence-indexed upsell routing (plans/OFFER_MODEL_REDESIGN.md §6, P3.2b)."""

    def setUp(self):
        self.pages = FakeDocumentRepository("page_id")
        self.pages.put({
            "tenant_id": "tenant_demo", "page_id": "page_entry", "offer_id": "offer_up",
            "post_checkout": {"thank_you_page": {"page_id": "page_thank_you"}},
        })
        self.offers = FakeDocumentRepository("offer_id")
        self.offers.put({"tenant_id": "tenant_demo", "offer_id": "offer_up", "funnel": {"upsells": [
            {"product_id": "prod_a", "price_id": "price_a_up"},
            {"product_id": "prod_b", "price_id": "price_b_up"},
        ]}})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "published"})
        self.products = FakeDocumentRepository("product_id")
        for pid, price_id in (("prod_a", "price_a_up"), ("prod_b", "price_b_up")):
            self.products.put({"tenant_id": "tenant_demo", "product_id": pid, "prices": [
                {"price_id": price_id, "context": "upsell", "unit_amount": 1000, "currency": "usd"},
            ]})

    def call(self, outcome=None, step_id=None, session_id=None):
        params = {"tenant_id": "tenant_demo"}
        if outcome is not None:
            params["outcome"] = outcome
        if step_id is not None:
            params["step_id"] = step_id
        if session_id is not None:
            params["session_id"] = session_id
        return handler(
            {"httpMethod": "GET", "pathParameters": {"page_id": "page_entry"}, "queryStringParameters": params},
            None, repository=self.pages, pages_domain="pages.example.com",
            offers_repo=self.offers, products_repo=self.products,
        )

    def test_first_hop_serves_upsell_1(self):
        response = self.call(outcome="accept", session_id="cs_1")
        location = urlparse(response["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__upsell_1/index.html")
        query = parse_qs(location.query)
        self.assertEqual(query["funnel_step"], ["1"])
        self.assertEqual(query["funnel_page"], ["page_entry"])
        self.assertEqual(query["session_id"], ["cs_1"])

    def test_accept_advances_to_next_upsell(self):
        location = urlparse(self.call(outcome="accept", step_id="1")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__upsell_2/index.html")
        self.assertEqual(parse_qs(location.query)["funnel_step"], ["2"])

    def test_decline_also_advances_in_p32b(self):
        location = urlparse(self.call(outcome="decline", step_id="1")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__upsell_2/index.html")

    def test_past_last_upsell_goes_to_synthesized_thank_you(self):
        # The funnel terminus is the thank-you screen synthesized alongside the funnel, not the landing page.
        location = urlparse(self.call(outcome="accept", step_id="2")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__thank_you/index.html")

    def test_decline_of_last_upsell_also_goes_to_thank_you(self):
        location = urlparse(self.call(outcome="decline", step_id="2")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__thank_you/index.html")

    def test_bad_outcome_rejected_on_the_sequence_path(self):
        self.assertEqual(self.call(outcome="maybe", step_id="1")["statusCode"], 400)

    def test_funnel_terminus_ignores_a_dangling_tenant_thank_you_ref(self):
        # Even if the page references a thank-you page that was never created, the funnel uses its own
        # synthesized thank-you screen — no landing-page fallback, no 404.
        self.pages.put({
            "tenant_id": "tenant_demo", "page_id": "page_entry", "offer_id": "offer_up",
            "post_checkout": {"thank_you_page": {"page_id": "page_ghost"}},
        })
        location = urlparse(self.call(outcome="accept", step_id="2")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__thank_you/index.html")


class CarouselRoutingTests(unittest.TestCase):
    """Carousel-mode post-purchase routing (>3 upsells, plans/OFFER_MODEL_REDESIGN.md §6)."""

    def _setup(self, downsell_products=("prod_a", "prod_c")):
        self.pages = FakeDocumentRepository("page_id")
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_entry", "offer_id": "offer_up"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "published"})
        upsells = [{"product_id": f"prod_{c}", "price_id": f"price_{c}_up"} for c in "abcd"]
        downsells = [{"product_id": p, "price_id": f"price_{p[-1]}_down"} for p in downsell_products]
        self.offers = FakeDocumentRepository("offer_id")
        self.offers.put({"tenant_id": "tenant_demo", "offer_id": "offer_up",
                         "funnel": {"upsells": upsells, "downsells": downsells}})
        self.products = FakeDocumentRepository("product_id")
        for c in "abcd":
            prices = [{"price_id": f"price_{c}_up", "context": "upsell", "unit_amount": 1000, "currency": "usd"}]
            if f"prod_{c}" in downsell_products:
                prices.append({"price_id": f"price_{c}_down", "context": "downsell", "unit_amount": 500, "currency": "usd"})
            self.products.put({"tenant_id": "tenant_demo", "product_id": f"prod_{c}", "prices": prices})

    def setUp(self):
        self._setup()

    def call(self, outcome=None, step_id=None, session_id=None):
        params = {"tenant_id": "tenant_demo"}
        if outcome is not None:
            params["outcome"] = outcome
        if step_id is not None:
            params["step_id"] = step_id
        if session_id is not None:
            params["session_id"] = session_id
        return handler(
            {"httpMethod": "GET", "pathParameters": {"page_id": "page_entry"}, "queryStringParameters": params},
            None, repository=self.pages, pages_domain="pages.example.com",
            offers_repo=self.offers, products_repo=self.products,
        )

    def test_first_hop_serves_the_upsell_carousel(self):
        location = urlparse(self.call(outcome="accept", session_id="cs_1")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__upsell_carousel/index.html")
        query = parse_qs(location.query)
        self.assertEqual(query["funnel_page"], ["page_entry"])
        self.assertEqual(query["session_id"], ["cs_1"])
        self.assertNotIn("funnel_step", query)  # carousel has no per-sequence step

    def test_dismiss_upsell_carousel_goes_to_downsell_carousel_when_downsells_exist(self):
        location = urlparse(self.call(outcome="decline", step_id="upsell_carousel")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__downsell_carousel/index.html")

    def test_dismiss_downsell_carousel_goes_to_thank_you(self):
        location = urlparse(self.call(outcome="decline", step_id="downsell_carousel")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__thank_you/index.html")

    def test_dismiss_upsell_carousel_skips_to_thank_you_when_no_downsells(self):
        self._setup(downsell_products=())
        location = urlparse(self.call(outcome="decline", step_id="upsell_carousel")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry__thank_you/index.html")


class PostCheckoutHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("page_id")
        self.repository.put(entry_page())
        # A real, PUBLISHED thank-you page so the funnel terminus resolves (a dangling/draft one falls back).
        self.repository.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "published"})

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

    def test_unpublished_thank_you_falls_back_to_entry_success(self):
        # Legacy (no offer-derived upsells) path: a dangling/unpublished thank-you must not 404 the buyer.
        self.repository.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "draft"})
        location = urlparse(self.call(outcome="accept", step_id="upsell_1")["headers"]["Location"])
        self.assertEqual(location.path, "/page_entry/index.html")
        self.assertEqual(parse_qs(location.query)["checkout"], ["success"])

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
        # A real, PUBLISHED thank-you page so the funnel terminus resolves (a dangling/draft one falls back).
        self.repository.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "published"})

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


class PostCheckoutOfferDerivedReservedSlugTests(unittest.TestCase):
    """The offer-derived funnel serves on the custom domain at its RESERVED slugs (/upsell, /thank-you) so the
    buyer never bounces to the platform host mid-funnel (plans/SALES_FUNNELS.md P2b)."""

    def setUp(self):
        self.pages = FakeDocumentRepository("page_id")
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_entry", "offer_id": "offer_up",
                        "post_checkout": {"thank_you_page": {"page_id": "page_thank_you"}}})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_thank_you", "status": "published"})
        self.offers = FakeDocumentRepository("offer_id")
        self.offers.put({"tenant_id": "tenant_demo", "offer_id": "offer_up", "funnel": {"upsells": [
            {"product_id": "prod_a", "price_id": "price_a_up"}, {"product_id": "prod_b", "price_id": "price_b_up"},
        ]}})
        self.products = FakeDocumentRepository("product_id")
        for pid, price_id in (("prod_a", "price_a_up"), ("prod_b", "price_b_up")):
            self.products.put({"tenant_id": "tenant_demo", "product_id": pid,
                               "prices": [{"price_id": price_id, "context": "upsell", "unit_amount": 1000, "currency": "usd"}]})

    def _site(self, verified=True):
        return {
            "tenant_id": "tenant_demo", "site_id": "site_r",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": verified}},
            "pages": {"/": {"page_id": "page_entry"},
                      "/upsell": {"page_id": "page_entry", "funnel_role": "upsell", "strategy": "sequence", "enabled": True},
                      "/thank-you": {"page_id": "page_entry", "funnel_role": "thank_you", "strategy": "sequence", "enabled": True}},
        }

    def _call(self, outcome, step_id=None, verified=True):
        params = {"tenant_id": "tenant_demo", "outcome": outcome, "session_id": "cs_1"}
        if step_id is not None:
            params["step_id"] = step_id
        return handler(
            {"httpMethod": "GET", "pathParameters": {"page_id": "page_entry"}, "queryStringParameters": params},
            None, repository=self.pages, pages_domain="pages.example.com",
            offers_repo=self.offers, products_repo=self.products, sites_repo=_FakeSitesRepo(self._site(verified=verified)),
        )

    def test_first_upsell_serves_at_reserved_slug_with_step(self):
        location = urlparse(self._call("accept")["headers"]["Location"])
        self.assertEqual(location.netloc, "shop.example.com")
        self.assertEqual(location.path, "/upsell")   # single reserved slug, step in the query
        query = parse_qs(location.query)
        self.assertEqual(query["funnel_step"], ["1"])
        self.assertEqual(query["session_id"], ["cs_1"])

    def test_advance_stays_on_reserved_upsell_slug(self):
        location = urlparse(self._call("accept", step_id="1")["headers"]["Location"])
        self.assertEqual(location.netloc, "shop.example.com")
        self.assertEqual(location.path, "/upsell")
        self.assertEqual(parse_qs(location.query)["funnel_step"], ["2"])

    def test_past_last_upsell_serves_reserved_thank_you_slug(self):
        location = urlparse(self._call("accept", step_id="2")["headers"]["Location"])
        self.assertEqual(location.netloc, "shop.example.com")
        self.assertEqual(location.path, "/thank-you")
        self.assertEqual(parse_qs(location.query)["session_id"], ["cs_1"])

    def test_unverified_domain_falls_back_to_platform_artifact(self):
        location = urlparse(self._call("accept", verified=False)["headers"]["Location"])
        self.assertEqual(location.netloc, "pages.example.com")
        self.assertEqual(location.path, "/page_entry__upsell_1/index.html")


if __name__ == "__main__":
    unittest.main()
