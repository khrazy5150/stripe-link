"""Recording a tenant's use of a category, so a non-curated one can accrue toward promotion.

Lives here rather than in `handlers/products.py` for the reason `document_route.py` spells out: a handler
that imports another handler inherits every table that handler reaches, because `tests/envreach.py` follows
imports transitively — and this stack has sat at CloudFormation's transform limit. Services needed the same
function products already had, so the function moved out instead of being imported across or copied.

Pure glue: the promotion RULE is `domain/categories.py`, the storage is the categories repository.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from stripe_link.domain.categories import CURATED_CATEGORIES, category_label, normalize_category

logger = logging.getLogger(__name__)


def record_category_usage(document: dict[str, Any], categories_repo: Any = None, *,
                          product_type: str | None = None) -> None:
    """Register this tenant's use of `document["product_category"]` (plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md).

    Curated categories are skipped — they are already promoted and don't need counting. Best-effort: a
    failure here must never fail the save, and it no-ops when the table isn't configured (unit tests).

    `product_type` overrides the document's own field, which is what a SERVICE needs: a service document has
    no `product_type`, and recording with an empty one would store a category with no type scope. That is
    not a harmless blank — `search_suggestions` only filters when the stored entry HAS types, so an
    unscoped "Massage Therapy" would be suggested for T-shirts (`feedback_absence_reads_as_safety`).
    """
    key = normalize_category(str(document.get("product_category") or ""))
    tenant_id = str(document.get("tenant_id") or "")
    if not key or not tenant_id or key in CURATED_CATEGORIES:
        return
    scope = str(product_type if product_type is not None else document.get("product_type") or "")
    if categories_repo is None:
        if not os.environ.get("PRODUCT_CATEGORIES_TABLE"):
            return
        from stripe_link.repositories.documents import product_categories_repository

        categories_repo = product_categories_repository()
    try:
        categories_repo.record_usage(key, category_label(key), scope, tenant_id, int(time.time()))
    except Exception:  # noqa: BLE001 - recording usage is best-effort, never blocks a save
        logger.warning("Failed to record category usage for %s", key, exc_info=True)
