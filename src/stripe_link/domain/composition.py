"""Page Composer — the single place that decides which sections a landing page renders.

Business logic, not rendering. Both renderers obey it: the Python publisher calls compose_page() here, and
the Vue builder mirrors the same decisions from the SAME rules file (composition_rules.json), so a section
can never appear in the preview and not on the published page. See plans/PAGE_COMPOSER.md.

Rules (composition_rules.json) are an ALLOW-LIST: per offer_type, the section keys visible by default.
A section whose key isn't "governed" (the composable body elements — testimonials, faq, …) shows whenever
it's present (adding it IS the opt-in). The tenant overrides a governed default via page.composition.overrides
(compact: {section_key: {enabled: bool}}) — default != forced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent.parent / "composition_rules.json"
try:
    with _RULES_PATH.open(encoding="utf-8") as _fh:
        RULES: dict[str, Any] = json.load(_fh)
except (OSError, ValueError):
    # Degrade safely if the rules file is somehow unbundled: nothing governed -> every section visible
    # (no composition), rather than crashing the Lambda at import.
    RULES = {"elements": {}, "governed_sections": [], "offer_types": {}}

ELEMENTS: dict[str, Any] = RULES.get("elements") or {}
_GOVERNED: set[str] = set(RULES.get("governed_sections") or [])
_OFFER_TYPES: dict[str, Any] = RULES.get("offer_types") or {}


def element(section_type: str) -> dict[str, Any]:
    """Catalog metadata for a section type (label / ui / kind / channel / heading_role / tokens)."""
    return ELEMENTS.get(str(section_type or ""), {})


def element_label(section_type: str) -> str:
    return str(element(section_type).get("label") or section_type)


def section_key(section_type: str) -> str:
    """Canonical composition key. Post-Builder-Reframe the key IS the section type (no aliasing)."""
    return str(section_type or "")


def _offer_type_rule(offer_type: str) -> dict[str, Any]:
    return _OFFER_TYPES.get(str(offer_type or ""), _OFFER_TYPES.get("single", {}))


def default_visible(offer_type: str, key: str) -> bool:
    """Whether a governed section key is visible by DEFAULT for this offer_type (before overrides)."""
    return key in (_offer_type_rule(offer_type).get("sections") or [])


def is_section_visible(offer_type: str, section_type: str, overrides: dict[str, Any] | None = None) -> bool:
    """Final visibility for one section: override wins, else the offer_type default; ungoverned sections
    (body elements) are visible whenever present."""
    key = section_key(section_type)
    if key not in _GOVERNED:
        return True
    override = (overrides or {}).get(key)
    if isinstance(override, dict) and "enabled" in override:
        return bool(override.get("enabled"))
    return default_visible(offer_type, key)


def page_overrides(page: dict[str, Any]) -> dict[str, Any]:
    composition = page.get("composition") or {}
    overrides = composition.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


def compose_page(offer: dict[str, Any], page: dict[str, Any]) -> list[dict[str, Any]]:
    """The Renderable Page Model: page.sections filtered to those the composer deems visible. The renderer
    only iterates this — it never decides."""
    offer_type = str((offer or {}).get("offer_type") or "single")
    overrides = page_overrides(page)
    return [
        section for section in (page.get("sections") or [])
        if is_section_visible(offer_type, str(section.get("type") or ""), overrides)
    ]


def recommended_section_keys(offer_type: str) -> list[str]:
    """Governed sections visible by default for this offer_type (for the builder's 'Recommended' group)."""
    return [key for key in RULES.get("governed_sections", []) if default_visible(offer_type, key)]


def optional_section_keys(offer_type: str) -> list[str]:
    """Governed sections hidden by default — the tenant can opt them in ('Other available' group)."""
    return [key for key in RULES.get("governed_sections", []) if not default_visible(offer_type, key)]


def allowed_ctas(offer_type: str) -> list[str]:
    return list(_offer_type_rule(offer_type).get("allowed_ctas") or [])
