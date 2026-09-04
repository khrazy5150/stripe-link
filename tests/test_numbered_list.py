"""Numbered List — a heading plus an ordered list of authored lines (plans/LANDING_ELEMENTS_UNIT.md).

ONE element for benefits AND how-it-works steps. The only thing separating those uses is the heading the
tenant types, which is content rather than structure — two visually identical elements would just make a
tenant guess which to pick. Named for its shape so neither framing is privileged.

The ordering lives in a real <ol>, not only in the styling: the visible badge is a CSS counter, so the
number is never selectable text and never duplicates what assistive technology already announces.
"""

import re
import unittest

from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_numbered_list

CSS = "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
LIST = {
    "id": "nl",
    "heading": "What's Inside The Course",
    "items": [
        "Learn All About Successful Social Media Marketing",
        "Implement the Knowledge for Yourself or Your Business",
        "Understand Secrets Behind Successful Influencers",
    ],
}


def texts(html):
    return re.findall(r'class="sl-numbered-text">([^<]*)<', html)


class RenderTests(unittest.TestCase):
    def test_renders_every_line_in_order(self):
        self.assertEqual(texts(render_numbered_list(LIST)), LIST["items"])

    def test_uses_a_real_ordered_list(self):
        html = render_numbered_list(LIST)
        self.assertIn("<ol", html)
        self.assertEqual(html.count("<li"), 3)

    def test_the_number_is_a_css_counter_not_content(self):
        # If the digits were in the markup they would be selectable, and a screen reader would hear the
        # position twice — once from the <ol>, once from the text.
        html = render_numbered_list(LIST)
        self.assertNotIn(">1<", html)
        self.assertIn("counter-increment:sl-num", CSS)
        self.assertIn("content:counter(sl-num)", CSS)

    def test_blank_lines_are_dropped(self):
        html = render_numbered_list({**LIST, "items": ["Real line", "   ", "", "Another"]})
        self.assertEqual(texts(html), ["Real line", "Another"])

    def test_no_lines_renders_nothing(self):
        self.assertEqual(render_numbered_list({"id": "nl", "heading": "Empty"}), "")
        self.assertEqual(render_numbered_list({"id": "nl", "items": ["", "  "]}), "")

    def test_capped_at_twelve_as_the_legacy_is(self):
        html = render_numbered_list({**LIST, "items": [f"Line {n}" for n in range(20)]})
        self.assertEqual(html.count("<li"), 12)

    def test_heading_is_an_h2_and_takes_headline_markup(self):
        html = render_numbered_list({**LIST, "heading": "What's **Inside**"})
        self.assertIn("<h2", html)
        self.assertNotIn("**", html)

    def test_heading_is_optional(self):
        self.assertNotIn("<h2", render_numbered_list({"id": "nl", "items": ["Just a line"]}))

    def test_lines_are_escaped(self):
        html = render_numbered_list({"id": "nl", "items": ["<script>x</script>", "a & b"]})
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)


class NotTheOtherElementsTests(unittest.TestCase):
    """Checked rather than assumed: this is neither an FAQ nor product details."""

    def test_the_lines_are_flat_not_expandable(self):
        # faq is Q&A the visitor opens; this is a list they read.
        html = render_numbered_list(LIST)
        self.assertNotIn("<details", html)
        self.assertNotIn("<summary", html)

    def test_it_carries_authored_copy_not_product_data(self):
        # product_details renders a gallery and badges from the PRODUCT; this takes only what was typed.
        html = render_numbered_list(LIST)
        self.assertNotIn("<img", html)


class NarrowViewportTests(unittest.TestCase):
    def test_the_section_and_the_text_column_are_both_bounded(self):
        # Same trap as the other elements: an unbounded track sizes to max-content and a long unbroken
        # line would widen the whole page on a phone.
        self.assertIn(".sl-numbered-list{display:grid;grid-template-columns:minmax(0,1fr)", CSS)
        self.assertIn("grid-template-columns:auto minmax(0,1fr)", CSS)


if __name__ == "__main__":
    unittest.main()
