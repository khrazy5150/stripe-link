"""The slim list projection of an offer — enough to render a card, search it, and sort it.

Why this exists: the list screen loaded FULL offer documents (~2.9KB each), which breaches the 6MB Lambda
response limit somewhere around 2,000 offers. Paginating the full documents instead would have broken
search, because filtering is client-side and would then only cover the loaded pages
(plans/OFFER_ITEM_VISIBILITY.md §7).

An index entry carries no product data — only ids. The list screen already loads the product and service
stores (it needs them for item names and for deriving funnel roles from pricing contexts), so resolving a
name client-side is free, while embedding names here would duplicate catalog data into a second place that
can go stale. Ids are the reference; the catalog is the source of truth.

Sizing: roughly 300-400 bytes per offer against ~2.9KB for the full document, so 1,000 offers is ~0.4MB —
small enough to load whole, which is what keeps substring search instant and COMPLETE rather than limited
to whatever has been scrolled.
"""

from typing import Any

from stripe_link.domain.opportunities import STAGE_LANDING, opportunities_from_offer


def offer_index_entry(offer: dict[str, Any]) -> dict[str, Any]:
    """One offer as a list-projection row.

    `item_ids` is every product/service the offer references, in offer order — the client derives funnel
    roles from each one's pricing contexts, exactly as domain/funnels.funnel_context_items does on the
    server. `landing_ids` is the subset shown on the page, which is genuinely offer data (membership and
    order), not something derivable from pricing.
    """
    item_ids: list[str] = []
    landing_ids: list[str] = []
    for opportunity in opportunities_from_offer(offer):
        entity_id = str(opportunity.get("product_id") or opportunity.get("service_id") or "")
        if not entity_id:
            continue
        if entity_id not in item_ids:
            item_ids.append(entity_id)
        if str(opportunity.get("stage") or STAGE_LANDING) == STAGE_LANDING and entity_id not in landing_ids:
            landing_ids.append(entity_id)

    presentation = offer.get("presentation") or {}
    entry = {
        "offer_id": str(offer.get("offer_id") or ""),
        "name": str(offer.get("name") or ""),
        "slug": str(offer.get("slug") or ""),
        "offer_type": str(offer.get("offer_type") or ""),
        "product_intent": str(offer.get("product_intent") or ""),
        "status": str(offer.get("status") or ""),
        "created_at": str(offer.get("created_at") or ""),
        "updated_at": str(offer.get("updated_at") or ""),
        "item_ids": item_ids,
        "landing_ids": landing_ids,
    }
    # Only when set: the card falls back to the first landing product's own image, which the client
    # already holds, so an absent key costs nothing and an empty string would just be noise.
    image_url = str(presentation.get("image_url") or presentation.get("hero_image_url") or "")
    if image_url:
        entry["image_url"] = image_url
    return entry
