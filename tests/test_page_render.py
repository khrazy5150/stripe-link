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
        self.assertIn("<link rel=\"icon\" href=\"https://images.juniorbay.com/icon/favicon.png\">", html)
        self.assertIn("<link rel=\"shortcut icon\" href=\"https://images.juniorbay.com/icon/favicon.png\">", html)
        self.assertIn("<link rel=\"apple-touch-icon\" href=\"https://images.juniorbay.com/icon/favicon.png\">", html)
        self.assertIn("--sl-font-body:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif", html)
        self.assertIn("font-family:var(--sl-font-body)", html)
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

    def test_render_page_uses_custom_favicon_url(self):
        page = copy.deepcopy(self.page)
        page["seo"]["favicon_url"] = "https://cdn.example.com/favicon.png"

        html = render_page(page, self.offer, self.products_by_id)

        self.assertIn("<link rel=\"icon\" href=\"https://cdn.example.com/favicon.png\">", html)
        self.assertIn("<link rel=\"shortcut icon\" href=\"https://cdn.example.com/favicon.png\">", html)
        self.assertIn("<link rel=\"apple-touch-icon\" href=\"https://cdn.example.com/favicon.png\">", html)

    def test_render_universal_bundle_template_sections(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["preset"] = "techno-green"
        countdown = next(section for section in page["sections"] if section["type"] == "countdown_timer")
        countdown["persistent"] = True
        countdown.pop("start_color", None)
        countdown.pop("end_color", None)

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-background:#0b1220", html)
        self.assertIn("--sl-card:#0f172a", html)
        self.assertIn("--sl-brand:#22c55e", html)
        self.assertIn("--sl-cta-from:#22c55e", html)
        self.assertIn("--sl-price-card-bg:#0f172a", html)
        self.assertIn("--sl-subheadline-text:#cbd5e1", html)
        self.assertIn("--sl-price-card-selected-border:#22c55e", html)
        self.assertIn("--sl-refund-bg:#0f172a", html)
        self.assertIn("--sl-faq-summary:#f8fafc", html)
        self.assertIn("--sl-legal-link:#cbd5e1", html)
        self.assertIn("data-section-type=\"countdown_timer\"", html)
        self.assertIn("data-duration-minutes=\"1\"", html)
        self.assertIn("data-persistent=\"true\"", html)
        self.assertIn("data-sticky=\"true\"", html)
        self.assertIn("data-start-color=\"#dc2626\"", html)
        self.assertIn("data-end-color=\"#f97316\"", html)
        self.assertIn("data-countdown-display", html)
        self.assertIn("--sl-font-body:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif", html)
        self.assertIn("--sl-font-heading:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif", html)
        self.assertIn("--sl-font-accent:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif", html)
        self.assertIn("font-family:var(--sl-font-body)", html)
        self.assertIn("html{font-size:62.5%;-webkit-text-size-adjust:100%}", html)
        self.assertIn("main{width:100%;padding:0 0 12rem", html)
        self.assertIn("main > :not(.sl-countdown):not(.sl-checkout-cta){width:min(52rem,calc(100% - 3.2rem))", html)
        self.assertIn(".sl-countdown{width:100%", html)
        self.assertIn(".sl-brand-label h1{font-family:var(--sl-font-accent);font-size:1.3rem", html)
        self.assertIn(".sl-headline h2{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem)", html)
        self.assertIn(".sl-price-option strong{font-family:var(--sl-font-heading);font-size:1.6rem", html)
        self.assertIn(".sl-price-description{color:var(--sl-price-description);font-size:1.3rem", html)
        self.assertIn("data-section-type=\"brand_label\"", html)
        self.assertIn("<h1>Creatine Gummies</h1>", html)
        self.assertIn("data-section-type=\"hero_media\"", html)
        self.assertIn("data-media-count=\"1\"", html)
        self.assertIn("images/universal-bundle/creatine_gummies_1.webp", html)
        self.assertIn("<h2>Get Creatine Gummies Bundle Today</h2>", html)
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
        self.assertIn("class=\"sl-refund-policy-body\"", html)
        self.assertIn("class=\"sl-refund-policy-copy\"", html)
        self.assertIn("class=\"sl-refund-policy-return\"", html)
        self.assertIn(".sl-refund-policy-applies{font-size:1.3rem", html)
        self.assertIn(".sl-refund-policy-return{padding-left:2rem", html)
        self.assertIn("Applies to: Creatine Gummies - Single Pack", html)
        self.assertIn("Physical items may be returned within 30 days", html)
        self.assertIn("This item doesn&#x27;t need to be returned.", html)
        self.assertIn("data-section-type=\"content_block\"", html)
        self.assertIn(".sl-content-block h3{font-family:var(--sl-font-heading);font-size:2rem", html)
        self.assertIn(".sl-content-block p{color:var(--sl-content-text);font-size:1.5rem", html)
        self.assertIn("data-section-type=\"faq\"", html)
        self.assertIn(".sl-faq summary{cursor:pointer;font-family:var(--sl-font-heading);font-size:1.4rem", html)
        self.assertIn(".sl-faq p{color:var(--sl-faq-text);font-size:1.4rem", html)
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

    def test_trust_badges_skip_disabled_slots(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        trust_badges = next(section for section in page["sections"] if section["type"] == "trust_badges")
        trust_badges["badges"] = [
            {"enabled": False, "emoji": "x", "label": "Hidden badge"},
            {"enabled": True, "emoji": "✓", "label": "Visible badge"},
        ]

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("Visible badge", html)
        self.assertNotIn("Hidden badge", html)

    def test_headlines_use_chicago_title_case_and_markup(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["tokens"] = {
            "highlight_text": "#123456",
            "highlight_bg": "#abcdef",
            "highlight_bg_text": "#111111",
        }
        headline = next(section for section in page["sections"] if section["type"] == "headline")
        headline["text"] = "make **more money** with ^^stripe link^^ today"
        content = next(section for section in page["sections"] if section["type"] == "content_block")
        content["blocks"][0]["title"] = "answers for **busy tenants**"
        faq = next(section for section in page["sections"] if section["type"] == "faq")
        faq["items"][0]["question"] = "what is ^^inside the box^^?"

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-highlight-text:#123456", html)
        self.assertIn("--sl-highlight-bg:#abcdef", html)
        self.assertIn("--sl-highlight-bg-text:#111111", html)
        self.assertIn("Make <span class=\"sl-mark-text\">More Money</span> With <span class=\"sl-mark-bg\">Stripe Link</span> Today", html)
        self.assertIn("Answers for <span class=\"sl-mark-text\">Busy Tenants</span>", html)
        self.assertIn("What Is <span class=\"sl-mark-bg\">Inside the Box</span>?", html)

    def test_universal_bundle_markup_uses_default_highlight_colors(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        headline = next(section for section in page["sections"] if section["type"] == "headline")
        headline["text"] = "Create **Recurring Revenue** With ^^Payment Links^^"

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-highlight-text:#f97316", html)
        self.assertIn("--sl-highlight-bg:#facc15", html)
        self.assertIn("--sl-highlight-bg-text:#1a1a1a", html)
        self.assertIn("<span class=\"sl-mark-text\">Recurring Revenue</span>", html)
        self.assertIn("<span class=\"sl-mark-bg\">Payment Links</span>", html)

    def test_refund_policy_prefers_offer_policy(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        offer["refund_policy"] = {
            "source": "offer",
            "short_label": "Offer refund guarantee",
            "return_method": "return_required",
            "full_policy": "Offer-specific refund copy applies to this bundle.",
        }

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("<summary>Offer refund guarantee</summary>", html)
        self.assertIn("Offer-specific refund copy applies to this bundle.", html)
        self.assertIn("The customer must return the item", html)
        self.assertNotIn("Physical items may be returned within 30 days", html)

    def test_refund_policy_section_can_be_disabled(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        refund_section = next(section for section in page["sections"] if section["type"] == "refund_policy")
        refund_section["enabled"] = False

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertNotIn("class=\"sl-refund-policy\"", html)
        self.assertNotIn("data-section-type=\"refund_policy\"", html)

    def test_legal_footer_current_year_token_is_filled_by_javascript(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        legal_footer = next(section for section in page["sections"] if section["type"] == "legal_footer")
        legal_footer["copyright"] = "© {{current_year}} All rights reserved."

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("© <span data-sl-current-year></span> All rights reserved.", html)
        self.assertIn("new Date().getFullYear()", html)

    def test_universal_bundle_element_tokens_override_preset(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["tokens"] = {
            "hero_border": "#111111",
            "price_card_bg": "#222222",
            "price_card_selected_border": "#333333",
            "refund_applies": "#444444",
            "faq_summary": "#555555",
            "legal_link": "#666666",
            "countdown_bg": "#777777",
            "countdown_end_bg": "#888888",
        }
        countdown = next(section for section in page["sections"] if section["type"] == "countdown_timer")
        countdown.pop("start_color", None)
        countdown.pop("end_color", None)

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-hero-border:#111111", html)
        self.assertIn("--sl-price-card-bg:#222222", html)
        self.assertIn("--sl-price-card-selected-border:#333333", html)
        self.assertIn("--sl-refund-applies:#444444", html)
        self.assertIn("--sl-faq-summary:#555555", html)
        self.assertIn("--sl-legal-link:#666666", html)
        self.assertIn("data-start-color=\"#777777\"", html)
        self.assertIn("data-end-color=\"#888888\"", html)

    def test_universal_bundle_countdown_defaults_to_cta_colors_for_non_techno_presets(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["preset"] = "rose-minimalist"
        countdown = next(section for section in page["sections"] if section["type"] == "countdown_timer")
        countdown.pop("start_color", None)
        countdown.pop("end_color", None)

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-cta-from:#d63d76", html)
        self.assertIn("--sl-cta-to:#c22d66", html)
        self.assertIn("data-start-color=\"#d63d76\"", html)
        self.assertIn("data-end-color=\"#c22d66\"", html)

    def test_universal_bundle_theme_fonts_override_defaults(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page = copy.deepcopy(page)
        page["theme"]["fonts"] = {
            "service": "junior-bay",
            "body": {"family": "Inter", "fallback": "sans-serif"},
            "heading": {"family": "Inter Tight", "fallback": "sans-serif"},
            "accent": {"family": "JB Mono", "fallback": "monospace"},
        }

        html = render_page(page, offer, {product["product_id"]: product})

        self.assertIn("--sl-font-body:Inter,sans-serif", html)
        self.assertIn("--sl-font-heading:'Inter Tight',sans-serif", html)
        self.assertIn("--sl-font-accent:'JB Mono',monospace", html)

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

    def test_render_page_disables_checkout_cta_on_click(self):
        html = render_page(
            self.page,
            self.offer,
            self.products_by_id,
            checkout_url="https://dev.juniorbay.com/checkout",
        )

        self.assertIn(".sl-cta.is-connecting", html)
        self.assertIn("cta.textContent = 'Connecting...';", html)
        self.assertIn("window.location.assign(href)", html)

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
