"""Bragging Points — quantified proof, standalone (plans/AUTHOR_BIO.md §4a).

It reads as an extension of Author Bio, and it is deliberately NOT one: the same component is the stats
band ("10,000 customers served"), which has no author in it. Welded to the bio, a tenant who wants company
stats and no bio cannot have them, and the stats band gets built a second time.

Two properties carry the element:

  * the VALUE is free text, never a parsed number — the author's own third example is `Q-Media /
    Founder and CEO`;
  * it is the SECOND consumer of the shared section override, so it is the proof that step 0 generalised.
    A tenant colours SURFACES only; every ink is derived, so no colour choice can hide the text.
"""

import re
import unittest

from stripe_link.domain.section_theme import DARK_INK, LIGHT_INK
from stripe_link.runtime.html import render_bragging_points

THREE = {
    "id": "bp",
    "heading": "By The Numbers",
    "items": [
        {"value": "$6M+", "label": "In sales"},
        {"value": "12 yrs", "label": "Experience"},
        {"value": "Q-Media", "label": "Founder and CEO"},
    ],
}


def values(html):
    return re.findall(r'class="sl-brag-value">([^<]*)<', html)


class RenderTests(unittest.TestCase):
    def test_renders_a_card_per_point_in_order(self):
        html = render_bragging_points(THREE)
        self.assertEqual(values(html), ["$6M+", "12 yrs", "Q-Media"])
        self.assertEqual(html.count('class="sl-brag-card"'), 3)

    def test_a_value_is_free_text_not_a_number(self):
        # The third example in the spec is a company name and a job title. Nothing may parse or format it.
        html = render_bragging_points(THREE)
        self.assertIn("Q-Media", html)
        self.assertIn("Founder and CEO", html)

    def test_empty_renders_nothing_at_all(self):
        # A section that renders an empty shell is worse than one that renders nothing.
        self.assertEqual(render_bragging_points({"id": "bp", "items": []}), "")
        self.assertEqual(render_bragging_points({"id": "bp", "items": [{"value": "", "label": ""}]}), "")

    def test_a_point_with_only_one_half_still_counts(self):
        html = render_bragging_points({"id": "bp", "items": [{"value": "40%"}, {"label": "Repeat buyers"}]})
        self.assertEqual(html.count('class="sl-brag-card"'), 2)

    def test_heading_is_an_h2_and_takes_headline_markup(self):
        html = render_bragging_points({**THREE, "heading": "Why **Us**"})
        self.assertIn("<h2", html)
        self.assertNotIn("**", html, "headline markup must be rendered, not printed")

    def test_values_are_escaped(self):
        html = render_bragging_points({"id": "bp", "items": [{"value": "<script>x</script>", "label": "&"}]})
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)

    def test_no_heading_emits_no_empty_heading(self):
        self.assertNotIn("<h2", render_bragging_points({"id": "bp", "items": [{"value": "9"}]}))


class SectionOverrideTests(unittest.TestCase):
    """The point of building this second: it proves the step-0 mechanism generalised rather than fitting
    one element. Bragging Points colours a different surface than Author Bio — cards, not a photo ring —
    and gets the same guarantee without any element-specific contrast code."""

    def test_default_follows_the_preset(self):
        html = render_bragging_points(THREE)
        self.assertNotIn("--sl-section-bg", html)
        self.assertNotIn("sl-section-themed", html)

    def test_a_dark_background_derives_light_ink(self):
        html = render_bragging_points({**THREE, "theme": {"bg": "#111827"}})
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", html)

    def test_a_light_background_derives_dark_ink(self):
        html = render_bragging_points({**THREE, "theme": {"bg": "#fef3c7"}})
        self.assertIn(f"--sl-section-ink:{DARK_INK}", html)

    def test_the_card_surface_gets_its_OWN_derived_ink(self):
        # The value sits on the card, not on the section background. A pale card on a dark section is the
        # exact case that made the author-bio name pill invisible, one surface along.
        html = render_bragging_points({**THREE, "theme": {"bg": "#111827", "accent": "#fbbf24"}})
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", html)
        self.assertIn(f"--sl-section-accent-ink:{DARK_INK}", html)

    def test_the_tenant_never_picks_a_text_colour(self):
        # Every override is a SURFACE. If a text colour were ever accepted here, the derived-ink guarantee
        # would have a hole in it, so this asserts the shape of the contract rather than its output.
        html = render_bragging_points({**THREE, "theme": {"bg": "#111827", "text": "#111827"}})
        self.assertNotIn("--sl-section-text", html)


class NarrowViewportTests(unittest.TestCase):
    """The card grid must never be wider than the phone it is on.

    Found on a 42rem preview pane: `justify-items:center` gives the section an AUTO track, an auto track
    sizes to its child's max-content, and the card grid's max-content is every column at full width. The
    section grew past the viewport and pushed the whole page right — hero and content block included, so it
    read as a page-wide layout fault rather than one element's CSS. `width:100%` on the child cannot fix it,
    because that width resolves against the very track it is inflating.

    Both halves are load-bearing, which is why they are asserted rather than left to review.
    """

    def _css(self):
        from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES
        return "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)

    def test_the_section_track_is_bounded(self):
        css = self._css()
        self.assertIn(".sl-bragging-points{display:grid;grid-template-columns:minmax(0,1fr)", css,
                      "an auto track would size to the card grid's max-content and overflow the viewport")

    def test_auto_fit_columns_never_demand_more_than_the_container(self):
        css = self._css()
        self.assertIn("repeat(auto-fit,minmax(min(22rem,100%),1fr))", css,
                      "a bare minmax(22rem,1fr) overflows instead of collapsing to one column")


if __name__ == "__main__":
    unittest.main()
