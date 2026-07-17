"""Product categories — an organically-grown, shared taxonomy (plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md).

A tenant types a category; it is theirs immediately (stored on their product). It becomes a *suggestion to
other tenants* only after enough distinct tenants have independently used it. This module is the pure logic:
normalization (so near-duplicates fold together), the curated seed list, type-scoping, and the promotion
rule. The table and endpoint wire around it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# A category is a shared suggestion once this many DISTINCT tenants have used it. Below the bar it stays
# private to the tenants using it, so typos and one-off junk never reach other tenants' suggestions.
PROMOTION_THRESHOLD = 3

# The three product types (physical / digital / service) categories are scoped to. A category applies to
# one or more; the autocomplete only suggests categories valid for the product being edited, because a
# service shouldn't be offered "Apparel" nor a supplement "Consulting".
PRODUCT_TYPES = ("physical", "digital", "service")

# Curated categories: always promoted, owned in code (they change rarely; see docs on adding one). The table
# holds only tenant-contributed categories, so there is no seed step. Declared as (label, types); the KEY is
# derived as normalize(label), which guarantees a label always round-trips to its own key — otherwise a
# tenant typing a curated label would mint a duplicate contributed entry instead of matching it.
_CURATED: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Physical goods
    ("Apparel", ("physical",)),
    ("Jewelry and Accessories", ("physical",)),
    ("Beauty and Personal Care", ("physical",)),
    ("Health and Household", ("physical",)),
    ("Dietary Supplement", ("physical",)),
    ("Food and Beverage", ("physical",)),
    ("Home and Garden", ("physical",)),
    ("Electronics", ("physical",)),
    ("Sporting Goods", ("physical",)),
    ("Toys and Games", ("physical",)),
    ("Baby and Kids", ("physical",)),
    ("Pet Supplies", ("physical",)),
    ("Automotive", ("physical",)),
    ("Arts and Crafts", ("physical",)),
    ("Office Supplies", ("physical",)),
    ("Books and Printed Material", ("physical",)),
    ("Music and Movies", ("physical",)),
    # Digital
    ("Digital Download", ("digital",)),
    ("Software", ("digital",)),
    ("Software as a Service", ("digital",)),
    ("Course", ("digital",)),
    ("Membership", ("digital",)),
    # Services
    ("Professional Services", ("service",)),
    ("Consulting", ("service",)),
    ("Plumbing", ("service",)),
    ("Dental", ("service",)),
    ("Home Cleaning", ("service",)),
    # Catch-all — valid for any product type
    ("Other", PRODUCT_TYPES),
)


def normalize_category(text: str) -> str:
    """The canonical key for a category label: lowercased, accent-folded, non-alphanumerics collapsed to a
    single underscore. This is what dedups "Dietary Supplement" / "dietary supplement" / "Supplements " into
    one entry — without it the shared list fragments into near-duplicates, the very mess it should prevent.
    Returns "" for empty/punctuation-only input.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


# key -> {"label", "types"}. Built from _CURATED so the key can never drift from its label.
CURATED_CATEGORIES: dict[str, dict[str, Any]] = {
    normalize_category(label): {"label": label, "types": set(types)}
    for label, types in _CURATED
}


def category_label(key: str, provided: str = "") -> str:
    """Display label for a key: the curated label if it's curated, else the caller's text, else a humanized
    fall-back so a bare key never reaches a page."""
    key = str(key or "")
    if key in CURATED_CATEGORIES:
        return CURATED_CATEGORIES[key]["label"]
    provided = str(provided or "").strip()
    if provided:
        return provided
    return " ".join(word.capitalize() for word in key.split("_") if word)


def _types_of(item: dict[str, Any]) -> set[str]:
    return {str(t) for t in (item.get("types") or set())}


def is_promoted(item: dict[str, Any]) -> bool:
    """A tenant-contributed category is a shared suggestion once PROMOTION_THRESHOLD distinct tenants use it.
    tenant_ids is a set, so its size is the distinct count."""
    tenant_ids = item.get("tenant_ids") or set()
    try:
        return len(tenant_ids) >= PROMOTION_THRESHOLD
    except TypeError:
        return False


def search_suggestions(
    query: str,
    contributed: list[dict[str, Any]],
    *,
    product_type: str = "",
    tenant_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """The autocomplete result for `query`, scoped to `product_type`: curated categories + promoted
    contributed ones, plus the requesting tenant's own not-yet-promoted ones (so they can re-pick what they
    typed before). Each result is {key, label, source}.

    Matching is a case/accent-insensitive substring on the normalized query — the same fold used for keys,
    so "supp" finds "Dietary Supplement". An empty product_type does not filter (list everything).
    """
    needle = normalize_category(query)
    ptype = str(product_type or "")
    results: dict[str, dict[str, Any]] = {}

    def add(key: str, label: str, source: str, types: set[str]) -> None:
        if not key or key in results:
            return
        if ptype and types and ptype not in types:
            return
        if needle and needle not in key and needle not in normalize_category(label):
            return
        results[key] = {"key": key, "label": label, "source": source}

    for key, meta in CURATED_CATEGORIES.items():
        add(key, meta["label"], "curated", meta["types"])
    for item in contributed:
        key = str(item.get("category_key") or "")
        label = category_label(key, str(item.get("label") or ""))
        types = _types_of(item)
        if is_promoted(item):
            add(key, label, "promoted", types)
        elif tenant_id and tenant_id in (item.get("tenant_ids") or set()):
            add(key, label, "yours", types)

    ordered = sorted(results.values(), key=lambda r: (r["source"] != "curated", r["label"].lower()))
    return ordered[:limit]
