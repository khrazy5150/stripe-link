"""Page Composer — the single place that decides which sections a landing page renders.

Business logic, not rendering. Both renderers obey it: the Python publisher calls compose_page() here, and
the Vue builder mirrors the same decisions from the SAME rules file (composition_rules.json), so a section
can never appear in the preview and not on the published page. See plans/PAGE_COMPOSER.md.

Rules (composition_rules.json) are an ALLOW-LIST: per offer_type, the section keys visible by default.
A section whose key isn't "governed" (the composable body elements — testimonials, faq, …) shows whenever
it's present (adding it IS the opt-in). The tenant overrides a governed default via page.composition.overrides
(compact: {section_key: {enabled: bool}}) — default != forced.

Composition has two axes (plans/LANDING_PAGE_GOAL_COMPOSITION.md): offer_type (WHAT the page sells) sets the
base sections, and the page's goal (WHY / where its traffic comes from) enables capability packs on top.
Packs are union-only, so a page without a goal composes exactly as it did before goals existed.
"""

from __future__ import annotations

import json
from pathlib import Path

from stripe_link.domain.opportunities import derived_offer_type
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent.parent / "composition_rules.json"
try:
    with _RULES_PATH.open(encoding="utf-8") as _fh:
        RULES: dict[str, Any] = json.load(_fh)
except (OSError, ValueError):
    # Degrade safely if the rules file is somehow unbundled: nothing governed -> every section visible
    # (no composition), rather than crashing the Lambda at import.
    RULES = {"elements": {}, "governed_sections": [], "offer_types": {}, "packs": {}, "goals": {}}

ELEMENTS: dict[str, Any] = RULES.get("elements") or {}
_GOVERNED: set[str] = set(RULES.get("governed_sections") or [])
_OFFER_TYPES: dict[str, Any] = RULES.get("offer_types") or {}
_PACKS: dict[str, Any] = RULES.get("packs") or {}
_GOALS: dict[str, Any] = RULES.get("goals") or {}


def element(section_type: str) -> dict[str, Any]:
    """Catalog metadata for a section type (label / ui / kind / channel / heading_role / tokens)."""
    return ELEMENTS.get(str(section_type or ""), {})


def element_label(section_type: str) -> str:
    return str(element(section_type).get("label") or section_type)


def element_channel(section_type: str) -> str:
    """Where a section renders: "body" (visible markup), "head" (meta / JSON-LD) or "sidecar" (its own
    artifact, e.g. /llms.txt). The renderer routes composed sections by this, so head sections are ordinary
    composed sections that simply don't paint pixels (plans/LANDING_PAGE_GOAL_COMPOSITION.md). Unknown or
    unset defaults to "body" — the safe assumption for any element predating channels."""
    return str(element(section_type).get("channel") or "body")


def section_key(section_type: str) -> str:
    """Canonical composition key. Post-Builder-Reframe the key IS the section type (no aliasing)."""
    return str(section_type or "")


def _offer_type_rule(offer_type: str) -> dict[str, Any]:
    return _OFFER_TYPES.get(str(offer_type or ""), _OFFER_TYPES.get("single", {}))


def supported_goals() -> list[str]:
    """Every goal a page may legally store, INCLUDING deprecated ones. Deleting a goal outright would strand
    pages that already reference it — they would stop validating, so they could not be saved or even
    re-rendered. Retiring is therefore additive: mark it `deprecated` and it stays valid forever while
    disappearing from the wizard (see offerable_goals)."""
    return list(_GOALS.keys())


def offerable_goals() -> list[str]:
    """Goals a NEW page may choose — what the wizard lists. Excludes deprecated ones."""
    return [name for name, meta in _GOALS.items() if not (meta or {}).get("deprecated")]


def goal_deprecated(goal: str) -> bool:
    return bool((_GOALS.get(str(goal or "")) or {}).get("deprecated"))


def goal_label(goal: str) -> str:
    return str((_GOALS.get(str(goal or "")) or {}).get("label") or goal)


def goal_note(goal: str) -> str:
    return str((_GOALS.get(str(goal or "")) or {}).get("note") or "")


def goal_packs(goal: str) -> list[str]:
    """Capability packs a goal turns on. An unknown/absent goal enables none — which is exactly how pages
    composed before goals existed, so old pages need no migration."""
    return list((_GOALS.get(str(goal or "")) or {}).get("packs") or [])


def pack_seeds(goal: str) -> list[str]:
    """Content-bearing element types the create wizard should seed for this goal (deduped, in pack order).
    These render nothing until the tenant fills them in, and are tenant-owned once seeded — the goal never
    retracts them."""
    seeds: list[str] = []
    for name in goal_packs(goal):
        for seed in (_PACKS.get(name) or {}).get("seeds") or []:
            if seed not in seeds:
                seeds.append(seed)
    return seeds


def goal_sections(goal: str) -> set[str]:
    """Governed sections the goal's packs turn on, unioned over the base. Empty until derived head/sidecar
    sections (structured_data, llms_txt) land — see plans/LANDING_PAGE_GOAL_COMPOSITION.md Phase 3."""
    return {
        key
        for name in goal_packs(goal)
        for key in ((_PACKS.get(name) or {}).get("sections") or [])
    }


def default_visible(offer_type: str, key: str, goal: str = "") -> bool:
    """Whether a governed section key is visible by DEFAULT for this offer_type + goal (before overrides).
    Base sections from the offer_type, unioned with the sections the goal's packs enable."""
    base = _offer_type_rule(offer_type).get("sections") or []
    return key in base or key in goal_sections(goal)


def is_section_visible(
    offer_type: str,
    section_type: str,
    overrides: dict[str, Any] | None = None,
    goal: str = "",
) -> bool:
    """Final visibility for one section: override wins, else the offer_type + goal default; ungoverned
    sections (body elements) are visible whenever present."""
    key = section_key(section_type)
    if key not in _GOVERNED:
        return True
    override = (overrides or {}).get(key)
    if isinstance(override, dict) and "enabled" in override:
        return bool(override.get("enabled"))
    return default_visible(offer_type, key, goal)


def page_overrides(page: dict[str, Any]) -> dict[str, Any]:
    composition = page.get("composition") or {}
    overrides = composition.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


def page_goal(page: dict[str, Any]) -> str:
    """The page's goal, or "" when it predates the goal axis (composes as base-only)."""
    return str((page or {}).get("goal") or "")


def compose_page(offer: dict[str, Any], page: dict[str, Any]) -> list[dict[str, Any]]:
    """The Renderable Page Model: page.sections filtered to those the composer deems visible. The renderer
    only iterates this — it never decides."""
    offer_type = derived_offer_type(offer or {})
    overrides = page_overrides(page)
    goal = page_goal(page)
    return [
        section for section in (page.get("sections") or [])
        if is_section_visible(offer_type, str(section.get("type") or ""), overrides, goal)
    ]


# Placement governs ORDER + draggability; visibility is the separate `enabled` axis above. Both the
# Python renderer and the Vue builder read these values from the one composition_rules.json, so there is
# no second list to drift (see plans/TODO.md, "silent agreement failures").
PLACEMENT_BANDS = ("lead", "pinned_top", "free", "pinned_bottom")


def element_placement(key: str) -> str:
    """Which band a section sits in. Unknown keys are treated as free — a new element is orderable
    until someone decides otherwise, which is the safe default for rendering."""
    return str((RULES.get("elements", {}).get(key) or {}).get("placement") or "free")


def is_movable(key: str) -> bool:
    """Only `free` sections may be dragged. The hero block is pinned on purpose."""
    return element_placement(key) == "free"


def baseline_order(goal: str = "") -> list[str]:
    """The default section sequence for a page nobody has reordered (plans/BUILDER_SECTION_ORDER.md 4a).

    A goal may override it wholesale via goals.<goal>.default_order; none do today, deliberately.
    """
    override = ((RULES.get("goals", {}).get(goal) or {}).get("default_order")) if goal else None
    return list(override or RULES.get("default_order", []))


def order_section_keys(keys, tenant_order=(), goal: str = "") -> list[str]:
    """Sort section keys into lead -> pinned_top -> tenant-ordered free -> pinned_bottom.

    `tenant_order` is the tenant's drag order. Keys missing from it fall back to the BASELINE order, so a
    tenant who never drags anything still gets a researched sequence, and a newly added section lands in a
    sensible place instead of vanishing to one end. A key in neither list sorts last rather than first --
    an unplaced element should not silently jump to the top of the page.
    """
    keys = list(keys)
    baseline = {key: index for index, key in enumerate(baseline_order(goal))}
    rank = {key: index for index, key in enumerate(tenant_order)}
    fallback = len(rank)
    tail = len(baseline)

    def sort_key(key):
        band = element_placement(key)
        band_index = PLACEMENT_BANDS.index(band) if band in PLACEMENT_BANDS else PLACEMENT_BANDS.index("free")
        within = rank.get(key, fallback + baseline.get(key, tail))
        return (band_index, within)

    return [key for key in sorted(keys, key=sort_key) if element_placement(key) != "none"]


def recommended_section_keys(offer_type: str, goal: str = "") -> list[str]:
    """Governed sections visible by default for this offer_type + goal (the builder's 'Recommended' group)."""
    return [key for key in RULES.get("governed_sections", []) if default_visible(offer_type, key, goal)]


def optional_section_keys(offer_type: str, goal: str = "") -> list[str]:
    """Governed sections hidden by default — the tenant can opt them in ('Other available' group)."""
    return [key for key in RULES.get("governed_sections", []) if not default_visible(offer_type, key, goal)]


def allowed_ctas(offer_type: str) -> list[str]:
    return list(_offer_type_rule(offer_type).get("allowed_ctas") or [])
