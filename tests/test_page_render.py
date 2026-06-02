import json
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
