"""Quote — a pull-quote with a vertical accent bar (plans/LANDING_ELEMENTS_UNIT.md §Quote).

The element carries an IDEA — a maxim, a principle, the tenant's own line. `testimonials` carries a
customer vouching for the product. The obligation that follows is a styling one: a quote must not look
like a testimonial, or it reads as an endorsement nobody actually gave.

It is also the third consumer of the step-0 section override, and the first to use `accent` as a visible
BAR rather than a page background or a card fill.
"""

import unittest

from stripe_link.domain.section_theme import DARK_INK, LIGHT_INK
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_quote

QUOTE = {
    "id": "q",
    "text": "Marketing is no longer about the stuff you make, but the stories you tell.",
    "attribution": "Seth Godin",
}
CSS = "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)


class RenderTests(unittest.TestCase):
    def test_renders_the_quote_and_attribution(self):
        html = render_quote(QUOTE)
        self.assertIn("stories you tell", html)
        self.assertIn("Seth Godin", html)

    def test_no_text_renders_nothing(self):
        self.assertEqual(render_quote({"id": "q", "text": "   "}), "")
        self.assertEqual(render_quote({"id": "q", "attribution": "Nobody"}), "")

    def test_attribution_is_optional(self):
        html = render_quote({"id": "q", "text": "Ship it."})
        self.assertNotIn("figcaption", html)

    def test_a_typed_dash_is_absorbed_not_doubled(self):
        # The dash is presentation. A tenant who types one anyway must not get two.
        for typed in ("— Seth Godin", "- Seth Godin", "– Seth Godin", "—— Seth Godin"):
            with self.subTest(typed=typed):
                html = render_quote({**QUOTE, "attribution": typed})
                self.assertIn("— Seth Godin", html)
                self.assertNotIn("— —", html)
                self.assertNotIn("— - ", html)

    def test_text_is_escaped(self):
        html = render_quote({"id": "q", "text": "<script>x</script>", "attribution": "a & b"})
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)

    def test_attribution_sits_outside_the_blockquote(self):
        # Who said it is ABOUT the quote, not part of what was said — figure/figcaption, not blockquote.
        html = render_quote(QUOTE)
        blockquote = html.split("<blockquote")[1].split("</blockquote>")[0]
        self.assertNotIn("Seth Godin", blockquote)
        self.assertIn("<figcaption", html)


class NotATestimonialTests(unittest.TestCase):
    """The distinction is the reason the element exists, so it is asserted rather than left to review."""

    def test_it_does_not_reuse_testimonial_markup(self):
        html = render_quote(QUOTE)
        self.assertNotIn("sl-testimonial", html)

    def test_the_bar_is_the_signature_and_the_card_border_is_not(self):
        self.assertIn("border-left:0.5rem solid var(--sl-section-accent", CSS)
        # Testimonials are bordered cards with an avatar; the quote has neither.
        self.assertNotIn(".sl-quote-figure{margin:0;width:100%;max-width:62rem;text-align:left;border:", CSS)


class SectionOverrideTests(unittest.TestCase):
    def test_default_follows_the_preset(self):
        html = render_quote(QUOTE)
        self.assertNotIn("--sl-section-bg", html)
        self.assertNotIn("sl-section-themed", html)

    def test_dark_background_derives_light_ink(self):
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", render_quote({**QUOTE, "theme": {"bg": "#1e1033"}}))

    def test_light_background_derives_dark_ink(self):
        self.assertIn(f"--sl-section-ink:{DARK_INK}", render_quote({**QUOTE, "theme": {"bg": "#fef3c7"}}))

    def test_the_bar_takes_the_accent_and_falls_back_to_the_preset(self):
        html = render_quote({**QUOTE, "theme": {"bg": "#1e1033", "accent": "#f97316"}})
        self.assertIn("--sl-section-accent:#f97316", html)
        # Without an override the bar must still be painted, from the page's own accent.
        self.assertIn("var(--sl-section-accent,var(--sl-accent))", CSS)


class NarrowViewportTests(unittest.TestCase):
    def test_the_section_track_is_bounded(self):
        # Same trap as bragging points: justify-items:center leaves an auto track, an auto track sizes to
        # max-content, and a long unbroken line would then widen the whole page on a phone.
        self.assertIn(".sl-quote{display:grid;grid-template-columns:minmax(0,1fr)", CSS)


if __name__ == "__main__":
    unittest.main()
