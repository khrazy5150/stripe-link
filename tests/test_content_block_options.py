"""What a content block requires, and what it merely offers.

Two relaxations, both so the element can be what a landing page actually needs it to be: a plain
paragraph.

The author: "I think we should be flexible and allow simple paragraphs to be added without a title or a
headline." The content block is the only element that puts a plain paragraph on a page, and the validator
demanded a heading for one -- so a tenant who wanted a paragraph had to invent a title or go without the
paragraph. Nothing else enforced it: the builder's own collapsed-row summary already had a branch for a
title-less block, and no JSON schema mentions it.

`text` stays required. It is what makes the block a content block, and dropping it would allow a section
that renders an empty <article>.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import render_content_blocks

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
FIXTURE = ROOT / "schemas" / "examples" / "page-creatine-standard.json"


def page(block):
    """A REAL page with the block swapped in, so a pass cannot come from an incomplete fixture."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["sections"] = [{"type": "content_block", "id": "cb", "blocks": [block]}]
    return document


class TheTitleIsOptional(unittest.TestCase):
    def test_a_block_with_only_text_validates(self):
        validate_page_document(page({"text": "Just a paragraph."}))

    def test_an_empty_title_validates(self):
        """The builder sends "" for a field the tenant cleared, not a missing key."""
        validate_page_document(page({"title": "", "text": "Just a paragraph."}))

    def test_a_title_is_still_accepted(self):
        validate_page_document(page({"title": "A heading", "text": "Body."}))

    def test_a_non_string_title_is_still_rejected(self):
        """Optional does not mean unvalidated."""
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"title": 7, "text": "Body."}))

    def test_text_is_still_required(self):
        """Without it the block renders an empty <article>."""
        with self.assertRaises(DocumentValidationError) as caught:
            validate_page_document(page({"title": "A heading"}))
        self.assertIn("text", str(caught.exception))


class NoTitleMeansNoHeading(unittest.TestCase):
    """An empty <h2> is a hole in the page outline (plans/SEMANTIC_HTML.md) and reads as a blank line to a
    screen reader -- worse than the heading simply not being there."""

    def test_the_h2_is_omitted_entirely(self):
        html = render_content_blocks({"blocks": [{"text": "Just a paragraph."}]})
        self.assertNotIn("<h2", html)
        self.assertIn("Just a paragraph.", html)

    def test_a_whitespace_only_title_counts_as_absent(self):
        self.assertNotIn("<h2", render_content_blocks({"blocks": [{"title": "   ", "text": "x"}]}))

    def test_a_real_title_still_renders_its_heading(self):
        self.assertIn("<h2>A Heading</h2>", render_content_blocks({"blocks": [{"title": "A heading", "text": "x"}]}))

    def test_the_paragraphs_still_work_without_a_title(self):
        html = render_content_blocks({"blocks": [{"text": "one\n\ntwo"}]})
        self.assertEqual(len(re.findall(r"<p[^>]*>", html)), 2)

    def test_an_omitted_part_leaves_no_blank_line(self):
        html = render_content_blocks({"blocks": [{"text": "x"}]})
        self.assertNotIn("\n\n", html, "empty rows used to be joined in as blank lines")


class TheDividingLineIsOptIn(unittest.TestCase):
    """It used to be automatic: `.sl-content-block` carried `border-top`, so every block drew a rule above
    itself. With a title now optional, the common block is a plain paragraph, and a line over every
    paragraph reads as a document rather than a landing page. The author asked for it to work like
    "Center this block" -- off by default, on when ticked."""

    def test_no_line_by_default(self):
        html = render_content_blocks({"blocks": [{"text": "x"}]})
        self.assertNotIn("sl-content-blocks--divided", html)

    def test_the_flag_turns_it_on(self):
        html = render_content_blocks({"divider": True, "blocks": [{"text": "x"}]})
        self.assertIn("sl-content-blocks--divided", html)

    def test_it_composes_with_centered(self):
        """Two independent axes; ticking one must not cancel the other."""
        html = render_content_blocks({"divider": True, "centered": True, "blocks": [{"text": "x"}]})
        self.assertIn("sl-content-blocks--centered", html)
        self.assertIn("sl-content-blocks--divided", html)

    def test_the_border_moved_to_the_opt_in_rule(self):
        from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES
        css = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-content-blocks--divided .sl-content-block{border-top:", css)
        base = [r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                if isinstance(r, str) and r.strip().startswith(".sl-content-block{")]
        self.assertEqual(len(base), 1)
        self.assertNotIn("border-top", base[0], "the unconditional rule is what drew the line")

    def test_the_document_accepts_and_rejects_it_like_centered(self):
        validate_page_document(page({"text": "x"}))                      # absent
        doc = page({"text": "x"})
        doc["sections"][0]["divider"] = True
        validate_page_document(doc)
        doc["sections"][0]["divider"] = "yes"
        with self.assertRaises(DocumentValidationError):
            validate_page_document(doc)

    def test_the_builder_round_trips_it(self):
        """A flag that saves but does not reload reads to the tenant as "it did not stick"."""
        self.assertIn("Add a dividing line", BUILDER)
        self.assertIn("element.divider ? { divider: true }", BUILDER)
        self.assertIn("divider: Boolean(section.divider)", BUILDER)
        self.assertIn('centered: false, divider: false', BUILDER)


class TheBuilderSaysSo(unittest.TestCase):
    def test_the_field_is_labelled_optional(self):
        self.assertIn('placeholder="Title (optional)"', BUILDER)

    def test_a_titleless_row_is_summarised_by_its_opening_words(self):
        """The collapsed row exists to tell blocks apart; the bare word "text" could not."""
        self.assertIn("excerpt(e.text)", BUILDER)
        self.assertIn("function excerpt(", BUILDER)


if __name__ == "__main__":
    unittest.main()
