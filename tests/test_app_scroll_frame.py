"""The app shell is a fixed-height frame with exactly one scrolling region.

Chosen over window-scroll virtualization: giving the list its own `overflow-y: auto` makes windowing
simple, and the usual objection — two competing scrollbars — is removed by fixing the shell's height so
the page itself never scrolls.

CSS is not covered by the renderer tests, so this reads the stylesheet and App.vue directly. Crude, but
these are rules whose absence produces an unreachable UI rather than an error.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")


def rule(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return match.group(1) if match else ""


class ShellFrameTests(unittest.TestCase):
    def test_shell_is_a_fixed_height_frame(self):
        body = rule(".app-shell")
        self.assertIn("100dvh", body, "dvh, so mobile browser chrome collapsing does not clip the last row")
        self.assertIn("overflow: hidden", body)

    def test_the_grid_row_is_bounded(self):
        """The bug the first version shipped with: .app-shell is a grid, and with no explicit row the
        implicit one is `auto` and sizes to content — so main grew past 100dvh, nothing needed to scroll,
        and overflow:hidden clipped the list with its buttons unreachable. minmax(0, 1fr) rather than 1fr,
        because 1fr carries an automatic minimum of `auto`."""
        body = rule(".app-shell")
        self.assertIn("grid-template-rows", body)
        self.assertIn("minmax(0, 1fr)", body.split("grid-template-rows")[1])

    def test_the_brand_stays_pinned_and_only_the_nav_scrolls(self):
        """First version scrolled the whole aside, which carried the logo off the top — it read as a bug.
        The sidebar mirrors main: a fixed header and one scrolling region beneath it."""
        aside = rule(".sidebar")
        self.assertIn("flex-direction: column", aside)
        self.assertIn("overflow: hidden", aside, "the aside itself must not scroll")
        self.assertIn("flex: none", rule(".sidebar > .brand"))
        nav = rule(".sidebar > nav")
        self.assertIn("overflow-y: auto", nav)
        self.assertIn("min-height: 0", nav)
        self.assertIn("overscroll-behavior: contain", nav)

    def test_main_can_actually_shrink(self):
        # Without min-height:0 a flex item's automatic minimum size is its content, so the scroll region
        # grows the frame instead of scrolling inside it.
        self.assertIn("min-height: 0", rule("main"))

    def test_one_scroll_region_with_a_stable_gutter(self):
        body = rule(".app-view")
        self.assertIn("overflow-y: auto", body)
        self.assertIn("scrollbar-gutter: stable", body)

    def test_the_topbar_does_not_shrink(self):
        self.assertIn("flex: none", rule(".topbar"))


class NoScreenOptsOutTests(unittest.TestCase):
    """The per-screen self-scrolling experiment was reverted; .app-view is the one scroll region.

    Tried on Products, Services and Offers and reverted all three (2026-09-02). The pattern assumed a
    screen was ONE list filling the page: Services also holds FulfillersPanel and the availability panels
    so pinning every child clipped them; Offers stretched into a tall empty box; and on Products it simply
    read worse than the plain page scroll it replaced. plans/LIST_VIRTUALIZATION.md carries the table.
    """

    def test_the_opt_in_machinery_is_gone_not_left_dead(self):
        for token in ("owns-scroll", "viewOwnsScroll", "SELF_SCROLLING_VIEWS"):
            with self.subTest(token=token):
                self.assertNotIn(token, APP)
                self.assertNotIn(token, CSS)

    def test_no_component_still_marks_a_scroll_chain(self):
        components = ROOT / "dashboard" / "src" / "components"
        for filename in ("Products.vue", "Services.vue", "Offers.vue", "LandingPages.vue"):
            source = (components / filename).read_text(encoding="utf-8")
            with self.subTest(component=filename):
                self.assertNotIn("scroll-region", source)
                self.assertNotIn("scroll-column", source)


if __name__ == "__main__":
    unittest.main()
