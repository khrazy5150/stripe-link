"""Catalog markup and meta descriptions for offer-less pages (plans/OFFERLESS_PAGES_IN_BUILDER.md P4).

Two defects, both found by rendering the pages rather than reading the code:

* A storefront and a category page emitted NO structured data at all. `product_json_ld` returns "" without
  prices and the grid renderer emitted none of its own, so the two page types that carry the catalogue were
  invisible to structured-data consumers while the store-profile page -- which carries no products -- was
  emitting three node types.
* All three published the meta description `Get yours today!`. With no `seo.description` and no product,
  `document_description` fell through to the rotating CTA pool: one identical sentence across every
  offer-less page on a Site, and a sales CTA on an "about" page.
"""

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LONG_DESCRIPTION = (
    "Probe Store has sold supplements out of Springfield, Oregon since 2014. We keep the range short "
    "and test every batch, and we pack every order ourselves."
)
PRODUCT_NAMES = ["Creatine Gummies", "Electrolyte Sticks", "Whey Isolate Vanilla", "Magnesium Glycinate"]


def _fixture(name):
    return json.loads((ROOT / "schemas" / "examples" / name).read_text())


def _catalogue(count):
    """`count` real product pages on one Site, so a grid resolves to that many linked cards."""
    base_product, base_offer = _fixture("product-creatine-gummies.json"), _fixture("offer-creatine-standard.json")
    products, offers, entries = {}, {}, {}
    for index, name in enumerate(PRODUCT_NAMES[:count]):
        product_id, offer_id = f"prod_{index}", f"off_{index}"
        product = copy.deepcopy(base_product)
        product["product_id"], product["name"] = product_id, name
        for price in product["prices"]:
            price["price_id"] = f"{price['price_id']}_{index}"
        product["default_price_id"] = product["prices"][0]["price_id"]
        offer = copy.deepcopy(base_offer)
        offer["offer_id"], offer["name"] = offer_id, name
        offer["items"] = [{"product_id": product_id,
                           "price_id": product["prices"][0]["price_id"], "quantity": 1}]
        offer.setdefault("presentation", {})["headline"] = name
        products[product_id], offers[offer_id] = product, offer
        entries[f"/{product_id}"] = {"page_id": f"pg_{index}", "offer_id": offer_id,
                                     "page_type": "landing", "enabled": True}
    return products, offers, entries


def _render(sections, *, slug, page_type, title, org_description="", product_count=4, goal="search_seo"):
    from stripe_link.runtime.html import render_page
    from stripe_link.runtime.publishing import resolve_category_grids

    products, offers, entries = _catalogue(product_count)
    tenant = next(iter(products.values()))["tenant_id"] if products else "tenant_demo"
    organization = {
        "name": "Probe Store", "telephone": "+1-555-0100",
        "address": {"street": "1 Main St", "locality": "Springfield", "region": "OR",
                    "postal_code": "97477", "country": "US"},
    }
    if org_description:
        organization["description"] = org_description
    site = {
        "document_type": "site", "tenant_id": tenant, "site_id": "s1", "name": "Probe Store",
        "hostname": "probestore.com",
        "hosting": {"custom_domain": "probestore.com", "verification": {"verified": True}},
        "indexing": {"eligibility": "eligible"}, "status": "active",
        "organization": organization,
        "pages": {"/": {"page_id": "pg_sf", "page_type": "homepage", "enabled": True},
                  "/about": {"page_id": "pg_pf", "page_type": "about", "enabled": True},
                  "/widgets": {"page_id": "pg_cat", "page_type": "category", "enabled": True},
                  **entries},
    }
    collections = {"c1": {"document_type": "collection", "tenant_id": tenant, "collection_id": "c1",
                          "site_id": "s1", "name": "All", "rule": "all"}}
    page = {
        "schema_version": "2026-05-29", "document_type": "page", "tenant_id": tenant,
        "page_id": "pg_x", "name": "Page", "status": "published", "published_at": None, "revision": 1,
        "route": {"slug": slug or "home"}, "theme": {"preset": "clean-slate"},
        "seo": {"title": title}, "sections": sections,
    }
    if goal:
        page["goal"] = goal
    work = copy.deepcopy(page)
    resolve_category_grids(work, site, collections_by_id=collections)
    return render_page(work, {}, products, offers_by_id=offers,
                       canonical_url=f"https://probestore.com/{slug}", indexable=True, site=site,
                       page_type=page_type, home_url="https://probestore.com/",
                       api_base_url="https://api.example.com")


STOREFRONT = [
    {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store",
     "tagline": "Good things, fairly priced"},
    {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1"},
]
CATEGORY = [
    {"id": "brand-hero", "type": "brand_hero", "headline": "Widgets"},
    {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1", "heading": "Widgets"},
]
PROFILE = [
    {"id": "brand-hero", "type": "brand_hero", "headline": "About our store"},
    {"id": "seller-profile", "type": "seller_profile", "heading": "About our store"},
]


def _json_ld(html):
    return [json.loads(m) for m in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def _meta_description(html):
    found = re.findall(r'name="description" content="(.*?)"', html)
    return found[0] if found else ""


class CatalogMarkupTests(unittest.TestCase):
    def test_a_storefront_emits_a_collection_page_with_an_item_list(self):
        blocks = _json_ld(_render(STOREFRONT, slug="", page_type="homepage", title="Probe Store"))
        collection = next((b for b in blocks if b.get("@type") == "CollectionPage"), None)
        self.assertIsNotNone(collection, "a storefront still emits no CollectionPage")
        self.assertEqual(collection["url"], "https://probestore.com/")
        self.assertEqual(collection["name"], "Probe Store")
        item_list = collection["mainEntity"]
        self.assertEqual(item_list["@type"], "ItemList")
        self.assertEqual(item_list["numberOfItems"], 4)
        self.assertEqual([i["position"] for i in item_list["itemListElement"]], [1, 2, 3, 4])
        self.assertEqual([i["name"] for i in item_list["itemListElement"]], PRODUCT_NAMES)
        for item in item_list["itemListElement"]:
            self.assertTrue(item["url"].startswith("https://probestore.com/"))

    def test_a_category_page_emits_one_too(self):
        blocks = _json_ld(_render(CATEGORY, slug="widgets", page_type="category", title="Widgets"))
        collection = next((b for b in blocks if b.get("@type") == "CollectionPage"), None)
        self.assertIsNotNone(collection)
        self.assertEqual(collection["mainEntity"]["numberOfItems"], 4)

    def test_the_item_list_does_not_restate_prices(self):
        """The listing page's job is to link; the full Product/Offer markup lives on each product's own
        page. Restating a price here would put one claim in two places that can disagree."""
        html = _render(STOREFRONT, slug="", page_type="homepage", title="Probe Store")
        item_list = next(b for b in _json_ld(html) if b.get("@type") == "CollectionPage")["mainEntity"]
        for item in item_list["itemListElement"]:
            self.assertEqual(set(item) - {"@type", "position", "url", "name"}, set())

    def test_an_about_page_that_also_has_a_grid_has_only_one_collection_page(self):
        """render_seller_profile emits its own CollectionPage (mainEntity: the Organization). Two
        CollectionPage nodes for one URL, disagreeing about what the page is, would be worse than none."""
        html = _render(PROFILE + [{"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1"}],
                       slug="about", page_type="about", title="About our store")
        blocks = _json_ld(html)
        self.assertEqual(len([b for b in blocks if b.get("@type") == "CollectionPage"]), 1)
        # The grid is still described -- as a bare ItemList rather than a second page-level claim.
        self.assertEqual(len([b for b in blocks if b.get("@type") == "ItemList"]), 1)

    def test_an_about_page_with_no_grid_emits_no_item_list(self):
        html = _render(PROFILE, slug="about", page_type="about", title="About our store")
        self.assertEqual([b for b in _json_ld(html) if b.get("@type") == "ItemList"], [])

    def test_unlinkable_cards_are_left_out(self):
        """Off a serving host the grid renders plain tiles with no hrefs, and an ItemList entry with
        nothing to point at describes a link that does not exist."""
        from stripe_link.runtime.html import render_page
        from stripe_link.runtime.publishing import resolve_category_grids

        products, offers, entries = _catalogue(4)
        tenant = next(iter(products.values()))["tenant_id"]
        site = {"document_type": "site", "tenant_id": tenant, "site_id": "s1", "name": "Probe Store",
                "hostname": "probestore.com", "organization": {"name": "Probe Store"},
                "pages": {"/": {"page_id": "pg_sf", "page_type": "homepage", "enabled": True}, **entries}}
        collections = {"c1": {"document_type": "collection", "tenant_id": tenant, "collection_id": "c1",
                              "site_id": "s1", "name": "All", "rule": "all"}}
        page = {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": tenant,
                "page_id": "pg_sf", "name": "SF", "status": "published", "published_at": None,
                "revision": 1, "route": {"slug": "home"}, "theme": {"preset": "clean-slate"},
                "seo": {"title": "Probe Store"}, "goal": "search_seo", "sections": STOREFRONT}
        work = copy.deepcopy(page)
        resolve_category_grids(work, site, collections_by_id=collections)
        # No home_url: the page is not served on a host whose links resolve.
        html = render_page(work, {}, products, offers_by_id=offers,
                           canonical_url="https://artifact.example.com/pg_sf/", indexable=True,
                           site=site, page_type="homepage", api_base_url="https://api.example.com")
        self.assertEqual([b for b in _json_ld(html) if b.get("@type") in ("ItemList", "CollectionPage")], [])


class MetaDescriptionTests(unittest.TestCase):
    CTAS = ("Get yours today!", "Order now.", "Ships fast — order today.", "In stock now.")

    def _all_three(self, org_description=""):
        return {
            "storefront": _meta_description(_render(
                STOREFRONT, slug="", page_type="homepage", title="Probe Store",
                org_description=org_description)),
            "category": _meta_description(_render(
                CATEGORY, slug="widgets", page_type="category", title="Widgets",
                org_description=org_description)),
            "profile": _meta_description(_render(
                PROFILE, slug="about", page_type="about", title="About our store",
                org_description=org_description)),
        }

    def test_no_offerless_page_publishes_a_bare_sales_cta(self):
        for org_description in ("", LONG_DESCRIPTION):
            for shape, description in self._all_three(org_description).items():
                with self.subTest(shape=shape, org=bool(org_description)):
                    self.assertTrue(description)
                    for cta in self.CTAS:
                        self.assertNotEqual(description, cta)
                    self.assertNotIn("Get yours today", description)

    def test_the_three_pages_of_one_site_do_not_share_a_description(self):
        """The duplicate footprint, which survived the first fix: taking the business description first for
        every shape gave the storefront and the about page the same sentence word for word."""
        for org_description in ("", LONG_DESCRIPTION):
            with self.subTest(org=bool(org_description)):
                descriptions = self._all_three(org_description)
                self.assertEqual(len(set(descriptions.values())), 3, descriptions)

    def test_an_about_page_leads_with_the_business_description(self):
        """Its subject IS the business, so the tenant's own words lead and nothing is bolted in front."""
        description = self._all_three(LONG_DESCRIPTION)["profile"]
        self.assertTrue(LONG_DESCRIPTION.startswith(description[:80]))

    def test_a_catalog_page_leads_with_what_the_page_is(self):
        descriptions = self._all_three(LONG_DESCRIPTION)
        self.assertTrue(descriptions["storefront"].startswith("Probe Store — Good things"))
        self.assertIn("Browse 4 products", descriptions["storefront"])
        # A bare category heading is a word a dozen other shops use too, so the store is named with it.
        self.assertTrue(descriptions["category"].startswith("Widgets from Probe Store"))

    def test_the_product_count_is_what_the_page_actually_shows(self):
        one = _meta_description(_render(STOREFRONT, slug="", page_type="homepage",
                                        title="Probe Store", product_count=1))
        self.assertIn("Browse 1 product.", one)
        self.assertNotIn("1 products", one)

    def test_an_offer_page_is_untouched(self):
        """The offer-shaped derivation, including its CTA, is right for a page that sells something."""
        from stripe_link.runtime.html import document_description

        page, offer = _fixture("page-creatine-standard.json"), _fixture("offer-creatine-standard.json")
        product = _fixture("product-creatine-gummies.json")
        page.pop("seo", None)
        page["seo"] = {}
        description = document_description(page, offer, {product["product_id"]: product})
        self.assertTrue(description)
        self.assertNotIn("Browse", description)


class GoalGatingTests(unittest.TestCase):
    def test_the_catalog_markup_follows_the_structured_data_section(self):
        """Same rule as an offer page's Product markup: the goal axis is the discoverability switch, so the
        markup arrives with `search_seo` and not before. P3 asks every new page for a goal, so the gate is
        reachable; a page created before that needs one set in the builder's Page Settings."""
        with_goal = _json_ld(_render(STOREFRONT, slug="", page_type="homepage",
                                     title="Probe Store", goal="search_seo"))
        without = _json_ld(_render(STOREFRONT, slug="", page_type="homepage",
                                   title="Probe Store", goal=""))
        self.assertTrue([b for b in with_goal if b.get("@type") == "CollectionPage"])
        self.assertEqual(without, [])


class WarningsStayActionableTests(unittest.TestCase):
    """plans/... P4, and the standing rule: a notice needs an action the tenant must take.

    `structured_data_warnings` opened with "No price is shown on this page, so no Product markup can be
    emitted." On a storefront that describes correct behaviour and names nothing to do about it. It was
    unreachable until these pages started opening in the builder, so the exposure arrived with P2's fix.
    """

    STOREFRONT_PAGE = {"sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store"},
        {"id": "catalog-grid", "type": "catalog_grid", "items": [{"offer_id": "o1", "slug": "/a"}]},
    ]}
    EMPTY_GRID_PAGE = {"sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store"},
        {"id": "catalog-grid", "type": "catalog_grid", "items": []},
    ]}
    PROFILE_PAGE = {"sections": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "About"},
        {"id": "seller-profile", "type": "seller_profile"},
    ]}

    def test_a_working_storefront_is_not_warned_at_all(self):
        from stripe_link.runtime.html import structured_data_warnings

        self.assertEqual(structured_data_warnings({}, {}, None, self.STOREFRONT_PAGE), [])

    def test_no_offerless_page_is_told_about_missing_product_markup(self):
        from stripe_link.runtime.html import structured_data_warnings

        for name, page in (("storefront", self.STOREFRONT_PAGE),
                           ("empty grid", self.EMPTY_GRID_PAGE),
                           ("profile", self.PROFILE_PAGE)):
            with self.subTest(page=name):
                for warning in structured_data_warnings({}, {}, None, page):
                    self.assertNotIn("Product markup", warning)
                    self.assertNotIn("No price is shown", warning)

    def test_an_empty_grid_is_warned_because_that_one_is_fixable(self):
        from stripe_link.runtime.html import structured_data_warnings

        warnings = structured_data_warnings({}, {}, None, self.EMPTY_GRID_PAGE)
        self.assertEqual(len(warnings), 1)
        self.assertIn("grid is empty", warnings[0])

    def test_the_thin_content_remedy_fits_the_page(self):
        """Same lesson one notice over: three of the four remedies the thin-content nudge offers -- a
        product description, a specifications table, condition details -- do not exist on an offer-less
        page. P2 made that notice reachable, so P4 has to make it callable. Found by invoking the DEPLOYED
        dev renderer, not by reading the code."""
        from stripe_link.runtime.html import thin_content_warnings

        html = "<html><body><p>Four short words here</p></body></html>"
        offerless = thin_content_warnings(html, {}, self.STOREFRONT_PAGE)[0]
        self.assertIn("intro paragraph", offerless)
        for dead_end in ("product description", "specifications table", "condition details"):
            self.assertNotIn(dead_end, offerless)
        # An offer page keeps the remedies that suit it, and so does a caller passing no page at all.
        for warning in (thin_content_warnings(html, None, _fixture("page-creatine-standard.json"))[0],
                        thin_content_warnings(html)[0]):
            self.assertIn("product description", warning)

    def test_an_offer_page_keeps_every_product_check(self):
        """The offer-shaped warnings are right for a page that sells something, and the new branch must be
        reachable only via the page argument."""
        from stripe_link.runtime.html import structured_data_warnings

        offer_page = _fixture("page-creatine-standard.json")
        warnings = structured_data_warnings({}, {}, None, offer_page)
        self.assertTrue(any("Product markup" in w for w in warnings),
                        "an offer page lost its Product-markup check")
        # And with no page at all, the old behaviour is unchanged for every existing caller.
        self.assertTrue(any("Product markup" in w for w in structured_data_warnings({}, {})))


if __name__ == "__main__":
    unittest.main()
