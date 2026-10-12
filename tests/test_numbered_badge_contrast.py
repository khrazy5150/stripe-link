"""The numbered badge's numeral must be readable on the accent it sits on.

The author, 2026-10-12, on the TikTok dark theme: *"TikTok dark uses white font inside the aqua blue.
That makes it hard to see."*

The cause was that the badge coloured its numeral with `cta_text` — which answers *"what reads on the
CTA gradient?"* — while sitting on `accent`. Different colours, different question. An audit of all
sixteen presets found **twelve** failing WCAG AA, `tiktok-dark` worst at **1.41:1**: white on `#00f2ea`,
effectively invisible.

Deriving the ink from the accent's own luminance fixes every preset at once and stops a new preset
reintroducing the fault by choosing a light accent.
"""
import unittest

from stripe_link.runtime.html import (UNIVERSAL_BUNDLE_THEME_PRESETS, _relative_luminance, readable_ink,
                                      theme_tokens)

AA_NORMAL = 4.5


def contrast(one: str, two: str) -> float:
    first, second = _relative_luminance(one), _relative_luminance(two)
    assert first is not None and second is not None, (one, two)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


class EveryPresetsBadgeIsReadable(unittest.TestCase):
    def test_all_sixteen_pass_wcag_aa(self):
        for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
            with self.subTest(preset=name):
                ink = theme_tokens({"theme": {"preset": name}})["accent_text"]
                self.assertGreaterEqual(
                    contrast(preset["accent"], ink), AA_NORMAL,
                    f"{name}: {ink} on {preset['accent']} is unreadable")

    def test_the_reported_theme_is_dramatically_better(self):
        """1.41 before, which is why it looked like the numeral was missing."""
        accent = UNIVERSAL_BUNDLE_THEME_PRESETS["tiktok-dark"]["accent"]
        ink = theme_tokens({"theme": {"preset": "tiktok-dark"}})["accent_text"]
        self.assertGreater(contrast(accent, ink), 10)
        self.assertLess(contrast(accent, "#ffffff"), 2, "the old colour really was that bad")

    def test_a_dark_accent_still_gets_light_ink(self):
        """Not a blanket darkening -- `youtube-red` and `professional-gray` have dark accents and keep
        white. Flipping those would have traded one unreadable badge for another."""
        for name in ("youtube-red", "professional-gray"):
            with self.subTest(preset=name):
                self.assertEqual(theme_tokens({"theme": {"preset": name}})["accent_text"], "#ffffff")

    def test_a_light_accent_gets_dark_ink(self):
        self.assertEqual(theme_tokens({"theme": {"preset": "tiktok-dark"}})["accent_text"], "#0b0b0b")


class ReadableInkHandlesWhatThemesActuallyContain(unittest.TestCase):
    def test_six_digit_hex(self):
        self.assertEqual(readable_ink("#ffffff"), "#0b0b0b")
        self.assertEqual(readable_ink("#000000"), "#ffffff")

    def test_three_digit_hex(self):
        self.assertEqual(readable_ink("#fff"), "#0b0b0b")
        self.assertEqual(readable_ink("#000"), "#ffffff")

    def test_rgb_notation(self):
        """`instagram-gradient` stores its CTA stops as `rgb(...)`, so this is not hypothetical."""
        self.assertEqual(readable_ink("rgb(255,255,255)"), "#0b0b0b")
        self.assertEqual(readable_ink("rgb(0,0,0)"), "#ffffff")

    def test_an_unparseable_value_keeps_the_old_behaviour(self):
        """A gradient or a var() is not something to guess a contrast against. White is what the badge
        used before, so an unknown changes nothing rather than inventing an answer."""
        for value in ("linear-gradient(90deg,#ff0050,#00f2ea)", "var(--sl-accent)", "", None, "teal"):
            with self.subTest(value=value):
                self.assertEqual(readable_ink(value), "#ffffff")

    def test_luminance_is_none_for_those_values(self):
        self.assertIsNone(_relative_luminance("linear-gradient(90deg,#fff,#000)"))
        self.assertIsNone(_relative_luminance("#12345"))


class APresetCanStillChooseItsOwn(unittest.TestCase):
    """The derivation is a DEFAULT, not a policy. A theme that wants a brand ink on its badge says so."""

    def test_an_explicit_token_wins(self):
        tokens = theme_tokens({"theme": {"preset": "tiktok-dark", "tokens": {"accent_text": "#ff0050"}}})
        self.assertEqual(tokens["accent_text"], "#ff0050")


class TheBadgeActuallyUsesTheToken(unittest.TestCase):
    def test_the_rule_references_accent_text_not_cta_text(self):
        from stripe_link.runtime.html import render_template_styles
        css = "\n".join(render_template_styles({"theme": {"preset": "tiktok-dark"},
                                                "template": "universal_bundle"}))
        rule = next(line for line in css.splitlines() if ".sl-numbered-item::before" in line)
        self.assertIn("color:var(--sl-accent-text", rule)
        self.assertNotIn("color:var(--sl-cta-text", rule)

    def test_the_variable_is_emitted_with_the_derived_value(self):
        from stripe_link.runtime.html import render_template_styles
        css = "\n".join(render_template_styles({"theme": {"preset": "tiktok-dark"},
                                                "template": "universal_bundle"}))
        self.assertIn("--sl-accent-text:#0b0b0b", css)


if __name__ == "__main__":
    unittest.main()
