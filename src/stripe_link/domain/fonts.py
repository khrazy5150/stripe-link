"""Which typeface a page uses, and who decided it.

Four levels, most specific winning. This is the SAME shape as the colour-token override
(plans/ADVANCED_COLOR_SETTINGS.md), deliberately: type and colour are the same kind of decision, and two
different precedence rules for one visual identity is a thing nobody can hold in their head.

    system fallback     always present, never fails
      ← preset          the design the tenant picked
      ← tenant default  ONLY when they switched the override on
      ← page override   an explicit choice on THIS page

A page override beats the tenant default on purpose. A tenant with a house style will still want one
landing page to look different, and should not have to turn their own preference off to get it.

Presets PROPOSE fonts rather than owning them. If a preset owned type, switching preset would silently
destroy a deliberate choice — and the tenant would not find out until a customer did.
"""

from typing import Any

# Verified serving on fonts.juniorbay.com 2026-09-07. A family named here that the service cannot serve
# emits CSS pointing at a 404, which is worse than no webfont at all -- so this list is an ALLOW-LIST, not
# a wish list, and nothing joins it without being checked.
SERVABLE_FAMILIES = {
    "Inter", "Montserrat", "Poppins", "Lato", "Merriweather", "Oswald", "Roboto", "Raleway", "Nunito",
    # Added 2026-09-07: converted from the TTFs already in the bucket and registered in fonts-api. Both
    # are STATIC -- one file per weight -- because the source TTFs are, which is the constraint recorded
    # in FONT_SERVICE.md section 10.
    "Source Code Pro", "Source Sans Pro",
}

# Six pairings across sixteen colour presets. Not one each: several presets are colour mimicry of a
# platform (tiktok, linkedin, youtube, twitter) where distinctive type would be arbitrary, and imitating a
# platform's actual typeface is a licensing question nobody needs.
#
# Two families per pairing, never three. Every family is a download on a page already tuned for LCP.
PAIRINGS: dict[str, dict[str, str]] = {
    "modern": {"heading": "Inter", "body": "Inter"},
    "editorial": {"heading": "Merriweather", "body": "Inter"},
    "geometric": {"heading": "Montserrat", "body": "Lato"},
    "friendly": {"heading": "Nunito", "body": "Nunito"},
    "impact": {"heading": "Poppins", "body": "Lato"},
    # techno-green gets its own: a monospace headline reads as technical in a way no sans does, which is
    # the whole point of that preset.
    "terminal": {"heading": "Source Code Pro", "body": "Source Sans Pro"},
    "elegant": {"heading": "Raleway", "body": "Lato"},
}

# preset name -> pairing. Platform-mimicry presets take `modern`: neutral, one family, cheapest to load.
PRESET_PAIRINGS: dict[str, str] = {
    "clean-slate": "modern",
    "professional-gray": "modern",
    "trust-blue": "modern",
    "linkedin-blue": "modern",
    "twitter-dark": "modern",
    "tiktok-dark": "modern",
    "youtube-red": "modern",
    "instagram-gradient": "friendly",
    "coral-sunrise": "friendly",
    "natural-calm": "editorial",
    "midnight-luxe": "elegant",
    "royal-velvet": "elegant",
    "rose-minimalist": "elegant",
    "fire-sale": "impact",
    "techno-green": "terminal",
    "cyber-pulse": "geometric",
}

# The preset applied when a page names none. MUST match the renderer's colour fallback: a page showing
# techno-green colours and modern type would mean the preset does not actually carry the visual identity.
DEFAULT_PRESET = "techno-green"

# The existing sentinel for "no webfont, use the fallback stack". It is an explicit CHOICE, not an
# absence, so it beats the preset like any other page-level decision -- a tenant who picked system fonts
# should not have a preset quietly hand them a download.
SYSTEM = "system"

ROLES = ("heading", "body")
# `accent` is never PROPOSED by a preset -- a third family is a third download on a page tuned for LCP --
# but a tenant who explicitly sets one keeps it. Proposing and permitting are different questions.
OPTIONAL_ROLES = ("accent",)


def pairing_for_preset(preset: Any) -> dict[str, str]:
    """The fonts a preset proposes. An absent or unknown preset falls back the same way colours do."""
    name = str(preset or "").strip() or DEFAULT_PRESET
    pairing = PRESET_PAIRINGS.get(name) or PRESET_PAIRINGS[DEFAULT_PRESET]
    return dict(PAIRINGS[pairing])


def _named_family(source: Any, role: str) -> str:
    """A family explicitly chosen for `role`, or "".

    Deliberately NOT filtered against SERVABLE_FAMILIES. Dropping a name we cannot serve would silently
    replace the tenant's explicit choice with the preset's, which is the failure this whole design exists
    to avoid. The allow-list belongs at the request, not here.
    """
    if not isinstance(source, dict):
        return ""
    entry = source.get(role)
    return str((entry.get("family") if isinstance(entry, dict) else entry) or "").strip()


def is_system(family: Any) -> bool:
    return str(family or "").strip().lower() == SYSTEM


def resolve_families(page: Any, preferences: Any = None) -> dict[str, str]:
    """The family for each role after applying all four levels."""
    page = page if isinstance(page, dict) else {}
    theme = page.get("theme") if isinstance(page.get("theme"), dict) else {}
    resolved = pairing_for_preset(theme.get("preset"))

    # The tenant default applies ONLY behind the explicit toggle. Without it, idly picking a font in
    # preferences would silently re-typeset every page they have ever published.
    preferences = preferences if isinstance(preferences, dict) else {}
    tenant_fonts = preferences.get("fonts") if isinstance(preferences.get("fonts"), dict) else {}
    if tenant_fonts.get("override_presets"):
        for role in ROLES:
            family = _named_family(tenant_fonts, role)
            if family:
                resolved[role] = family

    # The page has the last word, and may name a role no preset proposes.
    for role in ROLES + OPTIONAL_ROLES:
        family = _named_family(theme.get("fonts"), role)
        if family:
            resolved[role] = family
    return resolved


def families_to_load(page: Any, preferences: Any = None) -> list[str]:
    """The distinct families a page actually needs, sorted for a stable URL.

    Sorted because the stylesheet URL is a cache key: the same page must not produce two different URLs
    and pay twice for one download.
    """
    # Filtered HERE: a family the service cannot serve would produce a stylesheet request that 404s, which
    # is worse than no webfont. It still appears in the CSS stack -- see _named_family.
    return sorted({
        family for family in resolve_families(page, preferences).values()
        if family in SERVABLE_FAMILIES
    })
