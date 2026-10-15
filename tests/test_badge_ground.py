"""Eight presets darken the badge GROUND so white ink earns its place.

Author, 2026-10-15, looking at a red numbered circle with near-black numerals: *"you are now putting dark
text inside the red circles and pills for certain themes."* The ink was right — `readable_ink` measures both
and takes the higher — but on a light accent the readable answer is the one that looks like a mistake.

Forcing white was the obvious fix and is the wrong one: it reverts part of the 2026-10-12 work, where
TWELVE of sixteen presets failed WCAG AA and `tiktok-dark` sat at 1.41:1. Six of these eight would have
landed between 2.14 and 2.98:1 — the same failure in a different hue.

So the GROUND moves, not the ink. A darker shade of the same hue, and `readable_ink` then chooses white on
its own. The brand colour is untouched everywhere else on the page.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.section_theme import contrast_ratio  # noqa: E402
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS as PRESETS, theme_tokens  # noqa: E402

DARKENED = ["clean-slate", "rose-minimalist", "fire-sale", "natural-calm",
            "cyber-pulse", "linkedin-blue", "instagram-gradient", "twitter-dark"]


class TheEightTests(unittest.TestCase):
    def test_each_now_gets_white_ink(self):
        for preset in DARKENED:
            with self.subTest(preset=preset):
                self.assertEqual(theme_tokens({"theme": {"preset": preset}})["badge_ink"], "#ffffff")

    def test_white_is_EARNED_not_declared(self):
        """None of them states the ink. If one ever did, the measurement would stop protecting it."""
        for preset in DARKENED:
            with self.subTest(preset=preset):
                self.assertNotIn("accent_text", PRESETS[preset])
                self.assertNotIn("badge_ink", PRESETS[preset])

    def test_the_ground_is_darker_than_the_accent_and_passes(self):
        for preset in DARKENED:
            with self.subTest(preset=preset):
                tokens = theme_tokens({"theme": {"preset": preset}})
                accent, ground = PRESETS[preset]["accent"], tokens["badge_bg"]
                self.assertNotEqual(ground, accent)
                self.assertGreater(contrast_ratio("#ffffff", ground), contrast_ratio("#ffffff", accent))
                self.assertGreaterEqual(contrast_ratio("#ffffff", ground), 4.5)


class TheRestOfThePageIsUntouchedTests(unittest.TestCase):
    def test_the_accent_itself_never_changed(self):
        """The point of moving the ground rather than the accent: everything else keeps the brand colour."""
        expected = {"clean-slate": "#38bdf8", "rose-minimalist": "#ff6b9d", "fire-sale": "#f87171",
                    "natural-calm": "#22c55e", "cyber-pulse": "#818cf8", "linkedin-blue": "#00a0dc",
                    "instagram-gradient": "#fd1d1d", "twitter-dark": "#1a8cd8"}
        for preset, accent in expected.items():
            with self.subTest(preset=preset):
                self.assertEqual(PRESETS[preset]["accent"], accent)

    def test_presets_that_said_nothing_are_bit_for_bit_the_same(self):
        for preset, spec in PRESETS.items():
            if preset in DARKENED:
                continue
            with self.subTest(preset=preset):
                tokens = theme_tokens({"theme": {"preset": preset}})
                self.assertEqual(tokens["badge_bg"], spec["accent"])
                self.assertEqual(tokens["badge_ink"], tokens["accent_text"])

    def test_the_reported_tiktok_badge_is_still_fixed(self):
        """The regression this whole family of tests exists to prevent."""
        tokens = theme_tokens({"theme": {"preset": "tiktok-dark"}})
        self.assertEqual(tokens["badge_ink"], "#0b0f19")
        self.assertGreater(contrast_ratio(tokens["badge_ink"], tokens["badge_bg"]), 10)


if __name__ == "__main__":
    unittest.main()
