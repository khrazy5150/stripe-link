from html import escape
from decimal import Decimal
from typing import Any

from stripe_link.domain.pricing import find_price, resolve_offer


class RenderError(ValueError):
    pass


CURRENCY_SYMBOLS = {
    "usd": "$",
    "eur": "€",
    "gbp": "£",
}

SIMPLE_TEMPLATE_STYLES = [
    "    html{font-size:62.5%}",
    "    *{margin:0;padding:0;box-sizing:border-box}",
    "    :root{--sl-background:var(--sl-theme-background);--sl-text:var(--sl-theme-text);--sl-accent:var(--sl-theme-accent);font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--sl-text);background:var(--sl-background)}",
    "    body{font-size:1.6rem;padding:3.2rem;display:flex;justify-content:center;background:var(--sl-background)}",
    "    main{width:min(96rem,100%);display:grid;gap:2.4rem}",
    "    .sl-hero h1{font-size:4rem;line-height:1.05;margin:0 0 1rem}",
    "    .sl-hero p{font-size:1.8rem;color:#4b5563;margin:0}",
    "    .sl-price-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1.2rem}",
    "    .sl-price-option{border:1px solid #d1d5db;border-radius:0.8rem;padding:1.6rem;background:#fff}",
    "    .sl-price-option[data-default='true']{border-color:var(--sl-accent);box-shadow:0 0 0 1px var(--sl-accent)}",
    "    .sl-badge{display:inline-block;font-size:1.2rem;font-weight:700;color:#166534;background:#dcfce7;padding:0.3rem 0.8rem;border-radius:99.9rem;margin-bottom:0.8rem}",
    "    .sl-cta{display:inline-flex;align-items:center;justify-content:center;background:var(--sl-accent);color:#fff;border:0;border-radius:0.8rem;padding:1.4rem 1.8rem;font-weight:700;text-decoration:none}",
    "    .sl-legal{display:flex;gap:1.2rem;flex-wrap:wrap;font-size:1.3rem;color:#6b7280}",
    "    .sl-legal a{color:inherit}",
]

TEMPLATE_STYLES = {
    "simple": SIMPLE_TEMPLATE_STYLES,
}


def theme_color(page: dict[str, Any], name: str, fallback: str) -> str:
    value = ((page.get("theme") or {}).get("color") or {}).get(name)
    if isinstance(value, str) and value.startswith("#") and len(value) in {4, 7}:
        return value
    return fallback


def format_money(unit_amount: int, currency: str) -> str:
    amount = Decimal(unit_amount) / Decimal(100)
    currency_code = currency.lower()
    symbol = CURRENCY_SYMBOLS.get(currency_code)
    if symbol:
        return f"{symbol}{amount:.2f}"
    return f"{currency_code.upper()} {amount:.2f}"


def template_name(page: dict[str, Any]) -> str:
    return str((page.get("theme") or {}).get("template") or "simple")


def render_template_styles(page: dict[str, Any]) -> list[str]:
    template = template_name(page)
    try:
        styles = TEMPLATE_STYLES[template]
    except KeyError as exc:
        raise RenderError(f"Unsupported page theme.template '{template}'.") from exc

    background = escape(theme_color(page, "background", "#ffffff"))
    text = escape(theme_color(page, "text", "#111827"))
    accent = escape(theme_color(page, "accent", "#16a34a"))
    return [
        f"    :root{{--sl-theme-background:{background};--sl-theme-text:{text};--sl-theme-accent:{accent}}}",
        *styles,
    ]


def require_offer_products(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> None:
    for item in offer.get("items", []):
        product_id = item.get("product_id", "")
        if product_id not in products_by_id:
            raise RenderError(f"Product '{product_id}' was not provided for offer '{offer.get('offer_id', '')}'.")


def render_page(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None = None,
    checkout_url: str | None = None,
) -> str:
    require_offer_products(offer, products_by_id)
    resolved_offer = resolve_offer(offer, products_by_id, selected_prices)
    title = escape((page.get("seo") or {}).get("title") or page.get("name") or "Checkout")
    description = escape((page.get("seo") or {}).get("description") or "")
    styles = render_template_styles(page)
    body = "\n".join(
        render_section(section, page, offer, products_by_id, resolved_offer, checkout_url)
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
        *styles,
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
    checkout_url: str | None,
) -> str:
    section_type = section.get("type")
    if section_type == "hero":
        return render_hero(section)
    if section_type == "offer_price_selector":
        return render_offer_price_selector(offer, products_by_id)
    if section_type == "checkout_cta":
        return render_checkout_cta(section, offer, resolved_offer, checkout_url)
    return f"    <section data-section-id=\"{escape(str(section.get('id', '')))}\"></section>"


def render_hero(section: dict[str, Any]) -> str:
    headline = escape(str(section.get("headline") or ""))
    subheadline = escape(str(section.get("subheadline") or ""))
    return "\n".join([
        f"    <section class=\"sl-hero\" data-section-id=\"{escape(str(section.get('id', 'hero')))}\" data-section-type=\"hero\">",
        f"      <h1>{headline}</h1>" if headline else "",
        f"      <p>{subheadline}</p>" if subheadline else "",
        "    </section>",
    ])


def render_offer_price_selector(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    cards: list[str] = []
    for item in offer.get("items", []):
        product_id = item.get("product_id", "")
        product = products_by_id.get(product_id)
        if product is None:
            raise RenderError(f"Product '{product_id}' was not provided for offer '{offer.get('offer_id', '')}'.")
        default_price_id = item.get("default_price_id")
        for option in item.get("selectable_prices") or []:
            price = find_price(product, option.get("price_id", ""))
            label = escape(str(option.get("label") or price.get("label") or "Option"))
            badge = escape(str(option.get("badge") or price.get("badge") or ""))
            amount = int(price.get("unit_amount", 0))
            currency = str(price.get("currency") or "usd")
            default_attr = "true" if price.get("price_id") == default_price_id else "false"
            cards.append("\n".join([
                f"      <article class=\"sl-price-option\" data-price-id=\"{escape(str(price.get('price_id', '')))}\" data-default=\"{default_attr}\">",
                f"        <span class=\"sl-badge\">{badge}</span>" if badge else "",
                f"        <strong>{label}</strong>",
                f"        <div>{escape(format_money(amount, currency))}</div>",
                "      </article>",
            ]))
    return "\n".join([
        "    <section class=\"sl-price-selector\" data-section-type=\"offer_price_selector\">",
        "      <div class=\"sl-price-options\">",
        *cards,
        "      </div>",
        "    </section>",
    ])


def render_checkout_cta(
    section: dict[str, Any],
    offer: dict[str, Any],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
) -> str:
    label = escape(str(section.get("label") or (offer.get("presentation") or {}).get("cta_label") or "Checkout"))
    subtotal = int(resolved_offer.get("subtotal", 0))
    currency = str(resolved_offer.get("currency") or "usd")
    href = escape(checkout_url or "#checkout")
    return "\n".join([
        "    <section class=\"sl-checkout-cta\" data-section-type=\"checkout_cta\">",
        f"      <a class=\"sl-cta\" href=\"{href}\">{label} - {escape(format_money(subtotal, currency))}</a>",
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
