"""Offer Semantic Model — the canonical understanding of an offer (plans/OFFER_SEMANTIC_ANALYZER.md).

The analyzer emits MEANING only: no SEO, formatting, URL, or channel logic. Downstream generators (slug, label,
title, schema, … and later AI / merchant feeds / ads) consume the model and own their own output. The model is
domain-agnostic; the consumers are domain-specific.

This is the deterministic core (P1). It populates the fields honestly derivable from the offer + catalog today;
the rest of the schema is present but empty/low-confidence for the AI enrichment tier — consumers must degrade
gracefully on missing fields. `facts` are stable values; `interpretation` isolates opinions (weights,
confidence) so improving them never touches the facts.
"""
import re
from typing import Any

from stripe_link.domain.opportunities import (
    STAGE_CHECKOUT,
    STAGE_LANDING,
    STAGE_POST_PURCHASE,
    landing_presentation,
    stage_opportunities,
)

# Bump when the model's SHAPE or deterministic derivation changes in a way a cached AI model should be
# considered stale for (resolve_semantic_model falls back to a fresh compute on a version mismatch).
MODEL_VERSION = 1

_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "of", "with", "to", "in", "on", "at", "by", "from",
    "your", "you", "our", "my", "this", "that", "is", "are", "plus",
})


def _tokens(text: Any, limit: int | None = None) -> list[str]:
    """Lowercased alphanumeric keyword tokens, stop-words dropped. A machine category ("dietary_supplement")
    splits into ["dietary", "supplement"]."""
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split() if w and w not in _STOP_WORDS]
    return words[:limit] if limit else words


def _dedupe(tokens: list[str]) -> list[str]:
    seen, out = set(), []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _humanize(machine: Any) -> str:
    """"dietary_supplement" -> "Dietary Supplement" (a readable taxonomy label)."""
    return " ".join(w.capitalize() for w in re.split(r"[^a-z0-9]+", str(machine or "").lower()) if w)


def _shared_category(products: list[dict]) -> str:
    """The single machine-style product_category shared by ALL products, else ""."""
    cats = [str((p or {}).get("product_category") or "").strip().lower() for p in products]
    if cats and all(cats) and len(set(cats)) == 1:
        return cats[0]
    return ""


def analyze_offer(offer: dict, products_by_id: dict, services_by_id: dict | None = None) -> dict:
    """Return the deterministic OfferSemanticModel for an offer (+ its resolved products). Pure meaning.

    `services_by_id` is optional but matters: a service-only offer has NO products, so without it the
    primary entity fell back to the offer's own (usually empty) name and every such offer was labelled
    "Offer" with the slug "offer" — then offer-2, offer-3. The model already typed it as a service; it
    just had no way to name it. Restores the intent of 95da715 (auto-label/slug key off the unified item
    set, products AND services), which was dropped when this moved to the semantic model.
    """
    landing_opps = stage_opportunities(offer, STAGE_LANDING)
    products = [products_by_id.get(str((o or {}).get("product_id") or "")) for o in landing_opps]
    products = [p for p in products if p]
    services_by_id = services_by_id or {}
    service_names = [
        str((services_by_id.get(str((o or {}).get("service_id") or "")) or {}).get("name") or "")
        for o in landing_opps if str((o or {}).get("service_id") or "")
    ]
    service_names = [name for name in service_names if name]
    pres_kind = str(landing_presentation(offer).get("kind") or "")  # single | tiered | carousel | none
    commercial = str(offer.get("product_intent") or "transaction")
    brand = str(((offer.get("presentation") or {}).get("brand")) or "").strip()
    is_single_service = bool(landing_opps and str((landing_opps[0] or {}).get("service_id") or ""))
    shared_cat = _shared_category(products)

    # entities.primary.type — by structure (entity COUNT), not the backend's confusing "bundle"=tiered label:
    # multiple distinct products = a bundle (one primary + secondary[]); one product (even tiered) = a product.
    if commercial == "lead_generation":
        primary_type = "lead_generation"
    elif is_single_service:
        primary_type = "service"
    elif len(products) > 1:
        primary_type = "bundle"
    else:
        primary_type = "product"

    # entities.primary.name — the product for a single; the shared-category theme for a homogeneous bundle;
    # else the headline product. secondary[] exposes the rest so a consumer can decide whether to use them.
    if len(products) <= 1:
        # Services are entities too. Order: the product, else the service, else the offer's own name.
        fallback_name = service_names[0] if service_names else offer.get("name")
        primary_name = str((products[0].get("name") if products else fallback_name) or "Offer")
    elif shared_cat:
        primary_name = _humanize(shared_cat)
    else:
        primary_name = str(products[0].get("name") or "Offer")
    secondary = [{"type": "product", "name": str(p.get("name") or "")} for p in products[1:] if p.get("name")]
    if not products:  # a multi-service offer names its remaining services the way a bundle names products
        secondary = [{"type": "service", "name": name} for name in service_names[1:]]

    # taxonomy.hierarchy — shallow + deterministic. Populated for a single product (its category) or a bundle
    # whose products SHARE a category; a mixed bundle has no single coherent category, so it stays empty (honest,
    # and it's what lets the slug fall back to naming the top products rather than one product's category).
    if shared_cat:
        hierarchy = [_humanize(shared_cat)]
    elif len(products) <= 1 and products and products[0].get("product_category"):
        hierarchy = [_humanize(products[0].get("product_category"))]
    else:
        hierarchy = []

    # commerce — all deterministic, useful far beyond SEO
    checkout_opps = stage_opportunities(offer, STAGE_CHECKOUT)
    post_opps = stage_opportunities(offer, STAGE_POST_PURCHASE)
    upsells = [o for o in post_opps if str((o.get("placement") or {}).get("surface") or "") == "upsell"]
    downsells = [o for o in post_opps if str((o.get("placement") or {}).get("surface") or "") == "downsell"]
    pricing_model = {"tiered": "tiered", "carousel": "multi"}.get(pres_kind, "single")
    purchase_model = "one_time"
    for product in products:
        if any(str(price.get("pricing_model") or "") == "recurring" for price in (product.get("prices") or [])):
            purchase_model = "subscription"
            break
    fulfillment = str((products[0].get("product_type") if products else "") or "")
    if is_single_service:
        fulfillment = "service"

    # interpretation.key_concepts — weighted; brand strongest, then primary, category, secondary
    concepts: list[dict] = []
    for token in _tokens(brand, 2):
        concepts.append({"value": token, "weight": 100})
    for token in _tokens(primary_name, 5):
        concepts.append({"value": token, "weight": 90})
    if shared_cat:
        for token in _tokens(shared_cat):
            concepts.append({"value": token, "weight": 70})
    for entity in secondary[:2]:
        for token in _tokens(entity["name"], 2):
            concepts.append({"value": token, "weight": 50})
    # collapse duplicate tokens, keeping the highest weight
    best: dict[str, int] = {}
    for concept in concepts:
        best[concept["value"]] = max(best.get(concept["value"], 0), concept["weight"])
    key_concepts = [{"value": value, "weight": weight} for value, weight in
                    sorted(best.items(), key=lambda kv: -kv[1])]

    return {
        "facts": {
            "entities": {"primary": {"type": primary_type, "name": primary_name}, "secondary": secondary},
            "brand": {"name": brand} if brand else None,
            "taxonomy": {"hierarchy": hierarchy},
            "intent": {"commercial": commercial, "audience": "", "fulfillment": fulfillment,
                       "acquisition": "", "urgency": ""},
            "commerce": {
                "pricing_model": pricing_model,
                "purchase_model": purchase_model,
                "funnel": {"landing": bool(landing_opps), "order_bump": bool(checkout_opps),
                           "upsells": len(upsells), "downsells": len(downsells)},
            },
            "attributes": _attributes(pricing_model, purchase_model),
        },
        "interpretation": {
            "key_concepts": key_concepts,
            "confidence": {
                "entities.primary": 1.0 if len(products) <= 1 else (0.8 if shared_cat else 0.6),
                "taxonomy.hierarchy": 0.8 if shared_cat else (0.4 if hierarchy else 0.0),
            },
            "source": "deterministic",
            "version": MODEL_VERSION,
        },
    }


def resolve_semantic_model(offer: dict, products_by_id: dict) -> dict:
    """The read seam for the model (plans/OFFER_SEMANTIC_P4.md, P4.0). Return the offer's CACHED model only when
    it is a current AI-enriched one; otherwise recompute the deterministic model. Deterministic recompute is
    cheap, so the cache exists ONLY to preserve expensive AI enrichment — an absent, stale-version, or merely
    deterministic cache just recomputes. The cache WRITE lands in P4.1 (the AI tier); this makes consumers safe
    to route through today with zero behaviour change."""
    cached = offer.get("semantic_model")
    if isinstance(cached, dict):
        interpretation = cached.get("interpretation") or {}
        if interpretation.get("source") == "ai" and interpretation.get("version") == MODEL_VERSION:
            return cached
    return analyze_offer(offer, products_by_id)


def _attributes(pricing_model: str, purchase_model: str) -> list[dict]:
    attrs = []
    if pricing_model == "tiered":
        attrs.append({"name": "Quantity Pricing", "value": True})
    if purchase_model == "subscription":
        attrs.append({"name": "Subscription", "value": True})
    return attrs


# -- Generators: consume the model, own their formatting -------------------------------------------------

_SLUG_MAX_TOKENS = 6


def slug_from_model(model: dict) -> str:
    """SEO slug BASE from the model (not deduped — the caller runs unique_offer_slug). Reads entities +
    taxonomy + brand; never re-derives from raw products. See plans/OFFER_SEMANTIC_ANALYZER.md."""
    facts = model.get("facts") or {}
    entities = facts.get("entities") or {}
    primary = entities.get("primary") or {}
    secondary = entities.get("secondary") or []
    hierarchy = (facts.get("taxonomy") or {}).get("hierarchy") or []
    brand_tokens = _tokens((facts.get("brand") or {}).get("name"), 2)

    if not secondary:  # single entity
        core, suffix = _tokens(primary.get("name"), 5), []
    else:  # bundle: shared category, else the top-2 entities
        if hierarchy:
            core = _tokens(hierarchy[-1])
        else:
            core = _tokens(primary.get("name"), 3) + _tokens(secondary[0].get("name"), 3)
        suffix = ["bundle"]

    tokens = _dedupe(brand_tokens + core)
    tokens = tokens[: _SLUG_MAX_TOKENS - len(suffix)] + suffix
    return "-".join(tokens) or "offer"


def label_from_model(model: dict) -> str:
    """Human offer LABEL from the model — coherent with the slug (both read entities.primary), so a bundle
    gets a representative label instead of just the first product's name."""
    facts = model.get("facts") or {}
    entities = facts.get("entities") or {}
    primary = entities.get("primary") or {}
    secondary = entities.get("secondary") or []
    hierarchy = (facts.get("taxonomy") or {}).get("hierarchy") or []

    if not secondary:
        return str(primary.get("name") or "Offer")
    if hierarchy:
        return f"{hierarchy[-1]} Bundle"
    names = [str(primary.get("name") or "")] + [str(secondary[0].get("name") or "")]
    return " + ".join(n for n in names if n) + " Bundle"


def is_bundle(model: dict) -> bool:
    """True when the offer bundles more than one distinct entity (secondary[] populated). Prose generators
    branch on this to name the whole bundle rather than its first product."""
    entities = (model.get("facts") or {}).get("entities") or {}
    return bool(entities.get("secondary"))


def subject_from_model(model: dict) -> str:
    """The offer's primary subject as prose generators (page <title>, meta description) should name it.
    Identical to the offer label by design — that identity IS the coherence the model exists to guarantee:
    the <title>, the offer label, and the slug all describe the same subject rather than diverging."""
    return label_from_model(model)
