"""New composable page elements: testimonials, rating, client_marquee — render + validate."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import (
    render_client_marquee,
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

    def test_renders_one_slide_per_item_with_cart_attrs(self):
        html = render_listicle_carousel(
            self._listicle(), self._products(), {}, {"tenant_id": "t1", "page_id": "pg"},
            "https://checkout.example.com/pay", "https://api.example.com/dev",
        )
        self.assertIn("data-listicle", html)
        self.assertEqual(html.count("data-cart-item"), 2)
        self.assertIn('data-product-id="p1"', html)     # cart attrs present for L2
        self.assertIn('data-price-id="pr2"', html)
        self.assertIn("$52.01", html)
        self.assertIn("$53.17", html)
        self.assertIn("Briefs", html)


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
