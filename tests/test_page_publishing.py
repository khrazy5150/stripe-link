import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from handlers.page_publish import handler
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import (
    PublishError,
    _denormalize_page_catalog,
    _prune_unrenderable_landing_items,
    artifact_targets,
    attach_funnel_pages,
    delete_page_artifacts,
    detach_page_from_sites,
    find_site_for_page,
    publish_page_document,
    resolve_category_grids,
    resolve_related_products,
    site_page_slug,
)


ROOT = Path(__file__).resolve().parents[1]
_serializer = TypeSerializer()


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def stream_image(document: dict):
    return {
        key: _serializer.serialize(value)
        for key, value in document.items()
    }


class FakeRepository:
    def __init__(self, id_field: str, documents: list[dict]):
        self.id_field = id_field
        self.documents = {
            (document["tenant_id"], document[id_field]): document
            for document in documents
        }

    def get(self, tenant_id: str, document_id: str):
        document = self.documents.get((tenant_id, document_id))
        return copy.deepcopy(document) if document else None


class FakeSitesRepository:
    def __init__(self, sites: list[dict]):
        self.sites = sites

    def list_for_tenant(self, tenant_id: str):
        return [copy.deepcopy(s) for s in self.sites if s.get("tenant_id") == tenant_id]

    def put(self, site: dict):
        self.sites = [s for s in self.sites if s.get("site_id") != site.get("site_id")] + [copy.deepcopy(site)]
        return copy.deepcopy(site)


class FakeDomainsIndexRepository:
    def __init__(self):
        self.records = []

    def put(self, record: dict):
        self.records.append(copy.deepcopy(record))
        return record


class FakeS3Client:
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {}

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)
        return {}


class FakeCloudFrontClient:
    def __init__(self):
        self.invalidations = []

    def create_invalidation(self, **kwargs):
        self.invalidations.append(kwargs)
        return {"Invalidation": {"Id": "INV123"}}


class PagePublishingTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-simple-coffee.json")
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()
        self.cloudfront = FakeCloudFrontClient()

    def test_artifact_paths_are_shared(self):
        self.assertEqual(
            artifact_paths("tenant_demo", "page_simple_coffee", "simple-coffee"),
            {
                "preview": "preview/tenant_demo/page_simple_coffee/index.html",
                "test": "page_simple_coffee/index.html",
                "published": "page_simple_coffee/index.html",
            },
        )

    def test_artifact_paths_use_page_id_for_public_key(self):
        self.assertNotEqual(
            artifact_paths("tenant_demo", "page_first", "same-slug")["test"],
            artifact_paths("tenant_demo", "page_second", "same-slug")["test"],
        )

    def test_artifact_targets_include_preview_only_for_draft(self):
        targets = artifact_targets(
            self.page,
            environment="dev",
            pages_bucket="pages",
            preview_bucket="preview",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview"])
        self.assertEqual(targets[0]["key"], "preview/tenant_demo/page_simple_coffee/index.html")

    def test_artifact_targets_include_published_when_page_is_published(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"

        targets = artifact_targets(
            page,
            environment="prod",
            pages_bucket="pages",
            preview_bucket="preview",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview", "published"])
        self.assertEqual(targets[1]["key"], "page_simple_coffee/index.html")

    def test_delete_page_artifacts_removes_preview_and_public_keys(self):
        result = delete_page_artifacts(
            self.page,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            cloudfront_client=self.cloudfront,
            pages_distribution_id="DIST123",
        )

        self.assertEqual(
            [(item["Bucket"], item["Key"]) for item in self.s3.deletes],
            [
                ("preview", "preview/tenant_demo/page_simple_coffee/index.html"),
                ("pages", "page_simple_coffee/index.html"),
            ],
        )
        self.assertEqual(result["invalidation"]["paths"], ["/page_simple_coffee/index.html"])

    def test_publish_page_document_writes_preview_html_for_draft(self):
        result = publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )

        self.assertEqual([put["Key"] for put in self.s3.puts], ["preview/tenant_demo/page_simple_coffee/index.html"])
        self.assertIn(b"Simple Coffee", self.s3.puts[0]["Body"])
        self.assertIn(b"https://checkout.stripe.com/c/pay/demo", self.s3.puts[0]["Body"])
        self.assertEqual([artifact["kind"] for artifact in result["artifacts"]], ["preview"])
        self.assertIsNone(result["invalidation"])

    def test_publish_writes_preview_context_artifact_for_enabled_sale_on_a_draft(self):
        page = copy.deepcopy(self.page)
        page["sale"] = {"enabled": True}
        publish_page_document(
            page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="dev",
            pages_domain="p", preview_domain="pv",
        )
        keys = [(put["Bucket"], put["Key"]) for put in self.s3.puts]
        # the /sale preview artifact is written for a draft; the published one is not (still a draft)
        self.assertIn(("preview", "preview/tenant_demo/page_simple_coffee/sale/index.html"), keys)
        self.assertNotIn(("pages", "page_simple_coffee/sale/index.html"), keys)

    def test_prune_drops_landing_items_with_dangling_prices(self):
        products = {"p1": {"product_id": "p1", "prices": [{"price_id": "good"}]}}
        offer = {"offer_id": "o", "items": [
            {"product_id": "p1", "price_id": "good", "quantity": 1},          # keep
            {"product_id": "p1", "price_id": "gone", "quantity": 1},          # drop: price removed
            {"product_id": "missing", "price_id": "x", "quantity": 1},        # drop: product not loaded
            {"service_id": "svc", "price_id": "y", "quantity": 1},            # keep: service untouched
        ]}
        pruned = _prune_unrenderable_landing_items(offer, products)
        self.assertEqual(
            [(i.get("product_id"), i.get("service_id")) for i in pruned["items"]],
            [("p1", None), (None, "svc")],
        )

    def test_prune_keeps_valid_tiers_and_fixes_default(self):
        products = {"p1": {"product_id": "p1", "prices": [{"price_id": "a"}, {"price_id": "b"}]}}
        offer = {"offer_id": "o", "items": [{
            "product_id": "p1", "default_price_id": "gone",
            "selectable_prices": [{"price_id": "a"}, {"price_id": "gone"}, {"price_id": "b"}],
        }]}
        pruned = _prune_unrenderable_landing_items(offer, products)
        item = pruned["items"][0]
        self.assertEqual([sp["price_id"] for sp in item["selectable_prices"]], ["a", "b"])
        self.assertEqual(item["default_price_id"], "a")  # dangling default repointed to a surviving tier

    def test_prune_is_a_noop_when_everything_resolves(self):
        products = {"p1": {"product_id": "p1", "prices": [{"price_id": "good"}]}}
        offer = {"offer_id": "o", "items": [{"product_id": "p1", "price_id": "good", "quantity": 1}]}
        self.assertIs(_prune_unrenderable_landing_items(offer, products), offer)

    def test_publish_writes_an_upsell_screen_artifact_per_plan_entry(self):
        # An offer with an upsell-context price gets a Universal Bundle upsell artifact at {page_id}__upsell_1.
        product = copy.deepcopy(self.product)
        product["prices"].append({
            "price_id": "price_up", "stripe_price_id": "sp_up", "context": "upsell",
            "unit_amount": 500, "currency": "usd", "quantity": 1,
        })
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"upsells": [{"product_id": product["product_id"], "price_id": "price_up"}]}
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        publish_page_document(
            page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", [product]),
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="dev",
            pages_domain="p", preview_domain="pv",
        )
        up_id = f"{page['page_id']}__upsell_1"
        keys = [(put["Bucket"], put["Key"]) for put in self.s3.puts]
        self.assertIn(("pages", artifact_paths("tenant_demo", up_id)["published"]), keys)
        self.assertIn(("preview", artifact_paths("tenant_demo", up_id)["preview"]), keys)
        upsell_body = next(put["Body"] for put in self.s3.puts if put["Key"] == artifact_paths("tenant_demo", up_id)["published"])
        self.assertIn(b"Wait! Before You Go", upsell_body)

    def test_publish_writes_no_upsell_artifact_for_an_ordinary_offer(self):
        publish_page_document(
            copy.deepcopy(self.page), offers_repository=self.offers_repo, products_repository=self.products_repo,
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="dev",
            pages_domain="p", preview_domain="pv",
        )
        self.assertFalse(any("__upsell_" in put["Key"] for put in self.s3.puts))

    def test_publish_deletes_stale_context_artifacts_when_a_context_is_disabled(self):
        # No sale/flash enabled -> their artifacts are cleaned up so /sale //flash-sale stop serving.
        publish_page_document(
            self.page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="dev",
            pages_domain="p", preview_domain="pv",
        )
        deletes = [(d["Bucket"], d["Key"]) for d in self.s3.deletes]
        self.assertIn(("preview", "preview/tenant_demo/page_simple_coffee/sale/index.html"), deletes)
        self.assertIn(("preview", "preview/tenant_demo/page_simple_coffee/flash-sale/index.html"), deletes)

    def test_find_site_for_page_matches_by_page_id(self):
        site = {"tenant_id": "tenant_demo", "site_id": "site_x", "pages": {"/": {"page_id": "page_simple_coffee"}}}
        repo = FakeSitesRepository([site])
        self.assertEqual(find_site_for_page(repo, "tenant_demo", "page_simple_coffee")["site_id"], "site_x")
        self.assertIsNone(find_site_for_page(repo, "tenant_demo", "page_other"))
        self.assertIsNone(find_site_for_page(None, "tenant_demo", "page_simple_coffee"))

    def _valid_site(self, pages):
        return {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_x", "tenant_id": "tenant_demo",
            "environment": "live", "name": "Store", "status": "active",
            "hosting": {"type": "platform", "platform_hostname": "store.jbay.uk", "custom_domain": None},
            "organization": {"name": "Store", "entity_type": "OnlineStore"},
            "indexing": {"eligibility": "blocked"}, "pages": pages, "created_at": 1, "updated_at": 1,
        }

    def test_load_page_reviews_includes_product_and_owning_business_only(self):
        from stripe_link.runtime.publishing import load_page_reviews

        class Repo:
            def list_for_tenant(self, tenant_id):
                return [
                    {"target": {"type": "product", "id": "p1"}, "status": "approved", "source": "manual", "rating": 5},
                    {"target": {"type": "business", "id": "site_x"}, "status": "approved", "source": "manual", "rating": 5},
                    {"target": {"type": "business", "id": "other"}, "status": "approved", "source": "manual", "rating": 1},
                    {"target": {"type": "product", "id": "p1"}, "status": "pending", "source": "manual", "rating": 1},
                    {"target": {"type": "business", "id": "site_x"}, "status": "approved", "source": "gbp", "rating": 1},
                ]
        out = load_page_reviews(Repo(), "t1", {"p1": {}}, site_id="site_x")
        self.assertEqual(sorted((r["target"]["type"], r["target"]["id"]) for r in out),
                         [("business", "site_x"), ("product", "p1")])  # other-site, pending, gbp all excluded

    def test_detach_page_from_sites_removes_from_route_map(self):
        site = self._valid_site({"/": {"page_id": "page_home", "page_type": "homepage"},
                                 "/deal": {"page_id": "page_deal", "page_type": "landing"}})
        repo = FakeSitesRepository([site])
        n = detach_page_from_sites(repo, FakeDomainsIndexRepository(), "tenant_demo", "page_deal")
        self.assertEqual(n, 1)
        saved = repo.list_for_tenant("tenant_demo")[0]["pages"]
        self.assertNotIn("/deal", saved)
        self.assertIn("/", saved)  # other pages untouched

    def test_detach_page_from_sites_is_noop_when_absent(self):
        repo = FakeSitesRepository([self._valid_site({"/": {"page_id": "page_home", "page_type": "homepage"}})])
        self.assertEqual(detach_page_from_sites(repo, FakeDomainsIndexRepository(), "tenant_demo", "page_gone"), 0)
        self.assertEqual(detach_page_from_sites(None, FakeDomainsIndexRepository(), "tenant_demo", "page_home"), 0)

    def test_publish_emits_organization_from_the_owning_site(self):
        page = copy.deepcopy(self.page)
        page["goal"] = "search_seo"
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "organization": {"name": "Bean Bros", "entity_type": "OnlineStore"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }
        publish_page_document(
            page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]),
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )
        body = self.s3.puts[0]["Body"].decode()
        self.assertIn("/#organization", body)
        self.assertIn("Bean Bros", body)
        self.assertIn('"@type":"WebSite"', body)

    def test_homepage_publish_writes_crawl_files_and_submits_indexnow(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "seo": {"indexnow_key": "k1abc"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }
        with patch("stripe_link.runtime.publishing.submit_indexnow", return_value=True) as ping:
            publish_page_document(
                page, offers_repository=self.offers_repo, products_repository=self.products_repo,
                sites_repository=FakeSitesRepository([site]), s3_client=self.s3,
                pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        keys = [put["Key"] for put in self.s3.puts]
        self.assertIn("page_simple_coffee/sitemap.xml", keys)
        self.assertIn("page_simple_coffee/robots.txt", keys)
        self.assertIn("page_simple_coffee/k1abc.txt", keys)   # the IndexNow key file
        ping.assert_called_once()
        sitemap = [put["Body"] for put in self.s3.puts if put["Key"].endswith("sitemap.xml")][0].decode()
        self.assertIn("<loc>https://shop.example.com/</loc>", sitemap)

    def test_no_crawl_files_for_platform_host(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        with patch("stripe_link.runtime.publishing.submit_indexnow") as ping:
            publish_page_document(
                page, offers_repository=self.offers_repo, products_repository=self.products_repo,
                sites_repository=FakeSitesRepository([]), s3_client=self.s3,
                pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        self.assertFalse([put["Key"] for put in self.s3.puts if put["Key"].endswith((".xml", ".txt"))])
        ping.assert_not_called()

    def test_homepage_on_verified_domain_switches_canonical_and_indexes(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        # An indexable page needs real content: pad past the SEO-08 thin-content floor so the gate doesn't
        # (correctly) demote this otherwise-eligible page to noindex.
        page.setdefault("sections", []).append({
            "id": "about", "type": "content_block",
            "blocks": [{"title": "About this coffee", "text": " ".join(["freshly roasted single origin beans"] * 30)}],
        })
        site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }
        publish_page_document(
            page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]),
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="prod",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )
        published = [put for put in self.s3.puts if "preview/" not in put["Key"]][0]["Body"].decode()
        self.assertIn('<link rel="canonical" href="https://shop.example.com/">', published)
        self.assertIn('content="index,follow', published)

    def test_thin_page_on_eligible_domain_is_demoted_to_noindex(self):
        # SEO-08: the bare coffee fixture (a few dozen words) is below the content floor, so even on an
        # eligible verified domain it must publish noindex,follow rather than drag the Site's ranking down.
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }
        publish_page_document(
            page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]), s3_client=self.s3,
            pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )
        published = [put for put in self.s3.puts if "preview/" not in put["Key"]][0]["Body"].decode()
        self.assertIn('content="noindex,follow"', published)

    def test_publish_without_a_site_emits_no_organization(self):
        page = copy.deepcopy(self.page)
        page["goal"] = "search_seo"
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        publish_page_document(
            page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([]),
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )
        self.assertNotIn("/#organization", self.s3.puts[0]["Body"].decode())

    def test_publish_page_document_threads_api_base_url_into_rendered_html(self):
        publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://dev.juniorbay.com/checkout",
            api_base_url="https://api.example.com/dev",
        )

        self.assertIn(b"data-checkout-api-base-url=\"https://api.example.com/dev\"", self.s3.puts[0]["Body"])

    def test_publish_page_document_uses_offer_mode_checkout_base(self):
        result = publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        self.assertEqual([artifact["kind"] for artifact in result["artifacts"]], ["preview"])
        html = self.s3.puts[0]["Body"].decode("utf-8")
        self.assertIn("https://dev.juniorbay.com/checkout?", html)
        self.assertIn("clientID=tenant_demo", html)
        self.assertIn("offer=offer_simple_coffee", html)
        self.assertIn("page_id=page_simple_coffee", html)

    def test_publish_page_document_filters_landing_page_price_contexts_in_offer_order(self):
        product = copy.deepcopy(self.product)
        product["prices"] = [
            {
                "price_id": "price_standard",
                "currency": "usd",
                "unit_amount": 1800,
                "quantity": 1,
                "context": "standard",
            },
            {
                "price_id": "price_sale",
                "currency": "usd",
                "unit_amount": 1400,
                "quantity": 1,
                "context": "sale",
            },
            {
                "price_id": "price_upsell",
                "currency": "usd",
                "unit_amount": 900,
                "quantity": 1,
                "context": "upsell",
            },
            {
                "price_id": "price_flash",
                "currency": "usd",
                "unit_amount": 1200,
                "quantity": 1,
                "context": "flash_sale",
            },
        ]
        product["default_price_id"] = "price_standard"

        offer = copy.deepcopy(self.offer)
        offer["items"][0]["selectable_prices"] = [
            {"price_id": "price_sale", "quantity": 1, "label": "Sale Price"},
            {"price_id": "price_upsell", "quantity": 1, "label": "Upsell Price"},
            {"price_id": "price_standard", "quantity": 1, "label": "Standard Price"},
            {"price_id": "price_flash", "quantity": 1, "label": "Flash Sale Price"},
        ]
        offer["items"][0]["default_price_id"] = "price_standard"

        s3 = FakeS3Client()
        publish_page_document(
            self.page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", [product]),
            s3_client=s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        # Only the standard-context price renders; sale / flash_sale / upsell are all filtered out. Sale and
        # flash sale are alternate pricing MODES (a future builder toggle), not extra cards.
        html = s3.puts[0]["Body"].decode("utf-8")
        self.assertIn("Standard Price", html)
        self.assertNotIn("Upsell Price", html)
        self.assertNotIn("Sale Price", html)
        self.assertNotIn("Flash Sale Price", html)

    def test_publish_page_document_sorts_landing_page_prices_by_quantity(self):
        product = copy.deepcopy(self.product)
        product["prices"] = [
            {
                "price_id": "price_one",
                "currency": "usd",
                "unit_amount": 3709,
                "quantity": 1,
                "context": "standard",
            },
            {
                "price_id": "price_two",
                "currency": "usd",
                "unit_amount": 6694,
                "quantity": 2,
                "context": "standard",
            },
            {
                "price_id": "price_three",
                "currency": "usd",
                "unit_amount": 8990,
                "quantity": 3,
                "context": "standard",
            },
            {
                "price_id": "price_upsell",
                "currency": "usd",
                "unit_amount": 2217,
                "quantity": 1,
                "context": "upsell",
            },
        ]
        product["default_price_id"] = "price_two"

        offer = copy.deepcopy(self.offer)
        offer["eligibility"] = {
            "allowed_price_contexts": ["standard", "sale", "flash_sale"],
        }
        offer["items"][0]["selectable_prices"] = [
            {"price_id": "price_three", "quantity": 3, "label": "3 Containers"},
            {"price_id": "price_one", "quantity": 1, "label": "1 Container"},
            {"price_id": "price_upsell", "quantity": 1, "label": "1 Container Upsell"},
            {"price_id": "price_two", "quantity": 2, "label": "2 Containers"},
        ]
        offer["items"][0]["default_price_id"] = "price_two"

        s3 = FakeS3Client()
        publish_page_document(
            self.page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", [product]),
            s3_client=s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        html = s3.puts[0]["Body"].decode("utf-8")
        self.assertNotIn("1 Container Upsell", html)
        self.assertLess(html.index("1 Container"), html.index("2 Containers"))
        self.assertLess(html.index("2 Containers"), html.index("3 Containers"))

    def test_publish_page_document_writes_published_html_and_invalidates_cloudfront(self):
        page = copy.deepcopy(self.page)
        page.update({
            "status": "published",
            "PK": "TENANT#tenant_demo",
            "SK": "PAGE#page_simple_coffee",
            "GSI1PK": "PAGE#page_simple_coffee",
        })

        result = publish_page_document(
            page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            cloudfront_client=self.cloudfront,
            pages_distribution_id="DIST123",
        )

        self.assertEqual([put["Key"] for put in self.s3.puts], [
            "preview/tenant_demo/page_simple_coffee/index.html",
            "page_simple_coffee/index.html",
        ])
        self.assertEqual(result["invalidation"]["paths"], ["/page_simple_coffee/index.html"])
        self.assertEqual(self.cloudfront.invalidations[0]["DistributionId"], "DIST123")
        invalidation_batch = self.cloudfront.invalidations[0]["InvalidationBatch"]
        self.assertEqual(invalidation_batch["Paths"], {
            "Quantity": 1,
            "Items": ["/page_simple_coffee/index.html"],
        })
        self.assertTrue(invalidation_batch["CallerReference"].startswith("page_simple_coffee:publish:"))

    def test_publish_page_document_rejects_missing_offer(self):
        missing_offers = FakeRepository("offer_id", [])

        with self.assertRaisesRegex(PublishError, "Offer 'offer_simple_coffee'"):
            publish_page_document(
                self.page,
                offers_repository=missing_offers,
                products_repository=self.products_repo,
                s3_client=self.s3,
                pages_bucket="pages",
                preview_bucket="preview",
                environment="dev",
            )

    def test_stream_handler_publishes_page_records(self):
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {"NewImage": stream_image(self.page)},
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "pages",
            "PAGES_PREVIEW_BUCKET": "preview",
            "PAGES_DISTRIBUTION_DOMAIN": "pages.example.com",
            "PREVIEW_DISTRIBUTION_DOMAIN": "preview.example.com",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(len(self.s3.puts), 1)
        self.assertEqual(self.s3.puts[0]["Key"], "preview/tenant_demo/page_simple_coffee/index.html")

    def test_stream_handler_unpublish_deletes_public_artifact_and_writes_preview(self):
        old_page = copy.deepcopy(self.page)
        old_page["status"] = "published"
        new_page = copy.deepcopy(self.page)
        new_page["status"] = "draft"
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {
                        "OldImage": stream_image(old_page),
                        "NewImage": stream_image(new_page),
                    },
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "pages",
            "PAGES_PREVIEW_BUCKET": "preview",
            "PAGES_DISTRIBUTION_ID": "DIST123",
            "PAGES_DISTRIBUTION_DOMAIN": "pages.example.com",
            "PREVIEW_DISTRIBUTION_DOMAIN": "preview.example.com",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        deletes = [(item["Bucket"], item["Key"]) for item in self.s3.deletes]
        # The unpublish deletes the published artifact first...
        self.assertEqual(deletes[:2], [
            ("preview", "preview/tenant_demo/page_simple_coffee/index.html"),
            ("pages", "page_simple_coffee/index.html"),
        ])
        # ...then the re-render cleans up the now-disabled /sale //flash-sale sibling artifacts.
        self.assertIn(("preview", "preview/tenant_demo/page_simple_coffee/sale/index.html"), deletes)
        self.assertIn(("preview", "preview/tenant_demo/page_simple_coffee/flash-sale/index.html"), deletes)
        self.assertEqual([put["Key"] for put in self.s3.puts], ["preview/tenant_demo/page_simple_coffee/index.html"])

    def test_stream_handler_reports_failed_records(self):
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {"NewImage": stream_image(self.page)},
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "",
            "PAGES_PREVIEW_BUCKET": "",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "record-1"}]})


class StorefrontHomepageTests(unittest.TestCase):
    def setUp(self):
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()

    def test_offerless_homepage_publishes_catalog_grid_linking_to_slugs(self):
        # An offer-less storefront homepage: no primary offer, a brand hero + a catalog grid whose one card
        # links to the coffee offer's landing slug on the verified custom domain.
        page = {
            "schema_version": "2026-01-01", "document_type": "page", "page_id": "page_home01",
            "tenant_id": self.offer["tenant_id"],
            "name": "Storefront", "status": "published", "route": {"slug": "home"},
            "sections": [
                {"id": "h", "type": "brand_hero", "headline": "Bean Co", "tagline": "Roasted to order"},
                {"id": "g", "type": "catalog_grid", "heading": "Shop all",
                 "items": [{"offer_id": self.offer["offer_id"], "slug": "/coffee"}]},
                {"id": "f", "type": "legal_footer"},
            ],
        }
        site = {
            "tenant_id": self.offer["tenant_id"], "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/": {"page_id": "page_home01", "page_type": "homepage"}},
        }
        publish_page_document(
            page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]), s3_client=self.s3,
            pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
        )
        published = [p for p in self.s3.puts if "preview/" not in p["Key"]][0]["Body"].decode()
        self.assertIn('data-section-type="brand_hero"', published)
        self.assertIn('data-section-type="catalog_grid"', published)
        # The card resolved the referenced offer (loaded despite no primary offer) and links to its Site slug.
        self.assertIn('href="https://shop.example.com/coffee"', published)
        self.assertIn("<h1>Bean Co</h1>", published)


class CategoryPageTests(unittest.TestCase):
    def _site(self):
        return {"pages": {
            "/": {"page_id": "page_home", "page_type": "homepage"},
            "/creatine": {"page_id": "page_a", "page_type": "landing", "offer_id": "offer_a", "category": "supplements"},
            "/whey": {"page_id": "page_b", "page_type": "landing", "offer_id": "offer_b", "category": "supplements"},
            "/mat": {"page_id": "page_c", "page_type": "landing", "offer_id": "offer_c", "category": "gear"},
            "/category/supplements": {"page_id": "page_cat", "page_type": "category", "category": "supplements"},
        }}

    def test_resolve_category_grid_pulls_matching_landing_pages(self):
        page = {"sections": [{"id": "g", "type": "catalog_grid", "category": "supplements"}]}
        resolve_category_grids(page, self._site())
        items = page["sections"][0]["items"]
        self.assertEqual({i["offer_id"] for i in items}, {"offer_a", "offer_b"})   # gear excluded
        self.assertEqual({i["slug"] for i in items}, {"/creatine", "/whey"})

    def test_resolve_leaves_curated_grid_untouched(self):
        page = {"sections": [{"id": "g", "type": "catalog_grid", "items": [{"offer_id": "x", "slug": "/x"}]}]}
        resolve_category_grids(page, self._site())
        self.assertEqual(page["sections"][0]["items"], [{"offer_id": "x", "slug": "/x"}])  # no category -> untouched

    def test_related_products_pulls_same_category_excluding_self(self):
        page = {"sections": [{"id": "r", "type": "related_products", "heading": "More"}]}
        added = resolve_related_products(page, self._site(), "supplements", "page_a")  # current page = page_a
        items = page["sections"][0]["items"]
        self.assertEqual({i["offer_id"] for i in items}, {"offer_b"})  # page_b only: self excluded, gear excluded
        self.assertEqual(added, ["offer_b"])

    def test_related_products_respects_limit(self):
        page = {"sections": [{"id": "r", "type": "related_products", "limit": 1}]}
        resolve_related_products(page, self._site(), "supplements", "page_x")  # not one of the pages -> both eligible
        self.assertEqual(len(page["sections"][0]["items"]), 1)

    def test_denormalize_records_offer_and_category(self):
        site = {"pages": {"/p": {"page_id": "page_a", "page_type": "landing"}}}
        self.assertTrue(_denormalize_page_catalog(site, "page_a", "offer_a", "supplements"))
        self.assertEqual(site["pages"]["/p"]["offer_id"], "offer_a")
        self.assertEqual(site["pages"]["/p"]["category"], "supplements")
        self.assertFalse(_denormalize_page_catalog(site, "page_a", "offer_a", "supplements"))  # idempotent


class FunnelAttachTests(unittest.TestCase):
    def test_site_page_slug_finds_and_misses(self):
        site = {"pages": {"/": {"page_id": "p_home"}, "/upsell-1": {"page_id": "p_up"}}}
        self.assertEqual(site_page_slug(site, "p_up"), "/upsell-1")
        self.assertEqual(site_page_slug(site, "p_home"), "/")
        self.assertEqual(site_page_slug(site, "p_gone"), "")

    def test_attach_adds_funnel_pages_at_derived_slugs(self):
        site = {"pages": {"/": {"page_id": "p_home"}}}
        page = {"post_checkout": {"thank_you_page": {"page_id": "p_ty"},
                                  "funnel_steps": [{"step_id": "upsell_1", "page_id": "p_up"}]}}
        updated, changed = attach_funnel_pages(site, page)
        self.assertTrue(changed)
        self.assertEqual(updated["pages"]["/thank-you"], {"page_id": "p_ty", "page_type": "thank_you", "enabled": True})
        self.assertEqual(updated["pages"]["/upsell-1"], {"page_id": "p_up", "page_type": "funnel_step", "enabled": True})

    def test_attach_is_idempotent_and_leaves_existing_placement(self):
        site = {"pages": {"/": {"page_id": "p_home"}, "/deal": {"page_id": "p_up"}}}
        page = {"post_checkout": {"funnel_steps": [{"step_id": "upsell_1", "page_id": "p_up"}]}}
        updated, changed = attach_funnel_pages(site, page)
        self.assertFalse(changed)  # p_up already routes at /deal; not moved to /upsell-1
        self.assertNotIn("/upsell-1", updated["pages"])

    def test_attach_suffixes_a_taken_slug(self):
        site = {"pages": {"/": {"page_id": "p_home"}, "/thank-you": {"page_id": "p_other"}}}
        page = {"post_checkout": {"thank_you_page": {"page_id": "p_ty"}}}
        updated, _ = attach_funnel_pages(site, page)
        self.assertEqual(updated["pages"]["/thank-you-2"]["page_id"], "p_ty")


class FunnelPublishIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-simple-coffee.json")
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()

    def test_publishing_funnel_entry_attaches_pages_and_rewrites_route_table(self):
        page = copy.deepcopy(self.page)
        page["page_id"] = "page_entry01"
        page["status"] = "published"
        page["post_checkout"] = {
            "thank_you_page": {"page_id": "page_ty01"},
            "funnel_steps": [{"step_id": "upsell_1", "page_id": "page_up01", "on_accept": "thank_you", "on_decline": "thank_you"}],
        }
        site = {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_ABC123",
            "tenant_id": "tenant_demo", "environment": "live", "name": "Demo", "status": "active",
            "hosting": {"type": "custom", "platform_hostname": "demo.jbay.uk", "custom_domain": "shop.example.com",
                        "verification": {"verified": True}},
            "organization": {"name": "Demo", "entity_type": "OnlineStore"},
            "domain_provisioning": {"status": "active"},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/": {"page_id": "page_entry01", "page_type": "landing", "enabled": True}},
            "created_at": 1, "updated_at": 1,
        }
        sites_repo = FakeSitesRepository([site])
        domains_repo = FakeDomainsIndexRepository()
        publish_page_document(
            page,
            offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=sites_repo, domains_index_repository=domains_repo,
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )
        attached = sites_repo.sites[0]["pages"]
        self.assertEqual(attached["/thank-you"], {"page_id": "page_ty01", "page_type": "thank_you", "enabled": True})
        self.assertEqual(attached["/upsell-1"], {"page_id": "page_up01", "page_type": "funnel_step", "enabled": True})
        # The denormalized route table the edge resolver reads was refreshed with the new slugs.
        self.assertTrue(domains_repo.records)
        routes = domains_repo.records[-1]["routes"]
        self.assertEqual(routes["/upsell-1"]["page_id"], "page_up01")
        self.assertEqual(routes["/thank-you"]["page_id"], "page_ty01")


if __name__ == "__main__":
    unittest.main()
