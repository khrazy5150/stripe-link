import json
import copy
import unittest
from pathlib import Path

from handlers.page_render import handler
from stripe_link.runtime.html import RenderError, format_money, render_page


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class PageRenderTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}

    def test_render_page_outputs_semantic_sections_and_price_options(self):
        html = render_page(self.page, self.offer, self.products_by_id)

        self.assertIn("<h1>Creatine Gummies</h1>", html)
        self.assertIn("--sl-theme-accent:#16a34a", html)
        self.assertIn("data-section-type=\"offer_price_selector\"", html)
        self.assertIn("data-price-id=\"price_1bottle\"", html)
        self.assertIn("data-price-id=\"price_6bottle\"", html)
        self.assertIn("Continue To Checkout - $67.00", html)
        self.assertIn("sl-google-tag-id", html)
        self.assertIn("https://example.com/terms", html)

    def test_render_page_uses_selected_price_for_cta_total(self):
        html = render_page(self.page, self.offer, self.products_by_id, {
            "prod_creatine_gummies": "price_6bottle",
        })

        self.assertIn("Continue To Checkout - $149.00", html)

    def test_render_universal_bundle_template_sections(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-background:#0b1220", html)
        self.assertIn("--sl-card:#0f172a", html)
        self.assertIn("--sl-brand:#22c55e", html)
        self.assertIn("--sl-cta-from:#22c55e", html)
        self.assertIn("data-section-type=\"countdown_timer\"", html)
        self.assertIn("data-duration-minutes=\"1\"", html)
        self.assertIn("data-persistent=\"true\"", html)
        self.assertIn("data-sticky=\"true\"", html)
        self.assertIn("data-start-color=\"#dc2626\"", html)
        self.assertIn("data-end-color=\"#f97316\"", html)
        self.assertIn("data-countdown-display", html)
        self.assertIn("main{width:min(52rem,100%)", html)
        self.assertIn("data-section-type=\"brand_label\"", html)
        self.assertIn("<span>Creatine Gummies</span>", html)
        self.assertIn("data-section-type=\"hero_media\"", html)
        self.assertIn("data-media-count=\"1\"", html)
        self.assertIn("images/universal-bundle/creatine_gummies_1.webp", html)
        self.assertIn("Get Creatine Gummies Bundle Today", html)
        self.assertIn("data-section-type=\"trust_badges\"", html)
        self.assertIn("data-price-id=\"price_universal_triple\"", html)
        self.assertIn("data-sale-amount=\"6942\"", html)
        self.assertIn("data-regular-amount=\"9400\"", html)
        self.assertIn("Single Pack", html)
        self.assertIn("Double Pack", html)
        self.assertIn("Triple Pack", html)
        self.assertIn("$69.42", html)
        self.assertIn("$94.00", html)
        self.assertIn("Save 31%", html)
        self.assertIn("<details class=\"sl-refund-policy\"", html)
        self.assertIn("data-section-type=\"refund_policy\"", html)
        self.assertIn("<summary>30-day money-back</summary>", html)
        self.assertIn("Applies to: Creatine Gummies - Single Pack", html)
        self.assertIn("Physical items may be returned within 30 days", html)
        self.assertIn("data-section-type=\"content_block\"", html)
        self.assertIn("data-section-type=\"faq\"", html)
        self.assertIn("Get The Bundle - $69.42", html)
        self.assertIn("Terms of Service", html)
        self.assertIn("© 2026 All rights reserved.", html)
        self.assertIn("localStorage.setItem(storageKey, 'expired')", html)
        self.assertIn("expireDiscounts()", html)
        self.assertIn("selectCard(cards.find", html)

    def test_universal_bundle_theme_tokens_override_preset(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["tokens"] = {
            "background": "#ffffff",
            "card": "#f8fafc",
            "brand": "#0ea5e9",
            "cta_from": "#0ea5e9",
            "cta_to": "#0284c7",
            "cta_text": "#ffffff",
        }

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-background:#ffffff", html)
        self.assertIn("--sl-card:#f8fafc", html)
        self.assertIn("--sl-brand:#0ea5e9", html)
        self.assertIn("--sl-cta-to:#0284c7", html)

    def test_bundle_hero_media_uses_page_images_as_carousel_override(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        hero_media = next(section for section in page["sections"] if section["type"] == "hero_media")
        hero_media["images"] = [
            "images/universal-bundle/creatine_gummies_1.webp",
            "images/universal-bundle/creatine_gummies_2.webp",
        ]

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("data-media-count=\"2\"", html)
        self.assertIn("images/universal-bundle/creatine_gummies_2.webp", html)

    def test_render_page_uses_checkout_url_when_provided(self):
        html = render_page(
            self.page,
            self.offer,
            self.products_by_id,
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )

        self.assertIn("href=\"https://checkout.stripe.com/c/pay/demo\"", html)

    def test_render_page_rejects_missing_offer_product(self):
        with self.assertRaisesRegex(RenderError, "was not provided"):
            render_page(self.page, self.offer, {})

    def test_format_money_uses_currency_and_minor_units(self):
        self.assertEqual(format_money(1899, "usd"), "$18.99")
        self.assertEqual(format_money(1899, "eur"), "€18.99")
        self.assertEqual(format_money(1899, "cad"), "CAD 18.99")

    def test_render_handler_returns_html(self):
        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": self.offer,
                "products": [self.product],
            })
        }, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertIn("<!doctype html>", body["html"])

    def test_render_handler_rejects_mismatched_page_offer(self):
        offer = dict(self.offer)
        offer["offer_id"] = "offer_other"

        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": offer,
                "products": [self.product],
            })
        }, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "render_error")

    def test_render_handler_validates_products(self):
        product = dict(self.product)
        product["tenant_id"] = "tenant_other"

        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": self.offer,
                "products": [product],
            })
        }, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "render_error")

    def test_render_handler_accepts_checkout_url(self):
        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": self.offer,
                "products": [self.product],
                "checkout_url": "https://checkout.stripe.com/c/pay/demo",
            })
        }, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn(
            "href=\"https://checkout.stripe.com/c/pay/demo\"",
            json.loads(response["body"])["html"],
        )


if __name__ == "__main__":
    unittest.main()
