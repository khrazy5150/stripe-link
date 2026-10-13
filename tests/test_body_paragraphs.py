"""Body copy renders as paragraphs.

Reported 2026-10-13 against a live Author Bio that came out as one unreadable run-on block. It was not a
missing feature: every body field is a `<textarea>`, so the tenant's blank lines were ALREADY stored, and
the renderer dropped them -- `<p>{escape(body)}</p>` is a single element, and HTML collapses the newlines
inside it to spaces. The stored copy had 3 blank-line breaks and 0 stray newlines.

That measurement is why a blank line is the mechanism rather than a marker like `##`: the tenants' text
already carries it, so nothing has to be re-typed, and it is what a writer presses by reflex.
"""
import re
import unittest

from stripe_link.runtime.html import (
    render_author_bio,
    render_body_markup,
    render_content_blocks,
    render_headline_markup,
)

BIO = ("Chase isn't just another guy.\n\n"
       "While everyone else is still trying to go viral, Chase built a system.\n\n"
       "This Wednesday he breaks it down.")


def paragraphs(html):
    return re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)


class ABlankLineStartsAParagraph(unittest.TestCase):
    def test_three_breaks_make_four_paragraphs(self):
        self.assertEqual(len(paragraphs(render_body_markup("a\n\nb\n\nc\n\nd"))), 4)

    def test_the_reported_bio_is_no_longer_one_block(self):
        rendered = render_author_bio({"id": "ab", "body": BIO})
        self.assertEqual(len(paragraphs(rendered)), 3)
        self.assertNotIn("guy. While", rendered, "that run-on is the bug")

    def test_runs_of_blank_lines_do_not_make_empty_paragraphs(self):
        self.assertEqual(len(paragraphs(render_body_markup("a\n\n\n\n\nb"))), 2)

    def test_whitespace_only_lines_count_as_blank(self):
        """A textarea collects the stray spaces an invisible 'empty' line leaves behind."""
        self.assertEqual(len(paragraphs(render_body_markup("a\n   \nb"))), 2)

    def test_text_with_no_breaks_is_still_one_paragraph(self):
        self.assertEqual(len(paragraphs(render_body_markup("one continuous thought"))), 1)

    def test_empty_body_renders_nothing(self):
        for value in ("", None, "   ", "\n\n"):
            with self.subTest(value=value):
                self.assertEqual(render_body_markup(value), "")


class ASingleNewlineIsALineBreak(unittest.TestCase):
    """In a plain textarea what you typed is what you should get; collapsing it is how the run-on
    happened in the first place."""

    def test_it_renders_a_br_inside_one_paragraph(self):
        html = render_body_markup("first line\nsecond line")
        self.assertEqual(len(paragraphs(html)), 1)
        self.assertIn("first line<br>second line", html)

    def test_carriage_returns_do_not_produce_stray_breaks(self):
        self.assertEqual(render_body_markup("a\r\n\r\nb"), render_body_markup("a\n\nb"))


class TheInlineMarkersWorkHereToo(unittest.TestCase):
    """A tenant who learns `**` in a headline should not find it printing literally in a bio."""

    def test_emphasis_and_highlight_render(self):
        html = render_body_markup("a **bold** and a ^^marked^^ word")
        self.assertIn('<span class="sl-mark-text">bold</span>', html)
        self.assertIn('<span class="sl-mark-bg">marked</span>', html)

    def test_body_is_not_title_cased(self):
        """Title casing belongs to headings. Prose wants the sentence case it was written in."""
        self.assertIn("a quiet little sentence", render_body_markup("a quiet little sentence"))
        self.assertIn("Quiet Little Sentence", render_headline_markup("a quiet little sentence"))

    def test_a_marker_never_spans_a_paragraph_break(self):
        html = render_body_markup("an **unclosed\n\nmarker** here")
        self.assertNotIn("sl-mark-text", html)
        self.assertIn("**unclosed", html.replace("&quot;", '"'))

    def test_the_markup_is_still_escaped(self):
        self.assertIn("&lt;script&gt;", render_body_markup("<script>alert(1)</script>"))

    def test_both_renderers_share_one_parser(self):
        """Two copies would let headings and body drift apart."""
        source = (__import__("pathlib").Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text()
        self.assertEqual(source.count('<span class=\\"sl-mark-text\\">'), 1)


class TheParagraphsAreActuallySpaced(unittest.TestCase):
    """Every body class sets `margin:0`, so paragraphs would otherwise stack flush and read as a run-on
    again -- the bug, with more elements."""

    def test_each_paragraph_is_marked(self):
        self.assertEqual(render_body_markup("a\n\nb").count('class="sl-para"'), 2)

    def test_the_existing_class_is_kept_alongside_it(self):
        html = render_body_markup("a\n\nb", "sl-author-body")
        self.assertEqual(html.count('class="sl-author-body sl-para"'), 2)

    def test_the_spacing_rule_exists_and_outranks_the_margin_resets(self):
        from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES
        css = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-para + .sl-para{margin-top:", css)
        for reset in (".sl-author-body{margin:0", ".sl-ribbon-body{margin:0", ".sl-quote-text{margin:0"):
            with self.subTest(rule=reset):
                self.assertIn(reset, css)   # one class each, so the two-class rule above wins


class EveryProseFieldGotIt(unittest.TestCase):
    def test_the_content_block_body(self):
        html = render_content_blocks({"blocks": [{"title": "T", "text": "a\n\nb"}]})
        self.assertEqual(len(paragraphs(html)), 2)

    def test_a_quote_keeps_its_blockquote_wrapper(self):
        from stripe_link.runtime.html import render_quote
        html = render_quote({"id": "q", "text": "a\n\nb"})
        self.assertIn("<blockquote", html)
        self.assertEqual(len(paragraphs(html)), 2)

    def test_the_carousel_bound_description_is_left_alone(self):
        """`data-conversion-bind` fields are rewritten with `el.textContent` on every swipe, so paragraphs
        there would be flattened on the first tap. They stay single-element on purpose."""
        source = (__import__("pathlib").Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text()
        bound = re.search(r'<p class=\\"sl-details-desc\\" data-conversion-bind[^\n]*', source)
        self.assertIsNotNone(bound)
        self.assertIn("escape(description)", bound.group(0))


if __name__ == "__main__":
    unittest.main()
