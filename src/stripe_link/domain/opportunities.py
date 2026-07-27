"""Read-time adapter to the purchase-opportunity model (plans/OFFER_MODEL_REDESIGN.md, P0).

Normalizes ANY offer — new (a real `purchase_opportunities[]`) or legacy (`items[]` + `offer.funnel.*` +
inferred `offer_type`) — into one purchase-opportunity shape, so every consumer can migrate to this BEFORE any
document is rewritten. Pure: never mutates the offer, no I/O.

An opportunity is "present this product, at this STAGE, in this PLACEMENT":
  { opportunity_id, stage, placement{surface, group, order, strategy}, product_id|service_id, <price fields> }
"""

from typing import Any

STAGE_LANDING = "landing"
STAGE_CHECKOUT = "checkout"
STAGE_POST_PURCHASE = "post_purchase"

# Legacy offer.funnel.<key> -> (stage, placement.surface, default placement.strategy).
_FUNNEL_STAGE = {
    "order_bumps": (STAGE_CHECKOUT, "order_bump", "single"),
    "upsells": (STAGE_POST_PURCHASE, "upsell", "sequence"),
    "downsells": (STAGE_POST_PURCHASE, "downsell", "single"),
}


def _legacy_id(stage: str, surface: str, index: int) -> str:
    return f"opp_{stage}_{surface}_{index}"


def _normalize(opportunity: dict[str, Any], index: int) -> dict[str, Any]:
    """Fill in placement/id defaults for a NEW-model opportunity read straight off the offer."""
    opp = dict(opportunity)
    opp.setdefault("stage", STAGE_LANDING)
    placement = dict(opp.get("placement") or {})
    placement.setdefault("surface", "primary")
    placement.setdefault("group", "main_offer")
    placement.setdefault("order", index)
    placement.setdefault("strategy", "")
    opp["placement"] = placement
    opp.setdefault("opportunity_id", _legacy_id(str(opp["stage"]), str(placement["surface"]), index))
    return opp


def opportunities_from_offer(offer: dict[str, Any]) -> list[dict[str, Any]]:
    """The offer's purchase opportunities, normalized. Returns the offer's own `purchase_opportunities` when
    present; otherwise derives them from the legacy `items[]` (landing/primary) and `offer.funnel.*`
    (checkout/order_bump, post_purchase/upsell, post_purchase/downsell)."""
    if not isinstance(offer, dict):
        return []

    existing = offer.get("purchase_opportunities")
    if isinstance(existing, list) and existing:
        return [_normalize(o, i) for i, o in enumerate(existing) if isinstance(o, dict)]

    opportunities: list[dict[str, Any]] = []
    for index, item in enumerate(offer.get("items") or []):
        if not isinstance(item, dict):
            continue
        # Preserve the item verbatim (product_id/service_id, price_id or selectable_prices+default_price_id,
        # quantity, label, presentation_context, …) so pricing/render read exactly what they do today.
        opportunities.append({
            **item,
            "opportunity_id": _legacy_id(STAGE_LANDING, "primary", index),
            "stage": STAGE_LANDING,
            "placement": {"surface": "primary", "group": "main_offer", "order": index, "strategy": ""},
        })

    funnel = offer.get("funnel") or {}
    for key, (stage, surface, strategy) in _FUNNEL_STAGE.items():
        for index, entry in enumerate(funnel.get(key) or []):
            if not isinstance(entry, dict):
                continue
            opportunities.append({
                "opportunity_id": _legacy_id(stage, surface, index),
                "stage": stage,
                "placement": {"surface": surface, "group": surface, "order": index, "strategy": strategy},
                "product_id": entry.get("product_id", ""),
                "price_id": entry.get("price_id", ""),
            })
    return opportunities


def stage_opportunities(offer: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    """The offer's opportunities at one stage (landing / checkout / post_purchase)."""
    return [o for o in opportunities_from_offer(offer) if o.get("stage") == stage]


def landing_presentation(offer: dict[str, Any]) -> dict[str, str]:
    """How the landing stage should present — DERIVED, no stored offer_type (plans/OFFER_MODEL_REDESIGN.md §3).

    Returns {"kind": single|tiered|carousel|none, "checkout": single|cart}. Reproduces today's offer_type
    inference exactly (1 opp 1 price -> single; 1 opp with tiers -> tiered/bundle; N opps -> carousel/cart),
    so it's behavior-preserving for every legacy offer. (P2 will let a NEW offer mark N landing opps that
    share a bundle group as a single-checkout fixed bundle; until then N -> cart, matching the listicle path.)
    """
    landing = stage_opportunities(offer, STAGE_LANDING)
    if not landing:
        return {"kind": "none", "checkout": "single"}
    if len(landing) == 1:
        if len(landing[0].get("selectable_prices") or []) > 1:
            return {"kind": "tiered", "checkout": "single"}
        return {"kind": "single", "checkout": "single"}
    return {"kind": "carousel", "checkout": "cart"}


def derived_offer_type(offer: dict[str, Any]) -> str:
    """The legacy offer_type value (single/bundle/listicle), DERIVED from the opportunities — a drop-in for
    `offer.get("offer_type")` so consumers can stop reading the stored field."""
    kind = landing_presentation(offer)["kind"]
    if kind == "tiered":
        return "bundle"
    if kind == "carousel":
        return "listicle"
    return "single"
