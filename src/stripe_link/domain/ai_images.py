"""AI image requests: what a tenant may ask for, and what we send (pure -- no I/O).

The capability lives in `../sam/ai-image-generator`; this module is the POLICY half, and the split is
the same one every other AI surface here follows. The service knows how to make an image and nothing
about plans. This file knows what a plan permits and nothing about providers.

Two things it exists to stop:

QUALITY IS A CEILING, NOT A CONTROL. `high` costs 15x `low` per image and the parameter travels in the
request body, so a UI that omits the dropdown is not a limit -- it is a suggestion. Everything is
clamped here, server-side, against a number that came off the tenant profile.

STYLE IS A PROMPT FRAGMENT, NOT AN API FEATURE. The provider has no `style` parameter -- proven, not
assumed: sending one returns `invalid_request_error / Unknown parameter: 'style'` (2026-10-20). The
services that appear to offer styles are appending text, and so do we. One vocabulary, read from config
with the table below as fallback, so a style the tenant can pick is a style the page builder can request
and the two cannot drift.

The fragments steer SCENE AND MOOD on purpose. A photorealistic rendering of a product nobody
photographed, on a page where someone is about to pay, is the visual form of an assertion we were not
given -- the same objection `ai_floor.py` raises to unsourced claims and `ai_elements.py` raises to
generated testimonials. The real product is on the price card; the hero is for the feeling.
"""

from __future__ import annotations

from typing import Any

# Cheapest first. The ORDER is the semantics: a ceiling permits itself and everything below it, so this
# tuple is what makes "up to medium" meaningful without a second table of comparisons.
QUALITIES = ("low", "medium", "high")

QUALITY_LABELS = {"low": "Standard", "medium": "Detailed", "high": "High detail"}

# What one image of each quality costs the allowance. All 1 today because every tier is `low`, so there
# is nothing to weigh. It exists as a seam rather than a constant because `consume_if_available` already
# takes `by=`, which means the day a tier offers `high` at 4x the price, this table is the only edit --
# no new column, no backfill, and the ledger's history stays comparable either side of the change.
QUALITY_CREDITS = {"low": 1, "medium": 1, "high": 1}

DEFAULT_QUALITY = "low"

# Hero shape. Square is what a product shot wants, and the hero is explicitly not that -- the product
# photographs are already on the price card.
HERO_SIZE = "1536x1024"

# The fallback vocabulary. Config wins (`ai_image_styles` on the CONFIG row) so these can be tuned from
# the Admin Site as we learn what makes a good hero, exactly like the allowances.
DEFAULT_STYLES: tuple[dict[str, str], ...] = (
    {"value": "lifestyle", "label": "Lifestyle",
     "fragment": "candid lifestyle scene, natural window light, shallow depth of field"},
    {"value": "studio", "label": "Studio",
     "fragment": "minimal still life, single subject, seamless backdrop, soft shadow"},
    {"value": "illustrated", "label": "Illustrated",
     "fragment": "flat vector illustration, bold shapes, limited palette"},
    {"value": "soft_3d", "label": "Soft 3D",
     "fragment": "soft 3D render, rounded forms, studio lighting, pastel palette"},
    {"value": "graphic", "label": "Graphic",
     "fragment": "high-contrast poster, strong geometry, saturated colour"},
)

DEFAULT_STYLE = "lifestyle"

MAX_PROMPT = 2000
MAX_IMAGES_PER_REQUEST = 4
# One image per PAGE generation. A page becomes $0.105 + $0.0165; unbounded, one generation could order
# four without anybody choosing to.
MAX_IMAGES_PER_PAGE_GENERATION = 1


def rank(quality: str) -> int:
    """Where a quality sits on the price ladder. Unknown sorts to the cheapest, never the dearest."""
    try:
        return QUALITIES.index(str(quality or "").strip().lower())
    except ValueError:
        return 0


def clamp_quality(wanted: str, ceiling: str) -> str:
    """The quality we will actually send: what was asked for, or the ceiling, whichever is cheaper.

    CLAMPS rather than refuses. A request above the ceiling is not an attack to repel -- the control
    that offers it was built from the same ceiling, so it means a stale page or a caller that has not
    been updated, and silently giving them the quality they are entitled to is the kinder answer that
    costs us nothing. What must never happen is sending the dearer one.
    """
    ceiling = str(ceiling or "").strip().lower()
    ceiling = ceiling if ceiling in QUALITIES else DEFAULT_QUALITY
    wanted = str(wanted or "").strip().lower()
    if wanted not in QUALITIES:
        return ceiling if rank(DEFAULT_QUALITY) > rank(ceiling) else DEFAULT_QUALITY
    return wanted if rank(wanted) <= rank(ceiling) else ceiling


def allowed_qualities(ceiling: str) -> list[dict[str, Any]]:
    """What this tenant may choose, for the UI to RENDER rather than decide.

    A one-entry list renders no control at all, which is why there is no quality selector today without
    anyone having decided there would not be one. When a tier lifts the ceiling this list grows and the
    control appears, with no change to the page that draws it.
    """
    top = rank(clamp_quality(ceiling, ceiling))
    return [{"value": q, "label": QUALITY_LABELS.get(q, q), "credits": QUALITY_CREDITS.get(q, 1)}
            for q in QUALITIES[:top + 1]]


def credits_for(quality: str, count: int = 1) -> int:
    """What this request costs the allowance. Never less than the number of images."""
    per = QUALITY_CREDITS.get(str(quality or "").strip().lower(), 1)
    return max(1, int(per)) * max(1, int(count or 1))


def styles(config: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """The style vocabulary, config first. Entries missing a value or a fragment are dropped rather
    than rendered half-formed -- a style whose fragment is empty is a button that does nothing."""
    configured = (config or {}).get("ai_image_styles")
    if isinstance(configured, list) and configured:
        out = []
        for entry in configured:
            if not isinstance(entry, dict):
                continue
            value = str(entry.get("value") or "").strip()
            fragment = str(entry.get("fragment") or "").strip()
            if value and fragment:
                out.append({"value": value, "label": str(entry.get("label") or value).strip(),
                            "fragment": fragment})
        if out:
            return out
    return [dict(style) for style in DEFAULT_STYLES]


def style_fragment(value: str, config: dict[str, Any] | None = None) -> str:
    """The text a style appends, or "" for no style. An unknown style is no style, never an error:
    a stale page naming a style we have since retired should still generate."""
    wanted = str(value or "").strip().lower()
    if not wanted:
        return ""
    for style in styles(config):
        if style["value"] == wanted:
            return style["fragment"]
    return ""


def compose_prompt(prompt: str, style: str = "", config: dict[str, Any] | None = None) -> str:
    """What we actually send: the tenant's words, then the style.

    The tenant's text comes FIRST and is never edited. The fragment is appended as a trailing clause
    because a prefix reads as the instruction and would quietly outrank what the person asked for --
    the whole complaint about the page generator was that the questionnaire's shape became the
    semantics, and this is the same mistake available in one line.
    """
    prompt = str(prompt or "").strip()
    fragment = style_fragment(style, config)
    composed = f"{prompt}. {fragment}" if prompt and fragment else (prompt or fragment)
    return composed[:MAX_PROMPT]
