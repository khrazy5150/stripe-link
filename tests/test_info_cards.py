"""Info cards: titled points that each carry their own explanation.

The author: "Info cards allow tenants to create quick, relevant points in a sequence. They are better than
the numbered list, which are meant to be just that: a list."

Kept apart from numbered_list rather than grown out of it. That element's items are plain STRINGS and its
whole argument is that it is a list — a real <ol> whose order is the content. Turning its items into
objects would migrate every existing page to say something it does not mean.

Two presentations from the author's two references, in one element:
  numbered  — auto-numbered, title in a narrow column, body beside it
  labelled  — an authored eyebrow ("TOOL 01") above a bigger title, body underneath
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_info_cards

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
CSS = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
FIXTURE = ROOT / "schemas" / "examples" / "page-creatine-standard.json"


def page(section):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["sections"] = [{"type": "info_cards", "id": "ic", **section}]
    return doc


def cards(**section):
    section.setdefault("items", [{"title": "A"}, {"title": "B"}])
    return render_info_cards({"id": "ic", **section})


class ItRendersTheCards(unittest.TestCase):
    def test_each_item_is_a_card(self):
        self.assertEqual(cards().count('<li class="sl-info-card'), 2)

    def test_an_item_with_neither_title_nor_body_is_dropped(self):
        html = cards(items=[{"title": "A"}, {"label": "orphan"}])
        self.assertEqual(html.count('<li class="sl-info-card'), 1)
        self.assertNotIn("orphan", html)

    def test_nothing_usable_renders_nothing(self):
        for items in ([], None, [{}], [{"title": "  "}]):
            with self.subTest(items=items):
                self.assertEqual(render_info_cards({"items": items}), "")

    def test_the_card_title_is_an_h3_under_the_section_h2(self):
        html = cards(heading="What you'll learn")
        self.assertIn('<h2 class="sl-info-heading">', html)
        self.assertIn('<h3 class="sl-info-title">', html)

    def test_it_is_capped(self):
        from stripe_link.runtime.html import INFO_CARDS_MAX
        html = cards(items=[{"title": f"C{i}"} for i in range(INFO_CARDS_MAX + 4)])
        self.assertEqual(html.count('<li class="sl-info-card'), INFO_CARDS_MAX)


class TheSequenceIsInTheMarkupOnlyWhenItIsReal(unittest.TestCase):
    """An <ol> is a claim about order. Numbered cards make it; a labelled set does not."""

    def test_numbered_uses_an_ordered_list(self):
        self.assertIn("<ol class=\"sl-info-cards\">", cards(presentation="numbered"))

    def test_labelled_uses_an_unordered_list(self):
        html = cards(presentation="labelled")
        self.assertIn("<ul class=\"sl-info-cards\">", html)
        self.assertNotIn("<ol", html)

    def test_numbered_is_the_default(self):
        self.assertIn("is-numbered", cards())

    def test_an_unknown_presentation_falls_back_rather_than_breaking(self):
        self.assertIn("is-numbered", cards(presentation="chartreuse"))


class TheNumberIsNeverAuthored(unittest.TestCase):
    """A stored number strands itself the first time the cards are reordered."""

    def test_the_glyph_comes_from_a_css_counter(self):
        self.assertIn("counter-increment:sl-info", CSS)
        self.assertIn("content:counter(sl-info)", CSS)

    def test_the_counter_element_carries_no_text(self):
        html = cards(presentation="numbered")
        self.assertIn('class="sl-info-label sl-info-count" aria-hidden="true"></p>', html)

    def test_an_authored_label_replaces_the_number(self):
        html = cards(presentation="numbered", items=[{"label": "STEP ONE", "title": "A"}])
        self.assertIn("STEP ONE", html)
        self.assertNotIn("sl-info-count", html)

    def test_labelled_never_shows_a_counter(self):
        self.assertNotIn("sl-info-count", cards(presentation="labelled"))


class TheExtrasAreWeightNotMeaning(unittest.TestCase):
    def test_the_badge_renders_as_a_sticker(self):
        html = cards(items=[{"title": "A", "badge": "sells from: $990"}])
        self.assertIn('class="sl-info-badge"', html)
        self.assertIn("sells from: $990", html)

    def test_the_badge_is_hidden_from_screen_readers(self):
        """It repeats an aside the body states, and meeting it before the title reads as noise."""
        self.assertIn('class="sl-info-badge" aria-hidden="true"', cards(items=[{"title": "A", "badge": "x"}]))

    def test_the_badge_uses_the_tenants_own_highlight_colours(self):
        """The same ^^highlight^^ tokens the Appearance panel already exposes, not a hardcoded yellow."""
        rule = next(r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES if isinstance(r, str) and ".sl-info-badge{" in r)
        self.assertIn("var(--sl-highlight-bg)", rule)
        self.assertIn("var(--sl-highlight-bg-text)", rule)

    def test_featured_outlines_the_card_and_changes_nothing_else(self):
        html = cards(items=[{"title": "A", "featured": True}])
        self.assertIn("sl-info-card is-featured", html)
        rule = next(r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES if isinstance(r, str) and "is-featured{" in r)
        self.assertIn("border-color:var(--sl-accent)", rule)

    def test_no_badge_means_no_empty_sticker(self):
        self.assertNotIn("sl-info-badge", cards())


class TheBodyIsRealProse(unittest.TestCase):
    def test_a_blank_line_starts_a_new_paragraph(self):
        html = cards(items=[{"title": "A", "body": "First thought.\n\nWho buys it: everyone."}])
        self.assertEqual(len(re.findall(r'<p class="sl-info-body sl-para">', html)), 2)

    def test_the_inline_markers_work_here_too(self):
        html = cards(items=[{"title": "A", "body": "a **marked** word"}])
        self.assertIn('<span class="sl-mark-text">marked</span>', html)

    def test_a_card_may_be_a_title_alone(self):
        """The numbered style is built for one-line points."""
        html = cards(items=[{"title": "Just a point"}])
        self.assertIn("Just a Point", html)
        self.assertNotIn("sl-info-body", html)


class TheTwoColumnSplitOnlyAppliesWhereItFits(unittest.TestCase):
    def test_the_grid_is_behind_a_min_width(self):
        """On a phone three columns become three strips a few characters wide."""
        rule = next(r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                    if isinstance(r, str) and "is-numbered .sl-info-card{grid-template-columns" in r)
        self.assertIn("@media (min-width:", rule)


class ItIsRegisteredAndValidated(unittest.TestCase):
    def test_catalog_entry(self):
        spec = RULES["elements"]["info_cards"]
        self.assertEqual(spec["ui"], "add")
        self.assertFalse(spec["repeatable"])

    def test_it_sits_next_to_the_element_it_is_not(self):
        order = RULES["default_order"]
        self.assertEqual(order.index("info_cards"), order.index("numbered_list") + 1)

    def test_numbered_list_items_are_still_plain_strings(self):
        """The reason this is a separate element. If this ever fails, the two have merged."""
        from stripe_link.runtime.html import render_numbered_list
        self.assertIn("One", render_numbered_list({"items": ["One", "Two"]}))

    def test_a_minimal_block_validates(self):
        validate_page_document(page({"items": [{"title": "A"}]}))

    def test_a_card_needs_a_title(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"items": [{"body": "no title"}]}))

    def test_an_unknown_presentation_is_refused_on_save(self):
        """Degrading at render is for documents that already exist; a new save should be refused."""
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"presentation": "chartreuse", "items": [{"title": "A"}]}))

    def test_the_builder_round_trips_every_field(self):
        for fragment in ('type === "info_cards"', 'element.type === "info_cards"',
                         'section.type === "info_cards"', "element.presentation",
                         "item.badge", "item.featured", "item.label"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, BUILDER)


if __name__ == "__main__":
    unittest.main()
