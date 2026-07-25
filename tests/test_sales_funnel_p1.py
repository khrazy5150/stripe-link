"""Sales funnel P1b — /sale //flash-sale context views (pair by quantity + context) + checkout acceptance.

plans/SALES_FUNNELS.md. The render swaps each displayed tier to its paired sale/flash price (same quantity),
badges it, strikes through the Standard price, and falls back to Standard per-tier and whole-page. Checkout
accepts sale/flash contexts for a standard offer so the /sale CTA charges the sale price.
"""
import copy
import json
import re
import unittest
from pathlib import Path

from stripe_link.domain.pricing import PricingError, resolve_offer_item
from stripe_link.runtime.html import render_page

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.load((ROOT / "schemas" / "examples" / name).open())


def _product_with_sales(sale_qtys=(1, 6), context="sale"):
    product = load("product-creatine-gummies.json")
    by_qty = {int(p.get("quantity") or 1): p for p in product["prices"] if str(p.get("context") or "standard") == "standard"}
    for q in sale_qtys:
        std = by_qty[q]
        product["prices"].append({**std, "price_id": f"price_{context}_{q}", "unit_amount": int(std["unit_amount"] * 0.7), "context": context})
    return product


def _cards(html):
    return re.findall(r'data-price-id="([^"]+)"[^>]*?data-sale-amount="(\d+)"', html)


class SaleContextRenderTests(unittest.TestCase):
    def setUp(self):
        self.offer = load("offer-creatine-standard.json")
        self.page = load("page-creatine-standard.json")

    def _render(self, product, price_context="standard"):
        return render_page(self.page, self.offer, {product["product_id"]: product}, canonical_url="https://x/p", price_context=price_context)

    def test_standard_render_unchanged_by_the_feature(self):
        product = _product_with_sales()
        html = self._render(product, "standard")
        ids = [pid for pid, _ in _cards(html)]
        self.assertTrue(all(pid.startswith("price_") and "sale" not in pid for pid in ids))
        self.assertNotIn(">Sale<", html)

    def test_sale_view_swaps_paired_tiers_and_falls_back(self):
        product = _product_with_sales(sale_qtys=(1, 6))  # qty 2 and 3 have no sale price
        cards = dict(_cards(self._render(product, "sale")))
        # Swapped tiers use the sale price_id; unpaired tiers keep the standard price_id.
        self.assertIn("price_sale_1", cards)
        self.assertIn("price_sale_6", cards)
        self.assertIn("price_2bottle", cards)   # fallback to Standard
        self.assertIn("price_3bottle", cards)
        self.assertIn(">Sale<", self._render(product, "sale"))

    def test_flash_view_uses_flash_price_and_fire_badge(self):
        product = _product_with_sales(sale_qtys=(1, 2, 3, 6), context="flash_sale")
        html = self._render(product, "flash_sale")
        self.assertIn("price_flash_sale_1", dict(_cards(html)))
        self.assertIn("Flash Sale", html)  # the fire-badge label

    def test_whole_page_fallback_when_no_sale_price(self):
        # A product with no sale price at all -> /sale renders identically to Standard.
        product = load("product-creatine-gummies.json")
        self.assertEqual(_cards(self._render(product, "sale")), _cards(self._render(product, "standard")))
        self.assertNotIn(">Sale<", self._render(product, "sale"))

    def test_flash_view_emits_banner_state_script_and_revert_data(self):
        product = _product_with_sales(sale_qtys=(1, 2, 3, 6), context="flash_sale")
        self.page["flash_sale"] = {"enabled": True, "starts_on": 1000, "ends_at": 999999999999}
        html = self._render(product, "flash_sale")
        self.assertIn('<div class="sl-flash-banner"', html)             # the banner element
        self.assertIn('data-price-context="flash_sale"', html)          # state config
        self.assertIn('data-starts-on="1000"', html)
        self.assertIn('data-ends-at="999999999999"', html)
        self.assertIn("const tick", html)                               # client state script
        self.assertIn("data-standard-price-id=", html)                  # per-card revert fallback
        self.assertIn("data-standard-amount=", html)

    def test_standard_view_has_no_banner_or_state_script(self):
        product = _product_with_sales(context="flash_sale")
        html = self._render(product, "standard")
        self.assertNotIn('<div class="sl-flash-banner"', html)
        self.assertNotIn("data-price-context=", html)
        self.assertNotIn("data-standard-price-id=", html)


class ListicleSaleContextRenderTests(unittest.TestCase):
    """A listicle offer's cards + conversion payload must swap to the sale/flash price and show the badge on
    the /sale //flash-sale views, at parity with the single/bundle selector (plans/SALES_FUNNELS.md P1)."""

    def setUp(self):
        self.offer = load("offer-creatine-standard.json")
        self.offer["offer_type"] = "listicle"
        self.page = load("page-creatine-standard.json")

    def _render(self, product, price_context="standard"):
        return render_page(
            self.page, self.offer, {product["product_id"]: product},
            api_base_url="https://api.x", canonical_url="https://x/p", price_context=price_context,
        )

    def test_listicle_renders_carousel(self):
        html = self._render(_product_with_sales(sale_qtys=(1,)), "standard")
        self.assertIn("data-listicle", html)  # confirm we're exercising the listicle path

    def test_listicle_sale_view_swaps_price_and_shows_badge(self):
        html = self._render(_product_with_sales(sale_qtys=(1,), context="sale"), "sale")
        self.assertIn("price_sale_1", html)   # conversion payload binds the sale price
        self.assertIn(">Sale<", html)         # card badge

    def test_listicle_flash_view_uses_flash_price_and_fire_badge(self):
        html = self._render(_product_with_sales(sale_qtys=(1,), context="flash_sale"), "flash_sale")
        self.assertIn("price_flash_sale_1", html)
        self.assertIn("\U0001F525 Flash Sale", html)

    def test_listicle_standard_view_has_no_context_swap(self):
        html = self._render(_product_with_sales(sale_qtys=(1,), context="sale"), "standard")
        self.assertNotIn("price_sale_1", html)
        self.assertNotIn(">Sale<", html)


class CheckoutContextAcceptanceTests(unittest.TestCase):
    def _item_and_product(self, price_context):
        product = {
            "product_id": "p1", "name": "W", "status": "active",
            "prices": [{"price_id": "pr", "unit_amount": 3000, "currency": "usd", "quantity": 1, "context": price_context}],
        }
        item = {"product_id": "p1", "price_id": "pr", "quantity": 1}
        return item, product

    def test_standard_offer_accepts_sale_and_flash(self):
        for ctx in ("standard", "sale", "flash_sale"):
            item, product = self._item_and_product(ctx)
            resolved = resolve_offer_item(item, product, "standard")
            self.assertEqual(resolved.context, ctx)

    def test_standard_offer_still_rejects_funnel_contexts(self):
        for ctx in ("upsell", "downsell", "order_bump"):
            item, product = self._item_and_product(ctx)
            with self.assertRaises(PricingError):
                resolve_offer_item(item, product, "standard")


class ContextArtifactAndRouteTests(unittest.TestCase):
    def test_artifact_paths_context_subpath(self):
        from stripe_link.runtime.artifacts import artifact_paths
        self.assertEqual(artifact_paths("t1", "page_1")["published"], "page_1/index.html")
        self.assertEqual(artifact_paths("t1", "page_1", context="sale")["published"], "page_1/sale/index.html")
        self.assertEqual(artifact_paths("t1", "page_1", context="flash_sale")["published"], "page_1/flash-sale/index.html")

    def _site(self, root_page="page_home"):
        return {"pages": {"/": {"page_id": root_page, "page_type": "landing", "enabled": True}}}

    def test_attach_context_view_slugs_adds_and_removes(self):
        from stripe_link.runtime.publishing import attach_context_view_slugs
        page = {"page_id": "page_home", "sale": {"enabled": True}, "flash_sale": {"enabled": True, "ends_at": 9}}
        site, changed = attach_context_view_slugs(self._site(), page)
        self.assertTrue(changed)
        self.assertEqual(site["pages"]["/sale"], {"page_id": "page_home", "page_type": "landing", "price_context": "sale", "enabled": True})
        self.assertEqual(site["pages"]["/flash-sale"]["price_context"], "flash_sale")
        # Toggling sale off retires just its route.
        page2 = {"page_id": "page_home", "sale": {"enabled": False}, "flash_sale": {"enabled": True, "ends_at": 9}}
        site2, changed2 = attach_context_view_slugs(site, page2)
        self.assertTrue(changed2)
        self.assertNotIn("/sale", site2["pages"])
        self.assertIn("/flash-sale", site2["pages"])

    def test_attach_skips_non_root_page(self):
        from stripe_link.runtime.publishing import attach_context_view_slugs
        # The page sits at /deals, not "/" -> no reserved context slugs attached.
        site = {"pages": {"/deals": {"page_id": "page_x", "page_type": "landing", "enabled": True}}}
        _, changed = attach_context_view_slugs(site, {"page_id": "page_x", "sale": {"enabled": True}})
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
