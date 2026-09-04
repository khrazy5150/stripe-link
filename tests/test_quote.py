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

    def test_the_bar_is_the_minimal_signature(self):
        self.assertIn(".sl-quote-minimal .sl-quote-figure{", CSS)
        self.assertIn("border-left:0.5rem solid var(--sl-section-accent", CSS)


class StyleTests(unittest.TestCase):
    """Two presentations of the same content. Minimal is the default, so an existing quote is unchanged."""

    def test_minimal_is_the_default(self):
        for section in (QUOTE, {**QUOTE, "style": ""}, {**QUOTE, "style": "nonsense"}):
            with self.subTest(style=section.get("style")):
                self.assertIn("sl-quote-minimal", render_quote(section))

    def test_fancy_is_opt_in(self):
        html = render_quote({**QUOTE, "style": "fancy"})
        self.assertIn("sl-quote-fancy", html)
        self.assertNotIn("sl-quote-minimal", html)

    def test_only_fancy_wraps_the_words_for_the_quotation_mark(self):
        # The glyph is positioned against the words, not the card, so it stays beside them at any width.
        self.assertIn("sl-quote-body", render_quote({**QUOTE, "style": "fancy"}))
        self.assertNotIn("sl-quote-body", render_quote(QUOTE))

    def test_the_opening_mark_adapts_to_the_card(self):
        # currentColor at low opacity, NOT the reference design's fixed blue — the card colour is the
        # tenant's, so a hardcoded glyph colour would eventually land on a background it cannot be seen on.
        self.assertIn(".sl-quote-fancy .sl-quote-body::before{content:'\\201C'", CSS)
        self.assertNotIn("#81bedb", CSS)


class OptionalFieldsTests(unittest.TestCase):
    def test_title_is_optional_and_becomes_a_heading(self):
        self.assertNotIn("sl-quote-title", render_quote(QUOTE))
        self.assertIn('<h2 class="sl-quote-title">', render_quote({**QUOTE, "title": "What We Believe"}))

    def test_title_takes_headline_markup(self):
        self.assertNotIn("**", render_quote({**QUOTE, "title": "Why **Us**"}))

    def test_image_is_optional(self):
        self.assertNotIn("sl-quote-photo", render_quote(QUOTE))
        self.assertIn("sl-quote-photo", render_quote({**QUOTE, "image_url": "https://img/g.jpg"}))

    def test_image_alt_falls_back_when_there_is_no_attribution(self):
        html = render_quote({"id": "q", "text": "Ship it.", "image_url": "https://img/g.jpg"})
        self.assertIn('alt="Quote"', html)

    def test_the_image_appears_in_both_styles(self):
        for presentation in ("minimal", "fancy"):
            with self.subTest(style=presentation):
                html = render_quote({**QUOTE, "style": presentation, "image_url": "https://img/g.jpg"})
                self.assertIn("sl-quote-photo", html)


class SectionOverrideTests(unittest.TestCase):
    def test_default_follows_the_preset(self):
        html = render_quote(QUOTE)
        self.assertNotIn("--sl-section-bg", html)
        self.assertNotIn("sl-section-themed", html)

    def test_dark_background_derives_light_ink(self):
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", render_quote({**QUOTE, "theme": {"bg": "#1e1033"}}))

    def test_light_background_derives_dark_ink(self):
        self.assertIn(f"--sl-section-ink:{DARK_INK}", render_quote({**QUOTE, "theme": {"bg": "#fef3c7"}}))

    def test_the_accent_paints_the_bar_in_minimal_and_the_card_in_fancy(self):
        # One token, two surfaces — which is why the derived ink matters more in fancy, where text sits ON it.
        html = render_quote({**QUOTE, "theme": {"bg": "#1e1033", "accent": "#f97316"}})
        self.assertIn("--sl-section-accent:#f97316", html)
        self.assertIn("var(--sl-section-accent,var(--sl-accent))", CSS)

    def test_the_fancy_card_text_is_derived_never_hardcoded(self):
        # The reference design is white-on-pink. That must come out of the contrast maths, so a PALE card
        # gets dark text instead of the same white the reference happened to use.
        self.assertIn("color:var(--sl-section-accent-ink,var(--sl-cta-text,#fff))", CSS)
        dark_card = render_quote({**QUOTE, "style": "fancy", "theme": {"bg": "#ffffff", "accent": "#d6336c"}})
        pale_card = render_quote({**QUOTE, "style": "fancy", "theme": {"bg": "#ffffff", "accent": "#fde68a"}})
        self.assertIn(f"--sl-section-accent-ink:{LIGHT_INK}", dark_card)
        self.assertIn(f"--sl-section-accent-ink:{DARK_INK}", pale_card)


class NarrowViewportTests(unittest.TestCase):
    def test_the_fancy_card_stacks_without_a_breakpoint(self):
        # flex-wrap with a basis on each part: the photo and the words stack themselves when the card is
        # too narrow, so the element survives a phone with no media query of its own.
        self.assertIn("flex-wrap:wrap", CSS)
        self.assertIn(".sl-quote-fancy .sl-quote-photo{flex:1 1 18rem", CSS)
        self.assertIn(".sl-quote-fancy .sl-quote-body{flex:3 1 24rem;min-width:0", CSS)

    def test_the_section_track_is_bounded(self):
        # Same trap as bragging points: justify-items:center leaves an auto track, an auto track sizes to
        # max-content, and a long unbroken line would then widen the whole page on a phone.
        self.assertIn(".sl-quote{display:grid;grid-template-columns:minmax(0,1fr)", CSS)


if __name__ == "__main__":
    unittest.main()
