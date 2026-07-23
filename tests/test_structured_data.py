import html as htmllib
import json
import re
import unittest

from stripe_link.runtime.html import (
    accessibility_warnings,
    heading_outline_warnings,
    indexable_word_count,
    render_page,
    structured_data_warnings,
    thin_content_warnings,
)
from tests.test_page_render import load_fixture


def visible_text(html):
    """The page body as a crawler sees it: entity-decoded. The renderer escapes tenant copy, so a raw
    string compare would report a false mismatch for anything containing an apostrophe."""
    return htmllib.unescape(html.split("<body>")[1])


def ld_blocks(html):
    """Every JSON-LD payload in the page, decoded."""
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        raw = m.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
        out.append(json.loads(raw))
    return out


class StructuredDataTests(unittest.TestCase):
    """Derived head-channel JSON-LD (plans/LANDING_PAGE_GOAL_COMPOSITION.md Phase 3)."""

    FAQ_SECTION = {
        "id": "faq",
        "type": "faq",
        "heading": "Frequently Asked Questions",
        "items": [{"question": "Is there a money-back guarantee?", "answer": "Yes, within 30 days."}],
    }

    def _page(self, goal=None, faq=False):
        page = load_fixture("page-creatine-standard.json")
        if faq:
            page["sections"].append(json.loads(json.dumps(self.FAQ_SECTION)))
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        if goal:
            page["goal"] = goal
        else:
            page.pop("goal", None)
        return page

    def _render(self, goal=None, faq=False):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        return render_page(self._page(goal, faq), offer, {product["product_id"]: product})

    def test_no_goal_emits_no_structured_data(self):
        # The section is present, but only the goal's discoverability pack turns it on. Existing pages
        # must not silently gain markup.
        self.assertEqual(ld_blocks(self._render()), [])

    def test_paid_ads_emits_no_structured_data(self):
        self.assertEqual(ld_blocks(self._render("paid_ads")), [])

    def test_search_seo_emits_product_json_ld_in_head(self):
        html = self._render("search_seo")
        types = [b["@type"] for b in ld_blocks(html)]
        self.assertIn("Product", types)
        # head channel means head: markup in <body> would be junk the visitor can't see.
        self.assertNotIn("application/ld+json", html.split("<body>")[1])

    def test_marked_up_price_is_a_price_the_page_displays(self):
        # Google requires marked-up prices to match visible content. A product can carry prices this page
        # never shows (upsell context), so JSON-LD derives from the same filter the price cards use.
        html = self._render("search_seo")
        body = visible_text(html)
        product = next(b for b in ld_blocks(html) if b["@type"] == "Product")
        offers = product["offers"]
        marked = ([offers["lowPrice"], offers["highPrice"]]
                  if offers["@type"] == "AggregateOffer" else [offers["price"]])
        for price in marked:
            self.assertIn(f"${price}", body, f"marked-up price {price} is not visible on the page")

    def test_never_emits_a_fabricated_rating(self):
        # The rating element is a number a tenant typed with no verifiable source. Emitting it as review
        # markup would be fabricated structured data (Google policy + FTC deceptive-ratings rule). It stays
        # visible text until a real review source exists (plans/BUSINESS_PROFILE_AND_GBP.md).
        page = self._page("search_seo")
        page["sections"].append({"id": "r", "type": "rating", "value": 4.9, "count": 1200, "label": "on Google"})
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertIn("4.9", html.split("<body>")[1])  # still rendered as visible text
        for block in ld_blocks(html):
            self.assertNotIn("aggregateRating", json.dumps(block))
            self.assertNotIn("AggregateRating", json.dumps(block))
            self.assertNotIn("review", json.dumps(block).lower())

    def test_no_faq_section_means_no_faq_markup(self):
        # FAQPage is derived from the composed faq section — no section, no markup.
        types = [b["@type"] for b in ld_blocks(self._render("search_seo"))]
        self.assertNotIn("FAQPage", types)

    def test_faq_json_ld_only_for_questions_on_the_page(self):
        html = self._render("search_seo", faq=True)
        blocks = ld_blocks(html)
        faq = next((b for b in blocks if b["@type"] == "FAQPage"), None)
        self.assertIsNotNone(faq, "the composed faq section should produce FAQPage markup")
        body = visible_text(html)
        for entry in faq["mainEntity"]:
            # Whole question, not a prefix: render_faq title-cases its questions, so the marked-up text has
            # to go through the same transform or markup and visible content disagree.
            self.assertIn(entry["name"], body, "marked-up question must appear verbatim on the page")
            self.assertIn(entry["acceptedAnswer"]["text"], body, "marked-up answer must appear on the page")

    def test_json_ld_is_script_safe(self):
        # A literal </script> in tenant copy would close the tag early and break the page.
        page = self._page("search_seo", faq=True)
        faq = next(s for s in page["sections"] if s["type"] == "faq")
        faq["items"][0]["answer"] = "Use </script><script>alert(1)</script> carefully"
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        html = render_page(page, offer, {product["product_id"]: product})
        head = html.split("</head>")[0]
        self.assertNotIn("</script><script>alert(1)", head)
        self.assertTrue(ld_blocks(html), "payload must still parse as JSON")


class BreadcrumbTests(unittest.TestCase):
    """Breadcrumbs (SEO-11): visible crawlable trail + matching BreadcrumbList JSON-LD, only on a page served
    at a non-root slug on the Site's verified custom domain."""

    VERIFIED_SITE = {
        "organization": {"name": "Bean Co", "entity_type": "OnlineStore"},
        "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
    }

    def _render(self, *, canonical, page_type="landing", site=None, goal="search_seo"):
        page = load_fixture("page-creatine-standard.json")
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        if goal:
            page["goal"] = goal
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        return render_page(page, offer, {product["product_id"]: product}, canonical_url=canonical,
                           robots="index,follow", site=site if site is not None else self.VERIFIED_SITE,
                           page_type=page_type)

    def _nav(self, html):
        m = re.search(r'<nav class="sl-breadcrumb".*?</nav>', html, re.S)
        return m.group(0) if m else ""

    def test_non_root_page_emits_visible_trail_and_json_ld(self):
        html = self._render(canonical="https://shop.example.com/creatine")
        nav = self._nav(html)
        self.assertIn('<a href="https://shop.example.com/">Home</a>', nav)
        self.assertIn('aria-current="page"', nav)
        crumb = next(b for b in ld_blocks(html) if b["@type"] == "BreadcrumbList")
        items = crumb["itemListElement"]
        self.assertEqual(items[0]["name"], "Home")
        self.assertEqual(items[0]["item"], "https://shop.example.com/")
        self.assertEqual(items[-1]["position"], 2)
        self.assertNotIn("item", items[-1], "the current page carries no item URL by design")

    def test_visible_trail_matches_json_ld_leaf(self):
        html = self._render(canonical="https://shop.example.com/creatine")
        crumb = next(b for b in ld_blocks(html) if b["@type"] == "BreadcrumbList")
        leaf = crumb["itemListElement"][-1]["name"]
        self.assertIn(leaf, visible_text(html))
        self.assertIn(f'aria-current="page">{leaf}<', self._nav(html))

    def test_breadcrumb_deepens_with_a_matching_category_page(self):
        # When the Site has a category page for this product's category, the trail becomes Home → Category →
        # Product (SEO-11/13), the category linking to that category page.
        product = load_fixture("product-creatine-gummies.json")
        site = {
            **self.VERIFIED_SITE,
            "pages": {
                "/creatine": {"page_id": "page_land", "page_type": "landing"},
                "/category/supps": {"page_id": "page_cat", "page_type": "category",
                                    "category": product["product_category"], "label": "Supplements"},
            },
        }
        html = self._render(canonical="https://shop.example.com/creatine", site=site)
        crumb = next(b for b in ld_blocks(html) if b["@type"] == "BreadcrumbList")
        names = [i["name"] for i in crumb["itemListElement"]]
        self.assertEqual(names[0], "Home")
        self.assertEqual(names[1], "Supplements")
        self.assertEqual(len(names), 3)
        self.assertEqual(crumb["itemListElement"][1]["item"], "https://shop.example.com/category/supps")
        self.assertIn('href="https://shop.example.com/category/supps">Supplements</a>', self._nav(html))

    def test_homepage_has_no_breadcrumb(self):
        html = self._render(canonical="https://shop.example.com/")
        self.assertEqual(self._nav(html), "")
        self.assertNotIn("BreadcrumbList", json.dumps(ld_blocks(html)))

    def test_funnel_step_page_has_no_breadcrumb(self):
        html = self._render(canonical="https://shop.example.com/upsell-1", page_type="funnel_step")
        self.assertEqual(self._nav(html), "")

    def test_no_breadcrumb_off_a_verified_custom_domain(self):
        html = self._render(canonical="https://cf.net/page_x/index.html",
                            site={"organization": {"name": "Bean Co"}})
        self.assertEqual(self._nav(html), "")

    def test_breadcrumb_json_ld_omitted_without_seo_goal(self):
        # JSON-LD rides the search_seo discoverability pack (like Product/FAQ); the visible trail still renders.
        html = self._render(canonical="https://shop.example.com/creatine", goal=None)
        self.assertNotIn("BreadcrumbList", json.dumps(ld_blocks(html)))
        self.assertNotEqual(self._nav(html), "")


class SiteNavigationTests(unittest.TestCase):
    """Visible nav rendered from Site.navigation (SEO-13): crawlable primary/footer menus + a store-root
    brand link, only on a verified custom domain."""

    def _site(self):
        return {
            "organization": {"name": "Bean Co", "entity_type": "OnlineStore"},
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "navigation": {"primary": ["/about", "/shop-all", "/missing"], "footer": ["/contact"]},
            "pages": {
                "/": {"page_id": "page_home"},
                "/about": {"page_id": "page_about", "label": "About Us"},
                "/shop-all": {"page_id": "page_shop"},           # no label -> derived
                "/contact": {"page_id": "page_c", "label": "Contact"},
                "/hidden": {"page_id": "page_h", "enabled": False},
            },
        }

    def _render(self, *, page_type="landing", canonical="https://shop.example.com/about", site=None):
        page = load_fixture("page-creatine-standard.json")
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        return render_page(page, offer, {product["product_id"]: product}, canonical_url=canonical,
                           robots="index,follow", site=site if site is not None else self._site(), page_type=page_type)

    def _region(self, html, pattern):
        m = re.search(pattern, html, re.S)
        return m.group(0) if m else ""

    def test_header_has_brand_store_root_link_and_primary_menu(self):
        header = self._region(self._render(), r'<header class="sl-siteheader">.*?</header>')
        self.assertIn('<a class="sl-brand" href="https://shop.example.com/">Bean Co</a>', header)
        self.assertIn('<a href="https://shop.example.com/about">About Us</a>', header)
        self.assertIn('<a href="https://shop.example.com/shop-all">Shop All</a>', header)  # label derived from slug

    def test_menu_skips_slugs_not_in_pages(self):
        header = self._region(self._render(), r'<header class="sl-siteheader">.*?</header>')
        self.assertNotIn("/missing", header)  # navigation lists a slug with no page entry

    def test_footer_nav_renders_footer_menu(self):
        footer = self._region(self._render(), r'<nav class="sl-footernav".*?</nav>')
        self.assertIn('<a href="https://shop.example.com/contact">Contact</a>', footer)

    def test_no_header_on_post_checkout_page(self):
        html = self._render(page_type="funnel_step", canonical="https://shop.example.com/upsell-1")
        self.assertNotIn('<header class="sl-siteheader"', html)

    def test_no_header_off_a_verified_custom_domain(self):
        html = self._render(canonical="https://cf.net/page_x/index.html", site={"organization": {"name": "Bean Co"}})
        self.assertNotIn('<header class="sl-siteheader"', html)


class SellerProfileTests(unittest.TestCase):
    """The tenant/seller profile page (TENANT_PROFILE_REQUIREMENTS §4)."""

    def _render(self, *, verified_social=True):
        site = {
            "organization": {
                "name": "Bean Co", "entity_type": "OnlineStore", "description": "Great coffee.",
                "telephone": "+18015550100", "email": "hi@bean.co",
                "same_as": [{"url": "https://instagram.com/beanco", "verified": verified_social},
                            {"url": "https://facebook.com/impostor", "verified": False}],
            },
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "pages": {"/about": {"page_id": "page_prof", "page_type": "about"},
                      "/category/supps": {"page_id": "page_c", "page_type": "category", "category": "creatine", "label": "Supplements"}},
        }
        page = {"schema_version": "2026-01-01", "document_type": "page", "page_id": "page_prof", "tenant_id": "t1",
                "name": "About", "route": {"slug": "about"},
                "sections": [{"id": "h", "type": "brand_hero", "headline": "Bean Co"},
                             {"id": "p", "type": "seller_profile", "heading": "About us"}]}
        offer = load_fixture("offer-creatine-standard.json"); product = load_fixture("product-creatine-gummies.json")
        return render_page(page, {}, {product["product_id"]: product}, offers_by_id={},
                           canonical_url="https://shop.example.com/about", robots="index,follow", site=site, page_type="about")

    def test_collection_page_wraps_the_resolving_online_store(self):
        cp = next(b for b in ld_blocks(self._render()) if b["@type"] == "CollectionPage")
        entity = cp["mainEntity"]
        self.assertEqual(entity["@type"], "OnlineStore")
        self.assertEqual(entity["@id"], "https://shop.example.com/#organization")  # resolves (TP-03)
        self.assertEqual(entity["email"], "hi@bean.co")
        self.assertEqual(entity["hasOfferCatalog"]["itemListElement"][0]["name"], "Supplements")

    def test_only_verified_social_links_render_with_nofollow(self):
        html = self._render(verified_social=True)
        self.assertIn('href="https://instagram.com/beanco" rel="nofollow ugc noopener"', html)
        self.assertNotIn("facebook.com/impostor", html)  # unverified never emitted (TP §4.4)

    def test_unverified_social_yields_no_sameas(self):
        html = self._render(verified_social=False)
        self.assertNotIn("instagram.com/beanco", html)
        cp = next(b for b in ld_blocks(html) if b["@type"] == "CollectionPage")
        self.assertNotIn("sameAs", cp["mainEntity"])


class ThinContentGateTests(unittest.TestCase):
    """SEO-08: unique-content floor for indexing."""

    def _doc(self, body):
        return f"<html><body><main>{body}</main></body></html>"

    def test_counts_content_words_ignoring_chrome_and_scripts(self):
        words = " ".join(["real content word"] * 40)  # 120 words
        html = self._doc(
            f"<h1>Buy It</h1><p>{words}</p>"
            "<nav class=\"sl-breadcrumb\"><ol><li>lots of breadcrumb words here padding padding</li></ol></nav>"
            "<footer class=\"sl-legal\">many legal boilerplate words that must not be counted at all here</footer>"
            "<script>var a = 'ignored script words that should never count toward content length';</script>"
        )
        count = indexable_word_count(html)
        # The 120 content words plus the short "Buy It" heading — chrome/script excluded, so well under the 150 floor.
        self.assertTrue(120 <= count < 140, count)

    def test_warns_below_floor_and_silent_above(self):
        self.assertTrue(thin_content_warnings(self._doc("<p>only a few words here</p>")))
        self.assertEqual(thin_content_warnings(self._doc("<p>" + " ".join(["word"] * 200) + "</p>")), [])


class SiteOrganizationIdentityTests(unittest.TestCase):
    """The Site's Organization is the single source of the page's entity graph (plans/SITE_OBJECT.md §2.2):
    the Organization + WebSite JSON-LD nodes, the Offer.seller reference, and the brand fallback."""

    ORG = {
        "name": "Axel Mart",
        "entity_type": "OnlineStore",
        "legal_name": "Axel Mart LLC",
        "description": "Your neighborhood shop.",
        "telephone": "+12065654418",
        "email": "hi@axelmart.example",
        "address": {"street": "1493 Osage St", "locality": "Denver", "region": "Colorado",
                    "postal_code": "80204", "country": "US"},
        "same_as": [{"url": "https://instagram.com/axelmart", "verified": True},
                    {"url": "https://facebook.com/impostor", "verified": False}],
    }
    ORIGIN = "https://axel-mart.jbay.uk"

    def _render(self, site=None, canonical_url="https://axel-mart.jbay.uk/p/creatine"):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        page["goal"] = "search_seo"
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        return render_page(page, offer, {product["product_id"]: product},
                           canonical_url=canonical_url, site=site)

    def _node(self, html, type_name):
        return next((b for b in ld_blocks(html)
                     if b.get("@type") == type_name
                     or (isinstance(b.get("@type"), list) and type_name in b["@type"])), None)

    def test_organization_node_from_site(self):
        org = self._node(self._render(site={"organization": self.ORG}), "OnlineStore")
        self.assertIsNotNone(org)
        self.assertEqual(org["@id"], f"{self.ORIGIN}/#organization")
        self.assertEqual(org["name"], "Axel Mart")
        self.assertEqual(org["url"], f"{self.ORIGIN}/")
        self.assertEqual(org["legalName"], "Axel Mart LLC")
        self.assertEqual(org["address"]["@type"], "PostalAddress")
        self.assertEqual(org["address"]["addressLocality"], "Denver")
        self.assertEqual(org["address"]["addressCountry"], "US")
        self.assertEqual(org["sameAs"], ["https://instagram.com/axelmart"])

    def test_local_business_fields_emit_geo_hours_and_map(self):
        org = dict(self.ORG, entity_type="LocalBusiness",
                   geo={"latitude": 39.74, "longitude": -104.99},
                   gbp_url="https://maps.google.com/?cid=123",
                   opening_hours=[{"days": ["Monday", "Tuesday"], "opens": "09:00", "closes": "17:00"}])
        node = self._node(self._render(site={"organization": org}), "LocalBusiness")
        self.assertIsNotNone(node)
        self.assertEqual(node["geo"], {"@type": "GeoCoordinates", "latitude": 39.74, "longitude": -104.99})
        self.assertEqual(node["hasMap"], "https://maps.google.com/?cid=123")
        spec = node["openingHoursSpecification"][0]
        self.assertEqual(spec["@type"], "OpeningHoursSpecification")
        self.assertEqual(spec["dayOfWeek"], ["Monday", "Tuesday"])
        self.assertEqual((spec["opens"], spec["closes"]), ("09:00", "17:00"))

    def test_website_node_publishes_organization(self):
        website = self._node(self._render(site={"organization": self.ORG}), "WebSite")
        self.assertIsNotNone(website)
        self.assertEqual(website["@id"], f"{self.ORIGIN}/#website")
        self.assertEqual(website["publisher"]["@id"], f"{self.ORIGIN}/#organization")

    def test_offer_seller_resolves_to_the_organization(self):
        html = self._render(site={"organization": self.ORG})
        product = next(b for b in ld_blocks(html) if b.get("@type") == "Product")
        seller = product["offers"]["seller"]
        self.assertEqual(seller["@id"], f"{self.ORIGIN}/#organization")
        self.assertEqual(seller["name"], "Axel Mart")

    def test_no_site_emits_no_organization_or_website(self):
        html = self._render(site=None)
        types = [b.get("@type") for b in ld_blocks(html)]
        self.assertNotIn("OnlineStore", types)
        self.assertNotIn("WebSite", types)
        # The offer names no brand and there's no Organization, so there's no seller stub to dangle either.
        product = next(b for b in ld_blocks(html) if b.get("@type") == "Product")
        self.assertNotIn("seller", product["offers"])

    def test_org_name_is_the_og_site_name_fallback(self):
        # The offer names no brand; the business name (not the platform) fills og:site_name.
        head = self._render(site={"organization": self.ORG}).split("<body>")[0]
        self.assertIn('property="og:site_name" content="Axel Mart"', head)

    def test_org_name_fills_the_title_suffix_when_no_explicit_title(self):
        # With no tenant-set title, the formula's brand suffix is the Organization name, not the platform.
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        page.pop("seo", None)
        html = render_page(page, offer, {product["product_id"]: product},
                           canonical_url=f"{self.ORIGIN}/p/creatine", site={"organization": self.ORG})
        self.assertIn("| Axel Mart</title>", html.split("<body>")[0])

    def test_verification_meta_tags_from_site_seo(self):
        site = {"organization": self.ORG, "seo": {"google_site_verification": "gtok123", "bing_site_verification": "btok456"}}
        head = self._render(site=site).split("<body>")[0]
        self.assertIn('<meta name="google-site-verification" content="gtok123">', head)
        self.assertIn('<meta name="msvalidate.01" content="btok456">', head)

    def test_no_verification_meta_without_site_seo(self):
        head = self._render(site={"organization": self.ORG}).split("<body>")[0]
        self.assertNotIn("google-site-verification", head)
        self.assertNotIn("msvalidate.01", head)

    def test_organization_needs_a_canonical_origin_to_anchor(self):
        # No canonical origin → nowhere to anchor the @id, so the node is omitted rather than left dangling.
        self.assertIsNone(self._node(self._render(site={"organization": self.ORG}, canonical_url=""), "OnlineStore"))


class ProductMarkupRichnessTests(unittest.TestCase):
    """Thin markup is valid but ignored: Google showed no rich result for name+description+AggregateOffer.
    A merchant listing needs a specific buyable price and enough identifying detail."""

    def _render(self, **product_overrides):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        product.update(product_overrides)
        page = load_fixture("page-creatine-standard.json")
        page["goal"] = "search_seo"
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        return render_page(page, offer, {product["product_id"]: product})

    def _product_ld(self, html):
        return next(b for b in ld_blocks(html) if b["@type"] == "Product")

    def test_emits_a_single_buyable_offer_not_a_range(self):
        # AggregateOffer describes a price range across sellers/variants; this page sells one selected price.
        offers = self._product_ld(self._render(condition="new"))["offers"]
        self.assertEqual(offers["@type"], "Offer")
        self.assertIn("price", offers)
        self.assertNotIn("lowPrice", offers)

    def test_price_is_a_decimal_string_matching_the_cta(self):
        # SEO-07/22: price is emitted as a decimal string, not a float.
        html = self._render(condition="new")
        price = self._product_ld(html)["offers"]["price"]
        self.assertIsInstance(price, str)
        self.assertRegex(price, r"^\d+\.\d{2}$")
        self.assertIn(f'data-cta-amount="{int(round(float(price) * 100))}"', html)

    def test_name_is_the_product_not_the_offer_headline(self):
        # "Creatine Gummies Single Offer" is the offer's packaging label; a search result must not show it.
        self.assertEqual(self._product_ld(self._render())["name"], "Creatine Gummies")

    def test_category_is_humanized(self):
        ld = self._product_ld(self._render(product_category="dietary_supplement"))
        self.assertEqual(ld["category"], "Dietary Supplement")

    def test_sku_prefers_the_field_and_falls_back_to_product_id(self):
        self.assertEqual(self._product_ld(self._render(sku="CRT-GUM-120"))["sku"], "CRT-GUM-120")
        ld = self._product_ld(self._render())
        self.assertEqual(ld["sku"], "prod_creatine_gummies")

    def test_item_condition_is_stated_never_assumed(self):
        # An unstated condition must not become a machine-readable claim — same rule as the rating.
        self.assertNotIn("itemCondition", self._product_ld(self._render())["offers"])
        self.assertEqual(
            self._product_ld(self._render(condition="refurbished"))["offers"]["itemCondition"],
            "https://schema.org/RefurbishedCondition",
        )

    def test_image_uses_a_rendition_large_enough_for_rich_results(self):
        # Stored URLs point at small (640w); Google wants >=1200px.
        ld = self._product_ld(self._render(images=["https://images.juniorbay.com/products/abc/small.webp"]))
        self.assertEqual(ld["image"], ["https://images.juniorbay.com/products/abc/large.webp"])

    def test_non_rendition_image_passes_through(self):
        ld = self._product_ld(self._render(images=["https://example.com/custom.png"]))
        self.assertEqual(ld["image"], ["https://example.com/custom.png"])


class StructuredDataWarningTests(unittest.TestCase):
    """Advisory page health — never a gate."""

    def _warn(self, **overrides):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        product.update(overrides)
        return structured_data_warnings(offer, {product["product_id"]: product})

    def test_complete_product_has_only_optional_gaps(self):
        warnings = self._warn(condition="new", sku="CRT-1", images=["https://x/y/large.webp"],
                              description="d", product_category="dietary_supplement")
        self.assertEqual(warnings, [])

    def test_flags_what_google_needs(self):
        self.assertTrue(any("image" in w for w in self._warn(images=[])))
        self.assertTrue(any("description" in w for w in self._warn(description="")))
        self.assertTrue(any("condition" in w for w in self._warn(condition=None)))
        self.assertTrue(any("SKU" in w for w in self._warn(sku="")))

    def test_warnings_never_prevent_rendering(self):
        # The page must still publish: thin markup is a nudge, not an error.
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        product["images"] = []
        product["description"] = ""
        page = load_fixture("page-creatine-standard.json")
        page["goal"] = "search_seo"
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertIn("<h1", html)
        self.assertTrue(ld_blocks(html), "markup is still emitted, just thinner")



class HeadingOutlineWarningTests(unittest.TestCase):
    """Publish-time outline validator (plans/SEMANTIC_HTML.md): one H1, ordered, no empty/skipped levels.
    Warnings only — the renderer builds a correct outline by construction; this catches regressions."""

    def _body(self, inner):
        # An H1 in <head> must be ignored — only the visible body is an outline.
        return f"<html><head><h1>head noise</h1></head><body><main>{inner}</main></body></html>"

    def test_valid_outline_has_no_warnings(self):
        self.assertEqual(heading_outline_warnings(self._body("<h1>Thesis</h1><h2>A</h2><h3>a</h3><h2>B</h2>")), [])

    def test_real_pages_pass(self):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertEqual(heading_outline_warnings(html), [])

    def test_missing_h1(self):
        self.assertTrue(any("no main heading" in w for w in heading_outline_warnings(self._body("<h2>A</h2>"))))

    def test_multiple_h1(self):
        self.assertTrue(any("2 main headings" in w for w in heading_outline_warnings(self._body("<h1>A</h1><h1>B</h1>"))))

    def test_empty_heading(self):
        self.assertTrue(any("empty heading" in w for w in heading_outline_warnings(self._body("<h1>A</h1><h2></h2>"))))

    def test_skipped_level(self):
        self.assertTrue(any("skips from H1 to H3" in w for w in heading_outline_warnings(self._body("<h1>A</h1><h3>x</h3>"))))

    def test_going_shallower_is_fine(self):
        # H3 back to H2 closes a subsection — not a skip.
        self.assertEqual(heading_outline_warnings(self._body("<h1>A</h1><h2>B</h2><h3>c</h3><h2>D</h2>")), [])

    def test_head_h1_does_not_count(self):
        # Only body headings matter; a stray H1 in head must not satisfy the H1 requirement.
        self.assertTrue(any("no main heading" in w for w in heading_outline_warnings(self._body("<h2>A</h2>"))))



class AccessibilityWarningTests(unittest.TestCase):
    """Content images need alt text (plans/LANDING_PAGE_GOAL_COMPOSITION.md Phase 4). Warnings only."""

    def _body(self, inner):
        return f"<html><head></head><body><main>{inner}</main></body></html>"

    def test_real_pages_have_alt_on_every_image(self):
        # The renderer fills alt from offer/product data — hero, gallery, avatar included.
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertEqual(accessibility_warnings(html), [])

    def test_missing_alt_attribute_is_flagged(self):
        self.assertTrue(accessibility_warnings(self._body('<img src="x.png">')))

    def test_empty_alt_is_flagged(self):
        self.assertTrue(accessibility_warnings(self._body('<img src="x.png" alt="">')))
        self.assertTrue(accessibility_warnings(self._body('<img src="x.png" alt="   ">')))

    def test_descriptive_alt_passes(self):
        self.assertEqual(accessibility_warnings(self._body('<img src="x.png" alt="Creatine Gummies bottle">')), [])

    def test_decorative_images_opt_out(self):
        # alt="" is correct for decorative images IF they're hidden from the a11y tree.
        self.assertEqual(accessibility_warnings(self._body('<img src="x.png" alt="" aria-hidden="true">')), [])
        self.assertEqual(accessibility_warnings(self._body('<img src="x.png" alt="" role="presentation">')), [])

    def test_counts_multiple(self):
        w = accessibility_warnings(self._body('<img src="a"><img src="b" alt=""><img src="c" alt="ok">'))
        self.assertIn("2 images", w[0])



if __name__ == "__main__":
    unittest.main()
