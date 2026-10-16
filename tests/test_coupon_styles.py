"""Five coupon looks over one markup shape.

Author, 2026-10-15, with four reference designs and "you can keep the original too": Modern (default),
Bold, Ribbon, Dark, Original. *"The coupon color schemes should follow the current theme's color scheme,
but the dark option may remain fixed as is."*

One markup shape and five stylesheets, so a style is a CSS question and the renderer stays a renderer.
The ticket's three custom properties were never assigned, which is why it ignored the preset entirely --
the hardcoded fallbacks WERE the design. They are derived now, and the two styles that are about a
specific look (`dark`, `original`) pin them back.
"""
import json
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.documents import DocumentValidationError, validate_page_document  # noqa: E402
from stripe_link.runtime.html import COUPON_STYLES, TEMPLATE_STYLES, render_coupon, theme_tokens  # noqa: E402

CSS = "\n".join(line for style in TEMPLATE_STYLES.values()
                for line in (style if isinstance(style, (list, tuple)) else [str(style)]))
BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def coupon(**extra):
    return render_coupon({"id": "c", "code": "X", "value_text": "20% off", **extra},
                         {"offer_type": "single", "items": []}, {}, "")


def declared_style(markup):
    return re.search(r'data-coupon-style="([^"]+)"', markup).group(1)


class TheStyleIsDeclaredTests(unittest.TestCase):
    def test_absent_means_modern(self):
        self.assertEqual(declared_style(coupon()), "modern")

    def test_each_style_reaches_the_markup(self):
        for style in COUPON_STYLES:
            with self.subTest(style=style):
                self.assertEqual(declared_style(coupon(style=style)), style)

    def test_an_unknown_style_falls_back_rather_than_rendering_unstyled(self):
        self.assertEqual(declared_style(coupon(style="neon")), "modern")

    def test_the_markup_itself_never_changes(self):
        """One shape, five stylesheets. If a style ever needs different markup, this fails and the design
        is the thing to revisit -- not the renderer."""
        shapes = {re.sub(r' data-coupon-style="[^"]+"', "", coupon(style=style)) for style in COUPON_STYLES}
        self.assertEqual(len(shapes), 1)


class EveryStyleIsActuallyStyledTests(unittest.TestCase):
    def test_each_has_rules(self):
        """A style offered in the picker and absent from the stylesheet is a choice that does nothing."""
        for style in COUPON_STYLES:
            with self.subTest(style=style):
                self.assertIn(f"data-coupon-style='{style}'", CSS)


class TheThemeIsFollowedTests(unittest.TestCase):
    def test_the_ticket_tokens_are_derived_from_the_preset(self):
        for preset in ("clean-slate", "techno-green", "royal-velvet"):
            with self.subTest(preset=preset):
                tokens = theme_tokens({"theme": {"preset": preset}})
                self.assertEqual(tokens["coupon_accent"], tokens["accent"])
                self.assertEqual(tokens["coupon_bg"], tokens["card"])

    def test_the_ink_is_measured_against_the_ticket_ground(self):
        """The ticket paints its own ground, so inheriting --sl-text put white on white for a dark preset
        and erased the value, the code and the headline (found 2026-09-22). The ink is measured, not
        inherited."""
        from stripe_link.domain.section_theme import contrast_ratio

        for preset in ("clean-slate", "techno-green", "midnight-luxe"):
            with self.subTest(preset=preset):
                tokens = theme_tokens({"theme": {"preset": preset}})
                self.assertGreater(contrast_ratio(tokens["coupon_text"], tokens["coupon_bg"]), 4.5)

    def test_dark_pins_its_own_palette(self):
        """Fixed on purpose: a dark ticket whose colours moved with the preset would stop being the thing
        the tenant picked."""
        rule = re.search(r"\.sl-coupon\[data-coupon-style='dark'\]\{([^}]*)\}", CSS).group(1)
        for prop in ("--sl-coupon-bg:", "--sl-coupon-text:", "--sl-coupon-accent:"):
            self.assertIn(prop, rule)

    def test_original_pins_the_colours_that_used_to_be_fallbacks(self):
        """They were hardcoded defaults nothing ever overrode. Now that the ticket follows the preset,
        "original" has to state them or it would quietly become a theme-following style."""
        rule = re.search(r"\.sl-coupon\[data-coupon-style='original'\]\{([^}]*)\}", CSS).group(1)
        self.assertIn("--sl-coupon-accent:#e0402c", rule)
        self.assertIn("--sl-coupon-bg:#fff", rule)

    def test_the_other_three_pin_nothing(self):
        for style in ("modern", "bold", "ribbon"):
            with self.subTest(style=style):
                rule = re.search(r"\.sl-coupon\[data-coupon-style='" + style + r"'\]\{([^}]*)\}", CSS)
                self.assertNotIn("--sl-coupon-bg:", rule.group(1) if rule else "")


class TheStoredSectionTests(unittest.TestCase):
    def page(self, **coupon_section):
        return {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
                "page_id": "p1", "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                "sections": [{"type": "coupon", "id": "c", "code": "X", **coupon_section}]}

    def test_every_style_validates(self):
        for style in COUPON_STYLES:
            with self.subTest(style=style):
                validate_page_document(self.page(style=style))

    def test_absent_validates(self):
        validate_page_document(self.page())

    def test_a_typo_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self.page(style="moderne"))


class TheBuilderTests(unittest.TestCase):
    def test_every_style_is_offered(self):
        for style in COUPON_STYLES:
            with self.subTest(style=style):
                self.assertIn(f'<option value="{style}">', BUILDER)

    def test_a_new_coupon_starts_modern(self):
        new_element = BUILDER.split('if (type === "coupon") return', 1)[1].split(";", 1)[0]
        self.assertIn('style: "modern"', new_element)

    def test_the_default_is_not_written_to_the_document(self):
        """So a page keeps tracking the default if it ever moves, the same rule as the FAQ toggle."""
        save = BUILDER.split('if (element.type === "coupon") {', 1)[1]
        save = save[:save.index("\n  }")]
        self.assertIn('element.style !== "modern" ? element.style : undefined', save)

    def test_loading_treats_absent_as_modern(self):
        load = BUILDER.split('} else if (section.type === "coupon") {', 1)[1]
        self.assertIn('style: section.style || "modern"', load[:load.index("\n    }")])


if __name__ == "__main__":
    unittest.main()
