"""Five coupon looks over one markup shape.

Author, 2026-10-15, with four reference designs and a fifth kept alongside them: Modern (default), Bold,
Ribbon, Dark, Minimalist. *"The coupon color schemes should follow the current theme's color scheme,
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

    def test_minimalist_pins_its_own_colours(self):
        """They were hardcoded defaults nothing ever overrode. Now that the ticket follows the preset,
        this style has to state them or it would quietly become a theme-following one."""
        rule = re.search(r"\.sl-coupon\[data-coupon-style='minimalist'\]\{([^}]*)\}", CSS).group(1)
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


class BoldIsRibbonWithAHandmadeFinishTests(unittest.TestCase):
    """Author, 2026-10-15: *"The 'bold' style is basically the same as the 'ribbon' style except with the
    details I mentioned."* Picture on the right, perforated edges, a framed photograph, a drawn arrow."""

    def rule(self, selector):
        found = re.search(re.escape(selector) + r"\{([^}]*)\}", CSS)
        return found.group(1) if found else ""

    def test_the_picture_moves_to_the_right_like_ribbon(self):
        self.assertIn("order:2", self.rule(".sl-coupon[data-coupon-style='bold'] .sl-coupon-media"))
        self.assertIn("order:1", self.rule(".sl-coupon[data-coupon-style='bold'] .sl-coupon-body"))

    def test_both_put_the_picture_in_the_same_column(self):
        """The one structural thing that makes them "basically the same"."""
        for style in ("ribbon", "bold"):
            with self.subTest(style=style):
                self.assertIn("grid-template-columns:minmax(0,1fr)",
                              self.rule(f".sl-coupon[data-coupon-style='{style}']"))

    def test_the_ticket_is_outlined(self):
        """A masked notch was invisible on a cream ticket against a cream page, and could never be fixed
        with a border: a mask clips the border too, so the arcs had no outline and nor did the straight
        edges (reported 2026-10-15)."""
        card = self.rule(".sl-coupon[data-coupon-style='bold']")
        self.assertIn("border:1px solid var(--sl-coupon-edge)", card)
        self.assertNotIn("mask", card, "the notch is painted now, not masked")

    def test_the_edge_colour_is_derived_not_branched(self):
        """Near-black on a light ticket, light grey on a dark one, without asking which preset is on."""
        card = self.rule(".sl-coupon[data-coupon-style='bold']")
        self.assertIn("--sl-coupon-edge:color-mix(in srgb,var(--sl-coupon-text", card)

    def test_the_notches_are_painted_and_carry_the_same_outline(self):
        notch = self.rule(".sl-coupon[data-coupon-style='bold']::before,"
                          ".sl-coupon[data-coupon-style='bold']::after")
        self.assertIn("border-radius:50%", notch)
        self.assertIn("background:var(--sl-background", notch)
        self.assertIn("border:1px solid var(--sl-coupon-edge)", notch)

    def test_each_notch_shows_only_the_half_over_the_ticket(self):
        """The outer half would draw a stray arc on the page."""
        # Asserted on the whole declaration rather than through `rule()`: the shared block names both
        # pseudos, so looking up "::after" alone finds that one and proves nothing about the side.
        self.assertIn("left:calc(var(--sl-notch) * -1);clip-path:inset(0 0 0 50%)", CSS)
        self.assertIn("right:calc(var(--sl-notch) * -1);clip-path:inset(0 50% 0 0)", CSS)

    def test_the_card_stops_clipping_so_the_notches_can_sit_on_its_edge(self):
        self.assertIn("overflow:visible", self.rule(".sl-coupon[data-coupon-style='bold']"))

    def test_only_bold_is_outlined(self):
        """The outline exists to make the perforation legible. No other style has one to explain."""
        for style in ("modern", "minimalist", "ribbon", "dark"):
            with self.subTest(style=style):
                self.assertNotIn("--sl-coupon-edge",
                                 self.rule(f".sl-coupon[data-coupon-style='{style}']"))

    def test_the_photograph_is_framed_and_tilted(self):
        img = self.rule(".sl-coupon[data-coupon-style='bold'] .sl-coupon-media img")
        self.assertIn("border:0.8rem solid #fff", img)
        self.assertIn("rotate(", img)
        self.assertIn("box-shadow", img)

    def test_the_redeem_line_has_a_drawn_arrow(self):
        before = self.rule(".sl-coupon[data-coupon-style='bold'] .sl-coupon-cta::before")
        self.assertIn("var(--sl-coupon-arrow)", before)
        self.assertIn("background:currentColor", before, "the arrow takes the line's colour, not its own")
        self.assertIn("--sl-coupon-arrow:url(", CSS)

    def test_the_redeem_line_uses_the_accent_family(self):
        """`--sl-font-accent` rather than a family named in the stylesheet: a third webfont is a third
        download on a page tuned for LCP, and the accent role exists for exactly this."""
        cta = self.rule(".sl-coupon[data-coupon-style='bold'] .sl-coupon-cta")
        self.assertIn("font-family:var(--sl-font-accent,var(--sl-font-heading))", cta)
        self.assertIn("font-style:italic", cta)

    def test_no_font_family_is_hardcoded_into_a_coupon_style(self):
        """If one ever is, a page gained a download nobody chose."""
        for style in ("modern", "minimalist", "ribbon", "bold", "dark"):
            with self.subTest(style=style):
                for line in CSS.splitlines():
                    if f"data-coupon-style='{style}'" in line and "font-family:" in line:
                        self.assertIn("var(--sl-font", line)
