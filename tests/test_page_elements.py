"""New composable page elements: testimonials, rating, client_marquee — render + validate."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import (
    render_client_marquee,
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

    def test_marquee_duplicates_row_for_scroll(self):
        html = render_client_marquee({"id": "m", "logos": [
            {"image_url": "https://img/a.png", "name": "Acme"},
            {"image_url": "", "name": "skip"},  # no image dropped
        ]})
        self.assertIn('data-section-type="client_marquee"', html)
        self.assertEqual(html.count("https://img/a.png"), 2)  # duplicated for seamless scroll
        self.assertNotIn("skip", html)


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
