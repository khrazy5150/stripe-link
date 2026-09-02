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
    def test_title_is_one_line_with_an_ellipsis(self):
        body = rule(".product-card-heading h3")
        self.assertIn("text-overflow: ellipsis", body)
        self.assertIn("white-space: nowrap", body)
        self.assertIn("overflow: hidden", body)

    def test_title_has_min_width_zero(self):
        # Without it a flex item's automatic minimum size is its content, so a long title pushes the
        # status badge out of the card instead of truncating. Same trap as the settings accordion.
        self.assertIn("min-width: 0", rule(".product-card-heading h3"))


class FullTextRemainsReachableTests(unittest.TestCase):
    def test_clamped_text_is_carried_on_the_title_attribute(self):
        # Clamping may hide characters; it must not hide information.
        self.assertIn(':title="title"', CARD)
        self.assertIn(':title="description"', CARD)


if __name__ == "__main__":
    unittest.main()
