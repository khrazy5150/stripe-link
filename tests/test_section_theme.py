"""Section-scoped theme overrides, and the derived ink that makes them safe.

Four elements in the landing-elements unit break the page preset (Author Bio, Bragging Points, Quote, Page
Ribbon). This is the one mechanism they share — built once rather than as four sets of colour pickers.

The property that matters: a tenant chooses ONE colour and cannot produce unreadable text. The legacy
offers a background picker with no text colour, so the ink keeps coming from the preset and a dark
background on a light-text theme makes the copy invisible with no warning.
"""

import unittest

from stripe_link.domain.section_theme import (
    ALLOWED_TOKENS,
    DARK_INK,
    LIGHT_INK,
    contrast_ratio,
    has_section_theme,
    readable_ink,
    relative_luminance,
    section_theme_vars,
)

# A spread deliberately including the hard cases: saturated mid-tones and grey, where a naive
# luminance threshold picks the wrong ink.
BACKGROUNDS = (
    "#1e1033", "#ffffff", "#f97316", "#4f46e5", "#facc15", "#0f766e",
    "#e5e7eb", "#7f1d1d", "#a3a3a3", "#22c55e", "#000000", "#808080", "#6b7280",
)


class ReadableInkTests(unittest.TestCase):
    def test_always_picks_the_higher_contrast_ink(self):
        """The first implementation thresholded luminance at 0.42 and chose the WORSE ink for orange,
        mid-grey and green — three of ten. Measuring both is exact and has no number to tune."""
        for background in BACKGROUNDS:
            with self.subTest(background=background):
                chosen = readable_ink(background)
                other = DARK_INK if chosen == LIGHT_INK else LIGHT_INK
                self.assertGreaterEqual(
                    contrast_ratio(chosen, background),
                    contrast_ratio(other, background),
                    f"{background} got the worse ink",
                )

    def test_every_background_clears_wcag_aa(self):
        # This is the whole promise of the feature: pick a colour, get readable text.
        for background in BACKGROUNDS:
            with self.subTest(background=background):
                self.assertGreaterEqual(contrast_ratio(readable_ink(background), background), 4.5)

    def test_an_unparseable_colour_returns_none_rather_than_guessing(self):
        # Falling back to the preset is safe; guessing is how text disappears.
        for junk in ("", "red", "javascript:alert(1)", "#12", "not a colour", None):
            with self.subTest(value=junk):
                self.assertIsNone(readable_ink(junk))

    def test_shorthand_hex_is_understood(self):
        self.assertAlmostEqual(relative_luminance("#fff"), relative_luminance("#ffffff"))


class SectionThemeVarsTests(unittest.TestCase):
    def test_no_theme_means_follow_the_preset(self):
        # The default path: an existing page has no `theme` and must be untouched.
        for section in ({}, {"theme": None}, {"theme": {}}, {"theme": "dark"}):
            with self.subTest(section=section):
                self.assertEqual(section_theme_vars(section), "")
                self.assertFalse(has_section_theme(section))

    def test_emits_only_the_tokens_given_plus_derived_ink(self):
        css = section_theme_vars({"theme": {"bg": "#1e1033"}})
        self.assertIn("--sl-section-bg:#1e1033", css)
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", css)
        self.assertNotIn("accent", css)

    def test_accent_and_border_ride_along(self):
        # Quote needs an accent (its vertical bar) as well as a background — which is why this is a token
        # map rather than a single background field.
        css = section_theme_vars({"theme": {"bg": "#1e1033", "accent": "#f97316", "border": "#ffffff"}})
        for token in ALLOWED_TOKENS:
            with self.subTest(token=token):
                self.assertIn(f"--sl-section-{token}:", css)

    def test_an_accent_alone_derives_no_ink(self):
        # Ink is derived from a BACKGROUND. Without one the section keeps the preset's text colour.
        css = section_theme_vars({"theme": {"accent": "#f97316"}})
        self.assertIn("--sl-section-accent", css)
        self.assertNotIn("--sl-section-ink", css)

    def test_unknown_tokens_are_dropped(self):
        css = section_theme_vars({"theme": {"bg": "#1e1033", "font_size": "99px", "onclick": "x"}})
        self.assertNotIn("font_size", css)
        self.assertNotIn("onclick", css)

    def test_a_value_that_is_not_a_colour_cannot_reach_the_style_attribute(self):
        # These land in an inline style, so anything unparseable is dropped rather than echoed.
        css = section_theme_vars({"theme": {"bg": 'red;content:"x"', "accent": "url(javascript:1)"}})
        self.assertEqual(css, "")


if __name__ == "__main__":
    unittest.main()
