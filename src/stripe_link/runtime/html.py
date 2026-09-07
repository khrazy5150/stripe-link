from html import escape, unescape
from dataclasses import dataclass
from decimal import Decimal
import base64
import json
import re
from typing import Any
from urllib.parse import urlencode, urlparse

from stripe_link.platform_config import default_favicon_url
from stripe_link.domain.bargain import FROM_PREFIX, derived_bargain
from stripe_link.domain.business_types import BUSINESS_TYPES, resolve_entity_type
from stripe_link.domain.composition import compose_page, element_channel
from stripe_link.domain.connect_sync import site_seo_enabled
from stripe_link.domain.documents import PRODUCT_CONDITIONS
from stripe_link.domain.opportunities import STAGE_LANDING, STAGE_POST_PURCHASE, derived_offer_type, stage_opportunities
from stripe_link.domain.pricing import PricingError, expand_offer, find_price, resolve_offer, single_unit_price
from stripe_link.domain.semantic import is_bundle, resolve_semantic_model, subject_from_model
from stripe_link.domain.reviews import aggregate_reviews, markup_eligible
from stripe_link.domain.image_crop import crop_style_vars
from stripe_link.domain.video_embeds import parse_video_embed
from stripe_link.domain.section_theme import section_theme_vars
from stripe_link.domain.service_pricing import resolve_service_price


class RenderError(ValueError):
    pass


CURRENCY_SYMBOLS = {
    "usd": "$",
    "eur": "€",
    "gbp": "£",
}
SYSTEM_FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif"
SYSTEM_MONO_FONT_STACK = "ui-monospace,SFMono-Regular,Menlo,monospace"
# The opening quotation mark wants a heavy geometric sans to read as FAT rather than as a stray tick.
# Inter is named first as the author specified, but it is not self-hosted for published pages, so in
# practice this resolves to the system sans unless the visitor happens to have Inter installed.
QUOTE_MARK_FONT = "Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"
FONT_FALLBACK_STACKS = {
    "system": SYSTEM_FONT_STACK,
    "sans-serif": "sans-serif",
    "serif": "serif",
    "monospace": "monospace",
}
CURRENT_YEAR_TOKEN = "{{current_year}}"
# The landing page shows ONLY the product's standard-context prices. `sale` / `flash_sale` are alternate
# pricing MODES, not extra cards — a page shows them only when the builder explicitly switches into a Sale
# or Flash Sale mode (a future phase), at which point the active context replaces "standard" here. Upsell /
# downsell / order-bump prices belong to the post-checkout flow and are excluded for the same reason.
LANDING_PAGE_PRICE_CONTEXTS = {"standard"}
HEADLINE_LOWERCASE_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "but",
    "or",
    "nor",
    "for",
    "yet",
    "so",
    "as",
    "at",
    "by",
    "in",
    "of",
    "off",
    "on",
    "per",
    "to",
    "up",
    "via",
    "if",
    "vs",
    "vs.",
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
    # Socialite palettes (ported from stripe-cart/templates/core.js). CTA gradients come from cta_from/cta_to
    # (the button already renders linear-gradient(135deg, ...)). See plans/SOCIALITE_PARITY.md.
    "linkedin-blue": {
        "background": "#f3f2ef",
        "card": "#ffffff",
        "text": "#000000",
        "muted": "#666666",
        "brand": "#0077b5",
        "accent": "#00a0dc",
        "headline": "#000000",
        "cta_from": "#0077b5",
        "cta_to": "#005582",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(0,119,181,.1)",
        "chip_text": "#0077b5",
        "chip_border": "rgba(0,119,181,.2)",
        "savings_bg": "rgba(34,197,94,.1)",
        "savings_text": "#16a34a",
        "savings_border": "rgba(34,197,94,.2)",
        "featured_badge_bg": "#0077b5",
        "featured_badge_text": "#ffffff",
        "border": "#e5e7eb",
    },
    "instagram-gradient": {
        "background": "#fafafa",
        "card": "#ffffff",
        "text": "#262626",
        "muted": "#8e8e8e",
        "brand": "#e1306c",
        "accent": "#fd1d1d",
        "headline": "#262626",
        "cta_from": "rgb(112,28,242)",
        "cta_to": "rgb(231,52,139)",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(225,48,108,.1)",
        "chip_text": "#e1306c",
        "chip_border": "rgba(225,48,108,.2)",
        "savings_bg": "rgba(34,197,94,.1)",
        "savings_text": "#16a34a",
        "savings_border": "rgba(34,197,94,.2)",
        "featured_badge_bg": "#e1306c",
        "featured_badge_text": "#ffffff",
        "border": "#dbdbdb",
        "avatar_ring": "linear-gradient(90deg,#833ab4,#fcb045)",
    },
    "tiktok-dark": {
        "background": "#000000",
        "card": "#121212",
        "text": "#ffffff",
        "muted": "#8a8a8a",
        "brand": "#ff0050",
        "accent": "#00f2ea",
        "headline": "#ffffff",
        "cta_from": "#ff0050",
        "cta_to": "#00f2ea",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(255,0,80,.15)",
        "chip_text": "#ff6090",
        "chip_border": "rgba(255,0,80,.3)",
        "savings_bg": "rgba(0,242,234,.15)",
        "savings_text": "#00f2ea",
        "savings_border": "rgba(0,242,234,.3)",
        "featured_badge_bg": "#ff0050",
        "featured_badge_text": "#ffffff",
        "border": "#2a2a2a",
        "avatar_ring": "linear-gradient(90deg,#ff0050,#00f2ea)",
    },
    "youtube-red": {
        "background": "#ffffff",
        "card": "#ffffff",
        "text": "#0f0f0f",
        "muted": "#606060",
        "brand": "#ff0000",
        "accent": "#cc0000",
        "headline": "#0f0f0f",
        "cta_from": "#ff0000",
        "cta_to": "#cc0000",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(255,0,0,.1)",
        "chip_text": "#cc0000",
        "chip_border": "rgba(255,0,0,.2)",
        "savings_bg": "rgba(34,197,94,.1)",
        "savings_text": "#16a34a",
        "savings_border": "rgba(34,197,94,.2)",
        "featured_badge_bg": "#ff0000",
        "featured_badge_text": "#ffffff",
        "border": "#e5e7eb",
    },
    "twitter-dark": {
        "background": "#15202b",
        "card": "#192734",
        "text": "#ffffff",
        "muted": "#8899a6",
        "brand": "#1d9bf0",
        "accent": "#1a8cd8",
        "headline": "#ffffff",
        "cta_from": "#1d9bf0",
        "cta_to": "#1a8cd8",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(29,155,240,.15)",
        "chip_text": "#1d9bf0",
        "chip_border": "rgba(29,155,240,.3)",
        "savings_bg": "rgba(0,186,124,.15)",
        "savings_text": "#00ba7c",
        "savings_border": "rgba(0,186,124,.3)",
        "featured_badge_bg": "#1d9bf0",
        "featured_badge_text": "#ffffff",
        "border": "#38444d",
    },
    "professional-gray": {
        "background": "#f8f9fa",
        "card": "#ffffff",
        "text": "#212529",
        "muted": "#6c757d",
        "brand": "#495057",
        "accent": "#6c757d",
        "headline": "#212529",
        "cta_from": "#343a40",
        "cta_to": "#212529",
        "cta_text": "#ffffff",
        "chip_bg": "rgba(73,80,87,.08)",
        "chip_text": "#495057",
        "chip_border": "rgba(73,80,87,.15)",
        "savings_bg": "rgba(25,135,84,.1)",
        "savings_text": "#198754",
        "savings_border": "rgba(25,135,84,.2)",
        "featured_badge_bg": "#495057",
        "featured_badge_text": "#ffffff",
        "border": "#dee2e6",
    },
}

UNIVERSAL_BUNDLE_TEMPLATE_STYLES = [
    "    html{font-size:62.5%;-webkit-text-size-adjust:100%}",
    "    *{margin:0;padding:0;box-sizing:border-box}",
    "    :root{--sl-background:var(--sl-theme-background);--sl-text:var(--sl-theme-text);--sl-accent:var(--sl-theme-accent);--sl-radius:1.6rem;font-family:var(--sl-font-body);color:var(--sl-text);background:var(--sl-background)}",
    "    body{font-size:1.6rem;line-height:1.5;background:var(--sl-background);color:var(--sl-text);padding-bottom:8rem}",
    "    main{width:100%;padding:0 0 12rem;display:grid;gap:1.6rem}",
    "    main > :not(.sl-countdown):not(.sl-checkout-cta){width:min(52rem,calc(100% - 3.2rem));margin-left:auto;margin-right:auto}",
    "    .sl-countdown{width:100%;display:flex;align-items:center;justify-content:center;gap:0.8rem;background:var(--sl-countdown-bg,var(--sl-card));color:var(--sl-countdown-text);border-radius:0;padding:1.2rem 1.6rem;font-weight:800}",
    # display:flex above beats the hidden attribute's UA display:none, which made Banner Start inert.
    "    .sl-countdown[hidden]{display:none}",
    "    .sl-countdown[data-sticky='true']{position:sticky;top:0;z-index:20}",
    "    .sl-countdown[data-transparent='true']{background:color-mix(in srgb,var(--sl-countdown-bg,var(--sl-card)) 85%,transparent)}",
    "    .sl-countdown[data-marquee='true']{overflow:hidden;white-space:nowrap}",
    # Own keyframe name: `sl-marquee` is also defined by the client-logo strip further down, and the later
    # definition wins — which gave the countdown the logo animation (0 -> -50%), so it restarted from the
    # middle instead of wrapping off one edge and back in the other.
    "    .sl-countdown[data-marquee='true'] .sl-countdown-content{display:inline-flex;align-items:center;gap:0.8rem;animation:sl-countdown-marquee var(--sl-countdown-marquee-duration,14s) linear infinite}",
    # Scrolling past the deadline reads as a live offer that has already gone.
    "    .sl-countdown[data-expired='true'] .sl-countdown-content{animation:none}",
    "    .sl-countdown time{font-family:var(--sl-font-mono);background:color-mix(in srgb,var(--sl-countdown-text) 16%,transparent);border-radius:0.4rem;padding:0.3rem 0.7rem}",
    "    @keyframes sl-countdown-marquee{from{transform:translateX(100%)}to{transform:translateX(-100%)}}",
    "    .sl-brand-label{display:flex;align-items:center;justify-content:center;gap:0.8rem;color:var(--sl-brand-label-text);padding-top:1.6rem}",
    "    .sl-brand-label::before{content:'';width:1rem;height:1rem;border-radius:999px;background:var(--sl-brand-dot);box-shadow:0 0 0.8rem var(--sl-brand-dot)}",
    "    .sl-brand-label p{font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.08em;line-height:1.2;text-transform:uppercase;color:var(--sl-brand-label-text)}",
    "    .sl-brand-label a{color:inherit;text-decoration:none}",
    "    .sl-brand-label a:hover{text-decoration:underline;text-underline-offset:0.25em}",
    "    .sl-seo-title{text-align:center}",
    "    .sl-seo-title p{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;color:var(--sl-headline)}",
    "    .sl-mark-text{color:var(--sl-highlight-text)}",
    "    .sl-mark-bg{background:var(--sl-highlight-bg);color:var(--sl-highlight-bg-text);padding:0.1em 0.3em;border-radius:0.4rem}",
    "    .sl-headline{text-align:center;padding:0.8rem 0 0.4rem}",
    "    .sl-headline h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;font-weight:800;color:var(--sl-headline);letter-spacing:0}",
    "    .sl-subheadline{text-align:center}",
    "    .sl-subheadline p{font-size:1.5rem;line-height:1.55;color:var(--sl-subheadline-text);max-width:46rem;margin:0 auto}",
    # Hero headline + subheadline centered, matching the builder preview (which centers them for every template).
    "    .sl-hero{text-align:center}",
    "    .sl-hero h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;font-weight:800;color:var(--sl-headline);letter-spacing:0;max-width:52rem;margin:0 auto}",
    "    .sl-hero p{font-size:1.5rem;line-height:1.55;color:var(--sl-subheadline-text);max-width:46rem;margin:0 auto}",
    "    .sl-hero-media{position:relative;padding-top:0.8rem}",
    "    .sl-hero-figure{margin:0}",
    "    .sl-hero-caption{font-size:1.3rem;color:var(--sl-muted);text-align:center;margin-top:0.6rem;line-height:1.4}",
    "    .sl-hero-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;border-radius:var(--sl-radius)}",
    "    .sl-hero-track::-webkit-scrollbar{display:none}",
    "    .sl-hero-slide{flex:0 0 100%;scroll-snap-align:center}",
    "    .sl-hero-slide img,.sl-hero-slide video{width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;border-radius:var(--sl-radius);border:1px solid var(--sl-hero-border);background:var(--sl-hero-bg)}",
    "    .sl-hero-nav{position:absolute;top:calc(50% + 0.4rem);transform:translateY(-50%);width:3.8rem;height:3.8rem;border-radius:50%;border:0;background:rgba(255,255,255,.9);color:#111;font-size:2.2rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.18)}",
    "    .sl-hero-prev{left:0.8rem}",
    "    .sl-hero-next{right:0.8rem}",
    "    .sl-hero-counter{position:absolute;top:1.6rem;right:0.8rem;background:rgba(0,0,0,.55);color:#fff;font-size:1.3rem;font-weight:700;padding:0.3rem 0.9rem;border-radius:99.9rem}",
    "    .sl-hero-dots{display:flex;gap:0.6rem;justify-content:center;margin-top:0.8rem}",
    "    .sl-hero-dot{width:0.8rem;height:0.8rem;border-radius:50%;background:var(--sl-border);cursor:pointer}",
    "    .sl-hero-dot.is-active{background:var(--sl-brand)}",
    # Socialite hero overlays (plans/SOCIALITE_PARITY.md): positionable brand chip + profile avatar.
    "    .sl-hero-media.has-avatar{margin-bottom:6.4rem}",
    "    .sl-hero-brand{position:absolute;display:flex;align-items:center;gap:0.8rem;background:rgba(0,0,0,.5);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);padding:0.8rem 1.4rem;border-radius:999px;font-family:var(--sl-font-accent);font-size:1.1rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,.92);z-index:6;pointer-events:none}",
    "    .sl-hero-brand-dot{width:0.8rem;height:0.8rem;border-radius:50%;background:var(--sl-brand)}",
    "    .sl-hero-brand--top-left{top:1.6rem;left:1.6rem}",
    "    .sl-hero-brand--top-right{top:1.6rem;right:1.6rem}",
    "    .sl-hero-brand--bottom-left{bottom:1.6rem;left:1.6rem}",
    "    .sl-hero-brand--bottom-right{bottom:1.6rem;right:1.6rem}",
    # The ring is a solid disc (border colour, or a gradient) — never transparent padding, which would reveal
    # the page background and read as an uneven border where the avatar overhangs onto the page.
    "    .sl-avatar-wrap{position:absolute;bottom:-5.8rem;left:2.4rem;z-index:10;width:12.3rem;height:12.3rem;border-radius:50%;padding:0.4rem;background:var(--sl-avatar-ring,var(--sl-avatar-border,#ffffff));box-shadow:0 0.4rem 1.2rem rgba(0,0,0,.15)}",
    "    .sl-avatar{width:100%;height:100%;border-radius:50%;object-fit:cover;background:var(--sl-hero-bg);display:block}",
    "    .sl-trust-badges{display:flex;flex-wrap:wrap;gap:0.8rem;justify-content:center}",
    "    .sl-trust-badge{display:flex;align-items:center;gap:0.6rem;border:1px solid var(--sl-trust-badge-border);background:var(--sl-trust-badge-bg);color:var(--sl-trust-badge-text);border-radius:999px;padding:0.8rem 1.4rem;font-family:var(--sl-font-accent);font-size:1.2rem;font-weight:800}",
    "    .sl-price-options{display:grid;grid-template-columns:1fr;gap:1.4rem;width:100%;margin:0 auto}",
    "    .sl-bnpl-message{margin:1rem auto 0;width:min(42rem,100%);min-height:1.2rem}",
    # A light card so the widget (fixed dark text) is legible on dark pages; :not(:empty) so no bare box
    # shows before Stripe.js mounts (or if it never does). Matches the appearance colorBackground below.
    "    .sl-bnpl-message:not(:empty){background:#fff;border-radius:.75rem;padding:.7rem 1rem;box-shadow:0 1px 3px rgba(0,0,0,.08)}",
    "    .sl-price-option{position:relative;display:grid;grid-template-columns:9rem minmax(0,1fr) 2.2rem;gap:1.4rem;align-items:center;border:2px solid var(--sl-price-card-border);border-radius:var(--sl-radius);padding:1.6rem 2rem;background:var(--sl-price-card-bg)}",
    "    .sl-price-option.selected{border-color:var(--sl-price-card-selected-border);box-shadow:0 0 0 3px color-mix(in srgb,var(--sl-price-card-selected-border) 13%,transparent)}",
    "    .sl-price-option input{width:2.2rem;height:2.2rem;accent-color:var(--sl-price-radio)}",
    "    .sl-price-option img{width:9rem;height:auto;aspect-ratio:1/1;object-fit:contain;border-radius:0.8rem;background:var(--sl-background)}",
    "    .sl-price-copy{display:grid;gap:0.4rem}",
    "    .sl-price-option strong{font-family:var(--sl-font-heading);font-size:1.6rem;line-height:1.2;font-weight:600;color:var(--sl-price-title)}",
    "    .sl-price-description{color:var(--sl-price-description);font-size:1.3rem;line-height:1.45}",
    "    .sl-price-row{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;margin-top:1rem}",
    "    .sl-price-amount{font-family:var(--sl-font-accent);font-size:2rem;font-weight:700;color:var(--sl-price-amount)}",
    "    .sl-regular-price{color:var(--sl-price-regular);text-decoration:line-through;font-size:1.4rem}",
    "    .sl-featured-price{display:flex;justify-content:center}",
    "    .sl-featured-price-card{width:min(42rem,100%);text-align:center;border:2px solid var(--sl-price-card-border);border-radius:var(--sl-radius);background:var(--sl-price-card-bg);padding:2rem 2.4rem;display:grid;gap:1rem;justify-items:center}",
    "    .sl-featured-price-label{font-size:1.3rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--sl-muted)}",
    "    .sl-featured-price-amount{font-family:var(--sl-font-accent);font-size:clamp(3.6rem,12vw,5.4rem);line-height:1;font-weight:800;color:var(--sl-price-amount)}",
    "    .sl-featured-price-pills{display:flex;flex-wrap:wrap;gap:0.8rem;justify-content:center}",
    "    .sl-featured-price-pill{font-size:1.4rem;font-weight:700;padding:0.5rem 1.2rem;border-radius:999px;border:1px solid var(--sl-price-card-border)}",
    "    .sl-featured-price-was{color:var(--sl-price-regular);text-decoration:line-through}",
    "    .sl-featured-price-save{color:var(--sl-price-amount);border-color:color-mix(in srgb,var(--sl-price-amount) 40%,transparent)}",
    "    .sl-price-option[data-expired='true'] .sl-regular-price,.sl-price-option[data-expired='true'] .sl-savings{display:none}",
    "    .sl-badge{display:inline-flex;width:max-content;font-family:var(--sl-font-accent);font-size:1.1rem;font-weight:700;color:var(--sl-featured-badge-text);background:var(--sl-featured-badge-bg);padding:0.4rem 1rem;border-radius:999px}",
    "    .sl-badge:empty{display:none}",
    "    .sl-savings{font-family:var(--sl-font-accent);font-size:1.1rem;font-weight:600;color:var(--sl-savings-text);background:var(--sl-savings-bg);border:1px solid var(--sl-savings-border);border-radius:1.2rem;padding:0.4rem 1rem}",
    "    .sl-content-blocks{display:grid;gap:1rem}",
    "    .sl-faq{display:grid;gap:1.2rem}",
    "    .sl-refund-policy{width:100%;border:1px solid var(--sl-refund-border);background:var(--sl-refund-bg);border-radius:var(--sl-radius);overflow:hidden}",
    "    .sl-refund-policy summary{list-style:none;cursor:pointer;padding:1.6rem 2rem;font-family:var(--sl-font-heading);font-size:1.4rem;font-weight:600;color:var(--sl-refund-summary);display:flex;align-items:center;justify-content:space-between;gap:1.2rem}",
    "    .sl-refund-policy summary::-webkit-details-marker{display:none}",
    "    .sl-refund-policy summary::after{content:'+';font-size:1.8rem;color:var(--sl-refund-applies);transition:transform .2s}",
    "    .sl-refund-policy[open] summary::after{transform:rotate(45deg)}",
    "    .sl-refund-policy-body{padding:0 2rem 2rem;display:grid;gap:1.4rem}",
    "    .sl-refund-policy h2{font-family:var(--sl-font-heading);font-size:1.5rem;line-height:1.3;margin-top:0.6rem;color:var(--sl-refund-title)}",
    "    .sl-refund-policy p{color:var(--sl-refund-text);line-height:1.6;font-size:1.4rem}",
    "    .sl-refund-policy-applies{font-size:1.3rem;line-height:1.55;font-weight:700;color:var(--sl-refund-applies)}",
    "    .sl-refund-policy-copy{padding-left:2rem}",
    "    .sl-refund-policy-return{padding-left:2rem;color:var(--sl-refund-return)!important;font-weight:800}",
    "    .sl-content-block{display:grid;grid-template-columns:minmax(0,1fr) minmax(12rem,18rem);gap:1.2rem;align-items:center;border-top:1px solid var(--sl-content-border);padding-top:1.6rem}",
    "    .sl-content-block h2{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:0.8rem;color:var(--sl-content-heading)}",
    "    .sl-content-block p{color:var(--sl-content-text);font-size:1.5rem;line-height:1.6}",
    "    .sl-content-media{border-radius:0.8rem;overflow:hidden}",
    "    .sl-content-media:not(.sl-cropped) img{width:100%;height:auto;aspect-ratio:4/3;object-fit:cover}",
    # Centered variant (SALES_FUNNELS.md P3.5): a single centered column — used for the upsell product blurb and
    # any content block a tenant opts to center.
    "    .sl-content-blocks--centered .sl-content-block{grid-template-columns:minmax(0,1fr);text-align:center;justify-items:center}",
    "    .sl-content-blocks--centered .sl-content-block p{max-width:46rem;margin:0 auto}",
    # Thank-you page extras (SALES_FUNNELS.md P3.5 Phase 2): celebration burst, "What's Next?" cards, footer.
    "    .sl-celebration{display:flex;justify-content:center;margin:0 auto 0.4rem}",
    "    .sl-celebration-mark svg{width:6.4rem;height:6.4rem}",
    "    .sl-celebration-ring{fill:none;stroke:var(--sl-brand);stroke-width:2;opacity:0.35}",
    "    .sl-celebration-check{fill:none;stroke:var(--sl-brand);stroke-width:4;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:48;stroke-dashoffset:48;animation:sl-ty-check 0.6s ease-out 0.15s forwards}",
    "    @keyframes sl-ty-check{to{stroke-dashoffset:0}}",
    "    .sl-next-steps{text-align:center;display:grid;gap:1.6rem;margin-top:1.6rem}",
    "    .sl-next-steps-title{font-family:var(--sl-font-heading);font-size:2rem;color:var(--sl-headline)}",
    "    .sl-next-steps-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1.2rem}",
    "    .sl-next-step{background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:var(--sl-radius);padding:1.6rem;display:grid;gap:0.5rem;text-align:center}",
    "    .sl-next-step-icon{font-size:2.4rem}",
    "    .sl-next-step strong{font-family:var(--sl-font-heading);font-size:1.5rem;color:var(--sl-headline)}",
    "    .sl-next-step p{color:var(--sl-content-text);font-size:1.35rem;line-height:1.5}",
    "    .sl-ty-footer{text-align:center;display:grid;gap:1rem;margin-top:2.4rem;padding-top:2rem;border-top:1px solid var(--sl-content-border)}",
    "    .sl-ty-footer h2{font-family:var(--sl-font-heading);font-size:1.8rem;color:var(--sl-headline)}",
    "    .sl-ty-footer p{color:var(--sl-content-text);font-size:1.45rem;line-height:1.6}",
    "    .sl-ty-download{justify-self:center}",
    "    .sl-ty-home{color:var(--sl-brand);text-decoration:none;font-weight:600;font-size:1.4rem}",
    "    .sl-ty-home:hover{text-decoration:underline}",
    "    .sl-faq details{border:1px solid var(--sl-faq-border);background:var(--sl-faq-bg);border-radius:1.6rem;padding:0;overflow:hidden}",
    "    .sl-faq summary{cursor:pointer;font-family:var(--sl-font-heading);font-size:1.4rem;font-weight:600;line-height:1.35;color:var(--sl-faq-summary);display:flex;align-items:center;justify-content:space-between;gap:1.2rem;padding:1.6rem 2rem}",
    "    .sl-faq summary h3{margin:0;font:inherit;color:inherit;flex:1}",
    # The summary is display:flex, which suppresses the native disclosure triangle — so without this
    # the questions read as plain text and nobody knows they open. Drawn from two borders rather than a
    # glyph so it inherits currentColor and stays sharp at any theme/preset colour.
    "    .sl-faq summary{list-style:none}",
    "    .sl-faq summary::-webkit-details-marker{display:none}",
    "    .sl-faq summary::after{content:'';flex:none;width:0.7rem;height:0.7rem;margin-left:0.4rem;border-right:2px solid var(--sl-accent);border-bottom:2px solid var(--sl-accent);transform:translateY(-0.2rem) rotate(45deg);transition:transform .2s ease}",
    "    .sl-faq details[open] summary::after{transform:translateY(0.1rem) rotate(-135deg)}",
    "    .sl-faq-heading{font-family:var(--sl-font-heading);font-size:1.8rem;line-height:1.25;margin-bottom:0.2rem;color:var(--sl-faq-summary)}",
    "    .sl-faq p{color:var(--sl-faq-text);font-size:1.4rem;line-height:1.6;padding:0 2rem 1.6rem}",
    "    .sl-checkout-cta{position:fixed;left:0;right:0;bottom:0;z-index:10;background:linear-gradient(transparent,var(--sl-cta-scrim) 20%);padding:1.6rem;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.8rem}",
    "    .sl-cta{display:inline-flex;width:min(52rem,100%);align-items:center;justify-content:center;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:1rem;padding:1.5rem 1.8rem;font-family:var(--sl-font-accent);font-size:1.7rem;font-weight:900;text-decoration:none}",
    "    .sl-cta.is-connecting{opacity:.72;cursor:wait;pointer-events:none}",
    "    .sl-decline-cta{width:auto;background:none;color:var(--sl-muted);text-decoration:underline;font-weight:600;font-size:1.3rem;padding:0.4rem}",
    "    .sl-downsell-note{text-align:center;color:var(--sl-muted);font-size:1.4rem;font-weight:600;margin-bottom:0.4rem}",
    "    .sl-call-number{width:auto;color:var(--sl-cta-text);font-family:var(--sl-font-accent);font-weight:900;font-size:2.2rem;letter-spacing:0.02em;text-decoration:none}",
    "    .sl-lead-form{display:flex;flex-direction:column;gap:1rem;width:min(52rem,100%);background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.6rem}",
    "    .sl-lead-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-lead-description{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-lead-input{width:100%;padding:1.2rem 1.4rem;border:1px solid var(--sl-price-card-border);border-radius:0.8rem;background:var(--sl-background);color:var(--sl-text);font-size:1.5rem}",
    "    .sl-lead-consent{display:flex;align-items:flex-start;gap:0.8rem;font-size:1.3rem;color:var(--sl-price-description);text-align:left}",
    "    .sl-lead-consent input{margin-top:0.3rem}",
    "    .sl-lead-status{font-size:1.4rem;color:var(--sl-price-description);text-align:center;min-height:1.4rem}",
    "    .sl-lead-status.is-error{color:#dc2626}",
    "    .sl-hp{position:absolute;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none}",
    "    .sl-booking-panel{display:flex;flex-direction:column;gap:1rem;width:min(52rem,100%);background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.6rem;margin-top:1.2rem;text-align:left}",
    "    .sl-booking-heading{font-family:var(--sl-font-heading);font-weight:800;font-size:1.6rem;color:var(--sl-price-title)}",
    "    .sl-booking-slots.is-empty{color:var(--sl-price-description);font-size:1.4rem}",
    "    .sl-booking-day{margin-bottom:1rem}",
    "    .sl-booking-day h4{font-size:1.4rem;font-weight:700;color:var(--sl-price-title);margin-bottom:0.6rem}",
    "    .sl-booking-times{display:flex;flex-wrap:wrap;gap:0.6rem}",
    "    .sl-booking-slot{border:1px solid var(--sl-price-card-border);background:var(--sl-background);color:var(--sl-text);border-radius:0.8rem;padding:0.6rem 1rem;font-size:1.4rem;cursor:pointer}",
    "    .sl-booking-slot.selected{background:var(--sl-brand);color:#fff;border-color:var(--sl-brand)}",
    "    .sl-booking-consent{font-size:1.2rem;color:var(--sl-price-description)}",
    "    .sl-booking-banner{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-booking-banner.is-error{color:#dc2626}",
    "    .sl-section-heading{font-family:var(--sl-font-heading);font-weight:800;font-size:2.4rem;text-align:center;color:var(--sl-content-heading);margin-bottom:1.6rem}",
    "    .sl-testimonials{display:grid;gap:1.4rem}",
    # Quote-led card: an oversized accent quote mark, the quote as the largest thing in it, and the
    # avatar to one side. Every colour is a theme token, so it re-skins with the preset instead of
    # carrying a palette of its own.
    "    .sl-testimonial{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:1.8rem;background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:1.6rem;padding:2rem 2rem 2rem 4.6rem;margin:0}",
    "    .sl-testimonial::before{content:'\\201C';position:absolute;left:1.4rem;top:0.4rem;font-family:var(--sl-font-heading);font-size:5.2rem;line-height:1;color:var(--sl-accent);opacity:0.32;pointer-events:none}",
    "    .sl-testimonial-body{display:grid;gap:1.2rem;min-width:0}",
    "    .sl-testimonial img{width:7.2rem;height:7.2rem;border-radius:50%;object-fit:cover;box-shadow:0 0 0 0.3rem var(--sl-card),0 0 0 0.5rem var(--sl-accent)}",
    "    .sl-testimonial blockquote{margin:0;font-size:1.8rem;line-height:1.55;color:var(--sl-content-text)}",
    "    .sl-testimonial figcaption{display:flex;align-items:center;flex-wrap:wrap;gap:0.9rem;font-size:1.4rem;color:var(--sl-muted)}",
    "    .sl-testimonial figcaption strong{color:var(--sl-text);font-weight:700}",
    "    .sl-testimonial-sep{width:1px;height:1.4rem;background:var(--sl-content-border)}",
    "    .sl-rating{display:flex;flex-direction:column;align-items:center;gap:0.4rem}",
    "    .sl-rating-stars{color:#f59e0b;font-size:2.4rem;letter-spacing:0.2rem}",
    "    .sl-rating-meta{font-size:1.4rem;color:var(--sl-content-text)}",
    "    .sl-client-marquee{overflow:hidden}",
    "    .sl-marquee-track{display:flex;width:max-content;animation:sl-marquee var(--sl-brand-marquee-duration,30s) linear infinite}",
    # Price highlight (plans/PRICE_HIGHLIGHT.md). Every colour falls through to the PRICE element's tokens,
    # so a preset styles this on day one and it cannot drift from the price card beside it. --sl-section-*
    # is the optional per-section override; absent, these resolve to the page theme.
    # Author bio (plans/AUTHOR_BIO.md). Colours fall through to the page theme unless the section
    # overrides them; --sl-section-ink is derived from the chosen background so the copy stays readable.
    "    .sl-author-bio{display:grid;gap:1.2rem;justify-items:center;text-align:center;padding:4rem 2rem;background:var(--sl-section-bg,transparent);color:var(--sl-section-ink,var(--sl-text))}",
    # The ring reads as a portrait frame; it falls back to the theme accent when the tenant sets no border.
    "    .sl-author-photo{width:14rem;height:14rem;border-radius:50%;overflow:hidden;box-shadow:0 0 0 0.5rem var(--sl-section-border,var(--sl-accent))}",
    "    .sl-author-photo:not(.sl-cropped) img{width:100%;height:100%;object-fit:cover;display:block}",
    # A pill, so the name reads as an attribution rather than a second heading.
    "    .sl-author-name{margin:0;display:inline-block;padding:0.4rem 1.4rem;border-radius:999px;background:var(--sl-section-border,var(--sl-accent));color:var(--sl-section-border-ink,var(--sl-cta-text,#fff));font-size:1.3rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em}",
    "    .sl-author-headline{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.6rem);line-height:1.2;color:var(--sl-section-ink,var(--sl-text))}",
    "    .sl-author-body{margin:0;max-width:62rem;font-size:1.6rem;line-height:1.7;color:var(--sl-section-ink,var(--sl-muted))}",
    # BRAGGING POINTS. Same section-override contract as the author bio above.
    # minmax(0,1fr) on the outer track, NOT the default `auto`: with justify-items:center an auto track
    # sizes to its child's MAX-CONTENT, which for the card grid below is every column at full width. The
    # section then grew past the viewport and shoved the whole page right on a phone. `width:100%` on the
    # child cannot fix that — it resolves against the very track it is inflating.
    "    .sl-bragging-points{display:grid;grid-template-columns:minmax(0,1fr);gap:1.6rem;justify-items:center;text-align:center;padding:4rem 2rem;background:var(--sl-section-bg,transparent);color:var(--sl-section-ink,var(--sl-text))}",
    "    .sl-brag-heading{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2rem,4vw,2.8rem);line-height:1.25;color:var(--sl-section-ink,var(--sl-text))}",
    # Capped at TWO columns on purpose: three cards then read 2 + 1 rather than a thin triple, which is the
    # reflow the element was specified with. auto-fit collapses to one column on narrow screens by itself.
    # min(22rem,100%) is the load-bearing half: a bare minmax(22rem,1fr) makes every track demand 22rem
    # even when the container is narrower, so auto-fit overflows instead of collapsing to one column.
    "    .sl-brag-grid{list-style:none;margin:0;padding:0;width:100%;max-width:62rem;display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fit,minmax(min(22rem,100%),1fr))}",
    # A lone trailing card spans the row, so 1 card is one wide and 3 cards are 2 + 1 — no count in the markup.
    "    .sl-brag-grid > .sl-brag-card:last-child:nth-child(odd){grid-column:1/-1}",
    "    .sl-brag-card{display:grid;gap:0.4rem;align-content:center;padding:2rem 1.6rem;border-radius:1rem;background:var(--sl-section-accent,rgba(127,127,127,0.12));color:var(--sl-section-accent-ink,var(--sl-section-ink,var(--sl-text)))}",
    "    .sl-brag-value{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.4rem);line-height:1.1;font-weight:800}",
    # Muted by OPACITY, not a second colour: it stays readable against whatever ink was derived.
    "    .sl-brag-label{margin:0;font-size:1.4rem;line-height:1.5;opacity:0.75}",
    # QUOTE. minmax(0,1fr) for the same reason as bragging points: justify-items:center leaves an auto
    # track, and an auto track sizes to max-content — long unbroken text would then widen the viewport.
    "    .sl-quote{display:grid;grid-template-columns:minmax(0,1fr);padding:4rem 2rem;background:var(--sl-section-bg,transparent);color:var(--sl-section-ink,var(--sl-text))}",
    "    .sl-quote-title{margin:0 auto 1.6rem;width:100%;max-width:62rem;font-family:var(--sl-font-heading);font-size:clamp(1.8rem,3.4vw,2.4rem);line-height:1.3}",
    "    .sl-quote-text{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2rem,4vw,2.8rem);line-height:1.45;font-style:italic}",
    # Muted by opacity, so it stays legible against whatever ink the surface derived.
    "    .sl-quote-attribution{margin:1.2rem 0 0;font-size:1.5rem;font-style:normal;opacity:0.75}",
    # MINIMAL — the BAR is the signature, and what keeps it from reading as a testimonial card.
    "    .sl-quote-minimal .sl-quote-figure{margin:0 auto;width:100%;max-width:62rem;text-align:left;border-left:0.5rem solid var(--sl-section-accent,var(--sl-accent));padding-left:2.4rem}",
    "    .sl-quote-minimal .sl-quote-photo{margin:0 0 1.6rem}",
    "    .sl-quote-minimal .sl-quote-photo img{width:8rem;height:8rem;border-radius:50%;object-fit:cover;display:block}",
    # FANCY — a coloured card. `accent` paints the CARD here rather than a bar, so the text on it is the
    # derived accent-ink: the reference design's white-on-pink comes out of the contrast maths, not a
    # hardcoded colour, and holds for a pale card just as well.
    "    .sl-quote-fancy .sl-quote-figure{margin:0 auto;width:100%;max-width:74rem;display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:2.4rem;padding:3.2rem;border-radius:1rem;background:var(--sl-section-accent,var(--sl-accent));color:var(--sl-section-accent-ink,var(--sl-cta-text,#fff))}",
    # The photo is sized by HEIGHT with a fixed box, exactly as the reference does. Sizing it by width
    # alone let a PORTRAIT source render ~500px tall, which forced the card to wrap even on a desktop and
    # buried the words under a column of photograph.
    # The photo OVERLAPS the card, as in the reference. The reference gets that from transform:scale(),
    # which grows the image visually without growing its layout box — so it always spills past the card.
    # A plain taller image cannot: the card's height is set by the WORDS, so the image never reaches the
    # edges of a card with a few lines in it. Here the box stretches to the card's content height and the
    # image is drawn taller than its box, which makes the bleed a CONSTANT 2.4rem whatever the text does:
    #   card   = content + 6.4rem (its padding)
    #   image  = content + 11.2rem
    #   bleed  = (image - card) / 2 = 2.4rem, top and bottom
    # min-height keeps the photo a sensible size when the quote is one short line.
    "    .sl-quote-fancy .sl-quote-photo{flex:0 0 auto;width:16rem;align-self:stretch;min-height:14rem;position:relative}",
    "    .sl-quote-fancy .sl-quote-photo img{position:absolute;top:50%;left:0;transform:translateY(-50%);display:block;width:100%;height:calc(100% + 11.2rem);object-fit:cover;border-radius:0.8rem;box-shadow:0 1.2rem 2.4rem rgba(0,0,0,0.4)}",
    "    .sl-quote-fancy .sl-quote-body{flex:1 1 18rem;min-width:0;position:relative;padding-top:2.8rem}",
    "    .sl-quote-fancy .sl-quote-text{font-size:clamp(1.8rem,3.2vw,2.2rem);font-style:normal;font-weight:600;line-height:1.35}",
    # The reference's fat opening mark: a heavy sans at 7.5rem, weight 600, 30% opacity. currentColor
    # rather than the reference's fixed blue, so it adapts to whatever ink the card derived.
    "    .sl-quote-fancy .sl-quote-body::before{content:'\\201C';position:absolute;top:0;left:-0.8rem;font-family:" + QUOTE_MARK_FONT + ";font-size:7.5rem;line-height:0.75;font-weight:600;opacity:0.3;pointer-events:none}",
    "    .sl-quote-fancy .sl-quote-attribution{margin-top:2rem}",
    # NUMBERED LIST. Follows the page preset — no section override, this element has no pattern-break job.
    "    .sl-numbered-list{display:grid;grid-template-columns:minmax(0,1fr);gap:1.6rem;padding:4rem 2rem}",
    "    .sl-numbered-heading{margin:0 auto;width:100%;max-width:62rem;font-family:var(--sl-font-heading);font-size:clamp(2rem,4vw,2.8rem);line-height:1.25;color:var(--sl-content-heading,var(--sl-text))}",
    # The badge number is a CSS counter, so it never becomes selectable or duplicated text — the <ol>
    # already carries the ordering for anything that reads the page rather than looks at it.
    "    .sl-numbered-items{list-style:none;counter-reset:sl-num;margin:0 auto;padding:0;width:100%;max-width:62rem;display:grid;gap:1.2rem}",
    "    .sl-numbered-item{counter-increment:sl-num;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:1.6rem;padding:1.6rem 2rem;border:1px solid var(--sl-content-border);border-radius:1rem;background:var(--sl-card)}",
    "    .sl-numbered-item::before{content:counter(sl-num);display:grid;place-items:center;width:3.6rem;height:3.6rem;border-radius:50%;background:var(--sl-accent);color:var(--sl-cta-text,#fff);font-family:var(--sl-font-heading);font-size:1.8rem;font-weight:700;line-height:1}",
    "    .sl-numbered-text{margin:0;font-size:1.6rem;line-height:1.55;color:var(--sl-content-text)}",
    # PAGE RIBBON — an Attention Block. Uses the shared section override, so a tenant can make it break
    # the page deliberately; that is the entire point of an interruption.
    "    .sl-page-ribbon{display:grid;gap:2rem;align-items:center;margin:0 auto;padding:3.2rem;border-radius:1.4rem;background:var(--sl-section-bg,var(--sl-card));color:var(--sl-section-ink,var(--sl-text));max-width:74rem}",
    "    .sl-page-ribbon.is-image_left{grid-template-columns:minmax(0,22rem) minmax(0,1fr)}",
    "    .sl-page-ribbon.is-centered{grid-template-columns:minmax(0,1fr);text-align:center;justify-items:center}",
    "    .sl-page-ribbon.is-compact{grid-template-columns:minmax(0,12rem) minmax(0,1fr);gap:1.6rem;padding:1.6rem 2rem}",
    "    .sl-ribbon-media{border-radius:1rem;overflow:hidden}",
    "    .sl-ribbon-media:not(.sl-cropped) img{width:100%;height:auto;display:block}",
    # A cropped image is scaled up inside a clipped box and offset, so the chosen region exactly fills it.
    "    .sl-cropped{position:relative;overflow:hidden;aspect-ratio:var(--sl-crop-ar,1)}",
    "    .sl-embed{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;border-radius:1rem;background:#000}",
    "    .sl-embed .sl-embed-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;border:0}",
    "    .sl-embed .sl-embed-poster.is-blank{background:linear-gradient(135deg,#1f2937,#0f172a)}",
    "    .sl-embed iframe{position:absolute;inset:0;width:100%;height:100%;border:0}",
    "    .sl-embed-play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);border:0;background:none;padding:0;cursor:pointer;line-height:0}",
    "    .sl-embed-play .sl-embed-play-bg{fill:#212121;fill-opacity:0.8;transition:fill-opacity 0.15s}",
    "    .sl-embed-play:hover .sl-embed-play-bg,.sl-embed-play:focus-visible .sl-embed-play-bg{fill:#f00;fill-opacity:1}",
    "    .sl-embed-play:focus-visible{outline:2px solid #fff;outline-offset:4px;border-radius:0.6rem}",
    "    .sl-before-after{max-width:74rem;margin:0 auto}",
    "    .sl-ba-heading{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:1.2rem;color:var(--sl-content-heading);text-align:center}",
    "    .sl-ba-frame{position:relative;aspect-ratio:var(--sl-ba-ar,4/3);overflow:hidden;border-radius:1rem;background:var(--sl-card);touch-action:none;user-select:none}",
    "    .sl-ba-frame:focus-within{outline:2px solid var(--sl-accent);outline-offset:3px}",
    # Both layers are the SAME box; the top one is clipped rather than resized, so the two halves cannot
    # drift out of register at the seam whatever the images are.
    "    .sl-before-after .sl-ba-img{position:absolute;inset:0;overflow:hidden}",
    "    .sl-before-after .sl-ba-img:not(.sl-cropped) img{width:100%;height:100%;object-fit:cover;display:block}",
    "    .sl-ba-img.is-before{clip-path:inset(0 calc(100% - var(--sl-ba-pos,50%)) 0 0)}",
    "    .sl-ba-handle{position:absolute;top:0;bottom:0;left:var(--sl-ba-pos,50%);width:0.2rem;margin-left:-0.1rem;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,0.25);pointer-events:none}",
    "    .sl-ba-handle::after{content:\"\";position:absolute;top:50%;left:50%;width:3.2rem;height:3.2rem;transform:translate(-50%,-50%);border-radius:50%;background:#fff;box-shadow:0 0.2rem 0.8rem rgba(0,0,0,0.35)}",
    # The range fills the frame so a drag or a click anywhere moves the divider, and it stays a real
    # control underneath: keyboard, touch and assistive technology all work without a line of script.
    "    .sl-ba-range{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:ew-resize;-webkit-appearance:none;appearance:none;background:transparent}",
    "    .sl-ba-range::-webkit-slider-thumb{-webkit-appearance:none;width:3.2rem;height:100%}",
    "    .sl-ba-range::-moz-range-thumb{width:3.2rem;height:100%;border:0;opacity:0}",
    "    .sl-ba-tag{position:absolute;bottom:1.2rem;padding:0.4rem 1rem;border-radius:999px;font-size:1.2rem;font-weight:600;background:rgba(0,0,0,0.6);color:#fff;pointer-events:none}",
    "    .sl-ba-tag.is-before{left:1.2rem}",
    "    .sl-ba-tag.is-after{right:1.2rem}",
    "    .sl-cropped>img{position:absolute;top:var(--sl-crop-y,0);left:var(--sl-crop-x,0);width:var(--sl-crop-w,100%);height:var(--sl-crop-h,100%);max-width:none;border-radius:inherit}",
    "    .sl-ribbon-copy{display:grid;gap:0.8rem;min-width:0}",
    "    .sl-page-ribbon.is-centered .sl-ribbon-copy{justify-items:center}",
    "    .sl-ribbon-eyebrow{margin:0;font-size:1.3rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.75}",
    "    .sl-ribbon-headline{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2rem,4vw,2.8rem);line-height:1.2}",
    "    .sl-ribbon-body{margin:0;font-size:1.6rem;line-height:1.55;opacity:0.85}",
    # The CTA takes the section accent when the ribbon breaks the pattern, so its ink is the DERIVED
    # accent-ink and a tenant cannot colour the button into invisibility.
    "    .sl-ribbon-cta{justify-self:start;display:inline-flex;align-items:center;margin-top:0.8rem;padding:1.1rem 2.2rem;border-radius:999px;background:var(--sl-section-accent,var(--sl-accent));color:var(--sl-section-accent-ink,var(--sl-cta-text,#fff));font-size:1.5rem;font-weight:700;text-decoration:none}",
    "    .sl-page-ribbon.is-centered .sl-ribbon-cta{justify-self:center}",
    "    .sl-page-ribbon.is-compact .sl-ribbon-headline{font-size:clamp(1.7rem,3vw,2.1rem)}",
    # The download dialog. Built by script, so its styles ship with the page whether or not it is used --
    # a few hundred bytes against a round trip to fetch them at the moment a visitor is deciding.
    "    .sl-dl-backdrop{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:2rem;background:rgba(0,0,0,.55)}",
    "    .sl-dl-card{width:100%;max-width:38rem;display:grid;gap:1.2rem;padding:2.4rem;border-radius:1.2rem;background:var(--sl-card,#fff);color:var(--sl-text)}",
    "    .sl-dl-title{margin:0;font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25}",
    "    .sl-dl-field{display:grid;gap:0.4rem;font-size:1.4rem}",
    "    .sl-dl-field input{padding:1rem 1.2rem;border:1px solid var(--sl-content-border);border-radius:0.8rem;font-size:1.6rem;font-family:inherit}",
    "    .sl-dl-error{margin:0;color:#b91c1c;font-size:1.4rem}",
    "    .sl-dl-actions{display:flex;gap:1rem;justify-content:flex-end}",
    "    .sl-dl-actions button{padding:1rem 1.8rem;border-radius:999px;font-size:1.5rem;font-weight:700;cursor:pointer;font-family:inherit}",
    "    .sl-dl-cancel{background:none;border:1px solid var(--sl-content-border);color:inherit}",
    "    .sl-dl-submit{border:0;background:var(--sl-accent);color:var(--sl-cta-text,#fff)}",
    "    .sl-dl-card{position:relative}",
    "    .sl-dl-dismiss{position:absolute;top:0.8rem;right:1rem;border:0;background:none;color:inherit;font-size:2.2rem;line-height:1;cursor:pointer;opacity:0.55}",
    "    .sl-ribbon-cta:disabled,.sl-dl-submit:disabled{opacity:0.6;cursor:default}",
    "    .sl-price-highlight{display:grid;gap:0.6rem;justify-items:center;text-align:center;padding:3.2rem 2rem;background:var(--sl-section-bg,transparent);color:var(--sl-section-ink,var(--sl-text))}",
    "    .sl-bargain-regular{margin:0;font-size:1.5rem;color:var(--sl-section-ink,var(--sl-price-regular));opacity:0.75}",
    "    .sl-bargain-amount{margin:0;font-family:var(--sl-font-heading);font-size:clamp(4rem,10vw,6.4rem);line-height:1;font-weight:800;color:var(--sl-section-ink,var(--sl-price-amount))}",
    # The prefix is small and quiet: it qualifies the number without competing with it.
    "    .sl-bargain-prefix{display:block;font-size:1.6rem;font-weight:600;letter-spacing:0.02em;opacity:0.8}",
    "    .sl-bargain-main{margin:0;font-family:var(--sl-font-heading);font-size:2.2rem;font-weight:700;color:var(--sl-section-ink,var(--sl-price-title))}",
    "    .sl-bargain-sub{margin:0;font-size:1.5rem;color:var(--sl-section-ink,var(--sl-price-description));opacity:0.85}",
    "    .sl-marquee-row{display:flex;align-items:center;gap:1.6rem;padding-right:1.6rem}",
    # Few logos -> centered + static; many (>=5) -> the rolling track above.
    "    .sl-marquee-static{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:1.6rem}",
    # Logos sit on a light chip so they stay visible on any theme (dark logos on a dark page vanish otherwise).
    "    .sl-marquee-logo{display:inline-flex;align-items:center;justify-content:center;background:#ffffff;border-radius:0.8rem;padding:0.8rem 1.2rem;box-shadow:0 1px 3px rgba(0,0,0,.08)}",
    "    .sl-marquee-logo img{height:3.2rem;width:auto;object-fit:contain}",
    # `none` backing drops the white card for tenants whose logos already suit their preset. The card
    # stays the default because a dark logo on a dark preset is invisible without it.
    "    .sl-marquee-logo.is-bare{background:none;box-shadow:none;padding:0}",
    # A text entry is a WORDMARK in the page's own type, not text sitting in a logo-shaped white card.
    "    .sl-marquee-word{display:inline-flex;align-items:center;height:3.2rem;font-family:var(--sl-font-heading);font-size:1.8rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;white-space:nowrap;color:var(--sl-muted)}",
    "    @keyframes sl-marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}",
    "    @media (prefers-reduced-motion: reduce){.sl-marquee-track{animation:none;flex-wrap:wrap}.sl-faq summary::after{transition:none}}",
    "    .sl-carousel-track{display:flex;gap:1.6rem;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:1.2rem;-webkit-overflow-scrolling:touch}",
    "    .sl-carousel-slide{scroll-snap-align:start;flex:0 0 min(80%,28rem);display:flex;flex-direction:column;gap:0.8rem;background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.4rem}",
    "    .sl-carousel-slide img{width:100%;height:16rem;object-fit:cover;border-radius:0.8rem}",
    "    .sl-carousel-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-carousel-desc{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-carousel-price{font-family:var(--sl-font-accent);font-weight:900;font-size:2rem;color:var(--sl-price-amount);margin-top:auto}",
    "    .sl-carousel-buy{width:auto;text-align:center}",
    "    .sl-pp-carousel{width:min(64rem,100%);margin:0 auto;display:flex;flex-direction:column;gap:1.2rem;text-align:center}",
    "    .sl-pp-carousel-heading{font-family:var(--sl-font-heading);font-weight:800;font-size:2.4rem;color:var(--sl-heading)}",
    "    .sl-pp-carousel-sub{font-size:1.5rem;color:var(--sl-muted)}",
    "    .sl-pp-carousel-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(20rem,1fr));gap:1.2rem}",
    "    .sl-pp-card{display:flex;flex-direction:column;gap:0.6rem;background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.4rem;text-align:left}",
    "    .sl-pp-card img{width:100%;height:13rem;object-fit:cover;border-radius:0.8rem}",
    "    .sl-pp-card-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.7rem;color:var(--sl-price-title)}",
    "    .sl-pp-card-desc{font-size:1.35rem;color:var(--sl-price-description)}",
    "    .sl-pp-card-price{font-family:var(--sl-font-accent);font-weight:900;font-size:1.9rem;color:var(--sl-price-amount)}",
    "    .sl-pp-add{margin-top:auto;width:100%;text-align:center}",
    "    .sl-pp-add.is-added{background:#16a34a;border-color:#16a34a;cursor:default}",
    "    .sl-pp-card.is-added{opacity:0.72}",
    "    .sl-pp-dismiss{background:none;border:none;color:var(--sl-muted);cursor:pointer;font-size:1.45rem;text-decoration:underline;padding:0.8rem}",
    "    .sl-brand-hero{text-align:center;padding:2.4rem 0 0.8rem}",
    "    .sl-brand-logo{display:block;height:7.2rem;width:auto;max-width:22rem;margin:0 auto 1.2rem;object-fit:contain}",
    "    .sl-brand-logo-faux{display:flex;align-items:center;justify-content:center;height:7.2rem;width:7.2rem;border-radius:1.6rem;background:var(--sl-cta-bg,var(--sl-headline));color:var(--sl-cta-text,#fff)}",
    "    .sl-brand-logo-faux svg{height:4rem;width:4rem}",
    "    .sl-brand-hero h1{font-family:var(--sl-font-heading);font-size:clamp(2.6rem,6vw,3.6rem);line-height:1.15;font-weight:800;color:var(--sl-headline);margin:0}",
    "    .sl-brand-hero-tagline{font-size:1.6rem;line-height:1.5;color:var(--sl-subheadline-text);max-width:46rem;margin:0.8rem auto 0}",
    "    .sl-catalog-grid{display:flex;flex-direction:column;gap:1.6rem}",
    "    .sl-catalog-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:1.4rem}",
    "    .sl-catalog-card{display:flex;flex-direction:column;gap:0.6rem;background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.2rem;text-decoration:none;transition:transform .15s ease,box-shadow .15s ease}",
    "    a.sl-catalog-card:hover{transform:translateY(-2px);box-shadow:0 10px 28px rgba(0,0,0,.12)}",
    # height:auto is load-bearing: responsive_img emits an intrinsic height attr, and a fixed height defeats aspect-ratio.
    "    .sl-catalog-card img{width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;border-radius:0.8rem;background:#fff;display:block}",
    "    .sl-catalog-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.6rem;line-height:1.3;color:var(--sl-price-title);margin:0}",
    "    .sl-catalog-price{font-family:var(--sl-font-accent);font-weight:900;font-size:1.8rem;color:var(--sl-price-amount);margin:auto 0 0}",
    "    .sl-seller-profile{display:flex;flex-direction:column;gap:1rem}",
    "    .sl-seller-desc{font-size:1.5rem;line-height:1.6;color:var(--sl-content-text)}",
    "    .sl-seller-contact{font-size:1.4rem;color:var(--sl-muted);display:flex;flex-wrap:wrap;gap:0.6rem}",
    "    .sl-seller-contact a{color:var(--sl-legal-link);text-decoration:none}",
    "    .sl-seller-social,.sl-seller-catalog{list-style:none;display:flex;flex-wrap:wrap;gap:1rem;padding:0;margin:0}",
    "    .sl-seller-social a,.sl-seller-catalog a{color:var(--sl-legal-link);text-decoration:none;font-size:1.4rem}",
    "    .sl-seller-social a:hover,.sl-seller-catalog a:hover{text-decoration:underline}",
    "    .sl-seller-hours{list-style:none;padding:0;margin:0;font-size:1.4rem;color:var(--sl-content-text)}",
    "    .sl-seller-hours li{display:flex;gap:1.2rem;justify-content:space-between;max-width:32rem;padding:0.2rem 0}",
    "    .sl-seller-hours li span:last-child{color:var(--sl-muted)}",
    "    .sl-seller-gbp a{color:var(--sl-legal-link);text-decoration:none;font-weight:600}",
    "    .sl-seller-gbp a:hover{text-decoration:underline}",
    "    .sl-reviews{max-width:var(--sl-content-width,72rem);margin:2.4rem auto;padding:0 1.6rem}",
    "    .sl-reviews-summary{font-size:1.6rem;color:var(--sl-content-text);margin:0 0 1.2rem}",
    "    .sl-reviews-avg{font-weight:800}",
    "    .sl-reviews-list{list-style:none;padding:0;margin:0;display:grid;gap:1.4rem}",
    "    .sl-review{border:1px solid var(--sl-line,#e5e7eb);border-radius:0.8rem;padding:1.2rem 1.4rem}",
    "    .sl-review-stars{color:#f59e0b;letter-spacing:0.1em;margin-right:0.8rem}",
    "    .sl-review-author{font-weight:700;color:var(--sl-content-text)}",
    "    .sl-review-date{color:var(--sl-muted);font-size:1.3rem;margin-left:0.8rem}",
    "    .sl-review-body{margin:0.6rem 0 0;color:var(--sl-content-text);line-height:1.6}",
    "    .sl-review-title{color:var(--sl-content-text)}",
    "    .sl-listicle{width:min(52rem,100%);margin:0 auto;display:flex;flex-direction:column;gap:1.2rem}",
    "    .sl-listicle-tiers{display:flex;flex-direction:column;gap:0.8rem}",
    "    .sl-listicle-tiers[hidden]{display:none}",
    "    .sl-listicle-stage{position:relative}",
    "    .sl-listicle-carousel{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none}",
    "    .sl-listicle-carousel::-webkit-scrollbar{display:none}",
    "    .sl-listicle-slide{flex:0 0 100%;scroll-snap-align:center;display:flex;align-items:center;justify-content:center}",
    "    .sl-listicle-slide img{width:100%;height:auto;max-height:38rem;object-fit:contain;border-radius:1.2rem}",
    "    .sl-listicle-dots{display:flex;gap:0.6rem;justify-content:center}",
    "    .sl-listicle-dot{width:0.7rem;height:0.7rem;border-radius:50%;background:var(--sl-border);transition:background .2s}",
    "    .sl-listicle-dot.is-active{background:var(--sl-brand)}",
    # Listicle reuses the standard price card (.sl-price-option) as a single, reactive instance — no radio,
    # so drop the third grid column; the add-to-cart button sits below.
    "    .sl-listicle-option{grid-template-columns:9rem minmax(0,1fr);cursor:default}",
    "    .sl-listicle-option.no-img{grid-template-columns:minmax(0,1fr)}",
    "    .sl-listicle-add{width:100%;text-align:center;margin-top:0.4rem}",
    "    .sl-flash-banner{position:sticky;top:0;z-index:30;text-align:center;padding:0.8rem 1rem;font-family:var(--sl-font-accent);font-weight:800;color:#fff;background:linear-gradient(90deg,#dc2626,#f97316)}",
    "    .sl-minicart{position:fixed;left:0;right:0;bottom:0;z-index:20;display:none;flex-direction:column;gap:0.6rem;padding:1rem 1.6rem 1.2rem;background:var(--sl-card);border-top:1px solid var(--sl-border);box-shadow:0 -2px 16px rgba(0,0,0,.12)}",
    # In-page notice modal (the server-rendered page is not a Vue app, so it can't mount ConfirmDialog.vue —
    # this mirrors that component's look with theme tokens). Used to surface blocked-action reasons, e.g. the
    # publish guard, instead of the browser's window.alert.
    "    .sl-notice-backdrop{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;padding:1.6rem;background:rgba(0,0,0,.55)}",
    "    .sl-notice-backdrop.is-visible{display:flex}",
    "    .sl-notice-card{width:min(40rem,100%);background:var(--sl-card);border:1px solid var(--sl-border);border-radius:var(--sl-radius);padding:2.4rem 2rem 2rem;text-align:center;display:grid;gap:1.4rem;justify-items:center;box-shadow:0 16px 48px rgba(0,0,0,.35)}",
    "    .sl-notice-icon{width:4.4rem;height:4.4rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2.2rem;font-weight:800;background:color-mix(in srgb,var(--sl-accent) 16%,transparent);color:var(--sl-accent)}",
    "    .sl-notice-msg{color:var(--sl-text);font-size:1.5rem;line-height:1.5;margin:0}",
    "    .sl-notice-ok{width:auto;min-width:12rem;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:0.9rem;padding:1rem 2.4rem;font-family:var(--sl-font-accent);font-size:1.5rem;font-weight:800;cursor:pointer}",
    "    .sl-minicart.is-visible{display:flex}",
    "    .sl-minicart-lines{display:flex;flex-direction:column;gap:0.3rem;max-height:34vh;overflow-y:auto}",
    "    .sl-minicart-line{display:flex;align-items:center;gap:0.8rem;font-size:1.35rem;color:var(--sl-text)}",
    "    .sl-minicart-line-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    "    .sl-minicart-line-qty{color:var(--sl-muted);font-variant-numeric:tabular-nums}",
    "    .sl-minicart-line-amt{font-weight:700;font-variant-numeric:tabular-nums}",
    "    .sl-minicart-remove{border:0;background:transparent;color:var(--sl-muted);font-size:1.8rem;line-height:1;cursor:pointer;padding:0 0.2rem}",
    "    .sl-minicart-remove:hover{color:var(--sl-text)}",
    "    .sl-minicart-bar{display:flex;align-items:center;justify-content:space-between;gap:1rem}",
    "    .sl-minicart-summary{font-family:var(--sl-font-accent);font-weight:800;color:var(--sl-text)}",
    "    .sl-minicart-checkout{margin:0;padding:0.9rem 1.8rem;white-space:nowrap}",
    "    .sl-minicart-checkout[disabled]{opacity:.7;cursor:default}",
    "    .sl-product-details{width:min(52rem,100%);margin:0 auto;display:flex;flex-direction:column;gap:1rem}",
    "    .sl-details-desc{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-details-gallery{display:flex;gap:0.8rem;overflow-x:auto;scrollbar-width:none}",
    "    .sl-details-gallery::-webkit-scrollbar{display:none}",
    "    .sl-details-thumb{width:7rem;height:7rem;object-fit:cover;border-radius:0.8rem;border:1px solid var(--sl-price-card-border);flex:0 0 auto}",
    "    .sl-details-badges{display:flex;flex-wrap:wrap;gap:0.6rem}",
    "    .sl-details-badge{font-size:1.2rem;font-weight:700;color:var(--sl-chip-text);background:var(--sl-chip-bg);border:1px solid var(--sl-chip-border);border-radius:99.9rem;padding:0.3rem 0.9rem}",
    "    .sl-legal{display:flex;gap:1.2rem;flex-wrap:wrap;justify-content:center;text-align:center;font-size:1.3rem;color:var(--sl-legal-text);padding:2.4rem 0 0}",
    "    .sl-legal span{flex:0 0 100%}",
    "    .sl-legal a{color:var(--sl-legal-link)}",
    "    .sl-breadcrumb{font-size:1.3rem;color:var(--sl-legal-text);padding:1.6rem 0 0}",
    "    .sl-breadcrumb ol{list-style:none;display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem;padding:0;margin:0}",
    "    .sl-breadcrumb li{display:flex;align-items:center;gap:0.5rem}",
    "    .sl-breadcrumb li+li::before{content:\"/\";opacity:0.6}",
    "    .sl-breadcrumb a{color:var(--sl-legal-link);text-decoration:none}",
    "    .sl-breadcrumb a:hover{text-decoration:underline}",
    "    .sl-breadcrumb [aria-current=\"page\"]{color:var(--sl-content-text)}",
    "    .sl-siteheader{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;padding:0.8rem 0 0}",
    "    .sl-siteheader:not(:has(.sl-brand)){justify-content:center}",
    "    .sl-brand{font-family:var(--sl-font-heading);font-weight:800;font-size:1.8rem;color:var(--sl-text);text-decoration:none}",
    "    .sl-nav ul{list-style:none;display:flex;flex-wrap:wrap;gap:1.4rem;padding:0;margin:0}",
    "    .sl-nav a{color:var(--sl-text);text-decoration:none;font-size:1.4rem}",
    "    .sl-nav a:hover{text-decoration:underline}",
    # SEO turned off (Site-level opt-out): the storefront header drops its breadcrumb and its brand (when it still
    # carries one — i.e. a page with no ● Brand mark of its own) renders as the plain no-SEO brand cue — centered,
    # uppercase, dotted (matching .sl-brand-label). The nav stays (it's navigation, not SEO). Purely visual; the
    # noindex robots directive is applied server-side at publish.
    "    body[data-seo=\"off\"] .sl-breadcrumb{display:none}",
    "    body[data-seo=\"off\"] .sl-siteheader{justify-content:center;padding-top:1.6rem}",
    "    body[data-seo=\"off\"] .sl-brand{display:inline-flex;align-items:center;gap:0.8rem;font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--sl-brand-label-text)}",
    "    body[data-seo=\"off\"] .sl-brand::before{content:'';width:1rem;height:1rem;border-radius:999px;background:var(--sl-brand-dot);box-shadow:0 0 0.8rem var(--sl-brand-dot)}",
    "    .sl-footernav{padding:1.6rem 0 0}",
    "    .sl-footernav ul{list-style:none;display:flex;flex-wrap:wrap;justify-content:center;gap:1.4rem;padding:0;margin:0}",
    "    .sl-footernav a{color:var(--sl-legal-link);text-decoration:none;font-size:1.3rem}",
    "    .sl-footernav a:hover{text-decoration:underline}",
    "    @media (max-width: 700px){.sl-price-option{grid-template-columns:8.8rem minmax(0,1fr) 2.4rem;gap:1rem;padding:1.2rem}.sl-price-option img{width:8.8rem}.sl-content-block{grid-template-columns:1fr}.sl-headline h1{font-size:3rem}.sl-testimonial{grid-template-columns:1fr;padding:1.8rem 1.6rem 1.8rem 3.8rem}.sl-testimonial img{width:5.6rem;height:5.6rem;order:-1}.sl-testimonial blockquote{font-size:1.6rem}.sl-quote-fancy .sl-quote-photo{align-self:auto;min-height:0;height:20rem}.sl-quote-fancy .sl-quote-photo img{position:static;transform:none;height:100%}.sl-page-ribbon{padding:2rem;gap:1.4rem}.sl-page-ribbon.is-image_left,.sl-page-ribbon.is-compact{grid-template-columns:minmax(0,1fr)}.sl-page-ribbon .sl-ribbon-media:not(.sl-cropped) img{max-height:22rem;object-fit:cover}.sl-ribbon-cta{justify-self:stretch;text-align:center;justify-content:center}}",
]

TEMPLATE_STYLES = {
    "universal_bundle": UNIVERSAL_BUNDLE_TEMPLATE_STYLES,
}


def format_money(unit_amount: int, currency: str) -> str:
    amount = Decimal(unit_amount) / Decimal(100)
    currency_code = currency.lower()
    symbol = CURRENCY_SYMBOLS.get(currency_code)
    if symbol:
        return f"{symbol}{amount:.2f}"
    return f"{currency_code.upper()} {amount:.2f}"


def template_name(page: dict[str, Any]) -> str:
    return str((page.get("theme") or {}).get("template") or "universal_bundle")


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
    tokens.setdefault("countdown_bg", tokens["cta_from"] if preset_name != "techno-green" else "#dc2626")
    tokens.setdefault("countdown_end_bg", tokens["cta_to"] if preset_name != "techno-green" else "#f97316")
    tokens.setdefault("countdown_text", "#ffffff")
    tokens.setdefault("brand_label_text", tokens["muted"])
    tokens.setdefault("brand_dot", tokens["brand"])
    tokens.setdefault("highlight_text", "#f97316")
    tokens.setdefault("highlight_bg", "#facc15")
    tokens.setdefault("highlight_bg_text", "#1a1a1a")
    tokens.setdefault("subheadline_text", tokens["muted"])
    tokens.setdefault("hero_bg", tokens["card"])
    tokens.setdefault("hero_border", tokens["border"])
    tokens.setdefault("trust_badge_bg", tokens["chip_bg"])
    tokens.setdefault("trust_badge_text", tokens["chip_text"])
    tokens.setdefault("trust_badge_border", tokens["chip_border"])
    tokens.setdefault("price_card_bg", tokens["card"])
    tokens.setdefault("price_card_border", tokens["border"])
    tokens.setdefault("price_card_selected_border", tokens["brand"])
    tokens.setdefault("price_radio", tokens["accent"])
    tokens.setdefault("price_title", tokens["text"])
    tokens.setdefault("price_description", tokens["muted"])
    tokens.setdefault("price_amount", tokens["brand"])
    tokens.setdefault("price_regular", tokens["muted"])
    tokens.setdefault("refund_bg", tokens["card"])
    tokens.setdefault("refund_border", tokens["border"])
    tokens.setdefault("refund_summary", tokens["text"])
    tokens.setdefault("refund_title", tokens["text"])
    tokens.setdefault("refund_text", tokens["muted"])
    tokens.setdefault("refund_applies", tokens["brand"])
    tokens.setdefault("refund_return", tokens["text"])
    tokens.setdefault("content_heading", tokens["text"])
    tokens.setdefault("content_text", tokens["muted"])
    tokens.setdefault("content_border", tokens["border"])
    tokens.setdefault("faq_bg", tokens["card"])
    tokens.setdefault("faq_border", tokens["border"])
    tokens.setdefault("faq_summary", tokens["text"])
    tokens.setdefault("faq_text", tokens["muted"])
    tokens.setdefault("legal_text", tokens["muted"])
    tokens.setdefault("legal_link", tokens["muted"])
    tokens.setdefault("cta_scrim", tokens["background"])
    return tokens


def css_var_name(token_name: str) -> str:
    return token_name.replace("_", "-")


def font_stack(page: dict[str, Any], role: str) -> str:
    fonts = ((page.get("theme") or {}).get("fonts") or {})
    font = fonts.get(role) if isinstance(fonts.get(role), dict) else {}
    family = str(font.get("family") or "system")
    fallback = str(font.get("fallback") or "system")
    fallback_stack = FONT_FALLBACK_STACKS.get(fallback, SYSTEM_FONT_STACK)
    if family == "system":
        return fallback_stack if fallback != "monospace" else SYSTEM_MONO_FONT_STACK
    css_family = f"'{family}'" if any(char.isspace() for char in family) else family
    if css_family == fallback_stack:
        return css_family
    return f"{css_family},{fallback_stack}"


def font_vars(page: dict[str, Any]) -> str:
    return (
        f"--sl-font-body:{font_stack(page, 'body')};"
        f"--sl-font-heading:{font_stack(page, 'heading')};"
        f"--sl-font-accent:{font_stack(page, 'accent')};"
        f"--sl-font-mono:{SYSTEM_MONO_FONT_STACK}"
    )


def render_template_styles(page: dict[str, Any]) -> list[str]:
    template = template_name(page)
    try:
        styles = TEMPLATE_STYLES[template]
    except KeyError as exc:
        raise RenderError(f"Unsupported page theme.template '{template}'.") from exc

    tokens = theme_tokens(page)
    token_vars = ";".join(
        f"--sl-{css_var_name(key)}:{escape(str(value))}"
        for key, value in tokens.items()
    )
    return [
        f"    :root{{{token_vars};--sl-theme-background:{escape(tokens['background'])};--sl-theme-text:{escape(tokens['text'])};--sl-theme-accent:{escape(tokens['accent'])};{font_vars(page)}}}",
        *styles,
    ]


def format_headline(text: str) -> str:
    if not text:
        return ""

    words = re.split(r"(\s+)", str(text))
    word_indexes = [index for index, word in enumerate(words) if word and not word.isspace()]
    if not word_indexes:
        return str(text)
    first_word = word_indexes[0]
    last_word = word_indexes[-1]

    formatted: list[str] = []
    for index, word in enumerate(words):
        if not word or word.isspace():
            formatted.append(word)
            continue
        formatted.append(format_headline_word(word, index == first_word, index == last_word))
    return "".join(formatted)


def format_headline_word(word: str, is_first: bool, is_last: bool) -> str:
    if len(word) >= 2 and word == word.upper() and re.fullmatch(r"[A-Z]+", word):
        return word

    leading = re.match(r"^[^A-Za-z]*", word).group(0)  # type: ignore[union-attr]
    trailing_match = re.search(r"[^A-Za-z]*$", word)
    trailing = trailing_match.group(0) if trailing_match else ""
    end_index = len(word) - len(trailing) if trailing else len(word)
    core = word[len(leading):end_index]
    if not core:
        return word
    if len(core) >= 2 and core == core.upper() and re.fullmatch(r"[A-Z]+", core):
        return word

    lower_core = core.lower()
    if lower_core == "s" and re.search(r"[\d']$", leading):
        return f"{leading}{core}{trailing}"
    if not is_first and not is_last and lower_core in HEADLINE_LOWERCASE_WORDS:
        return f"{leading}{lower_core}{trailing}"
    return f"{leading}{capitalize_headline_core(lower_core)}{trailing}"


def capitalize_headline_core(word: str) -> str:
    if "-" in word:
        return "-".join(capitalize_headline_core(part) for part in word.split("-"))
    return word[:1].upper() + word[1:] if word else word


def render_headline_markup(text: Any) -> str:
    raw = format_headline(str(text or ""))
    tokens = re.split(r"(\*\*.*?\*\*|\^\^.*?\^\^)", raw)
    rendered: list[str] = []
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) >= 4:
            rendered.append(f"<span class=\"sl-mark-text\">{escape(token[2:-2])}</span>")
            continue
        if token.startswith("^^") and token.endswith("^^") and len(token) >= 4:
            rendered.append(f"<span class=\"sl-mark-bg\">{escape(token[2:-2])}</span>")
            continue
        rendered.append(escape(token))
    return "".join(rendered)


def require_offer_products(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> None:
    for item in stage_opportunities(offer, STAGE_LANDING):
        if item.get("service_id"):
            continue  # service items are resolved against services_by_id, not products
        product_id = item.get("product_id", "")
        if product_id not in products_by_id:
            raise RenderError(f"Product '{product_id}' was not provided for offer '{offer.get('offer_id', '')}'.")


# Ultimate brand fallback for the <title> when the tenant set no offer brand and no business name.
PLATFORM_BRAND = "Junior Bay"
TITLE_MAX = 60
# Condition word emitted in a transactional title (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-03). "new" is the
# assumed default and omitted (frees characters); "damaged" reads as "For Parts" to match how buyers search.
_TITLE_CONDITION_WORD = {"used": "Used", "refurbished": "Refurbished", "new": None, "damaged": "For Parts"}


def _title_condition_word(condition: Any, include_new: bool) -> str | None:
    key = str(condition or "").strip().lower()
    if key == "new" and not include_new:
        return None
    return _TITLE_CONDITION_WORD.get(key)


def _dedupe_title_prefix(title: str) -> str:
    # Guard tenants who already named the product "Buy X" or "Used X".
    title = re.sub(r"(?i)^(?:Buy\s+)(?:Buy\s+)+", "Buy ", title)
    title = re.sub(r"(?i)\b(Used|Refurbished|New|For Parts)\s+\1\b", r"\1", title)
    return title


def _truncate_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).strip()


def document_title(page: dict[str, Any], offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    """The <head> <title> (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-03). Tenant's SEO title wins; otherwise a
    transactional formula "Buy {condition} {product.name} | {brand_label}" (lead-gen omits "Buy"). Degrades
    to fit ~60 chars: drop the brand suffix, then truncate the name at a word boundary. brand_label is the
    storefront brand (offer.presentation.brand); the product name carries the manufacturer. Never page.name/
    offer.name (the internal "… Single Offer" label)."""
    explicit = str((page.get("seo") or {}).get("title") or "").strip()
    if explicit:
        return explicit
    product = first_offer_product(offer, products_by_id)
    presentation = offer.get("presentation") or {}
    model = resolve_semantic_model(offer, products_by_id)
    bundle = is_bundle(model)
    # Coherence with the offer label + slug (Offer Semantic Model P2): a multi-product offer is titled by its
    # bundle subject ("Dietary Supplement Bundle"), not just the first product. A single product is unchanged
    # — same product.name, with the presentation.headline fallback preserved.
    name = subject_from_model(model) if bundle else str(product.get("name") or presentation.get("headline") or "").strip()
    brand = resolved_brand_label(presentation)
    intent = str(product.get("product_intent") or offer.get("product_intent") or "transaction")
    is_transactional = intent == "transaction"
    include_new = bool((page.get("seo") or {}).get("include_new_in_title"))
    # A condition word ("Used", "Refurbished") describes one product, not a mixed bundle — suppress for bundles.
    condition_word = (_title_condition_word(product.get("condition"), include_new)
                      if is_transactional and not bundle else None)

    parts = []
    if is_transactional:
        parts.append("Buy")
    if condition_word:
        parts.append(condition_word)
    parts.append(name)
    core = _dedupe_title_prefix(" ".join(part for part in parts if part)).strip()
    if not core:
        return brand
    suffix = f" | {brand}"
    if len(core + suffix) <= TITLE_MAX:
        return core + suffix
    if len(core) <= TITLE_MAX:
        return core
    return _truncate_at_word(core, TITLE_MAX)


_DESC_MIN = 100
_DESC_MAX = 155
# Rotated deterministically by product_id so a page's CTA is stable but the corpus isn't one boilerplate
# string (a near-duplicate footprint). A tenant can override globally via seo.description_cta.
_DESC_CTAS = ["Get yours today!", "Order now.", "Ships fast — order today.", "In stock now."]


def _stable_index(key: Any, length: int) -> int:
    if length <= 0:
        return 0
    total = 0
    for ch in str(key or ""):
        total = (total * 31 + ord(ch)) & 0xFFFFFFFF
    return total % length


def _return_window_days(policy: dict[str, Any]) -> int:
    match = re.search(r"(\d+)", str((policy or {}).get("refund_window") or ""))
    return int(match.group(1)) if match else 0


def document_description(page: dict[str, Any], offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    """The <head> <meta name="description"> (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-04). Tenant's text wins
    (capped). Otherwise the product description, and when it's thin (<100 chars) it is enriched into
    "Shop {condition} {name}. {desc}. {return signal} {CTA}" — idempotent (no double "Shop"/".."), capped at
    155 at a word boundary. Meta description is a CTR lever, not a ranking factor."""
    explicit = str((page.get("seo") or {}).get("description") or "").strip()
    if explicit:
        return trim_meta(explicit, _DESC_MAX)
    product = first_offer_product(offer, products_by_id)
    presentation = offer.get("presentation") or {}
    model = resolve_semantic_model(offer, products_by_id)
    bundle = is_bundle(model)
    desc = str(product.get("description") or presentation.get("subheadline") or "").strip()
    if len(desc) >= _DESC_MIN:
        return trim_meta(desc, _DESC_MAX)

    already_cta = bool(re.match(r"(?i)^(shop|buy|get|order)\b", desc))
    condition = "" if bundle else str(product.get("condition") or "").strip().lower()
    cond = f"{condition} " if condition and condition != "new" else ""
    # Same subject as the <title> and label: the enriched "Shop {subject}." names the bundle, not one product.
    name = subject_from_model(model) if bundle else str(product.get("name") or presentation.get("headline") or "").strip()
    policy = offer.get("refund_policy") or product.get("refund_policy") or {}
    days = _return_window_days(policy)
    site_cta = str((page.get("seo") or {}).get("description_cta") or "").strip()
    cta = site_cta or _DESC_CTAS[_stable_index(product.get("product_id"), len(_DESC_CTAS))]

    segments: list[str] = []
    if name and not already_cta:
        segments.append(f"Shop {cond}{name}.")
    body = re.sub(r"[.\s]+$", "", desc)
    if body:
        segments.append(f"{body}.")
    if days:
        segments.append(f"{days}-day returns.")
    if cta:
        segments.append(cta)
    text = re.sub(r"\.\s*\.", ".", re.sub(r"\s+", " ", " ".join(segments)).strip())
    return trim_meta(text, _DESC_MAX)


def render_head_seo_tags(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    title: str,
    description: str,
) -> list[str]:
    """Canonical, robots, Open Graph / Twitter Card, and LCP resource hints for the <head>
    (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01/02/09/10). Interim: canonical/og:url come from the page's
    published URL; clean root-domain paths and funnel/env noindex land with the Site work."""
    lines: list[str] = []
    canonical = _RENDER_STATE.get("canonical") or ""
    if canonical:
        lines.append(f'  <link rel="canonical" href="{escape(canonical)}">')
    # Indexing directive: index only for the published artifact in production; preview and non-prod are
    # noindex,nofollow (SEO-02/21). Funnel/upsell/thank-you noindex is still Phase 2 (needs funnel context).
    lines.append(f'  <meta name="robots" content="{escape(_RENDER_STATE.get("robots") or NOINDEX_ROBOTS)}">')
    # Webmaster verification tokens (SEO-16) — let a tenant verify their Site in Google/Bing Search Console
    # so they can submit sitemaps. Emitted only when set on the Site.
    google_verify = str(_RENDER_SEO.get("google_site_verification") or "").strip()
    if google_verify:
        lines.append(f'  <meta name="google-site-verification" content="{escape(google_verify)}">')
    bing_verify = str(_RENDER_SEO.get("bing_site_verification") or "").strip()
    if bing_verify:
        lines.append(f'  <meta name="msvalidate.01" content="{escape(bing_verify)}">')

    product = first_offer_product(offer, products_by_id)
    presentation = offer.get("presentation") or {}
    brand_label = resolved_brand_label(presentation)
    intent = str(product.get("product_intent") or offer.get("product_intent") or "transaction")
    og_type = "product" if intent == "transaction" else "website"
    og_title = title.split(" | ", 1)[0] if " | " in title else title
    image = seo_image_url(next((img for img in (product.get("images") or []) if img), ""))
    prices = landing_page_offer_prices(offer, products_by_id, services_by_id)
    selected = selected_landing_page_price(offer, products_by_id, prices) if prices else {}

    tags: list[tuple[str, str]] = [
        ("og:type", og_type),
        ("og:site_name", brand_label),
        ("og:title", og_title),
        ("og:description", description),
    ]
    if image:
        tags.append(("og:image", image))
        base = rendition_base(image)
        dims = _RENDER_DIMS_INDEX.get(base) if base else None
        if dims:
            tags.append(("og:image:width", str(dims[0])))
            tags.append(("og:image:height", str(dims[1])))
        alt = str(product.get("name") or "").strip()
        if alt:
            tags.append(("og:image:alt", alt))
    if canonical:
        tags.append(("og:url", canonical))
    if selected:
        tags.append(("product:price:amount", money_string(selected["unit_amount"])))
        tags.append(("product:price:currency", str(selected.get("currency") or "usd").upper()))
    for prop, content in tags:
        if content:
            lines.append(f'  <meta property="{escape(prop)}" content="{escape(str(content))}">')
    lines.append('  <meta name="twitter:card" content="summary_large_image">')

    # LCP hints: the hero is a cross-origin image, so save the DNS+TCP+TLS handshake and preload it.
    if image:
        host_match = re.match(r"^(https?://[^/]+)", image)
        host = host_match.group(1) if host_match else ""
        if host:
            lines.append(f'  <link rel="preconnect" href="{escape(host)}" crossorigin>')
            lines.append(f'  <link rel="dns-prefetch" href="{escape(host)}">')
        base = rendition_base(image)
        if base:
            srcset = ", ".join(
                f"{escape(f'{base}/{size}.webp')} {width}w"
                for size, width in IMAGE_RENDITION_WIDTHS.items()
                if size in ("small", "medium", "large")
            )
            lines.append(
                f'  <link rel="preload" as="image" href="{escape(f"{base}/medium.webp")}" '
                f'imagesrcset="{srcset}" imagesizes="{escape(HERO_MEDIA_SIZES)}" fetchpriority="high">'
            )
        else:
            lines.append(f'  <link rel="preload" as="image" href="{escape(image)}" fetchpriority="high">')
    return lines


def trim_meta(text: str, limit: int = 155) -> str:
    """Collapse whitespace and trim to a word boundary near `limit` — no mid-word cut, no trailing
    punctuation. Mirrors the builder's trimForMeta so preview and published descriptions match."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    cut = clean.rfind(" ", 0, limit)
    return clean[: cut if cut > 0 else limit].rstrip(",;:. ")


# Render-scoped page context (plans/ON_PAGE_SEO_REQUIREMENTS.md): the page's canonical public URL and its
# robots directive, needed by the head (canonical, og:url, robots) AND the Product JSON-LD (offers.url,
# seller) AND the checkout CTA (real success/cancel URLs). Threaded via a render-scoped holder — like
# _RENDER_DIMS_INDEX — so head-channel elements don't each need it in their signature.
_RENDER_STATE: dict[str, str] = {"canonical": "", "robots": "noindex,nofollow", "home_url": "", "page_type": ""}
# The Site's Organization identity for this render (plans/SITE_OBJECT.md §2.2) — the single source every
# page's entity graph derives from: the Organization/WebSite JSON-LD nodes, the Offer.seller reference, and
# the brand shown in the title suffix / og:site_name when the offer names no brand. Render-scoped like
# _RENDER_STATE; empty when the page has no Site yet (graceful — the renderer falls back to the offer brand).
_RENDER_ORG: dict[str, Any] = {}
# On-page BNPL messaging config for this render (plans/BNPL_PAYMENT_METHODS.md P3): {publishable_key,
# payment_method_types, country} threaded from publish (the tenant's stripe_keys), plus amount/currency the
# renderer fills from the resolved offer. Drives Stripe's Payment Method Messaging Element below the price.
# Render-scoped like _RENDER_ORG; empty when the tenant has no enabled installment methods / no publishable key.
_RENDER_BNPL: dict[str, Any] = {}
# The Site's SEO config for this render (plans/SITE_OBJECT.md §2.4): webmaster-verification tokens (SEO-16),
# title suffix, default OG image. Render-scoped like _RENDER_ORG; empty when the page has no Site.
_RENDER_SEO: dict[str, Any] = {}
# The Site's resolved menus for this render (SEO-13): {"primary": [{label,url}], "footer": [...]}. Rendered as
# visible nav only when the page is served on a verified custom domain (the slugs resolve there). Render-scoped.
_RENDER_NAV: dict[str, list[dict[str, str]]] = {"primary": [], "footer": []}
# The Site's category pages this render can link to (SEO-11/13): {category_key: {"slug", "label"}}. Lets a
# landing page's breadcrumb insert its category level (Home → Category → Product). Render-scoped.
_RENDER_CATEGORY_PAGES: dict[str, dict[str, str]] = {}
# product_id -> its markup-eligible reviews for this render (plans/REVIEWS.md). Feeds the Product
# aggregateRating/review JSON-LD AND the visible reviews block (Google requires the review text on-page).
_RENDER_REVIEWS: dict[str, list[dict[str, Any]]] = {}
# Business-target reviews for the page's Site — a visible trust block, NEVER a self-serving LocalBusiness
# AggregateRating (Google suppresses those; plans/REVIEWS.md).
_RENDER_BUSINESS_REVIEWS: list[dict[str, Any]] = []
# A page is indexable only when it is the published artifact in production (SEO-02/21). Everything else —
# the tenant's preview, any non-production environment — must be kept out of the index.
INDEXABLE_ROBOTS = "index,follow,max-image-preview:large,max-snippet:-1"
NOINDEX_ROBOTS = "noindex,nofollow"
# Crawlable-but-not-indexed: pending Connect verification, and funnel/checkout/thank-you pages on an otherwise
# eligible Site — let crawlers follow links without indexing the page itself (TP-08, SEO-02).
NOINDEX_FOLLOW_ROBOTS = "noindex,follow"
# An archived Site: its pages still serve, but tell crawlers to drop them entirely — no index, no link
# equity, no cached copy. `noarchive` suppresses the search engine's cached snapshot (plans/SITE_OBJECT.md).
NOINDEX_ARCHIVED_ROBOTS = "noindex,nofollow,noarchive"
# page_type values that must never be indexed even on an eligible Site (post-checkout funnel steps).
NONINDEXABLE_PAGE_TYPES = {"checkout", "thank_you", "funnel_step"}


def page_robots_directive(*, kind: str, environment: str, eligibility: str, page_type: str, on_custom_domain: bool, site_archived: bool = False, seo_enabled: bool = True) -> str:
    """The robots directive for a page artifact (plans/SITE_OBJECT.md §2.2, TP-08, SEO-02). Only a published
    artifact in production, actually served on the Site's verified custom domain, whose Site is index-eligible
    (verified custom domain AND verified Stripe Connect), on an indexable page_type, gets index,follow.
    Everything on platform infrastructure — and any page not served on the custom domain — is noindex,nofollow,
    the reputation-isolation floor."""
    if site_archived:
        return NOINDEX_ARCHIVED_ROBOTS  # an archived Site de-indexes every one of its pages, everywhere
    if not seo_enabled:
        return NOINDEX_ROBOTS  # the tenant turned search visibility off for this Site (Site-level opt-out)
    if kind != "published" or environment != "prod":
        return NOINDEX_ROBOTS
    if not on_custom_domain:
        return NOINDEX_ROBOTS  # platform host, or a page not served on the custom domain: never indexed
    if eligibility == "eligible":
        return NOINDEX_FOLLOW_ROBOTS if page_type in NONINDEXABLE_PAGE_TYPES else INDEXABLE_ROBOTS
    if eligibility == "pending":
        return NOINDEX_FOLLOW_ROBOTS
    return NOINDEX_ROBOTS  # blocked / revoked


# Local-SEO alt text (plans/LOCAL_SEO_SIGNALS.md): only local/service businesses (and physical stores) get a
# locality anchor woven into image alt — a DTC OnlineStore reviewing "Creatine Gummies in Denver" is noise.
_LOCAL_BUSINESS_TYPES = {
    "LocalBusiness", "HomeAndConstructionBusiness", "HealthAndBeautyBusiness",
    "FoodEstablishment", "ProfessionalService", "Store",
}


def _org_is_local(org: dict[str, Any]) -> bool:
    """A page is a local business when its Site's broad entity_type is a LocalBusiness bucket OR it names a
    specific LocalBusiness subtype (every business_type is local). Gates the alt/figcaption NAP signals."""
    if str(org.get("business_type") or "") in BUSINESS_TYPES:
        return True
    return str(org.get("entity_type") or "") in _LOCAL_BUSINESS_TYPES


def local_business_anchor() -> str:
    """' at {Business} in {City}, {Region}' when the page's Site is a LOCAL business with a locality — the
    local-SEO signal woven into image alt. Empty for DTC/product stores or incomplete NAP."""
    org = _RENDER_ORG
    if not _org_is_local(org):
        return ""
    name = str(org.get("name") or "").strip()
    locality = str((org.get("address") or {}).get("locality") or "").strip()
    if not name or not locality:
        return ""
    region = str((org.get("address") or {}).get("region") or "").strip()
    return f" at {name} in {locality}, {region}" if region else f" at {name} in {locality}"


def localized_alt(base_alt: str) -> str:
    """Append the local-business anchor to a (raw, unescaped) image alt — unless the alt is empty or already
    names the business (never keyword-stuff). Returns raw text; the caller escapes."""
    base = str(base_alt or "").strip()
    anchor = local_business_anchor()
    if not base or not anchor:
        return base
    name = str(_RENDER_ORG.get("name") or "").strip()
    if name and name.lower() in base.lower():
        return base
    return base + anchor


def local_business_caption() -> str:
    """A derived NAP figcaption for a local business hero (plans/LOCAL_SEO_SIGNALS.md) — visible text under the
    image carrying the name + full address that the alt shouldn't overstuff. Empty for non-local / no address."""
    org = _RENDER_ORG
    if not _org_is_local(org):
        return ""
    name = str(org.get("name") or "").strip()
    address = org.get("address") or {}
    place = ", ".join(p for p in (str(address.get(f) or "").strip() for f in ("street", "locality", "region")) if p)
    if not name or not place:
        return ""
    return f"{name} — {place}"


def resolved_brand_label(presentation: dict[str, Any]) -> str:
    """The storefront brand for the title suffix / og:site_name. The offer's explicit brand wins; otherwise
    the Site's Organization name (the single-source business identity); otherwise the platform brand."""
    brand = str((presentation or {}).get("brand") or "").strip()
    if brand:
        return brand
    return str(_RENDER_ORG.get("name") or "").strip() or PLATFORM_BRAND


def render_page(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None = None,
    checkout_url: str | None = None,
    api_base_url: str | None = None,
    services_by_id: dict[str, dict[str, Any]] | None = None,
    offers_by_id: dict[str, dict[str, Any]] | None = None,
    canonical_url: str = "",
    indexable: bool = False,
    robots: str | None = None,
    site: dict[str, Any] | None = None,
    page_type: str = "",
    reviews: list[dict[str, Any]] | None = None,
    price_context: str = "standard",
    home_url: str | None = None,
    bnpl_messaging: dict[str, Any] | None = None,
) -> str:
    services_by_id = services_by_id or {}
    offers_by_id = offers_by_id or {str(offer.get("offer_id") or ""): offer}
    require_offer_products(offer, products_by_id)
    # Intrinsic image dimensions (plans/LANDING_PAGE_GOAL_COMPOSITION.md Phase 4 CLS slice): merge every
    # document's image_dims sidecar into the render-scoped index so responsive_img can emit width/height
    # without threading a map through each section renderer. Cleared in the finally so the index never
    # leaks into an unrelated render on a warm container.
    _RENDER_DIMS_INDEX.clear()
    _RENDER_DIMS_INDEX.update(collect_image_dims(
        page, offer, *products_by_id.values(), *services_by_id.values(), *offers_by_id.values(),
    ))
    _RENDER_STATE["canonical"] = canonical_page_url(canonical_url)
    # The caller computes the full robots directive (it has the Site + environment); `indexable` remains a
    # back-compat shorthand for the unit tests that exercise the head in isolation.
    _RENDER_STATE["robots"] = robots if robots is not None else (INDEXABLE_ROBOTS if indexable else NOINDEX_ROBOTS)
    _RENDER_ORG.clear()
    organization = (site or {}).get("organization")
    if isinstance(organization, dict):
        _RENDER_ORG.update(organization)
    _RENDER_SEO.clear()
    seo = (site or {}).get("seo")
    if isinstance(seo, dict):
        _RENDER_SEO.update(seo)
    # The Site's resolvable home — root of the breadcrumb trail (SEO-11). Only a verified custom domain serves
    # a working "/", so a breadcrumb (and its Home link) is meaningful only there. page_type gates out
    # post-checkout pages, where a Home link would leak the buyer out of the funnel.
    # The Site's canonical serving origin. When the caller computes it (publishing, which knows whether the page
    # is served on a verified custom domain vs. the free platform host, and whether platform serving is wired),
    # it passes home_url explicitly. Otherwise fall back to the verified-custom-domain derivation — the shape the
    # unit tests and live preview rely on. Internal Site links render RELATIVE regardless (one artifact serves
    # every host); home_url only supplies the absolute origin for the breadcrumb JSON-LD and gates whether the
    # storefront chrome renders at all (plans/PLATFORM_HOSTNAME_SERVING.md Slice 2).
    if home_url is not None:
        _RENDER_STATE["home_url"] = home_url
    else:
        hosting = (site or {}).get("hosting") or {}
        custom_domain = str(hosting.get("custom_domain") or "").strip()
        domain_verified = bool((hosting.get("verification") or {}).get("verified"))
        _RENDER_STATE["home_url"] = f"https://{custom_domain}/" if custom_domain and domain_verified else ""
    _RENDER_STATE["page_type"] = str(page_type or "")
    # SEO opt-out (Site-level "discover in search" switch): when off, the storefront chrome renders in its plain
    # no-SEO form (breadcrumb hidden, brand centered) via a body marker CSS keys off. Robots noindex is applied
    # separately at publish. Default on, so nothing changes for a Site that hasn't toggled it.
    _RENDER_STATE["seo_enabled"] = site_seo_enabled(site)
    # Sale / Flash-Sale context views (plans/SALES_FUNNELS.md P1). The price selector swaps each tier to its
    # paired sale/flash price (same quantity, active context). Whole-page fallback: if no product in the offer
    # has a price in the requested context, the view renders as Standard (i.e. /sale looks like /). The flash
    # time-states (upcoming/ended) are applied client-side; the server render is the "active" state.
    active_context = str(price_context or "standard").strip().lower()
    if active_context not in ("sale", "flash_sale") or not _offer_has_price_context(offer, products_by_id, active_context):
        active_context = "standard"
    _RENDER_STATE["active_price_context"] = active_context
    _RENDER_BNPL.clear()
    if bnpl_messaging and bnpl_messaging.get("publishable_key") and bnpl_messaging.get("payment_method_types"):
        _RENDER_BNPL.update(bnpl_messaging)   # amount/currency get filled from the resolved offer in the body
    # The Site's menus, resolved to {label, url} against the home host (SEO-13). Only meaningful where the
    # slugs resolve (verified custom domain) and never on a post-checkout page (a nav would leak the buyer out).
    _RENDER_NAV["primary"], _RENDER_NAV["footer"] = [], []
    if _RENDER_STATE["home_url"] and str(page_type or "") not in NONINDEXABLE_PAGE_TYPES:
        _RENDER_NAV["primary"] = site_nav_items(site, "primary", _RENDER_STATE["home_url"])
        _RENDER_NAV["footer"] = site_nav_items(site, "footer", _RENDER_STATE["home_url"])
    _RENDER_CATEGORY_PAGES.clear()
    for cat_slug, cat_entry in ((site or {}).get("pages") or {}).items():
        if isinstance(cat_entry, dict) and cat_entry.get("page_type") == "category" and cat_entry.get("category"):
            _RENDER_CATEGORY_PAGES[str(cat_entry["category"])] = {"slug": str(cat_slug), "label": str(cat_entry.get("label") or "")}
    _RENDER_REVIEWS.clear()
    _RENDER_BUSINESS_REVIEWS.clear()
    for review in (reviews or []):
        target = review.get("target") or {}
        if target.get("type") == "product" and str(target.get("id") or ""):
            _RENDER_REVIEWS.setdefault(str(target["id"]), []).append(review)
        elif target.get("type") == "business":
            _RENDER_BUSINESS_REVIEWS.append(review)
    try:
        return _render_page_body(
            page, offer, products_by_id, selected_prices, checkout_url, api_base_url,
            services_by_id, offers_by_id,
        )
    finally:
        _RENDER_DIMS_INDEX.clear()
        _RENDER_STATE["canonical"] = ""
        _RENDER_STATE["robots"] = NOINDEX_ROBOTS
        _RENDER_STATE["home_url"] = ""
        _RENDER_STATE["page_type"] = ""
        _RENDER_STATE["active_price_context"] = "standard"
        _RENDER_BNPL.clear()
        _RENDER_NAV["primary"], _RENDER_NAV["footer"] = [], []
        _RENDER_CATEGORY_PAGES.clear()
        _RENDER_REVIEWS.clear()
        _RENDER_BUSINESS_REVIEWS.clear()
        _RENDER_ORG.clear()
        _RENDER_SEO.clear()


def canonical_page_url(url: str) -> str:
    """Normalize a canonical URL for emission (SEO-01): keep only scheme+host+path, drop every query string
    and fragment. Query params (?checkout=success, ?session_id=…) are crawlable duplicates the canonical
    exists to collapse. Returns "" for anything that isn't an absolute http(s) URL, so callers omit the tag
    rather than emit a broken one."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    match = re.match(r"^(https?)://([^/?#]+)([^?#]*)", raw, re.IGNORECASE)
    if not match:
        return ""
    scheme, host, path = match.group(1).lower(), match.group(2), match.group(3)
    return f"{scheme}://{host}{path}"


def canonical_origin() -> str:
    """scheme://host of the render-scoped canonical URL — the anchor for seller/Organization @id."""
    match = re.match(r"^(https?://[^/]+)", _RENDER_STATE.get("canonical") or "", re.IGNORECASE)
    return match.group(1) if match else ""


def _render_page_body(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None,
    checkout_url: str | None,
    api_base_url: str | None,
    services_by_id: dict[str, dict[str, Any]],
    offers_by_id: dict[str, dict[str, Any]],
) -> str:
    # Resolve against the prices this PAGE shows. The offer's default_price_id may point at an upsell /
    # downsell / order-bump price, which belongs to the post-checkout flow — letting it through made the CTA
    # advertise an amount no price card displayed.
    # A storefront/collection page has no primary offer (offer == {}); there's nothing to resolve or price.
    # Its catalog_grid resolves each card's own offer from offers_by_id instead.
    resolved_offer = resolve_offer(
        offer,
        products_by_id,
        landing_page_selected_prices(offer, products_by_id, selected_prices),
        services_by_id=services_by_id,
    ) if offer else {}
    # On-page BNPL messaging (P3): fill the displayed amount/currency from the resolved offer so Stripe's
    # Payment Method Messaging Element below the price shows "As low as N payments of $X" for the right total.
    if _RENDER_BNPL.get("publishable_key") and resolved_offer:
        _RENDER_BNPL["amount"] = int(resolved_offer.get("subtotal") or 0)
        _RENDER_BNPL["currency"] = str(resolved_offer.get("currency") or "usd")
    # The <head> title/description are derived here so they are correct regardless of what a page stored
    # (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-03/04). Never page.name/offer.name (the internal "… Single
    # Offer" label). The title is NOT re-title-cased — it preserves the product name verbatim so <title>,
    # <h1>, and JSON-LD all read the same "MacBook" (SEO-18 case consistency).
    title = escape(document_title(page, offer, products_by_id))
    description = escape(document_description(page, offer, products_by_id))
    # Default favicon (when the tenant sets none) comes from the configured asset CDN (app_config.public_asset_base_url),
    # resolved via the failsafe cached reader — no hardcoded URL. "" outside a configured backend (tests).
    favicon_tags = render_favicon_tags(page.get("seo") or {}, default_favicon_url())
    styles = render_template_styles(page)
    # Page Composer decides which sections render (plans/PAGE_COMPOSER.md). The renderer only iterates the
    # composed list — it never decides visibility itself.
    composed_sections = compose_page(offer, page, str(_RENDER_STATE.get("page_type") or "landing"))
    # Each element declares a channel (plans/LANDING_PAGE_GOAL_COMPOSITION.md): "body" paints markup, "head"
    # emits meta/JSON-LD, "sidecar" writes its own artifact. Route by it rather than assuming everything is
    # body — a head section rendered into <main> would be visible junk, and vice versa.
    body_sections = [s for s in composed_sections if element_channel(str(s.get("type") or "")) == "body"]
    head_sections = [s for s in composed_sections if element_channel(str(s.get("type") or "")) == "head"]
    # Storefront chrome from the Site's menus (SEO-13): a header (brand → store root + primary nav) and a
    # footer nav. Both empty off a verified custom domain / on post-checkout pages. A crawlable breadcrumb
    # trail (SEO-11) sits above the page content, matching the BreadcrumbList JSON-LD.
    # If the page composes its own ● Brand mark, the store header drops its brand so there's only one (SITE_COLLECTIONS.md
    # "Chrome / header composition"). A disabled brand_label section still counts as absent.
    has_brand_mark = any(
        s.get("type") == "brand_label" and s.get("enabled") is not False for s in body_sections
    )
    site_header = render_site_header(has_brand_mark=has_brand_mark)
    footer_nav = render_footer_nav()
    breadcrumb = render_breadcrumb(breadcrumb_trail(offer, products_by_id))
    body = "\n".join(
        render_section(section, page, offer, products_by_id, resolved_offer, checkout_url, api_base_url, services_by_id, offers_by_id)
        for section in body_sections
    )
    # First-party reviews render after the page's sections (visible content matching the Product review JSON-LD).
    reviews_block = render_reviews_block(offer, products_by_id)
    business_reviews_block = render_business_reviews_block()
    head_extras = "\n".join(part for part in (
        render_head_section(section, page, offer, products_by_id, services_by_id, composed_sections)
        for section in head_sections
    ) if part)
    has_legal_footer_section = any(section.get("type") == "legal_footer" for section in composed_sections)
    # Post-purchase funnel pages (upsell / downsell / thank-you) drop the auto legal footer: they are one-click
    # continuations of an already-completed checkout, not standalone sales pages, so the Terms/Privacy/Refund
    # links are noise there (user request). An explicitly-authored legal_footer section still renders.
    suppress_legal_footer = str(_RENDER_STATE.get("page_type") or "") in ("funnel_step", "thank_you")
    legal_footer = "" if (has_legal_footer_section or suppress_legal_footer) else render_legal_footer(page.get("legal") or {}, api_base_url=api_base_url)
    analytics_tags = render_analytics_tags(page.get("analytics") or {})
    analytics_adapters = render_analytics_adapters(page.get("analytics") or {})
    # A listicle page gets a persistent mini-cart (client-side this phase; server-side cart is L2).
    minicart = render_minicart() if derived_offer_type(offer) == "listicle" else ""
    # Hydration contract: serialize the whole OfferView once so the conversion island updates every
    # section from this single payload — never scraping the DOM (plans/CONVERSION_CONTEXT.md).
    conversion_data = render_conversion_data(offer, products_by_id, services_by_id)
    return "\n".join(part for part in [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"  <title>{title}</title>",
        f"  <meta name=\"description\" content=\"{description}\">" if description else "",
        *render_head_seo_tags(page, offer, products_by_id, services_by_id, title, description),
        favicon_tags,
        head_extras,
        "  <style>",
        *styles,
        "  </style>",
        analytics_tags,
        analytics_adapters,
        render_page_interactions_script(page),
        "</head>",
        ("<body>" if _RENDER_STATE.get("seo_enabled", True) else "<body data-seo=\"off\">"),
        render_price_context_banner(page),
        "  <main>",
        site_header,
        breadcrumb,
        body,
        reviews_block,
        business_reviews_block,
        footer_nav,
        legal_footer,
        "  </main>",
        minicart,
        render_price_context_script(),
        conversion_data,
        *render_bnpl_messaging_scripts(),
        "</body>",
        "</html>",
    ] if part != "")


def render_conversion_data(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> str:
    """Serialize the OfferView's targets into one JSON payload the conversion island reads. Every per-target
    value the page can show (headline/subheadline/image/price/compare/discount) lives here — the island
    never re-fetches or scrapes the DOM. `<` is escaped so the JSON can't close the script early."""
    # On a /sale //flash-sale view every target's single_unit_price swaps to its paired context price, so the
    # conversion island binds the discounted amount too (plans/SALES_FUNNELS.md P1 — listicle parity).
    active_ctx = str(_RENDER_STATE.get("active_price_context") or "standard")
    offer_view = expand_offer(offer, products_by_id, services_by_id, active_ctx)
    targets = []
    for target in offer_view.get("items", []):
        product = target.get("product") or {}
        price = (target.get("pricing") or {}).get("single_unit_price") or {}
        amount = int(price.get("unit_amount") or 0)
        compare = int(price.get("compare_at_amount") or 0)
        discount = round((compare - amount) / compare * 100) if compare > amount > 0 else 0
        badges = [str(b.get("label") if isinstance(b, dict) else b) for b in (product.get("badges") or []) if b]
        price_ctx = str(price.get("context") or "standard")
        targets.append({
            "product_id": product.get("product_id", ""),
            "price_id": price.get("price_id", ""),
            # Fall back to the product's own name/description so a target-bound hero (and any other bound
            # element) has real copy to swap in even when the product carries no presentation headline.
            "headline": product.get("headline") or product.get("name") or "",
            "subheadline": product.get("subheadline") or product.get("description") or "",
            "hero_image": product.get("hero_image", ""),
            "gallery": [str(url) for url in (product.get("gallery") or []) if url],
            "badges": badges,
            "sale_badge": _context_badge_label(price_ctx),
            "amount": amount,
            "compare_at": compare,
            "discount": discount,
            "currency": price.get("currency", "usd"),
        })
    if not targets:
        return ""
    payload = json.dumps(targets, separators=(",", ":")).replace("<", "\\u003c")
    return f"  <script type=\"application/json\" data-conversion-offer>{payload}</script>"


def render_minicart() -> str:
    # A summary bar + a per-line list the island fills from the SERVER cart (add/remove/qty via /cart), and a
    # Checkout button that turns the whole cart into one Stripe session (POST /cart/checkout, L2 Slice C).
    return "\n".join([
        "  <div class=\"sl-minicart\" data-minicart>",
        "    <div class=\"sl-minicart-lines\" data-minicart-lines></div>",
        "    <div class=\"sl-minicart-bar\">",
        "      <span class=\"sl-minicart-summary\" data-minicart-summary></span>",
        "      <button class=\"sl-cta sl-minicart-checkout\" type=\"button\" data-minicart-checkout>Checkout</button>",
        "    </div>",
        "  </div>",
    ])


def render_price_context_banner(page: dict[str, Any]) -> str:
    """A top-of-page state element for a Sale / Flash-Sale view (plans/SALES_FUNNELS.md P1b-2). Carries the
    page's window (`starts_on`/`ends_at`) so the client can pick the live state; flash also shows a visible
    banner (countdown / "coming up" / "ended"). Empty outside a sale/flash view."""
    ctx = str(_RENDER_STATE.get("active_price_context") or "standard")
    if ctx not in ("sale", "flash_sale"):
        return ""
    cfg = (page.get("flash_sale") if ctx == "flash_sale" else page.get("sale")) or {}
    starts_on = int(cfg.get("starts_on") or 0)
    ends_at = int(cfg.get("ends_at") or 0)
    attrs = f"data-price-context=\"{ctx}\" data-starts-on=\"{starts_on}\" data-ends-at=\"{ends_at}\""
    if ctx == "flash_sale":
        return "\n".join([
            f"  <div class=\"sl-flash-banner\" {attrs}>",
            "    <span class=\"sl-flash-banner-text\" data-flash-banner-text>\U0001F525 Flash Sale</span>",
            "  </div>",
        ])
    # Sale view: no visible banner, just the config so the client can revert after an optional expiry.
    return f"  <div class=\"sl-price-context\" {attrs} hidden></div>"


def render_price_context_script() -> str:
    """Client-side Sale/Flash time-states (plans/SALES_FUNNELS.md P1b-2). Pages publish statically, so the live
    state depends on view time: flash shows upcoming / active (countdown) / ended, and both revert the swapped
    price cards to their Standard fallback outside the active window. Empty outside a sale/flash view."""
    if str(_RENDER_STATE.get("active_price_context") or "standard") not in ("sale", "flash_sale"):
        return ""
    return "\n".join([
        "  <script>",
        "    (function () {",
        "      const el = document.querySelector('[data-price-context]');",
        "      if (!el) return;",
        "      const mode = el.getAttribute('data-price-context');",
        "      const startsOn = parseInt(el.getAttribute('data-starts-on') || '0', 10);",
        "      const endsAt = parseInt(el.getAttribute('data-ends-at') || '0', 10);",
        "      const bannerText = el.querySelector('[data-flash-banner-text]');",
        "      const cards = Array.from(document.querySelectorAll('.sl-price-option[data-standard-price-id]'));",
        "      const money = (cents, cur) => { try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: (cur || 'usd').toUpperCase() }).format((cents || 0) / 100); } catch (e) { return '$' + ((cents || 0) / 100).toFixed(2); } };",
        "      const fmtDate = (secs) => { try { return new Date(secs * 1000).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' }); } catch (e) { return ''; } };",
        # Capture both the flash (initial DOM) and Standard values so we can toggle either way.
        "      cards.forEach((c) => { c._flashId = c.getAttribute('data-price-id'); c._flashAmt = parseInt(c.getAttribute('data-sale-amount') || '0', 10); c._stdId = c.getAttribute('data-standard-price-id'); c._stdAmt = parseInt(c.getAttribute('data-standard-amount') || '0', 10); });",
        "      const apply = (useStandard) => {",
        "        cards.forEach((c) => {",
        "          const id = useStandard ? c._stdId : c._flashId; const amt = useStandard ? c._stdAmt : c._flashAmt;",
        "          if (!id) return;",
        "          c.setAttribute('data-price-id', id);",
        "          const radio = c.querySelector('input[type=radio]'); if (radio) radio.value = id;",
        "          const amtEl = c.querySelector('[data-price-amount]'); if (amtEl) amtEl.textContent = money(amt, c.getAttribute('data-currency'));",
        "          c.querySelectorAll('.sl-badge, .sl-regular-price, .sl-savings').forEach((n) => { n.style.display = useStandard ? 'none' : ''; });",
        "        });",
        "      };",
        "      const countdown = (secs) => { const d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60; return '\\u{1F525} Flash Sale ends in ' + (d ? d + 'd ' : '') + h + 'h ' + m + 'm ' + s + 's'; };",
        "      const tick = () => {",
        "        const now = Math.floor(Date.now() / 1000);",
        "        if (endsAt && now >= endsAt) { apply(true); if (bannerText) bannerText.textContent = 'Flash Sale ended'; return false; }",
        "        if (startsOn && now < startsOn) { apply(true); if (bannerText) bannerText.textContent = 'Flash Sale Coming Up on ' + fmtDate(startsOn); return true; }",
        "        apply(false); if (bannerText && endsAt) bannerText.textContent = countdown(endsAt - now); return true;",
        "      };",
        "      if (mode === 'flash_sale') { tick(); const t = setInterval(() => { if (!tick()) clearInterval(t); }, 1000); }",
        "      else { const now = Math.floor(Date.now() / 1000); if (endsAt && now >= endsAt) apply(true); }",  # sale: revert after expiry, no countdown
        "    })();",
        "  </script>",
    ])


def render_product_details(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> str:
    """A context-aware block (plans/CONVERSION_CONTEXT.md "future blocks"): the current target's description,
    gallery, and badges. It reads currentTarget, so on a multi-target/listicle page the whole block SWAPS as
    the visitor swipes — no new plumbing, just data-conversion-bind + data-conversion-list."""
    offer_view = expand_offer(offer, products_by_id, services_by_id or {})
    targets = offer_view.get("items", [])
    if not targets:
        return ""
    product = (targets[0].get("product") or {})
    gallery = [url for url in (product.get("gallery") or []) if url]
    badges = [str(b.get("label") if isinstance(b, dict) else b) for b in (product.get("badges") or []) if b]
    description = str(product.get("subheadline") or "")
    gallery_alt = escape(str(product.get("headline") or "Product image"))
    gallery_html = "".join(f"<img class=\"sl-details-thumb\" src=\"{escape(str(url))}\" loading=\"lazy\" alt=\"{gallery_alt}\">" for url in gallery)
    badges_html = "".join(f"<span class=\"sl-details-badge\">{escape(str(b))}</span>" for b in badges)
    gallery_hidden = "" if gallery else " style=\"display:none\""
    badges_hidden = "" if badges else " style=\"display:none\""
    return "\n".join([
        "    <section class=\"sl-product-details\" data-section-type=\"product_details\" data-conversion-section=\"product_details\">",
        f"      <p class=\"sl-details-desc\" data-conversion-bind=\"subheadline\">{escape(description)}</p>",
        f"      <div class=\"sl-details-gallery\" data-conversion-list=\"gallery\"{gallery_hidden}>{gallery_html}</div>",
        f"      <div class=\"sl-details-badges\" data-conversion-list=\"badges\"{badges_hidden}>{badges_html}</div>",
        "    </section>",
    ])


@dataclass
class SectionRenderContext:
    """Everything a section renderer might need. Passed to each registry entry so renderers read only
    what they use — the registry is the single dispatch source of truth (plans/CONVERSION_CONTEXT.md)."""
    section: dict[str, Any]
    page: dict[str, Any]
    offer: dict[str, Any]
    products_by_id: dict[str, dict[str, Any]]
    resolved_offer: dict[str, Any]
    checkout_url: str | None
    api_base_url: str | None
    services_by_id: dict[str, dict[str, Any]]
    offers_by_id: dict[str, dict[str, Any]]


def _render_offer_selector(c: "SectionRenderContext") -> str:
    if derived_offer_type(c.offer) == "listicle":
        return render_listicle_carousel(c.offer, c.products_by_id, c.services_by_id, c.page, c.checkout_url, c.api_base_url)
    return render_offer_price_selector(c.offer, c.products_by_id, c.services_by_id)


# type -> registry entry. `render` is the adapter; `version` supports future migrations. The builder-facing
# metadata (schema/defaults/editor) is the Vue registry's concern (the editor lives client-side).
SECTION_REGISTRY: dict[str, dict[str, Any]] = {
    "countdown_timer": {"render": lambda c: render_countdown_timer(c.section, c.page), "version": 1},
    "seo_title": {"render": lambda c: render_seo_title(c.section, c.page, c.products_by_id), "version": 1},
    "brand_label": {"render": lambda c: render_brand_label(c.section, c.page), "version": 1},
    "hero_media": {"render": lambda c: render_hero_media(c.section, c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "headline": {"render": lambda c: render_headline(c.section), "version": 1},
    "subheadline": {"render": lambda c: render_subheadline(c.section), "version": 1},
    "trust_badges": {"render": lambda c: render_trust_badges(c.section), "version": 1},
    "hero": {"render": lambda c: render_hero(c.section, c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "offer_price_selector": {"render": _render_offer_selector, "version": 1},
    # A standalone prominent price card (SALES_FUNNELS.md P3.5) — used by the upsell page, whose 'upsell'-context
    # price the offer_price_selector filters out, so the amount would otherwise show only in the CTA button.
    "featured_price": {"render": lambda c: render_featured_price(c.section), "version": 1},
    "refund_policy": {"render": lambda c: render_refund_policy(c.section, c.offer, c.products_by_id), "version": 1},
    "faq": {"render": lambda c: render_faq(c.section), "version": 1},
    "content_block": {"render": lambda c: render_content_blocks(c.section), "version": 1},
    # Thank-you page extras (SALES_FUNNELS.md P3.5 Phase 2) — emitted by synthesize_thank_you_page only.
    "celebration": {"render": lambda c: render_celebration(c.section), "version": 1},
    "next_steps": {"render": lambda c: render_next_steps(c.section), "version": 1},
    "thank_you_footer": {"render": lambda c: render_thank_you_footer(c.section), "version": 1},
    "testimonials": {"render": lambda c: render_testimonials(c.section), "version": 1},
    "rating": {"render": lambda c: render_rating(c.section), "version": 1},
    "client_marquee": {"render": lambda c: render_client_marquee(c.section), "version": 1},
    "price_highlight": {"render": lambda c: render_price_highlight(c.section, c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "author_bio": {"render": lambda c: render_author_bio(c.section), "version": 1},
    "product_details": {"render": lambda c: render_product_details(c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "product_carousel": {"render": lambda c: render_product_carousel(c.section, c.page, c.offers_by_id, c.products_by_id, c.services_by_id, c.checkout_url, c.api_base_url), "version": 1},
    "page_ribbon": {"render": lambda c: render_page_ribbon(c.section, c.page, c.api_base_url), "version": 1},
    "before_after": {"render": lambda c: render_before_after(c.section), "version": 1},
    "numbered_list": {"render": lambda c: render_numbered_list(c.section), "version": 1},
    "quote": {"render": lambda c: render_quote(c.section), "version": 1},
    "bragging_points": {"render": lambda c: render_bragging_points(c.section), "version": 1},
    "post_purchase_carousel": {"render": lambda c: render_post_purchase_carousel(c.section, c.page, c.api_base_url), "version": 1},
    "brand_hero": {"render": lambda c: render_brand_hero(c.section), "version": 1},
    "catalog_grid": {"render": lambda c: render_catalog_grid(c.section, c.offers_by_id, c.products_by_id, c.services_by_id), "version": 1},
    "related_products": {"render": lambda c: render_catalog_grid(c.section, c.offers_by_id, c.products_by_id, c.services_by_id), "version": 1},
    "seller_profile": {"render": lambda c: render_seller_profile(c.section), "version": 1},
    "checkout_cta": {"render": lambda c: render_checkout_cta(c.page, c.section, c.offer, c.resolved_offer, c.checkout_url, c.api_base_url, c.products_by_id), "version": 1},
    "legal_footer": {"render": lambda c: render_legal_footer(c.page.get("legal") or {}, c.section, c.api_base_url), "version": 1},
}


# type -> renderer for sections on the "head" channel. These are DERIVED: they take the whole composed page
# rather than just their own section, because their content comes from the offer and from what the composer
# put on the page — never from tenant-entered fields on the section itself.
# Lambdas defer the name lookup to call time, as SECTION_REGISTRY does, so renderers can be defined below.
HEAD_SECTION_REGISTRY: dict[str, Any] = {
    "structured_data": lambda *a: render_structured_data(*a),
}


def render_head_section(
    section: dict[str, Any],
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    composed_sections: list[dict[str, Any]],
) -> str:
    renderer = HEAD_SECTION_REGISTRY.get(str(section.get("type") or ""))
    if renderer is None:
        return ""
    return renderer(section, page, offer, products_by_id, services_by_id, composed_sections)


def render_section(
    section: dict[str, Any],
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
    services_by_id: dict[str, dict[str, Any]] | None = None,
    offers_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    entry = SECTION_REGISTRY.get(section.get("type"))
    if entry is None:
        return f"    <section data-section-id=\"{escape(str(section.get('id', '')))}\"></section>"
    ctx = SectionRenderContext(
        section=section, page=page, offer=offer, products_by_id=products_by_id,
        resolved_offer=resolved_offer, checkout_url=checkout_url, api_base_url=api_base_url,
        services_by_id=services_by_id or {}, offers_by_id=offers_by_id or {},
    )
    return entry["render"](ctx)


def first_offer_product(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for item in stage_opportunities(offer, STAGE_LANDING):
        product = products_by_id.get(item.get("product_id", ""))
        if product:
            return product
    return {}


def first_offer_lead_capture(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The lead_capture block of the offer's primary lead-gen product — drives the inline form fields."""
    for item in stage_opportunities(offer, STAGE_LANDING):
        product = products_by_id.get(str((item or {}).get("product_id") or ""))
        capture = (product or {}).get("lead_capture")
        if isinstance(capture, dict):
            return capture
    return {}


def countdown_timer_colors(page: dict[str, Any], section: dict[str, Any]) -> tuple[str, str]:
    if section.get("start_color") and section.get("end_color"):
        return str(section["start_color"]), str(section["end_color"])

    tokens = theme_tokens(page)
    return str(tokens["countdown_bg"]), str(tokens["countdown_end_bg"])


def render_countdown_timer(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    duration = int(section.get("duration_minutes") or 0)
    label = escape(str(section.get("start_text") or section.get("label") or "Offer expires in"))
    end_text = escape(str(section.get("end_text") or "Offer expired"))
    raw_start_color, raw_end_color = countdown_timer_colors(page, section)
    start_color = escape(raw_start_color)
    end_color = escape(raw_end_color)
    # Transparent has to win here: an inline background always beats a stylesheet rule, so the option
    # could never take effect while this was set unconditionally.
    transparent = bool(section.get("transparent"))
    marquee_seconds = max(3, min(60, int(section.get("marquee_seconds") or 14)))
    style = f"--sl-countdown-bg:{start_color};--sl-countdown-marquee-duration:{marquee_seconds}s" + ("" if transparent else f";background:{start_color}")
    # Each banner state can be switched off independently; the section hides itself while the active
    # state is disabled. Both were emitted by the builder and ignored here.
    start_enabled = section.get("start_enabled") is not False
    end_enabled = section.get("end_enabled") is not False
    start_icon = escape(str(section.get("start_icon") or ""))
    end_icon = escape(str(section.get("end_icon") or ""))
    return "\n".join([
        f"    <section class=\"sl-countdown\" data-section-id=\"{escape(str(section.get('id', 'countdown')))}\" data-section-type=\"countdown_timer\" data-duration-minutes=\"{duration}\" data-persistent=\"{str(bool(section.get('persistent'))).lower()}\" data-sticky=\"{str(bool(section.get('sticky'))).lower()}\" data-transparent=\"{str(transparent).lower()}\" data-marquee=\"{str(bool(section.get('marquee'))).lower()}\" data-start-text=\"{label}\" data-end-text=\"{end_text}\" data-start-icon=\"{start_icon}\" data-end-icon=\"{end_icon}\" data-start-enabled=\"{str(start_enabled).lower()}\" data-end-enabled=\"{str(end_enabled).lower()}\" data-start-color=\"{start_color}\" data-end-color=\"{end_color}\" style=\"{style}\"{'' if start_enabled else ' hidden'}>",
        # aria-live=off: the timer mutates every second; announcing every tick would flood a screen reader.
        "      <span class=\"sl-countdown-content\" aria-live=\"off\">",
        (f"        <span data-countdown-icon aria-hidden=\"true\">{start_icon}</span>" if start_icon else ""),
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
    title = render_headline_markup(section.get("label") or (page.get("seo") or {}).get("title") or product_name or page.get("name") or "")
    # heading_role: none in the element catalog — the hero is the page's only <h1>, so this is a <p>.
    return "\n".join([
        f"    <section class=\"sl-seo-title\" data-section-id=\"{escape(str(section.get('id', 'seo-title')))}\" data-section-type=\"seo_title\">",
        f"      <p>{title}</p>",
        "    </section>",
    ])


def render_brand_label(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    label = render_headline_markup(section.get("label") or (page.get("seo") or {}).get("title") or page.get("name") or "")
    # heading_role: none in the element catalog — a brand label is not a heading (matches the preview's span).
    # This centered ● Brand mark is the page's single brand header (the old top-left store-header brand is retired).
    # On a served, browseable page it doubles as the crawlable store-root link (SEO-13); on a post-checkout page it
    # stays plain text so it can't leak the buyer back out.
    home = _RENDER_STATE.get("home_url") or ""
    linkable = bool(home) and _RENDER_STATE.get("page_type") not in NONINDEXABLE_PAGE_TYPES
    inner = f'<a class="sl-brand-label-link" href="/">{label}</a>' if linkable else label
    return "\n".join([
        f"    <section class=\"sl-brand-label\" data-section-id=\"{escape(str(section.get('id', 'brand-label')))}\" data-section-type=\"brand_label\">",
        f"      <p>{inner}</p>",
        "    </section>",
    ])


def first_offer_service_image(offer: dict[str, Any], services_by_id: dict[str, dict[str, Any]]) -> str:
    for item in stage_opportunities(offer, STAGE_LANDING):
        service = services_by_id.get(item.get("service_id", ""))
        image = (service or {}).get("presentation", {}).get("hero_image_url") if service else ""
        if image:
            return str(image)
    return ""


VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv")


def is_video_url(url: str) -> bool:
    return urlparse(str(url or "")).path.lower().endswith(VIDEO_EXTENSIONS)


def render_video_embed(embed: dict[str, str], alt: str) -> str:
    """A click-to-load facade: poster and a play button, with the iframe inserted only on click.

    A YouTube iframe pulls roughly a megabyte of script and sets third-party cookies on the tenant's
    customers whether or not anyone watches. The facade costs one image, keeps the page fast, and means
    nothing is shared with the provider until a visitor deliberately asks to play -- which is also the
    honest default for someone else's customers.

    A real <button>, so it is reachable by keyboard and announced as a control. The provider URL is built
    from a strictly-validated id (domain/video_embeds.py), never from tenant text.
    """
    label = escape(alt or "Play video")
    poster = embed.get("thumbnail_url") or ""
    art = (
        f'<img class="sl-embed-poster" src="{escape(poster)}" alt="" loading="lazy" decoding="async">'
        if poster else '<span class="sl-embed-poster is-blank" aria-hidden="true"></span>'
    )
    return (
        f'<div class="sl-embed" data-sl-embed="{escape(embed["embed_url"])}"'
        f' data-embed-title="{label}">'
        f"{art}"
        f'<button type="button" class="sl-embed-play" aria-label="Play {label}">'
        '<svg viewBox="0 0 68 48" width="68" height="48" aria-hidden="true">'
        '<path class="sl-embed-play-bg" d="M66.5 7.7a8 8 0 0 0-5.6-5.7C56 .7 34 .7 34 .7s-22 0-26.9 1.3'
        'A8 8 0 0 0 1.5 7.7 83 83 0 0 0 0 24a83 83 0 0 0 1.5 16.3 8 8 0 0 0 5.6 5.7C12 47.3 34 47.3 34 47.3'
        's22 0 26.9-1.3a8 8 0 0 0 5.6-5.7A83 83 0 0 0 68 24a83 83 0 0 0-1.5-16.3z"></path>'
        '<path d="M45 24 27 14v20z" fill="#fff"></path>'
        "</svg></button></div>"
    )


def render_media_slide(url: str, alt: str, *, autoplay: bool, eager: bool = False) -> str:
    """The MediaViewer's image/video modes (plans/CONVERSION_CONTEXT.md review 4). A video URL renders a
    <video>. Autoplay adds muted+loop because every browser refuses to autoplay with sound.

    `controls` is ALWAYS present, autoplay included. Without it an autoplaying hero starts muted with no
    way to unmute, pause or scrub — the tenant enabled autoplay, not silence, and a visitor who wants the
    audio had no affordance at all. It is also a WCAG 2.2.2 (Pause, Stop, Hide) failure: content that
    plays automatically for more than five seconds must offer a way to stop it."""
    embed = parse_video_embed(url)
    if embed:
        return render_video_embed(embed, alt)
    if is_video_url(url):
        attrs = "controls playsinline" + (" muted loop autoplay" if autoplay else "")
        preload = "auto" if eager else "metadata"
        return (
            f"<video class=\"sl-hero-video\" src=\"{escape(str(url))}\" {attrs} preload=\"{preload}\" "
            f"aria-label=\"{escape(alt)}\"></video>"
        )
    return responsive_img(url, alt, sizes=HERO_MEDIA_SIZES, eager=eager)


HERO_BRAND_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def offer_brand_fallback(offer: dict[str, Any]) -> str:
    """Brand text when the section didn't set one: the offer's picked brand, else its product-derived
    headline — never offer.name, which is the internal disambiguation label ("… Single Offer") and must
    not leak into customer-facing copy (plans/LANDING_PAGE_DEFAULT_COPY.md)."""
    presentation = offer.get("presentation") or {}
    return str(presentation.get("brand") or presentation.get("headline") or "")


def render_hero_overlays(section: dict[str, Any], offer: dict[str, Any]) -> list[str]:
    """Socialite hero overlays (plans/SOCIALITE_PARITY.md): a positionable brand chip baked into the hero
    image, and a circular profile avatar ("face behind the business") overhanging the bottom-left. Both live
    inside the position:relative .sl-hero-media so toggling the brand never shifts layout."""
    lines: list[str] = []
    if section.get("brand_overlay"):
        brand_text = str(section.get("brand_text") or offer_brand_fallback(offer))
        if brand_text:
            position = str(section.get("brand_position") or "top-right")
            if position not in HERO_BRAND_POSITIONS:
                position = "top-right"
            lines.append(
                f"      <div class=\"sl-hero-brand sl-hero-brand--{position}\">"
                f"<span class=\"sl-hero-brand-dot\"></span>{escape(brand_text)}</div>"
            )
    avatar_url = str(section.get("avatar_url") or "")
    if avatar_url:
        # The avatar carries brand identity, so it's a content image — name it (brand text, else the offer).
        avatar_alt = escape(str(section.get("brand_text") or offer_brand_fallback(offer) or "Brand avatar"))
        lines.append(
            f"      <div class=\"sl-avatar-wrap\"><img class=\"sl-avatar\" src=\"{escape(avatar_url)}\" "
            f"alt=\"{avatar_alt}\" loading=\"lazy\" decoding=\"async\"></div>"
        )
    return lines


# Fallback "no image" illustration (an open box with a 0 badge) for a product/service that has none. Inlined as a
# base64 SVG data-URI so it needs no hosted asset and stays crisp at any size. It's a UI fallback ONLY — never fed
# into Product JSON-LD / og:image / SEO image signals (those read product["images"] directly, which we don't touch),
# so a placeholder can never masquerade as a real product photo to a crawler. It exists mainly so a listicle
# carousel keeps one hero slide PER product even when a product has no image, so the swipe→tier index sync holds
# (plans/LANDING_CAROUSEL_FIXES.md). Drop a real .svg in and swap this string to change the artwork.
_PLACEHOLDER_IMAGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" role="img" aria-label="No image available">'
    '<ellipse cx="200" cy="352" rx="132" ry="22" fill="#EEF3F6" stroke="#CBD9E6" stroke-width="3"/>'
    '<g fill="none" stroke="#FDC42B" stroke-width="9" stroke-linecap="round">'
    '<path d="M52 232 H104"/><path d="M40 268 a14 14 0 0 1 14 -14 H92"/>'
    '<path d="M300 176 H344"/><path d="M312 214 a14 14 0 0 0 14 14 H352"/></g>'
    '<polygon points="120,220 200,260 200,340 120,300" fill="#4FC07D"/>'
    '<polygon points="200,260 280,220 280,300 200,340" fill="#2E8F79"/>'
    '<polygon points="120,220 200,180 280,220 200,260" fill="#1C6F63"/>'
    '<polygon points="120,220 200,180 168,120 88,160" fill="#5FCB8E"/>'
    '<polygon points="200,180 280,220 300,150 214,110" fill="#17756A"/>'
    '<polygon points="140,286 172,302 172,326 140,310" fill="#FFFFFF"/>'
    '<circle cx="92" cy="178" r="38" fill="#EE6A2C"/>'
    '<text x="92" y="194" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" '
    'font-size="46" font-weight="700" fill="#FFFFFF">0</text>'
    '</svg>'
)
PLACEHOLDER_IMAGE = "data:image/svg+xml;base64," + base64.b64encode(_PLACEHOLDER_IMAGE_SVG.encode("utf-8")).decode("ascii")


def render_hero_media(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    product = first_offer_product(offer, products_by_id)
    if derived_offer_type(offer) == "listicle":
        # A listicle's hero carousel IS the offer's items — one slide per item, offer-driven so it can never fall
        # out of sync with a manually-edited field (plans, ConversionContext direction). Keep EVERY item's slide
        # (a "no image" placeholder for image-less ones) so the slide count matches the product count and the
        # swipe→tier index sync can't skip a product (plans/LANDING_CAROUSEL_FIXES.md).
        images = [slide["image"] or PLACEHOLDER_IMAGE for slide in listicle_slides(offer, products_by_id, services_by_id or {})]
    else:
        images = hero_media_images(section, offer, product)
        if not images:
            service_image = first_offer_service_image(offer, services_by_id or {})
            if service_image:
                images = [service_image]
    if not images:
        return ""
    alt = localized_alt(str(product.get("name") or offer.get("name") or "Product image"))
    section_id = escape(str(section.get("id", "hero-media")))
    autoplay = bool(section.get("autoplay"))
    overlays = render_hero_overlays(section, offer)
    media_class = "sl-hero-media" + (" has-avatar" if section.get("avatar_url") else "")
    slides = [
        f"        <div class=\"sl-hero-slide\">{render_media_slide(url, alt, autoplay=autoplay, eager=(index == 0))}</div>"
        for index, url in enumerate(images)
    ]
    # A <figcaption> carrying NAP on local-business heroes (SEO: crawlers weight text around an image).
    caption = local_business_caption()
    caption_html = f"        <figcaption class=\"sl-hero-caption\">{escape(caption)}</figcaption>" if caption else ""
    # A single image needs no carousel chrome.
    if len(images) == 1:
        return "\n".join([
            f"    <section class=\"{media_class}\" data-section-id=\"{section_id}\" data-section-type=\"hero_media\" data-media-count=\"1\">",
            "      <figure class=\"sl-hero-figure\">",
            "        <div class=\"sl-hero-track\">",
            *slides,
            "        </div>",
            caption_html,
            "      </figure>",
            *overlays,
            "    </section>",
        ])
    # Multiple images -> a swipeable carousel with prev/next arrows, a counter, and dots.
    dots = [
        f"        <span class=\"sl-hero-dot{' is-active' if index == 0 else ''}\" data-hero-dot data-index=\"{index}\"></span>"
        for index in range(len(images))
    ]
    return "\n".join([
        f"    <section class=\"{media_class} sl-hero-carousel\" data-section-id=\"{section_id}\" data-section-type=\"hero_media\" data-media-count=\"{len(images)}\" data-hero-carousel>",
        "      <figure class=\"sl-hero-figure\">",
        "      <div class=\"sl-hero-track\" data-hero-track>",
        *slides,
        "      </div>",
        "      <button class=\"sl-hero-nav sl-hero-prev\" type=\"button\" data-hero-prev aria-label=\"Previous image\">‹</button>",
        "      <button class=\"sl-hero-nav sl-hero-next\" type=\"button\" data-hero-next aria-label=\"Next image\">›</button>",
        f"      <span class=\"sl-hero-counter\" data-hero-counter>1 / {len(images)}</span>",
        "      <div class=\"sl-hero-dots\">",
        *dots,
        "      </div>",
        caption_html,
        "      </figure>",
        *overlays,
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
    if offer_uses_grouped_item_media(offer):
        first = first_image(product)
        return [first] if first else []
    return product_images


def offer_uses_grouped_item_media(offer: dict[str, Any]) -> bool:
    items = stage_opportunities(offer, STAGE_LANDING)
    return len(items) > 1 or any(item.get("selectable_prices") for item in items if isinstance(item, dict))


def render_headline(section: dict[str, Any]) -> str:
    # heading_role: h1 — a standalone headline section is the page's main title (mutually exclusive with hero).
    return "\n".join([
        f"    <section class=\"sl-headline\" data-section-id=\"{escape(str(section.get('id', 'headline')))}\" data-section-type=\"headline\">",
        f"      <h1>{render_headline_markup(section.get('text') or '')}</h1>",
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
    badges = [
        badge
        for badge in section.get("badges") or []
        if badge.get("enabled") is not False and badge.get("label")
    ]
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


def _first_target_copy(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """The first landing target's (headline, subheadline) for SEEDING a dynamic hero — the same product
    name/description fallback the conversion payload uses, so the server-rendered hero matches convTargets[0]
    and the island's per-slide swap is seamless."""
    view = expand_offer(offer, products_by_id, services_by_id or {})
    items = view.get("items") or []
    if not items:
        return "", ""
    product = items[0].get("product") or {}
    return (str(product.get("headline") or product.get("name") or ""),
            str(product.get("subheadline") or product.get("description") or ""))


def render_hero(
    section: dict[str, Any],
    offer: dict[str, Any] | None = None,
    products_by_id: dict[str, dict[str, Any]] | None = None,
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """The hero headline (h1) + subheadline.

    On a LISTICLE the hero always follows the CURRENT carousel product — it inherits each product's own
    name/description, seeded server-side with the first product and swapped per slide by the conversion island
    (data-conversion-bind). A multi-product carousel has no single fixed hero, so any stored hero copy (often
    just an auto-seeded product-name snapshot) is deliberately ignored. Other offer types render the section's
    fixed marketing copy verbatim (plans/CONVERSION_CONTEXT.md, plans/LANDING_CAROUSEL_FIXES.md)."""
    listicle = bool(offer) and derived_offer_type(offer) == "listicle"
    if listicle:
        dyn_headline, dyn_sub = _first_target_copy(offer, products_by_id or {}, services_by_id or {})
        headline_html, headline_attr = (
            (escape(dyn_headline), " data-conversion-bind=\"headline\"") if dyn_headline else ("", ""))
        sub_html, sub_attr = (
            (escape(dyn_sub), " data-conversion-bind=\"subheadline\"") if dyn_sub else ("", ""))
    else:
        explicit_headline = str(section.get("headline") or "").strip()
        explicit_sub = str(section.get("subheadline") or "").strip()
        headline_html, headline_attr = (render_headline_markup(explicit_headline), "") if explicit_headline else ("", "")
        sub_html, sub_attr = (escape(explicit_sub), "") if explicit_sub else ("", "")

    return "\n".join([
        f"    <section class=\"sl-hero\" data-section-id=\"{escape(str(section.get('id', 'hero')))}\" data-section-type=\"hero\">",
        f"      <h1{headline_attr}>{headline_html}</h1>" if headline_html else "",
        f"      <p{sub_attr}>{sub_html}</p>" if sub_html else "",
        "    </section>",
    ])


def render_service_price_card(item, service_id, services_by_id, offer, display_index):
    """A single landing-page price card for a service offer item, sourced from the service's own
    prices[] (the fixed price_id path). Carries data-service-id so checkout resolves the service."""
    service = services_by_id.get(service_id)
    if service is None:
        raise RenderError(f"Service '{service_id}' was not provided for offer '{offer.get('offer_id', '')}'.")
    price = resolve_service_price(service, item.get("price_id")) or {}
    if not is_landing_page_price(price):
        return None
    label = escape(str(item.get("display_label") or price.get("label") or service.get("name") or "Option"))
    amount = int(price.get("unit_amount", 0))
    currency = str(price.get("currency") or "usd")
    checkout_quantity = int(item.get("quantity") or 1)
    price_id = str(price.get("price_id") or "")
    image_url = (service.get("presentation") or {}).get("hero_image_url") or ""
    description = escape(str(price.get("description") or service.get("description") or ""))
    compare_at_unit_amount = price.get("compare_at_unit_amount")
    savings_pct = price.get("discount_pct")
    if not savings_pct and compare_at_unit_amount:
        savings_pct = discount_pct(amount, int(compare_at_unit_amount))
    card_markup = "\n".join([
        f"      <article class=\"sl-price-option\" data-service-id=\"{escape(service_id)}\" data-product-id=\"\" data-price-id=\"{escape(price_id)}\" data-quantity=\"{checkout_quantity}\" data-default=\"true\" data-sale-amount=\"{amount}\" data-regular-amount=\"{int(compare_at_unit_amount) if compare_at_unit_amount else ''}\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
        "        " + responsive_img(image_url, str(service.get("name") or label), sizes=PRICE_OPTION_SIZES) if image_url else "",
        "        <div class=\"sl-price-copy\">",
        f"          <strong>{label}</strong>",
        f"          <p class=\"sl-price-description\">{description}</p>" if description else "",
        "          <div class=\"sl-price-row\">",
        f"            <span class=\"sl-price-amount\" data-price-amount>{escape(format_money(amount, currency))}</span>",
        f"            <span class=\"sl-regular-price\">{escape(format_money(int(compare_at_unit_amount), currency))}</span>" if compare_at_unit_amount else "",
        f"            <span class=\"sl-savings\">Save {int(savings_pct)}%</span>" if savings_pct else "",
        "          </div>",
        "        </div>",
        f"        <input type=\"radio\" name=\"sl-price-{escape(service_id)}\" value=\"{escape(price_id)}\" aria-label=\"{label}, {escape(format_money(amount, currency))}\" checked>",
        "      </article>",
    ])
    return (landing_page_price_sort_key(price, item, display_index), card_markup)


def listicle_slides(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One slide per offer item, priced at the SINGLE-UNIT price (bundles/funnels ignored). On a /sale or
    /flash-sale view the slide swaps to the item's paired context price and carries the matching badge."""
    active_ctx = str(_RENDER_STATE.get("active_price_context") or "standard")
    slides = []
    for item in stage_opportunities(offer, STAGE_LANDING):
        product_id = str(item.get("product_id") or "")
        service_id = str(item.get("service_id") or "")
        if product_id and product_id in products_by_id:
            product = products_by_id[product_id]
            # Resolve the item's single price exactly as expand_offer does (default price first, then the
            # offer's selection) so listicle slides match the builder preview and the conversion payload.
            item_default_price_id = str(item.get("default_price_id") or item.get("price_id") or product.get("default_price_id") or "")
            selectable_ids = [o.get("price_id") for o in item.get("selectable_prices") or []]
            price = single_unit_price(product, selectable_ids or ([item_default_price_id] if item_default_price_id else None), item_default_price_id, active_ctx)
            if not price:
                continue
            compare = int(price.get("compare_at_unit_amount") or price.get("compare_at_amount") or 0)
            slides.append({
                "product_id": product_id, "service_id": "", "price_id": str(price.get("price_id") or ""),
                "name": str(product.get("name") or ""), "description": str(product.get("description") or ""),
                "image": str((product.get("images") or [""])[0] or ""),
                "amount": int(price.get("unit_amount") or 0), "currency": str(price.get("currency") or "usd"),
                "compare_at": compare, "sale_badge": _context_badge_label(str(price.get("context") or "standard")),
            })
        elif service_id and service_id in services_by_id:
            service = services_by_id[service_id]
            svc_price = service.get("price") or (service.get("prices") or [{}])[0]
            slides.append({
                "product_id": "", "service_id": service_id, "price_id": str(item.get("price_id") or ""),
                "name": str(service.get("name") or ""), "description": str(service.get("description") or ""),
                "image": str((service.get("presentation") or {}).get("hero_image_url") or ""),
                "amount": int(svc_price.get("unit_amount") or 0), "currency": str(svc_price.get("currency") or "usd"),
                "compare_at": 0,
            })
    return slides


def render_listicle_carousel(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    page: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
) -> str:
    """Listicle carousel (fixed hero + synced tiers, plans/LANDING_CAROUSEL_FIXES.md). The hero_media image
    carousel is the single image carousel and drives the current product; this section renders EVERY landing
    product's tier selector as a block and shows only the active one — the conversion island toggles them as the
    hero is swiped (conversion:itemChanged). One Add-to-cart adds the SHOWN product at its SELECTED tier to the
    server cart. Handles single- or multi-tier products per slide (each block reuses the single-product selector
    via _item_price_option_cards)."""
    services_by_id = services_by_id or {}
    offer_id = escape(str(offer.get("offer_id") or ""))
    add_label = escape(str(listicle_add_label(offer)))
    blocks: list[str] = []
    display_index = 0
    index = 0
    for item in stage_opportunities(offer, STAGE_LANDING):
        if item.get("service_id"):
            continue  # services aren't cart-checkout-eligible yet (LISTICLE_AND_CART.md L2 deferred)
        product_id = str(item.get("product_id") or "")
        product = products_by_id.get(product_id)
        if product is None:
            continue
        item_cards, display_index = _item_price_option_cards(item, product, offer, display_index)
        if not item_cards:
            continue
        cards_html = [markup for _, markup in sorted(item_cards, key=lambda card: card[0])]
        # No per-product name/description header here: the hero above already shows the CURRENT product's
        # name + description (target-bound, synced to this carousel via conversion:itemChanged), so repeating
        # it above the tier cards was pure duplication (plans/LANDING_CAROUSEL_FIXES.md). Tiers only here.
        blocks.append("\n".join(line for line in [
            f"      <div class=\"sl-listicle-tiers\" data-listicle-tiers data-index=\"{index}\" data-product-id=\"{escape(product_id)}\"{'' if index == 0 else ' hidden'}>",
            "        <div class=\"sl-price-options\">",
            *cards_html,
            "        </div>",
            "      </div>",
        ] if line))
        index += 1
    if not blocks:
        return ""
    # Server-cart wiring (L2): the island posts to {api_base}/cart with the page's tenant + this offer.
    cart_tenant_id = escape(str(page.get("tenant_id") or offer.get("tenant_id") or ""))
    cart_endpoint = escape(f"{str(api_base_url or '').rstrip('/')}/cart") if api_base_url else ""
    # Post-purchase routing (§6): when the page has a post-checkout funnel, the cart's Checkout lands on
    # {api}/pages/{page_id}/post-checkout/next (like the single-product CTA), not back on the landing page.
    cart_page_id = escape(str(page.get("page_id") or ""))
    cart_has_post_checkout = "true" if page.get("post_checkout") else "false"
    cart_mode = "live" if str(offer.get("stripe_mode") or "").strip().lower() == "live" else "test"
    return "\n".join(part for part in [
        f"    <section class=\"sl-listicle\" data-section-type=\"offer_price_selector\" data-conversion-section=\"offer_selector\" data-listicle data-offer-id=\"{offer_id}\" data-tenant-id=\"{cart_tenant_id}\" data-cart-endpoint=\"{cart_endpoint}\" data-page-id=\"{cart_page_id}\" data-stripe-mode=\"{cart_mode}\" data-has-post-checkout=\"{cart_has_post_checkout}\">",
        *blocks,
        # BNPL messaging (P3.5): follows the shown product's selected tier via conversion:itemChanged (below).
        render_bnpl_messaging_div(),
        f"      <button class=\"sl-cta sl-listicle-add\" type=\"button\" data-listicle-add>{add_label}</button>",
        "    </section>",
    ] if part != "")


def _item_price_option_cards(
    item: dict[str, Any], product: dict[str, Any], offer: dict[str, Any], display_index: int
) -> tuple[list[tuple[tuple[int, int, int], str]], int]:
    """The `sl-price-option` radio cards for ONE landing item's tiers — the exact markup the single-product
    selector renders. Shared so a listicle carousel slide reuses the tier selector verbatim (plans/
    LANDING_CAROUSEL_FIXES.md). Returns (cards, next_display_index); each card is (sort_key, markup)."""
    product_id = item.get("product_id", "")
    # Same rule as the CTA: if the offer's default is a price this page doesn't show (upsell/downsell/
    # order bump), the first displayed price is the selected one — otherwise no card renders as checked.
    default_price_id = landing_page_default_price_id(item, product)
    cards: list[tuple[tuple[int, int, int], str]] = []
    for option in item_price_options(item):
        price = find_price(product, option.get("price_id", ""))
        if not is_landing_page_price(price):
            continue
        # A selectable option carries its own label; a synthesized fixed option has none, so fall back
        # to the product name rather than a generic "Option".
        label = escape(str(option.get("label") or price.get("label") or product.get("name") or "Option"))
        # Sale / Flash-Sale context view: swap this tier to its paired sale price (same quantity), badge
        # it, and strike through the Standard price. `default_attr` stays keyed on the STANDARD tier so the
        # same option renders checked. `display_price` drives the amount, price_id, and checkout selection.
        active_ctx = str(_RENDER_STATE.get("active_price_context") or "standard")
        display_price = price
        sale_badge = ""
        context_compare = None
        if active_ctx in ("sale", "flash_sale"):
            paired = paired_context_price(product, price, active_ctx)
            if paired:
                display_price = paired
                sale_badge = "Sale" if active_ctx == "sale" else "\U0001F525 Flash Sale"
                context_compare = int(price.get("unit_amount") or 0)
        badge = escape(sale_badge or str(option.get("badge") or ""))
        amount = int(display_price.get("unit_amount", 0))
        currency = str(display_price.get("currency") or "usd")
        checkout_quantity = int(item.get("quantity") or 1)
        default_attr = "true" if price.get("price_id") == default_price_id else "false"
        image_url = price_image(product, display_price, option) or PLACEHOLDER_IMAGE  # "no image" fallback thumb
        description = escape(str(option.get("description") or price.get("description") or product.get("description") or ""))
        compare_at_unit_amount = context_compare if context_compare is not None else display_price.get("compare_at_unit_amount")
        savings_pct = option.get("display_discount_pct") or display_price.get("discount_pct")
        if context_compare is not None:
            savings_pct = discount_pct(amount, context_compare)  # Sale% off the Standard price
        if not savings_pct and compare_at_unit_amount:
            savings_pct = discount_pct(amount, int(compare_at_unit_amount))
        # Swapped to a sale/flash price: carry the Standard fallback so the client-side flash/expiry logic
        # (plans/SALES_FUNNELS.md P1b-2) can revert this card to Standard in the upcoming/ended states.
        revert_attrs = (
            f" data-standard-price-id=\"{escape(str(price.get('price_id', '')))}\" data-standard-amount=\"{int(price.get('unit_amount') or 0)}\""
            if context_compare is not None else ""
        )
        card_markup = "\n".join([
            f"      <article class=\"sl-price-option\" data-product-id=\"{escape(str(product_id))}\" data-price-id=\"{escape(str(display_price.get('price_id', '')))}\"{revert_attrs} data-quantity=\"{checkout_quantity}\" data-default=\"{default_attr}\" data-sale-amount=\"{amount}\" data-regular-amount=\"{int(compare_at_unit_amount) if compare_at_unit_amount else ''}\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
            "        " + responsive_img(image_url, str(product.get("name") or label), sizes=PRICE_OPTION_SIZES) if image_url else "",
            "        <div class=\"sl-price-copy\">",
            f"          <span class=\"sl-badge\">{badge}</span>" if badge else "",
            f"          <strong>{label}</strong>",
            f"          <p class=\"sl-price-description\">{description}</p>" if description else "",
            "          <div class=\"sl-price-row\">",
            f"            <span class=\"sl-price-amount\" data-price-amount>{escape(format_money(amount, currency))}</span>",
            f"            <span class=\"sl-regular-price\">{escape(format_money(int(compare_at_unit_amount), currency))}</span>" if compare_at_unit_amount else "",
            f"            <span class=\"sl-savings\">Save {int(savings_pct)}%</span>" if savings_pct else "",
            "          </div>",
            "        </div>",
            f"        <input type=\"radio\" name=\"sl-price-{escape(product_id)}\" value=\"{escape(str(display_price.get('price_id', '')))}\" aria-label=\"{label}, {escape(format_money(amount, currency))}\" {'checked' if default_attr == 'true' else ''}>",
            "      </article>",
        ])
        cards.append((landing_page_price_sort_key(price, option, display_index), card_markup))
        display_index += 1
    return cards, display_index


def render_offer_price_selector(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    services_by_id = services_by_id or {}
    cards: list[tuple[tuple[int, int, int], str]] = []
    display_index = 0
    for item in stage_opportunities(offer, STAGE_LANDING):
        service_id = item.get("service_id", "")
        if service_id:
            card = render_service_price_card(item, service_id, services_by_id, offer, display_index)
            if card is not None:
                cards.append(card)
                display_index += 1
            continue
        product_id = item.get("product_id", "")
        product = products_by_id.get(product_id)
        if product is None:
            raise RenderError(f"Product '{product_id}' was not provided for offer '{offer.get('offer_id', '')}'.")
        item_cards, display_index = _item_price_option_cards(item, product, offer, display_index)
        cards.extend(item_cards)
    return "\n".join(part for part in [
        "    <section class=\"sl-price-selector\" data-section-type=\"offer_price_selector\">",
        "      <div class=\"sl-price-options\">",
        *(card for _, card in sorted(cards, key=lambda item: item[0])),
        "      </div>",
        render_bnpl_messaging_div(),
        "    </section>",
    ] if part != "")


def render_bnpl_messaging_div() -> str:
    """Mount point for Stripe's Payment Method Messaging Element, placed below the price stack (P3,
    plans/BNPL_PAYMENT_METHODS.md). Empty unless the render state carries a publishable key + a displayed amount
    + supported methods; sets `_active` so render_bnpl_messaging_scripts emits the matching Stripe.js init."""
    if not (_RENDER_BNPL.get("publishable_key")
            and int(_RENDER_BNPL.get("amount") or 0) > 0
            and _RENDER_BNPL.get("payment_method_types")):
        return ""
    _RENDER_BNPL["_active"] = True
    return "      <div class=\"sl-bnpl-message\" id=\"sl-bnpl-message\"></div>"


def render_bnpl_messaging_scripts() -> list[str]:
    """Stripe.js + the inline init for the Payment Method Messaging Element, emitted at the end of <body> only
    when the messaging div was rendered. Keeps hosted Checkout — this is a messaging widget, not Elements
    checkout. Follows the price selector: when the buyer picks a different tier, the element is re-created with
    that tier's amount (data-sale-amount on the selected .sl-price-option) so the installment figure updates.
    Fails silent (try/catch) so a Stripe.js hiccup never breaks the page."""
    if not _RENDER_BNPL.get("_active"):
        return []
    pk = json.dumps(str(_RENDER_BNPL.get("publishable_key") or ""))
    amount = int(_RENDER_BNPL.get("amount") or 0)
    currency = json.dumps(str(_RENDER_BNPL.get("currency") or "usd").upper())
    methods = json.dumps(list(_RENDER_BNPL.get("payment_method_types") or []))
    country = str(_RENDER_BNPL.get("country") or "").strip().upper()
    return [
        "  <script src=\"https://js.stripe.com/v3/\"></script>",
        "  <script>",
        "  (function(){",
        "    var mount = document.getElementById('sl-bnpl-message');",
        "    if (!mount || !window.Stripe) return;",
        "    try {",
        f"      var stripe = Stripe({pk});",
        "      // The element renders in a Stripe iframe the page CSS can't reach, and the 'See plans' modal it",
        "      // opens is always WHITE. So fix a light-card scheme (dark text on a white background) instead of",
        "      // mirroring the page's own text color — the latter made the modal's text invisible on white. The",
        "      // .sl-bnpl-message div carries the matching light background so the inline widget reads on dark pages.",
        "      var _root = getComputedStyle(document.documentElement);",
        "      var _appv = { colorText: '#30313d', colorTextSecondary: '#4b5563', colorBackground: '#ffffff' };",
        "      var _font = (_root.getPropertyValue('--sl-font-body') || '').trim(); if (_font) _appv.fontFamily = _font;",
        "      var elements = stripe.elements({ appearance: { variables: _appv } });",
        f"      var base = {{ currency: {currency}, paymentMethodTypes: {methods} }};",
        (f"      base.countryCode = {json.dumps(country)};" if country else ""),
        "      var el = null, current = 0;",
        "      function render(amount){",
        "        amount = Number(amount) || 0;",
        "        if (amount <= 0 || amount === current) return;",
        "        current = amount;",
        "        try {",
        "          if (el && el.destroy) el.destroy();",
        "          el = elements.create('paymentMethodMessaging', Object.assign({ amount: amount }, base));",
        "          el.mount('#sl-bnpl-message');",
        "        } catch (e) {}",
        "      }",
        "      function cardAmount(card){ return card ? Number(card.getAttribute('data-sale-amount')) : 0; }",
        "      function checkedAmount(root){",
        "        if (!root) return 0;",
        "        var checked = root.querySelector('.sl-price-option input[type=\"radio\"]:checked');",
        "        var card = checked ? checked.closest('.sl-price-option') : root.querySelector('.sl-price-option');",
        "        return cardAmount(card);",
        "      }",
        "      // Listicle carousels render one hidden tier block per product; single/bundle render one options set.",
        "      var isListicle = !!document.querySelector('.sl-listicle-tiers');",
        "      function currentAmount(){",
        "        var visible = document.querySelector('.sl-listicle-tiers:not([hidden])');",
        "        return checkedAmount(visible || document.querySelector('.sl-price-selector, .sl-listicle') || document.body);",
        "      }",
        "      // Once the shopper adds items, finance the running CART TOTAL; before that, anchor on the shown item.",
        "      // The cart island keeps window.slConversion.cartTotal current, so read it LIVE on every re-price",
        "      // rather than trusting an event to reach us at the right moment.",
        "      function liveCartTotal(){ return (window.slConversion && Number(window.slConversion.cartTotal) > 0) ? Number(window.slConversion.cartTotal) : 0; }",
        "      function amountFor(specific){ var ct = liveCartTotal(); return ct > 0 ? ct : (specific || currentAmount()); }",
        f"      render(amountFor(currentAmount() || {amount}));",
        "      // Selection changed via the event bus. For a listicle the index is the CAROUSEL product; for",
        "      // single/bundle it's a tier CARD in the sole options set. (amountFor still prefers the cart total.)",
        "      if (window.slConversion && typeof window.slConversion.on === 'function') {",
        "        window.slConversion.on('conversion:cartChanged', function(){ render(amountFor(0)); });",
        "        window.slConversion.on('conversion:itemChanged', function(e){",
        "          var i = e && typeof e.index === 'number' ? e.index : -1;",
        "          if (isListicle) {",
        "            var block = i >= 0 ? document.querySelector('.sl-listicle-tiers[data-index=\"' + i + '\"]') : null;",
        "            render(amountFor(checkedAmount(block)));",
        "          } else {",
        "            var cards = document.querySelectorAll('.sl-price-option');",
        "            render(amountFor((i >= 0 && cards[i]) ? cardAmount(cards[i]) : 0));",
        "          }",
        "        });",
        "      }",
        "      // Bulletproof cart trigger: re-price whenever the mini-cart DOM changes (add/remove/hydrate),",
        "      // independent of whether the cartChanged event reached us. The mini-cart demonstrably re-renders.",
        "      var mcEl = document.querySelector('[data-minicart]');",
        "      if (mcEl && window.MutationObserver) {",
        "        new MutationObserver(function(){ render(amountFor(0)); }).observe(mcEl, { childList: true, subtree: true, characterData: true, attributes: true });",
        "      }",
        "      // Fallbacks: a direct tier click (reads the clicked card) + keyboard-driven native change.",
        "      var scope = document.querySelector('.sl-listicle') || document.querySelector('.sl-price-selector');",
        "      if (scope) {",
        "        scope.addEventListener('click', function(ev){",
        "          var card = ev.target && ev.target.closest && ev.target.closest('.sl-price-option');",
        "          if (card) render(amountFor(cardAmount(card)));",
        "        });",
        "        scope.addEventListener('change', function(){ render(amountFor(0)); });",
        "      }",
        "    } catch (e) {}",
        "  })();",
        "  </script>",
    ]


def is_landing_page_price(price: dict[str, Any]) -> bool:
    context = str(price.get("context") or "standard").strip().lower()
    return context in LANDING_PAGE_PRICE_CONTEXTS


def _offer_has_price_context(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]], context: str) -> bool:
    """Whether any product the offer sells has a price in `context` — gates the /sale //flash-sale fallback."""
    for item in stage_opportunities(offer, STAGE_LANDING):
        for price in (products_by_id.get(str(item.get("product_id") or "")) or {}).get("prices") or []:
            if str(price.get("context") or "standard") == context:
                return True
    return False


def _context_badge_label(context: str) -> str:
    """The badge shown on a card whose price is in a sale/flash context. Empty for standard."""
    ctx = str(context or "standard")
    if ctx == "sale":
        return "Sale"
    if ctx == "flash_sale":
        return "\U0001F525 Flash Sale"
    return ""


def paired_context_price(product: dict[str, Any], standard_price: dict[str, Any], context: str) -> dict[str, Any] | None:
    """The product's price in `context` (sale/flash_sale) paired to a displayed standard tier by matching
    `quantity` (plans/SALES_FUNNELS.md — "pair by quantity + context"). None when no such tier exists."""
    qty = int(standard_price.get("quantity") or 1)
    for price in product.get("prices") or []:
        if str(price.get("context") or "standard") == context and int(price.get("quantity") or 1) == qty:
            return price
    return None


def landing_page_default_price_id(item: dict[str, Any], product: dict[str, Any]) -> str:
    """The price the LANDING PAGE treats as selected for an item.

    An offer's `default_price_id` may legitimately point at an upsell / downsell / order-bump price — those
    belong to the post-checkout flow, not to this page. is_landing_page_price() already keeps them out of
    the rendered cards, so honouring such a default meant the page's selected price was one no card showed:
    the CTA advertised the upsell amount and no card rendered as checked. The landing page must only ever
    resolve to a price it actually displays, so fall back to the first displayed price.
    """
    displayed = [
        str(price.get("price_id") or "")
        for option in item_price_options(item)
        if is_landing_page_price(price := find_price(product, option.get("price_id", "")))
    ]
    default_price_id = str(item.get("default_price_id") or "")
    if default_price_id in displayed:
        return default_price_id
    return displayed[0] if displayed else default_price_id


def landing_page_selected_prices(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None,
) -> dict[str, str]:
    """product_id -> the price this page resolves to, for resolve_offer.

    Scoped to rendering on purpose: resolve_offer is shared with checkout and the upsell handler, which
    legitimately resolve upsell-context prices. The correction belongs to the landing page, not to pricing.
    An explicit caller selection always wins.
    """
    resolved: dict[str, str] = dict(selected_prices or {})
    for item in stage_opportunities(offer, STAGE_LANDING):
        product_id = str(item.get("product_id") or "")
        if not product_id or product_id in resolved or not item.get("selectable_prices"):
            continue
        product = products_by_id.get(product_id)
        if product is None:
            continue
        try:
            price_id = landing_page_default_price_id(item, product)
        except PricingError:
            continue  # a price the offer references is gone; resolve_offer will report it properly
        if price_id:
            resolved[product_id] = price_id
    return resolved


def item_price_options(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The price options a product offer item exposes on the page. A 'selectable' item lists them
    explicitly; a 'fixed' item (schema: price_id + quantity, no selector) stores a single price — normalize
    it to a one-entry option list so it still renders a price card and emits Product structured data.
    Both shapes are valid per validate_offer_document; only the renderer had ignored the fixed one."""
    options = item.get("selectable_prices")
    if options:
        return list(options)
    price_id = item.get("price_id")
    if price_id:
        return [{"price_id": str(price_id), "quantity": item.get("quantity") or 1}]
    return []


def landing_page_offer_prices(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every price the page actually SHOWS, in display order — the same set render_offer_price_selector
    paints, using the same item.selectable_prices + is_landing_page_price filter.

    Structured data must never advertise a price the page doesn't display: Google requires marked-up prices
    to match visible content, and a product can carry prices this page never shows (an `upsell`-context
    price, say). Deriving JSON-LD from here rather than from product.prices is what keeps the two honest.
    """
    services_by_id = services_by_id or {}
    prices: list[dict[str, Any]] = []
    for item in stage_opportunities(offer, STAGE_LANDING):
        service_id = str(item.get("service_id") or "")
        if service_id:
            service = services_by_id.get(service_id)
            if not service:
                continue
            svc_price = dict(service.get("price") or (service.get("prices") or [{}])[0])
            amount = int(svc_price.get("unit_amount") or 0)
            if amount:
                prices.append({"unit_amount": amount, "currency": str(svc_price.get("currency") or "usd")})
            continue
        product = products_by_id.get(str(item.get("product_id") or ""))
        if product is None:
            continue
        for option in item_price_options(item):
            price = find_price(product, option.get("price_id", ""))
            if not is_landing_page_price(price):
                continue
            prices.append({
                "unit_amount": int(price.get("unit_amount") or 0),
                "currency": str(price.get("currency") or "usd"),
            })
    return prices


_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def heading_outline_warnings(html: str) -> list[str]:
    """Page-health checks on the rendered document outline (plans/SEMANTIC_HTML.md, the quality baseline from
    plans/LANDING_PAGE_GOAL_COMPOSITION.md). Warnings, never gates — a correct outline (one H1, ordered
    H2/H3, no empty or skipped levels) is foundational for SEO, accessibility, and LLM parsing, and this
    catches regressions the renderer's by-construction guarantees don't.

    Validates the visible body only: `<head>` (meta/JSON-LD) carries no headings.
    """
    body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
    headings = [
        (int(level), _TAG_RE.sub("", text).strip())
        for level, text in _HEADING_RE.findall(body)
    ]
    warnings: list[str] = []

    h1_count = sum(1 for level, _ in headings if level == 1)
    if h1_count == 0:
        warnings.append("The page has no main heading (H1). The hero headline should be the page's single H1.")
    elif h1_count > 1:
        warnings.append(f"The page has {h1_count} main headings (H1); a page should have exactly one.")

    if any(not text for _, text in headings):
        warnings.append("The page has an empty heading. Every heading should have text.")

    # No skipped levels: a heading may go one level deeper than the previous at most (H2 then H3, never H2
    # then H4). Going shallower is always fine (closing a subsection).
    previous = 0
    for level, _ in headings:
        if previous and level > previous + 1:
            warnings.append(
                f"The heading order skips from H{previous} to H{level}. "
                f"Add an H{previous + 1} section, or the outline has a gap."
            )
            break
        previous = level

    return warnings


_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def accessibility_warnings(html: str) -> list[str]:
    """Accessibility checks on the rendered body (the quality baseline, plans/LANDING_PAGE_GOAL_COMPOSITION.md
    Phase 4). Warnings, never gates.

    Content images need descriptive alt text — screen readers announce it, and Google reads it. A genuinely
    decorative image opts out the accessible way, with `alt=""` PLUS `aria-hidden="true"` or
    `role="presentation"`; those are skipped. Everything else with a missing or empty alt is flagged. The
    renderer fills alt from offer/product data, so this mostly catches regressions and tenant-data edge cases.
    """
    body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
    missing = 0
    for tag in _IMG_RE.findall(body):
        if re.search(r'\baria-hidden="true"', tag, re.IGNORECASE) or re.search(r'\brole="presentation"', tag, re.IGNORECASE):
            continue  # deliberately decorative — correctly excluded from the accessibility tree
        alt = re.search(r'\balt="([^"]*)"', tag, re.IGNORECASE)
        if alt is None or not alt.group(1).strip():
            missing += 1
    if missing:
        noun = "image is" if missing == 1 else "images are"
        return [f"{missing} {noun} missing alt text. Describe each image so screen readers and search engines can use it."]
    return []


THIN_CONTENT_MIN_WORDS = 150

# Non-content chrome stripped before counting words: scripts/styles, and the boilerplate regions identical
# across every tenant/product (breadcrumb, legal footer, minicart). What's left is the page's own content.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_CHROME_BLOCK_RE = re.compile(
    r'<header class="sl-siteheader".*?</header>'
    r'|<nav class="sl-breadcrumb".*?</nav>'
    r'|<nav class="sl-footernav".*?</nav>'
    r'|<footer class="sl-legal".*?</footer>'
    r'|<div class="sl-minicart".*?</div>',
    re.IGNORECASE | re.DOTALL,
)


def indexable_word_count(html: str) -> int:
    """Approximate the page's unique indexable body text for the thin-content gate (SEO-08): strip scripts,
    styles, and cross-tenant chrome (breadcrumb, legal footer, minicart), drop the remaining tags, and count
    words. A floor check, not exact — precise per-tenant boilerplate subtraction and cross-page dedup within a
    Site are later refinements; the threshold already tolerates the trust-badge/CTA text this leaves in."""
    body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
    body = _SCRIPT_STYLE_RE.sub(" ", body)
    body = _CHROME_BLOCK_RE.sub(" ", body)
    text = unescape(_TAG_RE.sub(" ", body))
    return len(text.split())


def thin_content_warnings(html: str) -> list[str]:
    """Builder page-health nudge (SEO-08): a page below the unique-content floor is too thin to index, so tell
    the tenant what to add. Warning, never a gate — publishing is never blocked.

    Phrased CONDITIONALLY on purpose. The thin-content demotion in publishing.py only runs on an already
    indexable artifact — live mode, published, verified custom domain, eligible page_type. A test-mode or
    platform-hosted page is noindex for those reasons regardless of word count, so claiming the word count
    causes it would be false, and adding 200 words would not change anything the tenant can observe."""
    count = indexable_word_count(html)
    if count >= THIN_CONTENT_MIN_WORDS:
        return []
    return [
        f"This page has only about {count} words of unique content (under {THIN_CONTENT_MIN_WORDS}). On a "
        "verified custom domain that is too thin to index, so it would publish as noindex — hidden from "
        "search — to protect your site's ranking. Add a product description, a specifications table, an "
        "FAQ, or condition details to make it eligible."
    ]


def structured_data_warnings(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """What is missing for this page's Product markup to earn a rich result.

    Warnings only, never a gate — the quality baseline is surfaced as nudges, never as a block on publishing
    (plans/LANDING_PAGE_GOAL_COMPOSITION.md). Thin markup isn't invalid, it just gets ignored by Google,
    which is exactly the failure a tenant can't see for themselves.
    """
    warnings: list[str] = []
    prices = landing_page_offer_prices(offer, products_by_id, services_by_id or {})
    if not prices:
        warnings.append("No price is shown on this page, so no Product markup can be emitted.")
        return warnings
    product = first_offer_product(offer, products_by_id)
    if not str(product.get("name") or "").strip():
        warnings.append("The product has no name.")
    if not [image for image in (product.get("images") or []) if image]:
        warnings.append("Add a product image — Google needs one to show a product rich result.")
    if not str(product.get("description") or "").strip():
        warnings.append("Add a product description.")
    if not humanize_category(product.get("product_category")):
        warnings.append("Set a product category.")
    if not str(product.get("condition") or "").strip():
        warnings.append("Set the product condition so the markup can state it.")
    if not str(product.get("sku") or "").strip():
        warnings.append("Add a SKU — the product ID is used as a fallback identifier.")
    return warnings


def _slug_to_label(slug: str) -> str:
    """A readable menu label from a slug when the Site entry carries none: "/" → "Home", "/about-us" → "About
    Us"."""
    if slug in ("", "/"):
        return "Home"
    tail = slug.rstrip("/").rsplit("/", 1)[-1]
    return tail.replace("-", " ").title()


def internal_href(slug: str) -> str:
    """A host-relative link to a Site slug (plans/PLATFORM_HOSTNAME_SERVING.md Slice 2). Emitting `/slug` (and
    `/` for the root) instead of an absolute custom-domain URL lets ONE published artifact navigate correctly on
    the custom domain, the free platform host, and the preview — and fixes the dead-link bug where cards pointed
    at a not-yet-live custom domain."""
    slug = str(slug or "").strip()
    return "/" if slug in ("", "/") else ("/" + slug.lstrip("/"))


def site_nav_items(site: dict[str, Any] | None, menu: str, home_url: str) -> list[dict[str, str]]:
    """Resolve a Site menu (navigation.primary / navigation.footer) into ordered {label, url} items (SEO-13).
    Each slug must exist in Site.pages and be enabled; the label is the page entry's label or a slug-derived
    fallback; the URL is the slug as a host-relative link. Slugs not in pages (or disabled) are skipped."""
    nav = ((site or {}).get("navigation") or {}).get(menu) or []
    pages = (site or {}).get("pages") or {}
    items: list[dict[str, str]] = []
    for slug in nav:
        entry = pages.get(slug)
        if not isinstance(entry, dict) or entry.get("enabled", True) is False or not entry.get("page_id"):
            continue
        label = str(entry.get("label") or "").strip() or _slug_to_label(str(slug))
        items.append({"label": label, "url": internal_href(str(slug))})
    return items


def render_nav_list(items: list[dict[str, str]], *, css_class: str, aria_label: str) -> str:
    """A crawlable menu of real <a> links (SEO-13). "" when there are no items."""
    if not items:
        return ""
    links = "".join(f'<li><a href="{escape(i["url"])}">{escape(i["label"])}</a></li>' for i in items)
    return f'<nav class="{css_class}" aria-label="{escape(aria_label)}"><ul>{links}</ul></nav>'


def render_site_header(*, has_brand_mark: bool = False) -> str:
    """The storefront header: the Organization name linking to the store root (an internal link to the root on
    every page, SEO-13) plus the primary menu. When the page renders its own centered ● Brand mark
    (render_brand_label), the header drops the brand to avoid two competing brand marks and carries the menu
    alone — the brand mark takes over the store-root link. Rendered only when there's a home host; "" on a
    post-checkout page (a Home link would leak the buyer out) or when there's nothing to show."""
    home = _RENDER_STATE.get("home_url") or ""
    if not home or _RENDER_STATE.get("page_type") in NONINDEXABLE_PAGE_TYPES:
        return ""
    primary = render_nav_list(_RENDER_NAV.get("primary") or [], css_class="sl-nav", aria_label="Primary")
    brand = "" if has_brand_mark else str(_RENDER_ORG.get("name") or "").strip()
    if not primary and not brand:
        return ""
    brand_html = f'<a class="sl-brand" href="/">{escape(brand)}</a>' if brand else ""
    return f'  <header class="sl-siteheader">{brand_html}{primary}</header>'


def render_footer_nav() -> str:
    """The footer menu (SEO-13) — secondary crawlable links (about, contact, policies) back into the Site."""
    return render_nav_list(_RENDER_NAV.get("footer") or [], css_class="sl-footernav", aria_label="Footer")


def breadcrumb_leaf_name(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    """The current page's name for the breadcrumb leaf (SEO-11). The page's SUBJECT (Offer Semantic Model P3),
    so the leaf reads the same as the <title>, offer label, and slug: a single product is its own name; a
    bundle is its bundle subject ("Dietary Supplement Bundle"). Single products are unchanged — Product markup
    still names the real product, but the breadcrumb describes the PAGE. "" when nothing usable exists."""
    model = resolve_semantic_model(offer, products_by_id)
    if is_bundle(model):
        return subject_from_model(model).strip()
    product = first_offer_product(offer, products_by_id)
    name = str(product.get("name") or "").strip()
    if name:
        return name
    return headline_plain_text(offer_headline_text(offer, product)).strip()


def breadcrumb_trail(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """The breadcrumb chain for this render (SEO-11): Home → current page. Empty (no breadcrumb) unless the
    page is served on the Site's verified custom domain (a resolvable Home), below the root (the homepage is
    the root), and on a browseable page_type (never a post-checkout page). The trail is deliberately shallow
    until category pages exist (SEO-13); a category level slots in between Home and the leaf then."""
    home = _RENDER_STATE.get("home_url") or ""
    if not home or _RENDER_STATE.get("page_type") in NONINDEXABLE_PAGE_TYPES:
        return []
    canonical = _RENDER_STATE.get("canonical") or ""
    home_root = home.rstrip("/")
    if not canonical.startswith(home_root + "/") or canonical.rstrip("/") == home_root:
        return []  # off-host, or the homepage itself
    leaf = breadcrumb_leaf_name(offer, products_by_id)
    if not leaf:
        return []
    # Each crumb carries an absolute `url` (for the BreadcrumbList JSON-LD `item`, which Google wants absolute)
    # and a host-relative `href` (the visible <a>, so one artifact navigates on any host — Slice 2).
    trail = [{"name": "Home", "url": home, "href": "/"}]
    # Insert the category level when this page's product belongs to a Site category page (SEO-11/13). The
    # trail deepens from Home → Product to Home → Category → Product with no change to callers.
    category = str(first_offer_product(offer, products_by_id).get("product_category") or "")
    category_page = _RENDER_CATEGORY_PAGES.get(category) if category else None
    if category_page and category_page["slug"] != canonical[len(home_root):]:
        label = category_page["label"].strip() or humanize_category(category)
        trail.append({"name": label, "url": home_root + category_page["slug"], "href": internal_href(category_page["slug"])})
    trail.append({"name": leaf, "url": "", "href": ""})
    return trail


def breadcrumb_json_ld(trail: list[dict[str, str]]) -> str:
    """BreadcrumbList JSON-LD matching the visible trail (SEO-11). The final item carries no `item` URL by
    design — it is the current page."""
    if len(trail) < 2:
        return ""
    items = []
    for position, crumb in enumerate(trail, start=1):
        item: dict[str, Any] = {"@type": "ListItem", "position": position, "name": crumb["name"]}
        if crumb.get("url"):
            item["item"] = crumb["url"]
        items.append(item)
    return json_ld_dump({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})


def render_breadcrumb(trail: list[dict[str, str]]) -> str:
    """The visible, crawlable breadcrumb trail (SEO-11/SEO-13). Real <a> links so the crawler follows them;
    the current page is plain text with aria-current."""
    if len(trail) < 2:
        return ""
    crumbs = []
    for crumb in trail:
        label = escape(crumb["name"])
        if crumb.get("url"):
            href = crumb.get("href") or crumb["url"]  # visible link is host-relative; JSON-LD keeps the absolute url
            crumbs.append(f'<li><a href="{escape(href)}">{label}</a></li>')
        else:
            crumbs.append(f'<li aria-current="page">{label}</li>')
    return (
        '  <nav class="sl-breadcrumb" aria-label="Breadcrumb">\n'
        f'    <ol>{"".join(crumbs)}</ol>\n'
        '  </nav>'
    )


def render_structured_data(
    section: dict[str, Any],
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    composed_sections: list[dict[str, Any]],
) -> str:
    """JSON-LD for the page, DERIVED from the offer and the sections the composer actually put on the page.

    Nothing here is hand-entered — that is the point of the goal axis: "SEO" is a mode the goal flips on,
    not a form to fill (plans/LANDING_PAGE_GOAL_COMPOSITION.md). Two deliberate omissions:

    * No AggregateRating. The `rating` element is a number a tenant typed, with no verifiable source.
      Emitting it as review markup would be fabricated structured data — against Google's structured-data
      policies and squarely within the FTC's rule on deceptive ratings. It stays visible-only text until a
      real review source exists (plans/BUSINESS_PROFILE_AND_GBP.md).
    * No LocalBusiness/Service. That needs the canonical Business Profile's NAP, which does not exist yet.
    """
    blocks: list[str] = []
    # Organization + WebSite first: the canonical business entity (plans/SITE_OBJECT.md §2.2) the Product's
    # seller and every other node references by @id. Emitted only when the page has a resolved Site identity.
    origin = canonical_origin()
    organization_ld = organization_json_ld(_RENDER_ORG, origin)
    if organization_ld:
        blocks.append(organization_ld)
        website_ld = website_json_ld(_RENDER_ORG, origin)
        if website_ld:
            blocks.append(website_ld)
    product_ld = product_json_ld(page, offer, products_by_id, services_by_id)
    if product_ld:
        blocks.append(product_ld)
    breadcrumb_ld = breadcrumb_json_ld(breadcrumb_trail(offer, products_by_id))
    if breadcrumb_ld:
        blocks.append(breadcrumb_ld)
    faq_ld = faq_json_ld(composed_sections)
    if faq_ld:
        blocks.append(faq_ld)
    if not blocks:
        return ""
    return "\n".join(
        f"  <script type=\"application/ld+json\">{block}</script>" for block in blocks
    )


def json_ld_dump(payload: dict[str, Any]) -> str:
    """Serialize JSON-LD safely for inlining in a <script>. `</script>` inside a string would close the tag
    early, so escape the sequence rather than trusting the data."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _review_ld(review: dict[str, Any]) -> dict[str, Any]:
    """A schema.org Review node from a stored review (author/rating/body rendered verbatim, same as visible)."""
    node: dict[str, Any] = {
        "@type": "Review",
        "author": {"@type": "Person", "name": str(review.get("author") or "Anonymous")},
        "reviewRating": {"@type": "Rating", "ratingValue": int(review.get("rating") or 0), "bestRating": 5, "worstRating": 1},
    }
    for key, field in (("name", "title"), ("reviewBody", "body"), ("datePublished", "review_date")):
        value = str(review.get(field) or "").strip()
        if value:
            node[key] = value
    return node


def _review_li(review: dict[str, Any]) -> str:
    rating = max(0, min(5, int(review.get("rating") or 0)))
    stars = "★" * rating + "☆" * (5 - rating)
    author = escape(str(review.get("author") or "Anonymous"))
    body = escape(str(review.get("body") or ""))
    title = str(review.get("title") or "").strip()
    date = str(review.get("review_date") or "").strip()
    title_html = f'<strong class="sl-review-title">{escape(title)}</strong> ' if title else ""
    date_html = f'<time class="sl-review-date" datetime="{escape(date)}">{escape(date)}</time>' if date else ""
    return (
        f'<li class="sl-review"><span class="sl-review-stars" aria-label="Rated {rating} of 5">{stars}</span>'
        f'<span class="sl-review-author">{author}</span>{date_html}'
        f'<p class="sl-review-body">{title_html}{body}</p></li>'
    )


def render_reviews_block(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    """The VISIBLE product reviews section — Google requires the review text + author in the initial HTML,
    matching the Product review/aggregateRating JSON-LD exactly. All approved reviews render, low ratings
    included (no cherry-picking). Empty string when the page's product has none."""
    product = first_offer_product(offer, products_by_id)
    reviews = markup_eligible(_RENDER_REVIEWS.get(str(product.get("product_id") or "")) or [])
    if not reviews:
        return ""
    aggregate = aggregate_reviews(reviews)
    summary = ""
    if aggregate:
        count = aggregate["review_count"]
        summary = (f'      <p class="sl-reviews-summary"><span class="sl-reviews-avg">{aggregate["rating_value"]}</span>'
                   f' out of 5 · {count} review{"" if count == 1 else "s"}</p>')
    items = "".join(_review_li(review) for review in reviews)
    return (
        '    <section class="sl-reviews" data-section-type="reviews">\n'
        '      <h2 class="sl-section-heading">Customer reviews</h2>\n'
        f'{summary}\n'
        f'      <ul class="sl-reviews-list">{items}</ul>\n'
        '    </section>'
    )


def render_business_reviews_block() -> str:
    """VISIBLE business-target reviews (what customers say about the store) — trust content only, NO
    AggregateRating markup (self-serving business ratings are suppressed by Google; plans/REVIEWS.md). Renders
    on any page of the business's Site. All approved render; no cherry-picking. Empty when there are none."""
    reviews = markup_eligible(_RENDER_BUSINESS_REVIEWS)
    if not reviews:
        return ""
    items = "".join(_review_li(review) for review in reviews)
    return (
        '    <section class="sl-reviews sl-business-reviews" data-section-type="business_reviews">\n'
        '      <h2 class="sl-section-heading">What our customers say</h2>\n'
        f'      <ul class="sl-reviews-list">{items}</ul>\n'
        '    </section>'
    )


def product_json_ld(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> str:
    """Product + Offer markup for the page.

    A single `Offer` at the page's selected price, not an `AggregateOffer` over the range. The page is a
    merchant listing — a visitor buys one specific price, the one whose card is checked and whose amount the
    CTA advertises. An AggregateOffer describes a range across sellers/variants and gave Google nothing to
    show for a page like this.

    Everything here is stated by the tenant or computed from what the page displays. `itemCondition` comes
    from the product's `condition` field rather than assuming NewCondition: markup is a machine-readable
    claim, and asserting an unstated one is the same mistake as emitting a hand-typed rating.
    """
    prices = landing_page_offer_prices(offer, products_by_id, services_by_id)
    if not prices:
        return ""
    product = first_offer_product(offer, products_by_id)
    # The PRODUCT's name, not the offer's headline. This is Product markup: the offer is a packaging of the
    # product, so a headline like "Creatine Gummies Single Offer" would surface that internal label in a
    # search result. Fall back to the offer only when the product has no name.
    name = str(product.get("name") or "").strip() or str(offer_headline_text(offer, product) or "").strip()
    if not name:
        return ""
    selected = selected_landing_page_price(offer, products_by_id, prices)
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
    }
    images = [seo_image_url(image) for image in (product.get("images") or []) if image]
    if images:
        payload["image"] = images
    description = str(product.get("description") or "").strip()
    if description:
        payload["description"] = description
    # Prefer the tenant's SKU; otherwise fall back to the product id, stripping the internal "local_"
    # prefix so a client-generated id doesn't leak that implementation detail into public markup.
    sku = str(product.get("sku") or "").strip() or re.sub(r"(?i)^local_", "", str(product.get("product_id") or "").strip())
    if sku:
        payload["sku"] = sku
    # Merchant-listing identifiers (SEO-06/07): brand is the manufacturer; mpn/gtin identify the exact model.
    # Omit any empty key — an empty required-ish field invalidates the whole item.
    mpn = str(product.get("mpn") or "").strip()
    if mpn:
        payload["mpn"] = mpn
    gtin = "".join(ch for ch in str(product.get("gtin") or "") if ch.isdigit())
    if gtin:
        payload["gtin"] = gtin
    brand = str(product.get("brand") or "").strip()
    if brand:
        payload["brand"] = {"@type": "Brand", "name": brand}
    category = humanize_category(product.get("product_category"))
    if category:
        payload["category"] = category
    # First-party reviews (plans/REVIEWS.md): aggregateRating + individual Review nodes, from the product's
    # approved, non-GBP reviews only. Never a hand-typed number — this is the honest AggregateRating the
    # renderer previously refused to emit. The visible reviews block renders the same data on-page.
    product_reviews = markup_eligible(_RENDER_REVIEWS.get(str(product.get("product_id") or "")) or [])
    aggregate = aggregate_reviews(product_reviews)
    if aggregate:
        payload["aggregateRating"] = {
            "@type": "AggregateRating", "ratingValue": aggregate["rating_value"],
            "reviewCount": aggregate["review_count"], "bestRating": 5, "worstRating": 1,
        }
        payload["review"] = [_review_ld(review) for review in product_reviews]
    offer_payload: dict[str, Any] = {
        "@type": "Offer",
        # Decimal STRING, not a float (SEO-07/22).
        "price": money_string(selected["unit_amount"]),
        "priceCurrency": str(selected.get("currency") or "usd").upper(),
        "availability": "https://schema.org/InStock",
    }
    canonical = _RENDER_STATE.get("canonical") or ""
    if canonical:
        offer_payload["url"] = canonical
    condition = PRODUCT_CONDITIONS.get(str(product.get("condition") or "").strip().lower())
    if condition:
        offer_payload["itemCondition"] = condition
    # Seller = the responsible business (SEO-22). Prefer the Site's Organization (the single-source identity);
    # its @id resolves to the Organization node this page also emits, so the seller is a real linked entity,
    # not a bare stub. Fall back to the offer's brand when the page has no Site. @id anchors to the canonical
    # origin; omitted rather than dangling when there's no canonical.
    presentation = offer.get("presentation") or {}
    org_name = str(_RENDER_ORG.get("name") or "").strip()
    seller_name = org_name or str(presentation.get("brand") or "").strip()
    if seller_name:
        seller_type = resolve_entity_type(_RENDER_ORG.get("entity_type") or "OnlineStore", _RENDER_ORG.get("business_type") or "") if org_name else "OnlineStore"
        seller: dict[str, Any] = {"@type": seller_type, "name": seller_name}
        origin = canonical_origin()
        if origin:
            seller["@id"] = f"{origin}/#organization"
            seller["url"] = f"{origin}/"
        offer_payload["seller"] = seller
    # The refund policy already rendered on the page, made machine-readable (SEO-07). applicableCountry is
    # interim US until the tenant profile supplies the real country.
    return_policy = merchant_return_policy(offer.get("refund_policy") or product.get("refund_policy") or {})
    if return_policy:
        offer_payload["hasMerchantReturnPolicy"] = return_policy
    payload["offers"] = offer_payload
    return json_ld_dump(payload)


def _postal_address_ld(address: Any) -> dict[str, Any]:
    """A schema.org PostalAddress from the Organization's address, or {} when nothing usable is present."""
    if not isinstance(address, dict):
        return {}
    node: dict[str, Any] = {"@type": "PostalAddress"}
    for source, target in (
        ("street", "streetAddress"), ("locality", "addressLocality"), ("region", "addressRegion"),
        ("postal_code", "postalCode"), ("country", "addressCountry"),
    ):
        value = str(address.get(source) or "").strip()
        if value:
            node[target] = value
    return node if len(node) > 1 else {}


def organization_json_ld(organization: dict[str, Any], origin: str) -> str:
    """The Site's Organization node as a standalone <script> payload (SEO-12). "" without an origin/name."""
    node = organization_node(organization, origin)
    return json_ld_dump(node) if node else ""


def _opening_hours_ld(hours: Any) -> list[dict[str, Any]]:
    """schema.org OpeningHoursSpecification list from the organization's opening_hours (validated upstream).
    dayOfWeek uses full day names, which Google accepts."""
    if not isinstance(hours, list):
        return []
    out: list[dict[str, Any]] = []
    for spec in hours:
        if not isinstance(spec, dict):
            continue
        days = [d for d in (spec.get("days") or []) if isinstance(d, str) and d]
        opens, closes = str(spec.get("opens") or "").strip(), str(spec.get("closes") or "").strip()
        if days and opens and closes:
            out.append({"@type": "OpeningHoursSpecification", "dayOfWeek": days, "opens": opens, "closes": closes})
    return out


def organization_node(organization: dict[str, Any], origin: str, *, with_context: bool = True) -> dict[str, Any]:
    """The Site's Organization node (plans/SITE_OBJECT.md §2.2, SEO-12): the single canonical business entity
    every page references. Anchored at `{origin}/#organization` so the Offer.seller and the WebSite publisher
    resolve to it. Emits only verifiable, tenant-stated fields; {} without an origin or a name. `with_context`
    False when nesting the node inside another (e.g. the profile page's CollectionPage.mainEntity)."""
    name = str((organization or {}).get("name") or "").strip()
    if not origin or not name:
        return {}
    entity_type = resolve_entity_type(organization.get("entity_type") or "", organization.get("business_type") or "")
    payload: dict[str, Any] = {}
    if with_context:
        payload["@context"] = "https://schema.org"
    payload.update({
        "@type": entity_type,
        "@id": f"{origin}/#organization",
        "name": name,
        "url": f"{origin}/",
    })
    legal_name = str(organization.get("legal_name") or "").strip()
    if legal_name:
        payload["legalName"] = legal_name
    description = str(organization.get("description") or "").strip()
    if description:
        payload["description"] = description
    logo = organization.get("logo")
    logo_url = str(logo.get("url") or "").strip() if isinstance(logo, dict) else ""
    if logo_url:
        logo_node: dict[str, Any] = {"@type": "ImageObject", "url": logo_url}
        for dim in ("width", "height"):
            if isinstance(logo.get(dim), int) and logo[dim] > 0:
                logo_node[dim] = logo[dim]
        payload["logo"] = logo_node
    telephone = str(organization.get("telephone") or "").strip()
    if telephone:
        payload["telephone"] = telephone
    email = str(organization.get("email") or "").strip()
    if email:
        payload["email"] = email
    founding_date = str(organization.get("founding_date") or "").strip()
    if founding_date:
        payload["foundingDate"] = founding_date
    address = _postal_address_ld(organization.get("address"))
    if address:
        payload["address"] = address
    area_served = [a.strip() for a in (organization.get("area_served") or []) if isinstance(a, str) and a.strip()]
    if area_served:
        payload["areaServed"] = area_served
    # Local-business signals (Business Profile Phase 1): geo + hours turn a LocalBusiness node into a full
    # local listing; the GBP/Maps URL is the business's own map link (hasMap). All tenant-stated facts.
    geo = organization.get("geo")
    if isinstance(geo, dict):
        lat, lng = geo.get("latitude"), geo.get("longitude")
        if isinstance(lat, (int, float)) and not isinstance(lat, bool) and isinstance(lng, (int, float)) and not isinstance(lng, bool):
            payload["geo"] = {"@type": "GeoCoordinates", "latitude": lat, "longitude": lng}
    opening_hours = _opening_hours_ld(organization.get("opening_hours"))
    if opening_hours:
        payload["openingHoursSpecification"] = opening_hours
    gbp_url = str(organization.get("gbp_url") or "").strip()
    if gbp_url:
        payload["hasMap"] = gbp_url
    # hasOfferCatalog = the categories the store carries (TENANT_PROFILE_REQUIREMENTS §4.4: "brands I carry",
    # not brands I OWN). Derived from the Site's category pages — accurate + verifiable, never hand-asserted.
    catalog_names = sorted({
        (info.get("label") or "").strip() or humanize_category(key)
        for key, info in _RENDER_CATEGORY_PAGES.items() if key
    })
    if catalog_names:
        payload["hasOfferCatalog"] = {
            "@type": "OfferCatalog",
            "name": f"{name} catalog",
            "itemListElement": [{"@type": "OfferCatalog", "name": c} for c in catalog_names],
        }
    # Only OWNERSHIP-VERIFIED profiles emit into sameAs (TENANT_PROFILE_REQUIREMENTS §4.4). An unverified
    # sameAs is an impersonation vector — a tenant could assert any brand's real social profile on our domain.
    # Capped at 6.
    same_as = [str(e.get("url")).strip() for e in (organization.get("same_as") or [])
               if isinstance(e, dict) and e.get("verified") is True and str(e.get("url") or "").strip()][:6]
    if same_as:
        payload["sameAs"] = same_as
    return payload


def website_json_ld(organization: dict[str, Any], origin: str) -> str:
    """The WebSite node (SEO-12) tying the public site to its publishing Organization. Returns "" without an
    origin or an Organization name (the WebSite has nothing to attribute to otherwise)."""
    name = str((organization or {}).get("name") or "").strip()
    if not origin or not name:
        return ""
    return json_ld_dump({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{origin}/#website",
        "url": f"{origin}/",
        "name": name,
        "publisher": {"@id": f"{origin}/#organization"},
    })


def merchant_return_policy(policy: dict[str, Any]) -> dict[str, Any] | None:
    """MerchantReturnPolicy from the page's refund policy (SEO-07). Only emitted when the policy states a
    finite return window; applicableCountry is interim US pending the tenant profile."""
    days = _return_window_days(policy)
    if days <= 0:
        return None
    return {
        "@type": "MerchantReturnPolicy",
        "applicableCountry": "US",
        "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
        "merchantReturnDays": days,
        "returnMethod": "https://schema.org/ReturnByMail",
    }


def selected_landing_page_price(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    """The price the page presents as chosen — the checked card, which the CTA advertises. Falls back to the
    lowest displayed price so markup always quotes something the visitor can see."""
    for item in stage_opportunities(offer, STAGE_LANDING):
        product = products_by_id.get(str(item.get("product_id") or ""))
        if product is None or not item_price_options(item):
            continue
        try:
            price = find_price(product, landing_page_default_price_id(item, product))
        except PricingError:
            continue
        if is_landing_page_price(price):
            return {"unit_amount": int(price.get("unit_amount") or 0), "currency": price.get("currency") or "usd"}
    return min(prices, key=lambda p: int(p["unit_amount"]))


def money_number(unit_amount: int) -> float:
    """Minor units -> a schema.org price. Google accepts a number or a string; a number matches the shape
    that verified as passing. round() keeps 3709 -> 37.09 rather than 37.089999999999996."""
    return round(int(unit_amount) / 100, 2)


def money_string(unit_amount: int) -> str:
    """Minor units -> a decimal price string ("353.97"). plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-07/22: emit
    JSON-LD and og price as a string, not a float — float serialization round-trips badly and the string
    form matches Google's reference examples. No currency symbol, no thousands separator."""
    return f"{int(unit_amount) / 100:.2f}"


def seo_image_url(url: str) -> str:
    """The largest rendition of an image, for structured data.

    Stored URLs point at `small` (640w) because that is what the uploader returns, but Google wants product
    images of at least 1200px to be eligible for rich results. The processor already writes `large` (1920w),
    so rewrite a rendition URL to it. Non-rendition URLs pass through untouched.
    """
    match = _RENDITION_URL_RE.match(str(url or ""))
    if not match:
        return str(url or "")
    return f"{match.group('base')}/large.webp"


def humanize_category(value: Any) -> str:
    """product_category is stored machine-style ("dietary_supplement"); schema.org `category` is read by
    people and crawlers, so emit "Dietary Supplement"."""
    text = str(value or "").strip()
    if not text:
        return ""
    return " ".join(word.capitalize() for word in re.split(r"[_\-\s]+", text) if word)


def offer_headline_text(offer: dict[str, Any], product: dict[str, Any]) -> str:
    presentation = offer.get("presentation") or {}
    return str(presentation.get("headline") or offer.get("name") or product.get("name") or "")


def headline_plain_text(text: Any) -> str:
    """The plain text a headline actually renders as: the same Chicago title-casing render_headline_markup
    applies, with the ** / ^^ highlight delimiters dropped rather than turned into spans.

    Structured data must quote what the visitor sees. render_faq title-cases its questions, so emitting the
    raw stored string would mark up "Is there a money-back guarantee?" while the page shows "Is There a
    Money-Back Guarantee?" — a mismatch between markup and visible content.
    """
    raw = format_headline(str(text or ""))
    return re.sub(r"\*\*(.*?)\*\*|\^\^(.*?)\^\^", lambda m: m.group(1) or m.group(2) or "", raw)


def faq_json_ld(composed_sections: list[dict[str, Any]]) -> str:
    """FAQPage built from the faq section the composer put on the page. Derived from what is actually
    rendered — markup for questions a visitor cannot see would be exactly the mismatch Google penalises."""
    entries = []
    for section in composed_sections:
        if section.get("type") != "faq":
            continue
        for item in section.get("items") or []:
            question = headline_plain_text(item.get("question")).strip()
            answer = str(item.get("answer") or "").strip()
            if question and answer:
                entries.append({
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {"@type": "Answer", "text": answer},
                })
    if not entries:
        return ""
    return json_ld_dump({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entries})


def landing_page_price_quantity(price: dict[str, Any], option: dict[str, Any]) -> int | None:
    raw_quantity = price.get("quantity") or option.get("quantity")
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        quantity = 0
    if quantity > 0:
        return quantity

    label = str(option.get("label") or price.get("label") or "")
    match = re.search(r"\b(\d+)\b", label)
    return int(match.group(1)) if match else None


def landing_page_price_sort_key(price: dict[str, Any], option: dict[str, Any], index: int) -> tuple[int, int, int]:
    quantity = landing_page_price_quantity(price, option)
    if quantity is not None:
        return (0, quantity, index)
    return (1, index, index)


# Intrinsic pixel widths of the renditions the image processor writes for every uploaded asset
# (keyed by the URL size token). These mirror the processor's SIZES table (image-processing
# stack); keep them in sync if that table changes.
IMAGE_RENDITION_WIDTHS = {"thumb": 200, "small": 640, "medium": 1080, "large": 1920, "full": 2560}
_RENDITION_URL_RE = re.compile(r"^(?P<base>.+)/(?:thumb|small|medium|large|full)\.(?:webp|jpe?g|png)$", re.IGNORECASE)


def rendition_base(url: str) -> str | None:
    """The stable base of a processor rendition URL (.../<key>/<size>.<ext> -> .../<key>).

    Every rendition and format of one uploaded asset shares this base and the same aspect ratio,
    so it is the key we store/look up intrinsic dimensions under. Non-rendition URLs return None.
    """
    match = _RENDITION_URL_RE.match(str(url or ""))
    return match.group("base") if match else None


# Render-scoped intrinsic-dimension index, keyed by rendition base -> (width, height). Populated
# once per render_page() from each document's image_dims sidecar and consulted by responsive_img
# so it can emit width/height without threading the map through every section renderer. The render
# path is synchronous and non-reentrant per Lambda invocation, so a module-level index is safe; it
# is set and cleared in render_page()'s try/finally.
_RENDER_DIMS_INDEX: dict[str, tuple[int, int]] = {}


def collect_image_dims(*documents: dict[str, Any] | None) -> dict[str, tuple[int, int]]:
    """Merge the image_dims sidecars of every supplied document into one base -> (w, h) map.

    Keys are globally-unique rendition bases, so merging across page/offer/products/services is
    conflict-free. Malformed entries are skipped — dimensions are advisory, never a render blocker.
    """
    merged: dict[str, tuple[int, int]] = {}
    for document in documents:
        dims = (document or {}).get("image_dims")
        if not isinstance(dims, dict):
            continue
        for key, value in dims.items():
            base = rendition_base(str(key)) or str(key)
            try:
                width, height = int(value[0]), int(value[1])
            except (TypeError, ValueError, IndexError):
                continue
            if width > 0 and height > 0:
                merged[base] = (width, height)
    return merged


def _dims_attrs(url: str, dims: tuple[int, int] | None) -> str:
    """width/height attributes for an <img>, from an explicit override or the render-scoped index.

    The pair encodes the intrinsic aspect ratio; the browser reserves layout space from it (no CLS)
    while CSS still governs the displayed size. Where CSS pins aspect-ratio (object-fit:cover slots)
    the attributes only inform crawlers; where it does not (listicle contain slots) they reserve the
    box. Absent dimensions emit nothing — identical to prior behavior.
    """
    if dims is None:
        # Rendition URLs key by their shared base; external/custom URLs key by the full URL (that is how
        # collect_image_dims normalizes them), so a non-rendition image can still carry dimensions.
        base = rendition_base(url)
        dims = _RENDER_DIMS_INDEX.get(base) if base else _RENDER_DIMS_INDEX.get(url)
    if not dims:
        return ""
    return f' width="{int(dims[0])}" height="{int(dims[1])}"'


def responsive_img(url: str, alt: str, *, sizes: str, eager: bool = False, dims: tuple[int, int] | None = None) -> str:
    """Render an <img> that lets the browser pick the right rendition per slot and DPR.

    When the URL is a processor rendition (.../<key>/<size>.webp) we emit a webp srcset over
    all renditions plus a sizes hint, so a 144px thumbnail no longer downloads the 1080px file.
    Non-rendition URLs (external/custom) fall back to a plain tag but still get lazy loading.
    Always adds loading/decoding; the first hero image opts into eager + high fetch priority
    because it is the LCP candidate. Intrinsic width/height (from the image_dims sidecar, via the
    render-scoped index or an explicit `dims` override) are emitted when known so the browser
    reserves layout space and crawlers learn the dimensions.
    """
    url = str(url or "")
    alt_attr = escape(str(alt or ""))
    loading = "eager" if eager else "lazy"
    priority = ' fetchpriority="high"' if eager else ""
    dims_attrs = _dims_attrs(url, dims)
    match = _RENDITION_URL_RE.match(url)
    if not match:
        return f'<img src="{escape(url)}" alt="{alt_attr}"{dims_attrs} loading="{loading}" decoding="async"{priority}>'
    base = match.group("base")
    srcset = ", ".join(
        f"{escape(f'{base}/{size}.webp')} {width}w"
        for size, width in IMAGE_RENDITION_WIDTHS.items()
    )
    return (
        f'<img src="{escape(f"{base}/medium.webp")}" srcset="{srcset}" sizes="{escape(sizes)}" '
        f'alt="{alt_attr}"{dims_attrs} loading="{loading}" decoding="async"{priority}>'
    )


# Slot widths per image context, used as the srcset `sizes` hint. Hero/content stretch to the
# ~52rem content column (full width on phones); price-option thumbnails are a fixed 9rem.
HERO_MEDIA_SIZES = "(min-width: 52rem) 52rem, 100vw"
CONTENT_BLOCK_SIZES = "(min-width: 52rem) 52rem, 100vw"
# The author photo is a fixed circle, so one modest size covers every viewport.
AUTHOR_PHOTO_SIZES = "220px"
PRICE_OPTION_SIZES = "9rem"


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


def discount_pct(unit_amount: int, compare_at_unit_amount: int) -> int:
    if compare_at_unit_amount <= 0 or unit_amount >= compare_at_unit_amount:
        return 0
    return round((1 - (unit_amount / compare_at_unit_amount)) * 100)


def render_refund_policy(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
) -> str:
    if section.get("enabled") is False:
        return ""
    product = first_offer_product(offer, products_by_id)
    policy = offer.get("refund_policy") or product.get("refund_policy") or {}
    if not policy:
        return ""

    short_label = escape(str(policy.get("short_label") or "Refund policy"))
    full_policy = escape(str(policy.get("full_policy") or ""))
    return_note = escape(refund_policy_return_note(policy))
    applies_to = escape(", ".join(refund_policy_applies_to(offer, products_by_id)))
    return "\n".join([
        f"    <details class=\"sl-refund-policy\" data-section-id=\"{escape(str(section.get('id', 'refund-policy')))}\" data-section-type=\"refund_policy\">",
        f"      <summary>{short_label}</summary>",
        "      <div class=\"sl-refund-policy-body\">",
        f"        <h2>{escape(str(section.get('heading') or 'Refund Policy'))}</h2>",
        f"        <p class=\"sl-refund-policy-applies\">Applies to: {applies_to}</p>" if applies_to else "",
        f"        <p class=\"sl-refund-policy-copy\">{full_policy}</p>" if full_policy else "",
        f"        <p class=\"sl-refund-policy-return\">{return_note}</p>" if return_note else "",
        "      </div>",
        "    </details>",
    ])


def refund_policy_return_note(policy: dict[str, Any]) -> str:
    explicit = policy.get("return_note")
    if isinstance(explicit, str) and explicit:
        return explicit

    return_method = str(policy.get("return_method") or "").lower()
    if "no return" in return_method or "customer keeps" in return_method or "no_return" in return_method:
        return (
            "This item doesn't need to be returned. The customer may keep the item "
            "and dispose of it in a responsible way. The seller may still grant a refund."
        )
    if "return_required" in return_method or "return required" in return_method:
        return "The customer must return the item according to the seller's return instructions before the refund is completed."
    return ""


def refund_policy_applies_to(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for item in stage_opportunities(offer, STAGE_LANDING):
        product = products_by_id.get(item.get("product_id", ""))
        product_name = product.get("name") if product else ""
        for option in item_price_options(item):
            price = find_price(product, option.get("price_id", "")) if product else {}
            if not is_landing_page_price(price):
                continue
            label = option.get("label") or price.get("label")
            labels.append(f"{product_name} - {label}" if product_name and label else str(label or product_name))
    return [label for label in labels if label]


def render_faq(section: dict[str, Any]) -> str:
    items = section.get("items") or []
    # Each question is an <h3> under the section's <h2> heading — keeps the FAQ inside the
    # page heading outline (h1 → h2 section → h3 question) for SEO/a11y (plans/SEMANTIC_HTML.md).
    rendered = [
        "\n".join([
            "      <details>",
            f"        <summary><h3>{render_headline_markup(item.get('question') or '')}</h3></summary>",
            f"        <p>{escape(str(item.get('answer') or ''))}</p>",
            "      </details>",
        ])
        for item in items
    ]
    if not rendered:
        return ""
    heading = str(section.get("heading") or "Frequently Asked Questions")
    return "\n".join([
        f"    <section class=\"sl-faq\" data-section-id=\"{escape(str(section.get('id', 'faq')))}\" data-section-type=\"faq\">",
        f"      <h2 class=\"sl-faq-heading\">{escape(heading)}</h2>",
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
            f"          <h2>{render_headline_markup(block.get('title') or '')}</h2>",
            f"          <p>{escape(str(block.get('text') or ''))}</p>",
            "        </div>",
            "        " + cropped_media(
                responsive_img(image_url, str(block.get("title") or "Content image"), sizes=CONTENT_BLOCK_SIZES),
                block.get("image_crop"), "content_block", "sl-content-media",
            ) if image_url else "",
            "      </article>",
        ]))
    if not rendered:
        return ""
    centered = " sl-content-blocks--centered" if section.get("centered") else ""
    return "\n".join([
        f"    <section class=\"sl-content-blocks{centered}\" data-section-id=\"{escape(str(section.get('id', 'content-blocks')))}\" data-section-type=\"content_block\">",
        *rendered,
        "    </section>",
    ])


def render_featured_price(section: dict[str, Any]) -> str:
    """A prominent, standalone price display: a bordered card with a small label, the big headline price, and
    (when show_savings is on and there is a higher regular price) a struck original + a "You save N%" pill.

    Denormalized — it carries its own amount/currency/compare_at rather than resolving an offer — so it works
    on any page regardless of price context. The upsell page uses it because the upsell price lives in the
    'upsell' context, which the standard offer_price_selector filters out (it only shows 'standard' prices), so
    that selector renders nothing and the amount would otherwise appear only inside the CTA button. Colors come
    from the shared price tokens, so it matches whatever preset the template carries.
    """
    amount = int(section.get("amount") or 0)
    currency = str(section.get("currency") or "usd")
    label = str(section.get("label") or "").strip()
    compare_at = int(section.get("compare_at_amount") or 0)
    pills = ""
    if section.get("show_savings") and compare_at > amount > 0:
        percent = round((compare_at - amount) / compare_at * 100)
        pills = "\n".join([
            "      <div class=\"sl-featured-price-pills\">",
            f"        <span class=\"sl-featured-price-pill sl-featured-price-was\">{escape(format_money(compare_at, currency))}</span>",
            f"        <span class=\"sl-featured-price-pill sl-featured-price-save\">You save {percent}%</span>",
            "      </div>",
        ])
    return "\n".join(line for line in [
        f"    <section class=\"sl-featured-price\" data-section-id=\"{escape(str(section.get('id', 'featured-price')))}\" data-section-type=\"featured_price\" data-fp-compare-at=\"{compare_at}\" data-fp-currency=\"{escape(currency)}\">",
        "      <div class=\"sl-featured-price-card\">",
        (f"        <p class=\"sl-featured-price-label\">{escape(label)}</p>" if label else ""),
        f"        <div class=\"sl-featured-price-amount\">{escape(format_money(amount, currency))}</div>",
        pills,
        "      </div>",
        "    </section>",
    ] if line)


def render_celebration(section: dict[str, Any]) -> str:
    """A CSS-only celebration burst (an animated check mark) atop the thank-you page (SALES_FUNNELS.md P3.5,
    stripe-cart parity). No config — synthesize_thank_you_page emits it only when enabled."""
    return "\n".join([
        f"    <section class=\"sl-celebration\" data-section-id=\"{escape(str(section.get('id', 'celebration')))}\" data-section-type=\"celebration\" aria-hidden=\"true\">",
        "      <div class=\"sl-celebration-mark\">"
        "<svg viewBox=\"0 0 52 52\"><circle class=\"sl-celebration-ring\" cx=\"26\" cy=\"26\" r=\"24\"/>"
        "<path class=\"sl-celebration-check\" d=\"M14 27l7 7 16-16\"/></svg></div>",
        "    </section>",
    ])


def render_next_steps(section: dict[str, Any]) -> str:
    """The "What's Next?" cards on the thank-you page — a titled grid of {icon, title, desc} cards."""
    cards = [c for c in (section.get("cards") or []) if isinstance(c, dict) and (c.get("title") or c.get("desc"))]
    if not cards:
        return ""
    title = str(section.get("title") or "")
    card_html = []
    for card in cards:
        icon = str(card.get("icon") or "").strip()
        icon_html = f"<span class=\"sl-next-step-icon\">{escape(icon)}</span>" if icon and icon != "—" else ""
        card_html.append("\n".join(line for line in [
            "      <article class=\"sl-next-step\">",
            f"        {icon_html}" if icon_html else "",
            f"        <strong>{escape(str(card.get('title') or ''))}</strong>",
            f"        <p>{escape(str(card.get('desc') or ''))}</p>",
            "      </article>",
        ] if line))
    return "\n".join(line for line in [
        f"    <section class=\"sl-next-steps\" data-section-id=\"{escape(str(section.get('id', 'next-steps')))}\" data-section-type=\"next_steps\">",
        (f"      <h2 class=\"sl-next-steps-title\">{render_headline_markup(title)}</h2>" if title else ""),
        "      <div class=\"sl-next-steps-grid\">",
        *card_html,
        "      </div>",
        "    </section>",
    ] if line)


def render_thank_you_footer(section: dict[str, Any]) -> str:
    """The thank-you footer: an optional headline + message, an optional download button, and an optional
    'Back to Home' link (to the Site home when there is one, else '/')."""
    headline = str(section.get("headline") or "")
    message = str(section.get("message") or "")
    home_label = str(section.get("home_button_text") or "")
    download_label = str(section.get("download_button_text") or "")
    download_url = str(section.get("download_url") or "")
    home_url = "/"  # host-relative store root (Slice 2) — works on the platform host and the custom domain alike
    content = []
    if headline:
        content.append(f"      <h2>{render_headline_markup(headline)}</h2>")
    if message:
        content.append(f"      <p>{escape(message)}</p>")
    if download_label and download_url:
        content.append(f"      <a class=\"sl-cta sl-ty-download\" href=\"{escape(download_url)}\">{escape(download_label)}</a>")
    if home_label:
        content.append(f"      <a class=\"sl-ty-home\" href=\"{escape(str(home_url))}\">{escape(home_label)}</a>")
    if not content:
        return ""
    return "\n".join([
        f"    <section class=\"sl-ty-footer\" data-section-id=\"{escape(str(section.get('id', 'ty-footer')))}\" data-section-type=\"thank_you_footer\">",
        *content,
        "    </section>",
    ])


CTA_TYPES = {"buy", "call", "email", "external", "download", "booking", "appointment"}


def offer_cta(offer: dict[str, Any]) -> dict[str, str]:
    """Normalize the offer's snapshotted CTA contract. The offer is the page's source of truth, so the
    CTA type (buy / call / email / external / booking) drives which CTA component the page renders."""
    presentation = offer.get("presentation") or {}
    cta = presentation.get("cta") or {}
    cta_type = str(cta.get("type") or "").strip().lower()
    if cta_type not in CTA_TYPES:
        cta_type = "buy"
    return {
        "type": cta_type,
        "label": str(cta.get("label") or presentation.get("cta_label") or ""),
        "target": str(cta.get("target") or ""),
    }


# Legacy cta.type -> action.type, so existing offers (presentation.cta) resolve into the actions[] model.
CTA_TO_ACTION = {
    "buy": "buy_now",
    "call": "call_phone",
    "email": "submit_form",
    "external": "redirect",
    "download": "download",
    "booking": "appointment",
    "appointment": "appointment",
}

DEFAULT_ACTION_LABELS = {
    "buy_now": "Buy Now",
    "add_to_cart": "Add to Cart",
    "submit_form": "Submit",
    "call_phone": "Call Now",
    "sms": "Text Us",
    "download": "Download",
    "appointment": "Book Now",
    "redirect": "Visit Website",
    "external_checkout": "Checkout",
}


def offer_actions(offer: dict[str, Any]) -> list[dict[str, str]]:
    """The offer's action list (presentation.actions[]), rendered in order by the ActionBar. Falls back to
    deriving a single action from the legacy presentation.cta so pre-actions[] offers keep working."""
    presentation = offer.get("presentation") or {}
    raw = presentation.get("actions")
    actions: list[dict[str, str]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            atype = str(entry.get("type") or "").strip().lower()
            if not atype:
                continue
            actions.append({
                "type": atype,
                "label": str(entry.get("label") or DEFAULT_ACTION_LABELS.get(atype, "")),
                "target": str(entry.get("target") or ""),
            })
    if not actions:
        cta = offer_cta(offer)
        atype = CTA_TO_ACTION.get(cta["type"], "buy_now")
        actions.append({
            "type": atype,
            "label": cta["label"] or DEFAULT_ACTION_LABELS.get(atype, ""),
            "target": cta["target"],
        })
    return actions


def listicle_add_label(offer: dict[str, Any]) -> str:
    """Label for the listicle add-to-cart button — from the add_to_cart action if the offer declares one."""
    for action in offer_actions(offer):
        if action["type"] == "add_to_cart":
            return action["label"] or "Add to cart"
    return "Add to cart"


def render_testimonials(section: dict[str, Any]) -> str:
    items = section.get("items") or []
    cards = []
    for item in items:
        quote = str(item.get("quote") or "").strip()
        if not quote:
            continue
        author = str(item.get("author") or "").strip()
        role = str(item.get("role") or "").strip()
        avatar_url = str(item.get("avatar_url") or "").strip()
        byline = "<span class=\"sl-testimonial-sep\" aria-hidden=\"true\"></span>".join(
            part for part in [f"<strong>{escape(author)}</strong>" if author else "", escape(role) if role else ""] if part
        )
        cards.append("\n".join(line for line in [
            "      <figure class=\"sl-testimonial\">",
            "        <div class=\"sl-testimonial-body\">",
            f"          <blockquote>{escape(quote)}</blockquote>",
            (f"          <figcaption>{byline}</figcaption>" if byline else ""),
            "        </div>",
            # Avatar LAST in source so it sits on the right on desktop; CSS reorders it above the quote
            # on narrow screens, where a side-by-side split would squeeze the quote to a column of words.
            (f"        {responsive_img(avatar_url, author or 'Reviewer', sizes=CONTENT_BLOCK_SIZES)}" if avatar_url else ""),
            "      </figure>",
        ] if line))
    if not cards:
        return ""
    heading = str(section.get("heading") or "").strip()
    heading_html = f"      <h2 class=\"sl-section-heading\">{render_headline_markup(heading)}</h2>" if heading else ""
    return "\n".join(line for line in [
        f"    <section class=\"sl-testimonials\" data-section-id=\"{escape(str(section.get('id', 'testimonials')))}\" data-section-type=\"testimonials\">",
        heading_html,
        *cards,
        "    </section>",
    ] if line)


def render_rating(section: dict[str, Any]) -> str:
    try:
        value = float(section.get("value") or 0)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(5.0, value))
    full = int(value)
    half = 1 if value - full >= 0.5 else 0
    stars = "★" * full + ("⯨" if half else "") + "☆" * (5 - full - half)
    count = section.get("count")
    label = str(section.get("label") or "").strip()
    meta_parts = []
    if value:
        meta_parts.append(f"<strong>{value:.1f}</strong>")
    if isinstance(count, int) and count > 0:
        meta_parts.append(f"{count:,} reviews")
    if label:
        meta_parts.append(escape(label))
    meta = " · ".join(meta_parts)
    return "\n".join(line for line in [
        f"    <section class=\"sl-rating\" data-section-id=\"{escape(str(section.get('id', 'rating')))}\" data-section-type=\"rating\">",
        f"      <span class=\"sl-rating-stars\" aria-hidden=\"true\">{stars}</span>",
        (f"      <span class=\"sl-rating-meta\">{meta}</span>" if meta else ""),
        "    </section>",
    ] if line)


def render_price_highlight(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """The bargain block: regular price struck through, sale price large, two authored lines.

    Carries NO action on purpose — checkout_cta is the ask, and this is a pause that reframes value on the
    way there. Numbers are DERIVED (domain/bargain.py), never authored, so it cannot show a price that
    checkout will not honour.

    Reuses the price element's tokens rather than declaring its own, so every preset styles it on day one
    and it cannot drift from the price card beside it.
    """
    bargain = derived_bargain(offer, products_by_id, services_by_id or {})
    if not bargain["sale"]:
        return ""

    currency = bargain["currency"]
    sale = format_money(bargain["sale"], currency)
    # "as low as" makes a tiered figure a claim about the RANGE, so it cannot contradict the interactive
    # price selector when a visitor picks another tier (plans/PRICE_HIGHLIGHT.md §4).
    if bargain["tiered"]:
        amount = f'<span class="sl-bargain-prefix">{escape(FROM_PREFIX)}</span> {escape(sale)}'
    else:
        amount = escape(sale)

    rows: list[str] = []
    if bargain["has_bargain"]:
        regular = format_money(bargain["regular"], currency)
        rows.append(f'      <p class="sl-bargain-regular">Regular Price: <s>{escape(regular)}</s></p>')
    rows.append(f'      <p class="sl-bargain-amount">{amount}</p>')

    main_text = str(section.get("main_text") or "").strip()
    subtext = str(section.get("subtext") or "").strip()
    if main_text:
        rows.append(f'      <p class="sl-bargain-main">{render_headline_markup(main_text)}</p>')
    if subtext:
        rows.append(f'      <p class="sl-bargain-sub">{escape(subtext)}</p>')

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "price-highlight")))
    return "\n".join([
        f'    <section class="sl-price-highlight{themed}" data-section-id="{section_id}" data-section-type="price_highlight"{style_attr}>',
        *rows,
        "    </section>",
    ])


def render_author_bio(section: dict[str, Any]) -> str:
    """Credibility block: photo, name, a headline that earns attention, then the detail.

    The ORDER is the element (plans/AUTHOR_BIO.md): person -> name -> why they are worth hearing -> proof.
    It is not tenant-arrangeable, because rearranging it breaks the argument it encodes.

    Optionally breaks the page preset via the shared section override — and when it does, the ink is
    DERIVED from the chosen background, so a tenant cannot produce unreadable text by picking a colour.
    """
    name = str(section.get("name") or "").strip()
    headline = str(section.get("headline") or "").strip()
    body = str(section.get("body") or "").strip()
    photo = str(section.get("photo_url") or "").strip()
    if not (name or headline or body or photo):
        return ""

    rows: list[str] = []
    if photo:
        alt = escape(name or "Author")
        rows.append(
            "      " + cropped_media(
                responsive_img(photo, alt, sizes=AUTHOR_PHOTO_SIZES),
                section.get("image_crop"), "author_bio", "sl-author-photo",
            )
        )
    if name:
        rows.append(f'      <p class="sl-author-name">{escape(name)}</p>')
    if headline:
        # h2 so the block joins the page heading outline (plans/SEMANTIC_HTML.md) rather than floating.
        rows.append(f'      <h2 class="sl-author-headline">{render_headline_markup(headline)}</h2>')
    if body:
        rows.append(f'      <p class="sl-author-body">{escape(body)}</p>')

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "author-bio")))
    return "\n".join([
        f'    <section class="sl-author-bio{themed}" data-section-id="{section_id}" data-section-type="author_bio"{style_attr}>',
        *rows,
        "    </section>",
    ])


RIBBON_PRESENTATIONS = ("image_left", "centered", "compact")
RIBBON_PURPOSES = ("promote_offer", "capture_lead", "promote_content", "custom")
# Named after the existing action vocabulary (CTA_TO_ACTION below) rather than a new set of words for the
# same ideas. `none` is explicit: a ribbon with nothing to click is a content block, and should say so.
# `promote_page` is a redirect whose target the BUILDER resolves from the tenant's own page list, so the
# renderer treats it identically — the difference is where the URL comes from, not what happens on click.
RIBBON_ACTIONS = ("redirect", "promote_page", "download", "email_file", "call_phone", "email", "none")
RIBBON_IMAGE_SIZES = "(max-width: 700px) 100vw, 320px"
# A tenant types this URL, so the scheme is an injection surface: `javascript:` in an href executes on
# click. Allow only schemes that navigate, plus same-origin paths.
SAFE_HREF_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def safe_href(value: str) -> str:
    """A tenant-supplied link, or "" when it is not something we will put in an href.

    Same-origin paths (/thing) are allowed so a ribbon can point at another page on the tenant's own site,
    which is the "promote one of my offers" case. Everything else must carry a scheme we recognise.
    """
    url = str(value or "").strip()
    if not url:
        return ""
    lowered = url.lower()
    if lowered.startswith("//"):          # protocol-relative: inherits the page scheme, but hides its host
        return ""
    if url.startswith("/"):
        return url
    return url if lowered.startswith(SAFE_HREF_SCHEMES) else ""


def cropped_media(inner: str, crop: Any, surface: str, base_class: str) -> str:
    """Wrap rendered image markup in a crop box, or return it unwrapped when there is no crop.

    Every croppable surface goes through here so the class, the custom properties and the "no crop means
    no extra markup" rule are decided once. A surface that hand-rolls this is a surface that will forget
    one of the three (plans/IMAGE_CROPPER.md).

    The wrapper only frames: srcset, lazy loading and intrinsic dimensions stay with responsive_img.
    """
    style = crop_style_vars(crop, surface)
    if not style:
        return f'<div class="{base_class}">{inner}</div>'
    return f'<div class="{base_class} sl-cropped" style="{escape(style)}">{inner}</div>'


def render_page_ribbon(section: dict[str, Any], page: dict[str, Any] | None = None,
                       api_base_url: str | None = None) -> str:
    """An Attention Block, presented as a ribbon: a mid-scroll interruption that ASKS for something.

    Not a content_block (plans/ATTENTION_PRIMITIVE.md §4a): a content block informs, a ribbon acts. Same
    reason checkout_cta is its own element rather than a styled paragraph.

    Static only, deliberately. Ten of the twelve uses in the plan need no per-visitor state, and pages are
    rendered ONCE at publish time and served from S3 — so anything that varies by visitor needs client-side
    hydration, which is its own project (A-P3) rather than something to half-build here.
    """
    headline = str(section.get("headline") or "").strip()
    body = str(section.get("body") or "").strip()
    if not (headline or body):
        return ""

    presentation = str(section.get("presentation") or "image_left").strip().lower()
    if presentation not in RIBBON_PRESENTATIONS:
        presentation = "image_left"

    eyebrow = str(section.get("eyebrow") or "").strip()
    image = str(section.get("image_url") or "").strip()
    # `centered` is the no-image presentation by definition, so an image left over from another choice is
    # dropped rather than quietly changing the layout the tenant picked.
    if presentation == "centered":
        image = ""

    section_id = escape(str(section.get("id", "page-ribbon")))
    cta = section.get("cta") or {}
    action = str(cta.get("action") or "redirect").strip().lower()
    if action not in RIBBON_ACTIONS:
        action = "redirect"
    target = str(cta.get("target") or "").strip()
    if action == "call_phone":
        href = safe_href(f"tel:{target}") if target else ""
    elif action == "email":
        href = safe_href(f"mailto:{target}") if target else ""
    elif action in ("redirect", "promote_page"):
        href = safe_href(target)
    else:
        href = ""
    label = str(cta.get("label") or "").strip()

    parts: list[str] = []
    if image:
        parts.append("      " + cropped_media(
            responsive_img(image, headline or "", sizes=RIBBON_IMAGE_SIZES),
            section.get("image_crop"), "page_ribbon", "sl-ribbon-media",
        ))
    copy: list[str] = ['      <div class="sl-ribbon-copy">']
    if eyebrow:
        copy.append(f'        <p class="sl-ribbon-eyebrow">{escape(eyebrow)}</p>')
    if headline:
        copy.append(f'        <h2 class="sl-ribbon-headline">{render_headline_markup(headline)}</h2>')
    if body:
        copy.append(f'        <p class="sl-ribbon-body">{escape(body)}</p>')
    if action in ("download", "email_file") and label and (cta.get("asset") or {}).get("bucket_key"):
        page = page or {}
        collect = [field for field in ("email", "phone") if cta.get(f"collect_{field}")]
        # Emailing needs an address whatever the checkboxes say — the server enforces this too, but asking
        # for it up front saves the visitor a rejected submit.
        if action == "email_file" and "email" not in collect:
            collect.insert(0, "email")
        collect = ",".join(collect)
        endpoint = f"{str(api_base_url or '').rstrip('/')}/downloads/lead"
        mode = "live" if str(page.get("stripe_mode") or "").strip().lower() == "live" else "test"
        copy.append(
            '        <button type="button" class="sl-ribbon-cta" data-sl-download'
            f' data-endpoint="{escape(endpoint)}"'
            f' data-tenant-id="{escape(str(page.get("tenant_id") or ""))}"'
            f' data-page-id="{escape(str(page.get("page_id") or ""))}"'
            f' data-section-id="{section_id}"'
            f' data-stripe-mode="{mode}"'
            f' data-collect="{escape(collect)}">{escape(label)}</button>'
        )
    elif href and label:
        external = href.startswith(("http://", "https://"))
        rel = ' rel="noopener"' + (' target="_blank"' if external else "")
        copy.append(f'        <a class="sl-ribbon-cta" href="{escape(href)}"{rel}>{escape(label)}</a>')
    copy.append("      </div>")
    parts.extend(copy)

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    return "\n".join([
        f'    <section class="sl-page-ribbon is-{presentation}{themed}" data-section-id="{section_id}"'
        f' data-section-type="page_ribbon"{style_attr}>',
        *parts,
        "    </section>",
    ])


NUMBERED_LIST_MAX = 12


BEFORE_AFTER_SIZES = "(min-width: 60rem) 60rem, 100vw"
BEFORE_AFTER_DEFAULT_RATIO = 4 / 3


def render_before_after(section: dict[str, Any]) -> str:
    """Two photographs of the same thing, with a divider the visitor drags to wipe between them.

    The divider is a real `<input type="range">`, not hand-rolled pointer handling. That is what makes it
    work with a keyboard and with assistive technology, and it collapses the script to syncing one value
    into a CSS custom property -- drag, touch, capture and bounds all come from the browser.

    Without JavaScript the wipe sits at its authored position, which is a legible side-by-side split rather
    than a broken control. Published pages are static artifacts, so the no-JS state has to be a real state.

    Both images are locked to ONE ratio (the element's own), which is what makes the two halves align.
    Letting each side choose would reveal misaligned content at the seam and look broken.
    """
    before = str(section.get("before_url") or "").strip()
    after = str(section.get("after_url") or "").strip()
    if not (before and after):
        return ""  # a single image is not a comparison, and half a wipe is worse than none

    try:
        ratio = float(section.get("ratio") or BEFORE_AFTER_DEFAULT_RATIO)
    except (TypeError, ValueError):
        ratio = BEFORE_AFTER_DEFAULT_RATIO
    if ratio <= 0:
        ratio = BEFORE_AFTER_DEFAULT_RATIO

    try:
        start = float(section.get("start", 50))
    except (TypeError, ValueError):
        start = 50.0
    start = min(max(start, 0.0), 100.0)

    before_label = str(section.get("before_label") or "Before").strip() or "Before"
    after_label = str(section.get("after_label") or "After").strip() or "After"
    heading = str(section.get("heading") or "").strip()
    section_id = escape(str(section.get("id", "before-after")))

    def layer(url: str, crop: Any, alt: str, side: str, eager: bool) -> str:
        img = responsive_img(url, alt, sizes=BEFORE_AFTER_SIZES, eager=eager)
        return cropped_media(img, crop, "before_after", f"sl-ba-img is-{side}")

    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-ba-heading">{render_headline_markup(heading)}</h2>')
    rows.extend([
        f'      <div class="sl-ba-frame" data-sl-before-after style="--sl-ba-ar:{ratio:g};--sl-ba-pos:{start:g}%">',
        # AFTER sits underneath and BEFORE is clipped over it, so dragging left reveals the outcome --
        # the direction people expect, and the outcome is what the tenant is selling.
        "        " + layer(after, section.get("after_crop"), after_label, "after", eager=False),
        "        " + layer(before, section.get("before_crop"), before_label, "before", eager=True),
        f'        <span class="sl-ba-tag is-before">{escape(before_label)}</span>',
        f'        <span class="sl-ba-tag is-after">{escape(after_label)}</span>',
        '        <span class="sl-ba-handle" aria-hidden="true"></span>',
        '        <input class="sl-ba-range" type="range" min="0" max="100"',
        f'               value="{start:g}" aria-label="{escape(before_label)} and {escape(after_label)} comparison slider">',
        "      </div>",
    ])
    return "\n".join([
        f'    <section class="sl-before-after" data-section-id="{section_id}" data-section-type="before_after">',
        *rows,
        "    </section>",
    ])


def render_numbered_list(section: dict[str, Any]) -> str:
    """A heading plus an ordered list of authored lines, each on a card with a numbered badge.

    ONE element for benefits AND how-it-works steps (plans/LANDING_ELEMENTS_UNIT.md §Numbered List). The
    only thing separating them is the heading the tenant types — "What's Inside" versus "How It Works" —
    which is content, not structure. Two visually identical elements would just make a tenant guess.

    A real <ol>, so the sequence is in the markup rather than only in the styling: assistive technology
    announces the position, and the visible badge is a CSS counter that carries no content of its own.
    """
    items = [str(item or "").strip() for item in (section.get("items") or [])]
    items = [item for item in items if item][:NUMBERED_LIST_MAX]
    if not items:
        return ""

    heading = str(section.get("heading") or "").strip()
    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-numbered-heading">{render_headline_markup(heading)}</h2>')
    rows.append('      <ol class="sl-numbered-items">')
    for item in items:
        rows.append(f'        <li class="sl-numbered-item"><p class="sl-numbered-text">{escape(item)}</p></li>')
    rows.append("      </ol>")

    section_id = escape(str(section.get("id", "numbered-list")))
    return "\n".join([
        f'    <section class="sl-numbered-list" data-section-id="{section_id}" data-section-type="numbered_list">',
        *rows,
        "    </section>",
    ])


ATTRIBUTION_DASHES = ("\u2014", "\u2013", "-")
QUOTE_PHOTO_SIZES = "220px"
QUOTE_STYLES = ("minimal", "fancy")


def render_quote(section: dict[str, Any]) -> str:
    """A pull-quote: an IDEA given weight, with an optional attribution, title and portrait.

    Deliberately unlike `testimonials` (plans/LANDING_ELEMENTS_UNIT.md §Quote). A testimonial is a customer
    vouching for the product; a pull-quote is a maxim or the tenant's own line. They must not look alike, or
    a quote reads as an endorsement nobody actually gave.

    Two presentations, because the same content wants different weight in different places:

      * `minimal` (default) — a vertical accent bar and italic type. Quiet enough to sit inside body copy.
      * `fancy` — a coloured card with a portrait and a large opening quotation mark.

    The section override means the same thing in both, but paints a different surface: `accent` is the BAR
    in minimal and the CARD in fancy. Either way the text on it is `--sl-section-accent-ink`, derived, so a
    tenant cannot colour the quote into invisibility.

    figure/figcaption rather than a bare blockquote: the attribution is about the quote, not part of what
    was said, and HTML has a shape for exactly that (plans/SEMANTIC_HTML.md).
    """
    text = str(section.get("text") or "").strip()
    if not text:
        return ""

    presentation = str(section.get("style") or "minimal")
    if presentation not in QUOTE_STYLES:
        presentation = "minimal"

    title = str(section.get("title") or "").strip()
    photo = str(section.get("image_url") or "").strip()
    attribution = str(section.get("attribution") or "").strip()
    # The dash belongs to the presentation, so a tenant who types one anyway does not get two.
    while attribution and attribution[0] in ATTRIBUTION_DASHES:
        attribution = attribution[1:].strip()

    quote_html = f'<blockquote class="sl-quote-text">{escape(text)}</blockquote>'
    caption_html = (
        f'<figcaption class="sl-quote-attribution">\u2014 {escape(attribution)}</figcaption>'
        if attribution else ""
    )
    photo_html = (
        f'<div class="sl-quote-photo">'
        f"{responsive_img(photo, escape(attribution or title or 'Quote'), sizes=QUOTE_PHOTO_SIZES)}</div>"
        if photo else ""
    )

    rows: list[str] = []
    if title:
        # h2 so the block joins the page heading outline rather than floating (plans/SEMANTIC_HTML.md).
        rows.append(f'      <h2 class="sl-quote-title">{render_headline_markup(title)}</h2>')
    rows.append('      <figure class="sl-quote-figure">')
    if photo_html:
        rows.append(f"        {photo_html}")
    if presentation == "fancy":
        # The card's text is wrapped so the big quotation mark can be positioned against it rather than
        # against the card, which keeps the glyph beside the words at every width.
        rows.append('        <div class="sl-quote-body">')
        rows.append(f"          {quote_html}")
        if caption_html:
            rows.append(f"          {caption_html}")
        rows.append("        </div>")
    else:
        rows.append(f"        {quote_html}")
        if caption_html:
            rows.append(f"        {caption_html}")
    rows.append("      </figure>")

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "quote")))
    return "\n".join([
        f'    <section class="sl-quote sl-quote-{presentation}{themed}"'
        f' data-section-id="{section_id}" data-section-type="quote"{style_attr}>',
        *rows,
        "    </section>",
    ])


def render_bragging_points(section: dict[str, Any]) -> str:
    """Quantified proof: {value, label} cards. The value is the claim, the label says what it counts.

    Standalone rather than welded to Author Bio (plans/AUTHOR_BIO.md 4a) because the same component IS the
    stats band — "10,000 customers served" has no author in it. Adjacency to the bio is the tenant's drag,
    not a structural coupling.

    Values are free text, never parsed as numbers: the author's own example is `Q-Media / Founder and CEO`.
    """
    items = [
        item for item in (section.get("items") or [])
        if str(item.get("value") or "").strip() or str(item.get("label") or "").strip()
    ]
    if not items:
        return ""

    heading = str(section.get("heading") or "").strip()
    cards: list[str] = []
    for item in items:
        value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        parts = []
        if value:
            parts.append(f'          <p class="sl-brag-value">{escape(value)}</p>')
        if label:
            parts.append(f'          <p class="sl-brag-label">{escape(label)}</p>')
        cards.append("\n".join(['        <li class="sl-brag-card">', *parts, "        </li>"]))

    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-brag-heading">{render_headline_markup(heading)}</h2>')
    rows.append('      <ul class="sl-brag-grid">')
    rows.extend(cards)
    rows.append("      </ul>")

    # Second consumer of the shared section override — the mechanism step 0 exists for. The card surface is
    # `accent`, so its text is the DERIVED accent-ink and a tenant cannot colour the value into invisibility.
    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "bragging-points")))
    return "\n".join([
        f'    <section class="sl-bragging-points{themed}" data-section-id="{section_id}" data-section-type="bragging_points"{style_attr}>',
        *rows,
        "    </section>",
    ])


BRAND_MARQUEE_SCROLL_MODES = ("auto", "always", "never")
BRAND_MARQUEE_MIN_SECONDS = 3
BRAND_MARQUEE_MAX_SECONDS = 60
BRAND_MARQUEE_DEFAULT_SECONDS = 30
# Auto starts rolling once a row is long enough to be worth rolling. Keeping this exact number is what
# makes `auto` a safe default: no page that exists today changes behaviour.
BRAND_MARQUEE_AUTO_THRESHOLD = 5


def render_client_marquee(section: dict[str, Any]) -> str:
    """Social proof as a row of client names or logos (plans/BRAND_MARQUEE.md).

    The NAME is the entry and always renders; an image is the optional upgrade that renders instead of it.
    That is the fix for a real bug: entries were filtered on `image_url`, so a tenant who typed "YouTube"
    and uploaded nothing got silence — no logo, no text, no warning — while the builder labelled the field
    as being for search engines only. The legacy marquee this replaced was text-only, so the element could
    not reproduce what it succeeded.

    Scrolling has three states because two would force a migration that breaks something either way:
    default-scroll makes a two-logo page crawl, default-static stops an eight-logo one. `auto` keeps the
    >= 5 rule exactly, so nothing that exists today moves.
    """
    entries = [
        entry for entry in (section.get("logos") or [])
        if str(entry.get("name") or "").strip() or str(entry.get("image_url") or "").strip()
    ]
    if not entries:
        return ""

    bare = str(section.get("logo_backing") or "card").strip().lower() == "none"
    logo_class = "sl-marquee-logo is-bare" if bare else "sl-marquee-logo"

    def item(entry: dict[str, Any]) -> str:
        name = str(entry.get("name") or "").strip()
        image = str(entry.get("image_url") or "").strip()
        if image:
            return (f'<span class="{logo_class}">'
                    f'{responsive_img(image, name or "Client", sizes=CONTENT_BLOCK_SIZES)}</span>')
        # A themed wordmark, NOT a white card with text in it — that reads as a logo that failed to load.
        return f'<span class="sl-marquee-word">{escape(name)}</span>'

    items = "".join(item(entry) for entry in entries)
    heading = str(section.get("heading") or "Our Clients").strip()
    heading_html = f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>' if heading else ""

    mode = str(section.get("scroll") or "auto").strip().lower()
    if mode not in BRAND_MARQUEE_SCROLL_MODES:
        mode = "auto"
    scrolling = mode == "always" or (mode == "auto" and len(entries) >= BRAND_MARQUEE_AUTO_THRESHOLD)

    if scrolling:
        # The row is duplicated with aria-hidden on the copy, so the loop is seamless and the list is
        # announced once rather than twice.
        body = [
            '      <div class="sl-marquee-track">',
            f'        <div class="sl-marquee-row">{items}</div>',
            f'        <div class="sl-marquee-row" aria-hidden="true">{items}</div>',
            "      </div>",
        ]
    else:
        body = [f'      <div class="sl-marquee-static">{items}</div>']

    seconds = section.get("scroll_seconds")
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = BRAND_MARQUEE_DEFAULT_SECONDS
    seconds = max(BRAND_MARQUEE_MIN_SECONDS, min(BRAND_MARQUEE_MAX_SECONDS, seconds))
    # Its OWN duration property. The countdown banner has a separate marquee, and the two sharing a name
    # is how one of them silently stopped animating once before.
    style = f' style="--sl-brand-marquee-duration:{seconds}s"' if scrolling else ""

    return "\n".join(line for line in [
        f'    <section class="sl-client-marquee" data-section-id="{escape(str(section.get("id", "client-marquee")))}"'
        f' data-section-type="client_marquee"{style}>',
        heading_html,
        *body,
        "    </section>",
    ] if line)


def render_brand_hero(section: dict[str, Any]) -> str:
    """The storefront hero for a homepage/collection page (plans/SITE_OBJECT.md §2.5b): the store's name as the
    page's single H1 plus an optional tagline. No product — a storefront page has no single offer. Falls back
    to the Site Organization name when the section carries no headline."""
    headline = str(section.get("headline") or "").strip() or str(_RENDER_ORG.get("name") or "").strip()
    if not headline:
        return ""
    tagline = str(section.get("tagline") or "").strip()
    return "\n".join(line for line in [
        f'    <section class="sl-brand-hero" data-section-id="{escape(str(section.get("id", "brand-hero")))}" data-section-type="brand_hero">',
        brand_logo_markup(str(section.get("logo_url") or "").strip(), headline),
        f'      <h1>{render_headline_markup(headline)}</h1>',
        (f'      <p class="sl-brand-hero-tagline">{escape(tagline)}</p>' if tagline else ""),
        "    </section>",
    ] if line)


# A generic "home"/storefront glyph (Heroicons house, solid) — the faux logo when the store has no uploaded one,
# mirroring how product cards fall back to an auto-generated icon tile.
_FAUX_STORE_LOGO_SVG = (
    '<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">'
    '<path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/>'
    '</svg>'
)


def brand_logo_markup(logo_url: str, name: str) -> str:
    """The storefront's brand mark above the headline: the tenant's uploaded logo when set, otherwise an
    auto-generated "faux" logo — a house glyph on an accent tile — so every storefront has a mark (SITE_OBJECT
    §2.5b). The CSS caps the height, so a missing intrinsic size can't shift layout."""
    if logo_url:
        return f'      <img class="sl-brand-logo" src="{escape(logo_url)}" alt="{escape(name)} logo" loading="lazy">'
    return f'      <div class="sl-brand-logo sl-brand-logo-faux" aria-hidden="true">{_FAUX_STORE_LOGO_SVG}</div>'


def render_catalog_grid(
    section: dict[str, Any],
    offers_by_id: dict[str, dict[str, Any]],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> str:
    """A grid of the store's products (plans/SITE_OBJECT.md §2.5b / SEO-13): one card per curated item, each
    an internal link to that offer's landing page slug on the Site — the crawlable catalog hierarchy that
    makes subfolder domain authority work. Reuses the product_carousel card shape; links instead of buy-now.
    Links resolve against the Site home host, so cards render as plain (unlinked) tiles off a custom domain."""
    home = (_RENDER_STATE.get("home_url") or "").rstrip("/")
    cards = []
    for item in section.get("items") or []:
        offer = offers_by_id.get(str((item or {}).get("offer_id") or ""))
        if not offer:
            continue
        presentation = offer.get("presentation") or {}
        name = str(presentation.get("headline") or offer.get("name") or "")
        image = str(presentation.get("hero_image_url") or "").strip()
        if not image:
            product = first_offer_product(offer, products_by_id)
            image = str((product.get("images") or [""])[0] if product else "")
        price_html = ""
        try:
            resolved = resolve_offer(offer, products_by_id, None, services_by_id=services_by_id)
            price_html = f'<p class="sl-catalog-price">{escape(format_money(int(resolved.get("subtotal", 0)), str(resolved.get("currency") or "usd")))}</p>'
        except Exception:  # noqa: BLE001 - a broken card must not break the page
            pass
        inner = "\n".join(line for line in [
            (f"        {responsive_img(image, name or 'Product', sizes=CONTENT_BLOCK_SIZES)}" if image else ""),
            f'        <h3 class="sl-catalog-title">{render_headline_markup(name)}</h3>',
            (f"        {price_html}" if price_html else ""),
        ] if line)
        slug = str((item or {}).get("slug") or "").strip()
        href = internal_href(slug) if home and slug else ""  # host-relative so the card works on any serving host
        if href:
            cards.append(f'      <a class="sl-catalog-card" href="{escape(href)}">\n{inner}\n      </a>')
        else:
            cards.append(f'      <div class="sl-catalog-card">\n{inner}\n      </div>')
    if not cards:
        return ""
    heading = str(section.get("heading") or "").strip()
    heading_html = f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>' if heading else ""
    section_type = escape(str(section.get("type") or "catalog_grid"))
    return "\n".join(line for line in [
        f'    <section class="sl-catalog-grid" data-section-id="{escape(str(section.get("id", "catalog-grid")))}" data-section-type="{section_type}">',
        heading_html,
        '      <div class="sl-catalog-cards">',
        *cards,
        "      </div>",
        "    </section>",
    ] if line)


_SOCIAL_LABELS = {
    "facebook.com": "Facebook", "instagram.com": "Instagram", "twitter.com": "Twitter", "x.com": "X",
    "linkedin.com": "LinkedIn", "youtube.com": "YouTube", "tiktok.com": "TikTok", "pinterest.com": "Pinterest",
    "threads.net": "Threads", "github.com": "GitHub", "yelp.com": "Yelp", "trustpilot.com": "Trustpilot",
}


def _social_label(url: str) -> str:
    host = re.sub(r"^https?://", "", str(url or "").strip().lower()).split("/")[0]
    host = host[4:] if host.startswith("www.") else host
    for domain, label in _SOCIAL_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host or "Profile"


def render_seller_profile(section: dict[str, Any]) -> str:
    """The tenant/seller profile block (TENANT_PROFILE_REQUIREMENTS §4): visible store identity — description,
    contact, ownership-verified social links, and the store's categories — plus a CollectionPage whose
    mainEntity is the full OnlineStore node (so the seller `@id` resolves here, TP-03/04/05). Social links
    carry rel="nofollow ugc noopener" (TP-10); only verified sameAs render (TP §4.4)."""
    org = _RENDER_ORG
    origin = canonical_origin()
    name = str(org.get("name") or "").strip()
    if not name or not origin:
        return ""
    node = organization_node(org, origin, with_context=False)
    canonical = _RENDER_STATE.get("canonical") or f"{origin}/about"
    collection = {"@context": "https://schema.org", "@type": "CollectionPage", "url": canonical, "mainEntity": node}

    parts = [f'    <section class="sl-seller-profile" data-section-id="{escape(str(section.get("id", "seller-profile")))}" data-section-type="seller_profile">']
    heading = str(section.get("heading") or "").strip()
    if heading:
        parts.append(f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>')
    description = str(org.get("description") or "").strip()
    if description:
        parts.append(f'      <p class="sl-seller-desc">{escape(description)}</p>')
    contact = []
    tel = str(org.get("telephone") or "").strip()
    if tel:
        contact.append(f'<a href="tel:{escape(tel)}">{escape(tel)}</a>')
    email = str(org.get("email") or "").strip()
    if email:
        contact.append(f'<a href="mailto:{escape(email)}">{escape(email)}</a>')
    address = org.get("address") or {}
    addr_text = ", ".join(str(address.get(f) or "").strip() for f in ("street", "locality", "region", "postal_code", "country") if str(address.get(f) or "").strip())
    if addr_text:
        contact.append(f"<span>{escape(addr_text)}</span>")
    if contact:
        parts.append('      <p class="sl-seller-contact">' + " · ".join(contact) + "</p>")
    # Visible hours + a "View on Google" link — the on-page content that mirrors the LocalBusiness JSON-LD
    # (openingHoursSpecification / hasMap), so the two stay consistent for local SEO.
    hours = _opening_hours_ld(org.get("opening_hours"))
    if hours:
        rows = "".join(f'<li><span>{escape(", ".join(h["dayOfWeek"]))}</span><span>{escape(h["opens"])}–{escape(h["closes"])}</span></li>' for h in hours)
        parts.append(f'      <ul class="sl-seller-hours">{rows}</ul>')
    gbp_url = str(org.get("gbp_url") or "").strip()
    if gbp_url:
        parts.append(f'      <p class="sl-seller-gbp"><a href="{escape(gbp_url)}" rel="nofollow noopener" target="_blank">View on Google</a></p>')
    socials = [str(e.get("url")).strip() for e in (org.get("same_as") or [])
               if isinstance(e, dict) and e.get("verified") is True and str(e.get("url") or "").strip()][:6]
    if socials:
        links = "".join(f'<li><a href="{escape(u)}" rel="nofollow ugc noopener" target="_blank">{escape(_social_label(u))}</a></li>' for u in socials)
        parts.append(f'      <ul class="sl-seller-social">{links}</ul>')
    home = (_RENDER_STATE.get("home_url") or "").rstrip("/")
    if home and _RENDER_CATEGORY_PAGES:
        cats = "".join(
            f'<li><a href="{escape(internal_href(info["slug"]))}">{escape(info.get("label") or humanize_category(key))}</a></li>'
            for key, info in sorted(_RENDER_CATEGORY_PAGES.items()))
        parts.append(f'      <ul class="sl-seller-catalog">{cats}</ul>')
    parts.append(f'      <script type="application/ld+json">{json_ld_dump(collection)}</script>')
    parts.append("    </section>")
    return "\n".join(parts)


def render_product_carousel(
    section: dict[str, Any],
    page: dict[str, Any],
    offers_by_id: dict[str, dict[str, Any]],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    checkout_url: str | None,
    api_base_url: str | None = None,
) -> str:
    """Listicle carousel: a swipeable row of several offers, each slide with its own price and a Buy-now
    that launches THAT offer's existing single-offer checkout. Server-side cart is a later project."""
    slides = []
    for offer_id in section.get("offer_ids") or []:
        offer = offers_by_id.get(str(offer_id))
        if not offer:
            continue
        try:
            resolved = resolve_offer(offer, products_by_id, None, services_by_id=services_by_id)
        except Exception:  # noqa: BLE001 - a broken slide must not break the page
            continue
        subtotal = int(resolved.get("subtotal", 0))
        currency = str(resolved.get("currency") or "usd")
        presentation = offer.get("presentation") or {}
        name = str(presentation.get("headline") or offer.get("name") or "")
        subheadline = str(presentation.get("subheadline") or "")
        image = str(presentation.get("hero_image_url") or "").strip()
        if not image:
            product = first_offer_product(offer, products_by_id)
            image = str((product.get("images") or [""])[0] if product else "") or first_offer_service_image(offer, services_by_id)
        href = escape(checkout_context(page, offer, resolved, checkout_url, api_base_url)["href"])
        slides.append("\n".join(line for line in [
            "        <article class=\"sl-carousel-slide\">",
            (f"          {responsive_img(image, name or 'Product', sizes=CONTENT_BLOCK_SIZES)}" if image else ""),
            f"          <h3 class=\"sl-carousel-title\">{render_headline_markup(name)}</h3>",
            (f"          <p class=\"sl-carousel-desc\">{escape(subheadline)}</p>" if subheadline else ""),
            f"          <p class=\"sl-carousel-price\">{escape(format_money(subtotal, currency))}</p>",
            f"          <a class=\"sl-cta sl-carousel-buy\" href=\"{href}\">Buy now</a>",
            "        </article>",
        ] if line))
    if not slides:
        return ""
    heading = str(section.get("heading") or "").strip()
    heading_html = f"      <h2 class=\"sl-section-heading\">{render_headline_markup(heading)}</h2>" if heading else ""
    return "\n".join(line for line in [
        f"    <section class=\"sl-product-carousel\" data-section-id=\"{escape(str(section.get('id', 'product-carousel')))}\" data-section-type=\"product_carousel\">",
        heading_html,
        "      <div class=\"sl-carousel-track\">",
        *slides,
        "      </div>",
        "    </section>",
    ] if line)


def render_post_purchase_carousel(section: dict[str, Any], page: dict[str, Any], api_base_url: str | None) -> str:
    """Carousel-mode post-purchase screen (plans/OFFER_MODEL_REDESIGN.md §6): a grid of self-contained upsell (or
    downsell) cards, each a one-click Add wired to /upsell/charge by the island, plus a single dismiss. The
    section carries everything the island needs (offer/tenant/api on the container, product/price/sequence per
    card) so no per-card offer resolution happens here. Empty when the section has no cards."""
    cards = section.get("cards") or []
    if not cards:
        return ""
    card_html = []
    for card in cards:
        image = str(card.get("image_url") or "").strip()
        title = str(card.get("title") or "")
        desc = str(card.get("description") or "")
        amount = int(card.get("amount") or 0)
        currency = str(card.get("currency") or "usd")
        add_label = str(card.get("add_label") or "Add")
        card_html.append("\n".join(line for line in [
            f"      <article class=\"sl-pp-card\" data-pp-card data-sequence=\"{escape(str(card.get('sequence', '')))}\" data-product-id=\"{escape(str(card.get('product_id', '')))}\" data-price-id=\"{escape(str(card.get('price_id', '')))}\">",
            (f"        {responsive_img(image, title or 'Offer', sizes=CONTENT_BLOCK_SIZES)}" if image else ""),
            f"        <h3 class=\"sl-pp-card-title\">{escape(title)}</h3>",
            (f"        <p class=\"sl-pp-card-desc\">{escape(desc)}</p>" if desc else ""),
            f"        <p class=\"sl-pp-card-price\">{escape(format_money(amount, currency))}</p>",
            f"        <button class=\"sl-cta sl-pp-add\" type=\"button\" data-pp-add>{escape(add_label)}</button>",
            "      </article>",
        ] if line))
    heading = str(section.get("headline") or "")
    sub = str(section.get("subheadline") or "")
    dismiss = str(section.get("dismiss_label") or "No thanks")
    proceed = str(section.get("proceed_label") or "")
    funnel_page_id = str(section.get("funnel_page_id") or page.get("page_id") or "")
    return "\n".join(line for line in [
        (
            f"    <section class=\"sl-pp-carousel\" data-section-id=\"{escape(str(section.get('id', 'pp-carousel')))}\""
            f" data-section-type=\"post_purchase_carousel\" data-surface=\"{escape(str(section.get('surface', 'upsell')))}\""
            f" data-offer-id=\"{escape(str(section.get('offer_id', '')))}\" data-tenant-id=\"{escape(str(page.get('tenant_id', '')))}\""
            f" data-stripe-mode=\"{'live' if str(page.get('stripe_mode') or '').strip().lower() == 'live' else 'test'}\""
            f" data-page-id=\"{escape(funnel_page_id)}\" data-api-base-url=\"{escape(str(api_base_url or ''))}\">"
        ),
        (f"      <h2 class=\"sl-pp-carousel-heading\">{render_headline_markup(heading)}</h2>" if heading else ""),
        (f"      <p class=\"sl-pp-carousel-sub\">{escape(sub)}</p>" if sub else ""),
        "      <div class=\"sl-pp-carousel-grid\">",
        *card_html,
        "      </div>",
        f"      <button class=\"sl-pp-dismiss\" type=\"button\" data-pp-dismiss data-pp-proceed-label=\"{escape(proceed)}\">{escape(dismiss)}</button>",
        "    </section>",
    ] if line)


@dataclass
class CtaRenderContext:
    cta: dict[str, Any]
    page: dict[str, Any]
    section: dict[str, Any]
    offer: dict[str, Any]
    resolved_offer: dict[str, Any]
    checkout_url: str | None
    api_base_url: str | None
    products_by_id: dict[str, dict[str, Any]]


# cta.type -> registry entry. The server renders here; the plugin's validate/serialize/execute live in the
# JS island (client), which is where a conversion is actually performed (plans/CONVERSION_CONTEXT.md).
CTA_REGISTRY: dict[str, dict[str, Any]] = {
    "buy": {"render": lambda c: render_buy_cta(c.page, c.section, c.offer, c.resolved_offer, c.checkout_url, c.api_base_url), "version": 1},
    "call": {"render": lambda c: render_call_cta(c.cta), "version": 1},
    "external": {"render": lambda c: render_external_cta(c.cta), "version": 1},
    "email": {"render": lambda c: render_email_cta(c.page, c.offer, c.cta, c.products_by_id, c.api_base_url), "version": 1},
    "download": {"render": lambda c: render_download_cta(c.cta), "version": 1},
    # An appointment IS a booking — reuse the inline calendar widget rather than duplicate it.
    "booking": {"render": lambda c: render_booking_cta(c.cta, c.api_base_url, c.offer), "version": 1},
    "appointment": {"render": lambda c: render_booking_cta(c.cta, c.api_base_url, c.offer), "version": 1},
}


def render_checkout_cta(
    page: dict[str, Any],
    section: dict[str, Any],
    offer: dict[str, Any],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
    products_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    cta = offer_cta(offer)
    entry = CTA_REGISTRY.get(cta["type"], CTA_REGISTRY["buy"])
    ctx = CtaRenderContext(
        cta=cta, page=page, section=section, offer=offer, resolved_offer=resolved_offer,
        checkout_url=checkout_url, api_base_url=api_base_url, products_by_id=products_by_id or {},
    )
    return entry["render"](ctx)


LEAD_FIELD_INPUT_TYPES = {"email": "email", "phone": "tel", "tel": "tel", "number": "number"}


def render_email_cta(
    page: dict[str, Any],
    offer: dict[str, Any],
    cta: dict[str, str],
    products_by_id: dict[str, dict[str, Any]],
    api_base_url: str | None,
) -> str:
    """Inline lead-capture form. Renders the primary product's declared lead_capture.fields[], a honeypot,
    and two independent GDPR opt-ins (tenant list + Junior Bay list). Submits to POST /leads via JS."""
    lead_capture = first_offer_lead_capture(offer, products_by_id)
    declared = lead_capture.get("fields") or [{"name": "email", "type": "email", "required": True}]
    label = escape(cta["label"] or "Get Started")
    title = escape(str(lead_capture.get("title") or ""))
    description = escape(str(lead_capture.get("description") or ""))
    endpoint = escape(f"{str(api_base_url or '').rstrip('/')}/leads")
    tenant_id = escape(str(page.get("tenant_id") or offer.get("tenant_id") or ""))
    offer_id = escape(str(offer.get("offer_id") or ""))
    page_id = escape(str(page.get("page_id") or ""))
    brand = escape(str(offer_brand_fallback(offer) or "us"))

    inputs = []
    for field in declared:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        field_type = str(field.get("type") or "text").strip().lower()
        input_type = LEAD_FIELD_INPUT_TYPES.get(field_type, "text")
        required = "required" if field.get("required") else ""
        placeholder = escape(name.replace("_", " ").title())
        inputs.append(
            f"        <input class=\"sl-lead-input\" type=\"{input_type}\" name=\"{escape(name)}\" "
            f"placeholder=\"{placeholder}\" {required} />"
        )

    tenant_consent_text = f"Join {brand}'s mailing list."
    platform_consent_text = "Also hear from Junior Bay about offers like this."
    return "\n".join([
        "    <section class=\"sl-checkout-cta sl-email-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"email\">",
        f"      <form class=\"sl-lead-form\" data-lead-form data-endpoint=\"{endpoint}\" "
        f"data-tenant-id=\"{tenant_id}\" data-offer-id=\"{offer_id}\" data-page-id=\"{page_id}\" "
        f"data-stripe-mode=\"{'live' if str(offer.get('stripe_mode') or '').strip().lower() == 'live' else 'test'}\">",
        (f"        <p class=\"sl-lead-title\">{title}</p>" if title else ""),
        (f"        <p class=\"sl-lead-description\">{description}</p>" if description else ""),
        *inputs,
        # Honeypot — visually hidden, off-screen; bots fill it, humans don't.
        "        <input class=\"sl-hp\" type=\"text\" name=\"company_website\" tabindex=\"-1\" autocomplete=\"off\" aria-hidden=\"true\" />",
        "        <label class=\"sl-lead-consent\"><input type=\"checkbox\" data-consent=\"tenant_marketing\" "
        f"data-consent-text=\"{escape(tenant_consent_text)}\" /> {escape(tenant_consent_text)}</label>",
        "        <label class=\"sl-lead-consent\"><input type=\"checkbox\" data-consent=\"platform_marketing\" "
        f"data-consent-text=\"{escape(platform_consent_text)}\" /> {escape(platform_consent_text)}</label>",
        f"        <button class=\"sl-cta\" type=\"submit\">{label}</button>",
        "        <p class=\"sl-lead-status\" data-lead-status role=\"status\" aria-live=\"polite\"></p>",
        "      </form>",
        "    </section>",
    ])


def render_buy_cta(
    page: dict[str, Any],
    section: dict[str, Any],
    offer: dict[str, Any],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
) -> str:
    label = escape(str(section.get("label") or (offer.get("presentation") or {}).get("cta_label") or "Checkout"))
    subtotal = int(resolved_offer.get("subtotal", 0))
    currency = str(resolved_offer.get("currency") or "usd")
    # An upsell screen bakes the price into its accept label ("… for $22.17"), so it suppresses the CTA's own
    # amount to avoid "$22.17 - $22.17". The flag is echoed to the island so its updateCta doesn't re-append it.
    # The decline link's text is the scaffold's decline_label (falls back to the generic default).
    hide_amount = bool(section.get("hide_amount"))
    decline_label = escape(str(section.get("decline_label") or "No thanks, continue"))
    cta_text = label if hide_amount else f"{label} - {escape(format_money(subtotal, currency))}"
    hide_attr = " data-cta-hide-amount=\"true\"" if hide_amount else ""
    # An upsell CTA can carry its product's downsell price; the island swaps to it in place on decline/expiry.
    downsell_price_id = str(section.get("downsell_price_id") or "")
    downsell_attr = ""
    if downsell_price_id:
        downsell_attr = (
            f" data-downsell-price-id=\"{escape(downsell_price_id)}\""
            f" data-downsell-amount=\"{int(section.get('downsell_amount') or 0)}\""
            f" data-downsell-currency=\"{escape(str(section.get('downsell_currency') or 'usd'))}\""
            f" data-downsell-label=\"{escape(str(section.get('downsell_label') or ''))}\""
            f" data-downsell-headline=\"{escape(str(section.get('downsell_headline') or ''))}\""
        )
    hide_attr += downsell_attr
    # A last-chance note the island reveals once the downsell is showing (its final second-chance offer won't
    # come back). Hidden until then, and only emitted when this CTA actually carries a downsell.
    downsell_note = str(section.get("downsell_note") or "")
    note_html = (
        f"      <p class=\"sl-downsell-note\" data-downsell-note hidden>{escape(downsell_note)}</p>"
        if downsell_price_id and downsell_note else ""
    )
    checkout = checkout_context(page, offer, resolved_offer, checkout_url, api_base_url)
    href = escape(checkout["href"])
    data_attrs = " ".join(
        f"data-{escape(key)}=\"{escape(str(value))}\""
        for key, value in checkout["data"].items()
        if value is not None and value != ""
    )
    return "\n".join(line for line in [
        "    <section class=\"sl-checkout-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"buy\">",
        note_html,
        f"      <a class=\"sl-cta\" href=\"{href}\" data-cta-label=\"{label}\"{hide_attr} data-cta-currency=\"{escape(currency)}\" data-cta-amount=\"{subtotal}\" {data_attrs}>{cta_text}</a>",
        f"      <a class=\"sl-cta sl-decline-cta\" href=\"#decline\" data-role=\"decline\" style=\"display:none\">{decline_label}</a>",
        "    </section>",
    ] if line)


def render_call_cta(cta: dict[str, str]) -> str:
    """Phone/call CTA: a prominent number banner + a tel: call button."""
    phone = cta["target"].strip()
    label = escape(cta["label"] or "Call Now")
    tel = re.sub(r"[^\d+]", "", phone)
    href = f"tel:{escape(tel)}" if tel else "#"
    number_line = f"      <a class=\"sl-call-number\" href=\"{href}\">{escape(phone)}</a>" if phone else ""
    return "\n".join(line for line in [
        "    <section class=\"sl-checkout-cta sl-call-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"call\">",
        number_line,
        f"      <a class=\"sl-cta sl-call-button\" href=\"{href}\">{label}</a>",
        "    </section>",
    ] if line)


def render_external_cta(cta: dict[str, str]) -> str:
    """External-link CTA: a button that navigates out to the target URL in a new tab."""
    url = cta["target"].strip()
    label = escape(cta["label"] or "Learn More")
    href = escape(url) if url else "#"
    return "\n".join([
        "    <section class=\"sl-checkout-cta sl-external-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"external\">",
        f"      <a class=\"sl-cta\" href=\"{href}\" target=\"_blank\" rel=\"noopener noreferrer\">{label}</a>",
        "    </section>",
    ])


def render_download_cta(cta: dict[str, str]) -> str:
    """Download CTA: a button that downloads the target file (a free lead-magnet / digital file). The
    `download` attribute prompts a save; the browser owns execution — no JS needed."""
    url = cta["target"].strip()
    label = escape(cta["label"] or "Download")
    href = escape(url) if url else "#"
    return "\n".join([
        "    <section class=\"sl-checkout-cta sl-download-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"download\">",
        f"      <a class=\"sl-cta\" href=\"{href}\" download rel=\"noopener\">{label}</a>",
        "    </section>",
    ])


def render_booking_cta(cta: dict[str, str], api_base_url: str | None, offer: dict[str, Any] | None = None) -> str:
    """Booking CTA: a button that reveals an inline booking calendar. The JS island (page interactions)
    drives the same public availability -> reserve -> checkout flow as the standalone /book page."""
    service_id = escape(cta["target"].strip())
    label = escape(cta["label"] or "Book Now")
    api_base = escape(str(api_base_url or "").rstrip("/"))
    booking_mode = "live" if str((offer or {}).get("stripe_mode") or "").strip().lower() == "live" else "test"
    return "\n".join([
        "    <section class=\"sl-checkout-cta sl-booking-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"booking\"",
        f"      data-booking-widget data-service-id=\"{service_id}\" data-api-base=\"{api_base}\" data-stripe-mode=\"{booking_mode}\">",
        f"      <button class=\"sl-cta\" type=\"button\" data-booking-reveal>{label}</button>",
        "      <div class=\"sl-booking-panel\" data-booking-panel hidden>",
        "        <div class=\"sl-booking-banner\" data-booking-banner role=\"status\" aria-live=\"polite\"></div>",
        "        <p class=\"sl-booking-heading\">Choose a time</p>",
        "        <div class=\"sl-booking-slots\" data-booking-slots>Loading available times…</div>",
        "        <input class=\"sl-lead-input\" type=\"text\" data-booking-name placeholder=\"Name\" autocomplete=\"name\" />",
        "        <input class=\"sl-lead-input\" type=\"email\" data-booking-email placeholder=\"Email\" autocomplete=\"email\" required />",
        "        <input class=\"sl-lead-input\" type=\"tel\" data-booking-phone placeholder=\"Phone (optional)\" autocomplete=\"tel\" />",
        "        <p class=\"sl-booking-consent\">By adding your phone number, you agree to receive SMS appointment reminders. Message &amp; data rates may apply; reply STOP to opt out.</p>",
        "        <button class=\"sl-cta\" type=\"button\" data-booking-confirm disabled>Select a time</button>",
        "      </div>",
        "    </section>",
    ])


def _offer_has_upsell_funnel(offer: dict[str, Any]) -> bool:
    """Whether the offer derives a post-purchase upsell funnel (offer.funnel.upsells → post-purchase upsell
    opportunities). Drives the checkout success_url into /post-checkout/next even when the page carries no inline
    post_checkout block, so an offer-derived funnel actually starts (plans/SALES_FUNNELS.md P2b)."""
    return any(
        str((opp.get("placement") or {}).get("surface") or "") == "upsell"
        for opp in stage_opportunities(offer or {}, STAGE_POST_PURCHASE)
    )


def checkout_context(
    page: dict[str, Any],
    offer: dict[str, Any],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    if not checkout_url:
        return {"href": "#checkout", "data": {}}

    parsed = urlparse(checkout_url)
    if parsed.netloc.endswith("stripe.com"):
        return {"href": checkout_url, "data": {}}

    first_item = (resolved_offer.get("items") or [{}])[0]
    product_id = str(first_item.get("product_id") or "")
    price_id = str(first_item.get("price_id") or "")
    quantity = str(first_item.get("quantity") or 1)
    fallback = build_checkout_url(
        checkout_url,
        page=page,
        offer=offer,
        product_id=product_id,
        price_id=price_id,
        quantity=quantity,
    )
    return {
        "href": fallback,
        "data": {
            "checkout-base-url": checkout_url,
            "checkout-mode": "live" if str(offer.get("stripe_mode") or "").strip().lower() == "live" else "test",
            "checkout-tenant-id": page.get("tenant_id") or offer.get("tenant_id") or "",
            "checkout-offer-id": offer.get("offer_id") or "",
            "checkout-page-id": page.get("page_id") or "",
            "checkout-product-id": product_id,
            "checkout-price-id": price_id,
            "checkout-quantity": quantity,
            "checkout-api-base-url": str(api_base_url or "").rstrip("/"),
            # Enter the funnel when the page has an inline post_checkout block OR the offer derives an upsell
            # funnel — so an offer-derived funnel starts even with no page.post_checkout (P2b).
            "checkout-has-post-checkout": "true" if (page.get("post_checkout") or _offer_has_upsell_funnel(offer)) else "false",
        },
    }


def checkout_return_url(outcome: str) -> str:
    """The Stripe return URL for the static CTA href: the page's canonical location + ?checkout=<outcome>
    when known, else the "{{success_url}}"/"{{cancel_url}}" placeholder the interactions script fills on
    load. Resolving it server-side keeps the out-of-the-box markup clean for crawlers and no-JS visitors."""
    canonical = _RENDER_STATE.get("canonical") or ""
    if canonical:
        separator = "&" if "?" in canonical else "?"
        return f"{canonical}{separator}checkout={outcome}"
    return "{{success_url}}" if outcome == "success" else "{{cancel_url}}"


def build_checkout_url(
    base_url: str,
    *,
    page: dict[str, Any],
    offer: dict[str, Any],
    product_id: str,
    price_id: str,
    quantity: str,
) -> str:
    if not base_url:
        return "#checkout"
    params = {
        "clientID": page.get("tenant_id") or offer.get("tenant_id") or "",
        "offer": offer.get("offer_id") or "",
        "page_id": page.get("page_id") or "",
        "product_id": product_id,
        "price_id": price_id,
        "quantity": quantity or "1",
        # The offer's Stripe mode travels on the Buy URL so a host-agnostic checkout resolves the mode from the
        # request (plans/STRIPE_MODE_DECOUPLING.md P4) — a test page checks out test, a live page checks out live.
        "mode": "live" if str(offer.get("stripe_mode") or "").strip().lower() == "live" else "test",
        # Real return URLs when we know the page's canonical location, so a crawler or a no-JS visitor sees a
        # resolved link instead of "{{success_url}}" literals. The interactions script still overrides these
        # from window.location on load (plans/ON_PAGE_SEO_REQUIREMENTS.md — clean out-of-the-box markup).
        "success_url": checkout_return_url("success"),
        "cancel_url": checkout_return_url("cancel"),
    }
    query = urlencode({key: value for key, value in params.items() if value})
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{query}" if query else base_url


LEGAL_FOOTER_LINKS = (
    ("terms", "Terms of Service", "terms_url"),
    ("privacy", "Privacy Policy", "privacy_url"),
    ("refund", "Refund Policy", "refund_url"),
)


def _legal_href(stored_url: Any, page_id: str, api_base_url: str) -> str:
    """Resolve a footer legal link: honor an explicit absolute URL, else point at the
    platform legal page. Empty values and bare-anchor placeholders (e.g. '#terms') are
    treated as unset and default to {api_base_url}/legal/{page_id}."""
    stored = str(stored_url or "").strip()
    if stored.startswith("http://") or stored.startswith("https://"):
        return stored
    base = str(api_base_url or "").rstrip("/")
    return f"{base}/legal/{page_id}" if base else ""


def render_legal_footer(legal: dict[str, Any], section: dict[str, Any] | None = None, api_base_url: str = "") -> str:
    rendered_links = [
        f"      <a href=\"{escape(href)}\" target=\"_blank\" rel=\"noopener\">{label}</a>"
        for page_id, label, field in LEGAL_FOOTER_LINKS
        if (href := _legal_href(legal.get(field), page_id, api_base_url))
    ]
    copyright_text = (section or {}).get("copyright")
    if not rendered_links and not copyright_text:
        return ""
    return "\n".join([
        "    <footer class=\"sl-legal\" data-section-type=\"legal_footer\">",
        *rendered_links,
        f"      <span>{render_copyright_text(str(copyright_text))}</span>" if copyright_text else "",
        "    </footer>",
    ])


def render_copyright_text(value: str) -> str:
    if CURRENT_YEAR_TOKEN not in value:
        return escape(value)
    return "<span data-sl-current-year></span>".join(escape(part) for part in value.split(CURRENT_YEAR_TOKEN))


def render_analytics_tags(analytics: dict[str, Any]) -> str:
    tags: list[str] = []
    google_tag_id = analytics.get("google_tag_id")
    pixel_id = analytics.get("pixel_id")
    if google_tag_id:
        tags.append(f"  <meta name=\"sl-google-tag-id\" content=\"{escape(str(google_tag_id))}\">")
    if pixel_id:
        tags.append(f"  <meta name=\"sl-meta-pixel-id\" content=\"{escape(str(pixel_id))}\">")
    return "\n".join(tags)


def render_analytics_adapters(analytics: dict[str, Any]) -> str:
    """Load the configured pixels (GA4 / Meta) and subscribe them to the conversion event model — the first
    consumer of window.slConversion (plans/CONVERSION_CONTEXT.md). Analytics is a subscriber; it never
    touches a UI component. Maps semantic conversion:* events to standard e-commerce pixel events."""
    ga = re.sub(r"[^A-Za-z0-9_-]", "", str(analytics.get("google_tag_id") or ""))
    pixel = re.sub(r"[^A-Za-z0-9_-]", "", str(analytics.get("pixel_id") or ""))
    if not ga and not pixel:
        return ""
    lines = ["  <script>", "    (function () {", f"      var GA = '{ga}', PIXEL = '{pixel}';"]
    if ga:
        lines += [
            "      window.dataLayer = window.dataLayer || [];",
            "      function gtag(){ window.dataLayer.push(arguments); }",
            "      var g = document.createElement('script'); g.async = true; g.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA;",
            "      document.head.appendChild(g);",
            "      gtag('js', new Date()); gtag('config', GA);",
        ]
    if pixel:
        lines += [
            "      (function (f, b, e, v, n, t, s) { if (f.fbq) return; n = f.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); }; if (!f._fbq) f._fbq = n; n.push = n; n.loaded = true; n.version = '2.0'; n.queue = []; t = b.createElement(e); t.async = true; t.src = v; s = b.getElementsByTagName(e)[0]; s.parentNode.insertBefore(t, s); })(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');",
            "      window.fbq('init', PIXEL); window.fbq('track', 'PageView');",
        ]
    lines += [
        "      var money = function (t) { return { value: (Number((t && t.amount) || 0) / 100), currency: String((t && t.currency) || 'usd').toUpperCase() }; };",
        "      document.addEventListener('DOMContentLoaded', function () {",
        "        var C = window.slConversion; if (!C) return;",
        "        C.on('conversion:itemChanged', function (e) { var t = e.target || {}, m = money(t);",
        "          if (GA && window.gtag) gtag('event', 'view_item', { items: [{ item_id: t.product_id, price: m.value }] });",
        "          if (PIXEL && window.fbq) fbq('track', 'ViewContent', { content_ids: [t.product_id], value: m.value, currency: m.currency });",
        "        });",
        "        C.on('conversion:ctaInvoked', function (e) { var t = e.target || {}, m = money(t);",
        "          if (e.ctaType === 'add_to_cart') {",
        "            if (GA && window.gtag) gtag('event', 'add_to_cart', { items: [{ item_id: t.product_id, price: m.value }] });",
        "            if (PIXEL && window.fbq) fbq('track', 'AddToCart', { content_ids: [t.product_id], value: m.value, currency: m.currency });",
        "          }",
        "        });",
        "        C.on('conversion:checkoutStarted', function (e) { var m = money((e.targets || [])[0]);",
        "          if (GA && window.gtag) gtag('event', 'begin_checkout', { value: m.value, currency: m.currency });",
        "          if (PIXEL && window.fbq) fbq('track', 'InitiateCheckout', { value: m.value, currency: m.currency });",
        "        });",
        "        C.on('conversion:checkoutCompleted', function (e) {",
        "          if (GA && window.gtag) gtag('event', 'purchase', { transaction_id: e && e.orderId });",
        "          if (PIXEL && window.fbq) fbq('track', 'Purchase', { value: (e && e.total || 0) / 100 });",
        "        });",
        "      });",
        "    })();",
        "  </script>",
    ]
    return "\n".join(lines)


def render_favicon_tags(seo: dict[str, Any], default_url: str = "") -> str:
    favicon_url = str(seo.get("favicon_url") or default_url).strip()
    if not favicon_url:
        return ""  # no tenant favicon and no configured default — emit nothing rather than a broken empty href
    favicon_url = escape(favicon_url)
    return "\n".join([
        f"  <link rel=\"icon\" href=\"{favicon_url}\">",
        f"  <link rel=\"shortcut icon\" href=\"{favicon_url}\">",
        f"  <link rel=\"apple-touch-icon\" href=\"{favicon_url}\">",
    ])


def render_page_interactions_script(page: dict[str, Any]) -> str:
    has_countdown = any(section.get("type") == "countdown_timer" for section in page.get("sections", []))
    has_price_selector = any(section.get("type") == "offer_price_selector" for section in page.get("sections", []))
    has_checkout_cta = any(section.get("type") == "checkout_cta" for section in page.get("sections", []))
    has_current_year = any(
        section.get("type") == "legal_footer" and CURRENT_YEAR_TOKEN in str(section.get("copyright") or "")
        for section in page.get("sections", [])
    )
    has_hero_carousel = any(
        section.get("type") == "hero_media" and len(section.get("images") or []) > 1
        for section in page.get("sections", [])
    )
    has_pp_carousel = any(section.get("type") == "post_purchase_carousel" for section in page.get("sections", []))
    has_video_embed = any(
        parse_video_embed(url)
        for section in page.get("sections", [])
        for url in (section.get("images") or [])
    )
    has_before_after = any(
        section.get("type") == "before_after"
        and str(section.get("before_url") or "").strip()
        and str(section.get("after_url") or "").strip()
        for section in page.get("sections", [])
    )
    has_ribbon_download = any(
        section.get("type") == "page_ribbon"
        and str(((section.get("cta") or {}).get("action")) or "") == "download"
        for section in page.get("sections", [])
    )
    if not any([has_countdown, has_price_selector, has_current_year, has_checkout_cta, has_hero_carousel, has_pp_carousel, has_ribbon_download, has_before_after, has_video_embed]):
        return ""
    page_id = escape(str(page.get("page_id") or "page"))
    return "\n".join([
        "  <script>",
        "    document.addEventListener('DOMContentLoaded', () => {",
        "      document.querySelectorAll('[data-sl-current-year]').forEach((node) => {",
        "        node.textContent = String(new Date().getFullYear());",
        "      });",
        # BEFORE / AFTER. The range input already handles drag, touch, click-to-jump, keyboard and
        # assistive technology; all that is left is moving its value into the custom property the clip-path
        # and the handle read. Without this the divider simply stays where the tenant authored it, which is
        # a legible side-by-side rather than a broken control.
        # VIDEO EMBED. The provider's iframe -- a megabyte of script and third-party cookies -- is not
        # loaded until a visitor asks for it. Replacing the facade rather than layering over it means the
        # poster stops competing for the frame, and autoplay is honoured because the click IS the gesture
        # the browser requires.
        "      document.querySelectorAll('[data-sl-embed]').forEach((box) => {",
        "        const play = box.querySelector('.sl-embed-play');",
        "        if (!play) return;",
        "        play.addEventListener('click', () => {",
        "          const frame = document.createElement('iframe');",
        "          frame.src = box.dataset.slEmbed;",
        "          frame.title = box.dataset.embedTitle || 'Video';",
        "          frame.allow = 'accelerometer; autoplay; encrypted-media; picture-in-picture; web-share';",
        "          frame.referrerPolicy = 'strict-origin-when-cross-origin';",
        "          frame.allowFullscreen = true;",
        "          box.replaceChildren(frame);",
        "        });",
        "      });",
        "      document.querySelectorAll('[data-sl-before-after]').forEach((frame) => {",
        "        const range = frame.querySelector('.sl-ba-range');",
        "        if (!range) return;",
        "        const sync = () => frame.style.setProperty('--sl-ba-pos', range.value + '%');",
        "        range.addEventListener('input', sync);",
        "        sync();",
        "      });",
        # PAGE RIBBON DOWNLOAD. The URL is minted per click -- short-lived and presigned -- so this is a
        # button rather than a link. When the ribbon collects details a small dialog gates the request;
        # the SERVER still decides what is required, this only saves a pointless round trip. Built with DOM
        # calls rather than innerHTML so no field label can ever be markup.
        "      document.querySelectorAll('[data-sl-download]').forEach((btn) => {",
        "        const wanted = (btn.dataset.collect || '').split(',').filter(Boolean);",
        "        const LABELS = { email: 'Email address', phone: 'Phone number' };",
        "        const send = (fields, onError, onDone, onSent) => {",
        "          if (btn.disabled) return;",
        # Disabled IMMEDIATELY, and left that way on success. A download navigates to an attachment URL,
        # which does NOT leave the page — so without this the button is still live afterwards and a second
        # click mints a second signed URL, downloads the file again, and records a second lead.
        "          btn.disabled = true;",
        "          fetch(btn.dataset.endpoint, {",
        "            method: 'POST', headers: { 'Content-Type': 'application/json' },",
        "            body: JSON.stringify({",
        "              tenant_id: btn.dataset.tenantId, page_id: btn.dataset.pageId,",
        "              section_id: btn.dataset.sectionId, mode: btn.dataset.stripeMode || 'test',",
        "              fields: fields, company_website: fields.company_website || '',",
        "              idempotency_key: btn.dataset.pageId + '-' + btn.dataset.sectionId + '-' + (fields.email || fields.phone || Date.now()),",
        "            }),",
        "          }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))",
        "            .then((data) => {",
        "              if (data && data.url) { if (onDone) onDone(); window.location.href = data.url; return; }",
        # Emailed: there is nothing to navigate to, so say so where the visitor is looking. Without this the
        # dialog would just close and they would have no idea whether anything happened.
        "              if (onSent) onSent(); else if (onDone) onDone();",
        "            })",
        # Re-enabled ONLY on failure: nothing was delivered, so the visitor should be able to try again.
        "            .catch((err) => { btn.disabled = false; if (onError) onError(err); });",
        "        };",
        "        btn.addEventListener('click', () => {",
        "          if (!wanted.length) { send({}); return; }",
        "          const backdrop = document.createElement('div');",
        "          backdrop.className = 'sl-dl-backdrop';",
        "          const form = document.createElement('form');",
        "          form.className = 'sl-dl-card';",
        "          const title = document.createElement('p');",
        "          title.className = 'sl-dl-title';",
        "          title.textContent = 'Where should we send it?';",
        "          form.appendChild(title);",
        "          wanted.forEach((name) => {",
        "            const label = document.createElement('label');",
        "            label.className = 'sl-dl-field';",
        "            const span = document.createElement('span');",
        "            span.textContent = LABELS[name] || name;",
        "            const input = document.createElement('input');",
        "            input.name = name;",
        "            input.type = name === 'email' ? 'email' : 'tel';",
        "            input.required = true;",
        "            input.autocomplete = name === 'email' ? 'email' : 'tel';",
        "            label.appendChild(span); label.appendChild(input); form.appendChild(label);",
        "          });",
        "          const hp = document.createElement('input');",
        "          hp.className = 'sl-hp'; hp.name = 'company_website'; hp.tabIndex = -1;",
        "          hp.autocomplete = 'off'; hp.setAttribute('aria-hidden', 'true');",
        "          form.appendChild(hp);",
        "          const error = document.createElement('p');",
        "          error.className = 'sl-dl-error'; error.hidden = true;",
        "          error.textContent = 'Something went wrong. Please try again.';",
        "          form.appendChild(error);",
        "          const actions = document.createElement('div');",
        "          actions.className = 'sl-dl-actions';",
        "          const cancel = document.createElement('button');",
        "          cancel.type = 'button'; cancel.className = 'sl-dl-cancel'; cancel.textContent = 'Cancel';",
        "          const submit = document.createElement('button');",
        "          submit.type = 'submit'; submit.className = 'sl-dl-submit'; submit.textContent = 'Get it';",
        "          actions.appendChild(cancel); actions.appendChild(submit); form.appendChild(actions);",
        "          backdrop.appendChild(form);",
        "          document.body.appendChild(backdrop);",
        "          const close = () => backdrop.remove();",
        "          cancel.addEventListener('click', close);",
        "          backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });",
        "          document.addEventListener('keydown', function esc(e) {",
        "            if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }",
        "          });",
        "          const first = form.querySelector('input:not(.sl-hp)');",
        "          if (first) first.focus();",
        "          form.addEventListener('submit', (e) => {",
        "            e.preventDefault();",
        "            const fields = {};",
        "            form.querySelectorAll('input').forEach((i) => { if (i.value.trim()) fields[i.name] = i.value.trim(); });",
        "            error.hidden = true;",
        "            submit.disabled = true;",
        "            send(fields,",
        "              (err) => {",
        "                error.textContent = String(err && err.message) === '409'",
        "                  ? 'This is not available right now. Please try again later.'",
        "                  : 'Something went wrong. Please try again.';",
        "                error.hidden = false; submit.disabled = false;",
        "              },",
        "              () => close(),",
        "              () => {",
        "                form.querySelectorAll('.sl-dl-field,.sl-dl-actions').forEach((el) => el.remove());",
        "                title.textContent = 'Check your inbox — it is on its way.';",
        # Confirmed notices should not need dismissing, but must be dismissable: 3s is long enough to read
        # one line and short enough not to sit over the page. The X gives back control to anyone faster.
        "                const dismiss = document.createElement('button');",
        "                dismiss.type = 'button';",
        "                dismiss.className = 'sl-dl-dismiss';",
        "                dismiss.setAttribute('aria-label', 'Dismiss');",
        "                dismiss.textContent = '\\u00d7';",
        "                dismiss.addEventListener('click', close);",
        "                form.appendChild(dismiss);",
        "                setTimeout(close, 3000);",
        "              });",
        "          });",
        "        });",
        "      });",
        # Inline lead-capture form: POST to /leads, honeypot on the server, show a thank-you on success.
        "      const leadForm = document.querySelector('[data-lead-form]');",
        "      if (leadForm) {",
        "        const statusEl = leadForm.querySelector('[data-lead-status]');",
        "        const idempotencyKey = `${leadForm.dataset.pageId || 'p'}-${Date.now()}-${Math.random().toString(36).slice(2)}`;",
        "        leadForm.addEventListener('submit', (event) => {",
        "          event.preventDefault();",
        "          const submitBtn = leadForm.querySelector('button[type=\"submit\"]');",
        "          if (submitBtn && submitBtn.dataset.busy === 'true') return;",
        "          const fields = {};",
        "          leadForm.querySelectorAll('.sl-lead-input').forEach((input) => {",
        "            if (input.name && input.value.trim()) fields[input.name] = input.value.trim();",
        "          });",
        "          const consent = {};",
        "          leadForm.querySelectorAll('[data-consent]').forEach((box) => {",
        "            consent[box.dataset.consent] = { granted: box.checked, text: box.dataset.consentText || '' };",
        "          });",
        "          const hp = leadForm.querySelector('.sl-hp');",
        "          const payload = {",
        "            tenant_id: leadForm.dataset.tenantId, offer_id: leadForm.dataset.offerId,",
        "            mode: leadForm.dataset.stripeMode || 'test',",
        "            page_id: leadForm.dataset.pageId, fields, consent, idempotency_key: idempotencyKey,",
        "            company_website: hp ? hp.value : '',",
        "          };",
        "          if (statusEl) { statusEl.classList.remove('is-error'); statusEl.textContent = 'Sending...'; }",
        "          if (submitBtn) { submitBtn.dataset.busy = 'true'; submitBtn.classList.add('is-connecting'); }",
        "          fetch(leadForm.dataset.endpoint, {",
        "            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),",
        "          }).then((response) => {",
        "            if (!response.ok && response.status !== 202) throw new Error('failed');",
        "            leadForm.querySelectorAll('.sl-lead-input,.sl-lead-consent,button[type=\"submit\"]').forEach((el) => el.remove());",
        "            if (statusEl) statusEl.textContent = 'Thanks! We\\'ll be in touch shortly.';",
        "          }).catch(() => {",
        "            if (statusEl) { statusEl.classList.add('is-error'); statusEl.textContent = 'Something went wrong. Please try again.'; }",
        "            if (submitBtn) { submitBtn.dataset.busy = 'false'; submitBtn.classList.remove('is-connecting'); }",
        "          });",
        "        });",
        "      }",
        # Inline booking widget: reveal on click, then drive availability -> reserve -> checkout (same
        # public flow as the standalone /book page), cross-origin to the API base.
        "      const bookingWidget = document.querySelector('[data-booking-widget]');",
        "      if (bookingWidget) {",
        "        const serviceId = bookingWidget.dataset.serviceId;",
        "        const bookingMode = bookingWidget.dataset.stripeMode || 'test';",
        "        const apiBase = (bookingWidget.dataset.apiBase || '').replace(/\\/$/, '');",
        "        const panel = bookingWidget.querySelector('[data-booking-panel]');",
        "        const revealBtn = bookingWidget.querySelector('[data-booking-reveal]');",
        "        const slotsHost = bookingWidget.querySelector('[data-booking-slots]');",
        "        const confirmBtn = bookingWidget.querySelector('[data-booking-confirm]');",
        "        const bookingBanner = bookingWidget.querySelector('[data-booking-banner]');",
        "        let selectedSlot = null; let selectedFulfiller = null; let slotsLoaded = false;",
        "        const bookingError = (text) => { bookingBanner.className = 'sl-booking-banner is-error'; bookingBanner.textContent = text; };",
        "        const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });",
        "        const fmtDay = (iso) => new Date(iso).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });",
        "        const renderSlots = (slots) => {",
        "          if (!slots.length) { slotsHost.className = 'sl-booking-slots is-empty'; slotsHost.textContent = 'No available times in the next two weeks.'; return; }",
        "          const byDay = {};",
        "          slots.forEach((s) => { const k = new Date(s.start).toDateString(); (byDay[k] = byDay[k] || []).push(s); });",
        "          slotsHost.className = 'sl-booking-slots'; slotsHost.innerHTML = '';",
        "          Object.keys(byDay).forEach((k) => {",
        "            const group = byDay[k];",
        "            const day = document.createElement('div'); day.className = 'sl-booking-day';",
        "            const h = document.createElement('h4'); h.textContent = fmtDay(group[0].start); day.appendChild(h);",
        "            const row = document.createElement('div'); row.className = 'sl-booking-times';",
        "            group.forEach((s) => {",
        "              const b = document.createElement('button'); b.type = 'button'; b.className = 'sl-booking-slot'; b.textContent = fmtTime(s.start);",
        "              b.addEventListener('click', () => {",
        "                selectedSlot = s.start; selectedFulfiller = s.fulfiller_id || null;",
        "                bookingWidget.querySelectorAll('.sl-booking-slot').forEach((el) => el.classList.remove('selected'));",
        "                b.classList.add('selected'); confirmBtn.disabled = false; confirmBtn.textContent = 'Book ' + fmtTime(s.start);",
        "              });",
        "              row.appendChild(b);",
        "            });",
        "            day.appendChild(row); slotsHost.appendChild(day);",
        "          });",
        "        };",
        "        const loadSlots = () => {",
        "          const from = Math.floor(Date.now() / 1000); const to = from + 14 * 86400;",
        "          fetch(`${apiBase}/services/${encodeURIComponent(serviceId)}/availability?from=${from}&to=${to}&mode=${encodeURIComponent(bookingMode)}`)",
        "            .then((r) => r.json()).then((d) => renderSlots(d.slots || []))",
        "            .catch(() => { slotsHost.textContent = 'Could not load times.'; });",
        "        };",
        "        revealBtn.addEventListener('click', () => {",
        "          panel.hidden = false; revealBtn.style.display = 'none';",
        "          if (!slotsLoaded) { slotsLoaded = true; loadSlots(); }",
        "        });",
        "        confirmBtn.addEventListener('click', () => {",
        "          bookingBanner.textContent = '';",
        "          const email = (bookingWidget.querySelector('[data-booking-email]').value || '').trim();",
        "          if (!selectedSlot) return;",
        "          if (!email) { bookingError('Please enter your email.'); return; }",
        "          const customer = {",
        "            name: (bookingWidget.querySelector('[data-booking-name]').value || '').trim(), email,",
        "            phone: (bookingWidget.querySelector('[data-booking-phone]').value || '').trim(),",
        "          };",
        "          const body = { service_id: serviceId, mode: bookingMode, slot_start: selectedSlot, customer };",
        "          if (selectedFulfiller) body.fulfiller_id = selectedFulfiller;",
        "          confirmBtn.disabled = true; confirmBtn.textContent = 'Reserving...';",
        "          const base = window.location.href.split('?')[0];",
        "          fetch(`${apiBase}/services/appointments/reserve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })",
        "            .then((r) => r.json().then((j) => ({ ok: r.ok, j })))",
        "            .then((res) => {",
        "              if (!res.ok) throw new Error(res.j.message || 'That time is no longer available.');",
        "              return fetch(`${apiBase}/services/appointments/checkout`, { method: 'POST', headers: { 'Content-Type': 'application/json' },",
        "                body: JSON.stringify({ appointment_id: res.j.appointment.appointment_id, manage_token: res.j.manage_token, mode: bookingMode, success_url: base + '?booking=success', cancel_url: base + '?booking=cancel' }) }).then((r) => r.json());",
        "            })",
        "            .then((checkout) => {",
        "              if (checkout.checkout_url) { window.location = checkout.checkout_url; }",
        "              else if (checkout.status === 'booked') { panel.innerHTML = '<div class=\"sl-booking-banner\">Your booking is confirmed — check your email for details.</div>'; }",
        "              else { throw new Error(checkout.message || 'Could not complete booking.'); }",
        "            })",
        "            .catch((e) => { bookingError(e.message); confirmBtn.disabled = false; confirmBtn.textContent = 'Book'; loadSlots(); });",
        "        });",
        "        if (new URLSearchParams(window.location.search).get('booking') === 'success') {",
        "          panel.hidden = false; revealBtn.style.display = 'none';",
        "          panel.innerHTML = '<div class=\"sl-booking-banner\">Your booking is confirmed — check your email for details.</div>';",
        "        }",
        "      }",
        # Conversion island (plans/CONVERSION_CONTEXT.md): one shared currentTargetIndex. Reads the single
        # embedded OfferView payload; on target change writes every [data-conversion-bind] from it and emits
        # semantic conversion:* events. Analytics/pixels subscribe via window.slConversion.on — no UI coupling.
        "      const convEl = document.querySelector('[data-conversion-offer]');",
        "      let convTargets = [];",
        "      try { convTargets = JSON.parse((convEl && convEl.textContent) || '[]'); } catch (e) { convTargets = []; }",
        "      if (convTargets.length) {",
        "        const subs = {};",
        "        const emit = (name, payload) => { (subs[name] || []).forEach((fn) => { try { fn(payload); } catch (e) {} }); };",
        "        const on = (name, fn) => { (subs[name] = subs[name] || []).push(fn); return () => { subs[name] = (subs[name] || []).filter((f) => f !== fn); }; };",
        "        let currentIndex = 0;",
        "        const fmt = (cents, currency) => { const c = String(currency||'usd').toUpperCase(); const v = (Number(cents||0)/100).toFixed(2); return c === 'USD' ? ('$'+v) : (c+' '+v); };",
        "        const binders = {",
        "          headline: (el, t) => { el.textContent = t.headline || ''; },",
        "          subheadline: (el, t) => { el.textContent = t.subheadline || ''; },",
        "          price: (el, t) => { el.textContent = fmt(t.amount, t.currency); },",
        "          compare_at: (el, t) => { el.textContent = (Number(t.compare_at) > Number(t.amount)) ? fmt(t.compare_at, t.currency) : ''; },",
        "          discount: (el, t) => { el.textContent = (Number(t.discount) > 0) ? ('-' + t.discount + '%') : ''; },",
        "          savings: (el, t) => { el.textContent = (Number(t.discount) > 0) ? ('Save ' + t.discount + '%') : ''; },",
        "          sale_badge: (el, t) => { el.textContent = t.sale_badge || ''; },",
        "          hero_image: (el, t) => { if (t.hero_image) el.setAttribute('src', t.hero_image); },",
        "        };",
        "        const applyTarget = (index) => {",
        "          if (index < 0 || index >= convTargets.length) return;",
        "          currentIndex = index;",
        "          const t = convTargets[index];",
        "          document.querySelectorAll('[data-conversion-bind]').forEach((el) => { const b = binders[el.dataset.conversionBind]; if (b) b(el, t); });",
        # Context-aware lists: rebuild each [data-conversion-list] from the current target's array so
        # blocks (gallery, badges, and later per-product reviews/FAQ) swap as the target changes.
        "          document.querySelectorAll('[data-conversion-list]').forEach((el) => {",
        "            const name = el.dataset.conversionList; const arr = (t && t[name]) || [];",
        "            el.innerHTML = '';",
        "            arr.forEach((v) => {",
        "              let node;",
        "              if (name === 'gallery') { node = document.createElement('img'); node.src = v; node.className = 'sl-details-thumb'; node.loading = 'lazy'; node.alt = ''; }",
        "              else { node = document.createElement('span'); node.className = 'sl-details-badge'; node.textContent = v; }",
        "              el.appendChild(node);",
        "            });",
        "            el.style.display = arr.length ? '' : 'none';",
        "          });",
        "        };",
        "        window.slConversion = { on: on, emit: emit, targets: convTargets, get index() { return currentIndex; }, get target() { return convTargets[currentIndex]; } };",
        # The hero_media carousel is the single carousel; it drives the current target.
        "        const convTrack = document.querySelector('[data-hero-track]');",
        "        if (convTrack) {",
        "          let convTimer = null;",
        "          convTrack.addEventListener('scroll', () => {",
        "            window.clearTimeout(convTimer);",
        "            convTimer = window.setTimeout(() => {",
        "              const index = Math.round(convTrack.scrollLeft / convTrack.clientWidth);",
        "              if (index !== currentIndex) { applyTarget(index); emit('conversion:itemChanged', { index: index, target: convTargets[index] }); }",
        "            }, 60);",
        "          });",
        "        }",
        # Listicle cart: server-backed (POST/GET/DELETE {api_base}/cart) with a localStorage fallback so the
        # page still works if the cart API is unreachable. Adds the CURRENT carousel target.
        "        const listicle = document.querySelector('[data-listicle]');",
        "        if (listicle) {",
        "          const offerId = listicle.dataset.offerId || 'offer';",
        "          const tenantId = listicle.dataset.tenantId || '';",
        "          const cartMode = listicle.dataset.stripeMode || 'test';",  # Stripe mode travels with every cart call
        "          const cartEndpoint = listicle.dataset.cartEndpoint || '';",
        "          const serverEnabled = !!(cartEndpoint && tenantId);",
        "          const ctToken = (new URLSearchParams(window.location.search)).get('ct') || '';",  # identified-link token

        "          const idKey = 'sl_cart_id_' + offerId;",              # server cart id
        "          const fallbackKey = 'sl_cart_' + offerId;",           # L1 offline items
        "          const getCartId = () => { try { return localStorage.getItem(idKey) || ''; } catch (e) { return ''; } };",
        "          const setCartId = (id) => { try { if (id) localStorage.setItem(idKey, id); } catch (e) {} };",
        "          const readFallback = () => { try { return JSON.parse(localStorage.getItem(fallbackKey) || '[]'); } catch (e) { return []; } };",
        "          const writeFallback = (c) => { try { localStorage.setItem(fallbackKey, JSON.stringify(c)); } catch (e) {} };",
        "          let serverCart = null;",
        "          const minicart = document.querySelector('[data-minicart]');",
        "          const minicartSummary = minicart && minicart.querySelector('[data-minicart-summary]');",
        "          const minicartLines = minicart && minicart.querySelector('[data-minicart-lines]');",
        "          const renderMinicart = () => {",
        "            if (!minicart) return;",
        "            let lines, count, total, currency;",
        "            if (serverCart) { lines = serverCart.line_items || []; count = serverCart.item_count || 0; total = serverCart.total_amount || 0; currency = serverCart.currency || 'usd'; }",
        "            else { lines = readFallback(); count = lines.reduce((n, i) => n + (i.qty||1), 0); total = lines.reduce((s, i) => s + ((i.unit_amount!=null?i.unit_amount:i.amount)||0) * (i.qty||1), 0); currency = (lines[0] && lines[0].currency) || 'usd'; }",
        # Broadcast the running total so the BNPL messaging can finance the CART TOTAL (not just the shown item).
        # Also stash it on the bus so a subscriber that mounts AFTER this fired (async hydrate races) can still read it.
        "            if (window.slConversion) { window.slConversion.cartTotal = total; window.slConversion.cartCount = count; if (window.slConversion.emit) window.slConversion.emit('conversion:cartChanged', { total: total, count: count, currency: currency }); }",
        "            if (count <= 0) { minicart.classList.remove('is-visible'); if (minicartLines) minicartLines.innerHTML = ''; return; }",
        "            minicart.classList.add('is-visible');",
        "            if (minicartSummary) minicartSummary.textContent = 'Cart (' + count + ') \\u00b7 ' + fmt(total, currency);",
        "            if (minicartLines) {",
        "              minicartLines.innerHTML = '';",
        "              lines.forEach((ln, idx) => {",
        "                const amt = (ln.unit_amount != null ? ln.unit_amount : (ln.amount||0));",
        "                const row = document.createElement('div'); row.className = 'sl-minicart-line';",
        "                const nm = document.createElement('span'); nm.className = 'sl-minicart-line-name'; nm.textContent = ln.name || ''; row.appendChild(nm);",
        "                const qt = document.createElement('span'); qt.className = 'sl-minicart-line-qty'; qt.textContent = '\\u00d7' + (ln.qty||1); row.appendChild(qt);",
        "                const am = document.createElement('span'); am.className = 'sl-minicart-line-amt'; am.textContent = fmt(amt * (ln.qty||1), ln.currency || currency); row.appendChild(am);",
        "                const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'sl-minicart-remove'; rm.setAttribute('aria-label', 'Remove'); rm.textContent = '\\u00d7';",
        "                if (serverCart && ln.line_id && serverEnabled) { rm.addEventListener('click', () => removeLine(ln.line_id)); }",
        "                else { rm.addEventListener('click', () => removeFallback(idx)); }",
        "                row.appendChild(rm);",
        "                minicartLines.appendChild(row);",
        "              });",
        "            }",
        "          };",
        "          const applyServerCart = (data) => { if (data && data.cart) { serverCart = data.cart; if (data.cart_id) setCartId(data.cart_id); } renderMinicart(); };",
        "          const addFallback = (t) => { const cart = readFallback(); const existing = cart.find((i) => i.price_id === t.price_id); if (existing) existing.qty = (existing.qty||1) + 1; else cart.push({ product_id: t.product_id, price_id: t.price_id, name: t.headline, amount: Number(t.amount||0), currency: t.currency, qty: 1 }); writeFallback(cart); renderMinicart(); };",
        "          const removeFallback = (idx) => { const cart = readFallback(); if (idx >= 0 && idx < cart.length) { cart.splice(idx, 1); writeFallback(cart); } renderMinicart(); };",
        "          const removeLine = (lineId) => {",
        "            const id = getCartId(); if (!id || !serverEnabled) return;",
        "            fetch(cartEndpoint + '/items/' + encodeURIComponent(lineId) + '?tenant_id=' + encodeURIComponent(tenantId) + '&cart_id=' + encodeURIComponent(id) + '&mode=' + encodeURIComponent(cartMode), { method: 'DELETE' })",
        "              .then((r) => r.ok ? r.json() : Promise.reject(r)).then(applyServerCart).catch(() => {});",
        "          };",
        "          const addToCart = (t) => {",
        "            if (!serverEnabled) { addFallback(t); return; }",
        "            const body = { tenant_id: tenantId, offer_id: offerId, mode: cartMode, product_id: t.product_id || '', price_id: t.price_id || '', service_id: t.service_id || '', qty: 1, page_url: window.location.origin + window.location.pathname };",
        "            const id = getCartId(); if (id) body.cart_id = id;",
        "            if (ctToken) body.ct = ctToken;",

        "            fetch(cartEndpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })",
        "              .then((r) => r.ok ? r.json() : Promise.reject(r)).then(applyServerCart).catch(() => addFallback(t));",
        "          };",
        # Per-product tier blocks: the hero_media carousel drives the current product; show only its tier block
        # (toggled on conversion:itemChanged) so each product exposes its OWN tiers. Add reads the SHOWN block's
        # selected tier — so a multi-product carousel adds distinct products at chosen tiers (LANDING_CAROUSEL_FIXES).
        "          const tierBlocks = Array.from(listicle.querySelectorAll('[data-listicle-tiers]'));",
        "          const showTierBlock = (index) => { tierBlocks.forEach((b) => { b.hidden = Number(b.dataset.index || 0) !== index; }); };",
        "          const activeTierBlock = () => tierBlocks.find((b) => !b.hidden) || tierBlocks[0];",
        "          on('conversion:itemChanged', (e) => { if (e && typeof e.index === 'number') showTierBlock(e.index); });",
        "          const addBtn = listicle.querySelector('[data-listicle-add]');",
        "          if (addBtn) addBtn.addEventListener('click', () => {",
        "            const block = activeTierBlock(); if (!block) return;",
        "            const checked = block.querySelector('input[type=\"radio\"]:checked') || block.querySelector('input[type=\"radio\"]');",
        "            const card = checked ? checked.closest('.sl-price-option') : block.querySelector('.sl-price-option');",
        "            const t = {",
        "              product_id: block.dataset.productId || '',",
        "              price_id: (checked && checked.value) || (card && card.dataset.priceId) || '',",
        "              amount: card ? Number(card.dataset.saleAmount || 0) : 0,",
        "              currency: (card && card.dataset.currency) || 'usd',",
        "              headline: (card && card.dataset.label) || '',",
        "            };",
        "            addToCart(t);",
        "            emit('conversion:ctaInvoked', { ctaType: 'add_to_cart', target: t });",
        "            addBtn.textContent = 'Added \\u2713'; window.setTimeout(() => { addBtn.textContent = 'Add to cart'; }, 1200);",
        "          });",
        "          const checkoutBtn = minicart && minicart.querySelector('[data-minicart-checkout]');",
        "          if (checkoutBtn && !serverEnabled) checkoutBtn.style.display = 'none';",   # checkout needs the server cart
        "          if (checkoutBtn && serverEnabled) checkoutBtn.addEventListener('click', () => {",
        "            const id = getCartId(); if (!id) return;",
        "            checkoutBtn.disabled = true; checkoutBtn.textContent = 'Redirecting\\u2026';",
        "            const ret = window.location.origin + window.location.pathname;",
        # When the page has a post-checkout funnel, route success through {api}/pages/{page_id}/post-checkout/next
        # (mirrors the single-product CTA) so multi-product buyers enter the upsell/downsell funnel instead of
        # bouncing back to the landing page. {CHECKOUT_SESSION_ID} stays UNENCODED (Stripe substitutes it).
        "            let cartSuccessUrl = ret + '?checkout=success';",
        "            const cartApiBase = cartEndpoint.replace(/\\/cart$/, '');",
        "            const cartPageId = listicle.dataset.pageId || '';",
        "            if (listicle.dataset.hasPostCheckout === 'true' && cartApiBase && cartPageId) {",
        "              const nextp = new URLSearchParams(); nextp.set('outcome', 'accept'); if (tenantId) nextp.set('tenant_id', tenantId); nextp.set('origin', window.location.origin);",
        "              cartSuccessUrl = `${cartApiBase}/pages/${cartPageId}/post-checkout/next?${nextp.toString()}&session_id={CHECKOUT_SESSION_ID}`;",
        "            }",
        "            fetch(cartEndpoint + '/checkout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_id: tenantId, cart_id: id, mode: cartMode, page_id: cartPageId, success_url: cartSuccessUrl, cancel_url: ret + '?checkout=cancel' }) })",
        # Clear the LOCAL cart ONLY once Stripe hands off (we have a redirect url) so returning to the page shows
        # an empty cart, not the just-purchased items. The .catch keeps it on failure (retry still works). The
        # SERVER cart persists — the webhook marks it converted on payment via metadata[cart_id], or it stays
        # open for abandoned-cart recovery.
        # Always read the body (empty on parse failure) so a non-2xx carries its reason. A blocked checkout (e.g.
        # 403 from the publish guard) must SAY why, not fail silently — surface the server's message to the buyer.
        "              .then((r) => r.json().catch(() => ({})).then((d) => ({ ok: r.ok, d })))",
        "              .then(({ ok, d }) => { if (!ok) throw new Error((d && d.message) || 'Checkout is unavailable right now.'); if (d && d.url) { try { localStorage.removeItem(idKey); localStorage.removeItem(fallbackKey); } catch (e) {} serverCart = null; window.location.href = d.url; } else { throw new Error('Checkout is unavailable right now.'); } })",
        "              .catch((err) => { checkoutBtn.disabled = false; checkoutBtn.textContent = 'Checkout'; slNotice(err && err.message ? err.message : 'Checkout is unavailable right now.'); });",
        "          });",
        "          const hydrateFrom = (url) => fetch(url).then((r) => r.ok ? r.json() : Promise.reject(r)).then((d) => { if (d && d.cart) { serverCart = d.cart; if (d.cart.cart_id) setCartId(d.cart.cart_id); } renderMinicart(); }).catch(renderMinicart);",
        "          const existingId = getCartId();",
        "          if (serverEnabled && ctToken) {",
        # Recovery/identified link: resolve the token to its cart so it rehydrates on ANY device.
        "            hydrateFrom(cartEndpoint + '?tenant_id=' + encodeURIComponent(tenantId) + '&mode=' + encodeURIComponent(cartMode) + '&ct=' + encodeURIComponent(ctToken));",
        "          } else if (serverEnabled && existingId) {",
        "            hydrateFrom(cartEndpoint + '?tenant_id=' + encodeURIComponent(tenantId) + '&cart_id=' + encodeURIComponent(existingId) + '&mode=' + encodeURIComponent(cartMode));",
        "          } else { renderMinicart(); }",
        "        }",
        "        applyTarget(0);",
        "      }",
        # Hero media carousel: prev/next arrows, tappable dots, a counter, all synced to scroll position.
        "      const heroCarousel = document.querySelector('[data-hero-carousel]');",
        "      if (heroCarousel) {",
        "        const heroTrack = heroCarousel.querySelector('[data-hero-track]');",
        "        const heroDots = Array.from(heroCarousel.querySelectorAll('[data-hero-dot]'));",
        "        const heroCounter = heroCarousel.querySelector('[data-hero-counter]');",
        "        const heroCount = heroCarousel.querySelectorAll('.sl-hero-slide').length;",
        "        let heroIndex = 0;",
        "        const heroSync = (index) => {",
        "          heroIndex = index;",
        "          heroDots.forEach((dot, i) => dot.classList.toggle('is-active', i === index));",
        "          if (heroCounter) heroCounter.textContent = (index + 1) + ' / ' + heroCount;",
        "        };",
        # heroGo scrolls AND syncs the dots/counter immediately — don't rely on the scroll listener, whose
        # own guard would skip the update once heroIndex is set.
        # Wrap around (loop) so next past the last item returns to the first and prev past the first goes to
        # the last — matches the builder preview's modulo navigation.
        "        const heroGo = (index) => { const i = ((index % heroCount) + heroCount) % heroCount; if (heroTrack) heroTrack.scrollTo({ left: i * heroTrack.clientWidth, behavior: 'smooth' }); heroSync(i); };",
        "        const heroPrev = heroCarousel.querySelector('[data-hero-prev]');",
        "        const heroNext = heroCarousel.querySelector('[data-hero-next]');",
        "        if (heroPrev) heroPrev.addEventListener('click', () => heroGo(heroIndex - 1));",
        "        if (heroNext) heroNext.addEventListener('click', () => heroGo(heroIndex + 1));",
        "        heroDots.forEach((dot, i) => dot.addEventListener('click', () => heroGo(i)));",
        "        if (heroTrack) {",
        "          let heroTimer = null;",
        "          heroTrack.addEventListener('scroll', () => {",
        "            window.clearTimeout(heroTimer);",
        "            heroTimer = window.setTimeout(() => { const i = Math.round(heroTrack.scrollLeft / heroTrack.clientWidth); if (i !== heroIndex) heroSync(i); }, 60);",
        "          });",
        "        }",
        "      }",
        f"      const pageId = \"{page_id}\";",
        "      const money = (amount, currency) => {",
        "        const cents = Number(amount || 0);",
        "        const code = String(currency || 'usd').toUpperCase();",
        "        if (code === 'USD') return `$${(cents / 100).toFixed(2)}`;",
        "        return `${code} ${(cents / 100).toFixed(2)}`;",
        "      };",
        # A themed in-page notice modal (the server-rendered page can't use the dashboard's ConfirmDialog.vue),
        # built lazily on first use. Replaces window.alert so a blocked action reads as part of the page.
        "      const slNotice = (message) => {",
        "        let overlay = document.querySelector('.sl-notice-backdrop');",
        "        if (!overlay) {",
        "          overlay = document.createElement('div');",
        "          overlay.className = 'sl-notice-backdrop';",
        "          overlay.innerHTML = '<div class=\"sl-notice-card\" role=\"alertdialog\" aria-modal=\"true\"><div class=\"sl-notice-icon\" aria-hidden=\"true\">!</div><p class=\"sl-notice-msg\"></p><button type=\"button\" class=\"sl-notice-ok\">OK</button></div>';",
        "          document.body.appendChild(overlay);",
        "          const close = () => overlay.classList.remove('is-visible');",
        "          overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });",
        "          overlay.querySelector('.sl-notice-ok').addEventListener('click', close);",
        "        }",
        "        overlay.querySelector('.sl-notice-msg').textContent = String(message || '');",
        "        overlay.classList.add('is-visible');",
        "        const ok = overlay.querySelector('.sl-notice-ok'); if (ok) ok.focus();",
        "      };",
        "      const ctaSection = document.querySelector('[data-section-type=\"checkout_cta\"]');",
        "      const ctaType = (ctaSection && ctaSection.dataset.ctaType) || 'buy';",
        "      const cta = ctaType === 'buy' ? document.querySelector('[data-section-type=\"checkout_cta\"] .sl-cta') : null;",
        "      const declineCta = document.querySelector('[data-section-type=\"checkout_cta\"] .sl-decline-cta');",
        "      const cards = Array.from(document.querySelectorAll('.sl-price-option'));",
        "      const pageUrl = () => `${window.location.origin}${window.location.pathname}`;",
        "      const funnelParams = new URLSearchParams(window.location.search);",
        "      const funnelPageId = funnelParams.get('funnel_page') || '';",
        "      const funnelStepId = funnelParams.get('funnel_step') || '';",
        "      const funnelSessionId = funnelParams.get('session_id') || '';",
        "      const isFunnelStep = Boolean(funnelPageId && funnelStepId && cta);",
        "      const postCheckoutNextUrl = (outcome, stepId) => {",
        "        const next = new URLSearchParams();",
        "        next.set('outcome', outcome);",
        "        if (stepId) next.set('step_id', stepId);",
        "        if (cta.dataset.checkoutTenantId) next.set('tenant_id', cta.dataset.checkoutTenantId);",
        "        if (funnelSessionId) next.set('session_id', funnelSessionId);",
        # Carry the buyer's current host so the router redirects the funnel back to the SAME host (platform host
        # or custom domain), never leaking them off the host they entered on (plans/PLATFORM_HOSTNAME_SERVING.md
        # Slice 3). The server validates it against the Site's known origins before honoring it.
        "        next.set('origin', window.location.origin);",
        "        return `${cta.dataset.checkoutApiBaseUrl}/pages/${funnelPageId || cta.dataset.checkoutPageId}/post-checkout/next?${next.toString()}`;",
        "      };",
        "      const successUrl = () => {",
        "        const current = pageUrl();",
        "        if (cta && cta.dataset.checkoutApiBaseUrl && cta.dataset.checkoutHasPostCheckout === 'true') {",
        "          const next = new URLSearchParams();",
        "          next.set('outcome', 'accept');",
        "          if (cta.dataset.checkoutTenantId) next.set('tenant_id', cta.dataset.checkoutTenantId);",
        "          next.set('origin', window.location.origin);",  # keep the funnel on the buyer's entry host (Slice 3)
        # Append the Stripe placeholder UNENCODED — URLSearchParams would percent-encode the braces and Stripe
        # would never substitute the real Checkout Session id (it looks for the literal {CHECKOUT_SESSION_ID}).
        "          return `${cta.dataset.checkoutApiBaseUrl}/pages/${cta.dataset.checkoutPageId}/post-checkout/next?${next.toString()}&session_id={CHECKOUT_SESSION_ID}`;",
        "        }",
        "        return `${current}?checkout=success`;",
        "      };",
        "      const checkoutHref = (card) => {",
        "        if (!cta || !cta.dataset.checkoutBaseUrl) return cta ? cta.href : '#checkout';",
        "        const params = new URLSearchParams();",
        "        const productId = card?.dataset.productId || cta.dataset.checkoutProductId || '';",
        "        const priceId = card?.dataset.priceId || cta.dataset.checkoutPriceId || '';",
        "        const quantity = card?.dataset.quantity || cta.dataset.checkoutQuantity || '1';",
        "        if (cta.dataset.checkoutTenantId) params.set('clientID', cta.dataset.checkoutTenantId);",
        "        if (cta.dataset.checkoutOfferId) params.set('offer', cta.dataset.checkoutOfferId);",
        "        if (cta.dataset.checkoutPageId) params.set('page_id', cta.dataset.checkoutPageId);",
        "        params.set('mode', cta.dataset.checkoutMode || 'test');",
        "        if (productId) params.set('product_id', productId);",
        "        if (priceId) params.set('price_id', priceId);",
        "        if (quantity) params.set('quantity', quantity);",
        "        const current = pageUrl();",
        "        params.set('success_url', successUrl());",
        "        params.set('cancel_url', current);",
        "        const separator = cta.dataset.checkoutBaseUrl.includes('?') ? '&' : '?';",
        "        return `${cta.dataset.checkoutBaseUrl}${separator}${params.toString()}`;",
        "      };",
        "      const currentAmount = (card) => card?.dataset.expired === 'true' ? card.dataset.regularAmount : card?.dataset.saleAmount;",
        "      const updateCta = (card) => {",
        "        if (!cta || !card) return;",
        "        const amount = currentAmount(card);",
        "        const currency = card.dataset.currency || cta.dataset.ctaCurrency || 'usd';",
        "        const label = cta.dataset.ctaLabel || 'Checkout';",
        "        cta.dataset.ctaAmount = amount || '0';",
        "        cta.href = checkoutHref(card);",
        # An upsell CTA bakes the price into its label, so don't re-append the amount (avoids '$X - $X').
        "        cta.textContent = cta.dataset.ctaHideAmount === 'true' ? label : `${label} - ${money(amount, currency)}`;",
        "      };",
        "      if (cta && cta.dataset.checkoutBaseUrl) cta.href = checkoutHref(document.querySelector('.sl-price-option.selected') || cards[0]);",
        "      const selectCard = (card) => {",
        "        if (!card) return;",
        "        cards.forEach((item) => item.classList.toggle('selected', item === card));",
        "        const radio = card.querySelector('input[type=\"radio\"]');",
        "        if (radio) radio.checked = true;",
        "        updateCta(card);",
        "      };",
        "      if (cta && !isFunnelStep) {",
        "        cta.addEventListener('click', (event) => {",
        "          if (cta.dataset.connecting === 'true') {",
        "            event.preventDefault();",
        "            return;",
        "          }",
        "          const href = cta.href;",
        "          if (!href || href.endsWith('#checkout')) return;",
        "          event.preventDefault();",
        "          cta.dataset.connecting = 'true';",
        "          cta.setAttribute('aria-disabled', 'true');",
        "          cta.classList.add('is-connecting');",
        "          cta.textContent = 'Connecting...';",
        "          window.setTimeout(() => { window.location.assign(href); }, 80);",
        "        });",
        "      }",
        "      cards.forEach((card) => {",
        "        card.addEventListener('click', () => selectCard(card));",
        "        const radio = card.querySelector('input[type=\"radio\"]');",
        "        if (radio) radio.addEventListener('change', () => selectCard(card));",
        "      });",
        "      selectCard(cards.find((card) => card.dataset.default === 'true') || cards[0]);",
        "      let upsellCustomerId = '';",
        "      let upsellCustomerInfo = {};",
        # Shared by the countdown block: on a funnel step, a countdown expiry does what a decline does.
        "      let funnelDeclineOrExpire = null;",
        # Restart callbacks the countdown loop registers (below) so the downsell swap can re-arm the timer.
        "      const funnelCountdownRestarts = [];",
        "      if (isFunnelStep) {",
        # In-place downsell swap (§6): decline / countdown expiry swaps the price card + CTA to the same
        # product's downsell price rather than navigating to a separate page. A second decline advances.
        "        const swapToDownsell = (restartTimer) => {",
        "          const dsPrice = cta.dataset.downsellPriceId;",
        "          if (!dsPrice) return;",
        "          const dsAmount = Number(cta.dataset.downsellAmount || 0);",
        "          const dsCurrency = cta.dataset.downsellCurrency || 'usd';",
        "          cta.dataset.checkoutPriceId = dsPrice;",
        "          cta.dataset.ctaHideAmount = 'true';",
        "          const dsLabel = cta.dataset.downsellLabel || cta.dataset.ctaDefaultLabel || cta.textContent;",
        "          cta.textContent = dsLabel; cta.dataset.ctaDefaultLabel = dsLabel;",
        # The featured_price card replaced the offer_price_selector on the upsell page, so swap ITS amount to the
        # downsell price and recompute the savings pill against the (unchanged) regular price — a downsell is a
        # bigger discount, so the pill should reflect that. Legacy .sl-price-option kept as a fallback.
        "          const fp = document.querySelector('.sl-featured-price');",
        "          if (fp) {",
        "            const amtEl = fp.querySelector('.sl-featured-price-amount');",
        "            if (amtEl) amtEl.textContent = money(dsAmount, dsCurrency);",
        "            const pills = fp.querySelector('.sl-featured-price-pills');",
        "            const compareAt = Number(fp.dataset.fpCompareAt || 0);",
        "            if (pills) {",
        "              if (compareAt > dsAmount && dsAmount > 0) {",
        "                const saveEl = pills.querySelector('.sl-featured-price-save');",
        "                if (saveEl) saveEl.textContent = 'You save ' + Math.round((compareAt - dsAmount) / compareAt * 100) + '%';",
        "              } else { pills.style.display = 'none'; }",
        "            }",
        "          }",
        "          const card = document.querySelector('.sl-price-option');",
        "          if (card) {",
        "            card.dataset.priceId = dsPrice;",
        "            const amtEl = card.querySelector('[data-price-amount]');",
        "            if (amtEl) amtEl.textContent = money(dsAmount, dsCurrency);",
        "            const reg = card.querySelector('.sl-regular-price'); if (reg) reg.style.display = 'none';",
        "            const sav = card.querySelector('.sl-savings'); if (sav) sav.style.display = 'none';",
        "            const radio = card.querySelector('input[type=\"radio\"]'); if (radio) radio.value = dsPrice;",
        "          }",
        "          const dsHead = cta.dataset.downsellHeadline;",
        "          if (dsHead) { const h = document.querySelector('.sl-headline h1') || document.querySelector('.sl-headline'); if (h) h.textContent = dsHead; }",
        "          const dsNote = document.querySelector('[data-downsell-note]'); if (dsNote) dsNote.hidden = false;",
        # Restart the countdown ONLY on the live transition to the downsell (restartTimer). On a reload-restore we
        # resume the persisted downsell deadline instead — restarting would hand back a fresh window to stall.
        "          if (restartTimer) funnelCountdownRestarts.forEach((restart) => restart());",
        "        };",
        # Persist that the buyer reached the downsell: the server re-renders the UPSELL on reload (the swap is
        # client-side), so without this a refresh reverts to the upsell price and grants another shot at it.
        # Scoped to the funnel SESSION, not just the page: a new purchase gets a new session_id and therefore a
        # clean slate (starts at the upsell), while a refresh within the same session keeps the downsell.
        "        const downsellKey = `stripe-link:${pageId}:${funnelSessionId}:downsell`;",
        "        let downsellShown = false;",
        "        const goDownsellOrAdvance = () => {",
        "          if (cta.dataset.downsellPriceId && !downsellShown) {",
        "            downsellShown = true;",
        "            try { if (funnelSessionId) localStorage.setItem(downsellKey, '1'); } catch (e) {}",
        "            swapToDownsell(true);",
        "            return;",
        "          }",
        "          window.location.assign(postCheckoutNextUrl('decline', funnelStepId));",
        "        };",
        # Reload during the downsell: restore it immediately (no timer restart) so it never reverts to the upsell.
        "        if (funnelSessionId && cta.dataset.downsellPriceId && localStorage.getItem(downsellKey) === '1') {",
        "          downsellShown = true;",
        "          swapToDownsell(false);",
        "        }",
        "        funnelDeclineOrExpire = goDownsellOrAdvance;",
        "        if (declineCta) {",
        "          declineCta.style.display = '';",
        "          declineCta.addEventListener('click', (event) => { event.preventDefault(); goDownsellOrAdvance(); });",
        "        }",
        "        cta.setAttribute('aria-disabled', 'true');",
        "        cta.dataset.ctaDefaultLabel = cta.textContent;",
        "        cta.textContent = 'Loading...';",
        "        fetch(`${cta.dataset.checkoutApiBaseUrl}/upsell/session?session_id=${encodeURIComponent(funnelSessionId)}&clientID=${encodeURIComponent(cta.dataset.checkoutTenantId || '')}&mode=${encodeURIComponent(cta.dataset.checkoutMode || 'test')}`)",
        "          .then((response) => response.json())",
        "          .then((body) => {",
        "            const session = (body && body.session) || {};",
        "            upsellCustomerId = session.customer_id || '';",
        "            upsellCustomerInfo = {",
        "              name: session.customer_name || '',",
        "              email: session.customer_email || '',",
        "              phone: session.customer_phone || '',",
        "            };",
        "            cta.removeAttribute('aria-disabled');",
        "            cta.textContent = cta.dataset.ctaDefaultLabel || 'Add to my order';",
        "          })",
        "          .catch(() => { cta.textContent = 'Unavailable'; });",
        "        cta.addEventListener('click', (event) => {",
        "          event.preventDefault();",
        "          if (cta.dataset.connecting === 'true' || !upsellCustomerId) return;",
        "          cta.dataset.connecting = 'true';",
        "          cta.setAttribute('aria-disabled', 'true');",
        "          cta.classList.add('is-connecting');",
        "          cta.textContent = 'Processing...';",
        "          fetch(`${cta.dataset.checkoutApiBaseUrl}/upsell/charge`, {",
        "            method: 'POST',",
        "            headers: { 'Content-Type': 'application/json' },",
        "            body: JSON.stringify({",
        "              tenant_id: cta.dataset.checkoutTenantId || '',",
        "              mode: cta.dataset.checkoutMode || 'test',",
        "              session_id: funnelSessionId,",
        "              offer_id: cta.dataset.checkoutOfferId || '',",
        "              product_id: cta.dataset.checkoutProductId || '',",
        "              price_id: cta.dataset.checkoutPriceId || '',",
        "              sequence: funnelStepId,",
        "              customer_id: upsellCustomerId,",
        "              customer: upsellCustomerInfo,",
        "            }),",
        "          })",
        "            .then((response) => response.json().then((body) => ({ ok: response.ok, body })))",
        "            .then(({ ok, body }) => {",
        "              if (!ok) throw new Error((body && body.message) || 'Payment failed');",
        "              window.location.assign(postCheckoutNextUrl('accept', funnelStepId));",
        "            })",
        "            .catch(() => {",
        "              cta.dataset.connecting = 'false';",
        "              cta.removeAttribute('aria-disabled');",
        "              cta.classList.remove('is-connecting');",
        "              cta.textContent = 'Card declined - try again';",
        "            });",
        "        });",
        "      }",
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
        # Funnel-step timers scope to the session so a NEW purchase gets a fresh clock (a prior run may have
        # stored 'expired'); landing-page persist timers stay page-scoped, persisting across visits as intended.
        "        const cdScope = (isFunnelStep && funnelSessionId) ? ':' + funnelSessionId : '';",
        "        const storageKey = `stripe-link:${pageId}${cdScope}:countdown:${section.dataset.sectionId || 'timer'}`;",
        "        let deadline = Date.now() + duration * 1000;",
        "        let interval = null;",
        # The stored value carries the duration it was created for. Changing the timer from 15 to 5
        # minutes previously kept counting down the OLD deadline, and the only way out was to switch
        # Persist off and on again — which resumed the original value anyway.
        "        const writeStored = (value) => {",
        "          try { localStorage.setItem(storageKey, JSON.stringify({ v: value, d: duration })); } catch (e) {}",
        "        };",
        "        if (persistent) {",
        "          let stored = null;",
        "          try { stored = localStorage.getItem(storageKey); } catch (e) {}",
        "          let parsed = null;",
        "          if (stored) {",
        "            try { parsed = JSON.parse(stored); } catch (e) { parsed = null; }",
        # Values written before the duration was recorded are plain: a number, or the string 'expired'.
        "            if (parsed === null || typeof parsed !== 'object') parsed = { v: stored, d: duration };",
        "          }",
        # A different duration means the tenant changed the timer: discard and start fresh.
        "          if (parsed && Number(parsed.d) === duration) {",
        "            if (parsed.v === 'expired') deadline = Date.now();",
        "            else if (parsed.v) deadline = Number(parsed.v) || deadline;",
        "            else writeStored(deadline);",
        "          } else {",
        "            writeStored(deadline);",
        "          }",
        "        }",
        "        const render = () => {",
        "          const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));",
        "          const minutes = Math.floor(remaining / 60);",
        "          const seconds = String(remaining % 60).padStart(2, '0');",
        "          display.textContent = `${minutes}:${seconds}`;",
        "          if (remaining <= 0) {",
        # The end banner can be switched off independently: hide rather than swap to the expired state.
        "            if (section.dataset.endEnabled === 'false') { section.hidden = true; expireDiscounts(); return false; }",
        "            section.hidden = false;",
        "            if (label) label.textContent = section.dataset.endText || 'Offer expired';",
        "            const icon = section.querySelector('[data-countdown-icon]');",
        "            if (icon && section.dataset.endIcon) icon.textContent = section.dataset.endIcon;",
        "            section.dataset.expired = 'true';",
        "            section.style.setProperty('--sl-countdown-bg', section.dataset.endColor || '#ef4444');",
        # Re-applying a solid colour here would undo Transparent Background the moment the timer expired.
        "            if (section.dataset.transparent !== 'true') section.style.background = section.dataset.endColor || '#ef4444';",
        "            if (persistent) writeStored('expired');",
        "            expireDiscounts();",
        # On a funnel step, an expired upsell timer does what a decline does: swap to the downsell in place, or
        # advance to the next step / thank-you (§6, #4). No-op on ordinary pages.
        "            if (funnelDeclineOrExpire) funnelDeclineOrExpire();",
        "            return false;",
        "          }",
        "          return true;",
        "        };",
        "        const startTimer = () => {",
        "          if (!render()) return;",
        # Capture THIS run's timer id locally so its own tick clears only itself. The expiry render() restarts the
        # countdown synchronously (downsell swap), reassigning `interval` to the fresh timer; clearing the shared
        # variable here would kill that fresh timer instead of the expired one.
        "          const timer = window.setInterval(() => {",
        "            if (!render()) window.clearInterval(timer);",
        "          }, 1000);",
        "          interval = timer;",
        "        };",
        # Re-arm the timer for the downsell: fresh deadline, reset label + start color, so it counts down anew and
        # its next expiry advances the funnel (the downsell is already showing).
        "        funnelCountdownRestarts.push(() => {",
        "          if (interval) window.clearInterval(interval);",
        "          deadline = Date.now() + duration * 1000;",
        "          if (label) label.textContent = section.dataset.startText || label.textContent;",
        "          section.style.setProperty('--sl-countdown-bg', section.dataset.startColor || '');",
        "          section.style.background = section.dataset.startColor || '';",
        "          if (persistent) localStorage.setItem(storageKey, String(deadline));",
        "          startTimer();",
        "        });",
        "        startTimer();",
        "      });",
        # Post-purchase carousel (§6): a grid of independent one-click Adds + a single dismiss. Each Add charges
        # its card via /upsell/charge (idempotent by sequence) and marks the card Added in place; the dismiss
        # advances the funnel (post-checkout router → downsell carousel or thank-you). Self-contained: charge
        # context comes off the section container + each card, funnel context off the URL. No-op on other pages.
        "      const ppCarousel = document.querySelector('[data-section-type=\"post_purchase_carousel\"]');",
        "      if (ppCarousel) {",
        "        const ppApi = ppCarousel.dataset.apiBaseUrl || '';",
        "        const ppTenant = ppCarousel.dataset.tenantId || '';",
        "        const ppOffer = ppCarousel.dataset.offerId || '';",
        "        const ppSurface = ppCarousel.dataset.surface || 'upsell';",
        "        const ppMode = ppCarousel.dataset.stripeMode || 'test';",
        "        const ppSession = funnelParams.get('session_id') || '';",
        "        const ppPage = funnelParams.get('funnel_page') || ppCarousel.dataset.pageId || '';",
        "        const ppDismissUrl = () => {",
        "          const next = new URLSearchParams();",
        "          next.set('outcome', 'decline');",
        "          next.set('step_id', `${ppSurface}_carousel`);",
        "          if (ppTenant) next.set('tenant_id', ppTenant);",
        "          if (ppSession) next.set('session_id', ppSession);",
        "          next.set('origin', window.location.origin);",  # keep the carousel funnel on the buyer's host (Slice 3)
        "          return `${ppApi}/pages/${ppPage}/post-checkout/next?${next.toString()}`;",
        "        };",
        "        const ppDismiss = ppCarousel.querySelector('[data-pp-dismiss]');",
        "        if (ppDismiss) ppDismiss.addEventListener('click', (event) => { event.preventDefault(); window.location.assign(ppDismissUrl()); });",
        "        const ppAdds = Array.from(ppCarousel.querySelectorAll('[data-pp-add]'));",
        "        let ppCustomerId = '';",
        "        let ppCustomerInfo = {};",
        "        ppAdds.forEach((b) => { b.setAttribute('aria-disabled', 'true'); });",
        "        fetch(`${ppApi}/upsell/session?session_id=${encodeURIComponent(ppSession)}&clientID=${encodeURIComponent(ppTenant)}&mode=${encodeURIComponent(ppMode)}`)",
        "          .then((response) => response.json())",
        "          .then((body) => {",
        "            const session = (body && body.session) || {};",
        "            ppCustomerId = session.customer_id || '';",
        "            ppCustomerInfo = { name: session.customer_name || '', email: session.customer_email || '', phone: session.customer_phone || '' };",
        "            ppAdds.forEach((b) => { if (b.dataset.added !== 'true') b.removeAttribute('aria-disabled'); });",
        "          })",
        "          .catch(() => {});",
        "        ppAdds.forEach((btn) => {",
        "          const card = btn.closest('[data-pp-card]');",
        "          btn.addEventListener('click', (event) => {",
        "            event.preventDefault();",
        "            if (btn.dataset.added === 'true' || btn.dataset.connecting === 'true' || !ppCustomerId) return;",
        "            btn.dataset.connecting = 'true';",
        "            btn.setAttribute('aria-disabled', 'true');",
        "            btn.textContent = 'Processing...';",
        "            fetch(`${ppApi}/upsell/charge`, {",
        "              method: 'POST',",
        "              headers: { 'Content-Type': 'application/json' },",
        "              body: JSON.stringify({",
        "                tenant_id: ppTenant,",
        "                mode: ppMode,",
        "                session_id: ppSession,",
        "                offer_id: ppOffer,",
        "                product_id: (card && card.dataset.productId) || '',",
        "                price_id: (card && card.dataset.priceId) || '',",
        "                sequence: (card && card.dataset.sequence) || '',",
        "                customer_id: ppCustomerId,",
        "                customer: ppCustomerInfo,",
        "              }),",
        "            })",
        "              .then((response) => response.json().then((body) => ({ ok: response.ok, body })))",
        "              .then(({ ok, body }) => {",
        "                if (!ok) throw new Error((body && body.message) || 'Payment failed');",
        "                btn.dataset.added = 'true';",
        "                btn.dataset.connecting = 'false';",
        "                btn.classList.add('is-added');",
        "                btn.textContent = 'Added \\u2713';",
        "                if (card) card.classList.add('is-added');",
        # Once ANY card is added, the dismiss stops reading as 'No thanks' (which sounds like undoing the
        # just-made purchases) and becomes 'Continue…' — same funnel-advance, clearer intent.
        "                if (ppDismiss && ppDismiss.dataset.ppProceedLabel && ppDismiss.textContent !== ppDismiss.dataset.ppProceedLabel) ppDismiss.textContent = ppDismiss.dataset.ppProceedLabel;",
        "              })",
        "              .catch(() => {",
        "                btn.dataset.connecting = 'false';",
        "                btn.removeAttribute('aria-disabled');",
        "                btn.textContent = 'Card declined - try again';",
        "              });",
        "          });",
        "        });",
        "      }",
        "    });",
        "  </script>",
    ])
