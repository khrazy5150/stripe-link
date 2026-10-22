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
# What ONE page generation may order, now that the AI is meant to illustrate a whole page rather than
# only its hero. Ten, not seven: "one per control" undercounts, because before_after is inherently a
# PAIR and a link_cards row is usually three or four. Sizing to seven would mean revisiting this the
# first time somebody used a three-card row.
#
# Still a CAP rather than no limit. A fully illustrated page is ~$0.09-0.13 of images on top of
# $0.105 of generation; unbounded, one generation could order any number without anybody choosing to.
#
# The shapes come from `image_ratios.json`, which is why the cost is not a flat multiple: hero,
# page_ribbon and before_after default to landscape and carry the 1.5x non-square multiplier, while
# content_block, photo, link_cards and coupon default to square.
MAX_IMAGES_PER_PAGE_GENERATION = 10


def clean_qualities(values: Any, *, fallback: Any = None) -> tuple[str, ...]:
    """A GRANTED SET of qualities, ordered cheapest-first, or the fallback when nothing is usable.

    A SET and not a ceiling. "Up to medium" could only ever express a prefix of the ladder, so a plan
    granting low and high but not medium was unsayable -- and the implied ordering meant lifting a
    ceiling silently granted everything beneath it, which is a pricing decision made by a comparison
    operator rather than by a person.

    Order is imposed rather than taken from the caller, because `[0]` has to be the CHEAPEST grant:
    that is what an unrecognised request falls back to, and sorting is how it stays the cheapest no
    matter which order the boxes were ticked.
    """
    if isinstance(values, str):
        values = [values]
    seen = {str(v or "").strip().lower() for v in (values or []) if str(v or "").strip()}
    kept = tuple(q for q in QUALITIES if q in seen)
    if kept:
        return kept
    if fallback is None:
        return (DEFAULT_QUALITY,)
    return clean_qualities(fallback, fallback=[DEFAULT_QUALITY])


def qualities_up_to(ceiling: str) -> tuple[str, ...]:
    """The old CEILING read as a set, for rows written before the set existed.

    `ai_image_quality: "medium"` meant low and medium, so that is what it becomes. Nothing is migrated:
    a row keeps whichever field it has and this makes them mean the same thing.

    Computed straight from the ladder, NOT via `clamp_quality` -- that function calls this one for a
    string argument, and the pair recursed until the stack gave out.
    """
    name = str(ceiling or "").strip().lower()
    if name not in QUALITIES:
        name = DEFAULT_QUALITY
    return QUALITIES[:QUALITIES.index(name) + 1]


def rank(quality: str) -> int:
    """Where a quality sits on the price ladder. Unknown sorts to the cheapest, never the dearest."""
    try:
        return QUALITIES.index(str(quality or "").strip().lower())
    except ValueError:
        return 0


def clamp_quality(wanted: Any, allowed: Any) -> str:
    """The quality we will actually send: what was asked for if it is granted, else the cheapest grant.

    CLAMPS rather than refuses. A request for something ungranted is not an attack to repel -- the
    control that offered it was built from the same grant, so it means a stale page or a caller that
    has not been updated, and quietly giving them what they ARE entitled to costs us nothing. What must
    never happen is sending a dearer one than was granted.

    `allowed` may be a set, a list, or a single string (a ceiling from an older row), because this is
    reached from both shapes and the caller should not have to know which.

    THE RULE: the dearest grant that is not dearer than what was asked for; failing that, the cheapest
    grant. That generalises the old ceiling exactly -- granted {low, medium} and asked for high still
    yields medium, not low -- while giving a non-contiguous grant a sensible answer too: granted
    {low, high} and asked for medium yields low, because low is what they are entitled to that is no
    more than they asked for. Never dearer than requested unless nothing cheaper is granted at all.
    """
    granted = clean_qualities(allowed) if not isinstance(allowed, str) else qualities_up_to(allowed)
    wanted = str(wanted or "").strip().lower()
    if wanted not in QUALITIES:
        wanted = DEFAULT_QUALITY
    affordable = [q for q in granted if rank(q) <= rank(wanted)]
    return affordable[-1] if affordable else granted[0]


def allowed_qualities(allowed: Any) -> list[dict[str, Any]]:
    """What this tenant may choose, for the UI to RENDER rather than decide.

    A one-entry list renders no control at all, which is why there is no quality selector on a plan
    granting only `low` -- without anyone having decided there would not be one. Tick a second box on
    the plan and the control appears, with no change to the page that draws it.
    """
    granted = clean_qualities(allowed) if not isinstance(allowed, str) else qualities_up_to(allowed)
    return [{"value": q, "label": QUALITY_LABELS.get(q, q), "credits": QUALITY_CREDITS.get(q, 1)}
            for q in granted]


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


def refusal(used: int, allowance: int, source: str) -> str:
    """Why this tenant cannot generate an image, worded for them.

    NOT `ai_quota.may_generate`, which is page-shaped and ends "or connect your own AI provider key".
    There is no BYO-key path for images -- the platform's account pays for every one -- so that
    sentence sends a tenant to a screen that cannot help them. A notice has to name an action that
    works, or it is noise wearing a helpful face.
    """
    used, allowance = int(used or 0), int(allowance or 0)
    if allowance <= 0:
        if source == "free":
            return ("AI images are part of Premium. They are also included for the rest of your "
                    "14-day trial.")
        return "AI images are not included on your plan."
    if source == "trial":
        return (f"You have used all {allowance} AI images in your trial. "
                f"Subscribe to Premium for more.")
    return (f"You have used your {allowance} AI images for this month. "
            f"They reset on the 1st.")
