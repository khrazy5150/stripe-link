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

from stripe_link.domain.section_theme import DARK_INK, LIGHT_INK, contrast_ratio, readable_ink
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS, theme_tokens

AA_NORMAL = 4.5


def contrast(one: str, two: str) -> float:
    """`section_theme`'s own ratio, not a second copy. The first version of this fix carried a duplicate
    luminance implementation in `html.py` -- which is how a codebase acquires two answers to "which ink
    is readable" that quietly drift apart."""
    ratio = contrast_ratio(one, two)
    assert ratio is not None, (one, two)
    return ratio


class EveryPresetsBadgeIsReadable(unittest.TestCase):
    def test_all_sixteen_pass_wcag_aa(self):
        """Measured against the badge's own GROUND, which is what the numeral actually sits on.

        A preset may darken that ground (`badge_bg`) to earn white ink on a hue whose raw accent is too
        light for white — eight do, 2026-10-15. The guarantee is unchanged: whatever ground a preset
        chooses, the ink is still measured against it, so this cannot be satisfied by forcing a colour.
        """
        for name in UNIVERSAL_BUNDLE_THEME_PRESETS:
            with self.subTest(preset=name):
                tokens = theme_tokens({"theme": {"preset": name}})
                ink, ground = tokens["badge_ink"], tokens["badge_bg"]
                self.assertGreaterEqual(
                    contrast(ground, ink), AA_NORMAL, f"{name}: {ink} on {ground} is unreadable")

    def test_the_ground_defaults_to_the_accent(self):
        """A preset that says nothing is exactly as it was: same ground, same measured ink."""
        for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
            if "badge_bg" in preset:
                continue
            with self.subTest(preset=name):
                tokens = theme_tokens({"theme": {"preset": name}})
                self.assertEqual(tokens["badge_bg"], preset["accent"])
                self.assertEqual(tokens["badge_ink"], tokens["accent_text"])

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
                self.assertEqual(theme_tokens({"theme": {"preset": name}})["accent_text"], LIGHT_INK)

    def test_a_light_accent_gets_dark_ink(self):
        self.assertEqual(theme_tokens({"theme": {"preset": "tiktok-dark"}})["accent_text"], DARK_INK)


class ReadableInkHandlesWhatThemesActuallyContain(unittest.TestCase):
    def test_six_digit_hex(self):
        self.assertEqual(readable_ink("#ffffff"), DARK_INK)
        self.assertEqual(readable_ink("#000000"), LIGHT_INK)

    def test_three_digit_hex(self):
        self.assertEqual(readable_ink("#fff"), DARK_INK)
        self.assertEqual(readable_ink("#000"), LIGHT_INK)

    def test_an_unparseable_value_falls_back_to_the_old_behaviour(self):
        """`readable_ink` returns None for a colour it cannot read, and `theme_tokens` turns that into
        the light ink -- which is what every one of these rules used before. An unknown must change
        nothing rather than guess, because guessing wrong is the invisible-text failure itself.

        Every preset accent is hex today, so this is the guard, not the common path."""
        for value in ("linear-gradient(90deg,#ff0050,#00f2ea)", "var(--sl-accent)", "", None, "teal"):
            with self.subTest(value=value):
                self.assertIsNone(readable_ink(value))
        tokens = theme_tokens({"theme": {"preset": "tiktok-dark",
                                         "tokens": {"accent": "linear-gradient(90deg,#fff,#000)"}}})
        self.assertEqual(tokens["accent_text"], LIGHT_INK)


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
        # `badge_ink` is measured against the badge's own ground, which `accent_text` was until a preset
        # could darken that ground (2026-10-15). Still accent-aware; still never the CTA gradient's ink.
        self.assertIn("color:var(--sl-badge-ink", rule)
        self.assertNotIn("color:var(--sl-cta-text", rule)
        self.assertNotIn("color:var(--sl-accent-text", rule)

    def test_the_variable_is_emitted_with_the_derived_value(self):
        from stripe_link.runtime.html import render_template_styles
        css = "\n".join(render_template_styles({"theme": {"preset": "tiktok-dark"},
                                                "template": "universal_bundle"}))
        self.assertIn(f"--sl-accent-text:{DARK_INK}", css)


class EveryAccentBackgroundInksFromAccentText(unittest.TestCase):
    """The first fix did one element. The author: *"you need to fix every element that uses that aqua
    blue color."*

    Right — `.sl-numbered-item::before` was simply the one that got noticed. Four more rules sat on an
    accent-derived background and took their ink from `cta_text`: `.sl-dl-submit`, `.sl-ribbon-cta`
    (the "Reserve your spot" pill), `.sl-quote-fancy .sl-quote-figure` and `.sl-author-name`.

    This scans the stylesheet rather than listing them, so a NEW element that paints itself with
    `--sl-accent` and inks from `cta_text` fails here instead of shipping unreadable.
    """

    def rules(self):
        import pathlib
        import re
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "src" / "stripe_link" / "runtime" / "html.py").read_text()
        out = []
        for rule in re.findall(r'"\s{0,8}(\.[^"]*?\{[^"]*?\})"', src):
            selector, _, body = rule.partition("{")
            background = re.search(r"background(?:-color)?:\s*([^;}]+)", body)
            ink = re.search(r"(?<!-)color:\s*([^;}]+)", body)
            if background and ink:
                out.append((selector.strip(), background.group(1), ink.group(1)))
        return out

    def test_the_scan_finds_real_rules(self):
        """A guard that matches nothing would pass forever."""
        found = self.rules()
        self.assertGreater(len(found), 10)
        self.assertTrue(any(".sl-numbered-item::before" in sel for sel, _, _ in found))

    def test_no_flat_accent_background_inks_from_cta_text(self):
        for selector, background, ink in self.rules():
            if "--sl-accent)" in background and "gradient" not in background:
                with self.subTest(selector=selector):
                    self.assertNotIn(
                        "cta-text", ink,
                        f"{selector} paints itself with --sl-accent but inks from cta_text, which "
                        f"answers a question about the CTA gradient, not about the accent")

    def test_the_four_known_elements_use_the_right_token(self):
        """Named explicitly as well as scanned, so a rename cannot silently drop one from the sweep."""
        wanted = {".sl-dl-submit", ".sl-ribbon-cta", ".sl-quote-fancy .sl-quote-figure",
                  ".sl-author-name", ".sl-numbered-item::before"}
        seen = {sel for sel, _, ink in self.rules() if "badge-ink" in ink}
        self.assertEqual(wanted - seen, set(), "an element lost its badge-aware ink")

    def test_none_of_them_still_inks_from_the_raw_accent_text(self):
        """They all paint themselves with `badge_bg` now, so inking from `accent_text` would measure
        against a ground they are not sitting on — the original bug, one token along."""
        for selector, background, ink in self.rules():
            if "--sl-badge-bg" in background:
                with self.subTest(selector=selector):
                    self.assertNotIn("accent-text", ink)


if __name__ == "__main__":
    unittest.main()
