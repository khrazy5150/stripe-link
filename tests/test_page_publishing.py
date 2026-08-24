import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from handlers.page_publish import handler
from tests.fakes import FakeDocumentRepository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import (
    PublishError,
    _denormalize_page_catalog,
    _prune_unrenderable_landing_items,
    artifact_targets,
    attach_funnel_pages,
    attach_funnel_slugs,
    cascade_publish_collection_drafts,
    delete_page_artifacts,
    detach_page_from_sites,
    find_site_for_page,
    publish_page_document,
    catalog_grid_to_collection,
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
        self.page["stripe_mode"] = "live"  # publish tests assert the canonical live (root-key) serving path
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
        # The published artifact makes the BROWSER revalidate (max-age=0) so a re-publish shows without a hard
        # refresh, while the CDN still caches it (s-maxage); the preview is never cached.
        self.assertIn("max-age=0", targets[1]["cache_control"])
        self.assertIn("s-maxage=", targets[1]["cache_control"])
        self.assertIn("no-store", targets[0]["cache_control"])

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
        # A funnel also gets a synthesized thank-you terminus artifact.
        ty_id = f"{page['page_id']}__thank_you"
        self.assertIn(("pages", artifact_paths("tenant_demo", ty_id)["published"]), keys)
        ty_body = next(put["Body"] for put in self.s3.puts if put["Key"] == artifact_paths("tenant_demo", ty_id)["published"])
        self.assertIn(b"Thank You for Your Purchase", ty_body)

    def test_attach_funnel_slugs_sequence_and_retire(self):
        # A sequence funnel attaches /upsell + /thank-you to the root page (no /downsell — in-place swap), each
        # carrying funnel_role + strategy so the resolver can serve them on the custom domain (P2b).
        product = copy.deepcopy(self.product)
        product["prices"].append({"price_id": "price_up", "stripe_price_id": "sp_up", "context": "upsell",
                                  "unit_amount": 500, "currency": "usd", "quantity": 1})
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"upsells": [{"product_id": product["product_id"], "price_id": "price_up"}]}
        page_id = self.page["page_id"]
        site = {"tenant_id": "tenant_demo", "pages": {"/": {"page_id": page_id, "page_type": "landing"}}}

        updated, changed = attach_funnel_slugs(site, {"page_id": page_id}, offer, {product["product_id"]: product})
        self.assertTrue(changed)
        self.assertEqual(sorted(updated["pages"]), ["/", "/thank-you", "/upsell"])
        self.assertEqual(updated["pages"]["/upsell"]["funnel_role"], "upsell")
        self.assertEqual(updated["pages"]["/upsell"]["strategy"], "sequence")
        self.assertEqual(updated["pages"]["/thank-you"]["funnel_role"], "thank_you")

        # Remove the funnel (no upsells) -> our reserved slugs retire; a tenant's own same-named page is untouched.
        offer["funnel"] = {"upsells": []}
        updated["pages"]["/upsell-guide"] = {"page_id": "page_Guide"}  # not ours (no funnel_role)
        retired, changed2 = attach_funnel_slugs(updated, {"page_id": page_id}, offer, {product["product_id"]: product})
        self.assertTrue(changed2)
        self.assertNotIn("/upsell", retired["pages"])
        self.assertNotIn("/thank-you", retired["pages"])
        self.assertIn("/upsell-guide", retired["pages"])

    def test_attach_funnel_slugs_only_on_root_page(self):
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"upsells": [{"product_id": self.product["product_id"], "price_id": "price_up"}]}
        # The page is attached at a non-root slug -> no funnel slugs (funnel lives on the Site's "/").
        site = {"tenant_id": "tenant_demo", "pages": {"/other": {"page_id": self.page["page_id"]}}}
        updated, changed = attach_funnel_slugs(site, {"page_id": self.page["page_id"]}, offer, {self.product["product_id"]: self.product})
        self.assertFalse(changed)
        self.assertEqual(updated, site)

    def test_publish_writes_carousel_artifacts_for_four_or_more_upsells(self):
        # >3 upsells -> carousel strategy: ONE __upsell_carousel (+ __downsell_carousel when any upsell product
        # carries a downsell price) instead of per-sequence __upsell_N pages (plans/OFFER_MODEL_REDESIGN.md §6).
        products = [copy.deepcopy(self.product)]
        upsells, downsells = [], []
        for i in range(4):
            p = copy.deepcopy(self.product)
            p["product_id"] = f"prod_up_{i}"
            p["prices"].append({"price_id": f"price_up_{i}", "stripe_price_id": f"sp_up_{i}", "context": "upsell",
                                "unit_amount": 500 + i, "currency": "usd", "quantity": 1})
            if i < 2:  # two of the four also carry a downsell price
                p["prices"].append({"price_id": f"price_down_{i}", "stripe_price_id": f"sp_down_{i}",
                                    "context": "downsell", "unit_amount": 200 + i, "currency": "usd", "quantity": 1})
                downsells.append({"product_id": f"prod_up_{i}", "price_id": f"price_down_{i}"})
            products.append(p)
            upsells.append({"product_id": f"prod_up_{i}", "price_id": f"price_up_{i}"})
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"upsells": upsells, "downsells": downsells}
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        publish_page_document(
            page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", products),
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="dev",
            pages_domain="p", preview_domain="pv",
        )
        keys = [put["Key"] for put in self.s3.puts]
        uc_key = artifact_paths("tenant_demo", f"{page['page_id']}__upsell_carousel")["published"]
        dc_key = artifact_paths("tenant_demo", f"{page['page_id']}__downsell_carousel")["published"]
        self.assertIn(uc_key, keys)
        self.assertIn(dc_key, keys)
        # Carousel mode emits NO per-sequence upsell pages, but still the thank-you terminus.
        self.assertFalse(any("__upsell_1" in k for k in keys))
        self.assertIn(artifact_paths("tenant_demo", f"{page['page_id']}__thank_you")["published"], keys)
        # One card per upsell on the grid; the downsell carousel only has the two products that carry a downsell.
        uc_body = next(put["Body"] for put in self.s3.puts if put["Key"] == uc_key)
        dc_body = next(put["Body"] for put in self.s3.puts if put["Key"] == dc_key)
        self.assertEqual(uc_body.count(b'class="sl-pp-card"'), 4)
        self.assertEqual(dc_body.count(b'class="sl-pp-card"'), 2)

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

    def test_seo_disabled_site_is_noindex_disallow_and_no_indexnow(self):
        # Site-level SEO opt-out: every page renders noindex, robots.txt disallows, sitemap is empty, no IndexNow.
        page = copy.deepcopy(self.page)
        page["status"] = "published"
        site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible", "seo_enabled": False},
            "seo": {"indexnow_key": "k1abc"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }
        with patch("stripe_link.runtime.publishing.submit_indexnow") as ping:
            publish_page_document(
                page, offers_repository=self.offers_repo, products_repository=self.products_repo,
                sites_repository=FakeSitesRepository([site]), s3_client=self.s3,
                pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        ping.assert_not_called()  # no IndexNow ping when search visibility is off
        published = next(p["Body"] for p in self.s3.puts if p["Key"] == artifact_paths("tenant_demo", "page_simple_coffee")["published"]).decode()
        self.assertIn('name="robots" content="noindex,nofollow"', published)
        robots = next(p["Body"] for p in self.s3.puts if p["Key"].endswith("robots.txt")).decode()
        self.assertIn("Disallow: /", robots)

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

    def test_publish_page_document_uses_host_agnostic_checkout_with_mode(self):
        # Decoupled model (plans/STRIPE_MODE_DECOUPLING.md P4): the checkout base is the DEPLOY-CONFIGURED host
        # (PUBLIC_CHECKOUT_BASE_URL, set per stage) — host-agnostic by mode (no dev/prod split by mode); the offer's
        # Stripe mode travels as ?mode= on the Buy URL.
        with patch.dict(os.environ, {"PUBLIC_CHECKOUT_BASE_URL": "https://prod.juniorbay.com/checkout"}, clear=False):
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
        self.assertIn("https://prod.juniorbay.com/checkout?", html)  # the configured base, not an env-split host
        self.assertNotIn("dev.juniorbay.com/checkout", html)
        self.assertIn("clientID=tenant_demo", html)
        self.assertIn("offer=offer_simple_coffee", html)
        self.assertIn("page_id=page_simple_coffee", html)
        self.assertIn("mode=", html)

    def test_test_mode_page_publishes_under_test_prefix(self):
        # P5 (plans/STRIPE_MODE_DECOUPLING.md): a test-mode page's artifacts go under a `test/` prefix so they
        # never collide with the live promotion of the same page_id; live pages keep the root key.
        self.page["stripe_mode"] = "test"
        self.page["status"] = "published"
        result = publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )
        keys = [a["key"] for a in result["artifacts"]]
        self.assertIn("test/page_simple_coffee/index.html", keys)
        self.assertIn("preview/test/tenant_demo/page_simple_coffee/index.html", keys)
        self.assertNotIn("page_simple_coffee/index.html", keys)  # no bare (live) key for a test page

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
            # The coffee offer's page is on the Site at /coffee (offer_id recorded), so its grid card resolves.
            "pages": {"/": {"page_id": "page_home01", "page_type": "homepage"},
                      "/coffee": {"page_id": "page_coffee", "page_type": "landing", "offer_id": self.offer["offer_id"]}},
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
        # The card resolved the referenced offer (loaded despite no primary offer) and links to its Site slug
        # as a host-relative link (Slice 2 — one artifact navigates on any serving host).
        self.assertIn('href="/coffee"', published)
        self.assertIn("<h1>Bean Co</h1>", published)


class PlatformHostServingTests(unittest.TestCase):
    """Serving a Site on its free platform host ({label}.jbay.uk / .jbay.be) — navigable chrome + relative
    links, always noindex, gated behind PLATFORM_SERVING_ENABLED (plans/PLATFORM_HOSTNAME_SERVING.md Slice 2)."""

    def setUp(self):
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()

    def _page(self):
        return {
            "schema_version": "2026-01-01", "document_type": "page", "page_id": "page_home01",
            "tenant_id": self.offer["tenant_id"], "name": "Storefront", "status": "published",
            "route": {"slug": "home"},
            "sections": [
                {"id": "h", "type": "brand_hero", "headline": "Bean Co", "tagline": "Roasted to order"},
                {"id": "g", "type": "catalog_grid", "heading": "Shop all",
                 "items": [{"offer_id": self.offer["offer_id"], "slug": "/coffee"}]},
            ],
        }

    def _platform_site(self):
        # A platform-only Site: no custom domain, but a reserved free platform host.
        return {
            "tenant_id": self.offer["tenant_id"], "site_id": "site_p",
            "organization": {"name": "Bean Co", "entity_type": "OnlineStore"},
            "hosting": {"type": "platform", "platform_hostname": "bean-co.jbay.uk", "custom_domain": None},
            "indexing": {"eligibility": "blocked"},
            # The coffee offer's page is on the Site at /coffee so its grid card resolves to a real store page.
            "pages": {"/": {"page_id": "page_home01", "page_type": "homepage"},
                      "/coffee": {"page_id": "page_coffee", "page_type": "landing", "offer_id": self.offer["offer_id"]}},
        }

    def _publish(self, site):
        publish_page_document(
            self._page(), offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]), s3_client=self.s3,
            pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
        )
        return [p for p in self.s3.puts if "preview/" not in p["Key"]][0]["Body"].decode()

    def test_platform_serving_on_renders_navigable_chrome_and_platform_canonical(self):
        with patch.dict(os.environ, {"PLATFORM_SERVING_ENABLED": "true"}, clear=False):
            published = self._publish(self._platform_site())
        # canonical points at the platform host, chrome renders (card + brand are real relative links)...
        self.assertIn('<link rel="canonical" href="https://bean-co.jbay.uk/">', published)
        self.assertIn('href="/coffee"', published)
        self.assertIn('<a class="sl-brand" href="/">Bean Co</a>', published)
        # ...but the platform host is never indexed (reputation floor).
        self.assertIn('<meta name="robots" content="noindex', published)

    def test_platform_serving_off_leaves_platform_site_chromeless(self):
        # Default (flag off): the platform-only Site keeps its interim artifact identity — no chrome, the card is
        # a plain unlinked tile — so nothing sprouts navigation before the *.jbay.* edge Worker is wired.
        published = self._publish(self._platform_site())
        self.assertNotIn('href="/coffee"', published)
        self.assertIn('<div class="sl-catalog-card">', published)
        self.assertNotIn("bean-co.jbay.uk", published)
        self.assertIn('<meta name="robots" content="noindex', published)


class GridToCollectionMigrationTests(unittest.TestCase):
    """P1d migration (plans/SITE_COLLECTIONS.md): convert an inline catalog_grid into a Collection + embed."""

    def _site(self):
        return {"site_id": "site_x", "pages": {
            "/creatine": {"page_id": "page_a", "offer_id": "offer_a", "category": "supplements"},
            "/whey": {"page_id": "page_b", "offer_id": "offer_b", "category": "supplements"},
            "/mat": {"page_id": "page_c", "offer_id": "offer_c", "category": "gear"},
        }}

    def test_scope_all_grid_becomes_all_collection(self):
        section = {"type": "catalog_grid", "scope": "all", "heading": "Shop all", "items": []}
        coll = catalog_grid_to_collection(section, self._site(), "t1", "coll_1")
        self.assertEqual((coll["rule"], coll["name"], coll["site_id"]), ("all", "Shop all", "site_x"))
        self.assertEqual(coll["presentation"], {"heading": "Shop all"})
        self.assertEqual(section["collection_id"], "coll_1")
        self.assertNotIn("scope", section)  # inline config now lives on the Collection

    def test_category_grid_becomes_category_collection(self):
        section = {"type": "catalog_grid", "category": "gear"}
        coll = catalog_grid_to_collection(section, self._site(), "t1", "coll_1")
        self.assertEqual((coll["rule"], coll["category"]), ("category", "gear"))
        self.assertNotIn("category", section)

    def test_curated_grid_becomes_manual_with_page_members(self):
        section = {"type": "catalog_grid", "items": [{"offer_id": "offer_b"}, {"offer_id": "offer_a"}, {"offer_id": "gone"}]}
        coll = catalog_grid_to_collection(section, self._site(), "t1", "coll_1")
        self.assertEqual(coll["rule"], "manual")
        self.assertEqual(coll["members"], ["page_b", "page_a"])  # offer_id->page_id, order kept, off-Site dropped
        self.assertNotIn("items", section)

    def test_idempotent_when_already_a_collection_embed(self):
        section = {"type": "catalog_grid", "collection_id": "coll_existing"}
        self.assertIsNone(catalog_grid_to_collection(section, self._site(), "t1", "coll_1"))
        self.assertEqual(section["collection_id"], "coll_existing")

    def test_migration_is_behavior_preserving(self):
        # Migrating a curated grid then resolving via its Collection yields the SAME items as resolving the
        # original inline grid — the whole point of the migration.
        site = self._site()
        inline = {"sections": [{"id": "g", "type": "catalog_grid",
                                "items": [{"offer_id": "offer_b", "slug": "/x"}, {"offer_id": "offer_a", "slug": "/y"}]}]}
        before = copy.deepcopy(inline)
        resolve_category_grids(before, site)
        coll = catalog_grid_to_collection(inline["sections"][0], site, "t1", "coll_1")
        resolve_category_grids(inline, site, {"coll_1": coll})
        self.assertEqual(inline["sections"][0]["items"], before["sections"][0]["items"])

    def _backfill_fixtures(self):
        pages = FakeDocumentRepository("page_id")
        pages.put({"tenant_id": "t1", "page_id": "page_store",
                   "sections": [{"id": "g", "type": "catalog_grid", "scope": "all", "heading": "Shop all"}]})
        pages.put({"tenant_id": "t1", "page_id": "page_plain", "sections": [{"id": "h", "type": "brand_hero"}]})
        sites = FakeSitesRepository([{"tenant_id": "t1", "site_id": "site_x", "pages": {"/": {"page_id": "page_store"}}}])
        return pages, sites, FakeDocumentRepository("collection_id")

    def test_backfill_migrates_page_and_is_idempotent(self):
        from stripe_link.runtime.publishing import backfill_page_collections
        pages, sites, colls = self._backfill_fixtures()
        ids = iter(["coll_1", "coll_2"])
        summary = backfill_page_collections(pages, sites, colls, "t1", id_factory=lambda: next(ids), dry_run=False)
        self.assertEqual((summary["pages_migrated"], summary["collections_created"]), (1, 1))
        self.assertEqual(pages.get("t1", "page_store")["sections"][0]["collection_id"], "coll_1")  # page rewritten
        self.assertEqual(colls.get("t1", "coll_1")["rule"], "all")  # collection persisted (rule from scope)
        again = backfill_page_collections(pages, sites, colls, "t1", id_factory=lambda: "coll_x", dry_run=False)
        self.assertEqual(again["pages_migrated"], 0)  # already migrated -> skipped

    def test_backfill_dry_run_writes_nothing(self):
        from stripe_link.runtime.publishing import backfill_page_collections
        pages, sites, colls = self._backfill_fixtures()
        summary = backfill_page_collections(pages, sites, colls, "t1", id_factory=lambda: "coll_1", dry_run=True)
        self.assertEqual(summary["pages_migrated"], 1)  # reported...
        self.assertNotIn("collection_id", pages.get("t1", "page_store")["sections"][0])  # ...but nothing written
        self.assertIsNone(colls.get("t1", "coll_1"))


class CascadePublishDraftMembersTests(unittest.TestCase):
    """Auto-publish never-published draft members of a manual collection when the embedding page publishes
    (plans/SITE_COLLECTIONS.md — kill the hunt-down-drafts friction)."""

    def setUp(self):
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.tenant = self.offer["tenant_id"]
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()

    def _member(self, status="draft", **extra):
        # A draft offer page attached to the Site, selected into the storefront's collection.
        return {"schema_version": "2026-01-01", "document_type": "page", "page_id": "page_coffee",
                "tenant_id": self.tenant, "name": "Coffee", "status": status, "route": {"slug": "coffee"},
                "offer_id": self.offer["offer_id"],
                "sections": [{"id": "hero", "type": "hero", "html": "Coffee"}], **extra}

    def _storefront(self):
        return {"schema_version": "2026-01-01", "document_type": "page", "page_id": "page_home01",
                "tenant_id": self.tenant, "name": "Storefront", "status": "published", "route": {"slug": "home"},
                "sections": [
                    {"id": "h", "type": "brand_hero", "headline": "Bean Co"},
                    {"id": "g", "type": "catalog_grid", "heading": "Shop all", "collection_id": "coll_m"},
                ]}

    def _site(self):
        # The member is attached to the Site (its slug exists) but as a DRAFT: no offer_id yet, and its route
        # entry is disabled (the dashboard sets enabled = status=='published'). So the grid would drop it AND the
        # edge resolver would 404 its card until it's published.
        return {"schema_version": "2026-07-20", "document_type": "site", "site_id": "site_x",
                "tenant_id": self.tenant, "environment": "live", "name": "Shop", "status": "active",
                "hosting": {"type": "custom", "platform_hostname": "shop.jbay.uk",
                            "custom_domain": "shop.example.com", "verification": {"verified": True}},
                "organization": {"name": "Shop", "entity_type": "OnlineStore"},
                "domain_provisioning": {"status": "active"},
                "indexing": {"eligibility": "eligible"}, "created_at": 1, "updated_at": 1,
                "pages": {"/": {"page_id": "page_home01", "page_type": "landing", "enabled": True},
                          "/coffee": {"page_id": "page_coffee", "page_type": "landing", "enabled": False}}}

    def _publish(self, pages_repo, sites_repo):
        colls = FakeDocumentRepository("collection_id")
        colls.put({"tenant_id": self.tenant, "collection_id": "coll_m", "site_id": "site_x",
                   "rule": "manual", "members": ["page_coffee"]})
        publish_page_document(
            self._storefront(), offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=sites_repo, pages_repository=pages_repo, collections_repository=colls, s3_client=self.s3,
            pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
        )
        return [p for p in self.s3.puts if "preview/" not in p["Key"]][0]["Body"].decode()

    def test_draft_member_is_published_and_appears_in_grid(self):
        pages = FakeDocumentRepository("page_id")
        pages.put(self._member())
        sites = FakeSitesRepository([self._site()])
        published = self._publish(pages, sites)
        # The member flipped to published (its own stream would then render its artifact)...
        member = pages.get(self.tenant, "page_coffee")
        self.assertEqual(member["status"], "published")
        self.assertTrue(member["published_at"])
        # ...and THIS render already links its card (offer_id was denormalized onto the in-memory Site first).
        self.assertIn('href="/coffee"', published)
        # ...and its Site route was re-enabled + persisted, so the edge resolver serves it (not "store not active").
        site = sites.list_for_tenant(self.tenant)[0]
        self.assertIs(site["pages"]["/coffee"]["enabled"], True)
        self.assertEqual(site["pages"]["/coffee"]["offer_id"], self.offer["offer_id"])

    def test_enable_site_route_flips_disabled_entry(self):
        from stripe_link.runtime.publishing import _enable_site_route
        site = {"pages": {"/x": {"page_id": "p1", "enabled": False}, "/y": {"page_id": "p2", "enabled": True}}}
        self.assertTrue(_enable_site_route(site, "p1"))
        self.assertIs(site["pages"]["/x"]["enabled"], True)
        self.assertFalse(_enable_site_route(site, "p2"))  # already enabled → no change

    def test_once_published_since_unpublished_member_is_republished(self):
        # A member that was live before and is now a draft (unpublished to edit, then forgot to re-publish) IS
        # brought back — the tenant shouldn't have to remember which pages were once published.
        pages = FakeDocumentRepository("page_id")
        pages.put(self._member(status="draft", published_at=1700000000))
        sites = FakeSitesRepository([self._site()])
        published = self._publish(pages, sites)
        self.assertEqual(pages.get(self.tenant, "page_coffee")["status"], "published")  # republished
        self.assertIn('href="/coffee"', published)  # and back in the grid

    def test_already_published_member_not_rewritten_but_route_healed(self):
        # An already-live member is NOT re-written (no page write → the member's own stream can't re-cascade →
        # termination) — but its stale-disabled Site route IS healed so its card still resolves.
        pages = FakeDocumentRepository("page_id")
        pages.put(self._member(status="published", published_at=1700000000))
        colls = {"coll_m": {"collection_id": "coll_m", "rule": "manual", "members": ["page_coffee"]}}
        site = self._site()  # /coffee route is enabled=False (stale from draft time)
        result = cascade_publish_collection_drafts(self._storefront(), colls, site, pages_repository=pages, now=123)
        self.assertEqual(result["published"], [])          # no page re-write → cascade terminates
        self.assertTrue(result["site_changed"])            # ...but the route was healed
        self.assertIs(site["pages"]["/coffee"]["enabled"], True)

    def test_archived_member_left_alone(self):
        pages = FakeDocumentRepository("page_id")
        pages.put(self._member(status="archived"))
        colls = {"coll_m": {"collection_id": "coll_m", "rule": "manual", "members": ["page_coffee"]}}
        site = self._site()
        result = cascade_publish_collection_drafts(self._storefront(), colls, site, pages_repository=pages, now=123)
        self.assertEqual(result["published"], [])
        self.assertIs(site["pages"]["/coffee"]["enabled"], False)  # archived → route untouched

    def test_no_cascade_for_all_rule_collection(self):
        # An 'all' collection has no hand-selected members; nothing to auto-publish.
        pages = FakeDocumentRepository("page_id")
        pages.put(self._member())
        colls = {"coll_m": {"collection_id": "coll_m", "rule": "all"}}
        result = cascade_publish_collection_drafts(
            self._storefront(), colls, self._site(), pages_repository=pages, now=123)
        self.assertEqual(result["published"], [])
        self.assertEqual(pages.get(self.tenant, "page_coffee")["status"], "draft")


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

    def test_resolve_curated_grid_keeps_on_site_offers_repointed_and_drops_others(self):
        # A curated grid resolves against the Site route map: an item whose offer is a published page on the
        # Site is re-pointed to that page's real Site slug (its stored slug is ignored); an item whose offer
        # isn't on the Site is dropped, so a card never links to a dead path.
        page = {"sections": [{"id": "g", "type": "catalog_grid", "items": [
            {"offer_id": "offer_b", "slug": "/some-old-landing-slug"},  # on-Site -> re-pointed to /whey
            {"offer_id": "offer_missing", "slug": "/x"},                # not on Site -> dropped
        ]}]}
        resolve_category_grids(page, self._site())
        self.assertEqual(page["sections"][0]["items"], [{"offer_id": "offer_b", "slug": "/whey"}])

    def test_resolve_curated_grid_preserves_order(self):
        page = {"sections": [{"id": "g", "type": "catalog_grid", "items": [
            {"offer_id": "offer_c", "slug": "/x"}, {"offer_id": "offer_a", "slug": "/y"},
        ]}]}
        resolve_category_grids(page, self._site())
        self.assertEqual([i["slug"] for i in page["sections"][0]["items"]], ["/mat", "/creatine"])  # tenant order kept

    def test_resolve_scope_all_pulls_every_offer_page(self):
        # A brand-first storefront homepage (scope="all") auto-fills with EVERY offer page on the Site,
        # regardless of category; non-offer pages (homepage, category page) are excluded.
        page = {"sections": [{"id": "g", "type": "catalog_grid", "scope": "all", "items": []}]}
        resolve_category_grids(page, self._site())
        items = page["sections"][0]["items"]
        self.assertEqual({i["offer_id"] for i in items}, {"offer_a", "offer_b", "offer_c"})  # all offers, all categories
        self.assertNotIn("page_home", {i.get("page_id") for i in items})  # the homepage itself isn't a card

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

    def test_collection_embed_manual_keeps_order_and_drops_off_site(self):
        # A catalog_grid referencing a Collection resolves its members (page ids) to real Site slugs, in the
        # collection's order, dropping any not published on the Site (plans/SITE_COLLECTIONS.md P1).
        coll = {"collection_id": "c1", "rule": "manual", "members": ["page_b", "page_a", "page_missing"]}
        page = {"sections": [{"id": "g", "type": "catalog_grid", "collection_id": "c1"}]}
        resolve_category_grids(page, self._site(), {"c1": coll})
        self.assertEqual([i["slug"] for i in page["sections"][0]["items"]], ["/whey", "/creatine"])

    def test_collection_embed_all_rule_pulls_every_offer_page(self):
        page = {"sections": [{"id": "g", "type": "catalog_grid", "collection_id": "c1"}]}
        resolve_category_grids(page, self._site(), {"c1": {"collection_id": "c1", "rule": "all"}})
        self.assertEqual({i["offer_id"] for i in page["sections"][0]["items"]}, {"offer_a", "offer_b", "offer_c"})

    def test_collection_embed_category_rule(self):
        coll = {"collection_id": "c1", "rule": "category", "category": "gear"}
        page = {"sections": [{"id": "g", "type": "catalog_grid", "collection_id": "c1"}]}
        resolve_category_grids(page, self._site(), {"c1": coll})
        self.assertEqual([i["slug"] for i in page["sections"][0]["items"]], ["/mat"])

    def test_collection_embed_heading_falls_back_to_presentation(self):
        coll = {"collection_id": "c1", "rule": "all", "presentation": {"heading": "Shop all"}}
        page = {"sections": [{"id": "g", "type": "catalog_grid", "collection_id": "c1"}]}
        resolve_category_grids(page, self._site(), {"c1": coll})
        self.assertEqual(page["sections"][0]["heading"], "Shop all")

    def test_load_page_collections_gathers_referenced_ids(self):
        from stripe_link.runtime.publishing import load_page_collections

        class Repo:
            def get(self, tenant_id, cid):
                return {"collection_id": cid, "rule": "all"} if cid == "c1" else None
        page = {"sections": [{"type": "catalog_grid", "collection_id": "c1"},
                             {"type": "catalog_grid"}, {"type": "brand_hero"}]}
        out = load_page_collections(Repo(), "t1", page)
        self.assertEqual(list(out.keys()), ["c1"])
        self.assertEqual(load_page_collections(None, "t1", page), {})

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
        self.page["stripe_mode"] = "live"  # publish tests assert the canonical live (root-key) serving path
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

    def test_republish_without_slug_changes_still_syncs_platform_index_record(self):
        # Regression (PLATFORM_HOSTNAME_SERVING.md): the domain index — including the free platform-hostname
        # record — must be (re)written on EVERY publish, not only when a slug is newly attached. A page with no
        # funnel/context slugs to attach (nothing changes) previously skipped the sync, so {label}.jbay.uk never
        # got its resolver record and stayed unresolvable.
        page = copy.deepcopy(self.page)
        page["page_id"] = "page_home01"
        page["status"] = "published"
        page.pop("post_checkout", None)  # no funnel -> attach produces no change
        site = {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_PLAT",
            "tenant_id": "tenant_demo", "environment": "live", "name": "Demo", "status": "active",
            "hosting": {"type": "custom", "platform_hostname": "demo.jbay.uk", "custom_domain": "shop.example.com",
                        "verification": {"verified": True}},
            "organization": {"name": "Demo", "entity_type": "OnlineStore"},
            "domain_provisioning": {"status": "active"},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/": {"page_id": "page_home01", "page_type": "homepage", "enabled": True}},
            "created_at": 1, "updated_at": 1,
        }
        domains_repo = FakeDomainsIndexRepository()
        publish_page_document(
            page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            sites_repository=FakeSitesRepository([site]), domains_index_repository=domains_repo,
            s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="prod",
            pages_domain="pages.example.com", preview_domain="preview.example.com",
        )
        platform = [r for r in domains_repo.records if r.get("host_kind") == "platform"]
        self.assertTrue(platform, "the platform-hostname index record must be written even with no slug change")
        self.assertEqual(platform[-1]["domain"], "demo.jbay.uk")
        self.assertEqual(platform[-1]["status"], "active")


if __name__ == "__main__":
    unittest.main()


class _FakeKeysRepo:
    def __init__(self, doc):
        self.doc = doc
    def get(self, tenant_id, mode="test"):
        return dict(self.doc) if self.doc else None


class BnplPublishMessagingTests(unittest.TestCase):
    """publish_page_document injects the on-page BNPL messaging when the tenant has installments enabled
    (plans/BNPL_PAYMENT_METHODS.md P3)."""

    def setUp(self):
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.page = load_fixture("page-simple-coffee.json")
        self.page["stripe_mode"] = "live"  # publish tests assert the canonical live (root-key) serving path
        self.page["status"] = "published"
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()

    def _publish(self, keys_repo=None):
        publish_page_document(
            self.page, offers_repository=self.offers_repo, products_repository=self.products_repo,
            stripe_keys_repository=keys_repo, s3_client=self.s3, pages_bucket="pages", preview_bucket="preview",
            environment="prod", pages_domain="pages.example.com", preview_domain="preview.example.com")
        return [p for p in self.s3.puts if "preview/" not in p["Key"]][0]["Body"].decode()

    def test_messaging_injected_when_enabled(self):
        keys = {"tenant_id": self.offer["tenant_id"], "mode": "test", "publishable_key": "pk_test_x",
                "payment_methods": {"account_country": "US",
                                    "bnpl": {"klarna": {"enabled": True, "capability_status": "active"}}}}
        published = self._publish(_FakeKeysRepo(keys))
        self.assertIn("js.stripe.com", published)
        self.assertIn('Stripe("pk_test_x")', published)
        self.assertIn('paymentMethodTypes: ["klarna"]', published)
        self.assertIn('id="sl-bnpl-message"', published)

    def test_no_messaging_when_disabled(self):
        keys = {"tenant_id": self.offer["tenant_id"], "mode": "test", "publishable_key": "pk_test_x",
                "payment_methods": {"bnpl": {"klarna": {"enabled": False, "capability_status": "active"}}}}
        self.assertNotIn("js.stripe.com", self._publish(_FakeKeysRepo(keys)))

    def test_no_messaging_without_keys_repo(self):
        self.assertNotIn("js.stripe.com", self._publish(None))
