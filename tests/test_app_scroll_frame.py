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

    def test_the_sidebar_scrolls_itself(self):
        # Bounded by the frame now, and the nav is long enough to overflow a short viewport.
        self.assertIn("overflow-y: auto", rule(".sidebar"))

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


class SelfScrollingScreensTests(unittest.TestCase):
    def test_only_converted_screens_opt_in(self):
        """A view listed here BEFORE its layout is converted gets clipped: .owns-scroll stops the view
        scrolling, and an unconverted screen has no scroll of its own. Caught while writing this."""
        match = re.search(r"SELF_SCROLLING_VIEWS = new Set\(\[([^\]]*)\]\)", APP)
        self.assertIsNotNone(match)
        listed = {v.strip().strip('"\'') for v in match.group(1).split(",") if v.strip()}
        self.assertEqual(listed, {"products"}, "add a view only once its layout is a flex column")

    def test_the_opted_in_screen_scrolls_its_list_not_the_page(self):
        self.assertIn("overflow: hidden", rule(".app-view.owns-scroll"))
        body = rule(".app-view.owns-scroll .product-card-list")
        self.assertIn("overflow-y: auto", body)
        self.assertIn("min-height: 0", body)
        self.assertIn("scrollbar-gutter: stable", body)

    def test_the_list_is_keyboard_reachable(self):
        # A scroll container that only answers the mouse wheel is unusable without a pointer.
        self.assertIn('class="product-card-list" tabindex="0"', PRODUCTS)

    def test_unconverted_screens_are_untouched(self):
        # Every self-scrolling rule is scoped under .owns-scroll, so the other 22 screens keep the plain
        # .app-view scroll they had.
        for selector in (".app-view.owns-scroll .page", ".app-view.owns-scroll .product-card-list"):
            with self.subTest(selector=selector):
                self.assertTrue(rule(selector), f"{selector} missing")
        self.assertNotIn("overflow-y: auto", rule(".page"))


if __name__ == "__main__":
    unittest.main()
