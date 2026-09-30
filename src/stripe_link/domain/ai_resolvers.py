"""The decision brain: what code decides, what rules decide, what the AI is left to decide (§A.4).

The precedence chain, strongest first:

    explicit request  >  tenant brand/preferences  >  platform default rules  >  AI judgment

Every resolver here answers in that order and returns WHY, because a page that came out wrong is
otherwise unarguable -- "the AI chose it" is not a diagnosis. Where the AI genuinely should have a say
it gets a SHORTLIST rather than an open choice: rules narrow the space, the model picks inside it.

These are shared with the manual flow on purpose. A resolver only the AI consults is a second source
of truth waiting to disagree with the builder.
"""

from __future__ import annotations

from typing import Any

from stripe_link.domain.ai_floor import generatable_sections
from stripe_link.domain.composition import baseline_order, excluded_sections, supported_goals

EXPLICIT, TENANT, RULES, AI = "explicit", "tenant", "rules", "ai"

# Curated palettes, keyed by what a category FEELS like rather than what it sells. The AI never gets an
# open hex value: bounded tokens are the whole reason the composition system can promise a coherent
# page (Part B, "freedom in what, rails on how it looks").
CATEGORY_PRESETS: dict[str, tuple[str, ...]] = {
    "supplement": ("techno-green", "natural-calm", "cyber-pulse"),
    "fitness": ("techno-green", "cyber-pulse", "fire-sale"),
    "beauty": ("rose-minimalist", "coral-sunrise", "clean-slate"),
    "luxury": ("midnight-luxe", "royal-velvet", "clean-slate"),
    "finance": ("trust-blue", "clean-slate", "midnight-luxe"),
    "professional": ("trust-blue", "clean-slate", "midnight-luxe"),
    "food": ("coral-sunrise", "natural-calm", "fire-sale"),
    "outdoors": ("natural-calm", "techno-green", "trust-blue"),
    "tech": ("cyber-pulse", "midnight-luxe", "techno-green"),
}
FALLBACK_PRESETS = ("clean-slate", "trust-blue", "coral-sunrise")

# The tenant's VOICE, as a palette. `tone` is already asked for, already bounded to five values, and until
# now changed only the words -- so every generated page came out "clean-slate", the first fallback, whatever
# the tenant said they sounded like (author, 2026-09-29).
#
# Tone RANKS the category's shortlist rather than replacing it: a playful supplement brand is still a
# supplement brand, and a palette that ignores the category to chase the adjective is a worse answer than
# one that respects both. Anything the category did not offer is appended, so a tone preference can still
# be honoured when the category has no opinion.
#
# Deliberately a table and not the model's judgment. Picking a palette is a taste call with nothing to
# ground it, and this file's whole contract is that rules narrow and the model picks inside -- a resolver
# that is deterministic can be explained to a tenant ("you said playful"), reproduced, and tested. The
# shortlist is still returned, so handing the final pick to the model later needs no rework here.
# Leads chosen by the author 2026-09-29. Three are the Socialite palettes (plans/SOCIALITE_PARITY.md), and
# they earn the slot by being palettes people already have a FEELING about: a tenant who says "playful" and
# gets the Instagram gradient recognises the answer, where "coral-sunrise" is a name they have to go and look
# at. The second and third entries stay non-social, so a category that dislikes the lead still has somewhere
# ordinary to land.
TONE_PRESETS: dict[str, tuple[str, ...]] = {
    "direct": ("clean-slate", "trust-blue", "techno-green"),
    "warm": ("youtube-red", "coral-sunrise", "natural-calm"),
    "playful": ("instagram-gradient", "coral-sunrise", "fire-sale"),
    "technical": ("linkedin-blue", "cyber-pulse", "techno-green"),
    "premium": ("midnight-luxe", "royal-velvet", "rose-minimalist"),
}


def _decision(value: Any, source: str, why: str, shortlist=None) -> dict[str, Any]:
    out = {"value": value, "source": source, "why": why}
    if shortlist is not None:
        out["shortlist"] = list(shortlist)
    return out


def resolve_preset(*, requested: str = "", tenant_preset: str = "", category: str = "", tone: str = "",
                   supported: set[str] | None = None) -> dict[str, Any]:
    """Which palette. Returns the decision AND the shortlist the AI may choose within.

    A tenant who already has a preset keeps it even when the category suggests otherwise: their other
    pages look like that, and a generated page that does not match their own site is a worse answer
    than an imperfect palette.

    `tone` LEADS when the tenant stated one (see TONE_PRESETS): a voice is something they said, and a
    category inferred from a taxonomy field should not overrule it. The category is demoted rather than
    discarded -- its presets fill the rest of the shortlist.
    """
    known = supported or set()

    def ok(value):
        return bool(value) and (not known or value in known)

    if ok(requested):
        return _decision(requested, EXPLICIT, "the request named this preset")
    if ok(tenant_preset):
        return _decision(tenant_preset, TENANT, "the tenant's other pages already use this preset")
    category_key = str(category or "").strip().lower()
    shortlist = [p for p in CATEGORY_PRESETS.get(category_key, FALLBACK_PRESETS) if ok(p)] \
        or [p for p in FALLBACK_PRESETS if ok(p)]
    if not shortlist:
        return _decision("", RULES, "no supported preset could be resolved")

    tone_key = str(tone or "").strip().lower()
    if tone_key in TONE_PRESETS:
        # VOICE OUTRANKS CATEGORY, revised 2026-09-29. Tone is something the tenant SAID; category is
        # inferred from a taxonomy field, and an inference should not overrule a statement. The earlier
        # ranking-only version was defensible until the author chose social palettes as the leads: none of
        # them appear in any category shortlist, so "category keeps its say" would have meant the chosen
        # voice applied to uncategorised products only -- which is most of the value gone.
        #
        # The category is not discarded, it is demoted: its presets fill the rest of the shortlist, so the
        # model (or a later tenant override) still has the sector's palettes to hand.
        ranked = [p for p in TONE_PRESETS[tone_key] if ok(p)]
        ranked += [p for p in shortlist if p not in ranked]
        if ranked:
            return _decision(ranked[0], AI,
                             f"the '{tone_key}' voice leads here; category "
                             f"'{category or 'unknown'}' fills the rest and the model may pick among them",
                             shortlist=ranked)

    return _decision(shortlist[0], AI,
                     f"category '{category or 'unknown'}' suits these; the model may pick among them",
                     shortlist=shortlist)


def resolve_sections(*, offer_type: str = "", goal: str = "",
                     requested: list[str] | None = None) -> dict[str, Any]:
    """Which sections the AI may write, in the composer's own order.

    Three filters, and the order matters: the composer decides what belongs on this KIND of page, the
    §A.7 floor removes what the AI may never author, and an explicit request may only narrow what is
    left. A request cannot ADD a floored section -- that is the point of a floor.
    """
    baseline = baseline_order(goal) or baseline_order("")
    excluded = excluded_sections(offer_type)
    allowed = generatable_sections([s for s in baseline if s not in excluded])
    if requested:
        narrowed = [s for s in allowed if s in set(requested)]
        refused = sorted(set(requested) - set(narrowed))
        return _decision(narrowed or allowed, EXPLICIT if narrowed else RULES,
                         ("the request named these" if narrowed else
                          "none of the requested sections are available here"),
                         shortlist=allowed) | ({"refused": refused} if refused else {})
    return _decision(allowed, RULES,
                     f"the composer's order for offer_type '{offer_type or 'any'}', goal "
                     f"'{goal or 'none'}', minus what the AI may not author", shortlist=allowed)


def resolve_goal(*, requested: str = "", tenant_default: str = "") -> dict[str, Any]:
    supported = set(supported_goals())
    if requested in supported:
        return _decision(requested, EXPLICIT, "the request named this goal")
    if tenant_default in supported:
        return _decision(tenant_default, TENANT, "the tenant's usual goal")
    return _decision("", RULES, "no goal -- the baseline composition applies")


def resolve_brand(*, requested: str = "", business_name: str = "", product_brand: str = "") -> dict[str, Any]:
    """Whose name goes on the page. NEVER the AI's invention -- a brand is a fact about a business."""
    for value, source, why in ((requested, EXPLICIT, "the request named this brand"),
                               (business_name, TENANT, "the tenant's business name"),
                               (product_brand, RULES, "the product's own brand")):
        if str(value or "").strip():
            return _decision(str(value).strip(), source, why)
    return _decision("", RULES, "no brand is known; the page will not assert one")


def resolution_log(decisions: dict[str, dict[str, Any]]) -> list[str]:
    """One readable line per decision, for the generation job's record.

    A page a tenant dislikes is otherwise unarguable. "preset=techno-green (ai): category 'supplement'
    suits these" tells them which lever to pull; "the AI chose it" tells them nothing.
    """
    return [f"{name}={d.get('value')!r} ({d.get('source')}): {d.get('why')}"
            for name, d in sorted((decisions or {}).items())]
