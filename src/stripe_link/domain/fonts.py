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

# Every family the fonts-api catalogue can actually serve, audited 2026-09-08 against the files in the
# bucket: all 34 catalogued families resolve to a file that exists, so this list is the catalogue minus
# three deliberate exclusions.
#
# A family named here that the service cannot serve emits CSS pointing at a 404, which is worse than no
# webfont at all -- so this stays an ALLOW-LIST, not a wish list, and nothing joins it unchecked.
#
# NOT offered, and why -- each would be a mistake to "restore":
#   Themify        an ICON font. 0 of 62 Latin letters and digits are mapped (verified via its cmap), so
#                  setting body text in it renders glyph soup, not words. Fontawesome is the same and is
#                  not in the catalogue at all.
#   Futura         a commercial typeface. Serving it to every tenant from a public font service is a
#                  licensing exposure, not a technical one, and it carries neither a 400 nor a 700 face.
#   Ubuntu Titling the Junior Bay wordmark face (self-hosted for the dashboard). Handing the platform's own
#                  brand type to tenants is a branding decision, and it has no 400 for body text.
SERVABLE_FAMILIES = {
    "Aileron", "Arapey", "Bebas Neue", "Comic Relief", "DM Serif Display", "Heebo", "Inter", "Karla",
    "Konya", "Lato", "Lora", "Merriweather", "Merriweather Sans", "Montserrat", "Nunito", "Open Sans",
    "Oswald", "Overpass", "Overpass Mono", "PT Sans Caption", "PT Serif", "Playfair", "Poppins",
    "Quantico", "Quicksand", "Raleway", "Roboto", "Rubik", "Slabo", "Source Code Pro", "Source Sans 3", "Source Sans Pro",
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
    # Source Sans 3, not Source Sans Pro: the successor is variable (wght 200-900) in one file, so a
    # heading at 600 or 800 gets a real face rather than a faked bold. Source Sans Pro stays SERVABLE for
    # pages that already name it -- retiring a family out from under a published page is not an upgrade.
    "terminal": {"heading": "Source Code Pro", "body": "Source Sans 3"},
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

# Weights to request. A VARIABLE family ignores this and returns its whole range in one file; a STATIC
# family returns one file per weight, and without a list the service sends 400 only -- so every heading
# rendered at 600-900 had no matching face and the browser faked or dropped the font. That is exactly what
# went wrong the first time this shipped.
#
# 400 and 700 are enough: body text is 400, and the template's 600/700/800/900 headings all resolve to the
# 700 face. Adding 600 would double a static family's download to buy a weight nobody can see.
REQUEST_WEIGHTS = ("400", "700")

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
    # An imported family is excluded too, but for the opposite reason: the SERVICE cannot serve it, so
    # asking would 404. The renderer emits its @font-face itself -- see imported_faces_for.
    tenant_own = imported_families(preferences)
    return sorted({
        family for family in resolve_families(page, preferences).values()
        if family in SERVABLE_FAMILIES and family not in tenant_own
    })

def imported_fonts(preferences: Any) -> list[dict[str, Any]]:
    """The tenant's own uploaded faces, from their profile's `fonts.imported`.

    These are NOT in SERVABLE_FAMILIES and never will be: that list is the fonts-api catalogue, which is a
    hardcoded dict shared by every tenant. A tenant's own font is theirs alone, so the RENDERER emits its
    @font-face directly rather than asking the service for a family it has never heard of.
    """
    preferences = preferences if isinstance(preferences, dict) else {}
    fonts = preferences.get("fonts") if isinstance(preferences.get("fonts"), dict) else {}
    entries = fonts.get("imported")
    if not isinstance(entries, list):
        return []
    return [
        entry for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("family") or "").strip()
        and str(entry.get("url") or "").strip()
    ]


def imported_families(preferences: Any) -> set[str]:
    """Family names the tenant has uploaded, so the renderer can tell them from catalogue families."""
    return {str(entry["family"]).strip() for entry in imported_fonts(preferences)}


def imported_faces_for(page: Any, preferences: Any) -> list[dict[str, Any]]:
    """The uploaded faces THIS page actually uses, so a page never carries a font it does not render.

    A tenant may import a dozen fonts; a page resolves at most three roles. Emitting all of them would put
    every upload on every page, which is the opposite of what the subsetting work was for.
    """
    used = set(resolve_families(page, preferences).values())
    return [entry for entry in imported_fonts(preferences) if str(entry["family"]).strip() in used]

