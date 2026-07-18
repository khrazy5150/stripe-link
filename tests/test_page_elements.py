"""New composable page elements: testimonials, rating, client_marquee — render + validate."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import (
    render_client_marquee,
    render_hero_media,
    render_listicle_carousel,
    render_product_carousel,
    render_rating,
    render_testimonials,
)


class ElementRenderTests(unittest.TestCase):
    def test_testimonials_render_quotes_and_bylines(self):
        html = render_testimonials({"id": "t", "heading": "What clients say", "items": [
            {"quote": "Fantastic work.", "author": "Jane", "role": "CEO", "avatar_url": "https://img/x.jpg"},
            {"quote": "", "author": "Skip"},  # empty quote dropped
        ]})
        self.assertIn('data-section-type="testimonials"', html)
        self.assertIn("Fantastic work.", html)
        self.assertIn("Jane", html)
        self.assertNotIn("Skip", html)

    def test_testimonials_empty_renders_nothing(self):
        self.assertEqual(render_testimonials({"items": []}), "")

    def test_rating_renders_stars_and_meta(self):
        html = render_rating({"id": "r", "value": 4.5, "count": 1280, "label": "on Google"})
        self.assertIn('data-section-type="rating"', html)
        self.assertIn("★★★★", html)      # four full stars
        self.assertIn("4.5", html)
        self.assertIn("1,280 reviews", html)
        self.assertIn("on Google", html)

    def test_marquee_few_logos_static_centered_with_default_heading(self):
        html = render_client_marquee({"id": "m", "logos": [
            {"image_url": "https://img/a.png", "name": "Acme"},
            {"image_url": "", "name": "skip"},  # no image dropped
        ]})
        self.assertIn('data-section-type="client_marquee"', html)
        self.assertIn("sl-marquee-static", html)                 # < 5 -> static, not rolling
        self.assertNotIn("sl-marquee-track", html)
        self.assertEqual(html.count("https://img/a.png"), 1)     # not duplicated
        self.assertIn("Our Clients", html)                        # default heading
        self.assertNotIn("skip", html)

    def test_marquee_five_or_more_logos_roll(self):
        logos = [{"image_url": f"https://img/{i}.png", "name": f"C{i}"} for i in range(5)]
        html = render_client_marquee({"id": "m", "heading": "Trusted By", "logos": logos})
        self.assertIn("sl-marquee-track", html)                   # >= 5 -> rolling
        self.assertEqual(html.count("https://img/0.png"), 2)      # duplicated for seamless scroll
        self.assertIn("Trusted By", html)                         # explicit heading kept


def _carousel_offer(oid, pid, price_id):
    return {
        "schema_version": "2026-05-29", "document_type": "offer",
        "offer_id": oid, "tenant_id": "t1", "name": oid, "product_intent": "transaction",
        "status": "active", "stripe_mode": "test", "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
        "items": [{"product_id": pid, "price_id": price_id, "quantity": 1}],
        "presentation": {"headline": oid.upper(), "hero_image_url": f"https://img/{oid}.jpg"},
    }


def _carousel_product(pid, price_id, amount):
    return {
        "schema_version": "2026-05-29", "document_type": "product",
        "product_id": pid, "tenant_id": "t1", "name": pid, "default_price_id": price_id,
        "prices": [{"price_id": price_id, "currency": "usd", "unit_amount": amount, "context": "standard"}],
    }


class ProductCarouselTests(unittest.TestCase):
    def test_carousel_renders_a_priced_buy_slide_per_offer(self):
        section = {"id": "c", "type": "product_carousel", "heading": "Shop", "offer_ids": ["o1", "o2"]}
        offers_by_id = {"o1": _carousel_offer("o1", "p1", "pr1"), "o2": _carousel_offer("o2", "p2", "pr2")}
        products_by_id = {"p1": _carousel_product("p1", "pr1", 1000), "p2": _carousel_product("p2", "pr2", 2500)}
        html = render_product_carousel(
            section, {"tenant_id": "t1", "page_id": "pg"}, offers_by_id, products_by_id, {},
            "https://checkout.example.com", "https://api.example.com/dev",
        )
        self.assertIn('data-section-type="product_carousel"', html)
        self.assertEqual(html.count("sl-carousel-buy"), 2)   # one Buy-now per offer
        self.assertIn("$10.00", html)
        self.assertIn("$25.00", html)
        self.assertIn("O1", html)

    def test_carousel_skips_missing_offers_and_empties_to_nothing(self):
        section = {"id": "c", "type": "product_carousel", "offer_ids": ["missing"]}
        html = render_product_carousel(section, {"tenant_id": "t1"}, {}, {}, {}, None, None)
        self.assertEqual(html, "")


class CarouselPipelineTests(unittest.TestCase):
    def test_load_render_context_loads_carousel_offers(self):
        import copy
        import json
        from pathlib import Path
        from stripe_link.runtime.publishing import load_render_context
        from tests.fakes import FakeDocumentRepository

        root = Path(__file__).resolve().parents[1]
        main_offer = json.load((root / "schemas" / "examples" / "offer-creatine-standard.json").open())
        product = json.load((root / "schemas" / "examples" / "product-creatine-gummies.json").open())
        second_offer = copy.deepcopy(main_offer)
        second_offer["offer_id"] = "offer_creatine_two"  # a second offer reusing the same product

        offers = FakeDocumentRepository("offer_id")
        products = FakeDocumentRepository("product_id")
        offers.put(main_offer)
        offers.put(second_offer)
        products.put(product)
        page = {
            "tenant_id": main_offer["tenant_id"], "page_id": "pg", "offer_id": main_offer["offer_id"],
            "sections": [{"id": "c", "type": "product_carousel", "offer_ids": [second_offer["offer_id"]]}],
        }
        offer, products_by_id, services_by_id, offers_by_id = load_render_context(
            page, offers_repository=offers, products_repository=products,
        )
        self.assertEqual(offer["offer_id"], main_offer["offer_id"])
        self.assertIn(second_offer["offer_id"], offers_by_id)  # carousel offer resolved
        self.assertIn(product["product_id"], products_by_id)   # ...and its product loaded


class ListicleCarouselTests(unittest.TestCase):
    def _listicle(self):
        return {
            "offer_id": "o", "tenant_id": "t1", "name": "Briefs Listicle", "product_intent": "transaction",
            "offer_type": "listicle", "status": "active", "stripe_mode": "test",
            "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
            "items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1},
                      {"product_id": "p2", "price_id": "pr2", "quantity": 1}],
        }

    def _products(self):
        return {
            "p1": {"product_id": "p1", "name": "Briefs", "images": ["https://img/p1.jpg"],
                   "default_price_id": "pr1", "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 5201, "context": "standard"}]},
            "p2": {"product_id": "p2", "name": "NAD+", "images": ["https://img/p2.jpg"],
                   "default_price_id": "pr2", "prices": [{"price_id": "pr2", "currency": "usd", "unit_amount": 5317, "context": "standard"}]},
        }

    def test_renders_price_card_bound_to_conversion_context(self):
        # No image carousel and no hidden per-item data — the conversion island updates this card from the
        # single embedded OfferView payload, so the card's fields carry data-conversion-bind.
        html = render_listicle_carousel(
            self._listicle(), self._products(), {}, {"tenant_id": "t1", "page_id": "pg"},
            "https://checkout.example.com/pay", "https://api.example.com/dev",
        )
        self.assertIn("data-listicle", html)
        self.assertIn('data-conversion-section="offer_selector"', html)
        self.assertIn('data-conversion-bind="price"', html)     # bound to the current target
        self.assertIn('data-conversion-bind="savings"', html)   # "Save X%" like the standard card
        self.assertIn("sl-price-option", html)                  # reuses the standard price card design
        self.assertIn("sl-price-copy", html)
        self.assertIn("data-listicle-add", html)                # the Add-to-cart button
        self.assertIn("$52.01", html)                           # first target's single-unit price (initial)
        self.assertNotIn("data-listicle-item", html)            # no ad-hoc hidden per-item payload
        self.assertNotIn("sl-listicle-carousel", html)          # no separate image carousel
        self.assertNotIn("sl-listicle-card", html)              # bespoke card retired for sl-price-option

    def test_listicle_ignores_bundle_and_funnel_prices(self):
        listicle = self._listicle()
        listicle["items"] = [{"product_id": "p1", "price_id": "pr1", "quantity": 1}]
        products = {"p1": {"product_id": "p1", "name": "Briefs", "images": ["https://img/p1.jpg"],
                           "default_price_id": "pr1", "prices": [
                               {"price_id": "pr1", "currency": "usd", "unit_amount": 3900, "quantity": 1, "context": "standard"},
                               {"price_id": "pr2", "currency": "usd", "unit_amount": 6700, "quantity": 2, "context": "standard"},
                               {"price_id": "pru", "currency": "usd", "unit_amount": 2700, "quantity": 1, "context": "upsell"},
                           ]}}
        html = render_listicle_carousel(listicle, products, {}, {"tenant_id": "t1"}, None, None)
        self.assertIn("$39.00", html)       # the single-unit standard price
        self.assertNotIn("$67.00", html)    # not the 2-pack bundle
        self.assertNotIn("$27.00", html)    # not the upsell


class HeroFixedCopyTests(unittest.TestCase):
    def test_hero_is_not_conversion_bound(self):
        # The hero headline/subheadline are fixed page marketing copy — the carousel must NOT overwrite them
        # with the current product's name/description. Only the price card tracks the target.
        from stripe_link.runtime.html import render_hero
        html = render_hero({"id": "hero", "headline": "Feel 10 Years Younger", "subheadline": "A curated set"})
        self.assertIn("Feel 10 Years Younger", html)
        self.assertIn("A curated set", html)
        self.assertNotIn("data-conversion-bind", html)


class HeroOverlayTests(unittest.TestCase):
    def test_brand_overlay_and_avatar(self):
        from stripe_link.runtime.html import render_hero_overlays
        html = "\n".join(render_hero_overlays(
            {"brand_overlay": True, "brand_position": "bottom-left", "avatar_url": "https://img/a.jpg"},
            {"presentation": {"brand": "MinXin Chen"}},
        ))
        self.assertIn("sl-hero-brand sl-hero-brand--bottom-left", html)
        self.assertIn("MinXin Chen", html)
        self.assertIn("sl-avatar-wrap", html)
        self.assertIn("https://img/a.jpg", html)

    def test_brand_falls_back_to_product_headline_not_offer_name(self):
        from stripe_link.runtime.html import render_hero_overlays
        # The internal offer name ("… Single Offer") must NOT leak as brand; fall back to the
        # product-derived headline (plans/LANDING_PAGE_DEFAULT_COPY.md).
        offer = {"name": "Acme Single Offer", "presentation": {"headline": "Acme Widget"}}
        html = "\n".join(render_hero_overlays({"brand_overlay": True, "brand_position": "middle"}, offer))
        self.assertIn("sl-hero-brand--top-right", html)   # invalid position -> default
        self.assertIn("Acme Widget", html)
        self.assertNotIn("Single Offer", html)

    def test_brand_prefers_picked_brand_over_headline(self):
        from stripe_link.runtime.html import render_hero_overlays
        offer = {"name": "Acme Single Offer", "presentation": {"brand": "Acme Co", "headline": "Acme Widget"}}
        html = "\n".join(render_hero_overlays({"brand_overlay": True}, offer))
        self.assertIn("Acme Co", html)

    def test_empty_when_nothing_set(self):
        from stripe_link.runtime.html import render_hero_overlays
        self.assertEqual(render_hero_overlays({}, {}), [])
        # brand_overlay on but no text anywhere -> nothing
        self.assertEqual(render_hero_overlays({"brand_overlay": True}, {}), [])


class OfferActionsTests(unittest.TestCase):
    def _actions(self, offer):
        from stripe_link.runtime.html import offer_actions
        return offer_actions(offer)

    def test_reads_actions_array_in_order(self):
        offer = {"presentation": {"actions": [
            {"type": "buy_now", "label": "Buy Now"},
            {"type": "add_to_cart", "label": "Add to Cart"},
        ]}}
        actions = self._actions(offer)
        self.assertEqual([a["type"] for a in actions], ["buy_now", "add_to_cart"])
        self.assertEqual(actions[0]["label"], "Buy Now")

    def test_falls_back_to_legacy_cta(self):
        # No actions[] -> derive one action from presentation.cta so existing offers keep working.
        offer = {"presentation": {"cta": {"type": "call", "label": "Ring us", "target": "+15551234567"}}}
        actions = self._actions(offer)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "call_phone")
        self.assertEqual(actions[0]["label"], "Ring us")
        self.assertEqual(actions[0]["target"], "+15551234567")

    def test_defaults_to_buy_now_when_nothing_declared(self):
        actions = self._actions({"presentation": {}})
        self.assertEqual(actions[0]["type"], "buy_now")

    def test_labels_default_by_type(self):
        actions = self._actions({"presentation": {"actions": [{"type": "add_to_cart"}]}})
        self.assertEqual(actions[0]["label"], "Add to Cart")

    def test_listicle_add_label_uses_action(self):
        from stripe_link.runtime.html import listicle_add_label
        offer = {"presentation": {"actions": [
            {"type": "buy_now"}, {"type": "add_to_cart", "label": "Grab it"},
        ]}}
        self.assertEqual(listicle_add_label(offer), "Grab it")
        self.assertEqual(listicle_add_label({"presentation": {}}), "Add to cart")


class AnalyticsAdapterTests(unittest.TestCase):
    def test_empty_when_unconfigured(self):
        from stripe_link.runtime.html import render_analytics_adapters
        self.assertEqual(render_analytics_adapters({}), "")

    def test_loads_pixels_and_subscribes_to_conversion_events(self):
        from stripe_link.runtime.html import render_analytics_adapters
        js = render_analytics_adapters({"google_tag_id": "G-ABC123", "pixel_id": "99887766"})
        self.assertIn("googletagmanager.com/gtag/js", js)   # GA4 base loaded
        self.assertIn("connect.facebook.net", js)           # Meta pixel base loaded
        self.assertIn("conversion:ctaInvoked", js)          # subscribes to the event model
        self.assertIn("add_to_cart", js)                    # GA4 mapping
        self.assertIn("AddToCart", js)                      # Meta mapping
        self.assertIn("window.slConversion", js)            # via the event model, not UI coupling

    def test_ids_are_sanitized(self):
        from stripe_link.runtime.html import render_analytics_adapters
        js = render_analytics_adapters({"google_tag_id": "G-A<b>x", "pixel_id": ""})
        self.assertIn("var GA = 'G-Abx'", js)   # angle brackets stripped — the id can't break out of the script


class ProductDetailsTests(unittest.TestCase):
    def _offer(self):
        return {"offer_id": "o", "tenant_id": "t1", "offer_type": "listicle",
                "items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1}]}

    def _products(self):
        return {"p1": {"product_id": "p1", "name": "A", "description": "desc A",
                       "images": ["https://i/a1.jpg", "https://i/a2.jpg"], "badges": ["Bestseller", {"label": "New"}],
                       "default_price_id": "pr1", "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 5201, "quantity": 1, "context": "standard"}]}}

    def test_renders_context_aware_lists(self):
        from stripe_link.runtime.html import render_product_details
        html = render_product_details(self._offer(), self._products(), {})
        self.assertIn('data-conversion-section="product_details"', html)
        self.assertIn('data-conversion-list="gallery"', html)   # re-rendered per target by the island
        self.assertIn('data-conversion-list="badges"', html)
        self.assertIn('data-conversion-bind="subheadline"', html)
        self.assertIn("a1.jpg", html)          # initial (first target) gallery
        self.assertIn("Bestseller", html)       # string badge
        self.assertIn("New", html)              # dict badge -> label

    def test_conversion_payload_carries_gallery_and_badges(self):
        import json, re
        from stripe_link.runtime.html import render_conversion_data
        html = render_conversion_data(self._offer(), self._products(), {})
        payload = json.loads(re.search(r"data-conversion-offer>(.*)</script>", html).group(1))
        self.assertEqual(payload[0]["gallery"], ["https://i/a1.jpg", "https://i/a2.jpg"])
        self.assertEqual(payload[0]["badges"], ["Bestseller", "New"])


class SectionRegistryTests(unittest.TestCase):
    def test_registry_is_the_dispatch_source_of_truth(self):
        from stripe_link.runtime.html import SECTION_REGISTRY, render_section
        for kind in ("hero", "hero_media", "offer_price_selector", "checkout_cta", "faq", "testimonials",
                     "rating", "client_marquee", "legal_footer"):
            self.assertIn(kind, SECTION_REGISTRY)
            self.assertTrue(callable(SECTION_REGISTRY[kind]["render"]))
        # An unknown type renders an empty placeholder, not a crash.
        html = render_section({"type": "does_not_exist", "id": "x"}, {}, {}, {}, {}, None)
        self.assertIn('data-section-id="x"', html)


class ConversionPayloadTests(unittest.TestCase):
    def test_serializes_offerview_targets_as_json(self):
        from stripe_link.runtime.html import render_conversion_data
        offer = {"offer_id": "o", "tenant_id": "t1", "offer_type": "listicle",
                 "items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1}]}
        products = {"p1": {"product_id": "p1", "name": "Briefs", "description": "12 pack", "images": ["https://i/1.jpg"],
                          "default_price_id": "pr1", "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 3709, "compare_at_amount": 4900, "quantity": 1, "context": "standard"}]}}
        html = render_conversion_data(offer, products, {})
        self.assertIn('type="application/json"', html)
        self.assertIn("data-conversion-offer", html)
        import json, re
        payload = json.loads(re.search(r"data-conversion-offer>(.*)</script>", html).group(1))
        self.assertEqual(payload[0]["headline"], "Briefs")
        self.assertEqual(payload[0]["amount"], 3709)
        self.assertEqual(payload[0]["discount"], 24)   # round((4900-3709)/4900*100)

    def test_escapes_lt_so_json_cannot_close_script(self):
        from stripe_link.runtime.html import render_conversion_data
        offer = {"offer_id": "o", "tenant_id": "t1", "items": [{"product_id": "p1", "price_id": "pr1"}]}
        products = {"p1": {"product_id": "p1", "name": "A </script> x", "images": [], "default_price_id": "pr1",
                          "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 100, "quantity": 1, "context": "standard"}]}}
        html = render_conversion_data(offer, products, {})
        self.assertNotIn("</script> x", html)   # the injected close tag is neutralized
        self.assertIn("\\u003c/script>", html)


class MediaViewerTests(unittest.TestCase):
    def test_is_video_url(self):
        from stripe_link.runtime.html import is_video_url
        self.assertTrue(is_video_url("https://x/clip.mp4"))
        self.assertTrue(is_video_url("https://x/clip.webm?token=1"))
        self.assertFalse(is_video_url("https://x/photo.jpg"))
        self.assertFalse(is_video_url(""))

    def test_video_url_renders_video_element(self):
        from stripe_link.runtime.html import render_hero_media
        # autoplay -> muted+loop+autoplay (browser policy); a mixed image renders as <img>.
        html = render_hero_media({"id": "hm", "images": ["https://x/a.mp4", "https://x/b.jpg"], "autoplay": True}, {"name": "X"}, {})
        self.assertIn("<video", html)
        self.assertIn("autoplay", html)
        self.assertIn("muted", html)
        self.assertIn("<img", html)   # the jpg slide

    def test_non_autoplay_video_shows_controls(self):
        from stripe_link.runtime.html import render_hero_media
        html = render_hero_media({"id": "hm", "images": ["https://x/a.mp4"], "autoplay": False}, {"name": "X"}, {})
        self.assertIn("controls", html)
        self.assertNotIn("autoplay", html)


class HeroMediaCarouselTests(unittest.TestCase):
    def test_multiple_images_render_carousel_chrome(self):
        section = {"id": "hm", "type": "hero_media", "images": ["https://i/a.jpg", "https://i/b.jpg", "https://i/c.jpg"]}
        html = render_hero_media(section, {"name": "X"}, {})
        self.assertIn("sl-hero-carousel", html)
        self.assertIn("data-hero-prev", html)
        self.assertIn("data-hero-next", html)
        self.assertIn("1 / 3", html)          # counter
        self.assertEqual(html.count("data-hero-dot"), 3)

    def test_single_image_has_no_carousel_chrome(self):
        section = {"id": "hm", "type": "hero_media", "images": ["https://i/a.jpg"]}
        html = render_hero_media(section, {"name": "X"}, {})
        self.assertNotIn("sl-hero-carousel", html)
        self.assertNotIn("data-hero-prev", html)


class OfferTypeValidationTests(unittest.TestCase):
    def _offer(self, offer_type):
        return {
            "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "o",
            "name": "X", "product_intent": "transaction", "stripe_mode": "test", "status": "active",
            "offer_type": offer_type, "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
            "items": [{"product_id": "p", "price_id": "pr", "quantity": 1}],
        }

    def test_listicle_offer_type_valid(self):
        from stripe_link.domain.documents import validate_offer_document
        validate_offer_document(self._offer("listicle"))

    def test_bad_offer_type_rejected(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(self._offer("carousel"))


class ElementValidationTests(unittest.TestCase):
    def _page(self, section):
        return {
            "schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1", "page_id": "pg",
            "name": "P", "offer_id": "off", "route": {"slug": "p"},
            "theme": {"template": "universal_bundle"}, "sections": [section],
        }

    def test_valid_testimonials_pass(self):
        validate_page_document(self._page({"id": "t", "type": "testimonials", "items": [{"quote": "Great"}]}))

    def test_testimonial_without_quote_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self._page({"id": "t", "type": "testimonials", "items": [{"author": "x"}]}))

    def test_rating_out_of_range_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self._page({"id": "r", "type": "rating", "value": 9}))

    def test_marquee_logo_requires_image(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self._page({"id": "m", "type": "client_marquee", "logos": [{"name": "x"}]}))


if __name__ == "__main__":
    unittest.main()
