import html as htmllib
import json
import re
import unittest

from stripe_link.runtime.html import render_page
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


if __name__ == "__main__":
    unittest.main()
