"""Synthesize a post-purchase upsell page from the offer's plan + a per-page scaffold
(plans/OFFER_MODEL_REDESIGN.md §6, P3.2a).

Each upsell reuses the **Universal Bundle template**: it's an ordinary page pointed at a synthetic single-item
offer for the upsell product at its upsell price, inheriting the source page's theme so it stays on-brand. The
existing compose_page/render_page pipeline renders it unchanged — this module only builds the documents. The
small set of "different parts" (headline, subheadline, accept label, decline label, countdown) is the scaffold,
stored per-page at page.post_checkout.upsell_scaffold; a missing scaffold falls back to sensible defaults.
"""

from copy import deepcopy
from typing import Any

from stripe_link.runtime.html import format_money

# Default customer-facing copy for a post-purchase upsell screen. {{ upsell_price }} in accept_label is
# substituted with the formatted upsell price at synthesis. Editable per-page (P3.5).
DEFAULT_UPSELL_SCAFFOLD: dict[str, Any] = {
    "headline": "Wait! Before You Go…",
    "subheadline": "Exclusive One-Time Offer Just For You",
    "accept_label": "Yes, I'll Take This Deal for {{ upsell_price }}",
    "decline_label": "No, Thank You! Let's Move On",
    "countdown_enabled": True,
    "countdown_minutes": 1,
    "savings_badge": True,
}

_PRICE_TOKEN = "{{ upsell_price }}"


def upsell_scaffold(page: dict[str, Any]) -> dict[str, Any]:
    """The upsell scaffold for a page: defaults overlaid with page.post_checkout.upsell_scaffold (blank
    overrides are ignored so a partially-filled scaffold still gets defaults)."""
    scaffold = dict(DEFAULT_UPSELL_SCAFFOLD)
    override = ((page or {}).get("post_checkout") or {}).get("upsell_scaffold")
    if isinstance(override, dict):
        scaffold.update({key: value for key, value in override.items() if value not in (None, "")})
    return scaffold


def _fill_price(text: str, amount: int, currency: str) -> str:
    return str(text or "").replace(_PRICE_TOKEN, format_money(amount, currency))


def synthesize_upsell_offer(
    entry: dict[str, Any], source_offer: dict[str, Any], scaffold: dict[str, Any]
) -> dict[str, Any]:
    """A synthetic single-item offer for one upsell plan entry — the upsell product at its upsell price. Its
    presentation (headline/hero/CTA) comes from the scaffold + the product, so render_page resolves the upsell
    price and the Universal Bundle price card / CTA render against it."""
    product = entry["product"]
    price = entry["price"]
    amount = int(price.get("unit_amount") or 0)
    currency = str(price.get("currency") or "usd")
    accept_label = _fill_price(scaffold["accept_label"], amount, currency)
    offer_id = f"{source_offer.get('offer_id', 'offer')}__upsell_{entry['sequence']}"
    return {
        "schema_version": source_offer.get("schema_version", "2026-05-29"),
        "document_type": "offer",
        "tenant_id": source_offer.get("tenant_id", ""),
        "offer_id": offer_id,
        "name": f"Upsell {entry['sequence']}",
        "status": "active",
        "product_intent": "transaction",
        "stripe_mode": source_offer.get("stripe_mode", "test"),
        "offer_type": "single",
        "items": [{"product_id": entry["product_id"], "price_id": entry["price_id"], "quantity": 1}],
        "presentation": {
            "headline": scaffold["headline"],
            "subheadline": scaffold.get("subheadline") or product.get("description", ""),
            "hero_image_url": (product.get("images") or [""])[0] or "",
            "brand": (source_offer.get("presentation") or {}).get("brand", ""),
            "cta_label": accept_label,
            "cta": {"type": "buy", "label": accept_label},
        },
        "checkout": {"mode": "payment", "metadata": {"offer_id": offer_id}},
        "discount": {"mode": "none"},
        # Post-purchase: the buyer already checked out; this rides the saved payment method off-session.
        "eligibility": {
            "requires_prior_purchase": True, "allowed_price_contexts": ["upsell"],
            "starts_at": None, "ends_at": None,
        },
    }


def synthesize_upsell_page(
    entry: dict[str, Any],
    *,
    source_page: dict[str, Any],
    source_offer: dict[str, Any],
    scaffold: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (page, offer): a Universal Bundle page for one upsell plan entry plus its synthetic offer, ready
    for render_page(page, offer, {product_id: product}, selected_prices={product_id: price_id},
    page_type="funnel_step"). Inherits the source page's theme (brand consistency) and turns the countdown on
    per the scaffold. The decline link is emitted by the buy CTA when rendered as a funnel step."""
    offer = synthesize_upsell_offer(entry, source_offer, scaffold)
    sequence = entry["sequence"]
    presentation = offer["presentation"]

    sections: list[dict[str, Any]] = []
    if scaffold.get("countdown_enabled"):
        sections.append({
            "id": "countdown", "type": "countdown_timer", "enabled": True,
            "duration_minutes": int(scaffold.get("countdown_minutes") or 1),
            "label": "This offer expires in", "start_text": "This offer expires in", "end_text": "Offer expired",
            "sticky": True,
        })
    sections.extend([
        {"id": "hero-media", "type": "hero_media"},
        {"id": "headline", "type": "headline", "text": presentation["headline"]},
        {"id": "subheadline", "type": "subheadline", "text": presentation["subheadline"]},
        {"id": "offer-selector", "type": "offer_price_selector", "offer_id": offer["offer_id"]},
        {"id": "checkout", "type": "checkout_cta", "label": presentation["cta_label"]},
    ])

    theme = deepcopy(source_page.get("theme") or {})
    theme.setdefault("template", "universal_bundle")
    page = {
        "schema_version": source_page.get("schema_version", "2026-05-29"),
        "document_type": "page",
        "tenant_id": source_page.get("tenant_id", ""),
        "page_id": f"{source_page.get('page_id', 'page')}__upsell_{sequence}",
        "name": f"Upsell {sequence}",
        "status": "published",
        "offer_id": offer["offer_id"],
        "theme": theme,
        "sections": sections,
    }
    return page, offer
