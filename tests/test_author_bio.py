"""Author Bio — credibility block with an optional pattern break (plans/AUTHOR_BIO.md).

Two properties matter more than the markup:

  * the ORDER is fixed, because it encodes the argument — person, name, why they are worth hearing, proof;
  * a tenant who breaks the page style CANNOT produce unreadable text, because the ink is derived from the
    background they chose rather than inherited from the preset.
"""

import re
import unittest

from stripe_link.domain.section_theme import DARK_INK, LIGHT_INK
from stripe_link.runtime.html import render_author_bio

FULL = {
    "id": "ab",
    "photo_url": "https://img/j.jpg",
    "name": "Jordan Belfort",
    "headline": "Learn From Someone Who's Done **$6M+** In Digital Sales",
    "body": "25 years as a digital marketer.",
}


def order_of(html):
    """The CHILD class names in order, so structure can be asserted rather than eyeballed. Excludes the
    wrapper's own `sl-author-bio`, which is not part of the sequence."""
    return [name for name in re.findall(r'class="(sl-author-[a-z]+)"', html) if name != "sl-author-bio"]


class StructureTests(unittest.TestCase):
    def test_the_order_is_photo_name_headline_body(self):
        # Fixed on purpose: rearranging it breaks the argument the element exists to make.
        self.assertEqual(order_of(render_author_bio(FULL)),
                         ["sl-author-photo", "sl-author-name", "sl-author-headline", "sl-author-body"])

    def test_the_headline_is_an_h2_so_it_joins_the_page_outline(self):
        self.assertIn("<h2 class=\"sl-author-headline\"", render_author_bio(FULL))

    def test_highlight_markup_works_as_it_does_everywhere_else(self):
        # No new parser: render_headline_markup already handles ** and ^^.
        self.assertIn('<span class="sl-mark-text">$6M+</span>', render_author_bio(FULL))

    def test_every_field_is_optional(self):
        html = render_author_bio({"id": "ab", "name": "Jordan"})
        self.assertIn("Jordan", html)
        for absent in ("sl-author-photo", "sl-author-headline", "sl-author-body"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, html)

    def test_an_entirely_empty_section_renders_nothing(self):
        self.assertEqual(render_author_bio({"id": "ab"}), "")

    def test_the_photo_alt_falls_back_when_there_is_no_name(self):
        # An empty alt on a portrait tells a screen reader nothing.
        self.assertIn('alt="Author"', render_author_bio({"id": "ab", "photo_url": "https://img/x.jpg"}))


class PatternBreakTests(unittest.TestCase):
    def test_no_override_means_no_inline_style(self):
        html = render_author_bio(FULL)
        self.assertNotIn("style=", html)
        self.assertNotIn("sl-section-themed", html)

    def test_a_dark_background_gets_light_ink_and_vice_versa(self):
        """The property that makes the break safe. The legacy offers a background picker with no text
        colour, so the ink keeps coming from the preset and a wrong pairing hides the copy silently."""
        dark = render_author_bio({**FULL, "theme": {"bg": "#1e1033"}})
        light = render_author_bio({**FULL, "theme": {"bg": "#fef3c7"}})
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", dark)
        self.assertIn(f"--sl-section-ink:{DARK_INK}", light)

    def test_the_photo_ring_is_overridable_separately(self):
        html = render_author_bio({**FULL, "theme": {"bg": "#1e1033", "border": "#f97316"}})
        self.assertIn("--sl-section-border:#f97316", html)

    def test_the_name_pill_stays_readable_on_a_white_ring(self):
        """Found in review: the pill is painted with the BORDER colour and its text was hardcoded white,
        so a white photo ring made the name vanish — the invisible-text failure, one surface along from
        where it was guarded."""
        html = render_author_bio({**FULL, "theme": {"bg": "#111827", "border": "#ffffff"}})
        self.assertIn(f"--sl-section-border-ink:{DARK_INK}", html)

    def test_an_unparseable_colour_falls_back_to_the_preset(self):
        # Better a themeless section than a section with an unreadable or injected style.
        html = render_author_bio({**FULL, "theme": {"bg": "chartreuse; content:'x'"}})
        self.assertNotIn("style=", html)


if __name__ == "__main__":
    unittest.main()
