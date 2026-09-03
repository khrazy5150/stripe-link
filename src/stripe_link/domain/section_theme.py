"""Section-scoped theme overrides — one element breaking the page preset on purpose.

Four elements in the landing-elements unit want this: Author Bio (background + image border), Bragging
Points (background), Quote (background + the vertical bar accent) and the Page Ribbon. Built per element
that is four implementations of one idea — the failure this codebase has produced with slug rules, funnel
roles, entry readers and chips. So it is one mechanism, and each element declares which tokens it honours.

Shape: `section["theme"] = {"bg": "#1e1033", "accent": "#f97316", "border": "#ffffff"}`. Anything absent
falls through to the page preset, so the DEFAULT is always "follow the theme" and no existing page changes.
This is `plans/ADVANCED_COLOR_SETTINGS.md`'s page-level idea one scope down.

⚠️ The foreground is DERIVED, never authored and never inherited. The legacy implementation offers a
background picker with no text colour, so the ink keeps coming from the preset: a dark background on a
light-text theme makes the copy invisible, silently. Deriving it from the background's luminance makes the
tenant's choice a single decision that cannot produce an unreadable result — and it is better than exposing
a text-colour picker, which would let them choose black on black.
"""

from typing import Any

# Ink chosen when a section overrides its background. Measured across a spread of backgrounds rather than
# picked for looks: a softened white (#f8fafc) drops the worst case to 4.49:1 on mid-grey, just under WCAG
# AA, while pure white keeps it at 4.83:1 and clears AA on every background tried. The dark ink can stay
# near-black without costing anything, so it does — full black on a saturated colour reads harsh.
DARK_INK = "#0b0f19"
LIGHT_INK = "#ffffff"

# Every token a section may override. Anything else is ignored rather than silently emitted, so a typo
# cannot inject arbitrary CSS.
ALLOWED_TOKENS = ("bg", "accent", "border")



def _channel(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float | None:
    """WCAG relative luminance of a #rgb/#rrggbb colour, or None if it is not one we can read."""
    raw = str(color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    if len(raw) != 6:
        return None
    try:
        red, green, blue = (int(raw[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return None
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground: str, background: str) -> float | None:
    """WCAG contrast ratio between two colours, or None if either cannot be read."""
    first, second = relative_luminance(foreground), relative_luminance(background)
    if first is None or second is None:
        return None
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def readable_ink(background: str) -> str | None:
    """The ink that stays readable on `background`, or None when the colour cannot be parsed.

    MEASURES both candidates rather than thresholding luminance. A luminance cutoff seems reasonable and is
    wrong on saturated mid-tones: the first version of this used 0.42 and chose the WORSE ink for orange,
    mid-grey and green — three of ten test colours. Computing the actual contrast for both inks and taking
    the higher is exact, simpler, and has no magic number to tune.

    Returning None matters: an unparseable colour falls back to the preset rather than guessing, because
    guessing wrong is precisely the invisible-text failure this exists to prevent.
    """
    dark = contrast_ratio(DARK_INK, background)
    light = contrast_ratio(LIGHT_INK, background)
    if dark is None or light is None:
        return None
    return DARK_INK if dark >= light else LIGHT_INK


def section_theme_vars(section: dict[str, Any]) -> str:
    """Inline custom properties for a section's overrides, or "" when it follows the preset.

    Emits `--sl-section-*` names so a section's override can never collide with a page-level token, and so
    an element's CSS can opt in explicitly (`var(--sl-section-bg, var(--sl-background))`) rather than
    inheriting a background it was not designed for.
    """
    theme = section.get("theme")
    if not isinstance(theme, dict):
        return ""

    parts: list[str] = []
    for token in ALLOWED_TOKENS:
        value = str(theme.get(token) or "").strip()
        # Only colours we can parse: an arbitrary string here would land in a style attribute.
        if value and relative_luminance(value) is not None:
            parts.append(f"--sl-section-{token}:{value}")

    background = str(theme.get("bg") or "").strip()
    if background:
        ink = readable_ink(background)
        if ink:
            parts.append(f"--sl-section-ink:{ink}")
    return ";".join(parts)


def has_section_theme(section: dict[str, Any]) -> bool:
    """Whether this section actually overrides anything — for choosing a CSS class, not for styling."""
    return bool(section_theme_vars(section))
