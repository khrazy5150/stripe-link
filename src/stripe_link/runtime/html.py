from html import escape
from typing import Any

from stripe_link.domain.pricing import find_price, resolve_offer


def render_page(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None = None,
) -> str:
    resolved_offer = resolve_offer(offer, products_by_id, selected_prices)
    title = escape((page.get("seo") or {}).get("title") or page.get("name") or "Checkout")
    description = escape((page.get("seo") or {}).get("description") or "")
    body = "\n".join(
        render_section(section, page, offer, products_by_id, resolved_offer)
        for section in page.get("sections", [])
    )
    legal_footer = render_legal_footer(page.get("legal") or {})
    analytics_tags = render_analytics_tags(page.get("analytics") or {})
    return "\n".join([
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"  <title>{title}</title>",
        f"  <meta name=\"description\" content=\"{description}\">" if description else "",
        "  <style>",
        "    :root{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;background:#fff}",
        "    body{margin:0;padding:32px;display:flex;justify-content:center}",
        "    main{width:min(960px,100%);display:grid;gap:24px}",
        "    .sl-hero h1{font-size:40px;line-height:1.05;margin:0 0 10px}",
        "    .sl-hero p{font-size:18px;color:#4b5563;margin:0}",
        "    .sl-price-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}",
        "    .sl-price-option{border:1px solid #d1d5db;border-radius:8px;padding:16px;background:#fff}",
        "    .sl-price-option[data-default='true']{border-color:#16a34a;box-shadow:0 0 0 1px #16a34a}",
        "    .sl-badge{display:inline-block;font-size:12px;font-weight:700;color:#166534;background:#dcfce7;padding:3px 8px;border-radius:999px;margin-bottom:8px}",
        "    .sl-cta{display:inline-flex;align-items:center;justify-content:center;background:#16a34a;color:#fff;border:0;border-radius:8px;padding:14px 18px;font-weight:700;text-decoration:none}",
        "    .sl-legal{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:#6b7280}",
        "    .sl-legal a{color:inherit}",
        "  </style>",
        analytics_tags,
        "</head>",
        "<body>",
        "  <main>",
        body,
        legal_footer,
        "  </main>",
        "</body>",
        "</html>",
    ])


def render_section(
    section: dict[str, Any],
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    resolved_offer: dict[str, Any],
) -> str:
    section_type = section.get("type")
    if section_type == "hero":
        return render_hero(section)
    if section_type == "offer_price_selector":
        return render_offer_price_selector(offer, products_by_id)
    if section_type == "checkout_cta":
        return render_checkout_cta(section, resolved_offer)
    return f"    <section data-section-id=\"{escape(str(section.get('id', '')))}\"></section>"


def render_hero(section: dict[str, Any]) -> str:
    headline = escape(str(section.get("headline") or ""))
    subheadline = escape(str(section.get("subheadline") or ""))
    return "\n".join([
        f"    <section class=\"sl-hero\" data-section-id=\"{escape(str(section.get('id', 'hero')))}\">",
        f"      <h1>{headline}</h1>" if headline else "",
        f"      <p>{subheadline}</p>" if subheadline else "",
        "    </section>",
    ])


def render_offer_price_selector(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    cards: list[str] = []
    for item in offer.get("items", []):
        product = products_by_id.get(item.get("product_id", "")) or {}
        default_price_id = item.get("default_price_id")
        for option in item.get("selectable_prices") or []:
            price = find_price(product, option.get("price_id", ""))
            label = escape(str(option.get("label") or price.get("label") or "Option"))
            badge = escape(str(option.get("badge") or price.get("badge") or ""))
            amount = int(price.get("unit_amount", 0))
            default_attr = "true" if price.get("price_id") == default_price_id else "false"
            cards.append("\n".join([
                f"      <article class=\"sl-price-option\" data-price-id=\"{escape(str(price.get('price_id', '')))}\" data-default=\"{default_attr}\">",
                f"        <span class=\"sl-badge\">{badge}</span>" if badge else "",
                f"        <strong>{label}</strong>",
                f"        <div>${amount / 100:.2f}</div>",
                "      </article>",
            ]))
    return "\n".join([
        "    <section class=\"sl-price-selector\">",
        "      <div class=\"sl-price-options\">",
        *cards,
        "      </div>",
        "    </section>",
    ])


def render_checkout_cta(section: dict[str, Any], resolved_offer: dict[str, Any]) -> str:
    label = escape(str(section.get("label") or "Checkout"))
    subtotal = int(resolved_offer.get("subtotal", 0))
    return "\n".join([
        "    <section class=\"sl-checkout-cta\">",
        f"      <a class=\"sl-cta\" href=\"#checkout\">{label} - ${subtotal / 100:.2f}</a>",
        "    </section>",
    ])


def render_legal_footer(legal: dict[str, Any]) -> str:
    links = [
        ("Terms", legal.get("terms_url")),
        ("Privacy", legal.get("privacy_url")),
        ("Refunds", legal.get("refund_url")),
    ]
    rendered_links = [
        f"      <a href=\"{escape(str(url))}\">{label}</a>"
        for label, url in links
        if url
    ]
    if not rendered_links:
        return ""
    return "\n".join([
        "    <footer class=\"sl-legal\">",
        *rendered_links,
        "    </footer>",
    ])


def render_analytics_tags(analytics: dict[str, Any]) -> str:
    tags: list[str] = []
    google_tag_id = analytics.get("google_tag_id")
    pixel_id = analytics.get("pixel_id")
    if google_tag_id:
        tags.append(f"  <meta name=\"sl-google-tag-id\" content=\"{escape(str(google_tag_id))}\">")
    if pixel_id:
        tags.append(f"  <meta name=\"sl-meta-pixel-id\" content=\"{escape(str(pixel_id))}\">")
    return "\n".join(tags)
