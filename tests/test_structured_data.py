import html as htmllib
import json
import re
import unittest

from stripe_link.runtime.html import accessibility_warnings, heading_outline_warnings, render_page, structured_data_warnings
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
