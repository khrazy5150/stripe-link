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


class SelfScrollingScreensTests(unittest.TestCase):
    def test_every_opted_in_view_has_marked_its_chain(self):
        """A view listed here BEFORE its layout is marked gets clipped: .owns-scroll stops the view
        scrolling, and an unmarked screen has no scroll of its own. So the opt-in list and the marked
        components must agree — this asserts they do, rather than trusting that they will."""
        match = re.search(r"SELF_SCROLLING_VIEWS = new Set\(\[([^\]]*)\]\)", APP)
        self.assertIsNotNone(match)
        listed = {v.strip().strip('"\'') for v in match.group(1).split(",") if v.strip()}
        self.assertEqual(listed, {"products", "services", "offers"})

        components = {"products": "Products.vue", "services": "Services.vue", "offers": "Offers.vue"}
        for view, filename in components.items():
            source = (ROOT / "dashboard" / "src" / "components" / filename).read_text(encoding="utf-8")
            with self.subTest(view=view):
                self.assertIn("scroll-column", source, f"{filename} must mark its column chain")
                self.assertIn("scroll-region", source, f"{filename} must mark its scrolling list")

    def test_landing_pages_is_deliberately_not_converted(self):
        # Its list card is v-if="!builderOpen" and the builder is a different two-pane layout that needs
        # the view to scroll normally. Recorded so it is not "fixed" by adding it to the set.
        match = re.search(r"SELF_SCROLLING_VIEWS = new Set\(\[([^\]]*)\]\)", APP)
        self.assertNotIn("landingPages", match.group(1))
        source = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertNotIn("scroll-region", source)

    def test_the_marked_region_scrolls_not_the_page(self):
        self.assertIn("overflow: hidden", rule(".app-view.owns-scroll"))
        body = rule(".app-view.owns-scroll .scroll-region")
        self.assertIn("overflow-y: auto", body)
        self.assertIn("min-height: 0", body)
        self.assertIn("scrollbar-gutter: stable", body)

    def test_the_chain_is_marked_rather_than_assumed(self):
        # The first version hard-coded ".page > .dashboard-card > .product-card-list", which collapsed
        # Offers — its list sits one level deeper inside .offer-card-body.
        self.assertIn(".scroll-column", CSS)
        self.assertNotIn(".app-view.owns-scroll .page > .dashboard-card > :not(", CSS)

    def test_every_scroll_region_is_keyboard_reachable(self):
        # A scroll container that only answers the mouse wheel is unusable without a pointer.
        for filename in ("Products.vue", "Services.vue", "Offers.vue"):
            source = (ROOT / "dashboard" / "src" / "components" / filename).read_text(encoding="utf-8")
            with self.subTest(component=filename):
                self.assertIn('scroll-region" tabindex="0"', source)

    def test_unconverted_screens_are_untouched(self):
        # Every self-scrolling rule is scoped under .owns-scroll, so the other 22 screens keep the plain
        # .app-view scroll they had.
        for selector in (".app-view.owns-scroll .scroll-region",):
            with self.subTest(selector=selector):
                self.assertTrue(rule(selector), f"{selector} missing")
        self.assertNotIn("overflow-y: auto", rule(".page"))


if __name__ == "__main__":
    unittest.main()
