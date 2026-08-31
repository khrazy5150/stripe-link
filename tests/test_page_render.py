import json
import copy
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from handlers.page_render import handler
from stripe_link.runtime.html import RenderError, format_money, render_page, responsive_img


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ListicleCartFunnelTests(unittest.TestCase):
    """A multi-product landing (listicle carousel) with a post-checkout funnel must route its cart Checkout to
    the post-purchase funnel, like the single-product CTA (plans/LANDING_CAROUSEL_FIXES.md Bug 3)."""

    def _render(self, with_post_checkout):
        product_a = load_fixture("product-creatine-gummies.json")
        product_b = copy.deepcopy(product_a)
        product_b["product_id"] = "prod_second"
        product_b["name"] = "Second Product"
        product_b["default_price_id"] = "price_1bottle_b"
        for price in product_b["prices"]:
            price["price_id"] = price["price_id"] + "_b"
        offer = load_fixture("offer-creatine-standard.json")
        offer["offer_type"] = None
        offer["items"] = [  # two distinct landing products -> listicle carousel; product A keeps its 4 tiers
            offer["items"][0],
            {"product_id": "prod_second", "price_id": "price_1bottle_b", "quantity": 1},
        ]
        page = load_fixture("page-creatine-standard.json")
        if with_post_checkout:
            page["post_checkout"] = {"thank_you_page": {"page_id": "page_ty"}}
        else:
            page.pop("post_checkout", None)
        products = {"prod_creatine_gummies": product_a, "prod_second": product_b}
        return render_page(page, offer, products, api_base_url="https://api-dev.example.com")

    def test_cart_routes_to_funnel_when_page_has_post_checkout(self):
        html = self._render(with_post_checkout=True)
        self.assertIn("data-listicle", html)  # rendered as the listicle carousel
        self.assertIn('data-has-post-checkout="true"', html)
        self.assertIn("data-page-id=", html)
        # The cart's Checkout builds the funnel entry success_url (unencoded Stripe token), not a bare landing return.
        self.assertIn("post-checkout/next", html)
        self.assertIn("{CHECKOUT_SESSION_ID}", html)
        # On a successful handoff to Stripe the local cart is cleared, so returning to the page shows no items.
        self.assertIn("localStorage.removeItem(idKey)", html)

    def test_cart_uses_plain_success_when_no_post_checkout(self):
        html = self._render(with_post_checkout=False)
        self.assertIn("data-listicle", html)
        self.assertIn('data-has-post-checkout="false"', html)

    def test_cart_checkout_surfaces_blocks_in_a_themed_notice_not_alert(self):
        # A blocked cart checkout (e.g. the publish guard) shows the reason in a themed in-page modal (the
        # server page can't mount ConfirmDialog.vue), never the browser's window.alert.
        html = self._render(with_post_checkout=False)
        self.assertIn("const slNotice = (message)", html)
        self.assertIn("slNotice(err && err.message", html)   # the checkout catch surfaces the server message
        self.assertNotIn("window.alert", html)
        self.assertIn(".sl-notice-card{", html)              # themed with the page tokens

    def test_carousel_renders_one_tier_block_per_product_with_a_single_add(self):
        html = self._render(with_post_checkout=False)
        # One tier block per landing product; the first visible, the rest hidden (synced to the hero on swipe).
        self.assertEqual(html.count('class="sl-listicle-tiers"'), 2)
        self.assertIn('data-index="0"', html)
        self.assertIn('data-index="1" data-product-id="prod_second" hidden>', html)
        # Product A exposes its FULL tier selector (multiple tiers), not just the first (Bug 2).
        self.assertIn(">1 Bottle</strong>", html)
        self.assertIn(">6 Bottles</strong>", html)
        # Exactly one shared Add-to-cart (adds the shown product at its selected tier).
        self.assertEqual(html.count('class="sl-cta sl-listicle-add"'), 1)


class PageRenderTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}

    def test_render_page_outputs_semantic_sections_and_price_options(self):
        # The default favicon now comes from the configured asset CDN (app_config.public_asset_base_url), resolved by
        # the server-side reader — patch it to a known value to assert the tags carry it.
        with patch("stripe_link.runtime.html.default_favicon_url", return_value="https://images.juniorbay.com/icon/favicon.png"):
            html = render_page(self.page, self.offer, self.products_by_id)

        self.assertIn(">Creatine Gummies</h1>", html)   # the hero headline is the page's sole <h1>
        self.assertEqual(html.count("<h1"), 1)          # exactly one H1 — semantic outline invariant
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
        self.assertIn(".sl-brand-label p{font-family:var(--sl-font-accent);font-size:1.3rem", html)
        self.assertIn(".sl-headline h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem)", html)
        self.assertIn(".sl-price-option strong{font-family:var(--sl-font-heading);font-size:1.6rem", html)
        self.assertIn(".sl-price-description{color:var(--sl-price-description);font-size:1.3rem", html)
        self.assertIn("data-section-type=\"brand_label\"", html)
        self.assertIn(">Creatine Gummies</p>", html)
        self.assertIn("data-section-type=\"hero_media\"", html)
        self.assertIn("data-media-count=\"1\"", html)
        self.assertIn("images/universal-bundle/creatine_gummies_1.webp", html)
        self.assertIn("<h1>Get Creatine Gummies Bundle Today</h1>", html)   # standalone headline = the h1
        self.assertIn(">Creatine Gummies</p>", html)                         # brand label demoted to <p>
        self.assertEqual(html.count("<h1"), 1)                               # exactly one H1
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
        self.assertIn(".sl-content-block h2{font-family:var(--sl-font-heading);font-size:2rem", html)
        self.assertIn(".sl-content-block p{color:var(--sl-content-text);font-size:1.5rem", html)
        self.assertIn("data-section-type=\"faq\"", html)
        self.assertIn(".sl-faq summary{cursor:pointer;font-family:var(--sl-font-heading);font-size:1.4rem", html)
        self.assertIn(".sl-faq p{color:var(--sl-faq-text);font-size:1.4rem", html)
        # FAQ joins the heading outline: an <h2> section heading with each question as an <h3> (plans/SEMANTIC_HTML.md).
        self.assertIn("<h2 class=\"sl-faq-heading\">", html)
        self.assertIn("<summary><h3>", html)
        self.assertIn("Get The Bundle - $69.42", html)
        self.assertIn("Terms of Service", html)
        self.assertIn("© 2026 All rights reserved.", html)
        # Persistence now records the DURATION alongside the value, so changing the timer discards a
        # stale deadline instead of counting down the old one (fixed 2026-08-31).
        self.assertIn("writeStored('expired')", html)
        self.assertIn("JSON.stringify({ v: value, d: duration })", html)
        self.assertIn("Number(parsed.d) === duration", html)
        self.assertIn("expireDiscounts()", html)
        self.assertIn("selectCard(cards.find", html)

    def test_every_theme_preset_is_complete_and_validated(self):
        # Each preset must carry the keys theme_tokens() needs (no KeyError), render cleanly, and be in the
        # document validator's allow-list — so a saved page can actually use it.
        from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS, theme_tokens
        from stripe_link.domain.documents import SUPPORTED_THEME_PRESETS
        page = copy.deepcopy(load_fixture("page-universal-bundle.json"))
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        for preset in UNIVERSAL_BUNDLE_THEME_PRESETS:
            self.assertIn(preset, SUPPORTED_THEME_PRESETS, f"{preset} missing from SUPPORTED_THEME_PRESETS")
            page["theme"]["preset"] = preset
            tokens = theme_tokens(page)  # must not KeyError on any required key
            self.assertTrue(tokens["cta_from"] and tokens["cta_to"])
            render_page(page, offer, {product["product_id"]: product})  # must render

    def test_socialite_preset_renders_gradient_cta(self):
        page = copy.deepcopy(load_fixture("page-universal-bundle.json"))
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page["theme"]["preset"] = "tiktok-dark"
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertIn("--sl-cta-from:#ff0050", html)
        self.assertIn("--sl-cta-to:#00f2ea", html)
        self.assertIn("--sl-brand:#ff0050", html)
        # the button itself is the gradient
        self.assertIn("background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to))", html)

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

    def test_legal_footer_links_open_in_new_tab_and_honor_absolute_urls(self):
        page = load_fixture("page-universal-bundle.json")
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")

        html = render_page(page, offer, {product["product_id"]: product}, api_base_url="https://api.example.com/prod")

        self.assertIn("<a href=\"https://example.com/terms\" target=\"_blank\" rel=\"noopener\">Terms of Service</a>", html)
        self.assertIn("<a href=\"https://example.com/refunds\" target=\"_blank\" rel=\"noopener\">Refund Policy</a>", html)

    def test_legal_footer_placeholders_default_to_platform_legal_pages(self):
        page = copy.deepcopy(load_fixture("page-universal-bundle.json"))
        offer = load_fixture("offer-universal-bundle.json")
        product = load_fixture("product-universal-bundle.json")
        page["legal"] = {"terms_url": "#terms", "privacy_url": "#privacy", "refund_url": "#refund-policy"}

        html = render_page(page, offer, {product["product_id"]: product}, api_base_url="https://api.example.com/prod")

        self.assertIn("<a href=\"https://api.example.com/prod/legal/terms\" target=\"_blank\" rel=\"noopener\">Terms of Service</a>", html)
        self.assertIn("<a href=\"https://api.example.com/prod/legal/privacy\" target=\"_blank\" rel=\"noopener\">Privacy Policy</a>", html)
        self.assertIn("<a href=\"https://api.example.com/prod/legal/refund\" target=\"_blank\" rel=\"noopener\">Refund Policy</a>", html)
        self.assertNotIn("#terms", html)
        self.assertNotIn("#refund-policy", html)

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

    def test_render_page_stamps_post_checkout_and_api_base_url_for_funnel_routing(self):
        self.assertIn("post_checkout", self.page)
        html = render_page(
            self.page,
            self.offer,
            self.products_by_id,
            checkout_url="https://dev.juniorbay.com/checkout",
            api_base_url="https://api.example.com/dev",
        )

        self.assertIn("data-checkout-has-post-checkout=\"true\"", html)
        self.assertIn("data-checkout-api-base-url=\"https://api.example.com/dev\"", html)
        self.assertIn("class=\"sl-cta sl-decline-cta\"", html)
        self.assertIn("style=\"display:none\"", html)
        self.assertIn("post-checkout/next", html)
        self.assertIn("/upsell/session", html)
        self.assertIn("/upsell/charge", html)
        self.assertIn("funnel_page", html)
        self.assertIn("isFunnelStep", html)
        self.assertIn("{CHECKOUT_SESSION_ID}", html)

    def test_render_page_marks_post_checkout_false_when_not_configured(self):
        page = copy.deepcopy(self.page)
        page.pop("post_checkout", None)
        html = render_page(
            page,
            self.offer,
            self.products_by_id,
            checkout_url="https://dev.juniorbay.com/checkout",
            api_base_url="https://api.example.com/dev",
        )

        self.assertIn("data-checkout-has-post-checkout=\"false\"", html)
        self.assertIn("window.location.assign(href)", html)

    def test_offer_derived_funnel_enters_even_without_page_post_checkout(self):
        # An offer with funnel.upsells but NO page.post_checkout block still routes checkout success into the
        # funnel (SALES_FUNNELS.md P2b) — the entry gate is offer-aware, not page-block-only.
        page = copy.deepcopy(self.page)
        page.pop("post_checkout", None)
        offer = copy.deepcopy(self.offer)
        offer["funnel"] = {"upsells": [{"product_id": "prod_up", "price_id": "price_up"}]}
        html = render_page(
            page, offer, self.products_by_id,
            checkout_url="https://dev.juniorbay.com/checkout", api_base_url="https://api.example.com/dev",
        )
        self.assertIn("data-checkout-has-post-checkout=\"true\"", html)
        self.assertIn("post-checkout/next", html)

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

    def test_render_handler_accepts_valid_price_context(self):
        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": self.offer,
                "products": [self.product],
                "price_context": "sale",
            })
        }, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("<!doctype html>", json.loads(response["body"])["html"])

    def test_render_handler_rejects_unknown_price_context(self):
        response = handler({
            "body": json.dumps({
                "page": self.page,
                "offer": self.offer,
                "products": [self.product],
                "price_context": "bogus",
            })
        }, None)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "render_error")

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


class ResponsiveImageTests(unittest.TestCase):
    def test_rendition_url_emits_webp_srcset_and_sizes(self):
        markup = responsive_img(
            "https://images.juniorbay.com/products/ABC123/medium.webp",
            "Water Gun",
            sizes="9rem",
        )
        # A processor rendition advertises every rendition (widths mirror the processor's SIZES
        # table) so a small slot can pick thumb/small instead of downloading the 1080px file.
        base = "https://images.juniorbay.com/products/ABC123"
        for size, width in (("thumb", 200), ("small", 640), ("medium", 1080), ("large", 1920), ("full", 2560)):
            self.assertIn(f"{base}/{size}.webp {width}w", markup)
        self.assertIn('sizes="9rem"', markup)
        self.assertIn('loading="lazy"', markup)
        self.assertIn('decoding="async"', markup)

    def test_eager_hero_image_gets_high_fetch_priority(self):
        markup = responsive_img(
            "https://images.juniorbay.com/products/ABC123/small.webp",
            "Hero",
            sizes="100vw",
            eager=True,
        )
        self.assertIn('loading="eager"', markup)
        self.assertIn('fetchpriority="high"', markup)

    def test_non_rendition_url_falls_back_without_srcset(self):
        markup = responsive_img("https://cdn.example.com/pic.jpg", "External", sizes="9rem")
        self.assertNotIn("srcset", markup)
        self.assertIn('src="https://cdn.example.com/pic.jpg"', markup)
        self.assertIn('loading="lazy"', markup)

    def test_explicit_dims_emit_width_and_height(self):
        markup = responsive_img(
            "https://cdn.example.com/pic.jpg", "External", sizes="9rem", dims=(1600, 900)
        )
        self.assertIn(' width="1600" height="900"', markup)

    def test_no_dims_emits_no_width_height(self):
        markup = responsive_img("https://cdn.example.com/pic.jpg", "External", sizes="9rem")
        self.assertNotIn("width=", markup)
        self.assertNotIn("height=", markup)


class FixedPriceOfferTests(unittest.TestCase):
    """A fixed-price offer item (price_id + quantity, no selectable_prices) is a valid shape. It must still
    render a price card and emit Product structured data — the renderer used to read only selectable_prices,
    so fixed offers showed no card and no markup even though the CTA resolved the price."""

    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}
        # Rewrite the first item to the fixed shape.
        offer = copy.deepcopy(self.offer)
        offer["items"][0] = {
            "product_id": self.product["product_id"],
            "price_id": self.product["default_price_id"],
            "quantity": 1,
        }
        self.fixed_offer = offer

    def test_fixed_price_item_renders_a_price_card(self):
        html = render_page(self.page, self.fixed_offer, self.products_by_id)
        self.assertIn("sl-price-option", html)

    def test_fixed_price_item_is_counted_in_landing_page_prices(self):
        from stripe_link.runtime.html import landing_page_offer_prices
        prices = landing_page_offer_prices(self.fixed_offer, self.products_by_id, {})
        self.assertTrue(prices)

    def test_fixed_price_item_has_no_missing_price_warning(self):
        from stripe_link.runtime.html import structured_data_warnings
        warnings = structured_data_warnings(self.fixed_offer, self.products_by_id, {})
        self.assertFalseIfPresent = [w for w in warnings if "No price is shown" in w]
        self.assertEqual(self.assertFalseIfPresent, [])

    def test_fixed_price_item_emits_product_json_ld(self):
        from stripe_link.runtime.html import product_json_ld
        self.assertTrue(product_json_ld(self.page, self.fixed_offer, self.products_by_id, {}))


class LandingPagePriceContextTests(unittest.TestCase):
    """The landing page shows ONLY standard-context prices. sale / flash_sale are alternate pricing modes
    (a future builder toggle), not extra cards — they must not render alongside the standard price."""

    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        product = copy.deepcopy(product)
        product["prices"] = [
            {"price_id": "p_std", "currency": "usd", "unit_amount": 5317, "quantity": 1, "context": "standard"},
            {"price_id": "p_sale", "currency": "usd", "unit_amount": 3709, "quantity": 1, "context": "sale"},
            {"price_id": "p_flash", "currency": "usd", "unit_amount": 3135, "quantity": 1, "context": "flash_sale"},
        ]
        product["default_price_id"] = "p_std"
        self.product = product
        offer = copy.deepcopy(self.offer)
        offer["items"][0] = {
            "product_id": product["product_id"],
            "default_price_id": "p_std",
            "selectable_prices": [
                {"price_id": "p_std", "quantity": 1, "label": "Standard"},
                {"price_id": "p_sale", "quantity": 1, "label": "Sale"},
                {"price_id": "p_flash", "quantity": 1, "label": "Flash"},
            ],
        }
        self.offer = offer
        self.products_by_id = {product["product_id"]: product}

    def test_only_standard_price_renders(self):
        from stripe_link.runtime.html import landing_page_offer_prices
        prices = landing_page_offer_prices(self.offer, self.products_by_id, {})
        self.assertEqual([p["unit_amount"] for p in prices], [5317])

    def test_sale_and_flash_cards_do_not_render(self):
        html = render_page(self.page, self.offer, self.products_by_id)
        self.assertEqual(html.count('data-price-id="p_std"'), 1)
        self.assertNotIn('data-price-id="p_sale"', html)
        self.assertNotIn('data-price-id="p_flash"', html)


class HeadSeoTagsTests(unittest.TestCase):
    """Canonical, robots, Open Graph, and LCP hints (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01/02/09/10)."""

    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}

    def _head(self, **kw):
        return render_page(self.page, self.offer, self.products_by_id, **kw).split("<body", 1)[0]

    def test_canonical_strips_query_and_fragment(self):
        head = self._head(canonical_url="https://axelmart.com/p/mac?checkout=success&session_id=1#top")
        self.assertIn('<link rel="canonical" href="https://axelmart.com/p/mac">', head)

    def test_no_canonical_when_url_absent(self):
        self.assertNotIn("rel=\"canonical\"", self._head())

    def test_indexable_page_gets_index_robots(self):
        head = self._head(canonical_url="https://axelmart.com/p/mac", indexable=True)
        self.assertIn('name="robots" content="index,follow,max-image-preview:large,max-snippet:-1"', head)

    def test_non_indexable_page_is_noindex_by_default(self):
        # Preview / non-prod renders must never be indexable (SEO-02/21).
        head = self._head(canonical_url="https://axelmart.com/p/mac")
        self.assertIn('name="robots" content="noindex,nofollow"', head)

    def test_twitter_and_og_present(self):
        head = self._head(canonical_url="https://axelmart.com/p/mac")
        self.assertIn('name="twitter:card" content="summary_large_image"', head)
        self.assertIn('property="og:url" content="https://axelmart.com/p/mac"', head)

    def test_seo_off_stamps_body_marker(self):
        # Site-level SEO opt-out: the render stamps a body marker CSS keys off to switch the storefront header to
        # its plain no-SEO form (breadcrumb hidden, brand centered). Robots noindex is separate (publish-time).
        site = {"hosting": {"custom_domain": "shop.x.com", "verification": {"verified": True}},
                "organization": {"name": "Axel Mart"}, "indexing": {"eligibility": "eligible", "seo_enabled": False},
                "pages": {"/": {"page_id": self.page["page_id"]}}}
        html = render_page(self.page, self.offer, self.products_by_id, site=site, page_type="landing")
        self.assertIn('<body data-seo="off">', html)
        self.assertIn('body[data-seo="off"] .sl-breadcrumb{display:none}', html)   # off-state CSS present

    def test_seo_on_body_has_no_marker(self):
        site = {"hosting": {"custom_domain": "shop.x.com", "verification": {"verified": True}},
                "organization": {"name": "Axel Mart"}, "indexing": {"eligibility": "eligible"},
                "pages": {"/": {"page_id": self.page["page_id"]}}}
        html = render_page(self.page, self.offer, self.products_by_id, site=site, page_type="landing")
        import re as _re
        self.assertEqual(_re.search(r"<body[^>]*>", html).group(0), "<body>")

    def test_checkout_cta_resolves_return_urls_from_canonical(self):
        html = render_page(self.page, self.offer, self.products_by_id,
                           checkout_url="https://dev.juniorbay.com/checkout",
                           canonical_url="https://axelmart.com/p/mac", indexable=True)
        self.assertNotIn("%7B%7B", html)               # no {{success_url}} placeholder leaked
        self.assertIn("checkout%3Dsuccess", html.replace("%3D", "%3D"))  # ?checkout=success, url-encoded

    def test_checkout_cta_keeps_placeholder_without_canonical(self):
        # Without a canonical, the JS still fills it — keep the placeholder rather than a broken absolute URL.
        html = render_page(self.page, self.offer, self.products_by_id,
                           checkout_url="https://dev.juniorbay.com/checkout")
        self.assertIn("%7B%7Bsuccess_url%7D%7D", html)

    def test_lcp_preconnect_and_preload_when_image_present(self):
        product = {**self.product, "images": ["https://images.juniorbay.com/products/AB/large.webp"]}
        offer = {**self.offer, "items": [{"product_id": product["product_id"], "selectable_prices": self.offer["items"][0].get("selectable_prices")}]}
        head = render_page(self.page, offer, {product["product_id"]: product},
                           canonical_url="https://axelmart.com/p/mac").split("<body", 1)[0]
        self.assertIn('rel="preconnect" href="https://images.juniorbay.com" crossorigin', head)
        self.assertIn('rel="preload" as="image"', head)

    def test_seller_id_anchored_to_canonical_origin(self):
        from stripe_link.runtime.html import product_json_ld, _RENDER_STATE
        product = {**self.product, "product_intent": "transaction"}
        offer = {**self.offer, "presentation": {**(self.offer.get("presentation") or {}), "brand": "Axel Mart"}}
        _RENDER_STATE["canonical"] = "https://axelmart.com/p/mac"
        try:
            ld = product_json_ld(self.page, offer, {product["product_id"]: product}, {})
        finally:
            _RENDER_STATE["canonical"] = ""
        self.assertIn("axelmart.com/#organization", ld)
        self.assertIn("OnlineStore", ld)


class DocumentHeadCopyTests(unittest.TestCase):
    """The <head> <title>/<meta description> derive from the product when the page has no SEO override, and
    never from page.name/offer.name (the internal '… Single Offer' label). plans/SEMANTIC_HTML.md +
    plans/LANDING_PAGE_DEFAULT_COPY.md."""

    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}

    def _title(self, html):
        return re.search(r"<title>(.*?)</title>", html).group(1)

    def _meta(self, html):
        match = re.search(r'<meta name="description" content="(.*?)">', html)
        return match.group(1) if match else None

    def test_empty_seo_title_uses_buy_formula_not_page_name(self):
        # SEO-03: "Buy {condition} {product} | {brand_label}", never the internal page name.
        product = {**self.product, "product_intent": "transaction", "condition": "used"}
        offer = {**self.offer, "presentation": {**(self.offer.get("presentation") or {}), "brand": "Acme Co"}}
        page = {**self.page, "name": "Creatine Gummies Single Offer Landing Page", "seo": {}}
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertNotIn("Single Offer", self._title(html))
        self.assertEqual(self._title(html), "Buy Used Creatine Gummies | Acme Co")

    def test_lead_gen_title_omits_buy_prefix(self):
        from stripe_link.runtime.html import document_title
        offer = {"items": [{"product_id": "p"}], "presentation": {"brand": "Acme Co"}, "product_intent": "lead_gen"}
        self.assertEqual(
            document_title({"seo": {}}, offer, {"p": {"name": "Free Guide", "product_intent": "lead_gen"}}),
            "Free Guide | Acme Co",
        )

    def test_title_brand_falls_back_to_platform_when_no_brand(self):
        from stripe_link.runtime.html import document_title
        offer = {"items": [{"product_id": "p"}], "presentation": {}}
        self.assertEqual(
            document_title({"seo": {}}, offer, {"p": {"name": "Widget", "product_intent": "transaction"}}),
            "Buy Widget | Junior Bay",
        )

    def test_thin_description_is_enriched_with_shop_prefix(self):
        # SEO-04: a short description is wrapped; a long one is used verbatim (trimmed).
        product = {**self.product, "name": "Creatine Gummies", "description": "Tasty berry gummies.", "product_intent": "transaction"}
        page = {**self.page, "seo": {}}
        html = render_page(page, self.offer, {product["product_id"]: product})
        meta = self._meta(html)
        self.assertTrue(meta.startswith("Shop Creatine Gummies."), meta)
        self.assertIn("Tasty berry gummies", meta)

    def test_long_description_is_used_verbatim(self):
        product = {**self.product, "description": "Premium creatine monohydrate gummies. " * 5}
        page = {**self.page, "seo": {}}
        html = render_page(page, self.offer, {product["product_id"]: product})
        self.assertTrue(self._meta(html).startswith("Premium creatine monohydrate gummies."))
        self.assertNotIn("Shop", self._meta(html))

    def test_explicit_seo_is_respected(self):
        page = {**self.page, "seo": {"title": "My Keyword Title", "description": "My snippet."}}
        html = render_page(page, self.offer, self.products_by_id)
        self.assertEqual(self._title(html), "My Keyword Title")
        self.assertEqual(self._meta(html), "My snippet.")

    # --- Offer Semantic Model P2: title + meta name the same subject as the offer label / slug ------------

    def _bundle(self, cats, brand="Acme Co"):
        # Two-product offer; each product in cats[i]. Shared category -> "Creatine Bundle"; mixed -> "A + B".
        prods = {}
        for i, cat in enumerate(cats):
            pid = f"prod_b{i}"
            prods[pid] = {"product_id": pid, "name": f"Item {i}", "product_category": cat,
                          "product_type": "physical", "product_intent": "transaction",
                          "description": "Short.", "default_price_id": f"{pid}_p",
                          "prices": [{"price_id": f"{pid}_p", "unit_amount": 1000, "currency": "usd",
                                      "quantity": 1, "context": "standard"}]}
        offer = {"product_intent": "transaction", "presentation": {"brand": brand},
                 "items": [{"product_id": pid, "quantity": 1} for pid in prods]}
        return offer, prods

    def test_bundle_title_names_the_bundle_not_first_product(self):
        # A shared-category bundle is titled by its subject, coherent with label_from_model ("Creatine Bundle").
        from stripe_link.runtime.html import document_title
        offer, prods = self._bundle(["creatine", "creatine"])
        self.assertEqual(document_title({"seo": {}}, offer, prods), "Buy Creatine Bundle | Acme Co")

    def test_bundle_meta_shops_the_bundle_subject(self):
        from stripe_link.runtime.html import document_description
        offer, prods = self._bundle(["creatine", "creatine"])
        self.assertTrue(document_description({"seo": {}}, offer, prods).startswith("Shop Creatine Bundle."))

    def test_mixed_bundle_title_names_both_products(self):
        from stripe_link.runtime.html import document_title
        offer, prods = self._bundle(["creatine", "protein"])
        self.assertEqual(document_title({"seo": {}}, offer, prods), "Buy Item 0 + Item 1 Bundle | Acme Co")

    def test_bundle_title_suppresses_per_product_condition_word(self):
        # "Used" describes one product, not a mixed bundle — it must not leak into the bundle title.
        from stripe_link.runtime.html import document_title
        offer, prods = self._bundle(["creatine", "creatine"])
        for p in prods.values():
            p["condition"] = "used"
        self.assertEqual(document_title({"seo": {}}, offer, prods), "Buy Creatine Bundle | Acme Co")

    def test_single_product_title_is_unchanged_by_the_repoint(self):
        # Golden guard: a single product still uses product.name verbatim (byte-identical to pre-P2).
        from stripe_link.runtime.html import document_title
        product = {**self.product, "product_intent": "transaction", "condition": "used"}
        offer = {**self.offer, "presentation": {**(self.offer.get("presentation") or {}), "brand": "Acme Co"}}
        self.assertEqual(document_title({"seo": {}}, offer, {product["product_id"]: product}),
                         "Buy Used Creatine Gummies | Acme Co")


class ImageDimsSidecarTests(unittest.TestCase):
    """The image_dims sidecar (base -> [w, h]) reserves layout space and hints crawlers. It is merged into
    a render-scoped index so responsive_img emits width/height without threading a map everywhere."""

    def test_collect_merges_and_normalizes_rendition_keys(self):
        from stripe_link.runtime.html import collect_image_dims

        base = "https://images.juniorbay.com/products/ABC123"
        merged = collect_image_dims(
            {"image_dims": {f"{base}/large.webp": [1920, 1280]}},  # a full rendition URL as key
            {"image_dims": {"https://images.juniorbay.com/offers/HERO9": [800, 800]}},  # a bare base
        )
        # A rendition-URL key collapses to its base so any rendition of that asset resolves.
        self.assertEqual(merged[base], (1920, 1280))
        self.assertEqual(merged["https://images.juniorbay.com/offers/HERO9"], (800, 800))

    def test_collect_skips_malformed_entries(self):
        from stripe_link.runtime.html import collect_image_dims

        merged = collect_image_dims({"image_dims": {
            "https://x/a": [100, 200],
            "https://x/b": [0, 200],        # non-positive -> skip
            "https://x/c": ["wide", 200],   # non-int -> skip
            "https://x/d": [100],           # wrong arity -> skip
        }})
        self.assertEqual(merged, {"https://x/a": (100, 200)})

    def test_render_page_emits_dimensions_from_sidecar(self):
        page = load_fixture("page-creatine-standard.json")
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        images = [img for img in (product.get("images") or []) if "/" in img]
        if not images:
            self.skipTest("fixture product has no rendition image to key dims against")
        from stripe_link.runtime.html import rendition_base
        base = rendition_base(images[0]) or images[0]
        product = {**product, "image_dims": {base: [1080, 720]}}
        html = render_page(page, offer, {product["product_id"]: product})
        self.assertIn('width="1080" height="720"', html)


if __name__ == "__main__":
    unittest.main()


class LandingPageIgnoresPostCheckoutPricingTests(unittest.TestCase):
    """A landing page must price itself only from what it displays. An offer's default_price_id may point at
    an upsell / downsell / order-bump price — those belong to the post-checkout flow. Honouring one made the
    CTA advertise an amount no card showed ("Buy Now - $22.17" against cards of $37.09-$89.90) and left every
    card unchecked, because is_landing_page_price() had already filtered the default out of the cards.
    """

    def _fixtures(self, default_context="upsell"):
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        item = offer["items"][0]
        # Give the product a post-checkout price and point the offer's default at it.
        bump = {
            "price_id": "price_postcheckout",
            "unit_amount": 2217,
            "currency": "usd",
            "context": default_context,
            "label": "Post-checkout only",
        }
        product["prices"].append(bump)
        item["selectable_prices"].append({"price_id": "price_postcheckout", "label": "Post-checkout only"})
        item["default_price_id"] = "price_postcheckout"
        return page, offer, {product["product_id"]: product}

    def test_cta_never_advertises_a_post_checkout_price(self):
        for context in ("upsell", "downsell", "order_bump"):
            with self.subTest(context=context):
                page, offer, products = self._fixtures(context)
                html = render_page(page, offer, products)
                self.assertNotIn("$22.17", html, f"{context} price leaked into the page")
                self.assertNotIn('data-cta-amount="2217"', html)

    def test_cta_amount_matches_the_selected_card(self):
        page, offer, products = self._fixtures()
        html = render_page(page, offer, products)
        cta = re.search(r'data-cta-amount="(\d+)"', html).group(1)
        checked = re.search(r'data-price-id="([^"]+)"[^>]*data-default="true"[^>]*data-sale-amount="(\d+)"', html)
        self.assertIsNotNone(checked, "some card must be the default when the offer's default is filtered out")
        self.assertEqual(cta, checked.group(2), "CTA must advertise the selected card's price")

    def test_a_displayed_default_is_still_honoured(self):
        # The correction only kicks in when the offer's default isn't displayable — it must not override a
        # perfectly good default.
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        page = load_fixture("page-creatine-standard.json")
        chosen = offer["items"][0]["selectable_prices"][1]["price_id"]
        offer["items"][0]["default_price_id"] = chosen
        html = render_page(page, offer, {product["product_id"]: product})
        checked = re.search(r'data-price-id="([^"]+)"[^>]*data-default="true"', html)
        self.assertEqual(checked.group(1), chosen)

    def test_an_explicit_selection_still_wins_for_the_cta(self):
        # selected_prices is the caller stating the shopper's actual choice; the correction only supplies a
        # default when none was given, and must never override an explicit one.
        page, offer, products = self._fixtures()
        product_id = offer["items"][0]["product_id"]
        chosen = offer["items"][0]["selectable_prices"][1]["price_id"]
        chosen_amount = next(
            p["unit_amount"] for p in products[product_id]["prices"] if p["price_id"] == chosen
        )
        html = render_page(page, offer, products, {product_id: chosen})
        self.assertIn(f'data-cta-amount="{chosen_amount}"', html)


class BrandHeroLogoTests(unittest.TestCase):
    """Storefront brand mark (SITE_OBJECT §2.5b): the tenant's uploaded logo, else an auto-generated faux
    house logo — so every storefront has a mark."""

    def test_uploaded_logo_renders_as_image(self):
        from stripe_link.runtime.html import render_brand_hero
        html = render_brand_hero({"id": "h", "type": "brand_hero", "headline": "Nutri-Pro",
                                  "logo_url": "https://cdn.example/logo.png"})
        self.assertIn('<img class="sl-brand-logo" src="https://cdn.example/logo.png"', html)
        self.assertIn('alt="Nutri-Pro logo"', html)
        self.assertNotIn("sl-brand-logo-faux", html)
        self.assertIn("<h1>", html)

    def test_missing_logo_renders_faux_house(self):
        from stripe_link.runtime.html import render_brand_hero
        html = render_brand_hero({"id": "h", "type": "brand_hero", "headline": "Nutri-Pro"})
        self.assertIn("sl-brand-logo sl-brand-logo-faux", html)
        self.assertIn("<svg", html)
        self.assertNotIn("<img", html)


class BnplMessagingRenderTests(unittest.TestCase):
    """On-page Stripe Payment Method Messaging Element below the price (plans/BNPL_PAYMENT_METHODS.md P3)."""

    def setUp(self):
        self.page = load_fixture("page-creatine-standard.json")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products_by_id = {self.product["product_id"]: self.product}
        self.msg = {"publishable_key": "pk_test_abc", "payment_method_types": ["klarna", "affirm"], "country": "US"}

    def test_messaging_element_rendered_with_config(self):
        html = render_page(self.page, self.offer, self.products_by_id, bnpl_messaging=self.msg)
        self.assertIn('id="sl-bnpl-message"', html)                       # the mount div, below the price
        self.assertIn("https://js.stripe.com/v3/", html)                 # Stripe.js loaded
        self.assertIn('Stripe("pk_test_abc")', html)                     # tenant publishable key
        self.assertIn("paymentMethodMessaging", html)                    # the messaging element
        self.assertIn('paymentMethodTypes: ["klarna", "affirm"]', html)  # enabled+supported methods
        self.assertIn('base.countryCode = "US"', html)                   # account country
        self.assertIn("currentAmount() || 6700", html)                   # initial render: DOM default, else resolved subtotal ($67.00)
        self.assertIn('currency: "USD"', html)
        self.assertIn("appearance:", html)                               # fixed light-card scheme (iframe + white modal)
        self.assertIn("colorBackground: '#ffffff'", html)
        self.assertIn(".sl-bnpl-message:not(:empty)", html)              # light card only once mounted
        # follows the price selector: re-renders with the picked tier's amount
        self.assertIn(".sl-price-options", html)
        self.assertIn("data-sale-amount", html)
        self.assertIn("conversion:itemChanged", html)   # hooks the selector's event bus (click sets .checked programmatically)
        self.assertIn("window.slConversion", html)

    def test_no_messaging_without_config(self):
        html = render_page(self.page, self.offer, self.products_by_id)
        self.assertNotIn('id="sl-bnpl-message"', html)   # the .sl-bnpl-message CSS rule is always present; the div is not
        self.assertNotIn("js.stripe.com", html)

    def test_no_messaging_when_no_methods(self):
        html = render_page(self.page, self.offer, self.products_by_id,
                           bnpl_messaging={"publishable_key": "pk_test", "payment_method_types": []})
        self.assertNotIn('id="sl-bnpl-message"', html)
        self.assertNotIn("js.stripe.com", html)

    def test_messaging_on_listicle_carousel(self):
        # A listicle (multi-product carousel) mounts the messaging below the tiers, before Add-to-cart, and the
        # init follows the CAROUSEL product: conversion:itemChanged index -> the product's own tier block
        # (.sl-listicle-tiers[data-index=i]), not a tier card in one options set as single/bundle does.
        product_a = load_fixture("product-creatine-gummies.json")
        product_b = copy.deepcopy(product_a)
        product_b["product_id"] = "prod_second"
        product_b["name"] = "Second Product"
        product_b["default_price_id"] = "price_1bottle_b"
        for price in product_b["prices"]:
            price["price_id"] = price["price_id"] + "_b"
        offer = load_fixture("offer-creatine-standard.json")
        offer["offer_type"] = None                                    # two distinct products -> listicle
        offer["items"] = [offer["items"][0],
                          {"product_id": "prod_second", "price_id": "price_1bottle_b", "quantity": 1}]
        page = load_fixture("page-creatine-standard.json")
        products = {"prod_creatine_gummies": product_a, "prod_second": product_b}
        html = render_page(page, offer, products, bnpl_messaging=self.msg, api_base_url="https://api.example.com")
        self.assertIn("data-listicle", html)                          # rendered as the carousel
        self.assertIn('id="sl-bnpl-message"', html)                   # mount div present
        self.assertIn("https://js.stripe.com/v3/", html)
        self.assertIn("var isListicle", html)                         # listicle-aware init
        self.assertIn('sl-listicle-tiers[data-index="', html)         # carousel index -> product block
        self.assertLess(html.find('id="sl-bnpl-message"'),
                        html.find('<button class="sl-cta sl-listicle-add"'))   # div sits before Add-to-cart
        # Finances the running cart total once items are added: reads the total live off the bus and re-prices
        # on any mini-cart mutation (robust to the cartChanged event not reaching the messaging in time).
        self.assertIn("liveCartTotal", html)
        self.assertIn("window.slConversion.cartTotal", html)
        self.assertIn("new MutationObserver", html)
        self.assertIn("[data-minicart]", html)


class BrandHeaderCompositionTests(unittest.TestCase):
    """One brand mark, not two (plans/SITE_COLLECTIONS.md 'Chrome / header composition'). When a page composes
    its own centered ● Brand mark, that mark is the single brand + the crawlable store-root link, and the store
    header drops its brand; a page with no such mark keeps the header brand (non-regressive)."""

    def _with_state(self, **state):
        from stripe_link.runtime.html import _RENDER_STATE, _RENDER_ORG
        self._saved_state = dict(_RENDER_STATE)
        self._saved_org = dict(_RENDER_ORG)
        _RENDER_STATE.update(state)
        _RENDER_ORG.clear()
        _RENDER_ORG["name"] = "Poliaxis Nutrition"

    def tearDown(self):
        from stripe_link.runtime.html import _RENDER_STATE, _RENDER_ORG
        if hasattr(self, "_saved_state"):
            _RENDER_STATE.clear(); _RENDER_STATE.update(self._saved_state)
            _RENDER_ORG.clear(); _RENDER_ORG.update(self._saved_org)

    def test_served_brand_mark_carries_store_root_link_and_header_drops_its_brand(self):
        from stripe_link.runtime.html import render_brand_label, render_site_header
        self._with_state(home_url="https://poliaxis-nutrition.jbay.uk/", page_type="landing")
        mark = render_brand_label({"enabled": True, "label": "Poliaxis Nutrition"}, {})
        self.assertIn('<a class="sl-brand-label-link" href="/">', mark)   # the one crawlable store-root link
        self.assertNotIn('class="sl-brand"', render_site_header(has_brand_mark=True))  # not repeated in the header

    def test_header_keeps_brand_when_page_has_no_brand_mark(self):
        from stripe_link.runtime.html import render_site_header
        self._with_state(home_url="https://poliaxis-nutrition.jbay.uk/", page_type="landing")
        self.assertIn('<a class="sl-brand" href="/">Poliaxis Nutrition</a>', render_site_header(has_brand_mark=False))

    def test_brand_mark_is_plain_text_on_post_checkout_page(self):
        from stripe_link.runtime.html import render_brand_label
        self._with_state(home_url="https://poliaxis-nutrition.jbay.uk/", page_type="thank_you")
        mark = render_brand_label({"enabled": True, "label": "Poliaxis Nutrition"}, {})
        self.assertNotIn("sl-brand-label-link", mark)  # no store-root link that could leak the buyer back out
        self.assertIn("Poliaxis Nutrition", mark)

    def test_brand_mark_plain_text_without_a_home_host(self):
        from stripe_link.runtime.html import render_brand_label
        self._with_state(home_url="", page_type="landing")
        mark = render_brand_label({"enabled": True, "label": "Poliaxis Nutrition"}, {})
        self.assertNotIn("sl-brand-label-link", mark)  # nothing to link to off a served host


class ListiclePlaceholderTests(unittest.TestCase):
    """An image-less product still gets a hero slide (a "no image" placeholder) so the listicle carousel keeps one
    slide PER product and the swipe->tier index sync can't skip it (plans/LANDING_CAROUSEL_FIXES.md). The
    placeholder is a UI fallback only — never an SEO image signal."""

    def _render_two_product_listicle(self, *, second_has_image):
        product_a = load_fixture("product-creatine-gummies.json")
        product_b = copy.deepcopy(product_a)
        product_b["product_id"] = "prod_second"
        product_b["name"] = "Second Product"
        product_b["default_price_id"] = "price_1bottle_b"
        product_b["images"] = product_a["images"] if second_has_image else []
        for price in product_b["prices"]:
            price["price_id"] = price["price_id"] + "_b"
        offer = load_fixture("offer-creatine-standard.json")
        offer["offer_type"] = None  # two distinct products -> listicle
        offer["items"] = [offer["items"][0], {"product_id": "prod_second", "price_id": "price_1bottle_b", "quantity": 1}]
        page = load_fixture("page-creatine-standard.json")
        page["sections"] = [{"type": "hero_media"}, {"type": "offer_price_selector"}]  # ensure the hero carousel renders
        return render_page(page, offer, {"prod_creatine_gummies": product_a, "prod_second": product_b},
                           canonical_url="https://shop.example.com/p", robots="index,follow")

    def test_image_less_product_still_gets_a_hero_slide(self):
        html = self._render_two_product_listicle(second_has_image=False)
        media = re.search(r'<section class="sl-hero-media[^"]*"[^>]*data-media-count="(\d+)"', html)
        self.assertIsNotNone(media)
        self.assertEqual(media.group(1), "2")  # one slide per product, incl. the image-less one (was 1 before the fix)
        hero = re.search(r'<section class="sl-hero-media.*?</section>', html, re.S).group(0)
        self.assertIn("data:image/svg+xml;base64", hero)  # the placeholder fills the otherwise-missing slide

    def test_placeholder_is_never_an_seo_image(self):
        html = self._render_two_product_listicle(second_has_image=False)
        og = re.search(r'og:image" content="([^"]*)"', html)
        self.assertTrue(og)
        self.assertNotIn("data:image", og.group(1))  # og:image stays a real product photo
        ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        self.assertFalse(any("data:image" in block for block in ld))  # never in Product/Offer JSON-LD

    def test_no_placeholder_when_every_product_has_an_image(self):
        html = self._render_two_product_listicle(second_has_image=True)
        media = re.search(r'data-media-count="(\d+)"', html)
        self.assertEqual(media.group(1), "2")
        self.assertNotIn("data:image/svg+xml;base64", html)  # nothing missing -> no placeholder anywhere
