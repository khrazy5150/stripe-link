"""New composable page elements: testimonials, rating, client_marquee — render + validate."""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import render_client_marquee, render_rating, render_testimonials


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
