"""ListCard must clamp its text, not grow with it.

shared/ListCard.vue is used by Offers, Products and Services. It had `min-width: 0` (which stops a long
unbroken word blowing out the grid) but no line clamp and no ellipsis — so a 500-word product description
simply made a very tall card. The Offers card only looked robust because its CONTENT was capped
(offerItems.itemSummary: 3 names, "+N more", 90-char limit); Products and Services passed raw text.

Uniform row height is also the prerequisite for fixed-height list virtualization: with variable heights
that work needs measuring virtualization, which is markedly harder to get right.

CSS is not exercised by the Python renderer tests, so this reads the stylesheet directly. Crude, but it
guards rules that are easy to delete during an unrelated edit.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
CARD = (ROOT / "dashboard" / "src" / "components" / "shared" / "ListCard.vue").read_text(encoding="utf-8")


def rule(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return match.group(1) if match else ""


class DescriptionClampTests(unittest.TestCase):
    def test_description_is_clamped_to_two_lines(self):
        body = rule(".product-card p")
        self.assertIn("-webkit-line-clamp: 2", body)
        self.assertIn("-webkit-box-orient: vertical", body)
        self.assertIn("display: -webkit-box", body)
        self.assertIn("overflow: hidden", body)

    def test_an_unbreakable_string_cannot_widen_the_card(self):
        # A pasted URL or an id has no break opportunity, so clamping alone would still stretch the card.
        self.assertIn("overflow-wrap: anywhere", rule(".product-card p"))


class TitleTruncationTests(unittest.TestCase):
    def test_title_wraps_to_two_lines_then_clamps(self):
        """Changed from one nowrap line (author, 2026-10-18): a 95-character offer name cut to a single
        line is indistinguishable from the next one. Two lines, then clamp — bounded, so cards stay the
        same height, which is the point of this whole file."""
        body = rule(".product-card-heading h3")
        self.assertIn("-webkit-line-clamp: 2", body)
        self.assertIn("-webkit-box-orient: vertical", body)
        self.assertIn("display: -webkit-box", body)
        self.assertIn("overflow: hidden", body)

    def test_the_title_still_cannot_be_widened_by_one_long_token(self):
        # Wrapping handles spaces; a pasted URL or a slug has no break opportunity and would still escape.
        self.assertIn("overflow-wrap: anywhere", rule(".product-card-heading h3"))

    def test_title_has_min_width_zero(self):
        # Without it a flex item's automatic minimum size is its content, so a long title pushes the
        # status badge out of the card instead of truncating. Same trap as the settings accordion.
        self.assertIn("min-width: 0", rule(".product-card-heading h3"))

    def test_the_heading_ITSELF_has_min_width_zero(self):
        """The half that was missing, and why a title escaped its card anyway: the heading is a GRID ITEM
        of .product-card-body, so its automatic minimum size is its content too. min-width:0 on the h3
        alone leaves the chain broken one level up (found 2026-10-18)."""
        self.assertIn("min-width: 0", rule(".product-card-heading"))


class WarningLegibilityTests(unittest.TestCase):
    def test_no_os_dark_mode_override_repaints_the_price_warning(self):
        """There is no dark theme in this dashboard — nothing ever sets `data-theme` and every panel is
        light. An unguarded `prefers-color-scheme: dark` rule therefore painted amber-300 onto a white
        card: 1.44:1, for text carrying an instruction (found 2026-10-18)."""
        dark_blocks = re.findall(r"@media \(prefers-color-scheme: dark\)\s*\{(.*?)\n\}", CSS, re.S)
        for block in dark_blocks:
            self.assertNotIn("price-context-warning", block)


class FullTextRemainsReachableTests(unittest.TestCase):
    def test_clamped_text_is_carried_on_the_title_attribute(self):
        # Clamping may hide characters; it must not hide information.
        self.assertIn(':title="title"', CARD)
        self.assertIn(':title="description"', CARD)


if __name__ == "__main__":
    unittest.main()
