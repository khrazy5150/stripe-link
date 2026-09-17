"""Every tone, against every preset, in both polarities.

Author, 2026-09-17, on a dark theme: two of the three tones were unreadable. "dark" meant
`--sl-section-bg: var(--sl-text)` -- a dark colour on a light preset and a near-WHITE one on the eight dark
presets, where it painted a white panel and then wrote white on it. The inverted button did the same thing.

The rule that fixes it, and the one this file exists to keep: a tone may only pair tokens the PRESET designed
together -- (background, text), (card, text), (cta gradient, cta_text). Mixing one pair's surface with
another pair's ink is exactly what inverts when the preset does.

So this does not inspect the CSS for shape; it RESOLVES each tone against every shipped preset and measures
the contrast. A reviewer reading the rules would have said they looked fine.
"""
import re
import unittest

from stripe_link.domain.section_theme import SECTION_TONES, relative_luminance
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS, UNIVERSAL_BUNDLE_TEMPLATE_STYLES

CSS = "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
# This guards against INVERSION, not against the presets' own colour choices.
#
# The bug it exists for scored ~1.0 -- white ink on a white panel. Three shipped presets already pair their
# CTA gradient with white at 2.28-2.80 (coral-sunrise, clean-slate, natural-calm), below WCAG AA-large of
# 3.0, and that is true of every button on those pages today, not something a tone introduced. Failing them
# here would be this test complaining about a different problem than the one it can see; that one is
# recorded in plans/TODO.md instead. 2.0 separates "inverted" from "the preset's own call" cleanly.
MIN_LEGIBLE = 2.0


def _token(preset: dict, name: str) -> str:
    """Resolve `--sl-foo` to the preset's value. Preset keys are the token names without the prefix."""
    return preset.get(name.removeprefix("--sl-").replace("-", "_"), "")


def _resolve(value: str, preset: dict) -> str:
    """One CSS value -> a literal colour.

    Takes the FIRST var(--sl-*) in the value, which is the colour for a plain token and the first stop for a
    gradient -- the stop the ink sits on hardest. Written to see through the nested parens of
    `linear-gradient(135deg, var(--sl-cta-from), var(--sl-cta-to))`.
    """
    var = re.search(r"var\((--sl-[a-z-]+)\)", value)
    if var:
        return _token(preset, var.group(1))
    return value.strip()


def _rule(selector: str) -> dict:
    line = [l for l in CSS.splitlines() if l.strip().startswith(selector + "{")]
    if not line:
        line = [l for l in CSS.splitlines() if selector + "{" in l]
    body = line[0].split("{", 1)[1].rsplit("}", 1)[0]
    out = {}
    for declaration in body.split(";"):
        if ":" in declaration:
            key, _, val = declaration.partition(":")
            out[key.strip()] = val.strip()
    return out


def _hex(color: str) -> str:
    """#rrggbb for a hex or rgb() value. The presets use both, and relative_luminance reads only hex."""
    rgb = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color.strip())
    if rgb:
        return "#" + "".join(f"{int(part):02x}" for part in rgb.groups())
    return color.strip()


def _contrast(a: str, b: str) -> float | None:
    la, lb = relative_luminance(_hex(a)), relative_luminance(_hex(b))
    if la is None or lb is None:
        return None
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


class ToneContrastTests(unittest.TestCase):
    def test_every_preset_ships_the_tokens_a_tone_reads(self):
        for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
            for token in ("background", "text", "card", "cta_text", "cta_from"):
                self.assertTrue(preset.get(token), f"{name} has no {token}")

    def test_a_panel_is_readable_on_every_preset(self):
        """The failure the author hit: white ink on a white panel, on a dark theme."""
        failures = []
        for tone in SECTION_TONES:
            rule = _rule(f".sl-tone-{tone}")
            for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
                bg = _resolve(rule["--sl-section-bg"], preset)
                ink = _resolve(rule["--sl-section-ink"], preset)
                ratio = _contrast(bg, ink)
                if ratio is None or ratio < MIN_LEGIBLE:
                    failures.append(f"{tone} on {name}: {bg} vs {ink} = {ratio}")
        self.assertFalse(failures, "unreadable panels:\n" + "\n".join(failures))

    def test_a_button_on_a_filled_panel_is_readable_on_every_preset(self):
        """The second half of the same bug: the inverted button went white-on-white too."""
        rule = _rule(".sl-tone-contrast .sl-cta,.sl-tone-accent .sl-cta")
        failures = []
        for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
            bg = _resolve(rule["background"], preset)
            ink = _resolve(rule["color"], preset)
            ratio = _contrast(bg, ink)
            if ratio is None or ratio < MIN_LEGIBLE:
                failures.append(f"button on {name}: {bg} vs {ink} = {ratio}")
        self.assertFalse(failures, "unreadable buttons:\n" + "\n".join(failures))

    def test_the_button_also_stands_apart_from_the_panel_it_sits_on(self):
        # Readable text on a button nobody can see is not a button. Lower bar than AA -- this is a surface
        # boundary, not text -- but it has to be visible.
        button = _rule(".sl-tone-contrast .sl-cta,.sl-tone-accent .sl-cta")
        failures = []
        for tone in ("contrast", "accent"):
            panel = _rule(f".sl-tone-{tone}")
            for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
                ratio = _contrast(_resolve(panel["--sl-section-bg"], preset),
                                  _resolve(button["background"], preset))
                if ratio is None or ratio < 1.5:
                    failures.append(f"{tone} on {name}: button blends into the panel ({ratio})")
        self.assertFalse(failures, "invisible buttons:\n" + "\n".join(failures))

    def test_the_names_describe_the_relationship_not_an_absolute_colour(self):
        """"Dark" was a lie on eight of the fourteen presets.

        A tone inverts the page, or brands it, or quiets it -- none of those is a colour, and naming one
        after a colour is what let a white panel be called dark.
        """
        self.assertEqual(SECTION_TONES, ("contrast", "accent", "soft"))
        builder = _BUILDER
        self.assertIn('value="contrast">Bold — high contrast with the page', builder)
        self.assertNotIn('value="dark"', builder)

    def test_no_tone_pairs_one_designed_pair_with_another(self):
        # The structural half of the rule, so the reason survives even if the presets change.
        pairs = {
            "--sl-text": "--sl-background", "--sl-background": "--sl-text",
            "--sl-card": "--sl-text", "--sl-cta-from": "--sl-cta-text",
        }
        for tone in SECTION_TONES:
            rule = _rule(f".sl-tone-{tone}")
            bg = re.search(r"var\((--sl-[a-z-]+)\)", rule["--sl-section-bg"]).group(1)
            ink = re.search(r"var\((--sl-[a-z-]+)\)", rule["--sl-section-ink"]).group(1)
            self.assertEqual(pairs.get(bg), ink, f"{tone} pairs {bg} with {ink}, which the preset did not")


import pathlib  # noqa: E402  (kept beside its single use)

_BUILDER = (pathlib.Path(__file__).resolve().parents[1]
            / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
