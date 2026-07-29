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
    "downsell_headline": "Wait — Here's a Smaller Option",
    "countdown_enabled": True,
    "countdown_minutes": 1,
    "savings_badge": True,
    # Carousel-mode copy (>= MAX_SEQUENTIAL_UPSELLS upsells): one grid of all upsells, a single dismiss, and an
    # optional downsell-carousel second screen (plans/OFFER_MODEL_REDESIGN.md §6). {{ upsell_price }} in
    # carousel_add_label is filled per card with that card's own price at synthesis. Editable per-page (P3.5).
    "carousel_headline": "Special Deals — Just For You",
    "carousel_subheadline": "One-time offers at checkout prices. Add any you like, then continue.",
    "carousel_add_label": "Add for {{ upsell_price }}",
    "carousel_dismiss_label": "No thanks, I'm good!",
    # After the buyer adds ANY card, the dismiss link relabels to this — it advances the funnel identically, but
    # reads as continuing WITH the (already-charged) purchases rather than declining them.
    "carousel_proceed_label": "Continue to the next step",
    "downsell_carousel_headline": "Before You Go — A Lower-Priced Option",
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
    # Reuse the MAIN offer id so the funnel screen's CTA carries it: the one-click charge (process_upsell) loads
    # the real offer by this id and charges the upsell product@price standalone. Per-upsell identity lives on the
    # PAGE id + the sequence, not the offer id.
    offer_id = str(source_offer.get("offer_id") or "offer")
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
    # The accept label already carries the price (…for $22.17) so hide the CTA's own amount; the decline link
    # uses the scaffold's copy. When this upsell's product has a downsell price, bake it in so the island can
    # swap the price + CTA IN PLACE on decline / countdown expiry (§6) rather than navigating to a downsell page.
    checkout_section = {
        "id": "checkout", "type": "checkout_cta", "label": presentation["cta_label"],
        "hide_amount": True, "decline_label": scaffold["decline_label"],
    }
    downsell = entry.get("downsell")
    if downsell:
        ds_price = downsell.get("price") or {}
        ds_amount = int(ds_price.get("unit_amount") or 0)
        ds_currency = str(ds_price.get("currency") or "usd")
        checkout_section.update({
            "downsell_price_id": downsell.get("price_id"),
            "downsell_amount": ds_amount,
            "downsell_currency": ds_currency,
            "downsell_label": _fill_price(scaffold["accept_label"], ds_amount, ds_currency),
            "downsell_headline": scaffold.get("downsell_headline") or "",
        })
    sections.extend([
        {"id": "hero-media", "type": "hero_media"},
        {"id": "headline", "type": "headline", "text": presentation["headline"]},
        {"id": "subheadline", "type": "subheadline", "text": presentation["subheadline"]},
        {"id": "offer-selector", "type": "offer_price_selector", "offer_id": offer["offer_id"]},
        checkout_section,
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


def _carousel_card(sequence: int, product_id: str, product: dict[str, Any], price: dict[str, Any], scaffold: dict[str, Any]) -> dict[str, Any]:
    """One denormalized card for a post-purchase carousel: everything the renderer needs to lay out the card and
    everything the island needs to fire the one-click /upsell/charge (product_id, price_id, sequence, amount).
    `sequence` is the SAME 1-based key the sequence-mode charge uses, so process_upsell stays idempotent per
    card regardless of add order."""
    amount = int(price.get("unit_amount") or 0)
    currency = str(price.get("currency") or "usd")
    return {
        "sequence": sequence,
        "product_id": product_id,
        "price_id": str(price.get("price_id") or ""),
        "title": str(product.get("name") or f"Offer {sequence}"),
        "description": str(product.get("description") or ""),
        "image_url": (product.get("images") or [""])[0] or "",
        "amount": amount,
        "currency": currency,
        "compare_at_amount": int(price.get("compare_at_amount") or 0),
        "add_label": _fill_price(scaffold["carousel_add_label"], amount, currency),
    }


def _carousel_page(
    source_page: dict[str, Any], source_offer: dict[str, Any], suffix: str, section: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A Universal Bundle page carrying a single self-contained post_purchase_carousel section, plus a minimal
    empty-items offer (the section denormalizes its own card data, so the renderer needs no per-card offer
    resolution — like the thank-you page). Inherits the source page theme. Served at {page_id}__{suffix}."""
    offer_id = str(source_offer.get("offer_id") or "offer")
    offer = {
        "schema_version": source_offer.get("schema_version", "2026-05-29"),
        "document_type": "offer",
        "tenant_id": source_offer.get("tenant_id", ""),
        "offer_id": offer_id,
        "name": section.get("headline") or "Special Deals",
        "status": "active",
        "product_intent": "transaction",
        "stripe_mode": source_offer.get("stripe_mode", "test"),
        "offer_type": "single",
        "items": [],
        "presentation": {"headline": section.get("headline") or ""},
        "discount": {"mode": "none"},
    }
    theme = deepcopy(source_page.get("theme") or {})
    theme.setdefault("template", "universal_bundle")
    page = {
        "schema_version": source_page.get("schema_version", "2026-05-29"),
        "document_type": "page",
        "tenant_id": source_page.get("tenant_id", ""),
        "page_id": f"{source_page.get('page_id', 'page')}__{suffix}",
        "name": section.get("headline") or suffix,
        "status": "published",
        "offer_id": offer_id,
        "theme": theme,
        "sections": [section],
    }
    return page, offer


def synthesize_upsell_carousel_page(
    plan: dict[str, Any],
    *,
    source_page: dict[str, Any],
    source_offer: dict[str, Any],
    scaffold: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (page, offer): the carousel-mode upsell screen (plans/OFFER_MODEL_REDESIGN.md §6) — ONE grid of
    ALL of the plan's upsells, each an independent one-click Add, with a single dismiss. Used when the plan's
    strategy is `carousel` (> MAX_SEQUENTIAL_UPSELLS upsells). Served at {page_id}__upsell_carousel."""
    cards = [
        _carousel_card(e["sequence"], e["product_id"], e["product"], e["price"], scaffold)
        for e in (plan.get("upsells") or [])
    ]
    section = {
        "id": "upsell-carousel",
        "type": "post_purchase_carousel",
        "surface": "upsell",
        "offer_id": str(source_offer.get("offer_id") or "offer"),
        "funnel_page_id": str(source_page.get("page_id") or ""),
        "headline": scaffold["carousel_headline"],
        "subheadline": scaffold.get("carousel_subheadline") or "",
        "dismiss_label": scaffold["carousel_dismiss_label"],
        "proceed_label": scaffold["carousel_proceed_label"],
        "cards": cards,
    }
    return _carousel_page(source_page, source_offer, "upsell_carousel", section)


def synthesize_downsell_carousel_page(
    plan: dict[str, Any],
    *,
    source_page: dict[str, Any],
    source_offer: dict[str, Any],
    scaffold: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (page, offer) for the carousel-mode downsell screen, or None when no upsell product carries a
    downsell price. On the single upsell-carousel dismiss, the buyer sees ONE downsell carousel of the
    downsell-context prices of the upsell products that have one (§6), with its own single dismiss → thank-you.
    Served at {page_id}__downsell_carousel."""
    cards = [
        _carousel_card(e["sequence"], e["product_id"], e["downsell"]["product"], e["downsell"]["price"], scaffold)
        for e in (plan.get("upsells") or [])
        if e.get("downsell")
    ]
    if not cards:
        return None
    section = {
        "id": "downsell-carousel",
        "type": "post_purchase_carousel",
        "surface": "downsell",
        "offer_id": str(source_offer.get("offer_id") or "offer"),
        "funnel_page_id": str(source_page.get("page_id") or ""),
        "headline": scaffold["downsell_carousel_headline"],
        "subheadline": "",
        "dismiss_label": scaffold["carousel_dismiss_label"],
        "proceed_label": scaffold["carousel_proceed_label"],
        "cards": cards,
    }
    return _carousel_page(source_page, source_offer, "downsell_carousel", section)


# Default thank-you copy + optional sections — the funnel's terminus (SALES_FUNNELS.md P3.5). Every field is
# tenant-editable; the toggles (enable_*) turn the celebration burst, the "What's Next?" cards, and the footer
# on or off. Ported from stripe-cart's thank-you template (Phase 2 parity).
DEFAULT_THANK_YOU = {
    "headline": "Thank You for Your Purchase!",
    "headline_icon": "🎉",
    "subheadline": "Your order is confirmed — a receipt is on its way to your inbox.",
    "message": "We're getting your order ready. You'll get an email with the details shortly.",
    "enable_celebration": True,
    "enable_next_steps": True,
    "next_steps_title": "What's Next?",
    "next_steps": [
        {"icon": "📧", "title": "Check Your Email", "desc": "Confirmation and tracking details are on the way to your inbox."},
        {"icon": "📦", "title": "Free Shipping", "desc": "Your order will arrive within 5–7 business days."},
        {"icon": "🚀", "title": "Start Your Journey", "desc": "Begin your routine as soon as it arrives."},
    ],
    "enable_footer": False,
    "footer_headline": "The Ball Is in Our Court",
    "footer_message": "Look for an email from us with tracking information about your order.",
    "show_home_button": False,
    "home_button_text": "Back to Home",
    "enable_download": False,
    "download_button_text": "Download Your Product",
    "download_url": "",
}


def thank_you_config(page: dict[str, Any]) -> dict[str, Any]:
    """Thank-you config: defaults overlaid with page.post_checkout.thank_you_page overrides (blank strings
    ignored so a partially-filled override still gets defaults; a `False` toggle IS applied)."""
    config = dict(DEFAULT_THANK_YOU)
    override = ((page or {}).get("post_checkout") or {}).get("thank_you_page")
    if isinstance(override, dict):
        config.update({key: value for key, value in override.items() if key in config and value not in (None, "")})
    return config


def synthesize_thank_you_page(
    source_page: dict[str, Any], source_offer: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (page, offer): the funnel's terminal thank-you screen on the Universal Bundle template, inheriting
    the source page's theme. It sells nothing (no price/CTA), so its offer carries no items — render_page only
    lays out the headline/subheadline/message. Served at {page_id}__thank_you."""
    config = thank_you_config(source_page)
    offer_id = str(source_offer.get("offer_id") or "offer")
    offer = {
        "schema_version": source_offer.get("schema_version", "2026-05-29"),
        "document_type": "offer",
        "tenant_id": source_offer.get("tenant_id", ""),
        "offer_id": offer_id,
        "name": "Thank You",
        "status": "active",
        "product_intent": "transaction",
        "stripe_mode": source_offer.get("stripe_mode", "test"),
        "offer_type": "single",
        "items": [],
        "presentation": {"headline": config["headline"]},
        "discount": {"mode": "none"},
    }
    theme = deepcopy(source_page.get("theme") or {})
    theme.setdefault("template", "universal_bundle")
    sections: list[dict[str, Any]] = []
    if config.get("enable_celebration"):
        sections.append({"id": "celebration", "type": "celebration"})
    icon = str(config.get("headline_icon") or "").strip()
    headline_text = f"{icon} {config['headline']}".strip() if icon and icon != "—" else config["headline"]
    sections.append({"id": "headline", "type": "headline", "text": headline_text})
    sections.append({"id": "subheadline", "type": "subheadline", "text": config["subheadline"]})
    if config.get("message"):
        sections.append({"id": "content", "type": "content_block", "blocks": [{"title": "", "text": config["message"]}]})
    if config.get("enable_next_steps"):
        cards = [c for c in (config.get("next_steps") or []) if isinstance(c, dict) and (c.get("title") or c.get("desc"))]
        if cards:
            sections.append({"id": "next-steps", "type": "next_steps",
                             "title": config.get("next_steps_title") or "What's Next?", "cards": cards})
    download_on = bool(config.get("enable_download") and config.get("download_url"))
    if config.get("enable_footer") or config.get("show_home_button") or download_on:
        sections.append({
            "id": "ty-footer", "type": "thank_you_footer",
            "headline": config["footer_headline"] if config.get("enable_footer") else "",
            "message": config["footer_message"] if config.get("enable_footer") else "",
            "home_button_text": config["home_button_text"] if config.get("show_home_button") else "",
            "download_button_text": config["download_button_text"] if download_on else "",
            "download_url": config["download_url"] if download_on else "",
        })
    page = {
        "schema_version": source_page.get("schema_version", "2026-05-29"),
        "document_type": "page",
        "tenant_id": source_page.get("tenant_id", ""),
        "page_id": f"{source_page.get('page_id', 'page')}__thank_you",
        "name": "Thank You",
        "status": "published",
        "offer_id": offer_id,
        "theme": theme,
        "sections": sections,
    }
    return page, offer
