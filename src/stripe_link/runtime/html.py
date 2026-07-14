from html import escape
from dataclasses import dataclass
from decimal import Decimal
import json
import re
from typing import Any
from urllib.parse import urlencode, urlparse

from stripe_link.domain.pricing import expand_offer, find_price, resolve_offer, single_unit_price
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
FONT_FALLBACK_STACKS = {
    "system": SYSTEM_FONT_STACK,
    "sans-serif": "sans-serif",
    "serif": "serif",
    "monospace": "monospace",
}
DEFAULT_FAVICON_URL = "https://images.juniorbay.com/icon/favicon.png"
CURRENT_YEAR_TOKEN = "{{current_year}}"
LANDING_PAGE_PRICE_CONTEXTS = {"standard", "sale", "flash_sale", "flash sale"}
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
}

UNIVERSAL_BUNDLE_TEMPLATE_STYLES = [
    "    html{font-size:62.5%;-webkit-text-size-adjust:100%}",
    "    *{margin:0;padding:0;box-sizing:border-box}",
    "    :root{--sl-background:var(--sl-theme-background);--sl-text:var(--sl-theme-text);--sl-accent:var(--sl-theme-accent);--sl-radius:1.6rem;font-family:var(--sl-font-body);color:var(--sl-text);background:var(--sl-background)}",
    "    body{font-size:1.6rem;line-height:1.5;background:var(--sl-background);color:var(--sl-text);padding-bottom:8rem}",
    "    main{width:100%;padding:0 0 12rem;display:grid;gap:1.6rem}",
    "    main > :not(.sl-countdown):not(.sl-checkout-cta){width:min(52rem,calc(100% - 3.2rem));margin-left:auto;margin-right:auto}",
    "    .sl-countdown{width:100%;display:flex;align-items:center;justify-content:center;gap:0.8rem;background:var(--sl-countdown-bg,var(--sl-card));color:var(--sl-countdown-text);border-radius:0;padding:1.2rem 1.6rem;font-weight:800}",
    "    .sl-countdown[data-sticky='true']{position:sticky;top:0;z-index:20}",
    "    .sl-countdown[data-transparent='true']{background:color-mix(in srgb,var(--sl-countdown-bg,var(--sl-card)) 82%,transparent)}",
    "    .sl-countdown[data-marquee='true']{overflow:hidden;white-space:nowrap}",
    "    .sl-countdown[data-marquee='true'] .sl-countdown-content{display:inline-flex;align-items:center;gap:0.8rem;animation:sl-marquee 14s linear infinite}",
    "    .sl-countdown time{font-family:var(--sl-font-mono);background:color-mix(in srgb,var(--sl-countdown-text) 16%,transparent);border-radius:0.4rem;padding:0.3rem 0.7rem}",
    "    @keyframes sl-marquee{from{transform:translateX(100%)}to{transform:translateX(-100%)}}",
    "    .sl-brand-label{display:flex;align-items:center;justify-content:center;gap:0.8rem;color:var(--sl-brand-label-text);padding-top:1.6rem}",
    "    .sl-brand-label::before{content:'';width:1rem;height:1rem;border-radius:999px;background:var(--sl-brand-dot);box-shadow:0 0 0.8rem var(--sl-brand-dot)}",
    "    .sl-brand-label h1{font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.08em;line-height:1.2;text-transform:uppercase;color:var(--sl-brand-label-text)}",
    "    .sl-seo-title{text-align:center}",
    "    .sl-seo-title h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;color:var(--sl-headline)}",
    "    .sl-mark-text{color:var(--sl-highlight-text)}",
    "    .sl-mark-bg{background:var(--sl-highlight-bg);color:var(--sl-highlight-bg-text);padding:0.1em 0.3em;border-radius:0.4rem}",
    "    .sl-headline{text-align:center;padding:0.8rem 0 0.4rem}",
    "    .sl-headline h2{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;font-weight:800;color:var(--sl-headline);letter-spacing:0}",
    "    .sl-subheadline{text-align:center}",
    "    .sl-subheadline p{font-size:1.5rem;line-height:1.55;color:var(--sl-subheadline-text);max-width:46rem;margin:0 auto}",
    "    .sl-hero-media{position:relative;padding-top:0.8rem}",
    "    .sl-hero-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;border-radius:var(--sl-radius)}",
    "    .sl-hero-track::-webkit-scrollbar{display:none}",
    "    .sl-hero-slide{flex:0 0 100%;scroll-snap-align:center}",
    "    .sl-hero-slide img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:var(--sl-radius);border:1px solid var(--sl-hero-border);background:var(--sl-hero-bg)}",
    "    .sl-hero-nav{position:absolute;top:calc(50% + 0.4rem);transform:translateY(-50%);width:3.8rem;height:3.8rem;border-radius:50%;border:0;background:rgba(255,255,255,.9);color:#111;font-size:2.2rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.18)}",
    "    .sl-hero-prev{left:0.8rem}",
    "    .sl-hero-next{right:0.8rem}",
    "    .sl-hero-counter{position:absolute;top:1.6rem;right:0.8rem;background:rgba(0,0,0,.55);color:#fff;font-size:1.3rem;font-weight:700;padding:0.3rem 0.9rem;border-radius:99.9rem}",
    "    .sl-hero-dots{display:flex;gap:0.6rem;justify-content:center;margin-top:0.8rem}",
    "    .sl-hero-dot{width:0.8rem;height:0.8rem;border-radius:50%;background:var(--sl-border);cursor:pointer}",
    "    .sl-hero-dot.is-active{background:var(--sl-brand)}",
    "    .sl-trust-badges{display:flex;flex-wrap:wrap;gap:0.8rem;justify-content:center}",
    "    .sl-trust-badge{display:flex;align-items:center;gap:0.6rem;border:1px solid var(--sl-trust-badge-border);background:var(--sl-trust-badge-bg);color:var(--sl-trust-badge-text);border-radius:999px;padding:0.8rem 1.4rem;font-family:var(--sl-font-accent);font-size:1.2rem;font-weight:800}",
    "    .sl-price-options{display:grid;grid-template-columns:1fr;gap:1.4rem;width:100%;margin:0 auto}",
    "    .sl-price-option{position:relative;display:grid;grid-template-columns:9rem minmax(0,1fr) 2.2rem;gap:1.4rem;align-items:center;border:2px solid var(--sl-price-card-border);border-radius:var(--sl-radius);padding:1.6rem 2rem;background:var(--sl-price-card-bg)}",
    "    .sl-price-option.selected{border-color:var(--sl-price-card-selected-border);box-shadow:0 0 0 3px color-mix(in srgb,var(--sl-price-card-selected-border) 13%,transparent)}",
    "    .sl-price-option input{width:2.2rem;height:2.2rem;accent-color:var(--sl-price-radio)}",
    "    .sl-price-option img{width:9rem;aspect-ratio:1/1;object-fit:contain;border-radius:0.8rem;background:var(--sl-background)}",
    "    .sl-price-copy{display:grid;gap:0.4rem}",
    "    .sl-price-option strong{font-family:var(--sl-font-heading);font-size:1.6rem;line-height:1.2;font-weight:600;color:var(--sl-price-title)}",
    "    .sl-price-description{color:var(--sl-price-description);font-size:1.3rem;line-height:1.45}",
    "    .sl-price-row{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;margin-top:1rem}",
    "    .sl-price-amount{font-family:var(--sl-font-accent);font-size:2rem;font-weight:700;color:var(--sl-price-amount)}",
    "    .sl-regular-price{color:var(--sl-price-regular);text-decoration:line-through;font-size:1.4rem}",
    "    .sl-price-option[data-expired='true'] .sl-regular-price,.sl-price-option[data-expired='true'] .sl-savings{display:none}",
    "    .sl-badge{display:inline-flex;width:max-content;font-family:var(--sl-font-accent);font-size:1.1rem;font-weight:700;color:var(--sl-featured-badge-text);background:var(--sl-featured-badge-bg);padding:0.4rem 1rem;border-radius:999px}",
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
    "    .sl-content-block h3{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:0.8rem;color:var(--sl-content-heading)}",
    "    .sl-content-block p{color:var(--sl-content-text);font-size:1.5rem;line-height:1.6}",
    "    .sl-content-block img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:0.8rem}",
    "    .sl-faq details{border:1px solid var(--sl-faq-border);background:var(--sl-faq-bg);border-radius:1.6rem;padding:0;overflow:hidden}",
    "    .sl-faq summary{cursor:pointer;font-family:var(--sl-font-heading);font-size:1.4rem;font-weight:600;line-height:1.35;color:var(--sl-faq-summary);display:flex;align-items:center;justify-content:space-between;gap:1.2rem;padding:1.6rem 2rem}",
    "    .sl-faq p{color:var(--sl-faq-text);font-size:1.4rem;line-height:1.6;padding:0 2rem 1.6rem}",
    "    .sl-checkout-cta{position:fixed;left:0;right:0;bottom:0;z-index:10;background:linear-gradient(transparent,var(--sl-cta-scrim) 20%);padding:1.6rem;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.8rem}",
    "    .sl-cta{display:inline-flex;width:min(52rem,100%);align-items:center;justify-content:center;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:1rem;padding:1.5rem 1.8rem;font-family:var(--sl-font-accent);font-size:1.7rem;font-weight:900;text-decoration:none}",
    "    .sl-cta.is-connecting{opacity:.72;cursor:wait;pointer-events:none}",
    "    .sl-decline-cta{width:auto;background:none;color:var(--sl-cta-text);text-decoration:underline;font-weight:600;font-size:1.3rem;padding:0.4rem}",
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
    "    .sl-testimonial{display:grid;gap:0.8rem;background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:1.2rem;padding:1.6rem;margin:0}",
    "    .sl-testimonial img{width:5.6rem;height:5.6rem;border-radius:50%;object-fit:cover}",
    "    .sl-testimonial blockquote{margin:0;font-size:1.6rem;line-height:1.5;color:var(--sl-content-text)}",
    "    .sl-testimonial figcaption{font-size:1.4rem;color:var(--sl-muted)}",
    "    .sl-rating{display:flex;flex-direction:column;align-items:center;gap:0.4rem}",
    "    .sl-rating-stars{color:#f59e0b;font-size:2.4rem;letter-spacing:0.2rem}",
    "    .sl-rating-meta{font-size:1.4rem;color:var(--sl-content-text)}",
    "    .sl-client-marquee{overflow:hidden}",
    "    .sl-marquee-track{display:flex;width:max-content;animation:sl-marquee 30s linear infinite}",
    "    .sl-marquee-row{display:flex;align-items:center;gap:3.2rem;padding-right:3.2rem}",
    "    .sl-marquee-logo img{height:4rem;width:auto;object-fit:contain;filter:grayscale(1);opacity:0.75}",
    "    @keyframes sl-marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}",
    "    @media (prefers-reduced-motion: reduce){.sl-marquee-track{animation:none;flex-wrap:wrap}}",
    "    .sl-carousel-track{display:flex;gap:1.6rem;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:1.2rem;-webkit-overflow-scrolling:touch}",
    "    .sl-carousel-slide{scroll-snap-align:start;flex:0 0 min(80%,28rem);display:flex;flex-direction:column;gap:0.8rem;background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.4rem}",
    "    .sl-carousel-slide img{width:100%;height:16rem;object-fit:cover;border-radius:0.8rem}",
    "    .sl-carousel-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-carousel-desc{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-carousel-price{font-family:var(--sl-font-accent);font-weight:900;font-size:2rem;color:var(--sl-price-amount);margin-top:auto}",
    "    .sl-carousel-buy{width:auto;text-align:center}",
    "    .sl-listicle{width:min(52rem,100%);margin:0 auto;display:flex;flex-direction:column;gap:1.2rem}",
    "    .sl-listicle-stage{position:relative}",
    "    .sl-listicle-carousel{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none}",
    "    .sl-listicle-carousel::-webkit-scrollbar{display:none}",
    "    .sl-listicle-slide{flex:0 0 100%;scroll-snap-align:center;display:flex;align-items:center;justify-content:center}",
    "    .sl-listicle-slide img{width:100%;height:auto;max-height:38rem;object-fit:contain;border-radius:1.2rem}",
    "    .sl-listicle-dots{display:flex;gap:0.6rem;justify-content:center}",
    "    .sl-listicle-dot{width:0.7rem;height:0.7rem;border-radius:50%;background:var(--sl-border);transition:background .2s}",
    "    .sl-listicle-dot.is-active{background:var(--sl-brand)}",
    "    .sl-listicle-card{background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.4rem;padding:1.6rem;display:flex;flex-direction:column;gap:0.8rem}",
    "    .sl-listicle-pricerow{display:flex;align-items:baseline;gap:0.8rem;flex-wrap:wrap}",
    "    .sl-listicle-discount{color:#e11d48;font-family:var(--sl-font-accent);font-weight:900;font-size:2rem}",
    "    .sl-listicle-price{font-family:var(--sl-font-accent);font-weight:900;font-size:2.4rem;color:var(--sl-price-amount)}",
    "    .sl-listicle-compare{color:var(--sl-price-regular);font-size:1.6rem}",
    "    .sl-listicle-title{font-family:var(--sl-font-heading);font-weight:700;font-size:1.7rem;color:var(--sl-price-title)}",
    "    .sl-listicle-desc{font-size:1.4rem;color:var(--sl-price-description)}",
    "    .sl-listicle-add{width:100%;text-align:center;margin-top:0.4rem}",
    "    .sl-minicart{position:fixed;left:0;right:0;bottom:0;z-index:20;display:none;align-items:center;justify-content:space-between;gap:1rem;padding:1.2rem 1.6rem;background:var(--sl-card);border-top:1px solid var(--sl-border);box-shadow:0 -2px 16px rgba(0,0,0,.12)}",
    "    .sl-minicart.is-visible{display:flex}",
    "    .sl-minicart-summary{font-family:var(--sl-font-accent);font-weight:800;color:var(--sl-text)}",
    "    .sl-minicart-note{font-size:1.3rem;color:var(--sl-muted)}",
    "    .sl-legal{display:flex;gap:1.2rem;flex-wrap:wrap;justify-content:center;text-align:center;font-size:1.3rem;color:var(--sl-legal-text);padding:2.4rem 0 0}",
    "    .sl-legal span{flex:0 0 100%}",
    "    .sl-legal a{color:var(--sl-legal-link)}",
    "    @media (max-width: 700px){.sl-price-option{grid-template-columns:8.8rem minmax(0,1fr) 2.4rem;gap:1rem;padding:1.2rem}.sl-price-option img{width:8.8rem}.sl-content-block{grid-template-columns:1fr}.sl-headline h2{font-size:3rem}}",
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
    for item in offer.get("items", []):
        if item.get("service_id"):
            continue  # service items are resolved against services_by_id, not products
        product_id = item.get("product_id", "")
        if product_id not in products_by_id:
            raise RenderError(f"Product '{product_id}' was not provided for offer '{offer.get('offer_id', '')}'.")


def render_page(
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None = None,
    checkout_url: str | None = None,
    api_base_url: str | None = None,
    services_by_id: dict[str, dict[str, Any]] | None = None,
    offers_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    services_by_id = services_by_id or {}
    offers_by_id = offers_by_id or {str(offer.get("offer_id") or ""): offer}
    require_offer_products(offer, products_by_id)
    resolved_offer = resolve_offer(offer, products_by_id, selected_prices, services_by_id=services_by_id)
    title = escape((page.get("seo") or {}).get("title") or page.get("name") or "Checkout")
    description = escape((page.get("seo") or {}).get("description") or "")
    favicon_tags = render_favicon_tags(page.get("seo") or {})
    styles = render_template_styles(page)
    body = "\n".join(
        render_section(section, page, offer, products_by_id, resolved_offer, checkout_url, api_base_url, services_by_id, offers_by_id)
        for section in page.get("sections", [])
    )
    has_legal_footer_section = any(section.get("type") == "legal_footer" for section in page.get("sections", []))
    legal_footer = "" if has_legal_footer_section else render_legal_footer(page.get("legal") or {}, api_base_url=api_base_url)
    analytics_tags = render_analytics_tags(page.get("analytics") or {})
    # A listicle page gets a persistent mini-cart (client-side this phase; server-side cart is L2).
    minicart = render_minicart() if str(offer.get("offer_type") or "single") == "listicle" else ""
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
        favicon_tags,
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
        minicart,
        conversion_data,
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
    offer_view = expand_offer(offer, products_by_id, services_by_id)
    targets = []
    for target in offer_view.get("items", []):
        product = target.get("product") or {}
        price = (target.get("pricing") or {}).get("single_unit_price") or {}
        amount = int(price.get("unit_amount") or 0)
        compare = int(price.get("compare_at_amount") or 0)
        discount = round((compare - amount) / compare * 100) if compare > amount > 0 else 0
        targets.append({
            "product_id": product.get("product_id", ""),
            "price_id": price.get("price_id", ""),
            "headline": product.get("headline", ""),
            "subheadline": product.get("subheadline", ""),
            "hero_image": product.get("hero_image", ""),
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
    # This phase: a summary bar showing the client-side cart accumulate. Checkout is wired in L2 (the
    # server-side cart + multi-line Stripe checkout) — plans/LISTICLE_AND_CART.md.
    return "\n".join([
        "  <div class=\"sl-minicart\" data-minicart>",
        "    <span class=\"sl-minicart-summary\" data-minicart-summary></span>",
        "    <span class=\"sl-minicart-note\">Checkout coming soon</span>",
        "  </div>",
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
    if str(c.offer.get("offer_type") or "single") == "listicle":
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
    "hero": {"render": lambda c: render_hero(c.section), "version": 1},
    "offer_price_selector": {"render": _render_offer_selector, "version": 1},
    "refund_policy": {"render": lambda c: render_refund_policy(c.section, c.offer, c.products_by_id), "version": 1},
    "faq": {"render": lambda c: render_faq(c.section), "version": 1},
    "content_block": {"render": lambda c: render_content_blocks(c.section), "version": 1},
    "testimonials": {"render": lambda c: render_testimonials(c.section), "version": 1},
    "rating": {"render": lambda c: render_rating(c.section), "version": 1},
    "client_marquee": {"render": lambda c: render_client_marquee(c.section), "version": 1},
    "product_carousel": {"render": lambda c: render_product_carousel(c.section, c.page, c.offers_by_id, c.products_by_id, c.services_by_id, c.checkout_url, c.api_base_url), "version": 1},
    "checkout_cta": {"render": lambda c: render_checkout_cta(c.page, c.section, c.offer, c.resolved_offer, c.checkout_url, c.api_base_url, c.products_by_id), "version": 1},
    "legal_footer": {"render": lambda c: render_legal_footer(c.page.get("legal") or {}, c.section, c.api_base_url), "version": 1},
}


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
    for item in offer.get("items", []):
        product = products_by_id.get(item.get("product_id", ""))
        if product:
            return product
    return {}


def first_offer_lead_capture(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The lead_capture block of the offer's primary lead-gen product — drives the inline form fields."""
    for item in offer.get("items", []):
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
    title = render_headline_markup(section.get("label") or (page.get("seo") or {}).get("title") or product_name or page.get("name") or "")
    return "\n".join([
        f"    <section class=\"sl-seo-title\" data-section-id=\"{escape(str(section.get('id', 'seo-title')))}\" data-section-type=\"seo_title\">",
        f"      <h1>{title}</h1>",
        "    </section>",
    ])


def render_brand_label(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    label = render_headline_markup(section.get("label") or (page.get("seo") or {}).get("title") or page.get("name") or "")
    return "\n".join([
        f"    <section class=\"sl-brand-label\" data-section-id=\"{escape(str(section.get('id', 'brand-label')))}\" data-section-type=\"brand_label\">",
        f"      <h1>{label}</h1>",
        "    </section>",
    ])


def first_offer_service_image(offer: dict[str, Any], services_by_id: dict[str, dict[str, Any]]) -> str:
    for item in offer.get("items", []):
        service = services_by_id.get(item.get("service_id", ""))
        image = (service or {}).get("presentation", {}).get("hero_image_url") if service else ""
        if image:
            return str(image)
    return ""


def render_hero_media(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    product = first_offer_product(offer, products_by_id)
    if str(offer.get("offer_type") or "single") == "listicle":
        # A listicle's hero carousel IS the offer's items — one product image per slide, offer-driven so
        # it can never fall out of sync with a manually-edited field (plans, ConversionContext direction).
        images = [slide["image"] for slide in listicle_slides(offer, products_by_id, services_by_id or {}) if slide["image"]]
    else:
        images = hero_media_images(section, offer, product)
        if not images:
            service_image = first_offer_service_image(offer, services_by_id or {})
            if service_image:
                images = [service_image]
    if not images:
        return ""
    alt = str(product.get("name") or offer.get("name") or "Product image")
    section_id = escape(str(section.get("id", "hero-media")))
    slides = [
        f"        <div class=\"sl-hero-slide\">{responsive_img(image_url, alt, sizes=HERO_MEDIA_SIZES, eager=(index == 0))}</div>"
        for index, image_url in enumerate(images)
    ]
    # A single image needs no carousel chrome.
    if len(images) == 1:
        return "\n".join([
            f"    <section class=\"sl-hero-media\" data-section-id=\"{section_id}\" data-section-type=\"hero_media\" data-media-count=\"1\">",
            "      <div class=\"sl-hero-track\">",
            *slides,
            "      </div>",
            "    </section>",
        ])
    # Multiple images -> a swipeable carousel with prev/next arrows, a counter, and dots.
    dots = [
        f"        <span class=\"sl-hero-dot{' is-active' if index == 0 else ''}\" data-hero-dot data-index=\"{index}\"></span>"
        for index in range(len(images))
    ]
    return "\n".join([
        f"    <section class=\"sl-hero-media sl-hero-carousel\" data-section-id=\"{section_id}\" data-section-type=\"hero_media\" data-media-count=\"{len(images)}\" data-hero-carousel>",
        "      <div class=\"sl-hero-track\" data-hero-track>",
        *slides,
        "      </div>",
        "      <button class=\"sl-hero-nav sl-hero-prev\" type=\"button\" data-hero-prev aria-label=\"Previous image\">‹</button>",
        "      <button class=\"sl-hero-nav sl-hero-next\" type=\"button\" data-hero-next aria-label=\"Next image\">›</button>",
        f"      <span class=\"sl-hero-counter\" data-hero-counter>1 / {len(images)}</span>",
        "      <div class=\"sl-hero-dots\">",
        *dots,
        "      </div>",
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
    items = offer.get("items") or []
    return len(items) > 1 or any(item.get("selectable_prices") for item in items if isinstance(item, dict))


def render_headline(section: dict[str, Any]) -> str:
    return "\n".join([
        f"    <section class=\"sl-headline\" data-section-id=\"{escape(str(section.get('id', 'headline')))}\" data-section-type=\"headline\">",
        f"      <h2>{render_headline_markup(section.get('text') or '')}</h2>",
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


def render_hero(section: dict[str, Any]) -> str:
    headline = render_headline_markup(section.get("headline") or "")
    subheadline = escape(str(section.get("subheadline") or ""))
    # data-conversion-bind lets the island update these from the current target (multi-target pages).
    return "\n".join([
        f"    <section class=\"sl-hero\" data-section-id=\"{escape(str(section.get('id', 'hero')))}\" data-section-type=\"hero\" data-conversion-section=\"hero\">",
        f"      <h1 data-conversion-bind=\"headline\">{headline}</h1>" if headline else "",
        f"      <p data-conversion-bind=\"subheadline\">{subheadline}</p>" if subheadline else "",
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
        f"        <input type=\"radio\" name=\"sl-price-{escape(service_id)}\" value=\"{escape(price_id)}\" checked>",
        "      </article>",
    ])
    return (landing_page_price_sort_key(price, item, display_index), card_markup)


def listicle_slides(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One slide per offer item, priced at the SINGLE-UNIT price (bundles/funnels ignored)."""
    slides = []
    for item in offer.get("items", []):
        product_id = str(item.get("product_id") or "")
        service_id = str(item.get("service_id") or "")
        if product_id and product_id in products_by_id:
            product = products_by_id[product_id]
            price = single_unit_price(product)
            if not price:
                continue
            compare = int(price.get("compare_at_amount") or 0)
            slides.append({
                "product_id": product_id, "service_id": "", "price_id": str(price.get("price_id") or ""),
                "name": str(product.get("name") or ""), "description": str(product.get("description") or ""),
                "image": str((product.get("images") or [""])[0] or ""),
                "amount": int(price.get("unit_amount") or 0), "currency": str(price.get("currency") or "usd"),
                "compare_at": compare,
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
    """Listicle price card. No image carousel here — the hero_media carousel is the single carousel and this
    card SYNCS to its active target via the conversion island (each field carries data-conversion-bind; the
    per-target data comes from the embedded OfferView payload). Add-to-cart reads the current target too."""
    slides = listicle_slides(offer, products_by_id, services_by_id)
    if not slides:
        return ""
    offer_id = escape(str(offer.get("offer_id") or ""))
    first = slides[0]
    first_discount = round((first["compare_at"] - first["amount"]) / first["compare_at"] * 100) if first["compare_at"] > first["amount"] > 0 else 0
    return "\n".join([
        f"    <section class=\"sl-listicle\" data-section-type=\"offer_price_selector\" data-conversion-section=\"offer_selector\" data-listicle data-offer-id=\"{offer_id}\">",
        "      <div class=\"sl-listicle-card\">",
        "        <div class=\"sl-listicle-pricerow\">",
        f"          <span class=\"sl-listicle-discount\" data-conversion-bind=\"discount\">{('-' + str(first_discount) + '%') if first_discount else ''}</span>",
        f"          <span class=\"sl-listicle-price\" data-conversion-bind=\"price\">{escape(format_money(first['amount'], first['currency']))}</span>",
        f"          <del class=\"sl-listicle-compare\" data-conversion-bind=\"compare_at\">{escape(format_money(first['compare_at'], first['currency'])) if first['compare_at'] > first['amount'] else ''}</del>",
        "        </div>",
        f"        <p class=\"sl-listicle-title\" data-conversion-bind=\"headline\">{render_headline_markup(first['name'])}</p>",
        f"        <p class=\"sl-listicle-desc\" data-conversion-bind=\"subheadline\">{escape(first['description'])}</p>",
        "        <button class=\"sl-cta sl-listicle-add\" type=\"button\" data-listicle-add>Add to cart</button>",
        "      </div>",
        "    </section>",
    ])


def render_offer_price_selector(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    services_by_id = services_by_id or {}
    cards: list[tuple[tuple[int, int, int], str]] = []
    display_index = 0
    for item in offer.get("items", []):
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
        default_price_id = item.get("default_price_id")
        for option in item.get("selectable_prices") or []:
            price = find_price(product, option.get("price_id", ""))
            if not is_landing_page_price(price):
                continue
            label = escape(str(option.get("label") or price.get("label") or "Option"))
            badge = escape(str(option.get("badge") or ""))
            amount = int(price.get("unit_amount", 0))
            currency = str(price.get("currency") or "usd")
            checkout_quantity = int(item.get("quantity") or 1)
            default_attr = "true" if price.get("price_id") == default_price_id else "false"
            image_url = price_image(product, price, option)
            description = escape(str(option.get("description") or price.get("description") or product.get("description") or ""))
            compare_at_unit_amount = price.get("compare_at_unit_amount")
            savings_pct = option.get("display_discount_pct") or price.get("discount_pct")
            if not savings_pct and compare_at_unit_amount:
                savings_pct = discount_pct(amount, int(compare_at_unit_amount))
            card_markup = "\n".join([
                f"      <article class=\"sl-price-option\" data-product-id=\"{escape(str(product_id))}\" data-price-id=\"{escape(str(price.get('price_id', '')))}\" data-quantity=\"{checkout_quantity}\" data-default=\"{default_attr}\" data-sale-amount=\"{amount}\" data-regular-amount=\"{int(compare_at_unit_amount) if compare_at_unit_amount else ''}\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
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
                f"        <input type=\"radio\" name=\"sl-price-{escape(product_id)}\" value=\"{escape(str(price.get('price_id', '')))}\" {'checked' if default_attr == 'true' else ''}>",
                "      </article>",
            ])
            cards.append((landing_page_price_sort_key(price, option, display_index), card_markup))
            display_index += 1
    return "\n".join([
        "    <section class=\"sl-price-selector\" data-section-type=\"offer_price_selector\">",
        "      <div class=\"sl-price-options\">",
        *(card for _, card in sorted(cards, key=lambda item: item[0])),
        "      </div>",
        "    </section>",
    ])


def is_landing_page_price(price: dict[str, Any]) -> bool:
    context = str(price.get("context") or "standard").strip().lower()
    return context in LANDING_PAGE_PRICE_CONTEXTS


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


def responsive_img(url: str, alt: str, *, sizes: str, eager: bool = False) -> str:
    """Render an <img> that lets the browser pick the right rendition per slot and DPR.

    When the URL is a processor rendition (.../<key>/<size>.webp) we emit a webp srcset over
    all renditions plus a sizes hint, so a 144px thumbnail no longer downloads the 1080px file.
    Non-rendition URLs (external/custom) fall back to a plain tag but still get lazy loading.
    Always adds loading/decoding; the first hero image opts into eager + high fetch priority
    because it is the LCP candidate.
    """
    url = str(url or "")
    alt_attr = escape(str(alt or ""))
    loading = "eager" if eager else "lazy"
    priority = ' fetchpriority="high"' if eager else ""
    match = _RENDITION_URL_RE.match(url)
    if not match:
        return f'<img src="{escape(url)}" alt="{alt_attr}" loading="{loading}" decoding="async"{priority}>'
    base = match.group("base")
    srcset = ", ".join(
        f"{escape(f'{base}/{size}.webp')} {width}w"
        for size, width in IMAGE_RENDITION_WIDTHS.items()
    )
    return (
        f'<img src="{escape(f"{base}/medium.webp")}" srcset="{srcset}" sizes="{escape(sizes)}" '
        f'alt="{alt_attr}" loading="{loading}" decoding="async"{priority}>'
    )


# Slot widths per image context, used as the srcset `sizes` hint. Hero/content stretch to the
# ~52rem content column (full width on phones); price-option thumbnails are a fixed 9rem.
HERO_MEDIA_SIZES = "(min-width: 52rem) 52rem, 100vw"
CONTENT_BLOCK_SIZES = "(min-width: 52rem) 52rem, 100vw"
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
    for item in offer.get("items", []):
        product = products_by_id.get(item.get("product_id", ""))
        product_name = product.get("name") if product else ""
        for option in item.get("selectable_prices") or []:
            price = find_price(product, option.get("price_id", "")) if product else {}
            if not is_landing_page_price(price):
                continue
            label = option.get("label") or price.get("label")
            labels.append(f"{product_name} - {label}" if product_name and label else str(label or product_name))
    return [label for label in labels if label]


def render_faq(section: dict[str, Any]) -> str:
    items = section.get("items") or []
    rendered = [
        "\n".join([
            "      <details>",
            f"        <summary>{render_headline_markup(item.get('question') or '')}</summary>",
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
            f"          <h3>{render_headline_markup(block.get('title') or '')}</h3>",
            f"          <p>{escape(str(block.get('text') or ''))}</p>",
            "        </div>",
            "        " + responsive_img(image_url, str(block.get("title") or "Content image"), sizes=CONTENT_BLOCK_SIZES) if image_url else "",
            "      </article>",
        ]))
    if not rendered:
        return ""
    return "\n".join([
        f"    <section class=\"sl-content-blocks\" data-section-id=\"{escape(str(section.get('id', 'content-blocks')))}\" data-section-type=\"content_block\">",
        *rendered,
        "    </section>",
    ])


CTA_TYPES = {"buy", "call", "email", "external", "booking"}


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
        byline = " · ".join(part for part in [f"<strong>{escape(author)}</strong>" if author else "", escape(role) if role else ""] if part)
        cards.append("\n".join(line for line in [
            "      <figure class=\"sl-testimonial\">",
            (f"        {responsive_img(avatar_url, author or 'Reviewer', sizes=CONTENT_BLOCK_SIZES)}" if avatar_url else ""),
            f"        <blockquote>{escape(quote)}</blockquote>",
            (f"        <figcaption>{byline}</figcaption>" if byline else ""),
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


def render_client_marquee(section: dict[str, Any]) -> str:
    logos = [logo for logo in (section.get("logos") or []) if str(logo.get("image_url") or "").strip()]
    if not logos:
        return ""
    # Duplicate the row so the CSS marquee scrolls seamlessly.
    items = "".join(
        f"<span class=\"sl-marquee-logo\">{responsive_img(str(logo.get('image_url')), str(logo.get('name') or 'Client'), sizes=CONTENT_BLOCK_SIZES)}</span>"
        for logo in logos
    )
    heading = str(section.get("heading") or "").strip()
    heading_html = f"      <h2 class=\"sl-section-heading\">{render_headline_markup(heading)}</h2>" if heading else ""
    return "\n".join(line for line in [
        f"    <section class=\"sl-client-marquee\" data-section-id=\"{escape(str(section.get('id', 'client-marquee')))}\" data-section-type=\"client_marquee\">",
        heading_html,
        "      <div class=\"sl-marquee-track\">",
        f"        <div class=\"sl-marquee-row\">{items}</div>",
        f"        <div class=\"sl-marquee-row\" aria-hidden=\"true\">{items}</div>",
        "      </div>",
        "    </section>",
    ] if line)


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
    "booking": {"render": lambda c: render_booking_cta(c.cta, c.api_base_url), "version": 1},
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
    brand = escape(str((offer.get("presentation") or {}).get("headline") or offer.get("name") or "us"))

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
        f"data-tenant-id=\"{tenant_id}\" data-offer-id=\"{offer_id}\" data-page-id=\"{page_id}\">",
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
    checkout = checkout_context(page, offer, resolved_offer, checkout_url, api_base_url)
    href = escape(checkout["href"])
    data_attrs = " ".join(
        f"data-{escape(key)}=\"{escape(str(value))}\""
        for key, value in checkout["data"].items()
        if value is not None and value != ""
    )
    return "\n".join([
        "    <section class=\"sl-checkout-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"buy\">",
        f"      <a class=\"sl-cta\" href=\"{href}\" data-cta-label=\"{label}\" data-cta-currency=\"{escape(currency)}\" data-cta-amount=\"{subtotal}\" {data_attrs}>{label} - {escape(format_money(subtotal, currency))}</a>",
        "      <a class=\"sl-cta sl-decline-cta\" href=\"#decline\" data-role=\"decline\" style=\"display:none\">No thanks, continue</a>",
        "    </section>",
    ])


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


def render_booking_cta(cta: dict[str, str], api_base_url: str | None) -> str:
    """Booking CTA: a button that reveals an inline booking calendar. The JS island (page interactions)
    drives the same public availability -> reserve -> checkout flow as the standalone /book page."""
    service_id = escape(cta["target"].strip())
    label = escape(cta["label"] or "Book Now")
    api_base = escape(str(api_base_url or "").rstrip("/"))
    return "\n".join([
        "    <section class=\"sl-checkout-cta sl-booking-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"booking\"",
        f"      data-booking-widget data-service-id=\"{service_id}\" data-api-base=\"{api_base}\">",
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
            "checkout-tenant-id": page.get("tenant_id") or offer.get("tenant_id") or "",
            "checkout-offer-id": offer.get("offer_id") or "",
            "checkout-page-id": page.get("page_id") or "",
            "checkout-product-id": product_id,
            "checkout-price-id": price_id,
            "checkout-quantity": quantity,
            "checkout-api-base-url": str(api_base_url or "").rstrip("/"),
            "checkout-has-post-checkout": "true" if page.get("post_checkout") else "false",
        },
    }


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
        "success_url": "{{success_url}}",
        "cancel_url": "{{cancel_url}}",
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


def render_favicon_tags(seo: dict[str, Any]) -> str:
    favicon_url = escape(str(seo.get("favicon_url") or DEFAULT_FAVICON_URL))
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
    if not any([has_countdown, has_price_selector, has_current_year, has_checkout_cta, has_hero_carousel]):
        return ""
    page_id = escape(str(page.get("page_id") or "page"))
    return "\n".join([
        "  <script>",
        "    document.addEventListener('DOMContentLoaded', () => {",
        "      document.querySelectorAll('[data-sl-current-year]').forEach((node) => {",
        "        node.textContent = String(new Date().getFullYear());",
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
        "          fetch(`${apiBase}/services/${encodeURIComponent(serviceId)}/availability?from=${from}&to=${to}`)",
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
        "          const body = { service_id: serviceId, slot_start: selectedSlot, customer };",
        "          if (selectedFulfiller) body.fulfiller_id = selectedFulfiller;",
        "          confirmBtn.disabled = true; confirmBtn.textContent = 'Reserving...';",
        "          const base = window.location.href.split('?')[0];",
        "          fetch(`${apiBase}/services/appointments/reserve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })",
        "            .then((r) => r.json().then((j) => ({ ok: r.ok, j })))",
        "            .then((res) => {",
        "              if (!res.ok) throw new Error(res.j.message || 'That time is no longer available.');",
        "              return fetch(`${apiBase}/services/appointments/checkout`, { method: 'POST', headers: { 'Content-Type': 'application/json' },",
        "                body: JSON.stringify({ appointment_id: res.j.appointment.appointment_id, manage_token: res.j.manage_token, success_url: base + '?booking=success', cancel_url: base + '?booking=cancel' }) }).then((r) => r.json());",
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
        "          hero_image: (el, t) => { if (t.hero_image) el.setAttribute('src', t.hero_image); },",
        "        };",
        "        const applyTarget = (index) => {",
        "          if (index < 0 || index >= convTargets.length) return;",
        "          currentIndex = index;",
        "          const t = convTargets[index];",
        "          document.querySelectorAll('[data-conversion-bind]').forEach((el) => { const b = binders[el.dataset.conversionBind]; if (b) b(el, t); });",
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
        # Listicle client-side cart adds the CURRENT target (server-side cart + checkout are the next phase).
        "        const listicle = document.querySelector('[data-listicle]');",
        "        if (listicle) {",
        "          const cartKey = 'sl_cart_' + (listicle.dataset.offerId || 'offer');",
        "          const readCart = () => { try { return JSON.parse(localStorage.getItem(cartKey) || '[]'); } catch (e) { return []; } };",
        "          const writeCart = (cart) => { try { localStorage.setItem(cartKey, JSON.stringify(cart)); } catch (e) {} };",
        "          const minicart = document.querySelector('[data-minicart]');",
        "          const minicartSummary = minicart && minicart.querySelector('[data-minicart-summary]');",
        "          const renderMinicart = () => {",
        "            if (!minicart) return;",
        "            const cart = readCart();",
        "            const count = cart.reduce((n, i) => n + (i.qty||1), 0);",
        "            const total = cart.reduce((s, i) => s + (i.amount||0) * (i.qty||1), 0);",
        "            const currency = (cart[0] && cart[0].currency) || 'usd';",
        "            if (count > 0) { minicart.classList.add('is-visible'); if (minicartSummary) minicartSummary.textContent = 'Cart (' + count + ') · ' + fmt(total, currency); }",
        "            else minicart.classList.remove('is-visible');",
        "          };",
        "          const addBtn = listicle.querySelector('[data-listicle-add]');",
        "          if (addBtn) addBtn.addEventListener('click', () => {",
        "            const t = convTargets[currentIndex];",
        "            const cart = readCart();",
        "            const existing = cart.find((i) => i.price_id === t.price_id);",
        "            if (existing) existing.qty = (existing.qty||1) + 1;",
        "            else cart.push({ product_id: t.product_id, price_id: t.price_id, name: t.headline, amount: Number(t.amount||0), currency: t.currency, qty: 1 });",
        "            writeCart(cart); renderMinicart();",
        "            emit('conversion:ctaInvoked', { ctaType: 'add_to_cart', target: t });",
        "            addBtn.textContent = 'Added \\u2713'; window.setTimeout(() => { addBtn.textContent = 'Add to cart'; }, 1200);",
        "          });",
        "          renderMinicart();",
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
        "        const heroGo = (index) => { heroIndex = Math.max(0, Math.min(heroCount - 1, index)); if (heroTrack) heroTrack.scrollTo({ left: heroIndex * heroTrack.clientWidth, behavior: 'smooth' }); };",
        "        const heroSync = (index) => {",
        "          heroIndex = index;",
        "          heroDots.forEach((dot, i) => dot.classList.toggle('is-active', i === index));",
        "          if (heroCounter) heroCounter.textContent = (index + 1) + ' / ' + heroCount;",
        "        };",
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
        "        return `${cta.dataset.checkoutApiBaseUrl}/pages/${funnelPageId || cta.dataset.checkoutPageId}/post-checkout/next?${next.toString()}`;",
        "      };",
        "      const successUrl = () => {",
        "        const current = pageUrl();",
        "        if (cta && cta.dataset.checkoutApiBaseUrl && cta.dataset.checkoutHasPostCheckout === 'true') {",
        "          const next = new URLSearchParams();",
        "          next.set('outcome', 'accept');",
        "          if (cta.dataset.checkoutTenantId) next.set('tenant_id', cta.dataset.checkoutTenantId);",
        "          next.set('session_id', '{CHECKOUT_SESSION_ID}');",
        "          return `${cta.dataset.checkoutApiBaseUrl}/pages/${cta.dataset.checkoutPageId}/post-checkout/next?${next.toString()}`;",
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
        "        cta.textContent = `${label} - ${money(amount, currency)}`;",
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
        "      if (isFunnelStep) {",
        "        if (declineCta) {",
        "          declineCta.style.display = '';",
        "          declineCta.addEventListener('click', (event) => {",
        "            event.preventDefault();",
        "            window.location.assign(postCheckoutNextUrl('decline', funnelStepId));",
        "          });",
        "        }",
        "        cta.setAttribute('aria-disabled', 'true');",
        "        cta.dataset.ctaDefaultLabel = cta.textContent;",
        "        cta.textContent = 'Loading...';",
        "        fetch(`${cta.dataset.checkoutApiBaseUrl}/upsell/session?session_id=${encodeURIComponent(funnelSessionId)}&clientID=${encodeURIComponent(cta.dataset.checkoutTenantId || '')}`)",
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
        "              session_id: funnelSessionId,",
        "              offer_id: cta.dataset.checkoutOfferId || '',",
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
