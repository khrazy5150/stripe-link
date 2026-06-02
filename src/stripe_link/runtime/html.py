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

UNIVERSAL_BUNDLE_THEME_PRESETS = {
    "techno-green": {
        "background": "#0b1220",
        "card": "#0f172a",
        "text": "#f8fafc",
        "muted": "#cbd5e1",
        "brand": "#22c55e",
        "accent": "#4ade80",
        "headline": "#a3e635",
        "cta_from": "#22c55e",
        "cta_to": "#16a34a",
        "cta_text": "#052e16",
        "chip_bg": "#103f35",
        "chip_text": "#d1fae5",
        "chip_border": "#1f6f55",
        "savings_bg": "#14532d",
        "savings_text": "#86efac",
        "savings_border": "#267342",
        "featured_badge_bg": "#f97316",
        "featured_badge_text": "#ffffff",
        "border": "#334155",
    },
    "rose-minimalist": {
        "background": "#fefefe",
        "card": "#ffffff",
        "text": "#1f2937",
        "muted": "#6b7280",
        "brand": "#ff4181",
        "accent": "#ff6b9d",
        "headline": "#ff4181",
        "cta_from": "#d63d76",
        "cta_to": "#c22d66",
        "cta_text": "#ffffff",
        "chip_bg": "#fff1f6",
        "chip_text": "#d63d76",
        "chip_border": "#ffc4d8",
        "savings_bg": "#fff1f6",
        "savings_text": "#be185d",
        "savings_border": "#f9a8d4",
        "featured_badge_bg": "#ff4181",
        "featured_badge_text": "#ffffff",
        "border": "#e5e7eb",
    },
    "midnight-luxe": {
        "background": "#0a0a0a",
        "card": "#1a1a1a",
        "text": "#f5f5f5",
        "muted": "#a3a3a3",
        "brand": "#d4af37",
        "accent": "#f4d03f",
        "headline": "#d4af37",
        "cta_from": "#d4af37",
        "cta_to": "#c9a227",
        "cta_text": "#0a0a0a",
        "chip_bg": "#3a3218",
        "chip_text": "#f4d03f",
        "chip_border": "#6b5a23",
        "savings_bg": "#3a3218",
        "savings_text": "#f4d03f",
        "savings_border": "#6b5a23",
        "featured_badge_bg": "#d4af37",
        "featured_badge_text": "#0a0a0a",
        "border": "#3f3f46",
    },
    "trust-blue": {
        "background": "#0c1929",
        "card": "#132337",
        "text": "#f0f9ff",
        "muted": "#93c5fd",
        "brand": "#3b82f6",
        "accent": "#60a5fa",
        "headline": "#60a5fa",
        "cta_from": "#3b82f6",
        "cta_to": "#2563eb",
        "cta_text": "#ffffff",
        "chip_bg": "#142f57",
        "chip_text": "#93c5fd",
        "chip_border": "#24518d",
        "savings_bg": "#14532d",
        "savings_text": "#86efac",
        "savings_border": "#267342",
        "featured_badge_bg": "#3b82f6",
        "featured_badge_text": "#ffffff",
        "border": "#334155",
    },
    "coral-sunrise": {
        "background": "#fffbf7",
        "card": "#fff7ed",
        "text": "#1c1917",
        "muted": "#78716c",
        "brand": "#f97316",
        "accent": "#fb923c",
        "headline": "#ea580c",
        "cta_from": "#f97316",
        "cta_to": "#ea580c",
        "cta_text": "#ffffff",
        "chip_bg": "#ffedd5",
        "chip_text": "#c2410c",
        "chip_border": "#fed7aa",
        "savings_bg": "#ffedd5",
        "savings_text": "#c2410c",
        "savings_border": "#fdba74",
        "featured_badge_bg": "#f97316",
        "featured_badge_text": "#ffffff",
        "border": "#fed7aa",
    },
    "clean-slate": {
        "background": "#f8fafc",
        "card": "#ffffff",
        "text": "#0f172a",
        "muted": "#64748b",
        "brand": "#0ea5e9",
        "accent": "#38bdf8",
        "headline": "#0284c7",
        "cta_from": "#0ea5e9",
        "cta_to": "#0284c7",
        "cta_text": "#ffffff",
        "chip_bg": "#e0f2fe",
        "chip_text": "#0369a1",
        "chip_border": "#bae6fd",
        "savings_bg": "#e0f2fe",
        "savings_text": "#0369a1",
        "savings_border": "#7dd3fc",
        "featured_badge_bg": "#0ea5e9",
        "featured_badge_text": "#ffffff",
        "border": "#cbd5e1",
    },
    "royal-velvet": {
        "background": "#0f0720",
        "card": "#1a1033",
        "text": "#f5f3ff",
        "muted": "#c4b5fd",
        "brand": "#a855f7",
        "accent": "#c084fc",
        "headline": "#c084fc",
        "cta_from": "#a855f7",
        "cta_to": "#9333ea",
        "cta_text": "#ffffff",
        "chip_bg": "#3b2360",
        "chip_text": "#d8b4fe",
        "chip_border": "#6b3fa0",
        "savings_bg": "#3b2360",
        "savings_text": "#d8b4fe",
        "savings_border": "#6b3fa0",
        "featured_badge_bg": "#a855f7",
        "featured_badge_text": "#ffffff",
        "border": "#4c1d95",
    },
    "fire-sale": {
        "background": "#18181b",
        "card": "#27272a",
        "text": "#fafafa",
        "muted": "#a1a1aa",
        "brand": "#ef4444",
        "accent": "#f87171",
        "headline": "#f87171",
        "cta_from": "#ef4444",
        "cta_to": "#dc2626",
        "cta_text": "#ffffff",
        "chip_bg": "#4a1d1d",
        "chip_text": "#fca5a5",
        "chip_border": "#7f2d2d",
        "savings_bg": "#4a1d1d",
        "savings_text": "#fca5a5",
        "savings_border": "#7f2d2d",
        "featured_badge_bg": "#ef4444",
        "featured_badge_text": "#ffffff",
        "border": "#3f3f46",
    },
    "natural-calm": {
        "background": "#fefdf8",
        "card": "#f7f6f0",
        "text": "#1a1a1a",
        "muted": "#57534e",
        "brand": "#15803d",
        "accent": "#22c55e",
        "headline": "#15803d",
        "cta_from": "#22c55e",
        "cta_to": "#16a34a",
        "cta_text": "#ffffff",
        "chip_bg": "#dcfce7",
        "chip_text": "#166534",
        "chip_border": "#bbf7d0",
        "savings_bg": "#dcfce7",
        "savings_text": "#166534",
        "savings_border": "#86efac",
        "featured_badge_bg": "#15803d",
        "featured_badge_text": "#ffffff",
        "border": "#d6d3d1",
    },
    "cyber-pulse": {
        "background": "#0c0a1d",
        "card": "#1e1b4b",
        "text": "#eef2ff",
        "muted": "#a5b4fc",
        "brand": "#6366f1",
        "accent": "#818cf8",
        "headline": "#a5b4fc",
        "cta_from": "#6366f1",
        "cta_to": "#4f46e5",
        "cta_text": "#ffffff",
        "chip_bg": "#312e81",
        "chip_text": "#c7d2fe",
        "chip_border": "#4f46e5",
        "savings_bg": "#312e81",
        "savings_text": "#c7d2fe",
        "savings_border": "#4f46e5",
        "featured_badge_bg": "#6366f1",
        "featured_badge_text": "#ffffff",
        "border": "#3730a3",
    },
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

UNIVERSAL_BUNDLE_TEMPLATE_STYLES = [
    "    html{font-size:62.5%}",
    "    *{margin:0;padding:0;box-sizing:border-box}",
    "    :root{--sl-background:var(--sl-theme-background);--sl-text:var(--sl-theme-text);--sl-accent:var(--sl-theme-accent);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--sl-text);background:var(--sl-background)}",
    "    body{font-size:1.6rem;background:var(--sl-background);color:var(--sl-text)}",
    "    main{width:min(112rem,100%);margin:0 auto;padding:1.6rem 1.6rem 12rem;display:grid;gap:1.8rem}",
    "    .sl-countdown{display:flex;align-items:center;justify-content:center;gap:0.8rem;background:var(--sl-countdown-bg,var(--sl-card));color:var(--sl-countdown-text);border-radius:0.8rem;padding:1rem 1.4rem;font-weight:800}",
    "    .sl-countdown[data-sticky='true']{position:sticky;top:0;z-index:20}",
    "    .sl-countdown[data-transparent='true']{background:color-mix(in srgb,var(--sl-countdown-bg,var(--sl-card)) 82%,transparent)}",
    "    .sl-countdown[data-marquee='true']{overflow:hidden;white-space:nowrap}",
    "    .sl-countdown[data-marquee='true'] .sl-countdown-content{display:inline-flex;align-items:center;gap:0.8rem;animation:sl-marquee 14s linear infinite}",
    "    .sl-countdown time{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:color-mix(in srgb,var(--sl-countdown-text) 16%,transparent);border-radius:0.4rem;padding:0.3rem 0.7rem}",
    "    @keyframes sl-marquee{from{transform:translateX(100%)}to{transform:translateX(-100%)}}",
    "    .sl-brand-label{display:flex;align-items:center;gap:0.8rem;color:var(--sl-accent);font-size:1.2rem;font-weight:900;letter-spacing:0.08em;text-transform:uppercase}",
    "    .sl-brand-label::before{content:'';width:0.9rem;height:0.9rem;border-radius:999px;background:var(--sl-accent)}",
    "    .sl-seo-title h1,.sl-headline h2{font-size:clamp(3.2rem,6vw,6.4rem);line-height:0.98;letter-spacing:0;margin:0}",
    "    .sl-seo-title h1,.sl-headline h2{color:var(--sl-headline)}",
    "    .sl-subheadline p{font-size:clamp(1.8rem,2vw,2.2rem);line-height:1.45;color:var(--sl-muted);max-width:72rem}",
    "    .sl-hero-media{display:flex;gap:1rem;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:0.4rem}",
    "    .sl-hero-media img{flex:0 0 min(82vw,52rem);width:min(82vw,52rem);aspect-ratio:4/3;object-fit:cover;border-radius:0.8rem;border:1px solid var(--sl-border);background:var(--sl-card);scroll-snap-align:start}",
    "    .sl-trust-badges{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:0.8rem}",
    "    .sl-trust-badge{display:flex;align-items:center;gap:0.8rem;border:1px solid var(--sl-chip-border);background:var(--sl-chip-bg);color:var(--sl-chip-text);border-radius:0.8rem;padding:1rem 1.2rem;font-weight:800}",
    "    .sl-price-options{display:grid;grid-template-columns:1fr;gap:1.4rem;width:min(76rem,100%);margin:0 auto}",
    "    .sl-price-option{position:relative;display:grid;grid-template-columns:10.4rem minmax(0,1fr) 2.8rem;gap:1.6rem;align-items:center;border:2px solid var(--sl-border);border-radius:0.8rem;padding:1.6rem;background:var(--sl-card)}",
    "    .sl-price-option.selected{border-color:var(--sl-accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--sl-accent) 25%,transparent)}",
    "    .sl-price-option input{width:2rem;height:2rem;accent-color:var(--sl-accent)}",
    "    .sl-price-option img{width:10.4rem;aspect-ratio:1/1;object-fit:cover;border-radius:0.6rem;background:var(--sl-background)}",
    "    .sl-price-copy{display:grid;gap:0.7rem}",
    "    .sl-price-option strong{font-size:2rem;line-height:1.2}",
    "    .sl-price-description{color:var(--sl-muted);line-height:1.45}",
    "    .sl-price-row{display:flex;align-items:center;gap:1.2rem;flex-wrap:wrap}",
    "    .sl-price-amount{font-size:2.4rem;font-weight:900;color:var(--sl-brand)}",
    "    .sl-regular-price{color:var(--sl-muted);text-decoration:line-through;font-size:1.7rem}",
    "    .sl-price-option[data-expired='true'] .sl-regular-price,.sl-price-option[data-expired='true'] .sl-savings{display:none}",
    "    .sl-badge{display:inline-flex;width:max-content;font-size:1.2rem;font-weight:900;color:var(--sl-featured-badge-text);background:var(--sl-featured-badge-bg);padding:0.3rem 0.8rem;border-radius:999px}",
    "    .sl-savings{font-size:1.3rem;font-weight:800;color:var(--sl-savings-text);background:var(--sl-savings-bg);border:1px solid var(--sl-savings-border);border-radius:999px;padding:0.25rem 0.7rem}",
    "    .sl-content-blocks,.sl-faq{display:grid;gap:1rem}",
    "    .sl-refund-policy{width:min(76rem,100%);margin:0 auto;border:1px solid var(--sl-border);background:var(--sl-card);border-radius:0.8rem;padding:1.6rem;display:grid;gap:1rem}",
    "    .sl-refund-policy h2{font-size:2rem}",
    "    .sl-refund-policy h3{font-size:1.8rem}",
    "    .sl-refund-policy p{color:var(--sl-muted);line-height:1.55}",
    "    .sl-refund-policy-applies{font-weight:800;color:var(--sl-brand)}",
    "    .sl-content-block{display:grid;grid-template-columns:minmax(0,1fr) minmax(12rem,24rem);gap:1.2rem;align-items:center;border-top:1px solid var(--sl-border);padding-top:1.4rem}",
    "    .sl-content-block h3{font-size:2.2rem;margin-bottom:0.6rem}",
    "    .sl-content-block p,.sl-faq p{color:var(--sl-muted);line-height:1.55}",
    "    .sl-content-block img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:0.8rem}",
    "    .sl-faq details{border:1px solid var(--sl-border);background:var(--sl-card);border-radius:0.8rem;padding:1.2rem}",
    "    .sl-faq summary{cursor:pointer;font-weight:900}",
    "    .sl-checkout-cta{position:fixed;left:0;right:0;bottom:0;z-index:10;background:color-mix(in srgb,var(--sl-background) 94%,transparent);border-top:1px solid var(--sl-border);padding:1.2rem 1.6rem;display:flex;justify-content:center}",
    "    .sl-cta{display:inline-flex;width:min(48rem,100%);align-items:center;justify-content:center;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:0.8rem;padding:1.5rem 1.8rem;font-size:1.7rem;font-weight:900;text-decoration:none}",
    "    .sl-legal{display:flex;gap:1.2rem;flex-wrap:wrap;justify-content:center;font-size:1.3rem;color:var(--sl-muted);padding-top:1rem}",
    "    .sl-legal a{color:inherit}",
    "    @media (max-width: 700px){main{padding-inline:1.2rem}.sl-price-option{grid-template-columns:8.8rem minmax(0,1fr) 2.4rem;gap:1rem;padding:1.2rem}.sl-price-option img{width:8.8rem}.sl-content-block{grid-template-columns:1fr}.sl-seo-title h1,.sl-headline h2{font-size:3.8rem}}",
]

TEMPLATE_STYLES = {
    "simple": SIMPLE_TEMPLATE_STYLES,
    "universal_bundle": UNIVERSAL_BUNDLE_TEMPLATE_STYLES,
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


def theme_tokens(page: dict[str, Any]) -> dict[str, str]:
    theme = page.get("theme") or {}
    preset_name = str(theme.get("preset") or "techno-green")
    tokens = dict(UNIVERSAL_BUNDLE_THEME_PRESETS.get(preset_name, UNIVERSAL_BUNDLE_THEME_PRESETS["techno-green"]))
    legacy_color = theme.get("color") or {}
    if legacy_color.get("background"):
        tokens["background"] = legacy_color["background"]
    if legacy_color.get("text"):
        tokens["text"] = legacy_color["text"]
    if legacy_color.get("accent"):
        tokens["accent"] = legacy_color["accent"]
        tokens["brand"] = legacy_color["accent"]
    tokens.update(theme.get("tokens") or {})
    tokens.setdefault("countdown_text", "#ffffff")
    return tokens


def css_var_name(token_name: str) -> str:
    return token_name.replace("_", "-")


def render_template_styles(page: dict[str, Any]) -> list[str]:
    template = template_name(page)
    try:
        styles = TEMPLATE_STYLES[template]
    except KeyError as exc:
        raise RenderError(f"Unsupported page theme.template '{template}'.") from exc

    if template == "universal_bundle":
        tokens = theme_tokens(page)
        token_vars = ";".join(
            f"--sl-{css_var_name(key)}:{escape(str(value))}"
            for key, value in tokens.items()
        )
        return [
            f"    :root{{{token_vars};--sl-theme-background:{escape(tokens['background'])};--sl-theme-text:{escape(tokens['text'])};--sl-theme-accent:{escape(tokens['accent'])}}}",
            *styles,
        ]

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
    has_legal_footer_section = any(section.get("type") == "legal_footer" for section in page.get("sections", []))
    legal_footer = "" if has_legal_footer_section else render_legal_footer(page.get("legal") or {})
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
        render_page_interactions_script(page),
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
    if section_type == "countdown_timer":
        return render_countdown_timer(section)
    if section_type == "seo_title":
        return render_seo_title(section, page, products_by_id)
    if section_type == "brand_label":
        return render_brand_label(section, page)
    if section_type == "hero_media":
        return render_hero_media(section, offer, products_by_id)
    if section_type == "headline":
        return render_headline(section)
    if section_type == "subheadline":
        return render_subheadline(section)
    if section_type == "trust_badges":
        return render_trust_badges(section)
    if section_type == "hero":
        return render_hero(section)
    if section_type == "offer_price_selector":
        return render_offer_price_selector(offer, products_by_id)
    if section_type == "refund_policy":
        return render_refund_policy(section, offer, products_by_id)
    if section_type == "faq":
        return render_faq(section)
    if section_type == "content_block":
        return render_content_blocks(section)
    if section_type == "checkout_cta":
        return render_checkout_cta(section, offer, resolved_offer, checkout_url)
    if section_type == "legal_footer":
        return render_legal_footer(page.get("legal") or {}, section)
    return f"    <section data-section-id=\"{escape(str(section.get('id', '')))}\"></section>"


def first_offer_product(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for item in offer.get("items", []):
        product = products_by_id.get(item.get("product_id", ""))
        if product:
            return product
    return {}


def render_countdown_timer(section: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    duration = int(section.get("duration_minutes") or 0)
    label = escape(str(section.get("start_text") or section.get("label") or "Offer expires in"))
    end_text = escape(str(section.get("end_text") or "Offer expired"))
    start_color = escape(str(section.get("start_color") or "#111827"))
    end_color = escape(str(section.get("end_color") or "#ef4444"))
    style = f"--sl-countdown-bg:{start_color};background:{start_color}"
    return "\n".join([
        f"    <section class=\"sl-countdown\" data-section-id=\"{escape(str(section.get('id', 'countdown')))}\" data-section-type=\"countdown_timer\" data-duration-minutes=\"{duration}\" data-persistent=\"{str(bool(section.get('persistent'))).lower()}\" data-sticky=\"{str(bool(section.get('sticky'))).lower()}\" data-transparent=\"{str(bool(section.get('transparent'))).lower()}\" data-marquee=\"{str(bool(section.get('marquee'))).lower()}\" data-start-text=\"{label}\" data-end-text=\"{end_text}\" data-start-color=\"{start_color}\" data-end-color=\"{end_color}\" style=\"{style}\">",
        "      <span class=\"sl-countdown-content\">",
        f"        <span data-countdown-label>{label}</span>",
        f"        <time data-countdown-display>{duration}:00</time>" if duration else "",
        "      </span>",
        "    </section>",
    ])


def render_seo_title(
    section: dict[str, Any],
    page: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
) -> str:
    product_name = next((product.get("name") for product in products_by_id.values() if product.get("name")), "")
    title = escape(str(section.get("label") or (page.get("seo") or {}).get("title") or product_name or page.get("name") or ""))
    return "\n".join([
        f"    <section class=\"sl-seo-title\" data-section-id=\"{escape(str(section.get('id', 'seo-title')))}\" data-section-type=\"seo_title\">",
        f"      <h1>{title}</h1>",
        "    </section>",
    ])


def render_brand_label(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    label = escape(str(section.get("label") or (page.get("seo") or {}).get("title") or page.get("name") or ""))
    return "\n".join([
        f"    <section class=\"sl-brand-label\" data-section-id=\"{escape(str(section.get('id', 'brand-label')))}\" data-section-type=\"brand_label\">",
        f"      <span>{label}</span>",
        "    </section>",
    ])


def render_hero_media(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
) -> str:
    product = first_offer_product(offer, products_by_id)
    images = hero_media_images(section, offer, product)
    rendered = [
        f"      <img src=\"{escape(str(image_url))}\" alt=\"{escape(str(product.get('name') or 'Product image'))}\">"
        for image_url in images
    ]
    if not rendered:
        return ""
    return "\n".join([
        f"    <section class=\"sl-hero-media\" data-section-id=\"{escape(str(section.get('id', 'hero-media')))}\" data-section-type=\"hero_media\" data-media-count=\"{len(rendered)}\">",
        *rendered,
        "    </section>",
    ])


def hero_media_images(
    section: dict[str, Any],
    offer: dict[str, Any],
    product: dict[str, Any],
) -> list[str]:
    section_images = section.get("images") or []
    if section_images:
        return section_images

    offer_image = (offer.get("presentation") or {}).get("hero_image_url")
    if isinstance(offer_image, str) and offer_image:
        return [offer_image]

    product_images = product.get("images") or []
    if offer.get("offer_type") == "bundle":
        first = first_image(product)
        return [first] if first else []
    return product_images


def render_headline(section: dict[str, Any]) -> str:
    return "\n".join([
        f"    <section class=\"sl-headline\" data-section-id=\"{escape(str(section.get('id', 'headline')))}\" data-section-type=\"headline\">",
        f"      <h2>{escape(str(section.get('text') or ''))}</h2>",
        "    </section>",
    ])


def render_subheadline(section: dict[str, Any]) -> str:
    return "\n".join([
        f"    <section class=\"sl-subheadline\" data-section-id=\"{escape(str(section.get('id', 'subheadline')))}\" data-section-type=\"subheadline\">",
        f"      <p>{escape(str(section.get('text') or ''))}</p>",
        "    </section>",
    ])


def render_trust_badges(section: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    badges = section.get("badges") or []
    rendered = [
        "\n".join([
            "      <div class=\"sl-trust-badge\">",
            f"        <span>{escape(str(badge.get('emoji') or ''))}</span>",
            f"        <strong>{escape(str(badge.get('label') or ''))}</strong>",
            "      </div>",
        ])
        for badge in badges
    ]
    if not rendered:
        return ""
    return "\n".join([
        f"    <section class=\"sl-trust-badges\" data-section-id=\"{escape(str(section.get('id', 'trust-badges')))}\" data-section-type=\"trust_badges\">",
        *rendered,
        "    </section>",
    ])


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
            image_url = price_image(product, price, option)
            description = escape(str(option.get("description") or price.get("description") or product.get("description") or ""))
            regular_unit_amount = option.get("regular_unit_amount") or price.get("regular_unit_amount")
            savings_pct = option.get("display_discount_pct") or price.get("discount_pct")
            if not savings_pct and regular_unit_amount:
                savings_pct = discount_pct(amount, int(regular_unit_amount))
            cards.append("\n".join([
                f"      <article class=\"sl-price-option\" data-price-id=\"{escape(str(price.get('price_id', '')))}\" data-default=\"{default_attr}\" data-sale-amount=\"{amount}\" data-regular-amount=\"{int(regular_unit_amount) if regular_unit_amount else amount}\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
                f"        <img src=\"{escape(image_url)}\" alt=\"{escape(str(product.get('name') or label))}\">" if image_url else "",
                "        <div class=\"sl-price-copy\">",
                f"          <span class=\"sl-badge\">{badge}</span>" if badge else "",
                f"          <strong>{label}</strong>",
                f"          <p class=\"sl-price-description\">{description}</p>" if description else "",
                "          <div class=\"sl-price-row\">",
                f"            <span class=\"sl-price-amount\" data-price-amount>{escape(format_money(amount, currency))}</span>",
                f"            <span class=\"sl-regular-price\">{escape(format_money(int(regular_unit_amount), currency))}</span>" if regular_unit_amount else "",
                f"            <span class=\"sl-savings\">Save {int(savings_pct)}%</span>" if savings_pct else "",
                "          </div>",
                "        </div>",
                f"        <input type=\"radio\" name=\"sl-price-{escape(product_id)}\" value=\"{escape(str(price.get('price_id', '')))}\" {'checked' if default_attr == 'true' else ''}>",
                "      </article>",
            ]))
    return "\n".join([
        "    <section class=\"sl-price-selector\" data-section-type=\"offer_price_selector\">",
        "      <div class=\"sl-price-options\">",
        *cards,
        "      </div>",
        "    </section>",
    ])


def first_image(product: dict[str, Any]) -> str:
    images = product.get("images") or []
    if images and isinstance(images[0], str):
        return images[0]
    return ""


def price_image(product: dict[str, Any], price: dict[str, Any], option: dict[str, Any]) -> str:
    image_url = option.get("image_url") or price.get("image_url")
    if isinstance(image_url, str) and image_url:
        return image_url
    return first_image(product)


def discount_pct(unit_amount: int, regular_unit_amount: int) -> int:
    if regular_unit_amount <= 0 or unit_amount >= regular_unit_amount:
        return 0
    return round((1 - (unit_amount / regular_unit_amount)) * 100)


def render_refund_policy(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
) -> str:
    product = first_offer_product(offer, products_by_id)
    policy = product.get("refund_policy") or {}
    if not policy:
        return ""

    heading = escape(str(section.get("heading") or "Refund Policy"))
    short_label = escape(str(policy.get("short_label") or "Refund policy"))
    full_policy = escape(str(policy.get("full_policy") or ""))
    applies_to = escape(", ".join(refund_policy_applies_to(offer, products_by_id)))
    return "\n".join([
        f"    <section class=\"sl-refund-policy\" data-section-id=\"{escape(str(section.get('id', 'refund-policy')))}\" data-section-type=\"refund_policy\">",
        f"      <h2>{heading}</h2>",
        f"      <h3>{short_label}</h3>",
        f"      <p class=\"sl-refund-policy-applies\">Applies to: {applies_to}</p>" if applies_to else "",
        f"      <p>{full_policy}</p>" if full_policy else "",
        "    </section>",
    ])


def refund_policy_applies_to(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for item in offer.get("items", []):
        product = products_by_id.get(item.get("product_id", ""))
        product_name = product.get("name") if product else ""
        for option in item.get("selectable_prices") or []:
            price = find_price(product, option.get("price_id", "")) if product else {}
            label = option.get("label") or price.get("label")
            labels.append(f"{product_name} - {label}" if product_name and label else str(label or product_name))
    return [label for label in labels if label]


def render_faq(section: dict[str, Any]) -> str:
    items = section.get("items") or []
    rendered = [
        "\n".join([
            "      <details>",
            f"        <summary>{escape(str(item.get('question') or ''))}</summary>",
            f"        <p>{escape(str(item.get('answer') or ''))}</p>",
            "      </details>",
        ])
        for item in items
    ]
    if not rendered:
        return ""
    return "\n".join([
        f"    <section class=\"sl-faq\" data-section-id=\"{escape(str(section.get('id', 'faq')))}\" data-section-type=\"faq\">",
        *rendered,
        "    </section>",
    ])


def render_content_blocks(section: dict[str, Any]) -> str:
    blocks = section.get("blocks") or []
    rendered = []
    for block in blocks:
        image_url = block.get("image_url")
        rendered.append("\n".join([
            "      <article class=\"sl-content-block\">",
            "        <div>",
            f"          <h3>{escape(str(block.get('title') or ''))}</h3>",
            f"          <p>{escape(str(block.get('text') or ''))}</p>",
            "        </div>",
            f"        <img src=\"{escape(str(image_url))}\" alt=\"{escape(str(block.get('title') or 'Content image'))}\">" if image_url else "",
            "      </article>",
        ]))
    if not rendered:
        return ""
    return "\n".join([
        f"    <section class=\"sl-content-blocks\" data-section-id=\"{escape(str(section.get('id', 'content-blocks')))}\" data-section-type=\"content_block\">",
        *rendered,
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
        f"      <a class=\"sl-cta\" href=\"{href}\" data-cta-label=\"{label}\" data-cta-currency=\"{escape(currency)}\" data-cta-amount=\"{subtotal}\">{label} - {escape(format_money(subtotal, currency))}</a>",
        "    </section>",
    ])


def render_legal_footer(legal: dict[str, Any], section: dict[str, Any] | None = None) -> str:
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
    copyright_text = (section or {}).get("copyright")
    if not rendered_links and not copyright_text:
        return ""
    return "\n".join([
        "    <footer class=\"sl-legal\" data-section-type=\"legal_footer\">",
        *rendered_links,
        f"      <span>{escape(str(copyright_text))}</span>" if copyright_text else "",
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


def render_page_interactions_script(page: dict[str, Any]) -> str:
    has_countdown = any(section.get("type") == "countdown_timer" for section in page.get("sections", []))
    has_price_selector = any(section.get("type") == "offer_price_selector" for section in page.get("sections", []))
    if not has_countdown and not has_price_selector:
        return ""
    page_id = escape(str(page.get("page_id") or "page"))
    return "\n".join([
        "  <script>",
        "    document.addEventListener('DOMContentLoaded', () => {",
        f"      const pageId = \"{page_id}\";",
        "      const money = (amount, currency) => {",
        "        const cents = Number(amount || 0);",
        "        const code = String(currency || 'usd').toUpperCase();",
        "        if (code === 'USD') return `$${(cents / 100).toFixed(2)}`;",
        "        return `${code} ${(cents / 100).toFixed(2)}`;",
        "      };",
        "      const cta = document.querySelector('[data-section-type=\"checkout_cta\"] .sl-cta');",
        "      const cards = Array.from(document.querySelectorAll('.sl-price-option'));",
        "      const currentAmount = (card) => card?.dataset.expired === 'true' ? card.dataset.regularAmount : card?.dataset.saleAmount;",
        "      const updateCta = (card) => {",
        "        if (!cta || !card) return;",
        "        const amount = currentAmount(card);",
        "        const currency = card.dataset.currency || cta.dataset.ctaCurrency || 'usd';",
        "        const label = cta.dataset.ctaLabel || 'Checkout';",
        "        cta.dataset.ctaAmount = amount || '0';",
        "        cta.textContent = `${label} - ${money(amount, currency)}`;",
        "      };",
        "      const selectCard = (card) => {",
        "        if (!card) return;",
        "        cards.forEach((item) => item.classList.toggle('selected', item === card));",
        "        const radio = card.querySelector('input[type=\"radio\"]');",
        "        if (radio) radio.checked = true;",
        "        updateCta(card);",
        "      };",
        "      cards.forEach((card) => {",
        "        card.addEventListener('click', () => selectCard(card));",
        "        const radio = card.querySelector('input[type=\"radio\"]');",
        "        if (radio) radio.addEventListener('change', () => selectCard(card));",
        "      });",
        "      selectCard(cards.find((card) => card.dataset.default === 'true') || cards[0]);",
        "      const expireDiscounts = () => {",
        "        cards.forEach((card) => {",
        "          const regular = Number(card.dataset.regularAmount || 0);",
        "          const sale = Number(card.dataset.saleAmount || 0);",
        "          if (!regular || regular <= sale) return;",
        "          card.dataset.expired = 'true';",
        "          const priceAmount = card.querySelector('[data-price-amount]');",
        "          if (priceAmount) priceAmount.textContent = money(regular, card.dataset.currency);",
        "        });",
        "        updateCta(document.querySelector('.sl-price-option.selected') || cards[0]);",
        "      };",
        "      document.querySelectorAll('[data-section-type=\"countdown_timer\"]').forEach((section) => {",
        "        const duration = Number(section.dataset.durationMinutes || 0) * 60;",
        "        const display = section.querySelector('[data-countdown-display]');",
        "        const label = section.querySelector('[data-countdown-label]');",
        "        if (!duration || !display) return;",
        "        const persistent = section.dataset.persistent === 'true';",
        "        const storageKey = `stripe-link:${pageId}:countdown:${section.dataset.sectionId || 'timer'}`;",
        "        let deadline = Date.now() + duration * 1000;",
        "        if (persistent) {",
        "          const stored = localStorage.getItem(storageKey);",
        "          if (stored === 'expired') deadline = Date.now();",
        "          else if (stored) deadline = Number(stored) || deadline;",
        "          else localStorage.setItem(storageKey, String(deadline));",
        "        }",
        "        const render = () => {",
        "          const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));",
        "          const minutes = Math.floor(remaining / 60);",
        "          const seconds = String(remaining % 60).padStart(2, '0');",
        "          display.textContent = `${minutes}:${seconds}`;",
        "          if (remaining <= 0) {",
        "            if (label) label.textContent = section.dataset.endText || 'Offer expired';",
        "            section.style.setProperty('--sl-countdown-bg', section.dataset.endColor || '#ef4444');",
        "            section.style.background = section.dataset.endColor || '#ef4444';",
        "            if (persistent) localStorage.setItem(storageKey, 'expired');",
        "            expireDiscounts();",
        "            return false;",
        "          }",
        "          return true;",
        "        };",
        "        if (!render()) return;",
        "        const interval = window.setInterval(() => {",
        "          if (!render()) window.clearInterval(interval);",
        "        }, 1000);",
        "      });",
        "    });",
        "  </script>",
    ])
