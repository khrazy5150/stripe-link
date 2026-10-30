from html import escape, unescape
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import base64
import json
import re
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from stripe_link.platform_config import default_favicon_small_url, default_favicon_url
from stripe_link.domain.bargain import FROM_PREFIX, derived_bargain
from stripe_link.domain.business_types import BUSINESS_TYPES, resolve_entity_type
from stripe_link.domain.coupon_grants import grant_prefix
from stripe_link.domain.composition import (
    compose_page, composition_key, default_cta_label, element_channel, expand_title_tokens,
    is_lead_composition, offerless_composition, shows_breadcrumb)
from stripe_link.domain.connect_sync import site_seo_enabled
from stripe_link.domain.documents import PRODUCT_CONDITIONS, is_offerless_page
from stripe_link.domain.page_views import link_id as link_click_id
from stripe_link.domain.social_links import display_entries as display_social_entries
from stripe_link.domain.social_links import section_link_entries as social_section_entries
from stripe_link.domain.social_links import linkable_on_platform_host
from stripe_link.domain.social_links import is_adult_host, network_glyph, network_label
from stripe_link.domain.social_links import verified_urls as verified_same_as_urls
from stripe_link.domain.opportunities import (
    SERVICE_SELECTION_CHOICE,
    STAGE_LANDING,
    STAGE_POST_PURCHASE,
    derived_offer_type,
    service_selection,
    stage_opportunities,
)
from stripe_link.domain.pricing import (
    PricingError, chosen_service_item, expand_offer, find_price, resolve_offer,
    selected_service_price_id, service_price_options, single_unit_price,
)
from stripe_link.domain.semantic import is_bundle, resolve_semantic_model, subject_from_model
from stripe_link.domain.reviews import aggregate_reviews, markup_eligible
from stripe_link.domain.image_crop import crop_style_vars
from stripe_link.domain.fonts import (
    REQUEST_WEIGHTS, families_to_load, imported_faces_for, is_system, resolve_families,
)
from stripe_link.domain.events import (
    live_occurrence as event_live_occurrence,
    next_occurrence as event_next_occurrence,
    open_occurrences as event_open_occurrences,
    seats_left as event_seats_left,
    starts_at as event_starts_at,
)
from stripe_link.domain.store_timezone import load_zone
from stripe_link.domain.video_embeds import parse_video_embed
from stripe_link.domain.section_theme import (LIGHT_INK as SECTION_LIGHT_INK, SECTION_TONES,
                                              readable_ink as section_readable_ink, section_theme_vars,
                                              tone_class)
from stripe_link.domain.tips import MAX_AMOUNT as TIP_MAX_AMOUNT
from stripe_link.domain.tips import MIN_AMOUNT as TIP_MIN_AMOUNT
from stripe_link.domain.tips import allows_custom as tip_allows_custom
from stripe_link.domain.tips import allows_one_time as tip_allows_one_time
from stripe_link.domain.tips import is_tip_price
from stripe_link.domain.tips import stamp_tip_jar
from stripe_link.domain.tips import preset_charges as tip_preset_charges
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

# `badge_bg` is the ground under the FILLED accent shapes -- numbered circles, the author pill, the
# ribbon button. It defaults to `accent`, and a preset only states it to get WHITE ink on a hue whose
# raw accent is too light for white to pass (author, 2026-10-15: dark numerals in a red circle read as
# a mistake). Darkening the ground rather than forcing the ink keeps `readable_ink` in charge, so the
# WCAG guarantee from 2026-10-12 still holds and a future preset cannot reintroduce the fault.
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
        "badge_bg": "#bd4f74",
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
        "badge_bg": "#257da4",
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
    # WHITE CARDS ON A NEAR-BLACK VIOLET PAGE, with a violet-to-fuchsia CTA (author's reference,
    # 2026-10-12). The two surfaces have OPPOSITE polarity, which is why `card_*` exists: the page is
    # light-on-dark and every card is dark-on-light. Before those tokens this preset was not expressible
    # -- ten card elements inherited the page's light ink and would have been white on white.
    "royal-velvet": {
        "background": "#0a0512",
        # The card is the page's opposite, not a tinted version of it. Everything that sits on one gets
        # an explicit dark ink below; nothing here may fall through to `text`.
        "card": "#ffffff",
        "text": "#f5f3ff",
        "muted": "#b3a8cc",
        "brand": "#8b5cf6",
        # Deep enough that `readable_ink` chooses WHITE on it (5.70) rather than near-black (3.91), which
        # is what the author asked for on the numbered badges and the ribbon CTA -- and it matches the
        # CTA gradient's first stop, so the purples on the page are one family rather than two.
        "accent": "#7c3aed",
        # The HEADLINE carries the page's purple as a gradient and `**emphasis**` is white -- the
        # inverse of this preset's first cut, which painted the gradient on the emphasised words and so
        # left the "**emphasis** text" colour control with nothing to do.
        #
        # `headline` stays white as the solid fallback: a browser without `background-clip:text` gets a
        # white headline, so the page degrades to "no gradient" rather than to "no words".
        "headline": "#ffffff",
        "headline_gradient": "linear-gradient(90deg,#7c3aed,#c026d3)",
        "headline_ink": "transparent",
        # White emphasis reads AGAINST the gradient it sits inside, and at 19.9 on the page itself. It
        # is a plain colour with no gradient of its own, which is what makes the control govern it.
        "highlight_text": "#ffffff",
        "cta_from": "#7c3aed",
        "cta_to": "#c026d3",
        "cta_text": "#ffffff",
        # The reference pill is a lighter violet, but white on it measures 4.23 -- under AA for the
        # small all-caps text it carries. Matching the CTA's start colour keeps the look and clears it.
        "chip_bg": "#7c3aed",
        "chip_text": "#ffffff",
        "chip_border": "#a78bfa",
        "savings_bg": "rgba(139,92,246,.14)",
        "savings_text": "#7c3aed",
        "savings_border": "rgba(139,92,246,.35)",
        "featured_badge_bg": "#7c3aed",
        "featured_badge_text": "#ffffff",
        "border": "#2a1b45",
        # --- everything that sits ON a card, which is dark-on-light ---
        "card_text": "#14101f",
        "card_muted": "#574e6b",
        "card_heading": "#14101f",
        "price_card_bg": "#ffffff",
        "price_card_border": "#e7e2f0",
        "price_card_selected_border": "#7c3aed",
        "price_title": "#14101f",
        "price_description": "#574e6b",
        # Struck-through, so it is quiet by role rather than by being hard to read: 3.65 was under AA.
        "price_regular": "#6f6880",
        "price_amount": "#7c3aed",
        "faq_bg": "#ffffff",
        "faq_border": "#e7e2f0",
        "faq_summary": "#14101f",
        "faq_text": "#574e6b",
        "refund_bg": "#ffffff",
        "refund_border": "#e7e2f0",
        "refund_summary": "#14101f",
        "refund_title": "#14101f",
        "refund_text": "#574e6b",
        "refund_return": "#14101f",
        # --- and everything that sits on the PAGE, which stays light-on-dark ---
        "hero_bg": "#140b26",
        "hero_border": "#2a1b45",
        "content_heading": "#ffffff",
        "content_text": "#b3a8cc",
        "content_border": "#2a1b45",
        "subheadline_text": "#b3a8cc",
        "brand_label_text": "#c4b5fd",
        "trust_badge_bg": "rgba(139,92,246,.16)",
        "trust_badge_text": "#d8b4fe",
        "trust_badge_border": "rgba(139,92,246,.4)",
        "countdown_bg": "#140b26",
        "countdown_text": "#ffffff",
        "legal_text": "#8b8299",
        "legal_link": "#c4b5fd",
    },
    "fire-sale": {
        "background": "#18181b",
        "card": "#27272a",
        "text": "#fafafa",
        "muted": "#a1a1aa",
        "brand": "#ef4444",
        "accent": "#f87171",
        "badge_bg": "#bc5656",
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
        "badge_bg": "#178640",
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
        "badge_bg": "#656dc1",
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
        "badge_bg": "#007dac",
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
        "badge_bg": "#e91b1b",
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
        "badge_bg": "#177bbe",
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
    "    .sl-countdown-digits{display:flex;gap:0.8rem;align-items:stretch}",
    # Each unit is a tile: the number large, its name small and quiet beneath. tabular-nums so the digits
    # do not jitter the tile's width as they tick.
    "    .sl-countdown-unit{display:grid;gap:0.2rem;justify-items:center;min-width:6.4rem;padding:0.8rem 1rem;border-radius:0.8rem;background:rgba(0,0,0,.22)}",
    "    .sl-countdown-unit b{font-family:var(--sl-font-heading);font-size:2.4rem;line-height:1;font-variant-numeric:tabular-nums}",
    "    .sl-countdown-unit small{font-size:1.1rem;letter-spacing:0.08em;text-transform:uppercase;opacity:0.75;font-weight:700}",
    "    @media (max-width: 480px){.sl-countdown-digits{gap:0.5rem}.sl-countdown-unit{min-width:0;flex:1;padding:0.6rem 0.4rem}.sl-countdown-unit b{font-size:1.9rem}.sl-countdown-unit small{font-size:0.95rem;letter-spacing:0.04em}}",
    "    .sl-countdown[data-sticky='true']{position:sticky;top:0;z-index:20}",
    "    .sl-countdown[data-transparent='true']{background:color-mix(in srgb,var(--sl-countdown-bg,var(--sl-card)) 85%,transparent)}",
    # Horizontal padding is dropped so the travel is EXACT: `padding-left:100%` below resolves against
    # this element's content box, so any side padding would start the clock that far inside the visible
    # edge and leave the same sliver showing when it exits. Vertical padding is untouched.
    "    .sl-countdown[data-marquee='true']{overflow:hidden;white-space:nowrap;justify-content:flex-start;padding-left:0;padding-right:0}",
    # Own keyframe name: `sl-marquee` is also defined by the client-logo strip further down, and the later
    # definition wins — which gave the countdown the logo animation (0 -> -50%), so it restarted from the
    # middle instead of wrapping off one edge and back in the other.
    # The content span had NO base rule: it was an inline box, so the icon and label started at the left
    # edge of a box the wide digit grid had stretched, and the label sat off-centre above centred tiles.
    # `text-align` cannot fix an inline element -- it needs to be a flex row that WRAPS, so the grid drops
    # to a second line and each line is centred on its own.
    "    .sl-countdown-content{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:0.8rem}",
    # The marquee scrolls one continuous strip; wrapping it would stack the halves and shear the animation.
    #
    # `padding-left:100%` is the travel, not decoration. A percentage padding resolves against the
    # CONTAINING BLOCK, so it is one banner width -- which parks the clock just past the right edge and
    # makes the element (banner + clock) wide. translateX(-100%) then moves it by its own width, so the
    # clock crosses the full banner and leaves by the left edge, with no stretch where it is invisible.
    #
    # The previous rule animated 100% -> -100% on an inline-flex span, where 100% was the CLOCK's own
    # width: a narrow clock appeared and vanished well inside the banner, never reaching either edge.
    #
    # The client-logo strip solves the same problem by DUPLICATING its row and travelling 0 -> -50%. That
    # cannot be copied here: the island writes the time into the first `[data-countdown-display]` it finds,
    # so a second copy would hang on whatever the server rendered.
    #
    # flex-start, because a centred flex item with a banner-width padding would be shifted by half its own
    # overflow and lose the alignment the padding just bought.
    "    .sl-countdown[data-marquee='true'] .sl-countdown-content{flex:none;display:inline-flex;flex-wrap:nowrap;align-items:center;gap:0.8rem;padding-left:100%;animation:sl-countdown-marquee var(--sl-countdown-marquee-duration,14s) linear infinite}",
    # Scrolling past the deadline reads as a live offer that has already gone.
    "    .sl-countdown[data-expired='true'] .sl-countdown-content{animation:none}",
    "    .sl-countdown time{font-family:var(--sl-font-mono);background:color-mix(in srgb,var(--sl-countdown-text) 16%,transparent);border-radius:0.4rem;padding:0.3rem 0.7rem}",
    "    @keyframes sl-countdown-marquee{from{transform:translateX(0)}to{transform:translateX(-100%)}}",
    "    .sl-brand-label{display:flex;align-items:center;justify-content:center;gap:0.8rem;color:var(--sl-brand-label-text);padding-top:1.6rem}",
    "    .sl-brand-label::before{content:'';width:1rem;height:1rem;border-radius:999px;background:var(--sl-brand-dot);box-shadow:0 0 0.8rem var(--sl-brand-dot)}",
    # p OR h1 -- the brand mark carries the H1 on a composition with no hero (see render_brand_label). The
    # styling is identical either way: which tag it is says what the heading MEANS, never how it looks, and a
    # bare h1 would arrive with a browser default size and margin that the p never had.
    "    .sl-brand-label p,.sl-brand-label h1{font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.08em;line-height:1.2;text-transform:uppercase;color:var(--sl-brand-label-text);margin:0}",
    "    .sl-brand-label a{color:inherit;text-decoration:none}",
    "    .sl-brand-label a:hover{text-decoration:underline;text-underline-offset:0.25em}",
    "    .sl-seo-title{text-align:center}",
    "    .sl-seo-title p{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;color:var(--sl-headline)}",
    "    .sl-mark-text{color:var(--sl-highlight-text)}",
    # A GRADIENT-FILLED highlight, for a theme that wants one (royal-velvet). `background-clip:text`
    # paints the gradient through the glyphs, which needs the ink to be transparent -- and a browser
    # without the property would then render NOTHING. So it lives behind @supports and the solid
    # `--sl-highlight-text` above stays the fallback: no gradient, but readable text.
    #
    # Inert for every other preset: `--sl-highlight-gradient` defaults to `none` and
    # `--sl-highlight-ink` to the same solid colour, so the block changes nothing it touches.
    "    @supports ((-webkit-background-clip:text) or (background-clip:text)){",
    "      .sl-mark-text{background-image:var(--sl-highlight-gradient,none);-webkit-background-clip:text;background-clip:text;color:var(--sl-highlight-ink,var(--sl-highlight-text))}",
    "    }",
    "    .sl-mark-bg{background:var(--sl-highlight-bg);color:var(--sl-highlight-bg-text);padding:0.1em 0.3em;border-radius:0.4rem}",
    "    .sl-headline{text-align:center;padding:0.8rem 0 0.4rem}",
    "    .sl-headline h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;font-weight:800;color:var(--sl-headline);letter-spacing:0}",
    "    .sl-subheadline{text-align:center}",
    "    .sl-subheadline p{font-size:1.5rem;line-height:1.55;color:var(--sl-subheadline-text);max-width:46rem;margin:0 auto}",
    # Hero headline + subheadline centered, matching the builder preview (which centers them for every template).
    "    .sl-hero{text-align:center}",
    "    .sl-hero h1{font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.2rem);line-height:1.2;font-weight:800;color:var(--sl-headline);letter-spacing:0;max-width:52rem;margin:0 auto}",
    "    .sl-hero p{font-size:1.5rem;line-height:1.55;color:var(--sl-subheadline-text);max-width:46rem;margin:0 auto}",
    # A GRADIENT-FILLED headline, behind @supports for the same reason as the highlight above: the ink
    # has to go transparent for the gradient to show through the glyphs, and a browser without
    # `background-clip:text` would then render an invisible H1. `--sl-headline` stays the fallback.
    #
    # `**emphasis**` inside the H1 keeps its own opaque colour, so it paints OVER the clipped gradient
    # rather than being swallowed by it -- white words inside a purple-gradient headline.
    #
    # Inert for every preset but royal-velvet: the gradient defaults to `none`.
    #
    # It sits AFTER both headline rules on purpose. The selectors have equal specificity, so placed
    # above `.sl-hero h1` the plain `color:var(--sl-headline)` there would win and the hero would
    # render opaque -- gradient clipped behind text nobody can see through.
    "    @supports ((-webkit-background-clip:text) or (background-clip:text)){",
    "      .sl-headline h1,.sl-hero h1{background-image:var(--sl-headline-gradient,none);-webkit-background-clip:text;background-clip:text;color:var(--sl-headline-ink,var(--sl-headline))}",
    "    }",
    "    .sl-hero-media{position:relative;padding-top:0.8rem}",
    # The brand overlay is absolutely positioned; without this its containing block is .sl-hero-media, which
    # GROWS when an inline or centred avatar sits below the image -- so a bottom-left brand slid down to sit
    # level with the avatar, and overlapped it on a phone. Anchoring to the figure pins it to the artwork.
    "    .sl-hero-figure{margin:0;position:relative}",
    "    .sl-hero-caption{font-size:1.3rem;color:var(--sl-muted);text-align:center;margin-top:0.6rem;line-height:1.4}",
    "    .sl-hero-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;border-radius:var(--sl-radius)}",
    "    .sl-hero-track::-webkit-scrollbar{display:none}",
    "    .sl-hero-slide{flex:0 0 100%;scroll-snap-align:center}",
    "    .sl-hero-slide img,.sl-hero-slide video{width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;border-radius:var(--sl-radius);border:1px solid var(--sl-hero-border);background:var(--sl-hero-bg)}",
    # The DEFAULT social cover: a link-in-bio page with no uploaded image still needs somewhere for the
    # avatar to sit, and an avatar overlapping nothing looks like a mistake. Painted from the preset's own
    # designed CTA pair, so it re-skins with the theme, cannot land off-palette, and weighs nothing -- no
    # file, no request, no LCP cost on the page type most likely to be opened from a phone. 5:2 rather than
    # the slides' 1:1 because it is a cover band; a square of flat colour is a colour field.
    "    .sl-hero-band{width:100%;aspect-ratio:5/2;border-radius:var(--sl-radius);border:1px solid var(--sl-hero-border);background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to))}",
    "    .sl-hero-nav{position:absolute;top:calc(50% + 0.4rem);transform:translateY(-50%);width:3.8rem;height:3.8rem;border-radius:50%;border:0;background:rgba(255,255,255,.9);color:#111;font-size:2.2rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.18)}",
    "    .sl-hero-prev{left:0.8rem}",
    "    .sl-hero-next{right:0.8rem}",
    "    .sl-hero-counter{position:absolute;right:0;top:50%;transform:translateY(-50%);font-size:1.1rem;font-weight:600;opacity:.6;letter-spacing:.02em}",
    # position:relative so the counter can sit at the right end without pushing the dots off centre --
    # the dots stay centred under the image whether or not there is a counter beside them.
    "    .sl-hero-dots{position:relative;display:flex;gap:0.6rem;justify-content:center;align-items:center;margin-top:0.8rem}",
    "    .sl-hero-dot{width:0.8rem;height:0.8rem;border-radius:50%;background:var(--sl-border);cursor:pointer}",
    "    .sl-hero-dot.is-active{background:var(--sl-brand)}",
    # Socialite hero overlays (plans/SOCIALITE_PARITY.md): positionable brand chip + profile avatar.
    "    .sl-hero-media.has-avatar{margin-bottom:6.4rem}",
    "    .sl-hero-media.has-avatar-top{margin-top:6.4rem}",
    "    .sl-hero-brand{position:absolute;display:flex;align-items:center;gap:0.8rem;background:rgba(0,0,0,.5);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);padding:0.8rem 1.4rem;border-radius:999px;font-family:var(--sl-font-accent);font-size:1.1rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,.92);z-index:6;pointer-events:none}",
    "    .sl-hero-brand-dot{width:0.8rem;height:0.8rem;border-radius:50%;background:var(--sl-brand)}",
    # Opt-in only. A dot that pulses on every page would be noise; on one page it reads as a live signal.
    "    .sl-hero-brand-dot.is-pulsing{animation:sl-brand-pulse 1.8s ease-in-out infinite}",
    # The same pulse on the brand LABEL's dot, which is a ::before rather than an element. The setting is
    # about "the brand dot", and the brand appears in one place or the other -- never both -- so it has to
    # reach whichever one the page actually has.
    "    .sl-brand-label.is-pulsing::before{animation:sl-brand-pulse 1.8s ease-in-out infinite}",
    "    @keyframes sl-brand-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.78)}}",
    "    .sl-hero-brand--top-left{top:1.6rem;left:1.6rem}",
    "    .sl-hero-brand--top-right{top:1.6rem;right:1.6rem}",
    "    .sl-hero-brand--bottom-left{bottom:1.6rem;left:1.6rem}",
    "    .sl-hero-brand--bottom-right{bottom:1.6rem;right:1.6rem}",
    # The ring is a solid disc (border colour, or a gradient) — never transparent padding, which would reveal
    # the page background and read as an uneven border where the avatar overhangs onto the page.
    "    .sl-avatar-wrap{position:absolute;bottom:-5.8rem;left:2.4rem;z-index:10;width:12.3rem;height:12.3rem;border-radius:50%;padding:0.4rem;background:var(--sl-avatar-ring,var(--sl-avatar-border,#ffffff));box-shadow:0 0.4rem 1.2rem rgba(0,0,0,.15)}",
    # Placement variants. The base rule above IS the overlay, so `overlay` needs no override and a page
    # saved before this existed keeps rendering exactly as it did.
    # Hangs off the TOP edge exactly as the bottom-left overlay hangs off the bottom -- about half the
    # avatar above the artwork. .has-avatar-top reserves the room, mirroring .has-avatar, so the overhang
    # pushes the hero down rather than colliding with whatever sits above it.
    # Hangs off the BOTTOM edge, centred -- the linkcloud/linktree shape, and what a page with a name and a
    # slogan under the avatar wants. Same overhang as the bottom-left overlay, so it reuses .has-avatar.
    "    .sl-avatar-wrap.sl-avatar--overlay_bottom{left:50%;transform:translateX(-50%)}",
    "    .sl-avatar-wrap.sl-avatar--overlay_top{bottom:auto;top:-5.8rem;left:50%;transform:translateX(-50%)}",
    # Name + slogan, the identity block under the avatar. Centred always: it belongs to a centred avatar, and
    # every reference page in this category centres it.
    "    .sl-hero-identity{display:grid;gap:0.4rem;justify-items:center;text-align:center;margin:1.6rem 0 0}",
    # p OR h1 -- the name carries the H1 when the brand mark is hidden (see render_page). Identical either
    # way: which tag it is says what the heading MEANS, never how it looks.
    "    .sl-hero-identity-name,h1.sl-hero-identity-name{font-family:var(--sl-font-heading);font-weight:800;font-size:2.4rem;line-height:1.2;color:var(--sl-text);margin:0}",
    # One line, always. A slogan that wraps on a phone stops being a slogan and starts being a paragraph --
    # the length cap makes that rare, and this makes it impossible.
    "    .sl-hero-identity-tagline{font-size:1.5rem;line-height:1.4;color:var(--sl-muted);margin:0;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    "    .sl-avatar-wrap.sl-avatar--inline,.sl-avatar-wrap.sl-avatar--centered{position:static;bottom:auto;left:auto;margin-top:1.6rem}",
    "    .sl-avatar-wrap.sl-avatar--centered{margin-left:auto;margin-right:auto}",
    "    .sl-avatar{width:100%;height:100%;border-radius:50%;object-fit:cover;background:var(--sl-hero-bg);display:block}",
    "    .sl-trust-badges{display:flex;flex-wrap:wrap;gap:0.8rem;justify-content:center}",
    # One claim per line, each its own card. Same badge markup; only the container changes.
    "    .sl-trust-badges.is-vertical{flex-direction:column;flex-wrap:nowrap;align-items:stretch;gap:1rem}",
    "    .sl-trust-badges.is-vertical .sl-trust-badge{justify-content:flex-start;border-radius:1rem;padding:1.4rem 1.8rem;font-size:1.5rem}",
    # Directional glyphs, coloured by the glyph itself so one choice looks the same everywhere it is used.
    # Tokens rather than literals, so a theme can take them over later; the defaults are the gold and red the
    # author asked for (2026-09-16).
    # ...and sized up: a text glyph next to an emoji reads as punctuation at the same font-size. `em` so it
    # tracks the badge, which is smaller in the horizontal pill row than in the vertical list.
    "    .sl-trust-badge [data-icon='\\276F'],.sl-trust-badge [data-icon='\\2771'],.sl-trust-badge [data-icon='\\BB'],.sl-trust-badge [data-icon='\\27A4']{color:var(--sl-icon-gold,#d4a12a);font-size:1.35em;line-height:1}",
    "    .sl-trust-badge [data-icon='\\2794']{color:var(--sl-icon-alert,#dc2626);font-size:1.35em;line-height:1}",
    "    .sl-trust-badge{display:flex;align-items:center;gap:0.6rem;border:1px solid var(--sl-trust-badge-border);background:var(--sl-trust-badge-bg);color:var(--sl-trust-badge-text);border-radius:999px;padding:0.8rem 1.4rem;font-family:var(--sl-font-accent);font-size:1.2rem;font-weight:800}",
    "    .sl-price-options{display:grid;grid-template-columns:1fr;gap:1.4rem;width:100%;margin:0 auto}",
    # The shipping element, which until now rendered entirely unstyled -- it shipped as structure with no
    # stylesheet at all (plans/LIVE_SHIPPING_RATES.md phase 3). Theme tokens throughout so it inherits the
    # page's palette rather than asserting its own, and the selected rate is marked by BORDER and weight
    # rather than by colour alone, so it survives a preset whose accent is close to its surface.
    "    .sl-shipping{width:min(52rem,100%);margin:2.4rem auto;text-align:left}",
    # The `hidden` ATTRIBUTE must win inside this element. A class selector that sets `display` beats the
    # UA's `[hidden]{display:none}`, so `.sl-shipping-summary{display:flex}` left an empty Subtotal /
    # Shipping / Total block on the page whenever there was nothing to put in it, and a `.sl-shipping-field`
    # region input would show for countries that do not use one. Scoped rather than global so it cannot
    # surprise anything else on the page.
    "    .sl-shipping [hidden]{display:none!important}",
    "    .sl-shipping-prompt{color:var(--sl-muted);margin:0 0 1rem}",
    "    .sl-shipping-where{display:flex;flex-wrap:wrap;gap:1.2rem;margin-bottom:1.6rem}",
    "    .sl-shipping-field{display:flex;flex-direction:column;gap:0.4rem;flex:1 1 14rem;min-width:0}",
    "    .sl-shipping-field>span{font-size:1.3rem;color:var(--sl-muted)}",
    "    .sl-shipping-field select,.sl-shipping-field input{width:100%;box-sizing:border-box;padding:0.9rem 1rem;font:inherit;font-size:1.5rem;color:var(--sl-text);background:var(--sl-background);border:1px solid var(--sl-border);border-radius:0.8rem}",
    "    .sl-shipping-field select:focus-visible,.sl-shipping-field input:focus-visible{outline:2px solid var(--sl-accent);outline-offset:1px}",
    "    .sl-shipping-rates{display:flex;flex-direction:column;gap:0.8rem}",
    "    .sl-shipping-rate{display:flex;align-items:center;gap:1rem;padding:1.1rem 1.4rem;border:1px solid var(--sl-border);border-radius:1rem;cursor:pointer}",
    "    .sl-shipping-rate:has(input:checked){border-color:var(--sl-accent);border-width:2px;padding:1rem 1.3rem}",
    "    .sl-shipping-rate:has(input:focus-visible){outline:2px solid var(--sl-accent);outline-offset:2px}",
    "    .sl-shipping-rate-text{display:flex;flex-direction:column;gap:0.2rem;flex:1;min-width:0}",
    "    .sl-shipping-rate-label{font-weight:700;font-size:1.5rem}",
    "    .sl-shipping-rate-estimate{color:var(--sl-muted);font-size:1.3rem}",
    "    .sl-shipping-rate-price{font-weight:800;font-size:1.6rem;white-space:nowrap;font-variant-numeric:tabular-nums}",
    "    .sl-shipping-note{color:var(--sl-muted);font-size:1.4rem;margin:0 0 1rem}",
    "    .sl-shipping[data-shipping-state='error'] .sl-shipping-note{color:var(--sl-icon-alert,#dc2626)}",
    "    .sl-shipping-retry{align-self:flex-start;margin-bottom:1rem;padding:0.6rem 1.2rem;font:inherit;font-size:1.4rem;color:var(--sl-text);background:transparent;border:1px solid var(--sl-border);border-radius:0.8rem;cursor:pointer}",
    "    .sl-shipping-summary{margin:1.6rem 0 0;display:flex;flex-direction:column;gap:0.6rem;font-size:1.5rem}",
    "    .sl-shipping-summary>div{display:flex;justify-content:space-between;gap:1rem}",
    "    .sl-shipping-summary dt,.sl-shipping-summary dd{margin:0}",
    "    .sl-shipping-summary dd{font-variant-numeric:tabular-nums}",
    "    .sl-shipping-total-row{padding-top:0.6rem;border-top:1px solid var(--sl-border);font-weight:800;font-size:1.7rem}",
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
    # A TIP JAR's cards carry no image, so the picture column is dropped rather than left empty -- an empty
    # 9rem column reads as a missing image. The amount is the card, so it gets the larger type.
    # Two class names on the selector, deliberately: the ONLY deviation a tip card makes from the standard
    # price card is dropping the image column, and written as a plain `.sl-tip-option` it lost to the mobile
    # `.sl-price-option` rule further down the sheet -- same specificity, later wins. Under 700px the card
    # got its 3-column template back, the amount fell into the picture column and the radio into the middle
    # one instead of the right edge. Raising specificity settles it at every width, in one rule rather than
    # a second copy inside the media query that would have to be kept in step.
    "    .sl-price-option.sl-tip-option{grid-template-columns:minmax(0,1fr) auto}",
    "    .sl-tip-option strong{font-size:2.2rem;-webkit-line-clamp:1;line-clamp:1}",
    "    .sl-tip-input{display:inline-flex;align-items:center;gap:0.4rem;margin-top:0.4rem;border:1px solid var(--sl-price-card-border);border-radius:0.8rem;padding:0.4rem 1rem;background:var(--sl-background);color:var(--sl-price-title);font-family:var(--sl-font-heading);font-size:1.8rem;width:max-content}",
    "    .sl-tip-input input{width:9rem;border:0;background:transparent;color:inherit;font:inherit;padding:0.2rem 0}",
    "    .sl-tip-input input:focus{outline:none}",
    "    .sl-tip-note{margin:0.4rem 0 0;color:var(--sl-price-description);font-size:1.3rem;line-height:1.45}",
    "    .sl-tip-freq{color:var(--sl-price-description);font-size:1.2rem;letter-spacing:0.04em;text-transform:uppercase}",
    "    .sl-tip-frequency{display:flex;gap:0.6rem;justify-content:center;margin:0 auto 1.4rem;padding:0.4rem;border:1px solid var(--sl-price-card-border);border-radius:999px;width:max-content;background:var(--sl-price-card-bg)}",
    "    .sl-tip-freq-option{border:0;border-radius:999px;padding:0.6rem 1.6rem;background:transparent;color:var(--sl-price-description);font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;cursor:pointer}",
    "    .sl-tip-freq-option.is-selected{background:var(--sl-price-card-selected-border);color:var(--sl-cta-text)}",
    # Same line-clamp as the link cards, for the same reason: the tenant picks the font, so a character
    # limit would be a proxy for pixels. Price options stack in one column rather than sitting side by
    # side, so a long description does not distort a neighbour -- it pushes the CHECKOUT CTA down the
    # page, which is worse. Uniform option heights also make tiers scannable, which is the whole job of
    # a price selector.
    #
    # The full text is kept in title= and, on pages carrying product_details, rendered in full there --
    # so clamping a tier's summary never hides the only copy of what the buyer is choosing between.
    "    .sl-price-option strong{display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}",
    "    .sl-price-description{display:-webkit-box;-webkit-line-clamp:3;line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}",
    # Expanded state drops the clamp entirely. A price description is what the buyer is CHOOSING ON, and
    # the title= tooltip that rescues a clamped link card does not exist on touch -- which is exactly where
    # the clamp bites hardest, because the copy column is narrowest there.
    "    .sl-price-description.is-expanded{display:block;-webkit-line-clamp:none;line-clamp:none;overflow:visible}",
    "    .sl-price-more{align-self:start;background:none;border:0;padding:0;margin:.2rem 0 0;font:inherit;font-size:1.2rem;color:var(--sl-legal-link);text-decoration:underline;cursor:pointer}",
    "    .sl-price-row{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;margin-top:1rem}",
    "    .sl-price-amount{font-family:var(--sl-font-accent);font-size:2rem;font-weight:700;color:var(--sl-price-amount)}",
    # Attached to the amount and quieter than it: it qualifies the number rather than competing with it.
    "    .sl-price-every{margin-left:0.2rem;font-family:var(--sl-font-accent);font-size:1.4rem;font-weight:600;color:var(--sl-muted)}",
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
    "    .sl-content-block{display:grid;grid-template-columns:minmax(0,1fr) minmax(12rem,18rem);gap:1.2rem;align-items:center}",
    # The rule above used to carry `border-top` + `padding-top`, so every content block drew a line above
    # itself whether or not the page wanted one. A plain paragraph is the common case now that a title is
    # optional, and a rule over every paragraph reads as a document, not a landing page. Opt-in instead.
    "    .sl-content-blocks--divided .sl-content-block{border-top:1px solid var(--sl-content-border);padding-top:1.6rem}",
    "    .sl-content-block h2{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:0.8rem;color:var(--sl-content-heading)}",
    "    .sl-content-block p{color:var(--sl-content-text);font-size:1.5rem;line-height:1.6}",
    # Space between paragraphs of body copy. Every body class sets `margin:0`, so without this the
    # paragraphs stack flush and read as the run-on block they were split up to fix. Two classes outrank
    # the one-class `margin:0` rules, so it wins wherever it applies.
    "    .sl-para + .sl-para{margin-top:0.9em}",
    # BAND: the full-width announcement bar. Painted with the tenant's own ^^highlight^^ tokens, which is
    # what makes it the amber strip in the reference without hardcoding a colour the theme cannot reach.
    "    .sl-event-date{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:center;gap:0.6rem 1rem;text-align:center}",
    "    .sl-event-date.is-band{background:var(--sl-highlight-bg);color:var(--sl-highlight-bg-text);border-radius:0.8rem;padding:1.2rem 1.6rem;font-weight:800;text-transform:uppercase;letter-spacing:0.04em}",
    # CARD: the quieter form -- a bordered panel that sits in the flow rather than interrupting it.
    "    .sl-event-date.is-card{background:var(--sl-card);color:var(--sl-card-text,var(--sl-content-text));border:1px solid var(--sl-content-border);border-radius:var(--sl-radius);padding:1.6rem}",
    "    .sl-event-date-label{font-weight:700;letter-spacing:0.06em;text-transform:uppercase;font-size:1.3rem}",
    "    .sl-event-date-value{font-family:var(--sl-font-heading);font-size:1.8rem;line-height:1.3}",
    "    .sl-event-date.is-band .sl-event-date-value{font-size:1.5rem}",
    "    .sl-event-date-icon{font-size:1.6rem;line-height:1}",
    "    .sl-info{display:grid;gap:1.6rem}",
    "    .sl-info-heading{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;color:var(--sl-content-heading);text-align:center}",
    "    .sl-info-cards{list-style:none;display:grid;gap:1.6rem;counter-reset:sl-info}",
    # position:relative so the badge can overhang this card rather than the page.
    "    .sl-info-card{position:relative;background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:var(--sl-radius);padding:2.4rem}",
    # The marked card is outlined in the page accent and nothing else changes -- it is the one to look at,
    # not a different kind of card.
    "    .sl-info-card.is-featured{border-color:var(--sl-accent);box-shadow:0 0 0 1px var(--sl-accent)}",
    "    .sl-info-icon{font-size:2rem;line-height:1;margin-right:0.4rem}",
    "    .sl-info-label{font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--sl-card-muted,var(--sl-muted))}",
    # The counter lives in CSS so reordering cards renumbers them and the glyph carries no content.
    "    .sl-info-cards{counter-reset:sl-info}",
    "    .sl-info-card{counter-increment:sl-info}",
    "    .sl-info-count::before{content:counter(sl-info);font-family:var(--sl-font-heading);font-size:2.4rem;font-style:italic;letter-spacing:0;color:var(--sl-accent)}",
    "    .sl-info-title{font-family:var(--sl-font-heading);font-size:1.9rem;line-height:1.25;color:var(--sl-card-heading,var(--sl-content-heading))}",
    "    .sl-info-body{font-size:1.5rem;line-height:1.6;color:var(--sl-card-text,var(--sl-content-text))}",
    # The sticker: the ^^highlight^^ colours the tenant already controls, in the theme's accent face.
    # STRAIGHT by default -- a tilt is a strong stylistic choice, and a default that must be undone is a
    # worse default than one that must be opted into.
    "    .sl-info.has-crooked-badges .sl-info-badge{transform:rotate(-2deg)}",
    "    .sl-info-badge{position:absolute;top:-1.2rem;right:1.6rem;background:var(--sl-highlight-bg);color:var(--sl-highlight-bg-text);font-family:var(--sl-font-accent);font-size:1.3rem;line-height:1.3;padding:0.5rem 1rem;border-radius:0.6rem;max-width:min(26rem,70%)}",
    # NUMBERED: title in a narrow column, body beside it. Only where there is room -- on a phone the two
    # columns become two strips four characters wide, which is what the author's own screenshot shows.
    "    .sl-info.is-numbered .sl-info-card{display:grid;gap:0.4rem 1.6rem}",
    "    @media (min-width: 40rem){.sl-info.is-numbered .sl-info-card{grid-template-columns:3rem 14rem minmax(0,1fr);align-items:start}.sl-info.is-numbered .sl-info-label{grid-row:1;grid-column:1}.sl-info.is-numbered .sl-info-title{grid-row:1;grid-column:2}.sl-info.is-numbered .sl-info-body{grid-row:1;grid-column:3}}",
    # LABELLED: eyebrow, title, body stacked at full width.
    "    .sl-info.is-labelled .sl-info-card{display:grid;gap:0.8rem}",
    "    .sl-info.is-labelled .sl-info-title{font-size:2.4rem}",
    "    .sl-photos{display:grid;gap:1.6rem}",
    "    .sl-photo-heading{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;color:var(--sl-content-heading);text-align:center}",
    "    .sl-photo{margin:0;display:grid;gap:0.8rem}",
    # Radius + overflow on the CONTAINER, never on the <img>. A cropped image is a scaled, offset picture
    # inside this box; rounding the image itself rounds the part that is already overflowing and clipped,
    # which showed as a straight-cornered photo with a curved ghost (fixed once already, 2026-10-12).
    "    .sl-photo-media{border-radius:var(--sl-radius);overflow:hidden}",
    # Natural proportions when there is no crop: a screenshot is only proof while its text is readable, so
    # nothing letterboxes it. `:not(.sl-cropped)` because the crop surface owns its own sizing.
    "    .sl-photo-media:not(.sl-cropped) img{width:100%;height:auto;display:block}",
    "    .sl-photo figcaption{font-size:1.4rem;line-height:1.5;color:var(--sl-content-text);text-align:center}",
    # 2-up only where there is room for it; a pair of half-width images on a phone is two unreadable images.
    "    @media (min-width: 42rem){.sl-photos.is-side-by-side{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.sl-photos.is-side-by-side .sl-photo-heading{grid-column:1/-1}}",
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
    "    .sl-next-step{background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:var(--sl-radius);padding:1.6rem;display:grid;gap:0.5rem;text-align:center;color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-next-step-icon{font-size:2.4rem}",
    "    .sl-next-step strong{font-family:var(--sl-font-heading);font-size:1.5rem;color:var(--sl-headline)}",
    "    .sl-next-step p{color:var(--sl-card-muted,var(--sl-content-text));font-size:1.35rem;line-height:1.5}",
    "    .sl-ty-dl{display:grid;justify-items:center;margin-top:1.6rem}",
    "    .sl-ty-dl[hidden]{display:none}",
    "    .sl-ty-dl-card{background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:var(--sl-radius);padding:2rem 2.4rem;display:grid;gap:1rem;justify-items:center;text-align:center;max-width:42rem;width:100%;color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-ty-dl-icon{font-size:2.8rem;line-height:1}",
    "    .sl-ty-dl-card strong{font-family:var(--sl-font-heading);font-size:1.8rem;color:var(--sl-headline)}",
    "    .sl-ty-dl-file{color:var(--sl-card-muted,var(--sl-content-text));font-size:1.35rem;word-break:break-all}",
    "    .sl-ty-dl-note{color:var(--sl-card-muted,var(--sl-content-text));font-size:1.25rem}",
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
    # A LEAD page's cta is the FORM, not a buy bar, so it belongs in the flow. Fixed, it left the document
    # entirely: the footer floated up under the hero and the form sat pinned to the bottom of the viewport
    # with a screen of white space between them -- the page the author called an abomination (2026-09-15).
    # The reserved strip the fixed bar needs goes with it, or the page ends in 12rem of nothing.
    # The page gutter rule up top excludes `.sl-checkout-cta`, because the BUY cta is a fixed bottom bar
    # and is meant to be full-bleed. These three are not: they are inline blocks in the flow, so they take
    # the same gutter every other section gets. Without it the card sat flush against both edges on a
    # phone -- invisible at 52rem on a desktop, obvious the moment the closed notice went red (reported
    # 2026-10-15). Same specificity as that rule, so this has to stay BELOW it.
    "    .sl-checkout-cta.sl-email-cta,.sl-checkout-cta.sl-call-cta,.sl-checkout-cta.sl-external-cta{position:static;z-index:auto;background:none;padding:0;width:min(52rem,calc(100% - 3.2rem));margin-left:auto;margin-right:auto}",
    "    body:has(.sl-email-cta){padding-bottom:0}",
    "    body:has(.sl-email-cta) main{padding-bottom:4rem}",
    # THE CTA PANEL -- one implementation for call, external and download (see render_cta_panel). They differ
    # only in what the big line says: a phone number, a hostname, a filename.
    "    .sl-checkout-cta.sl-call-cta,.sl-checkout-cta.sl-external-cta{display:block;width:min(52rem,calc(100% - 3.2rem));margin-left:auto;margin-right:auto}",
    # THE TONE SCALE. Sets the --sl-section-* tokens and paints nothing itself, so every element that already
    # reads them (author bio, bragging points, quote, page ribbon, price highlight, cta panel) gains tones
    # from a single class. Every value comes from the page theme -- no literal colours here, ever.
    # Each tone pairs a surface with the ink the PRESET designed for it -- (text, background),
    # (cta gradient, cta_text), (card, text). Never one pair's surface with another's ink: that is what
    # inverted on the eight dark presets, where --sl-text is near-white.
    "    .sl-tone-contrast{--sl-section-bg:var(--sl-text);--sl-section-ink:var(--sl-background);--sl-section-border:transparent}",
    "    .sl-tone-accent{--sl-section-bg:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));--sl-section-ink:var(--sl-cta-text);--sl-section-border:transparent}",
    "    .sl-tone-soft{--sl-section-bg:var(--sl-card);--sl-section-ink:var(--sl-card-text);--sl-section-border:var(--sl-content-border)}",
    # A button sitting on a FILLED panel becomes the page's own surface -- background + text, the one pair
    # that is readable on every preset in either polarity -- so it reads as cut out of the panel rather than
    # dissolving into it. `soft` is already the card colour, so its button stays the ordinary gradient CTA.
    "    .sl-tone-contrast .sl-cta,.sl-tone-accent .sl-cta{background:var(--sl-background);color:var(--sl-text)}",
    "    .sl-cta-panel{display:grid;justify-items:center;gap:1.2rem;padding:3.2rem 2.4rem;border-radius:1.4rem;text-align:center;background:var(--sl-section-bg,var(--sl-text));color:var(--sl-section-ink,var(--sl-cta-text));border:1px solid var(--sl-section-border,transparent)}",
    "    .sl-cta-kicker{margin:0;font-family:var(--sl-font-accent);font-size:1.3rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;opacity:.75}",
    # The identifying line. Sized to be read across a room and tapped without aiming. `tabular-nums` so a
    # number's digits do not shimmy; `break-word` because a hostname runs longer than a phone number and must
    # not escape the panel.
    "    .sl-cta-lead{display:block;max-width:100%;color:inherit;font-family:var(--sl-font-accent);font-weight:900;font-size:clamp(2.6rem,7vw,4.4rem);line-height:1.05;letter-spacing:0.01em;font-variant-numeric:tabular-nums;overflow-wrap:break-word;text-decoration:none}",
    "    .sl-cta-panel .sl-cta-panel-button{min-width:16rem}",
    # The STICKY bar. A phone scroller should never have to find their way back to the action.
    "    .sl-cta-sticky{position:fixed;left:0;right:0;bottom:0;z-index:10;display:flex;justify-content:center;padding:1.2rem 1.6rem calc(1.2rem + env(safe-area-inset-bottom));background:linear-gradient(transparent,var(--sl-cta-scrim) 35%)}",
    "    .sl-cta-sticky .sl-cta-panel-button{width:min(52rem,100%);text-align:center}",
    # It is fixed, so the page has to reserve the strip it covers -- the same bargain the sales bar makes.
    "    body:has(.sl-cta-sticky){padding-bottom:0}",
    "    body:has(.sl-cta-sticky) main{padding-bottom:11rem}",
    "    .sl-cta{display:inline-flex;width:min(52rem,100%);align-items:center;justify-content:center;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:1rem;padding:1.5rem 1.8rem;font-family:var(--sl-font-accent);font-size:1.7rem;font-weight:900;text-decoration:none}",
    "    .sl-cta.is-connecting{opacity:.72;cursor:wait;pointer-events:none}",
    "    .sl-decline-cta{width:auto;background:none;color:var(--sl-muted);text-decoration:underline;font-weight:600;font-size:1.3rem;padding:0.4rem}",
    "    .sl-downsell-note{text-align:center;color:var(--sl-muted);font-size:1.4rem;font-weight:600;margin-bottom:0.4rem}",
    "    .sl-occurrence-picker{display:grid;gap:0.6rem;border:0;padding:0;margin:0}",
    "    .sl-occurrence-picker legend{font-size:1.3rem;font-weight:700;padding:0 0 0.4rem;color:var(--sl-price-title)}",
    "    .sl-occurrence{display:flex;align-items:center;gap:0.8rem;padding:1rem 1.2rem;border:1px solid var(--sl-price-card-border);border-radius:0.8rem;cursor:pointer;color:var(--sl-price-title)}",
    "    .sl-occurrence:has(input:checked){border-color:var(--sl-price-card-selected-border);box-shadow:0 0 0 1px var(--sl-price-card-selected-border)}",
    "    .sl-occurrence-seats{margin-left:auto;font-size:1.2rem;font-weight:700;color:var(--sl-price-amount)}",
    "    .sl-event-live-heading{font-family:var(--sl-font-heading);font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-event-join{display:block;text-align:center;text-decoration:none}",
    "    .sl-event-closed-heading{font-family:var(--sl-font-heading);font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-lead-dialog{border:0;padding:0;background:none;max-width:min(52rem,calc(100vw - 3.2rem));width:100%}",
    "    .sl-lead-dialog::backdrop{background:rgba(0,0,0,0.6)}",
    "    .sl-lead-dialog .sl-lead-form{width:100%}",
    "    .sl-lead-dialog-dismiss{display:flex;justify-content:flex-end;margin:0 0 -3.2rem 0;position:relative;z-index:1}",
    "    .sl-lead-dialog-close{border:0;background:none;color:var(--sl-price-description);font-size:2.4rem;line-height:1;padding:0.6rem 1rem;cursor:pointer}",
    "    .sl-checkout-cta.is-dialog{display:flex;justify-content:center}",
    "    .sl-lead-form{display:flex;flex-direction:column;gap:1rem;width:min(52rem,100%);background:var(--sl-price-card-bg);border:1px solid var(--sl-price-card-border);border-radius:1.2rem;padding:1.6rem}",
    "    .sl-lead-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.8rem;color:var(--sl-price-title)}",
    "    .sl-lead-description{font-size:1.4rem;color:var(--sl-price-description)}",
    # An ALERT, not a card: the whole job of this block is to contradict the page above it, so it must not
    # look like the page above it. Deliberately NOT a catalog token -- a catalog token has to be defined by
    # every preset, and a stop sign that changes colour with the palette is not a stop sign. Same shape as
    # `--sl-icon-alert` above: an overridable var with a strong default, not an advertised control.
    "    .sl-event-closed .sl-lead-form{background:var(--sl-closed-bg,#dc2626);border-color:var(--sl-closed-bg,#dc2626);gap:0.6rem}",
    "    .sl-event-closed .sl-event-closed-heading{color:var(--sl-closed-text,#fff);font-size:2.2rem;font-weight:800;line-height:1.25}",
    "    .sl-event-closed .sl-lead-description{color:var(--sl-closed-text,#fff);font-size:1.5rem;opacity:0.92}",
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
    "    .sl-testimonial{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:1.8rem;background:var(--sl-card);border:1px solid var(--sl-content-border);border-radius:1.6rem;padding:2rem 2rem 2rem 4.6rem;margin:0;color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-testimonial::before{content:'\\201C';position:absolute;left:1.4rem;top:0.4rem;font-family:var(--sl-font-heading);font-size:5.2rem;line-height:1;color:var(--sl-accent);opacity:0.32;pointer-events:none}",
    "    .sl-testimonial-body{display:grid;gap:1.2rem;min-width:0}",
    "    .sl-testimonial img{width:7.2rem;height:7.2rem;border-radius:50%;object-fit:cover;box-shadow:0 0 0 0.3rem var(--sl-card),0 0 0 0.5rem var(--sl-accent)}",
    "    .sl-testimonial blockquote{margin:0;font-size:1.8rem;line-height:1.55;color:var(--sl-card-text,var(--sl-content-text))}",
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
    "    .sl-author-name{margin:0;display:inline-block;padding:0.4rem 1.4rem;border-radius:999px;background:var(--sl-section-border,var(--sl-badge-bg,var(--sl-accent)));color:var(--sl-section-border-ink,var(--sl-badge-ink,#fff));font-size:1.3rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em}",
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
    # The VALUE carries the accent, the label stays body ink: the figure is the claim and the label only says
    # what it counts, so colouring both flattens the distinction the element exists to make (author,
    # 2026-09-30). Falls back to the section ink, so a preset without an accent is unchanged rather than
    # invisible.
    "    .sl-brag-value{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2.4rem,5vw,3.4rem);line-height:1.1;font-weight:800;color:var(--sl-accent,var(--sl-section-ink,var(--sl-text)))}",
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
    "    .sl-quote-fancy .sl-quote-figure{margin:0 auto;width:100%;max-width:74rem;display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:2.4rem;padding:3.2rem;border-radius:1rem;background:var(--sl-section-accent,var(--sl-badge-bg,var(--sl-accent)));color:var(--sl-section-accent-ink,var(--sl-badge-ink,#fff))}",
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
    "    .sl-numbered-item{counter-increment:sl-num;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:1.6rem;padding:1.6rem 2rem;border:1px solid var(--sl-content-border);border-radius:1rem;background:var(--sl-card);color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-numbered-item::before{content:counter(sl-num);display:grid;place-items:center;width:3.6rem;height:3.6rem;border-radius:50%;background:var(--sl-badge-bg,var(--sl-accent));color:var(--sl-badge-ink,#fff);font-family:var(--sl-font-heading);font-size:1.8rem;font-weight:700;line-height:1}",
    "    .sl-numbered-text{margin:0;font-size:1.6rem;line-height:1.55;color:var(--sl-card-muted,var(--sl-content-text))}",
    # PAGE RIBBON — an Attention Block. Uses the shared section override, so a tenant can make it break
    # the page deliberately; that is the entire point of an interruption.
    "    .sl-page-ribbon{display:grid;gap:2rem;align-items:center;margin:0 auto;padding:3.2rem;border-radius:1.4rem;background:var(--sl-section-bg,var(--sl-card));color:var(--sl-section-ink,var(--sl-card-text,var(--sl-text)));max-width:74rem}",
    "    .sl-page-ribbon.is-image_left{grid-template-columns:minmax(0,22rem) minmax(0,1fr)}",
    "    .sl-page-ribbon.is-centered{grid-template-columns:minmax(0,1fr);text-align:center;justify-items:center}",
    "    .sl-page-ribbon.is-compact{grid-template-columns:minmax(0,12rem) minmax(0,1fr);gap:1.6rem;padding:1.6rem 2rem}",
    "    .sl-ribbon-media{border-radius:1rem;overflow:hidden}",
    "    .sl-ribbon-media:not(.sl-cropped) img{width:100%;height:auto;display:block}",
    # A cropped image is scaled up inside a clipped box and offset, so the chosen region exactly fills it.
    # The CONTAINER clips -- `overflow:hidden` plus whatever radius the surface itself sets. The cropped
    # image must NOT inherit that radius: a crop makes the image TALLER than its box (here 227px inside a
    # 140px circle), so `border-radius:50%` on the image describes an ellipse of the IMAGE's box, not the
    # container's. The two do not line up, and the mismatch eats the picture from the sides -- 3.8px of
    # black at the top of the circle, 91.6px near the bottom, which is exactly the crescents reported on
    # a live author photo (2026-10-12). The container's own clip was always doing the real work.
    "    .sl-cropped{position:relative;overflow:hidden;aspect-ratio:var(--sl-crop-ar,1)}",
    "    .sl-embed{position:relative;width:100%;aspect-ratio:var(--sl-embed-ar,16/9);overflow:hidden;border-radius:1rem;background:#000}",
    "    .sl-video-block{max-width:74rem;margin:0 auto}",
    "    .sl-video-heading{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:1.2rem;color:var(--sl-content-heading);text-align:center}",
    "    .sl-video-frame{position:relative;width:100%;overflow:hidden;border-radius:1rem;background:#000}",
    # An uploaded file is sized here; an embed brings its own aspect-ratio box with it.
    "    .sl-video-frame>video{display:block;width:100%;height:100%;object-fit:contain;background:#000}",
    "    .sl-video-frame{aspect-ratio:var(--sl-video-ar,16/9)}",
    # A chromeless video IS its own play/pause control, so it has to look and focus like one.
    "    .sl-video-frame>video[data-sl-video-tap]{cursor:pointer}",
    "    .sl-video-frame>video[data-sl-video-tap]:focus-visible{outline:3px solid var(--sl-accent,#2563eb);outline-offset:2px}",
    # A vertical video on a wide screen must not become a full-height column; the frame stays centred and
    # bounded by the viewport instead.
    "    .sl-video-block.is-tall .sl-video-frame{max-width:min(100%,45vh);margin:0 auto}",
    "    .sl-video-caption{margin-top:0.8rem;text-align:center;font-size:1.4rem;color:var(--sl-content-text)}",
    "    .sl-embed .sl-embed-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;border:0}",
    "    .sl-embed .sl-embed-poster.is-blank{background:linear-gradient(135deg,#1f2937,#0f172a)}",
    "    .sl-embed iframe{position:absolute;inset:0;width:100%;height:100%;border:0}",
    "    .sl-embed-play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);border:0;background:none;padding:0;cursor:pointer;line-height:0}",
    "    .sl-embed-play .sl-embed-play-bg{fill:#212121;fill-opacity:0.8;transition:fill-opacity 0.15s}",
    "    .sl-embed-play:hover .sl-embed-play-bg,.sl-embed-play:focus-visible .sl-embed-play-bg{fill:#f00;fill-opacity:1}",
    "    .sl-embed-play:focus-visible{outline:2px solid #fff;outline-offset:4px;border-radius:0.6rem}",
    "    .sl-before-after{max-width:74rem;margin:0 auto}",
    "    .sl-ba-heading{font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25;margin-bottom:1.2rem;color:var(--sl-content-heading);text-align:center}",
    "    .sl-ba-frame{position:relative;aspect-ratio:var(--sl-ba-ar,4/3);overflow:hidden;border-radius:1rem;background:var(--sl-card);touch-action:none;user-select:none;color:var(--sl-card-text,var(--sl-text))}",
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
    "    .sl-cropped>img{position:absolute;top:var(--sl-crop-y,0);left:var(--sl-crop-x,0);width:var(--sl-crop-w,100%);height:var(--sl-crop-h,100%);max-width:none}",
    "    .sl-ribbon-copy{display:grid;gap:0.8rem;min-width:0}",
    "    .sl-page-ribbon.is-centered .sl-ribbon-copy{justify-items:center}",
    "    .sl-ribbon-eyebrow{margin:0;font-size:1.3rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;opacity:0.75}",
    "    .sl-ribbon-headline{margin:0;font-family:var(--sl-font-heading);font-size:clamp(2rem,4vw,2.8rem);line-height:1.2}",
    "    .sl-ribbon-body{margin:0;font-size:1.6rem;line-height:1.55;opacity:0.85}",
    # The CTA takes the section accent when the ribbon breaks the pattern, so its ink is the DERIVED
    # accent-ink and a tenant cannot colour the button into invisibility.
    "    .sl-ribbon-cta{justify-self:start;display:inline-flex;align-items:center;margin-top:0.8rem;padding:1.1rem 2.2rem;border-radius:999px;background:var(--sl-section-accent,var(--sl-badge-bg,var(--sl-accent)));color:var(--sl-section-accent-ink,var(--sl-badge-ink,#fff));font-size:1.5rem;font-weight:700;text-decoration:none}",
    "    .sl-page-ribbon.is-centered .sl-ribbon-cta{justify-self:center}",
    "    .sl-page-ribbon.is-compact .sl-ribbon-headline{font-size:clamp(1.7rem,3vw,2.1rem)}",
    # The download dialog. Built by script, so its styles ship with the page whether or not it is used --
    # a few hundred bytes against a round trip to fetch them at the moment a visitor is deciding.
    "    .sl-dl-backdrop{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:2rem;background:rgba(0,0,0,.55)}",
    "    .sl-dl-card{width:100%;max-width:38rem;display:grid;gap:1.2rem;padding:2.4rem;border-radius:1.2rem;background:var(--sl-card,#fff);color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-dl-title{margin:0;font-family:var(--sl-font-heading);font-size:2rem;line-height:1.25}",
    "    .sl-dl-field{display:grid;gap:0.4rem;font-size:1.4rem}",
    "    .sl-dl-field input{padding:1rem 1.2rem;border:1px solid var(--sl-content-border);border-radius:0.8rem;font-size:1.6rem;font-family:inherit}",
    "    .sl-dl-error{margin:0;color:#b91c1c;font-size:1.4rem}",
    "    .sl-dl-actions{display:flex;gap:1rem;justify-content:flex-end}",
    "    .sl-dl-actions button{padding:1rem 1.8rem;border-radius:999px;font-size:1.5rem;font-weight:700;cursor:pointer;font-family:inherit}",
    "    .sl-dl-cancel{background:none;border:1px solid var(--sl-content-border);color:inherit}",
    "    .sl-dl-submit{border:0;background:var(--sl-badge-bg,var(--sl-accent));color:var(--sl-badge-ink,#fff)}",
    "    .sl-dl-card{position:relative}",
    "    .sl-dl-dismiss{position:absolute;top:0.8rem;right:1rem;border:0;background:none;color:inherit;font-size:2.2rem;line-height:1;cursor:pointer;opacity:0.55}",
    "    .sl-ribbon-cta:disabled,.sl-dl-submit:disabled{opacity:0.6;cursor:default}",
    "    .sl-price-highlight{display:grid;gap:0.6rem;justify-items:center;text-align:center;padding:3.2rem 2rem;background:var(--sl-section-bg,transparent);color:var(--sl-section-ink,var(--sl-text))}",
    "    .sl-bargain-regular{margin:0;font-size:1.5rem;color:var(--sl-section-ink,var(--sl-content-text));opacity:0.75}",
    "    .sl-bargain-amount{margin:0;font-family:var(--sl-font-heading);font-size:clamp(4rem,10vw,6.4rem);line-height:1;font-weight:800;color:var(--sl-section-ink,var(--sl-price-amount))}",
    # The prefix is small and quiet: it qualifies the number without competing with it.
    "    .sl-bargain-prefix{display:block;font-size:1.6rem;font-weight:600;letter-spacing:0.02em;opacity:0.8}",
    "    .sl-bargain-main{margin:0;font-family:var(--sl-font-heading);font-size:2.2rem;font-weight:700;color:var(--sl-section-ink,var(--sl-content-heading))}",
    "    .sl-bargain-sub{margin:0;font-size:1.5rem;color:var(--sl-section-ink,var(--sl-content-text));opacity:0.85}",
    # --- Coupon -------------------------------------------------------------------------------------
    # A paper coupon, in the order those actually read: the picture of what you get, then the business whose
    # offer it is, then the value in the largest type on the ticket. Dashed edge because that is the whole
    # visual idiom -- it says "cut here" to anyone who has ever held one.
    #
    # The whole ticket is the link, so it gets the pointer and the lift, and every child inherits its colour
    # rather than turning into blue underlined text.
    "    .sl-coupon{display:grid;grid-template-columns:minmax(10rem,34%) minmax(0,1fr);align-items:stretch;"
    # The ticket paints its OWN ground (white by default), so its ink must default to a dark one rather
    # than inheriting --sl-text. On a dark preset --sl-text is near-white, which put white text on a
    # white ticket and erased the value, the code and the headline -- everything except the accent-
    # coloured lines, which is why it looked half-rendered rather than broken (found 2026-09-22).
    "max-width:56rem;margin:0 auto;text-decoration:none;color:var(--sl-coupon-text,#16181d);"
    "background:var(--sl-coupon-bg,#fff);border:2px dashed color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 55%,transparent);"
    "border-radius:1.4rem;overflow:hidden;box-shadow:0 1.2rem 3.2rem rgba(0,0,0,0.13);"
    "transition:transform .16s ease,box-shadow .16s ease}",
    "    .sl-coupon,.sl-coupon *{text-decoration:none}",
    "    .sl-coupon-noimage{grid-template-columns:minmax(0,1fr)}",
    "    a.sl-coupon:hover{transform:translateY(-2px);box-shadow:0 1.8rem 4rem rgba(0,0,0,0.18)}",
    "    a.sl-coupon:focus-visible{outline:3px solid var(--sl-coupon-accent,#e0402c);outline-offset:3px}",
    # The picture panel. Perforated divider on its inner edge, so the two halves read as one torn ticket.
    "    .sl-coupon-media{position:relative;background:color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 12%,transparent);"
    "border-right:2px dashed color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 45%,transparent)}",
    "    .sl-coupon-media img{width:100%;height:100%;min-height:15rem;object-fit:cover;display:block}",
    "    .sl-coupon-media-logo{display:grid;place-items:center;padding:2.2rem}",
    "    .sl-coupon-media-logo img{width:auto;height:auto;max-width:8rem;max-height:8rem;min-height:0;object-fit:contain}",
    "    .sl-coupon-body{display:grid;gap:0.45rem;justify-items:start;text-align:left;padding:1.8rem 1.9rem;align-content:center}",
    # The business owns the ticket, so it is named first and quietly -- a coupon that names no business is a
    # voucher for nowhere, and it is the first thing a recipient checks.
    "    .sl-coupon-brand{margin:0;font-size:1.2rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;"
    "color:var(--sl-coupon-accent,#e0402c)}",
    "    .sl-coupon-headline{margin:0;font-family:var(--sl-font-heading);font-size:1.6rem;line-height:1.25;"
    "font-weight:700;opacity:0.85}",
    # The value is the largest thing on the ticket. It is what the recipient is deciding on.
    "    .sl-coupon-value{margin:0.2rem 0 0.4rem;font-family:var(--sl-font-heading);"
    "font-size:clamp(3.2rem,9vw,4.8rem);line-height:0.95;font-weight:900;letter-spacing:-0.03em}",
    "    .sl-coupon-code-row{margin:0;display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap}",
    "    .sl-coupon-code-label{font-size:1.1rem;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;opacity:0.5}",
    "    .sl-coupon-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1.6rem;font-weight:700;"
    "letter-spacing:0.12em;padding:0.35rem 0.85rem;border-radius:0.5rem;"
    "background:var(--sl-coupon-code-bg,rgba(0,0,0,0.07))}",
    "    .sl-coupon-expiry{margin:0;font-size:1.25rem;font-weight:600;color:var(--sl-coupon-accent,#e0402c)}",
    "    .sl-coupon-terms{margin:0;font-size:1.15rem;line-height:1.45;opacity:0.65}",
    "    .sl-coupon-cta{margin-top:0.6rem;font-size:1.4rem;font-weight:800;color:var(--sl-coupon-accent,#e0402c)}",
    # Expired: still shown, visibly spent. Desaturated rather than hidden, because an email outlives its
    # deadline and "nothing here" reads as a broken page.
    # Applied: green, because that is what "this worked" looks like everywhere else. Green is used ONLY
    # for this state -- the ticket's own accent stays the tenant's, so the confirmation reads as a system
    # response rather than as part of the artwork.
    "    .sl-coupon-applied{display:flex;align-items:center;gap:0.65rem;margin-top:0.7rem;"
    "padding:0.5rem 0.9rem;border-radius:0.6rem;background:#e7f7ed;color:#136c34;"
    "border:1px solid #b6e3c6}",
    # `hidden` is only display:none in the UA stylesheet, so the display:flex above OUTRANKS it and the
    # panel showed before anyone clicked (found 2026-09-22). Any element given a display must restate the
    # attribute, or the attribute silently stops working.
    "    .sl-coupon-applied[hidden]{display:none}",
    "    .sl-coupon-applied-mark{flex:0 0 auto}",
    "    .sl-coupon-applied-text{display:flex;flex-direction:column;font-size:1.3rem;font-weight:800;line-height:1.25}",
    "    .sl-coupon-applied-text small{font-size:1.1rem;font-weight:600;opacity:0.85}",
    # Once applied the ticket is a receipt, not an invitation: it stops inviting another click.
    "    .sl-coupon.is-applied{cursor:default}",
    "    .sl-coupon.is-applied .sl-coupon-cta{display:none}",
    # ---- Coupon styles (author, 2026-10-15) ---------------------------------------------------------
    # Five looks over ONE markup shape, so a style is a stylesheet question and the renderer stays a
    # renderer. Four follow the page preset through --sl-coupon-*; `dark` fixes all three on purpose --
    # it is a style, not a palette, and a dark ticket whose colours moved with the theme would stop being
    # the thing the tenant picked.
    #
    # MINIMALIST: a plain white ticket with a red accent, pinned rather than themed. It PINS the three
    # properties to the values that used to be hardcoded fallbacks -- now that the base follows the preset,
    # this style has to state them or it would quietly become a theme-following one. The dashed ticket
    # edging it uses is the base, so there is nothing else to restate.
    "    .sl-coupon[data-coupon-style='minimalist']{--sl-coupon-accent:#e0402c;--sl-coupon-bg:#fff;"
    "--sl-coupon-text:#16181d;--sl-coupon-cta-ink:#fff}",
    # MODERN is the default and paints a plain card: no dashed ticket edging, the eyebrow small in the
    # accent, and the redeem line a filled pill rather than a line of coloured text.
    "    .sl-coupon[data-coupon-style='modern']{border:1px solid color-mix(in srgb,var(--sl-coupon-text,#16181d) 12%,transparent);"
    "border-radius:1.8rem;box-shadow:0 1rem 2.4rem rgba(0,0,0,0.10)}",
    "    .sl-coupon[data-coupon-style='modern'] .sl-coupon-media{border-right:0;background:transparent}",
    "    .sl-coupon[data-coupon-style='modern'] .sl-coupon-brand{font-size:1.15rem;letter-spacing:0.16em}",
    "    .sl-coupon[data-coupon-style='modern'] .sl-coupon-cta{display:inline-flex;align-items:center;gap:0.6rem;"
    "margin-top:1rem;padding:0.95rem 1.8rem;border-radius:999px;background:var(--sl-coupon-accent,#e0402c);"
    "color:var(--sl-coupon-cta-ink,#fff);font-size:1.4rem}",
    # RIBBON keeps the torn-ticket feel and flies the headline as a flag. The picture moves to the RIGHT,
    # which is what makes the banner the first thing read.
    "    .sl-coupon[data-coupon-style='ribbon']{grid-template-columns:minmax(0,1fr) minmax(10rem,38%);"
    "border:2px solid color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 30%,transparent);border-radius:1.6rem;padding:0.9rem}",
    "    .sl-coupon[data-coupon-style='ribbon'] .sl-coupon-media{order:2;border-right:0;border-radius:1rem;overflow:hidden}",
    "    .sl-coupon[data-coupon-style='ribbon'] .sl-coupon-body{order:1;border:2px dashed color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 40%,transparent);"
    "border-radius:1rem;padding:1.6rem 1.7rem}",
    # The flag: accent ground, notched tail, and the brand line sitting inside it.
    "    .sl-coupon[data-coupon-style='ribbon'] .sl-coupon-brand{background:var(--sl-coupon-accent,#e0402c);"
    "color:var(--sl-coupon-cta-ink,#fff);padding:0.7rem 2.4rem 0.7rem 1.2rem;margin:0 0 0.6rem -2.9rem;"
    "clip-path:polygon(0 0,100% 0,calc(100% - 1.2rem) 50%,100% 100%,0 100%)}",
    # BOLD is RIBBON with a handmade finish (author, 2026-10-15): same torn ticket and same picture on the
    # right, plus perforated edges, a framed photograph and a drawn arrow at the redeem line.
    # The ticket INVERTS THE PAGE, and the perforation is painted rather than masked.
    #
    # Two earlier attempts failed for the same reason: nothing separated the ticket from the page. A mask
    # was invisible on a cream ticket against a cream page, and an outline could not rescue it -- a mask
    # clips the border too. Outlining the painted discs was worse: the ring is continuous, so the bite read
    # as a bubble stuck to the side rather than a hole (author, 2026-10-15: "that's awful").
    #
    # Contrast is the actual answer. The ticket takes the page's INK as its ground and the page's ground as
    # its ink -- dark on a light preset, light on a dark one -- so a notch in the page's own colour reads as
    # a hole with no outline at all. (background, text) is a pair the preset DESIGNED together, which is the
    # rule `.sl-tone-contrast` follows for exactly this inversion; pairing one pair's surface with another
    # pair's ink is what inverts when the preset does.
    "    .sl-coupon[data-coupon-style='bold']{grid-template-columns:minmax(0,1fr) minmax(10rem,40%);"
    "--sl-notch:1.15rem;--sl-coupon-bg:var(--sl-text);--sl-coupon-text:var(--sl-background);"
    "border:0;border-radius:1.2rem;padding:1.4rem 1.8rem;"
    "position:relative;overflow:visible;box-shadow:0 1.4rem 3.4rem rgba(0,0,0,0.16)}",
    # The bite itself: the page's own ground, no border. Clipped to the half over the ticket so it never
    # paints outside its footprint.
    "    .sl-coupon[data-coupon-style='bold']::before,.sl-coupon[data-coupon-style='bold']::after{"
    "content:'';position:absolute;top:50%;width:calc(var(--sl-notch) * 2);height:calc(var(--sl-notch) * 2);"
    "border-radius:50%;background:var(--sl-background,#fff);transform:translateY(-50%);z-index:1}",
    "    .sl-coupon[data-coupon-style='bold']::before{left:calc(var(--sl-notch) * -1);"
    "clip-path:inset(0 0 0 50%)}",
    "    .sl-coupon[data-coupon-style='bold']::after{right:calc(var(--sl-notch) * -1);"
    "clip-path:inset(0 50% 0 0)}",
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-body{order:1;padding:1.2rem 1.4rem}",
    # The photograph: a thick white mount, a shadow and a slight tilt, so it reads as a print dropped on
    # the ticket rather than a panel built into it.
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-media{order:2;border-right:0;background:transparent;"
    "display:grid;align-content:center;padding:1rem}",
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-media img{border-radius:0.2rem;transform:rotate(2.5deg);"
    "border:0.8rem solid #fff;border-bottom-width:2.6rem;box-shadow:0 0.8rem 2rem rgba(0,0,0,0.28);min-height:0}",
    # A highlighter swipe behind the eyebrow and a thick one under the value -- drawn with the accent, so
    # they follow the preset like the rest of the ticket.
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-brand{display:inline;color:var(--sl-coupon-text,#16181d);"
    "background:color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 55%,transparent);"
    "box-decoration-break:clone;-webkit-box-decoration-break:clone;padding:0.3rem 0.7rem;border-radius:0.2rem}",
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-value{display:inline-block;font-size:clamp(3.6rem,10vw,5.4rem);"
    "text-transform:uppercase;box-shadow:inset 0 -0.22em 0 color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 55%,transparent)}",
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-code{border:2px dashed color-mix(in srgb,var(--sl-coupon-text,#16181d) 40%,transparent);"
    "background:transparent;padding:0.6rem 1.1rem}",
    # The redeem line is the hand-written one in the reference. `--sl-font-accent` rather than a family
    # named here: a third webfont is a third download on a page tuned for LCP (domain/fonts.py), and the
    # accent role already exists for exactly this -- a tenant who wants Karla sets it once and every
    # accent-typed thing on the page follows.
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-cta{display:inline-flex;align-items:center;gap:0.8rem;"
    "margin-top:1rem;font-family:var(--sl-font-accent,var(--sl-font-heading));font-style:italic;"
    "font-size:1.6rem;line-height:1.2;color:var(--sl-coupon-text,#16181d)}",
    # The drawn arrow, as a mask so it takes the line's own colour instead of shipping a coloured asset.
    "    .sl-coupon[data-coupon-style='bold'] .sl-coupon-cta::before{content:'';flex:0 0 auto;"
    "width:2.6rem;height:2.6rem;background:currentColor;"
    "-webkit-mask:var(--sl-coupon-arrow) center/contain no-repeat;mask:var(--sl-coupon-arrow) center/contain no-repeat}",
    "    .sl-coupon[data-coupon-style='bold']{--sl-coupon-arrow:url(\"data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M3 4c7 0 12 5 13 13'/%3E%3Cpath d='M11 15l5 3 2-5'/%3E%3C/svg%3E\")}",
    # DARK is FIXED. Every other style tracks the preset; this one is chosen for its own look, so its three
    # custom properties are set here rather than inherited.
    "    .sl-coupon[data-coupon-style='dark']{--sl-coupon-bg:#111827;--sl-coupon-text:#f8fafc;"
    "--sl-coupon-accent:#f5c518;--sl-coupon-cta-ink:#111827;--sl-coupon-code-bg:rgba(255,255,255,0.08);"
    "border:2px dashed #f5c518;border-radius:1.4rem}",
    "    .sl-coupon[data-coupon-style='dark'] .sl-coupon-media{border-right:0;padding:1.4rem;background:transparent}",
    "    .sl-coupon[data-coupon-style='dark'] .sl-coupon-media img{border-radius:1rem}",
    "    .sl-coupon[data-coupon-style='dark'] .sl-coupon-code{border:2px dashed #f5c518}",
    "    .sl-coupon[data-coupon-style='dark'] .sl-coupon-cta{display:inline-flex;align-items:center;gap:0.6rem;"
    "margin-top:1rem;padding:0.95rem 1.8rem;border-radius:999px;background:#f5c518;color:#111827;font-size:1.4rem}",
    "    .sl-coupon-expired{filter:grayscale(1);opacity:0.7;box-shadow:none}",
    "    @media (max-width:34rem){.sl-coupon{grid-template-columns:minmax(0,1fr)}"
    ".sl-coupon-media{border-right:0;border-bottom:2px dashed color-mix(in srgb,var(--sl-coupon-accent,#e0402c) 45%,transparent)}"
    ".sl-coupon-media img{min-height:11rem}}",
    "    @media (prefers-reduced-motion:reduce){a.sl-coupon{transition:none}a.sl-coupon:hover{transform:none}}",
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
    "    @media (prefers-reduced-motion: reduce){.sl-hero-brand-dot.is-pulsing{animation:none}.sl-brand-label.is-pulsing::before{animation:none}.sl-marquee-track{animation:none;flex-wrap:wrap}.sl-faq summary::after{transition:none}}",
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
    #
    # `> img` -- the card's OWN picture, not every picture inside it. The editorial entry nests a page
    # ribbon, and a descendant selector here reached into it: the listicle's `width:12rem` outranked the
    # ribbon's `width:100%`, so the panel image rendered at 12rem inside a 22rem column. It looked like a
    # sizing choice rather than a leak, and the author spotted it by holding a hand-built ribbon beside it.
    # Every card puts its own image at the top level (catalog cards and link cards both), so the child
    # combinator costs nothing and stops this class of leak for whatever gets nested next.
    "    .sl-catalog-card > img{width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;border-radius:0.8rem;background:#fff;display:block}",
    # The words, as one block. `flex:1` lets the price keep its `margin-top:auto` bottom alignment in a
    # grid card; `min-width:0` is what stops a long title pushing out of its column in a listicle row.
    "    .sl-catalog-body{display:flex;flex-direction:column;gap:0.6rem;flex:1;min-width:0}",
    # MASONRY — CSS multi-column, ported from the old dot-net front page. No JS, no library.
    # The aspect-ratio above is explicitly dropped: variable tile heights ARE the layout, and forcing
    # every image square would produce a uniform grid with extra steps.
    "    .sl-catalog-cards.sl-catalog-masonry{display:block;column-count:5;column-gap:1.4rem}",
    "    .sl-catalog-masonry .sl-catalog-card{break-inside:avoid;margin:0 0 1.4rem;width:100%}",
    "    .sl-catalog-masonry .sl-catalog-card > img{aspect-ratio:auto}",
    "    @media (max-width:1180px){.sl-catalog-cards.sl-catalog-masonry{column-count:4}}",
    "    @media (max-width:900px){.sl-catalog-cards.sl-catalog-masonry{column-count:3}}",
    "    @media (max-width:650px){.sl-catalog-cards.sl-catalog-masonry{column-count:2;column-gap:1rem}}",
    "    @media (max-width:420px){.sl-catalog-cards.sl-catalog-masonry{column-count:1}}",
    # LISTICLE — one ordered row per member, image beside the text. A CSS counter draws the number so it
    # carries no content of its own; the <ol> already says the position to anything that reads markup.
    "    .sl-catalog-list{list-style:none;counter-reset:sl-catalog;display:flex;flex-direction:column;gap:1.2rem;margin:0;padding:0}",
    "    .sl-catalog-row{counter-increment:sl-catalog;display:block}",
    "    .sl-catalog-row .sl-catalog-card{display:grid;grid-template-columns:auto 12rem minmax(0,1fr);align-items:start;gap:1.2rem}",
    "    .sl-catalog-row .sl-catalog-card::before{content:counter(sl-catalog);font-family:var(--sl-font-accent);font-weight:900;font-size:2.2rem;line-height:1;color:var(--sl-price-amount);min-width:2.2rem;text-align:right}",
    "    .sl-catalog-row .sl-catalog-card > img{aspect-ratio:1/1;width:12rem}",
    "    .sl-catalog-row .sl-catalog-price{margin:0.4rem 0 0}",
    "    .sl-catalog-pitch{margin:0.3rem 0 0;font-size:1.5rem;line-height:1.5;color:var(--sl-content-text)}",
    # EDITORIAL — the same ordered list with room to argue. Shares the row grid; only the proportions and
    # the chrome change, so the two ordered layouts cannot drift into rendering different things.
    # The proportions are the PAGE RIBBON's, not new numbers. The author built his mock-up out of ribbons,
    # and the first cut of this guessed smaller values -- an 18rem image and a 2.2rem headline -- which
    # read as "a row with a button" rather than an entry that argues. Borrowing the element he actually
    # pointed at is both closer to what he drew and one less set of magic numbers to keep in step.
    #   ribbon: minmax(0,22rem) column | gap 2rem | padding 3.2rem | radius 1.4rem | centred
    # The entry is PROSE then a PANEL: the headline and paragraph sit on the page, in the tenant's words,
    # and the tinted panel below shows the product and offers the way through. So the card itself carries
    # no chrome at all -- a box around the prose would make it a tile again, which is what the first two
    # cuts got wrong.
    "    .sl-layout-editorial .sl-catalog-list{gap:3.2rem}",
    "    .sl-layout-editorial .sl-catalog-row .sl-catalog-card{display:block;background:transparent;border:0;padding:0;text-align:center}",
    # THE NUMBER MOVES ONTO THE HEADLINE. A bare numeral on its own line above the title read as a stray
    # figure rather than as a rank -- the author asked for the circled badge the numbered_list element
    # already draws, beside the words it numbers. Same recipe as `.sl-numbered-item::before`, inline so it
    # sits ON the heading line and wraps with it; the counter is incremented by the row, and a counter is
    # visible to a descendant, so no second counter is needed.
    "    .sl-layout-editorial .sl-catalog-row .sl-catalog-card::before{content:none}",
    "    .sl-layout-editorial .sl-catalog-title::before{content:counter(sl-catalog);display:inline-grid;place-items:center;width:3.6rem;height:3.6rem;margin-right:1rem;vertical-align:middle;border-radius:50%;background:var(--sl-badge-bg,var(--sl-accent));color:var(--sl-badge-ink,#fff);font-family:var(--sl-font-heading);font-size:1.8rem;font-weight:700;line-height:1}",
    # A RULE BETWEEN ENTRIES, same border token the content block's "Add a dividing line" uses. Intrinsic
    # to the layout rather than a tick: the tenant chose editorial, and an entry that is prose plus a panel
    # needs a boundary or the next headline reads as part of the panel above it. Symmetric space around the
    # line (the list gap above, the padding below) so it separates rather than attaching to one side.
    "    .sl-layout-editorial .sl-catalog-row + .sl-catalog-row{border-top:1px solid var(--sl-content-border);padding-top:3.2rem}",
    "    .sl-layout-editorial .sl-catalog-body{gap:0.8rem}",
    "    .sl-layout-editorial .sl-catalog-title{font-size:clamp(2rem,4vw,2.8rem);line-height:1.2}",
    "    .sl-layout-editorial .sl-catalog-pitch{font-size:1.6rem;line-height:1.55;opacity:0.85}",
    # THE PANEL IS A PAGE RIBBON. There is no `.sl-catalog-panel` any more, and that is the point: the
    # earlier one re-declared the ribbon's grid, gap, padding, radius and background by hand, which is
    # how it came to omit `color` -- so every word inside inherited the card's <a> and published in the
    # browser's visited-link purple. `.sl-page-ribbon` + `.sl-ribbon-*` now supply the colour, the type,
    # the button ink and the 700px collapse, and there is nothing left here to drift out of step.
    #
    # Three rules remain, and each is a difference the ribbon cannot know about from inside a ranked list:
    # the panel is a sibling of prose rather than a section of its own, its images must match each other
    # down the list, and the whole row is one link so the hover lift belongs to the panel.
    "    .sl-catalog-row .sl-page-ribbon{margin-top:1.6rem;text-align:left;transition:transform .15s ease,box-shadow .15s ease}",
    # `:not(.sl-cropped)` is REQUIRED, not defensive: a cropped box positions its image absolutely and
    # sizes it from custom properties, so any outer rule setting width/height/object-fit corrupts that
    # geometry (tests/test_image_crop.py::CssIsolationTests, which caught this one). Entries carry no crop
    # today -- the guard is what keeps that still true the day one does.
    "    .sl-catalog-row .sl-ribbon-media:not(.sl-cropped) img{aspect-ratio:1/1;object-fit:cover;border-radius:1rem;background:#fff}",
    "    .sl-layout-editorial a.sl-catalog-card:hover{transform:none;box-shadow:none}",
    "    .sl-layout-editorial a.sl-catalog-card:hover .sl-page-ribbon{transform:translateY(-2px);box-shadow:0 10px 28px rgba(0,0,0,.12)}",
    # A phone gets the number above a full-width image, not a 12rem column squeezed beside it.
    "    @media (max-width:650px){.sl-catalog-row .sl-catalog-card{grid-template-columns:auto minmax(0,1fr)}",
    "      .sl-catalog-row .sl-catalog-card > img{width:100%}",
    "      .sl-catalog-row .sl-catalog-body{grid-column:1/-1}}",
    # The lift on hover is decoration; anyone who asked for less motion does not get it.
    "    @media (prefers-reduced-motion:reduce){a.sl-catalog-card{transition:none}a.sl-catalog-card:hover{transform:none}",
    "      .sl-catalog-row .sl-page-ribbon{transition:none}.sl-layout-editorial a.sl-catalog-card:hover .sl-page-ribbon{transform:none}}",
    "    .sl-catalog-title{font-family:var(--sl-font-heading);font-weight:800;font-size:1.6rem;line-height:1.3;color:var(--sl-price-title);margin:0}",
    "    .sl-catalog-price{font-family:var(--sl-font-accent);font-weight:900;font-size:1.8rem;color:var(--sl-price-amount);margin:auto 0 0}",
    "    .sl-seller-profile{display:flex;flex-direction:column;gap:1rem}",
    "    .sl-seller-desc{font-size:1.5rem;line-height:1.6;color:var(--sl-content-text)}",
    "    .sl-seller-contact{font-size:1.4rem;color:var(--sl-muted);display:flex;flex-wrap:wrap;gap:0.6rem}",
    "    .sl-seller-contact a{color:var(--sl-legal-link);text-decoration:none}",
    "    .sl-seller-social,.sl-seller-catalog{list-style:none;display:flex;flex-wrap:wrap;gap:1rem;padding:0;margin:0}",
    # The standalone row leads a link-in-bio page rather than sitting inside a profile block, so it centres
    # and gets tap-sized targets: effectively all of this traffic is a thumb coming from an app's bio field.
    "    .sl-social-row{list-style:none;display:flex;flex-wrap:wrap;justify-content:center;gap:.75rem;padding:0;margin:0}",
    "    .sl-social-row a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;border:1px solid var(--sl-legal-link);border-radius:999px;color:var(--sl-legal-link);text-decoration:none}",
    # Every tile is the same 44px circle now -- there is no worded variant, because one spelled-out host used
    # to widen the row and break its rhythm. 44px also clears the WCAG 2.5.8 target minimum, which matters
    # here more than anywhere: this page is tapped by a thumb, from a bio link, which is all of its traffic.
    "    .sl-social-row a.sl-social-glyph{width:44px;height:44px;padding:0}",
    "    .sl-social-row a.sl-social-glyph svg{width:22px;height:22px;display:block}",
    # An unlinked profile on a shared platform host: same tile, visibly inert. Not hidden -- the tenant put it
    # there, and a card that silently vanishes tells them nothing about why.
    "    .sl-social-row .is-unlinked{display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;border:1px dashed var(--sl-legal-link);border-radius:999px;color:var(--sl-muted);opacity:.65}",
    "    .sl-social-row span.sl-social-glyph{width:44px;height:44px;padding:0}",
    "    .sl-social-row span.sl-social-glyph svg{width:22px;height:22px;display:block}",
    "    .sl-social-row a:hover{text-decoration:underline}",
    # The tip jar: one button, centred, reusing the CTA gradient so it reads as the page's primary action --
    # which on a hub with no checkout it is.
    # A PANEL, not loose text on the page ground. The section used to be a heading, a button and a line of
    # prose floating between two bordered neighbours, so the one thing on the page asking for money read as
    # the least deliberate thing on it. The tint is mixed from the theme accent rather than picked, so it
    # follows every preset instead of fighting the ones it was not designed against.
    "    .sl-tip-jar{display:grid;gap:1.2rem;justify-items:center;text-align:center;padding:2.8rem 2.4rem;border-radius:1.6rem;background:color-mix(in srgb,var(--sl-accent) 7%,var(--sl-card));border:1px solid color-mix(in srgb,var(--sl-accent) 22%,transparent)}",
    # Older Safari and Firefox have no color-mix: they get the plain card, which is still a panel.
    "    @supports not (background:color-mix(in srgb,red 50%,blue)){.sl-tip-jar{background:var(--sl-card);border-color:var(--sl-content-border)}}",
    "    .sl-tip-jar .sl-section-heading{margin:0}",
    "    .sl-tip-jar-btn{display:inline-flex;align-items:center;justify-content:center;gap:0.9rem;min-height:4.4rem;padding:0 2.8rem;border-radius:999px;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);font-family:var(--sl-font-accent);font-size:1.6rem;font-weight:800;text-decoration:none}",
    "    .sl-tip-jar-btn.is-unlinked{background:none;border:1px dashed var(--sl-legal-link);color:var(--sl-muted);opacity:.65}",
    # The icon inherits the label's colour and scales with it, so it stays right on the unlinked variant too.
    "    .sl-tip-jar-icon{flex:none;width:2.1rem;height:2.1rem}",
    "    .sl-tip-jar-note{margin:0;font-size:1.3rem;color:var(--sl-legal-link)}",
    "    .sl-social-row a.sl-social-glyph:hover{background:var(--sl-legal-link);color:var(--sl-page-bg)}",
    # The note inherits the card's ink at 80% on a dark card, which left it very nearly invisible (reported
    # 2026-09-13 -- "Hiking Gear" as dark blue on dark navy). --sl-legal-link is the one link colour the theme
    # guarantees is legible against the page ground, because the footer's links depend on it.
    "    .sl-link-card-note{margin:.25rem 0 0;font-size:.95rem;color:var(--sl-legal-link)}",
    # Clamp by LINES, not by character count. The card is constrained in pixels, and the tenant picks the
    # font -- Comic Relief at 40 characters is a different width from Lato at 40, so a maxlength would be a
    # proxy for the wrong thing. Clamping is font-agnostic by construction: a heavier face simply fits
    # fewer words in the same two lines, and every card in the row stays the same height.
    #
    # NOT `white-space:nowrap` + `text-overflow:ellipsis`, which is one line always: a phone card is about
    # 146px wide, so a single line holds ~16 characters and "My Amazon storefront" truncates to "My Amazon
    # st...". Mobile is where effectively all of this traffic lands.
    #
    # Visual only -- the full text stays in the DOM and in the title attribute, so nothing is lost to a
    # screen reader or to someone hovering. Same technique as the dashboard's ListCard.
    "    .sl-link-cards .sl-catalog-title{display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}",
    "    .sl-link-cards .sl-link-card-note{display:-webkit-box;-webkit-line-clamp:3;line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}",
    # Link cards get a FIXED three-column grid rather than catalog_grid's auto-fill. auto-fill packs from
    # the left, so a creator with one link had it stranded against the left edge with two columns of empty
    # space beside it. The rules below are about the LAST row, which is the only one that can be partial:
    #   a row of one  -> centre column, so it reads as deliberate rather than left over
    #   a row of two  -> the outer columns, spread to the edges
    # Written with nth-child(3n+1) so they apply to any trailing remainder, not just to pages with one or
    # two cards total: four cards strand the fourth exactly the way one card stranded the first.
    "    .sl-link-cards .sl-catalog-cards{grid-template-columns:repeat(3,minmax(0,1fr))}",
    "    .sl-link-cards .sl-catalog-cards>:nth-child(3n+1):last-child{grid-column:2}",
    "    .sl-link-cards .sl-catalog-cards>:nth-child(3n+1):nth-last-child(2){grid-column:1}",
    "    .sl-link-cards .sl-catalog-cards>:nth-child(3n+1):nth-last-child(2)+*{grid-column:3}",
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
    "    .sl-minicart{position:fixed;left:0;right:0;bottom:0;z-index:20;display:none;flex-direction:column;gap:0.6rem;padding:1rem 1.6rem 1.2rem;background:var(--sl-card);border-top:1px solid var(--sl-border);box-shadow:0 -2px 16px rgba(0,0,0,.12);color:var(--sl-card-text,var(--sl-text))}",
    # In-page notice modal (the server-rendered page is not a Vue app, so it can't mount ConfirmDialog.vue —
    # this mirrors that component's look with theme tokens). Used to surface blocked-action reasons, e.g. the
    # publish guard, instead of the browser's window.alert.
    "    .sl-notice-backdrop{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;padding:1.6rem;background:rgba(0,0,0,.55)}",
    "    .sl-notice-backdrop.is-visible{display:flex}",
    "    .sl-notice-card{width:min(40rem,100%);background:var(--sl-card);border:1px solid var(--sl-border);border-radius:var(--sl-radius);padding:2.4rem 2rem 2rem;text-align:center;display:grid;gap:1.4rem;justify-items:center;box-shadow:0 16px 48px rgba(0,0,0,.35);color:var(--sl-card-text,var(--sl-text))}",
    "    .sl-notice-icon{width:4.4rem;height:4.4rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2.2rem;font-weight:800;background:color-mix(in srgb,var(--sl-accent) 16%,transparent);color:var(--sl-accent)}",
    "    .sl-notice-msg{color:var(--sl-text);font-size:1.5rem;line-height:1.5;margin:0}",
    "    .sl-notice-ok{width:auto;min-width:12rem;background:linear-gradient(135deg,var(--sl-cta-from),var(--sl-cta-to));color:var(--sl-cta-text);border:0;border-radius:0.9rem;padding:1rem 2.4rem;font-family:var(--sl-font-accent);font-size:1.5rem;font-weight:800;cursor:pointer}",
    # The same card with two actions, for the age gate (plans/CREATOR_LINK_POLICY.md §5d). Declining must be
    # as easy to reach as continuing -- a dialog where only the affirmative answer is a real button is a dark
    # pattern, and this one exists to let someone say no.
    "    .sl-notice-actions{display:flex;flex-wrap:wrap;gap:1rem;justify-content:center}",
    "    .sl-notice-cancel{width:auto;min-width:10rem;background:transparent;color:var(--sl-text);border:1px solid var(--sl-border);border-radius:0.9rem;padding:1rem 2rem;font-family:var(--sl-font-accent);font-size:1.5rem;font-weight:700;cursor:pointer}",
    # "18+", not "18": the threshold is the point, and a bare number reads as an age rather than a minimum.
    # Sized down from the notice icon's 2.2rem because three glyphs have to sit inside the same 4.4rem circle.
    "    .sl-age-gate .sl-notice-icon{font-size:1.5rem;font-weight:900;letter-spacing:-0.03em}",
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
    "    @media (max-width: 700px){.sl-price-option{grid-template-columns:8.8rem minmax(0,1fr) 2.4rem;gap:1rem;padding:1.2rem}.sl-price-option img{width:8.8rem}.sl-content-block{grid-template-columns:1fr}.sl-headline h1{font-size:3rem}.sl-testimonial{grid-template-columns:1fr;padding:1.8rem 1.6rem 1.8rem 3.8rem}.sl-testimonial img{width:5.6rem;height:5.6rem;order:-1}.sl-testimonial blockquote{font-size:1.6rem}.sl-quote-fancy .sl-quote-photo{align-self:auto;min-height:0;height:20rem}.sl-quote-fancy .sl-quote-photo img{position:static;transform:none;height:100%}.sl-page-ribbon{padding:2rem;gap:1.4rem}.sl-page-ribbon.is-image_left,.sl-page-ribbon.is-compact{grid-template-columns:minmax(0,1fr)}.sl-page-ribbon .sl-ribbon-media:not(.sl-cropped) img{max-height:22rem;object-fit:cover}.sl-ribbon-cta{justify-self:stretch;text-align:center;justify-content:center}.sl-link-cards .sl-catalog-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.sl-link-cards .sl-catalog-cards>:nth-child(3n+1):last-child,.sl-link-cards .sl-catalog-cards>:nth-child(3n+1):nth-last-child(2),.sl-link-cards .sl-catalog-cards>:nth-child(3n+1):nth-last-child(2)+*{grid-column:auto}.sl-link-cards .sl-catalog-cards>:nth-child(2n+1):last-child{grid-column:1/-1}}",
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
    overrides = theme.get("tokens") or {}
    tokens.update(overrides)
    # A gradient painted through the glyphs HIDES the colour underneath it, so a preset gradient would
    # make the matching colour control inert -- the tenant picks a headline colour and the page ignores
    # it. An explicit override therefore drops the preset's gradient and the colour wins. Only an
    # override does this: left alone, the preset keeps its gradient.
    for colour_token, gradient_token in (("headline", "headline_gradient"), ("highlight_text", "highlight_gradient")):
        if overrides.get(colour_token) and not overrides.get(gradient_token):
            tokens[gradient_token] = "none"
            tokens.pop(f"{colour_token.removesuffix('_text')}_ink", None)
    tokens.setdefault("countdown_bg", tokens["cta_from"] if preset_name != "techno-green" else "#dc2626")
    tokens.setdefault("countdown_end_bg", tokens["cta_to"] if preset_name != "techno-green" else "#f97316")
    tokens.setdefault("countdown_text", "#ffffff")
    tokens.setdefault("brand_label_text", tokens["muted"])
    tokens.setdefault("brand_dot", tokens["brand"])
    tokens.setdefault("highlight_text", "#f97316")
    # The gradient a highlight is painted with, and the ink that lets it show through. Defaults keep
    # every preset on the solid colour above.
    tokens.setdefault("highlight_gradient", "none")
    tokens.setdefault("highlight_ink", tokens["highlight_text"])
    # The same pair for the headline, so a preset can paint the H1 with a gradient (royal-velvet).
    tokens.setdefault("headline_gradient", "none")
    tokens.setdefault("headline_ink", tokens["headline"])
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
    # Text that sits ON the accent -- not the same question as text on the CTA gradient, which is what
    # `cta_text` answers. Twelve of sixteen presets failed WCAG AA on the numbered badge while it
    # borrowed `cta_text`; `tiktok-dark` was 1.41:1, white on #00f2ea.
    #
    # Reuses `section_theme.readable_ink`, which already solved exactly this for section overrides and
    # carries the measurement behind its two inks. Writing a second one here (as the first version of
    # this fix did) is how a codebase ends up with two "which ink is readable" answers that drift.
    # It returns None for a colour it cannot parse; LIGHT_INK is what these rules used before, so an
    # unknown changes nothing rather than guessing.
    tokens.setdefault("accent_text", section_readable_ink(tokens["accent"]) or SECTION_LIGHT_INK)
    # The ground under filled accent shapes, and the ink measured against THAT ground rather than against
    # the accent. A preset that wants white numerals darkens the ground; the measurement still decides the
    # ink, so the badge cannot end up unreadable whatever a preset chooses.
    # The coupon ticket, which paints its own ground. These were never set, so the renderer's hardcoded
    # fallbacks (#e0402c on white) were the whole design and a ticket ignored the page preset — reported
    # 2026-10-15 as the coupon not following the theme. The `dark` style overrides all three back to fixed
    # values, deliberately: it is a style, not a palette.
    tokens.setdefault("coupon_accent", tokens["accent"])
    tokens.setdefault("coupon_bg", tokens.get("card") or "#ffffff")
    tokens.setdefault("coupon_text", section_readable_ink(tokens.get("card") or "#ffffff") or "#16181d")
    tokens.setdefault("badge_bg", tokens["accent"])
    tokens.setdefault("badge_ink", section_readable_ink(tokens["badge_bg"]) or SECTION_LIGHT_INK)
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
    # INK FOR TEXT ON A CARD, which the token set used to assume matched ink on the page. It does not,
    # once a theme wants a WHITE card on a DARK page (`royal-velvet`, 2026-10-12): thirteen elements are
    # painted with `--sl-card` and ten carried no ink of their own, so they inherited the page's light
    # `--sl-text` and would have rendered invisible on it.
    #
    # Defaulting to the page values means NO existing preset moves. This only gives a theme the OPTION of
    # saying its two surfaces differ.
    tokens.setdefault("card_text", tokens["text"])
    tokens.setdefault("card_muted", tokens["muted"])
    tokens.setdefault("card_heading", tokens["content_heading"])
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


FONT_SERVICE_ORIGIN = "https://fonts.juniorbay.com"
# Pre-generated per-family stylesheets, on the SAME origin as the font files they reference. The service at
# FONT_SERVICE_ORIGIN is an edge-optimized API Gateway domain with no stage caching, so asking it for CSS
# meant a Lambda on every page's critical path -- `x-cache: Miss` on every request, ~110ms in front of first
# paint. These are static, edge-cached (~45ms, `Hit`), and regenerated by
# fonts-api/tools/build_family_css.py whenever the catalogue changes.
#
# One file per FAMILY rather than per pairing: a page picks any two or three of 31 families, so
# combinations would be 465+ files. Per-family is 31, covers every combination, and caches better because a
# family's CSS is shared by every page using it.
FONT_CSS_BASE = "https://juniorbay.com/fonts/css"
FONT_CSS_ORIGIN = "https://juniorbay.com"
# Ask the font service to embed the font bytes in the stylesheet instead of pointing at them on a
# second host. Kept as a flag so the referencing form can be restored in one edit once the fonts are
# subset and the cross-origin fetch is understood.
# TESTING 2026-09-09: flipped OFF to find out whether the CORS fix (preflight-capable response-headers
# policy + bucket CORS + Origin forwarded to S3) actually resolved the cross-origin font block. Referencing
# is the pattern that used to fail. If it now works, embedding stops being necessary -- and referenced fonts
# are strictly better now that every family is subset: smaller HTML, and one download shared across pages
# instead of the same bytes inlined into each.
FONT_EMBED = False


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


def font_vars(page: dict[str, Any], preferences: dict[str, Any] | None = None) -> str:
    """The font tokens, with the resolved family in front of a fallback stack.

    Loading the stylesheet is only half the job: without the family reaching these variables the webfont
    downloads and nothing on the page ever asks for it. The fallback stays behind every family so a font
    that fails to arrive degrades to something readable rather than to the browser's default serif.

    `accent` follows the heading unless set, and `mono` is always the system stack -- neither justifies a
    third download on a page tuned for LCP.
    """
    resolved = resolve_families(page, render_preferences(preferences))
    heading = _family_with_fallback(page, "heading", resolved["heading"])
    # accent follows the heading unless the tenant named one -- no preset proposes a third family, but
    # taking the choice away is not the same as declining to make it for them.
    accent = _family_with_fallback(page, "accent", resolved["accent"]) if "accent" in resolved else heading
    return (
        f"--sl-font-body:{_family_with_fallback(page, 'body', resolved['body'])};"
        f"--sl-font-heading:{heading};"
        f"--sl-font-accent:{accent};"
        f"--sl-font-mono:{SYSTEM_MONO_FONT_STACK}"
    )


def _family_with_fallback(page: dict[str, Any], role: str, family: str) -> str:
    """`'Family',<fallback stack>`, or the bare stack when the tenant chose system fonts."""
    fonts = ((page.get("theme") or {}).get("fonts") or {})
    entry = fonts.get(role) if isinstance(fonts.get(role), dict) else {}
    fallback_name = str(entry.get("fallback") or "system")
    fallback = FONT_FALLBACK_STACKS.get(fallback_name, SYSTEM_FONT_STACK)
    if is_system(family):
        # An explicit "system" is a decision to load nothing; adding a family here would undo it.
        return SYSTEM_MONO_FONT_STACK if fallback_name == "monospace" else fallback
    quoted = f"'{family}'" if any(char.isspace() for char in family) else family
    return f"{quoted},{fallback}"


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


def render_inline_marks(text: str) -> str:
    """`**emphasis**` and `^^highlight^^`, escaping everything else.

    Shared by headings and body copy so the two cannot drift apart -- a tenant who learns the markers in a
    headline should not find them printing literally in a bio. `.` does not match a newline, so a marker is
    never matched across a line break.
    """
    tokens = re.split(r"(\*\*.*?\*\*|\^\^.*?\^\^)", text)
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


def render_headline_markup(text: Any) -> str:
    return render_inline_marks(format_headline(str(text or "")))


def render_body_markup(text: Any, css_class: str = "", indent: str = "") -> str:
    """Body copy as real paragraphs.

    A blank line starts a new `<p>`; a single newline is a `<br>`. Both were already being typed into the
    textareas and thrown away here -- every body field rendered as `<p>{escape(text)}</p>`, one element, and
    HTML collapses the newlines inside it to spaces. A tenant's four-paragraph author bio came out as one
    unreadable run-on block.

    A blank line is the mechanism rather than a marker like `##` because the tenants' stored text ALREADY
    carries it (measured 2026-10-13: the one dev page with breaks had 3 blank lines and 0 stray newlines),
    so no one has to re-type copy that is already correct. It is also what every writer presses by reflex.

    The single newline is a `<br>` rather than a space: in a plain textarea, what you typed is what you
    should get, and collapsing it is how the run-on above happened in the first place.

    No title-casing -- that belongs to headings, and sentence case is what prose wants.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return ""
    # Every paragraph is marked so ONE rule can space them. The body classes all set `margin:0`, so without
    # it the paragraphs would stack flush against each other and read as a run-on again.
    classes = f"{css_class} sl-para" if css_class else "sl-para"
    out: list[str] = []
    for paragraph in re.split(r"\n[ \t]*\n+", raw):
        if not paragraph.strip():
            continue
        lines = [render_inline_marks(line) for line in paragraph.strip("\n").split("\n")]
        out.append(f"{indent}<p class=\"{escape(classes)}\">{'<br>'.join(lines)}</p>")
    return "\n".join(out)


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


def _grid_item_count(page: dict[str, Any]) -> int:
    """How many cards the catalog grid will actually show. Read off the RESOLVED section, which the
    publisher fills from the Site route map before rendering (resolve_category_grids), so this counts the
    products a visitor sees rather than whatever the Collection claims to contain."""
    total = 0
    for section in page.get("sections") or []:
        if isinstance(section, dict) and section.get("type") == "catalog_grid":
            total += len([item for item in (section.get("items") or []) if item])
    return total


def _as_sentence(text: str) -> str:
    """End a description fragment with one full stop, and only one.

    The segments here were built as f-strings with a trailing "." and the tagline was `.rstrip(".")`ed to
    stop a double stop. That handles a tagline ending in a period and nothing else, which was enough while
    these were storefront taglines. A ROUNDUP's subheadline is marketing copy -- "These make great gifts!"
    -- and it came out as "great gifts!." A question mark does the same. Strip whatever terminal
    punctuation is already there, then add the one stop back.
    """
    stripped = str(text or "").strip().rstrip(".!?").rstrip()
    if not stripped:
        return ""
    # The ORIGINAL mark is kept when it carries meaning. "!" and "?" are the author's tone and a full stop
    # would flatten them; a bare "." was only ever punctuation we were about to re-add anyway.
    #
    # `mark and mark in "!?"`, not `mark in "!?"`. An empty string is a substring of every string, so the
    # bare test is TRUE for a fragment that ended in no punctuation at all -- which returned it unchanged
    # and dropped the full stop this function exists to add.
    mark = str(text or "").strip()[len(stripped):].strip()[:1]
    return f"{stripped}{mark if mark and mark in '!?' else '.'}"


def offerless_description(page: dict[str, Any], offer: dict[str, Any] | None = None,
                          products_by_id: dict[str, dict[str, Any]] | None = None) -> str:
    """The meta description for a page with NO offer — a storefront, a category page, a store profile.

    These used to fall through the whole offer-shaped derivation below and come out as the bare rotating
    CTA, so every offer-less page on a Site published the identical `Get yours today!` — a duplicate
    description footprint across a Site, and plainly wrong on an "about" page (SEO-04,
    plans/OFFERLESS_PAGES_IN_BUILDER.md P4).

    WHICH SOURCE LEADS DEPENDS ON THE SHAPE, and that is the whole difficulty. An about page's subject IS
    the business, so the business description the tenant wrote for the Site is the right first choice there.
    A catalog page's subject is its catalogue, so it leads with what THIS page is and what is on it. Taking
    the business description first for both — the obvious implementation, and the first one written here —
    gave a Site's storefront and its about page the same sentence word for word, which is the duplicate
    footprint this function exists to remove, just with better prose.

    No CTA is ever appended: "Order now" on a page with no checkout is a promise the page cannot keep.
    """
    # EITHER HERO. `brand_hero` is the storefront/category/profile one; a ROUNDUP is routed here too --
    # `is_offerless_page` is true for anything carrying a `catalog_grid`, and every Roundup has one -- but
    # it composes the ordinary `hero`. Looking only for `brand_hero` left both values empty on a Roundup,
    # so the description collapsed to the item count alone and every Roundup published "Browse 3
    # products." while its own h1 named the page.
    hero = next((s for s in (page.get("sections") or [])
                 if isinstance(s, dict) and s.get("type") in ("brand_hero", "hero")), {})
    if hero.get("type") == "hero":
        # THE RESOLVER THE h1 ITSELF USES, not a second reading of the same fields. `hero_copy` is
        # "the page's own words, else the offer's, else the product's", and reading only the SECTION --
        # which is what the first cut of this did -- missed every page whose headline was never typed
        # into the hero: the section is empty there and the h1 comes from `offer.presentation`. That is
        # the common case for a Roundup, so the fix looked right on a page built one way and changed
        # nothing on a real one. Sharing the resolver is what makes the two incapable of disagreeing.
        headline, tagline = hero_copy(hero, offer or {}, products_by_id or {})
        headline = headline_plain_text(headline).strip()
        tagline = tagline.strip()
        # `{count}`/`{year}` are resolved at publish by `expand_roundup_titles`, which rewrites the hero
        # SECTION in place -- so a headline reached through the offer fallback above never passed through
        # it and would print the raw token. Idempotent: an already-expanded string has no tokens left.
        count = _grid_item_count(page)
        headline = expand_title_tokens(headline, count=count or None, year=datetime.now(timezone.utc).year)
    else:
        headline = headline_plain_text(str(hero.get("headline") or "")).strip()
        tagline = str(hero.get("tagline") or "").strip()
    org_name = str(_RENDER_ORG.get("name") or "").strip()
    org_description = re.sub(r"[.\s]+$", "", str(_RENDER_ORG.get("description") or "").strip())
    is_profile = offerless_composition(page) == "store_profile"

    # The about page: the tenant's own words about the business, and nothing bolted on in front of them.
    if is_profile and len(org_description) >= _DESC_MIN:
        return trim_meta(org_description, _DESC_MAX)

    segments: list[str] = []
    if headline and tagline:
        segments.append(_as_sentence(f"{headline} — {tagline}"))
    elif headline:
        # Name the store alongside the page's own subject, so a category page reads "Widgets from Probe
        # Store" rather than the bare word a dozen other shops also use as a heading.
        segments.append(_as_sentence(f"{headline} from {org_name}") if org_name and org_name != headline
                        else _as_sentence(headline))
    elif tagline:
        segments.append(_as_sentence(tagline))
    count = _grid_item_count(page)
    if count:
        segments.append(f"Browse {count} product{'s' if count != 1 else ''}.")
    # The business description is the LAST resort on a catalog page: borrowing it when the page already
    # said something of its own is what made two pages read identically.
    if org_description and not segments:
        segments.append(_as_sentence(org_description))
    text = re.sub(r"\s+", " ", " ".join(segments)).strip()
    return trim_meta(text, _DESC_MAX)


def document_description(page: dict[str, Any], offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> str:
    """The <head> <meta name="description"> (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-04). Tenant's text wins
    (capped). Otherwise the product description, and when it's thin (<100 chars) it is enriched into
    "Shop {condition} {name}. {desc}. {return signal} {CTA}" — idempotent (no double "Shop"/".."), capped at
    155 at a word boundary. Meta description is a CTR lever, not a ranking factor."""
    explicit = str((page.get("seo") or {}).get("description") or "").strip()
    if explicit:
        return trim_meta(explicit, _DESC_MAX)
    # A page with no offer has nothing for the derivation below to read, and every branch of it is phrased
    # for something being sold. Decided on the page's own sections rather than on `offer` being empty: the
    # same question `is_offerless_page` answers everywhere else, and true whether or not a caller happened
    # to pass an empty offer.
    if is_offerless_page(page):
        return offerless_description(page, offer, products_by_id)
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
    # The tenant's own font default, applied only behind their explicit override toggle. Absent for every
    # caller that has no preferences to hand, which resolves to preset fonts -- the correct default.
    preferences: dict[str, Any] | None = None,
) -> list[str]:
    """Canonical, robots, Open Graph / Twitter Card, LCP resource hints and webfonts for the <head>
    (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01/02/09/10). Interim: canonical/og:url come from the page's
    published URL; clean root-domain paths and funnel/env noindex land with the Site work."""
    lines: list[str] = []
    canonical = _RENDER_STATE.get("canonical") or ""
    if canonical:
        lines.append(f'  <link rel="canonical" href="{escape(canonical)}">')
    # Indexing directive: index only for the published artifact in LIVE mode; a preview and anything in
    # test mode are noindex,nofollow (SEO-02/21). Funnel, upsell and thank-you pages are covered —
    # NONINDEXABLE_PAGE_TYPES demotes them to noindex,follow — which this described as "still Phase 2"
    # long after it shipped (author, 2026-10-23).
    lines.append(f'  <meta name="robots" content="{escape(_RENDER_STATE.get("robots") or NOINDEX_ROBOTS)}">')
    # Webmaster verification tokens (SEO-16) — let a tenant verify their Site in Google/Bing Search Console
    # so they can submit sitemaps. Emitted only when set on the Site.
    google_verify = str(_RENDER_SEO.get("google_site_verification") or "").strip()
    if google_verify:
        lines.append(f'  <meta name="google-site-verification" content="{escape(google_verify)}">')
    bing_verify = str(_RENDER_SEO.get("bing_site_verification") or "").strip()
    if bing_verify:
        lines.append(f'  <meta name="msvalidate.01" content="{escape(bing_verify)}">')
    # Pinterest claims a DOMAIN rather than a page, and only shows a website on the profile once claimed —
    # so without this a tenant cannot get their URL onto Pinterest at all, and the backlink check has
    # nothing to find. Emitted on every page of the Site, like the others, so the claim does not depend on
    # which page Pinterest happens to fetch.
    pinterest_verify = str(_RENDER_SEO.get("pinterest_site_verification") or "").strip()
    if pinterest_verify:
        lines.append(f'  <meta name="p:domain_verify" content="{escape(pinterest_verify)}">')

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
    # A TIP JAR has no price to advertise, and "0.00" would tell every share preview the page is free.
    if selected and not is_tip_price(selected):
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

    # WEBFONTS. Published pages carried none until now, so a tenant's chosen typography never reached
    # their customers -- every page fell back to whatever the visitor's device happened to have
    # (plans/FONT_SERVICE.md). preconnect first: the stylesheet and the font file are two round trips to
    # a third origin, and the handshake is most of the first one.
    # The tenant's OWN faces first: the service has never heard of them, so the page carries their
    # @font-face itself. Only the faces this page resolves to -- a tenant may have imported a dozen fonts,
    # and putting all of them on every page is the opposite of what the subsetting work was for.
    own = imported_faces_for(page, render_preferences(preferences))
    if own:
        lines.append("  <style>")
        for face in own:
            family = escape(str(face["family"]).strip())
            # The embedded bytes when publishing could read them, else the URL. See embed_imported_fonts:
            # a URL is the fallback, not the intent -- it is the one cross-origin font fetch left on a page.
            url = escape(str(face.get("data_uri") or face["url"]).strip())
            weight = escape(str(face.get("weight") or "400").strip())
            style = "italic" if str(face.get("style") or "").strip().lower() == "italic" else "normal"
            lines.append(
                f"    @font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
                f"src:url('{url}') format('woff2');font-display:swap}}"
            )
        lines.append("  </style>")

    families = families_to_load(page, render_preferences(preferences))
    if families:
        # `Name:400,700` -- the service's own syntax, not Google's `:wght@`. Without it a static family
        # serves weight 400 alone and every bold heading falls back.
        weights = ",".join(REQUEST_WEIGHTS)
        query = "&".join(f"family={quote(family)}:{weights}" for family in families)
        if not FONT_EMBED:
            # One <link> per family. Two tiny edge-cached files on one origin beat one uncached Lambda
            # round trip, and they are shared across every page that uses the family.
            lines.append(f'  <link rel="preconnect" href="{FONT_CSS_ORIGIN}" crossorigin>')
            for family in families:
                href = f"{FONT_CSS_BASE}/{quote(family.replace(' ', '-').lower())}.css"
                lines.append(f'  <link rel="stylesheet" href="{escape(href)}">')
            return lines
        if FONT_EMBED:
            # `fs=true` returns the font bytes INSIDE the stylesheet as data: URIs. The referencing
            # form needs a second, cross-origin request per face to a DIFFERENT host than the CSS, and
            # that request is what fails: Chromium and Firefox drop the fonts for a missing
            # Access-Control-Allow-Origin that curl, from the same machine and network, is served
            # correctly every time -- over IPv4 and IPv6, coalesced or not, cached or fresh. Embedding
            # deletes the request rather than the symptom, so there is nothing left to block.
            # Costs page weight until the faces are subset to Latin; see plans/FONT_SERVICE.md.
            query += "&fs=true"
        else:
            # Only worth a handshake when the files are fetched separately.
            lines.append(f'  <link rel="preconnect" href="{FONT_SERVICE_ORIGIN}" crossorigin>')
        lines.append(f'  <link rel="stylesheet" href="{escape(f"{FONT_SERVICE_ORIGIN}/?{query}")}">')
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
# `report_page_id` is set ONLY for a link hub on a platform host -- the page shape the abuse policy is about.
# Empty everywhere else, which is what keeps the Report link off a tenant's own storefront.
_RENDER_STATE: dict[str, str] = {"canonical": "", "robots": "noindex,nofollow", "home_url": "", "page_type": "",
                                 "report_page_id": ""}
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
# Set by `render_shipping_selector` when it actually emits a shell, so the ~4KB of selector JS is not shipped
# on pages that can never use it. Follows `_RENDER_BNPL`'s gate: emitted only when the markup exists.
_RENDER_SHIPPING: dict[str, Any] = {}
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

# Set by the lead CTA when it renders its form inside a <dialog>, read by any element that offers to open
# it. Render-scoped like the other indexes so one tenant's page cannot leak into another's on a warm
# container -- cleared in the same `finally`.
_RENDER_LEAD_DIALOG: dict[str, str] = {}
# Business-target reviews for the page's Site — a visible trust block, NEVER a self-serving LocalBusiness
# AggregateRating (Google suppresses those; plans/REVIEWS.md).
_RENDER_BUSINESS_REVIEWS: list[dict[str, Any]] = []
# A page is indexable only when it is the published artifact in LIVE Stripe mode (SEO-02/21). Everything
# else — the tenant's preview, anything in test mode — must be kept out of the index. This read "in
# production", which was the pre-decoupling world where the prod stack and live mode were the same thing;
# since plans/STRIPE_MODE_DECOUPLING.md the stack has no say (author, 2026-10-23).
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


def page_robots_directive(*, kind: str, mode: str, eligibility: str, page_type: str, on_custom_domain: bool, site_archived: bool = False, seo_enabled: bool = True) -> str:
    """The robots directive for a page artifact (plans/SITE_OBJECT.md §2.2, TP-08, SEO-02). Only a published
    artifact in LIVE mode, actually served on the Site's verified custom domain, whose Site is index-eligible
    (verified custom domain AND verified Stripe Connect), on an indexable page_type, gets index,follow.
    Everything else — a test-mode page, a preview, any page not served on the custom domain — is
    noindex,nofollow, the reputation-isolation floor.

    GATED ON STRIPE MODE, NOT ON THE PLATFORM STACK (author, 2026-10-23). This read
    `environment != "prod"` and treated the dev stack as inherently unindexable. That was the pre-decoupling
    world, where dev meant test and prod meant live; since plans/STRIPE_MODE_DECOUPLING.md the two are
    independent, and the question "may search engines see this?" is answered by the MODE alone. A live-mode
    store on a verified custom domain is a real shop whichever stack renders it, and a test-mode page is
    test data wherever it runs — which is why this used to need a second `if page_mode == "test"` override
    applied by the caller immediately afterwards. One gate now, in the function whose job it is.

    `checkout_base_url_for_page` kept its `environment` parameter "for signature compatibility" through the
    same decoupling; this one is renamed instead, because an argument named `environment` that must be
    handed a Stripe mode is how the two get confused again.
    """
    if site_archived:
        return NOINDEX_ARCHIVED_ROBOTS  # an archived Site de-indexes every one of its pages, everywhere
    if not seo_enabled:
        return NOINDEX_ROBOTS  # the tenant turned search visibility off for this Site (Site-level opt-out)
    # Test data must never reach search, whatever the Site's eligibility says.
    if kind != "published" or str(mode or "").strip().lower() != "live":
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
    preferences: dict[str, Any] | None = None,
    events_by_id: dict[str, dict[str, Any]] | None = None,
    kind: str = "",
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
    # Same lifecycle as the dims index: render-scoped, and cleared in the finally so one page's
    # descriptions can never leak into an unrelated render on a warm container.
    # The tenant's font preference reaches the resolver from here. Cleared in the finally with the rest, so
    # one tenant's preferences can never leak into another's page on a warm container.
    _RENDER_PREFERENCES.clear()
    _RENDER_PREFERENCES.update(preferences or {})
    # Scheduled events, by id. Render-scoped like the dims index above and cleared in the same finally: the
    # lead CTA that needs one sits six frames down, and threading a signature through every frame to reach
    # it is exactly what these indexes exist to avoid.
    _RENDER_EVENTS.clear()
    _RENDER_EVENTS.update(events_by_id or {})
    _RENDER_ALTS_INDEX.clear()
    _RENDER_ALTS_INDEX.update(collect_image_alts(
        page, offer, *products_by_id.values(), *services_by_id.values(), *offers_by_id.values(),
    ))
    _RENDER_STATE["canonical"] = canonical_page_url(canonical_url)
    # Where an island may call back to, and on whose behalf. The CTA carries these too, but only once a page
    # has a checkout_url -- which a PREVIEW has not, and a tip jar's amount box needs them to price a typed
    # amount. Cleared in the finally with the rest of the render-scoped state.
    _RENDER_STATE["api_base_url"] = str(api_base_url or "").rstrip("/")
    _RENDER_STATE["tenant_id"] = str(page.get("tenant_id") or offer.get("tenant_id") or "")
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
    # Whose domain this artifact will be served on, which is a DIFFERENT question from whether the Site has a
    # serving origin at all. §7's link trust boundary hangs on it: on the tenant's own verified domain any
    # destination may be linked, because the reputation at stake is theirs; on shared platform infrastructure
    # only allowlisted hosts become anchors. home_url is now true for a free *.jbay.uk address too (platform
    # hostname serving), so inferring the boundary from it -- which is what render_social_links and
    # render_link_cards did -- silently switched the check OFF on exactly the hosts it exists to protect.
    # Derived here from the Site, once, so the two renderers cannot disagree about it.
    hosting = (site or {}).get("hosting") or {}
    _RENDER_STATE["own_domain"] = bool(
        str(hosting.get("custom_domain") or "").strip()
        and (hosting.get("verification") or {}).get("verified")
    )
    _RENDER_STATE["breadcrumb"] = shows_breadcrumb(offer or {}, page)
    _RENDER_STATE["page_type"] = str(page_type or "")
    # A LINK HUB on a domain WE own gets a "Report this page" link (plans/CREATOR_LINK_POLICY.md §6). Both
    # halves matter: a hub is the tenant-authored, outbound-link page the policy exists for, and a shared
    # apex is what makes one bad actor everyone's problem. On the tenant's own verified domain it is their
    # page on their reputation, and a Report link of ours would be interference.
    _RENDER_STATE["report_page_id"] = (
        str(page.get("page_id") or "")
        if composition_key(offer or {}) == "lead_social" and not _RENDER_STATE["own_domain"]
        else ""
    )
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
    _RENDER_SHIPPING.clear()
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
    _RENDER_LEAD_DIALOG.clear()
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
            services_by_id, offers_by_id, kind,
        )
    finally:
        _RENDER_DIMS_INDEX.clear()
        _RENDER_ALTS_INDEX.clear()
        _RENDER_PREFERENCES.clear()
        # One tenant's sessions must never leak into another's page on a warm container.
        _RENDER_EVENTS.clear()
        _RENDER_STATE["canonical"] = ""
        _RENDER_STATE["api_base_url"] = ""
        _RENDER_STATE["tenant_id"] = ""
        _RENDER_STATE["tip_frequency_word"] = ""
        _RENDER_STATE["robots"] = NOINDEX_ROBOTS
        _RENDER_STATE["home_url"] = ""
        _RENDER_STATE["page_type"] = ""
        _RENDER_STATE["active_price_context"] = "standard"
        _RENDER_BNPL.clear()
        _RENDER_NAV["primary"], _RENDER_NAV["footer"] = [], []
        _RENDER_CATEGORY_PAGES.clear()
        _RENDER_REVIEWS.clear()
        _RENDER_LEAD_DIALOG.clear()
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
    kind: str = "",
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
    favicon_tags = render_favicon_tags(
        page.get("seo") or {}, default_favicon_url(), default_favicon_small_url())
    styles = render_template_styles(page)
    # Page Composer decides which sections render (plans/PAGE_COMPOSER.md). The renderer only iterates the
    # composed list — it never decides visibility itself.
    # The composer takes the OFFER and never its products, so the one product fact it needs -- is this a tip
    # jar? -- is stamped on first. Derived rather than read, so an offer saved before the field existed
    # composes the same way (domain/tips.py offer_is_tip_jar).
    composing_offer = stamp_tip_jar(offer, products_by_id)
    # The frequency a tip jar defaults to, resolved here rather than inside a section: the cards, the
    # frequency control and the CTA all state it, and they render in whatever order the tenant arranged.
    recurring_tip = tip_recurring_price(composing_offer, products_by_id)
    _RENDER_STATE["tip_frequency_word"] = (
        TIP_INTERVAL_WORDS.get(str(recurring_tip.get("recurring_interval") or "month"),
                               TIP_INTERVAL_WORDS["month"])[0] if recurring_tip else ""
    )
    # WHETHER THIS OFFER SHIPS, which decides the shipping element's default. Read from the products the
    # renderer has already loaded rather than trusted from the offer alone, so a page whose offer predates
    # the denormalised flag still composes right -- the composer ORs the two.
    ships_physical = any(
        (product.get("fulfillment") or {}).get("requires_shipping")
        for product in (products_by_id or {}).values()
    )
    composed_sections = compose_page(
        composing_offer, page, str(_RENDER_STATE.get("page_type") or "landing"),
        ships_physical=ships_physical)
    # Each element declares a channel (plans/LANDING_PAGE_GOAL_COMPOSITION.md): "body" paints markup, "head"
    # emits meta/JSON-LD, "sidecar" writes its own artifact. Route by it rather than assuming everything is
    # body — a head section rendered into <main> would be visible junk, and vice versa.
    # HIDING THE REVIEWS MUST DROP THE MARKUP TOO. Leaving `AggregateRating` in the head while the visible
    # reviews are gone is exactly the mismatch Google's guidelines forbid, and it is the one way the
    # Phase 2.5 element could do real harm (plans/REVIEWS.md). Decided ONCE, here, from the composed set,
    # so the head and the body cannot reach different answers depending on which renders first.
    _RENDER_STATE["reviews_visible"] = "yes" if any(
        str(s.get("type") or "") == "reviews" for s in composed_sections) else ""
    body_sections = [s for s in composed_sections if element_channel(str(s.get("type") or "")) == "body"]
    head_sections = [s for s in composed_sections if element_channel(str(s.get("type") or "")) == "head"]
    # Storefront chrome from the Site's menus (SEO-13): a header (brand → store root + primary nav) and a
    # footer nav. Both empty off a verified custom domain / on post-checkout pages. A crawlable breadcrumb
    # trail (SEO-11) sits above the page content, matching the BreadcrumbList JSON-LD.
    # If the page composes its own ● Brand mark, the store header drops its brand so there's only one (SITE_COLLECTIONS.md
    # "Chrome / header composition"). A disabled brand_label section still counts as absent.
    # Does this page have a brand mark OF ITS OWN -- shown or deliberately hidden? The storefront header
    # drops its brand either way, and the distinction matters: brand_label is in EVERY composition, so
    # "not in body_sections" means the tenant turned it off, not that the page never had one. Reading only
    # the composed list made hiding the brand HAND it to the header, which then printed the Organization name
    # in a different style at the top of the page -- the tenant switched the brand off and it moved.
    #
    # The header's brand exists for pages with no mark of their own (an offer-less storefront or category
    # page), and those carry no brand_label section at all.
    # Did the tenant explicitly HIDE the brand? That is the fact that matters, and neither of the two things
    # I reached for first can express it.
    #
    # Reading the page's saved sections says "no brand_label here" -- but the builder omits a hidden one
    # entirely rather than writing it disabled, so a page that just turned the brand off looks identical to a
    # page that never had one. That is why suppressing on the document appeared to work once and then stopped
    # the moment the page was re-saved.
    #
    # Reading the composition says "this shape owns a brand mark" for every offer page -- which would silence
    # the header on a legacy page whose sections predate brand_label, leaving it with no brand anywhere.
    #
    # The override is the tenant's own statement, so it is the one to read.
    brand_hidden = ((page.get("composition") or {}).get("overrides") or {}).get("brand_label", {}) \
        .get("enabled") is False
    has_brand_mark = any(
        s.get("type") == "brand_label" and s.get("enabled") is not False for s in body_sections
    )
    # Who owns the page's single H1. Normally the hero headline -- but a link-in-bio composition has no hero
    # at all (plans/LEAD_GEN_PAGES.md §4), which left those pages with NO H1 and a page-health notice the
    # tenant could not act on: the missing heading was the composition's decision, not theirs. The brand mark
    # is the honest answer there, because on a link hub the creator's name IS the page's heading. Decided ONCE
    # here, from the composed list, so the two sections cannot both claim it -- brand_label renders before the
    # hero would, so it cannot discover the answer on its own.
    # WHO owns the page's single H1, decided once here because the candidates render in different places and
    # none of them can see the others. A hero headline wins where there is one. Otherwise the brand mark --
    # and where the tenant has HIDDEN the brand because this page is about a person rather than a business,
    # the person's name takes it. A link hub whose visible heading is a name should say so in its markup, and
    # without this it published with no H1 at all and a page-health warning the tenant could not act on.
    hero_owns_h1 = any(s.get("type") in H1_SECTION_TYPES for s in body_sections)
    identity_section = next((s for s in body_sections if s.get("type") == "hero_media"
                             and s.get("show_identity")), None)
    if hero_owns_h1:
        h1_owner = "hero"
    elif has_brand_mark:
        h1_owner = "brand_label"
    elif identity_section is not None and tenant_display_name():
        h1_owner = "identity"
    else:
        h1_owner = ""
    _RENDER_STATE["h1_owner"] = h1_owner
    _RENDER_STATE["brand_label_is_h1"] = h1_owner == "brand_label"
    site_header = render_site_header(has_brand_mark=has_brand_mark or brand_hidden)
    footer_nav = render_footer_nav()
    breadcrumb = render_breadcrumb(breadcrumb_trail(offer, products_by_id))
    body = "\n".join(
        render_section(section, page, offer, products_by_id, resolved_offer, checkout_url, api_base_url, services_by_id, offers_by_id)
        for section in body_sections
    )
    # First-party reviews render after the page's sections (visible content matching the Product review JSON-LD).
    business_reviews_block = render_business_reviews_block(page)
    head_extras = "\n".join(part for part in (
        render_head_section(section, page, offer, products_by_id, services_by_id, composed_sections,
                            offers_by_id)
        for section in head_sections
    ) if part)
    has_legal_footer_section = any(section.get("type") == "legal_footer" for section in composed_sections)
    # Post-purchase funnel pages (upsell / downsell / thank-you) drop the auto legal footer: they are one-click
    # continuations of an already-completed checkout, not standalone sales pages, so the Terms/Privacy/Refund
    # links are noise there (user request). An explicitly-authored legal_footer section still renders.
    suppress_legal_footer = str(_RENDER_STATE.get("page_type") or "") in ("funnel_step", "thank_you")
    legal_footer = "" if (has_legal_footer_section or suppress_legal_footer) else render_legal_footer(page.get("legal") or {}, api_base_url=api_base_url)
    # A TEST page does not touch the tenant's real analytics.
    #
    # The adapters below send ViewContent, AddToCart, InitiateCheckout and Purchase to the tenant's own
    # GA4 property and Meta pixel. On a test page those are purchases that never happened -- and the Meta
    # pixel is not merely a report: its optimiser LEARNS from conversion events, and the tenant's ad spend
    # is then optimised against signals a tenant generated while testing their own funnel. Deleting the
    # data afterwards does not unteach it.
    #
    # Suppressed rather than tagged as test: GA4's debug_mode and Meta's test_event_code both need a value
    # only the tenant has, so there is nothing honest to send. The comment below says so in view-source,
    # because "my pixel isn't firing" is otherwise a confusing afternoon.
    _analytics = (page.get("analytics") or {}) if _page_is_live(page) else {}
    analytics_tags = render_analytics_tags(_analytics)
    analytics_adapters = render_analytics_adapters(_analytics)
    if not _page_is_live(page) and (page.get("analytics") or {}):
        analytics_tags = (
            "  <!-- Analytics suppressed: this is a test-mode page. Your GA4 property and Meta pixel are "
            "left alone so test traffic cannot train your ad optimisation. Publish in live mode to fire "
            "them. -->")
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
        "</head>",
        ("<body>" if _RENDER_STATE.get("seo_enabled", True) else "<body data-seo=\"off\">"),
        render_price_context_banner(page),
        "  <main>",
        site_header,
        breadcrumb,
        body,
        business_reviews_block,
        footer_nav,
        legal_footer,
        "  </main>",
        minicart,
        # END OF BODY, not <head>. It is ~50KB of inline script, and an inline script cannot be deferred --
        # `defer` is specified to have no effect without a `src` -- so in the head it stopped the parser
        # before any content painted, costing LCP and Total Blocking Time on every page. Everything it does
        # is already wrapped in DOMContentLoaded, so running it here changes no behaviour, and it now sits
        # with the other page scripts instead of being the one exception.
        render_page_interactions_script(page),
        render_price_context_script(),
        conversion_data,
        *render_bnpl_messaging_scripts(),
        render_shipping_selector_script(),
        render_price_description_toggle_script(page),
        render_view_beacon(page, kind, api_base_url),
        render_outbound_link_script(page, kind, api_base_url),
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
    "hero_media": {"render": lambda c: render_hero_media(c.section, c.offer, c.products_by_id, c.services_by_id, (c.page or {}).get("video_posters")), "version": 1},
    "headline": {"render": lambda c: render_headline(c.section), "version": 1},
    "subheadline": {"render": lambda c: render_subheadline(c.section), "version": 1},
    "trust_badges": {"render": lambda c: render_trust_badges(c.section), "version": 1},
    "hero": {"render": lambda c: render_hero(c.section, c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "offer_price_selector": {"render": _render_offer_selector, "version": 1},
    # A standalone prominent price card (SALES_FUNNELS.md P3.5) — used by the upsell page, whose 'upsell'-context
    # price the offer_price_selector filters out, so the amount would otherwise show only in the CTA button.
    "featured_price": {"render": lambda c: render_featured_price(c.section), "version": 1},
    "refund_policy": {"render": lambda c: render_refund_policy(c.section, c.offer, c.products_by_id), "version": 1},
    "shipping": {"render": lambda c: render_shipping_selector(c.section, c.offer, c.products_by_id,
                                                             c.api_base_url), "version": 1},
    "faq": {"render": lambda c: render_faq(c.section), "version": 1},
    "content_block": {"render": lambda c: render_content_blocks(c.section), "version": 1},
    # Thank-you page extras (SALES_FUNNELS.md P3.5 Phase 2) — emitted by synthesize_thank_you_page only.
    "celebration": {"render": lambda c: render_celebration(c.section), "version": 1},
    "shipping_eta": {"render": lambda c: render_shipping_eta(c.section), "version": 1},
    "reviews": {"render": lambda c: render_reviews_section(c.section, c.offer, c.products_by_id), "version": 1},
    "digital_download": {"render": lambda c: render_digital_download(c.section), "version": 1},
    "next_steps": {"render": lambda c: render_next_steps(c.section), "version": 1},
    "thank_you_footer": {"render": lambda c: render_thank_you_footer(c.section), "version": 1},
    "testimonials": {"render": lambda c: render_testimonials(c.section), "version": 1},
    "rating": {"render": lambda c: render_rating(c.section), "version": 1},
    "client_marquee": {"render": lambda c: render_client_marquee(c.section), "version": 1},
    "price_highlight": {"render": lambda c: render_price_highlight(c.section, c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "coupon": {"render": lambda c: render_coupon(c.section, c.offer, c.products_by_id, c.checkout_url,
                                                 page=c.page, resolved_offer=c.resolved_offer), "version": 1},
    "author_bio": {"render": lambda c: render_author_bio(c.section), "version": 1},
    "product_details": {"render": lambda c: render_product_details(c.offer, c.products_by_id, c.services_by_id), "version": 1},
    "product_carousel": {"render": lambda c: render_product_carousel(c.section, c.page, c.offers_by_id, c.products_by_id, c.services_by_id, c.checkout_url, c.api_base_url), "version": 1},
    "page_ribbon": {"render": lambda c: render_page_ribbon(c.section, c.page, c.api_base_url,
                                                          offer=c.offer, resolved_offer=c.resolved_offer,
                                                          checkout_url=c.checkout_url,
                                                          products_by_id=c.products_by_id), "version": 1},
    "before_after": {"render": lambda c: render_before_after(c.section), "version": 1},
    "photo": {"render": lambda c: render_photo(c.section), "version": 1},
    "info_cards": {"render": lambda c: render_info_cards(c.section), "version": 1},
    "event_date": {"render": lambda c: render_event_date(c.section, c.page), "version": 1},
    "video": {"render": lambda c: render_video(c.section), "version": 1},
    "numbered_list": {"render": lambda c: render_numbered_list(c.section), "version": 1},
    "quote": {"render": lambda c: render_quote(c.section), "version": 1},
    "bragging_points": {"render": lambda c: render_bragging_points(c.section), "version": 1},
    "post_purchase_carousel": {"render": lambda c: render_post_purchase_carousel(c.section, c.page, c.api_base_url), "version": 1},
    "brand_hero": {"render": lambda c: render_brand_hero(c.section), "version": 1},
    "catalog_grid": {"render": lambda c: render_catalog_grid(c.section, c.offers_by_id, c.products_by_id, c.services_by_id), "version": 1},
    "related_products": {"render": lambda c: render_catalog_grid(c.section, c.offers_by_id, c.products_by_id, c.services_by_id), "version": 1},
    "seller_profile": {"render": lambda c: render_seller_profile(c.section), "version": 1},
    "social_links": {"render": lambda c: render_social_links(c.section), "version": 1},
    "tip_jar": {"render": lambda c: render_tip_jar(c.section), "version": 1},
    "link_cards": {"render": lambda c: render_link_cards(c.section), "version": 1},
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
    offers_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """`offers_by_id` carries the OTHER offers the page references -- the ones behind a catalog grid's
    cards. A head section describing a catalog page needs them: its own `offer` is empty, because the page
    has none (plans/OFFERLESS_PAGES_IN_BUILDER.md P4)."""
    renderer = HEAD_SECTION_REGISTRY.get(str(section.get("type") or ""))
    if renderer is None:
        return ""
    return renderer(section, page, offer, products_by_id, services_by_id, composed_sections,
                    offers_by_id or {})


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


# `hidden` exists because the avatar became a REFERENCE: an empty page-level avatar_url now means "inherit
# the store's", not "no avatar", so without this a tenant who uploads a store avatar has no way to keep it
# off one particular page.
AVATAR_PLACEMENTS = ("overlay", "overlay_bottom", "overlay_top", "inline", "centered", "hidden")


def avatar_placement(section: dict[str, Any]) -> str:
    """Where the avatar sits relative to the hero image.

    `overlay` is the default and the pre-2026-09-10 behaviour: circular, overlapping the hero's bottom-left,
    the shape a link-in-bio page uses. `inline` drops it below the hero in the normal flow (the eddieabbew
    reference), and `centered` is inline but horizontally centred, which is what a page with no cover image
    wants -- an overlay avatar hanging off nothing looks like a mistake.

    Unknown values fall back to `overlay` rather than rendering an unstyled div, so a hand-edited document
    degrades to the old behaviour instead of a broken page.
    """
    value = str((section or {}).get("avatar_placement") or "").strip().lower()
    return value if value in AVATAR_PLACEMENTS else "overlay"


def avatar_source(section: dict[str, Any]) -> str:
    """The avatar this section actually renders, or "" for none.

    By REFERENCE: an empty page-level `avatar_url` inherits the STORE's rather than meaning "none", so a
    tenant who changes their profile picture changes it everywhere instead of leaving each page frozen at
    whatever it was the day it was made. Only `hidden` means none.

    One reader, because three callers need this answer -- the img, the overhang margin, and the cover band --
    and a fourth copy of "page url, else store url, unless hidden" is how they drift apart.
    """
    if avatar_placement(section) == "hidden":
        return ""
    return str((section or {}).get("avatar_url") or "") or str(_RENDER_PREFERENCES.get("avatar_url") or "")


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


EVENT_DATE_PRESENTATIONS = ("band", "card")
EVENT_DATE_SOURCES = ("auto", "event", "sale", "flash_sale", "custom")


def _page_epoch(page: dict[str, Any], key: str) -> int:
    try:
        return max(0, int((page.get(key) or {}).get("ends_at") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def _next_session_start(now: int) -> tuple[int, str]:
    """When the page's next open session starts, and the zone it is announced in. (0, "") if none.

    Reads the render-scoped event index, so the element does not need to know which product carries the
    event -- a registration page has one, and "the next one still open" is the only sensible answer.
    """
    best, zone = 0, ""
    for scheduled in _RENDER_EVENTS.values():
        upcoming = event_next_occurrence(scheduled, now=now)
        if not upcoming:
            continue
        starts = event_starts_at(upcoming)
        if starts and (not best or starts < best):
            best, zone = starts, str(upcoming.get("timezone") or "")
    return best, zone


def resolve_event_date(section: dict[str, Any], page: dict[str, Any]) -> int:
    """Which moment this element announces, as epoch seconds. 0 means there is nothing to show.

    A tenant should not retype a date the page already holds -- the same reasoning that makes Product
    details and Related products derive rather than ask. `sale.ends_at` and `flash_sale.ends_at` are both
    already stored and already honoured by the pricing, so the element reads one of them.

    `auto` prefers the FLASH sale when it has a date: a page carrying both is running the shorter, louder
    window inside the longer one, and the date worth announcing is the one about to pass. The dropdown
    exists for the tenant who disagrees, which is why the preference is a default rather than a rule.
    """
    source = str(section.get("source") or "auto")
    if source not in EVENT_DATE_SOURCES:
        source = "auto"
    if source == "custom":
        try:
            return max(0, int(section.get("date") or 0))
        except (TypeError, ValueError):
            return 0
    if source == "event":
        return _next_session_start(int(time.time()))[0]
    if source == "sale":
        return _page_epoch(page, "sale")
    if source == "flash_sale":
        return _page_epoch(page, "flash_sale")
    # `auto` is about SALES and stays that way. A webinar is not a sale and its session is not a deadline
    # on an offer (author, 2026-10-14: "webinars have nothing to do with sales, they are their own thing"),
    # so a registration page names `source: "event"` explicitly rather than reaching the session through a
    # pricing fallback. Blending the two would make the element mean different things on different pages.
    return _page_epoch(page, "flash_sale") or _page_epoch(page, "sale")


def format_event_date(epoch: int, tz_name: str, *, with_time: bool) -> str:
    """A moment in plain English: "Saturday, October 31, 2026", optionally "... at 7:00 PM EST".

    Rendered at PUBLISH rather than by a script, because the answer never changes: a fixed moment in a
    fixed zone is the same sentence forever, and a page that prints its date without JavaScript is one
    fewer thing that can fail in front of a visitor.

    The zone is the EVENT's, not the store's. A business in Denver can announce a webinar at 7PM EST, and
    the references label the host's zone rather than converting to the reader's -- "7PM EST" is part of
    what is being announced. It is also the only reachable answer: `business.timezone` lives on the USER
    profile and the renderer is handed the TENANT profile.

    Built by hand rather than with strftime's %-d / %-I, which are glibc extensions and not portable.
    """
    moment = datetime.fromtimestamp(int(epoch), tz=load_zone(tz_name))
    date_part = f"{moment.strftime('%A')}, {moment.strftime('%B')} {moment.day}, {moment.year}"
    if not with_time:
        return date_part
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    label = moment.strftime("%Z") or str(tz_name or "")
    return f"{date_part} at {hour}:{moment.minute:02d} {meridiem} {label}".strip()


def render_event_date(section: dict[str, Any], page: dict[str, Any]) -> str:
    """The date of the thing, spelled out. No date means NO element -- there is nothing to say."""
    epoch = resolve_event_date(section, page)
    if epoch <= 0:
        return ""

    presentation = str(section.get("presentation") or "band")
    if presentation not in EVENT_DATE_PRESENTATIONS:
        presentation = "band"
    tz_name = str(section.get("timezone") or "")
    source = str(section.get("source") or "auto")
    if source == "event" and not section.get("timezone"):
        # The session's own zone, not the store's: "9:30 AM AEST" is part of what is being announced, and
        # the occurrence is where that was chosen.
        session_zone = _next_session_start(int(time.time()))[1]
        if session_zone:
            tz_name = session_zone
    with_time = section.get("show_time") is not False
    text = format_event_date(epoch, tz_name, with_time=with_time)
    machine = datetime.fromtimestamp(epoch, tz=load_zone(tz_name)).isoformat()
    label = str(section.get("label") or "").strip()
    icon = str(section.get("icon") or "").strip()

    inner = "".join(part for part in (
        f'<span class="sl-event-date-icon" aria-hidden="true">{escape(icon)}</span>' if icon else "",
        f'<span class="sl-event-date-label">{escape(label)}</span>' if label else "",
        # <time datetime=...>: the sentence is for people, the attribute is what a calendar scraper or
        # assistive technology can actually parse.
        f'<time class="sl-event-date-value" datetime="{escape(machine)}">{escape(text)}</time>',
    ) if part)

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "event-date")))
    return "\n".join([
        f'    <section class="sl-event-date is-{presentation}{themed}" data-section-id="{section_id}"'
        f' data-section-type="event_date"{style_attr}>',
        f"      {inner}",
        "    </section>",
    ])


COUNTDOWN_MODES = ("duration", "deadline")
COUNTDOWN_DISPLAYS = ("line", "digits")
COUNTDOWN_UNITS = (("days", "Days"), ("hours", "Hours"), ("minutes", "Minutes"), ("seconds", "Seconds"))


def countdown_deadline(section: dict[str, Any], page: dict[str, Any]) -> int:
    """The moment a deadline countdown counts to, as epoch seconds. 0 means there is nothing to count to.

    An ABSENT `ends_at` derives from the page's own `sale.ends_at` -- the same "absent means derive at
    render" rule the brand label and hero copy follow. That field already exists and the sale machinery
    already honours it, so deriving is what stops the banner and the sale disagreeing about when the sale
    ends: a page cannot show "2 days left" over pricing that expired on Monday.
    """
    raw = section.get("ends_at")
    if raw:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0
    try:
        return max(0, int((page.get("sale") or {}).get("ends_at") or 0))
    except (TypeError, ValueError):
        return 0


def render_countdown_timer(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    mode = str(section.get("mode") or "duration")
    if mode not in COUNTDOWN_MODES:
        mode = "duration"
    display = str(section.get("display") or "line")
    if display not in COUNTDOWN_DISPLAYS:
        display = "line"
    ends_at = countdown_deadline(section, page) if mode == "deadline" else 0
    # A deadline with no date is not a countdown. Rendering the banner anyway would leave "Offer expires
    # in" above an empty space, which reads as a broken page rather than an unconfigured one.
    if mode == "deadline" and not ends_at:
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
        f"    <section class=\"sl-countdown\" data-section-id=\"{escape(str(section.get('id', 'countdown')))}\" data-section-type=\"countdown_timer\" data-mode=\"{mode}\" data-ends-at=\"{ends_at}\" data-display=\"{display}\" data-duration-minutes=\"{duration}\" data-persistent=\"{str(bool(section.get('persistent'))).lower()}\" data-sticky=\"{str(bool(section.get('sticky'))).lower()}\" data-transparent=\"{str(transparent).lower()}\" data-marquee=\"{str(bool(section.get('marquee'))).lower()}\" data-start-text=\"{label}\" data-end-text=\"{end_text}\" data-start-icon=\"{start_icon}\" data-end-icon=\"{end_icon}\" data-start-enabled=\"{str(start_enabled).lower()}\" data-end-enabled=\"{str(end_enabled).lower()}\" data-start-color=\"{start_color}\" data-end-color=\"{end_color}\" style=\"{style}\"{'' if start_enabled else ' hidden'}>",
        # aria-live=off: the timer mutates every second; announcing every tick would flood a screen reader.
        "      <span class=\"sl-countdown-content\" aria-live=\"off\">",
        (f"        <span data-countdown-icon aria-hidden=\"true\">{start_icon}</span>" if start_icon else ""),
        f"        <span data-countdown-label>{label}</span>",
        (
            # The grid is built server-side and filled by the island, so the shape is in the HTML rather
            # than assembled by script -- a page with no JS shows the boxes and their names, not nothing.
            "        <span class=\"sl-countdown-digits\" data-countdown-digits>"
            + "".join(
                f"<span class=\"sl-countdown-unit\"><b data-countdown-{key}>00</b>"
                f"<small>{word}</small></span>"
                for key, word in COUNTDOWN_UNITS
            )
            + "</span>"
            if display == "digits" else
            f"        <time data-countdown-display>{duration}:00</time>" if duration or mode == "deadline" else ""
        ),
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


# Every section type that emits an <h1>. Three, not one, because a page saved before the hero family was
# merged stores `headline` as its own section -- so checking only for "hero" would hand the H1 to the brand
# mark on every legacy page and give it two. Keep this list in step with the <h1> emitters in this module.
H1_SECTION_TYPES = frozenset({"hero", "headline", "brand_hero"})


def resolve_business_name() -> str:
    """What this business is CALLED, resolved from the Site down to the owner's own name.

    One definition, because two places now need it — the brand label and the coupon — and a coupon that
    named the business differently from the header on the same page would look like someone else's.
    """
    return (
        str(_RENDER_ORG.get("name") or "").strip()
        or str(_RENDER_PREFERENCES.get("business_name") or "").strip()
        or str(_RENDER_PREFERENCES.get("display_name") or "").strip()
    )


def render_brand_label(section: dict[str, Any], page: dict[str, Any]) -> str:
    if section.get("enabled") is False:
        return ""
    # The tenant's own words first, then the Site's business identity, and only then the page's own name.
    # The Site sits ABOVE the page name because a brand label names the business, not the document -- a link
    # hub falling back to "My Links Landing Page" is showing a filename to a visitor. Resolved here rather
    # than stored, so renaming the business or attaching a Site updates every page that never overrode it.
    # A brand label names the BUSINESS. Every step here is an identity; none is a document title, because a
    # page headed "2025 Guide to Junk Food Restaurants Landing Page" is showing a visitor a filename
    # (author, 2026-09-16). The Site is the best answer when the page has one; the tenant's own business name
    # covers a page not yet attached to one; the owner's name is the last resort, and is what a solo creator
    # would have put there anyway. page.name is deliberately NOT in the chain any more.
    label = render_headline_markup(section.get("label") or resolve_business_name())
    if not label:
        return ""
    # heading_role: none in the element catalog — a brand label is not a heading (matches the preview's span)
    # WHEN there is a hero to be one. On a composition with no hero (link-in-bio) it becomes the page's H1
    # rather than leaving the page without one; render_page decides, so the two can never both claim it.
    # This centered ● Brand mark is the page's single brand header (the old top-left store-header brand is retired).
    # On a served, browseable page it doubles as the crawlable store-root link (SEO-13); on a post-checkout page it
    # stays plain text so it can't leak the buyer back out.
    home = _RENDER_STATE.get("home_url") or ""
    linkable = bool(home) and _RENDER_STATE.get("page_type") not in NONINDEXABLE_PAGE_TYPES
    inner = f'<a class="sl-brand-label-link" href="/">{label}</a>' if linkable else label
    tag = "h1" if _RENDER_STATE.get("brand_label_is_h1") else "p"
    return "\n".join([
        f"    <section class=\"sl-brand-label{' is-pulsing' if section.get('brand_dot_pulse') else ''}\""
        f" data-section-id=\"{escape(str(section.get('id', 'brand-label')))}\" data-section-type=\"brand_label\">",
        f"      <{tag}>{inner}</{tag}>",
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
        # DECORATIVE, and marked so. The play button beside it already carries aria-label="Play {label}",
        # so describing the poster too would announce the same video twice. An empty alt alone is not enough:
        # accessibility_warnings counts that as missing, which is exactly the warning tenants could not act
        # on. aria-hidden is the accessible way to opt out -- the is-blank fallback below already did it.
        f'<img class="sl-embed-poster" src="{escape(poster)}" alt="" aria-hidden="true" loading="lazy" decoding="async">'
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


# Not a URL: the marker that this slide is the generated cover band. A data: URI was the obvious move --
# PLACEHOLDER_IMAGE already is one -- but an SVG cannot read a CSS custom property, so its colours would have
# to be baked in at publish time and the cover would then disagree with the page the first time the tenant
# changed preset. Deriving beats freezing (the rule the hero copy and brand label both learned the hard way).
HERO_BAND = "\x00hero-band"


def render_media_slide(url: str, alt: str, *, autoplay: bool, eager: bool = False, poster: str = "",
                       controls: bool = True) -> str:
    """The MediaViewer's image/video modes (plans/CONVERSION_CONTEXT.md review 4). A video URL renders a
    <video>. Autoplay adds muted+loop because every browser refuses to autoplay with sound.

    `controls` defaults to ON and the hero never turns it off. Without it an autoplaying hero starts muted
    with no way to unmute, pause or scrub — the tenant enabled autoplay, not silence, and a visitor who
    wants the audio had no affordance at all. It is also a WCAG 2.2.2 (Pause, Stop, Hide) failure: content
    that plays automatically for more than five seconds must offer a way to stop it.

    The video ELEMENT may turn it off, because a chromeless looping product clip is a real design and a
    control bar welded across it is not. What makes that legitimate rather than a regression is that the
    bar is REPLACED, not removed: the video becomes the control (`data-sl-video-tap`, focusable, click or
    Enter/Space to pause), so the mechanism 2.2.2 asks for still exists. Silence plus no way to stop it is
    the combination that is never shipped."""
    if url == HERO_BAND:
        # Decorative: it carries no information the identity block below does not already say, so it takes
        # no alt text and is hidden from a screen reader rather than announced as "image".
        return '<div class="sl-hero-band" role="presentation"></div>'
    embed = parse_video_embed(url)
    if embed:
        # A tenant poster wins: YouTube's auto-frame is often a blurred mid-sentence, and Vimeo has no
        # deterministic thumbnail at all, so this is the only poster it can have.
        return render_video_embed({**embed, "thumbnail_url": poster or embed["thumbnail_url"]}, alt)
    if is_video_url(url):
        # `muted` is not a taste decision: every browser refuses to autoplay a video with sound, so an
        # autoplay flag that did not mute would be a checkbox that silently does nothing -- the tenant
        # ticks it, nothing moves, and there is no error anywhere to explain why.
        parts = ["controls", "playsinline"] if controls else ["playsinline", "data-sl-video-tap",
                                                              'tabindex="0"']
        if autoplay:
            parts.extend(["muted", "loop", "autoplay"])
        attrs = " ".join(parts)
        # Autoplay with `preload="metadata"` asks the browser to start something it was told not to fetch.
        preload = "auto" if eager or autoplay else "metadata"
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


def render_hero_brand(section: dict[str, Any], offer: dict[str, Any]) -> list[str]:
    """The positionable brand chip (plans/SOCIALITE_PARITY.md), baked into the hero IMAGE.

    Emitted inside the <figure> on purpose. As a sibling of the figure its containing block was
    .sl-hero-media, which GROWS when an inline or centred avatar sits below the image -- so a bottom-left
    brand slid down to sit level with the avatar, and overlapped it on a phone. Anchored to the figure it
    stays on the artwork wherever the avatar goes.
    """
    lines: list[str] = []
    if section.get("brand_overlay"):
        brand_text = str(section.get("brand_text") or offer_brand_fallback(offer))
        if brand_text:
            position = str(section.get("brand_position") or "top-right")
            if position not in HERO_BRAND_POSITIONS:
                position = "top-right"
            # Opt-in per page: a dot pulsing on every page is noise; on one it reads as a live signal.
            dot_class = "sl-hero-brand-dot is-pulsing" if section.get("brand_dot_pulse") else "sl-hero-brand-dot"
            lines.append(
                f"      <div class=\"sl-hero-brand sl-hero-brand--{position}\">"
                f"<span class=\"{dot_class}\"></span>{escape(brand_text)}</div>"
            )
    return lines


# ONE cap, defined where the document is validated. Two constants that must agree is how a value ends up
# enforced at 40 in one place and 60 in another, and the renderer clipping a string the validator accepted.
from stripe_link.domain.documents import HERO_TAGLINE_MAX_LENGTH as TAGLINE_MAX_LENGTH


def tenant_display_name() -> str:
    """The creator's own name, as the dashboard's user pill shows it.

    Read from the tenant profile the renderer ALREADY loads, so this costs no extra work at publish. Two
    sources in one document, preferred in this order:

    - `display_name`, which publish copies in from the owner's user profile. That is the canonical string --
      the Profile page edits it, and it is what the pill displays.
    - `owner.first_name` + `owner.last_name`, written at signup. The fallback for when the copy is absent
      (a tenant that has not published since this shipped) or the read failed.

    It is the OWNER's name specifically, never "a user's": a page carries no author, and publish runs from a
    DynamoDB stream holding only the page, so there is no signed-in user to ask. The owner is the one person
    a tenant always has exactly one of.
    """
    prefs = _RENDER_PREFERENCES
    name = str(prefs.get("display_name") or "").strip()
    if name:
        return name
    owner = prefs.get("owner") or {}
    parts = [str(owner.get("first_name") or "").strip(), str(owner.get("last_name") or "").strip()]
    return " ".join(part for part in parts if part)


def render_hero_identity(section: dict[str, Any]) -> list[str]:
    """The creator's name and slogan, under the avatar.

    Opt-in per page: most pages are selling something and want the product's headline, not a person's name.
    The NAME is derived, never stored -- same rule as the avatar and the brand label, so renaming yourself
    updates every page instead of leaving each one frozen at whatever was true the day it was made. Only the
    slogan is the page's own, because it is the page's own sentence.
    """
    if not section.get("show_identity"):
        return []
    name = tenant_display_name()
    tagline = str(section.get("tagline") or "").strip()[:TAGLINE_MAX_LENGTH]
    if not name and not tagline:
        return []
    lines = ['      <div class="sl-hero-identity">']
    if name:
        # An H1 only when nothing else claims it -- render_page decides, so the hero headline, the brand mark
        # and this name can never all think they are the heading. plans/SEMANTIC_HTML.md keeps the outline to
        # exactly one.
        tag = "h1" if _RENDER_STATE.get("h1_owner") == "identity" else "p"
        lines.append(f'        <{tag} class="sl-hero-identity-name">{escape(name)}</{tag}>')
    if tagline:
        lines.append(f'        <p class="sl-hero-identity-tagline">{escape(tagline)}</p>')
    lines.append("      </div>")
    return lines


def render_hero_overlays(section: dict[str, Any], offer: dict[str, Any]) -> list[str]:
    """The avatar, which sits OUTSIDE the figure because an inline or centred one is in normal flow below
    the image rather than painted on it."""
    lines: list[str] = []
    # BY REFERENCE. A page that has not uploaded its own avatar shows the STORE's, resolved at render from
    # the tenant profile -- so when the tenant changes their picture, every page that never overrode it
    # shows the new one. Copying the URL onto each page at build time would have frozen each page at
    # whatever the avatar was the day it was made, which is the opposite of what a profile picture is for.
    avatar_url = avatar_source(section)
    if avatar_url:
        # The avatar carries brand identity, so it's a content image — name it (brand text, else the offer).
        avatar_alt = escape(str(section.get("brand_text") or offer_brand_fallback(offer) or "Brand avatar"))
        lines.append(
            f"      <div class=\"sl-avatar-wrap sl-avatar--{avatar_placement(section)}\">"
            f"<img class=\"sl-avatar\" src=\"{escape(avatar_url)}\" "
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
    # embed url -> tenant-supplied poster. Kept on the PAGE rather than in the media list because that
    # list is plain URL strings, and a poster is about the entry rather than a new kind of entry.
    posters: dict[str, str] | None = None,
) -> str:
    posters = posters or {}
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
    # A link-in-bio page with no uploaded cover gets a THEMED BAND instead of no hero at all. Not a fix to
    # the early return below, which is right for every other page: the avatar complements a cover image, so
    # where there is no cover there is nothing for one to complement. The band is not decoration filling a
    # hole -- it is the real estate the avatar needs in order to exist, on the one page shape whose entire
    # job is identity. Every other shape still renders nothing, because inventing furniture on a product or
    # bridge page would be furniture with no reason to be there.
    # ...and only when the hero has an OCCUPANT to seat, asked by rendering them and looking. Enumerating
    # the conditions instead got this wrong twice (author, 2026-09-17): gated on the avatar, hiding it
    # blanked the name and slogan; gated on those too, it still blanked a page whose only occupant was the
    # brand chip. Everything the hero can hold is built before the question is asked, so a fifth occupant
    # cannot reintroduce the bug. Still guarded rather than unconditional: an empty hero has nothing to
    # seat, and a bare strip of colour is decoration for its own sake.
    overlays = render_hero_overlays(section, offer)
    # OUTSIDE the section, deliberately. The avatar is absolutely positioned against .sl-hero-media, and
    # .has-avatar reserves the room it overhangs into with a margin BELOW that section. Putting the identity
    # block inside meant it rendered into the figure's flow -- under the image and behind the avatar -- and
    # grew the section, which moved the avatar's `bottom` anchor with it. As a sibling it lands after the
    # reserved margin, which is exactly where the overhang ends.
    identity = render_hero_identity(section)
    brand = render_hero_brand(section, offer)
    if not images and composition_key(offer) == "lead_social" and (overlays or identity or brand):
        images = [HERO_BAND]
    if not images:
        return ""
    alt = localized_alt(str(product.get("name") or offer.get("name") or "Product image"))
    section_id = escape(str(section.get("id", "hero-media")))
    autoplay = bool(section.get("autoplay"))
    # has-avatar reserves the space the overlay OVERHANGS into. An inline or centred avatar sits in normal
    # flow and needs no reserved gap -- keeping it would leave a hole under the hero.
    # Both OVERLAYS overhang the artwork and need room reserved -- one below, one above. inline/centred sit
    # in normal flow and need none; hidden has nothing to reserve for.
    placement = avatar_placement(section)
    has_avatar = placement in ("overlay", "overlay_bottom", "overlay_top") and bool(avatar_source(section))
    overhang = ("" if not has_avatar else
                (" has-avatar-top" if placement == "overlay_top" else " has-avatar"))
    media_class = "sl-hero-media" + overhang
    # Which conversion target each slide stands for, DECLARED rather than inferred from its position.
    #
    # The island used to read the settled slide's ordinal and treat it as the target index. That held only
    # while slide count == item count, which `offer_uses_grouped_item_media` guaranteed by throwing away a
    # single product's gallery. With the gallery restored the two counts legitimately differ, and the
    # ordinal would have meant: swiping to the second PHOTO re-prices the BNPL island against the second
    # TIER CARD (it indexes `.sl-price-option` by that number), and hides a listicle's tier block entirely.
    #
    # One landing item means one target, so every slide declares 0 and swiping a gallery changes nothing.
    # Several items and grouped media still gives exactly one slide each, so the ordinal is the item index.
    one_target = len(stage_opportunities(offer, STAGE_LANDING)) <= 1
    slides = [
        f"        <div class=\"sl-hero-slide\" data-conv-index=\"{0 if one_target else index}\">"
        f"{render_media_slide(url, alt, autoplay=autoplay, eager=(index == 0), poster=posters.get(url, ''))}</div>"
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
            *brand,
            caption_html,
            "      </figure>",
            *overlays,
            "    </section>",
            *identity,
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
        "      <div class=\"sl-hero-dots\">",
        *dots,
        # The counter sits WITH the dots below the image, not over it. Overlaid top-right it collided with
        # a top-right brand overlay, and two translucent pills stacked on the artwork looked like a bug.
        # Below the hero it is still exactly where someone looks to see how many images there are.
        f"        <span class=\"sl-hero-counter\" data-hero-counter>1 / {len(images)}</span>",
        "      </div>",
        *brand,
        caption_html,
        "      </figure>",
        *overlays,
        "    </section>",
        *identity,
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
    """Does the hero carousel stand for the ITEMS rather than for one product's gallery?

    One slide per item, because the slide ordinal IS the conversion-target index that the tier blocks and
    the BNPL island read. More than one landing item and that mapping has to hold.

    `any(selectable_prices)` used to be part of this and was WRONG. It arrived (98708a7, 2026-06-12) as a
    generalisation of `offer_type == "bundle"` at a moment when `offer_type` was being dropped as a stored
    field, so tiers were standing in for "several products". They are not the same thing: a single product
    sold as 1-pack and 4-pack is ONE product with ONE conversion target, and collapsing its gallery to a
    single image lost every photo but the first on exactly the offers most likely to have several --
    while the builder went on listing them all as AUTO rows, promising a carousel the page never built.
    `derived_offer_type` is authoritative now, so the proxy is not needed by anything.
    """
    return len(stage_opportunities(offer, STAGE_LANDING)) > 1


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


def render_shipping_selector(section: dict[str, Any], offer: dict[str, Any],
                             products_by_id: dict[str, dict[str, Any]],
                             api_base_url: str | None) -> str:
    """Where the buyer wants it sent, and what that costs. A RUNTIME component, not a snapshot.

    plans/SHIPPING_ELEMENT.md phase 5. Emits an empty shell with no prices and no country list in it: both come
    from `GET /shipping-quote` when the page loads. That is the plan's rule and the reason for it -- a rate
    depends on destination, live carrier pricing, package composition and the date, and a published page is an
    S3 artifact, so anything baked in starts rotting immediately. Even the COUNTRY list is fetched: a tenant who
    adds a zone would otherwise not see it until they republished.

    Renders nothing at all without an API base to ask, rather than a dropdown that can never populate.
    """
    if section.get("enabled") is False or not api_base_url:
        return ""
    # Nothing physical, nothing to ask. The endpoint answers this too, but a page that never emits the markup
    # cannot flash an empty selector before the fetch returns.
    if not any(
        (products_by_id.get(str(item.get("product_id") or "")) or {}).get("fulfillment", {}).get("requires_shipping")
        or (products_by_id.get(str(item.get("product_id") or "")) or {}).get("product_type") == "physical"
        for item in (offer.get("items") or [])
    ):
        return ""
    heading = escape(str(section.get("heading") or "Shipping"))
    prompt = escape(str(section.get("prompt") or "Where should we ship your order?"))
    section_id = escape(str(section.get("id", "shipping")))
    # Only now does the page need the script. Without this gate every page carried ~4KB of selector JS,
    # including digital ones with no element to drive -- dead weight the PageSpeed work would have objected to.
    _RENDER_SHIPPING["_active"] = True
    return "\n".join([
        f"    <section class=\"sl-shipping\" data-section-id=\"{section_id}\" data-section-type=\"shipping\"",
        f"             data-shipping-api-base=\"{escape(str(api_base_url))}\"",
        f"             data-shipping-tenant=\"{escape(str(offer.get('tenant_id') or ''))}\"",
        f"             data-shipping-offer=\"{escape(str(offer.get('offer_id') or ''))}\" hidden>",
        f"      <h2>{heading}</h2>",
        f"      <p class=\"sl-shipping-prompt\">{prompt}</p>",
        "      <div class=\"sl-shipping-where\">",
        "        <label class=\"sl-shipping-field\"><span>Country</span>",
        "          <select class=\"sl-shipping-country\" aria-label=\"Destination country\"></select>",
        "        </label>",
        # The field that makes tier 3 possible. A carrier prices a journey between two postcodes; until
        # this existed every live zone answered `needs: carrier` and every buyer shipped free.
        "        <label class=\"sl-shipping-field sl-shipping-postal-field\">",
        "          <span class=\"sl-shipping-postal-label\">Postal code</span>",
        "          <input class=\"sl-shipping-postal\" type=\"text\" inputmode=\"numeric\"",
        "                 autocomplete=\"postal-code\" aria-label=\"Postal code\" />",
        "        </label>",
        # Hidden until a country that needs it is chosen -- most do not, and an always-visible field a
        # buyer must guess at is friction bought for nothing.
        "        <label class=\"sl-shipping-field sl-shipping-region-field\" hidden>",
        "          <span class=\"sl-shipping-region-label\">State</span>",
        "          <input class=\"sl-shipping-region\" type=\"text\" autocomplete=\"address-level1\"",
        "                 maxlength=\"3\" aria-label=\"State or province\" />",
        "        </label>",
        "      </div>",
        "      <p class=\"sl-shipping-note\" hidden></p>",
        "      <button class=\"sl-shipping-retry\" type=\"button\" hidden>Try again</button>",
        "      <div class=\"sl-shipping-rates\" role=\"radiogroup\" aria-label=\"Shipping options\"></div>",
        "      <dl class=\"sl-shipping-summary\" hidden>",
        "        <div><dt>Subtotal</dt><dd class=\"sl-shipping-subtotal\"></dd></div>",
        "        <div><dt>Shipping</dt><dd class=\"sl-shipping-cost\"></dd></div>",
        "        <div class=\"sl-shipping-total-row\"><dt>Total</dt><dd class=\"sl-shipping-total\"></dd></div>",
        "      </dl>",
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
            # data-icon carries the glyph so the STYLESHEET can colour specific ones. Emoji bring their own
            # colour; the chevrons and arrows added 2026-09-16 are text glyphs that inherit currentColor, so
            # without this they would be badge-text blue rather than the gold and red they were asked for.
            f"        <span data-icon=\"{escape(str(badge.get('emoji') or ''))}\">"
            f"{escape(str(badge.get('emoji') or ''))}</span>",
            f"        <strong>{escape(str(badge.get('label') or ''))}</strong>",
            "      </div>",
        ])
        for badge in badges
    ]
    if not rendered:
        return ""
    # Vertical stacks them as full-width rows instead of a wrapping pill row. A pill row reads as
    # decoration; on a page whose whole argument is "we are licensed, we answer at 3am, we cover your
    # county", each claim deserves its own line (author, 2026-09-16).
    orientation = "vertical" if str(section.get("orientation") or "").strip() == "vertical" else "horizontal"
    return "\n".join([
        f"    <section class=\"sl-trust-badges is-{orientation}\" data-section-id=\"{escape(str(section.get('id', 'trust-badges')))}\" data-section-type=\"trust_badges\">",
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


def hero_copy(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """The hero's headline and subheadline: the page's own words, else the offer's, else the product's.

    The page wins, because a tenant who typed something meant it. Below that sits the offer's presentation --
    which is a snapshot of the PRODUCT's name and description, not the offer's internal label -- and then the
    product itself, for an offer written before presentation existed.

    Deliberately NOT a lead product's `lead_capture.description`. That sentence describes the FORM ("Collect
    the visitor's email address."), and using it here made every capture page introduce itself by explaining
    its own plumbing instead of naming the thing on offer (author, 2026-09-15: "an abomination").
    """
    presentation = offer.get("presentation") or {}
    product = first_offer_product(offer, products_by_id) if products_by_id else {}
    headline = (
        str(section.get("headline") or "").strip()
        or str(presentation.get("headline") or "").strip()
        or str(product.get("name") or "").strip()
    )
    subheadline = (
        str(section.get("subheadline") or "").strip()
        or str(presentation.get("subheadline") or "").strip()
        or str(product.get("description") or "").strip()
    )
    return headline, subheadline


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
        # DERIVED when the page does not say, exactly as hero_media_images derives the picture. A hero with
        # nothing in it used to render an empty <section>; more importantly, this is the half of the pattern
        # the brand label already follows ("absent means derive at render"), and following it here is what
        # stops a page freezing at whatever copy it happened to be seeded with.
        headline, subheadline = hero_copy(section, offer or {}, products_by_id or {})
        headline_html, headline_attr = (render_headline_markup(headline), "") if headline else ("", "")
        sub_html, sub_attr = (subheadline, "") if subheadline else ("", "")

    return "\n".join([
        f"    <section class=\"sl-hero\" data-section-id=\"{escape(str(section.get('id', 'hero')))}\" data-section-type=\"hero\">",
        f"      <h1{headline_attr}>{headline_html}</h1>" if headline_html else "",
        (f"      <p{sub_attr}>{escape(sub_html)}</p>" if sub_attr else render_body_markup(sub_html, "", "      ")) if sub_html else "",
        "    </section>",
    ])


def _frequency_label(price: dict[str, Any]) -> str:
    """"One time", "Every day", "Every 3 weeks" -- what a price option is called when nothing named it.

    The counterpart of the quantity label a product option falls back to; a service has no quantity to
    count, so how often it charges is the thing that distinguishes one option from another.
    """
    if str(price.get("pricing_model") or "") != "recurring":
        return "One time"
    recurring = price.get("recurring")
    if not isinstance(recurring, dict) or not recurring.get("interval"):
        return "One time"
    interval = str(recurring["interval"])
    try:
        count = int(recurring.get("interval_count") or 1)
    except (TypeError, ValueError):
        count = 1
    return f"Every {interval}" if count <= 1 else f"Every {count} {interval}s"


def _is_just_the_price(label: str, amount: int, currency: str, price: dict[str, Any]) -> bool:
    """Whether a card's title is nothing but the amount the card already shows underneath."""
    def squash(value: str) -> str:
        return "".join(str(value).split()).casefold()

    money = format_money(amount, currency)
    return squash(label) in {squash(money), squash(f"{money}{recurring_suffix(price)}")}


def render_service_price_card(item, service_id, services_by_id, offer, display_index,
                              *, group_name="", is_default=True, option=None):
    """One landing-page price card for a service offer item, sourced from the service's own prices[].
    Carries data-service-id so checkout resolves the service.

    `option` is the price being rendered, so one service item can produce several cards -- a single session
    beside a plan. Without it the card was always the item's one `price_id`, which is why a service with two
    prices could only ever show one of them.

    `group_name` and `is_default` exist for CHOICE offers, where the SERVICES are alternatives: every card
    shares one radio group and exactly one is checked. A BUNDLE keeps a group per service and every card
    checked, because there every service is charged and the radio is decorative (plans/SERVICE_CHOICE.md).
    """
    service = services_by_id.get(service_id)
    if service is None:
        raise RenderError(f"Service '{service_id}' was not provided for offer '{offer.get('offer_id', '')}'.")
    option = option or {}
    price = resolve_service_price(service, option.get("price_id") or item.get("price_id")) or {}
    if not is_landing_page_price(price):
        return None
    amount = int(price.get("unit_amount", 0))
    currency = str(price.get("currency") or "usd")
    raw_label = str(item.get("display_label") or option.get("label")
                    or price.get("label") or service.get("name") or "Option")
    # A card headed by its own price says the amount twice -- once as the title, again in the price row
    # right below it. The offer form seeded a service option's label from the money string, so published
    # offers carry it; fall back to what the card is actually FOR rather than repeating the number.
    if _is_just_the_price(raw_label, amount, currency, price):
        # When the item offers a CHOICE, the title has to tell the options apart, and the service name is
        # the same on every one of them (and already the page's H1). The frequency is the difference.
        raw_label = (_frequency_label(price) if len(item.get("selectable_prices") or []) > 1
                     else str(service.get("name") or "Option"))
    label = escape(raw_label)
    checkout_quantity = int(item.get("quantity") or 1)
    price_id = str(price.get("price_id") or "")
    image_url = (service.get("presentation") or {}).get("hero_image_url") or ""
    description = escape(str(price.get("description") or service.get("description") or ""))
    compare_at_unit_amount = price.get("compare_at_unit_amount")
    savings_pct = price.get("discount_pct")
    if not savings_pct and compare_at_unit_amount:
        savings_pct = discount_pct(amount, int(compare_at_unit_amount))
    card_markup = "\n".join([
        f"      <article class=\"sl-price-option\" data-service-id=\"{escape(service_id)}\" data-product-id=\"\" data-price-id=\"{escape(price_id)}\" data-quantity=\"{checkout_quantity}\" data-default=\"{'true' if is_default else 'false'}\" data-sale-amount=\"{amount}\" data-regular-amount=\"{int(compare_at_unit_amount) if compare_at_unit_amount else ''}\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
        "        " + responsive_img(image_url, str(service.get("name") or label), sizes=PRICE_OPTION_SIZES) if image_url else "",
        "        <div class=\"sl-price-copy\">",
        f"          <strong title=\"{label}\">{label}</strong>",
        f"          <p class=\"sl-price-description\" title=\"{description}\">{description}</p>" if description else "",
        "          <button type=\"button\" class=\"sl-price-more\" aria-expanded=\"false\" hidden>See more</button>" if description else "",
        "          <div class=\"sl-price-row\">",
        f"            <span class=\"sl-price-amount\" data-price-amount>{escape(format_money(amount, currency))}</span>"
        f"{f'<span class=\"sl-price-every\">{escape(recurring_suffix(price))}</span>' if recurring_suffix(price) else ''}",
        f"            <span class=\"sl-regular-price\">{escape(format_money(int(compare_at_unit_amount), currency))}</span>" if compare_at_unit_amount else "",
        f"            <span class=\"sl-savings\">Save {int(savings_pct)}%</span>" if savings_pct else "",
        "          </div>",
        "        </div>",
        f"        <input type=\"radio\" name=\"{escape(group_name or f'sl-price-{service_id}')}\" value=\"{escape(price_id)}\" aria-label=\"{label}, {escape(format_money(amount, currency))}{escape(recurring_suffix(price))}\" {'checked' if is_default else ''}>",
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


ONE_TIME_LABEL = "one-time"
# What each interval reads as on a card, and on the button that switches to it. The tenant offers ONE
# interval and the supporter chooses whether to use it, so a recurring jar still takes one-off tips -- and
# each card has to say which of the two it is about to charge.
TIP_INTERVAL_WORDS = {"day": ("daily", "Daily"), "week": ("weekly", "Weekly"),
                      "month": ("monthly", "Monthly"), "year": ("yearly", "Yearly")}


def tip_recurring_price(offer, products_by_id):
    """The offer's tip price, when it offers a recurring option. None otherwise."""
    for item in stage_opportunities(offer or {}, STAGE_LANDING):
        product = products_by_id.get(str(item.get("product_id") or "")) or {}
        for price in product.get("prices") or []:
            if str(price.get("price_id") or "") != str(item.get("price_id") or ""):
                continue
            if is_tip_price(price) and price.get("allow_recurring"):
                return price
    return None


def recurring_suffix(price: dict[str, Any]) -> str:
    """"/month", "every 3 weeks" -- what to append to a repeating price's amount.

    A subscription that renders as a bare number is the BUYER-facing half of the bug that let a recurring
    price sync as a one-off: the tenant meant a subscription, the page showed a price, and the first the
    buyer learned of it was the second charge. Empty for anything that does not repeat.

    Tips are excluded deliberately -- a repeating tip's frequency is chosen by the supporter at checkout, not
    fixed on the price, and `render_tip_frequency` already says so in its own words.
    """
    if str(price.get("pricing_model") or "") != "recurring":
        return ""
    recurring = price.get("recurring")
    if not isinstance(recurring, dict) or not recurring.get("interval"):
        return ""
    interval = str(recurring["interval"])
    try:
        count = int(recurring.get("interval_count") or 1)
    except (TypeError, ValueError):
        count = 1
    if count <= 1:
        return f"/{interval}"
    # "every 3 months" rather than "/3 month": a slash reads as "per one", and the number is the whole point.
    return f" every {count} {interval}s"


def render_tip_frequency(price):
    """One-time or repeating, asked ONCE above the amounts rather than per card.

    The amount and the frequency are two different questions; pairing every preset with every interval would
    be eight cards to say four things. The choice restates itself on each card, so whichever amount is
    selected always says what it is about to charge.

    **Repeating is pre-selected.** Defaulting a donation form to monthly rather than merely offering it
    raised monthly gifts 187.7% in NextAfter's experiment, with one-time still on the form -- the DEFAULT is
    the lever, not exclusivity. A tenant who went to the trouble of enabling a monthly tip is asking for
    monthly (author, 2026-09-14).

    When the tenant offers ONLY the repeating tip, the control still renders -- hidden, carrying the state
    the island and the cards read -- because there is no choice left to present, only a fact the cards
    already state.
    """
    interval = str(price.get("recurring_interval") or "month")
    word, title = TIP_INTERVAL_WORDS.get(interval, TIP_INTERVAL_WORDS["month"])
    attrs = (f'class="sl-tip-frequency" role="group" aria-label="How often" data-tip-frequency '
             f'data-tip-interval="{escape(interval)}" data-tip-word="{escape(word)}" data-tip-chosen="recurring"')
    if not tip_allows_one_time(price):
        return f'      <div {attrs} hidden></div>'
    return "\n".join([
        f"      <div {attrs}>",
        '        <button type="button" class="sl-tip-freq-option" data-tip-frequency-value="once" aria-pressed="false">One-time</button>',
        f'        <button type="button" class="sl-tip-freq-option is-selected" data-tip-frequency-value="recurring" aria-pressed="true">{escape(title)}</button>',
        "      </div>",
    ])


def _tip_option_cards(
    item: dict[str, Any], product: dict[str, Any], price: dict[str, Any], display_index: int
) -> tuple[list[tuple[tuple[int, int, int], str]], int]:
    """A TIP JAR's cards: one per preset amount, plus an "Other" card holding a number input.

    The same `.sl-price-option` radio card the tier selector uses, because a supporter choosing between $5,
    $10 and $25 is doing exactly what a buyer choosing between tiers does -- and reusing it means the CTA,
    the selection JS and the styling all work already. What differs is where the amount comes from: these
    carry `data-tip-amount` instead of a Stripe price id, and the server re-decides the charge at checkout
    (plans/PAY_WHAT_YOU_WANT.md §3).
    """
    product_id = str(item.get("product_id") or "")
    price_id = str(price.get("price_id") or "")
    currency = str(price.get("currency") or "usd")
    quantity = int(item.get("quantity") or 1)
    radio_name = f"sl-price-{escape(product_id)}"
    cards: list[tuple[tuple[int, int, int], str]] = []
    # The CHARGE, not the tenant's keyed amount: the button says what the card will be charged, so the
    # number on it and the number on the statement are the same one (plans/PAY_WHAT_YOU_WANT.md §5e).
    amounts = tip_preset_charges(price)
    for position, amount in enumerate(amounts):
        label = escape(format_money(amount, currency))
        cards.append(((0, position, display_index), "\n".join(line for line in [
            f"      <article class=\"sl-price-option sl-tip-option\" data-product-id=\"{escape(product_id)}\" data-price-id=\"{escape(price_id)}\" data-tip-amount=\"{amount}\" data-tip-source=\"preset\" data-quantity=\"{quantity}\" data-default=\"{'true' if position == 0 else 'false'}\" data-sale-amount=\"{amount}\" data-regular-amount=\"\" data-currency=\"{escape(currency)}\" data-label=\"{label}\">",
            "        <div class=\"sl-price-copy\">",
            f"          <strong>{label}</strong>",
            f"          <span class=\"sl-tip-freq\" data-tip-freq>{_RENDER_STATE.get('tip_frequency_word') or ONE_TIME_LABEL}</span>",
            "        </div>",
            f"        <input type=\"radio\" name=\"{radio_name}\" value=\"tip-{amount}\" aria-label=\"Tip {label}\"{' checked' if position == 0 else ''}>",
            "      </article>",
        ] if line)))
        display_index += 1
    if tip_allows_custom(price):
        # The last card is a box, not a button. Its amount is what the supporter means to GIVE, so the fee
        # mode applies on top of it -- the note under the input says the resulting charge, computed by the
        # same server calculation that will charge it (author, 2026-09-13).
        minimum, maximum = TIP_MIN_AMOUNT, TIP_MAX_AMOUNT
        fee_handling = escape(str(price.get("fee_handling") or "standard"))
        product_type = escape(str(product.get("product_type") or "digital"))
        # The box prices a typed amount through the platform's own calculation, so it needs somewhere to ask
        # and someone to ask as. Carried on the CARD rather than read off the CTA: a preview has no
        # checkout_url, so the CTA carries nothing, and the box silently quoted the tip without its fees.
        tip_api = escape(str(_RENDER_STATE.get("api_base_url") or ""))
        tip_tenant = escape(str(_RENDER_STATE.get("tenant_id") or ""))
        cards.append(((0, len(amounts), display_index), "\n".join(line for line in [
            f"      <article class=\"sl-price-option sl-tip-option sl-tip-custom\" data-product-id=\"{escape(product_id)}\" data-price-id=\"{escape(price_id)}\" data-tip-source=\"custom\" data-tip-min=\"{minimum}\" data-tip-max=\"{maximum}\" data-tip-fee-handling=\"{fee_handling}\" data-tip-product-type=\"{product_type}\" data-tip-api=\"{tip_api}\" data-tip-tenant=\"{tip_tenant}\" data-quantity=\"{quantity}\" data-default=\"{'true' if not amounts else 'false'}\" data-sale-amount=\"0\" data-regular-amount=\"\" data-currency=\"{escape(currency)}\" data-label=\"Other\">",
            "        <div class=\"sl-price-copy\">",
            "          <strong>Other</strong>",
            "          <label class=\"sl-tip-input\">",
            f"            <span aria-hidden=\"true\">{escape(CURRENCY_SYMBOLS.get(currency.lower(), currency.upper()))}</span>",
            f"            <input type=\"number\" inputmode=\"decimal\" min=\"{minimum // 100}\" max=\"{maximum // 100}\" step=\"1\" placeholder=\"{minimum // 100}\" aria-label=\"Enter your own amount\" data-tip-input>",
            "          </label>",
            f"          <span class=\"sl-tip-freq\" data-tip-freq>{_RENDER_STATE.get('tip_frequency_word') or ONE_TIME_LABEL}</span>",
            f"          <p class=\"sl-tip-note\" data-tip-note>{escape(format_money(minimum, currency))} to {escape(format_money(maximum, currency))}.</p>",
            "        </div>",
            f"        <input type=\"radio\" name=\"{radio_name}\" value=\"tip-custom\" aria-label=\"Enter your own amount\"{' checked' if not amounts else ''}>",
            "      </article>",
        ] if line)))
        display_index += 1
    return cards, display_index


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
        if is_tip_price(price):
            # No unit_amount to render -- the buyer picks. Rendering this as an ordinary tier card is what
            # put "$0.00" on a tip jar's page.
            tip_cards, display_index = _tip_option_cards(item, product, price, display_index)
            cards.extend(tip_cards)
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
            f"          <strong title=\"{label}\">{label}</strong>",
            f"          <p class=\"sl-price-description\" title=\"{description}\">{description}</p>" if description else "",
            "          <button type=\"button\" class=\"sl-price-more\" aria-expanded=\"false\" hidden>See more</button>" if description else "",
            "          <div class=\"sl-price-row\">",
            f"            <span class=\"sl-price-amount\" data-price-amount>{escape(format_money(amount, currency))}</span>"
            f"{f'<span class=\"sl-price-every\">{escape(recurring_suffix(display_price))}</span>' if recurring_suffix(display_price) else ''}",
            f"            <span class=\"sl-regular-price\">{escape(format_money(int(compare_at_unit_amount), currency))}</span>" if compare_at_unit_amount else "",
            f"            <span class=\"sl-savings\">Save {int(savings_pct)}%</span>" if savings_pct else "",
            "          </div>",
            "        </div>",
            f"        <input type=\"radio\" name=\"sl-price-{escape(product_id)}\" value=\"{escape(str(display_price.get('price_id', '')))}\" aria-label=\"{label}, {escape(format_money(amount, currency))}{escape(recurring_suffix(display_price))}\" {'checked' if default_attr == 'true' else ''}>",
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
    landing_items = list(stage_opportunities(offer, STAGE_LANDING))
    # In a CHOICE offer the services are alternatives, so they share one radio group and exactly one card is
    # checked -- the same item resolve_offer() would charge for a CTA that arrives with no selection, so the
    # page and the checkout agree on the default (plans/SERVICE_CHOICE.md).
    choosing = service_selection(offer) == SERVICE_SELECTION_CHOICE
    default_service_item = chosen_service_item(
        landing_items, "", str(offer.get("default_service_id") or ""),
    ) if choosing else None
    for item in landing_items:
        service_id = item.get("service_id", "")
        if service_id:
            # One card per price the item offers: a service can be sold as a single session AND as a plan.
            options = service_price_options(item)
            default_option_id = selected_service_price_id(item)
            for option in options:
                on_default_item = (item is default_service_item) if choosing else True
                card = render_service_price_card(
                    item, service_id, services_by_id, offer, display_index,
                    group_name="sl-service-choice" if choosing else "",
                    # Exactly one card is checked per radio group: the item's default price, and -- when the
                    # SERVICES are alternatives too -- only on the default service.
                    is_default=on_default_item and str(option.get("price_id")) == default_option_id,
                    option=option,
                )
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
    recurring_tip = tip_recurring_price(offer, products_by_id)
    return "\n".join(part for part in [
        "    <section class=\"sl-price-selector\" data-section-type=\"offer_price_selector\">",
        render_tip_frequency(recurring_tip) if recurring_tip else "",
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


def render_shipping_selector_script() -> str:
    """Fetch the destinations and the rates, then let the buyer choose. Nothing is priced in the page.

    Emitted ONLY when a shipping shell was rendered. The first version shipped unconditionally, putting ~4KB
    of JS on every page including digital ones that could never use it.

    plans/SHIPPING_ELEMENT.md phase 5. The element sends a SERVICE choice to checkout, never an amount: the
    server re-derives the price, so a browser cannot submit a $2 shipping option it was never offered.

    The country it settles on is published as `window.__jbShipTo` and rides to checkout as `ship_to_country`,
    which narrows Stripe's allowed countries to that one -- so a buyer quoted for Canada cannot switch to the
    US at the pay button and pay Canadian postage.

    Fails QUIET and stays hidden. A shipping selector that cannot reach the API must not block a sale: the
    buyer checks out and Stripe collects the address as it does today.
    """
    if not _RENDER_SHIPPING.get("_active"):
        return ""
    return "\n".join([
        "  <script>",
        "  (function(){",
        "    var box = document.querySelector('.sl-shipping');",
        "    if (!box) return;",
        "    var api = box.dataset.shippingApiBase, tenant = box.dataset.shippingTenant,",
        "        offer = box.dataset.shippingOffer;",
        "    if (!api || !tenant || !offer) return;",
        "    var select = box.querySelector('.sl-shipping-country');",
        "    var postal = box.querySelector('.sl-shipping-postal');",
        "    var postalLabel = box.querySelector('.sl-shipping-postal-label');",
        "    var regionField = box.querySelector('.sl-shipping-region-field');",
        "    var region = box.querySelector('.sl-shipping-region');",
        "    var regionLabel = box.querySelector('.sl-shipping-region-label');",
        "    var rates = box.querySelector('.sl-shipping-rates');",
        "    var note = box.querySelector('.sl-shipping-note');",
        "    var retry = box.querySelector('.sl-shipping-retry');",
        "    var summary = box.querySelector('.sl-shipping-summary');",
        # Carriers insist on a subdivision in these and quote without one everywhere else. Asking for a
        # state a country does not use is friction bought for nothing.
        #
        # THE US IS NOT ONE OF THEM, whatever the postal convention suggests: a US ZIP already determines
        # the state, and both carriers rate on it alone. Verified against live Shippo rather than assumed --
        # the same eleven services at the same eleven prices come back for 80204 with the state and without
        # it. So the field bought nothing and cost every US buyer a keystroke (author, 2026-10-04).
        "    var REGION_REQUIRED = { CA:'Province', AU:'State', BR:'State', IN:'State', MX:'State' };",
        "    var POSTAL_LABEL = { US:'ZIP code', GB:'Postcode', AU:'Postcode', NZ:'Postcode', IE:'Eircode' };",
        "    var seq = 0, lastData = null;",
        "    var cart = function(){",
        # `.selected`, and fall back to the FIRST card -- the convention the rest of this page already
        # uses (`querySelector('.sl-price-option.selected') || cards[0]`). The element shipped looking for
        # `[aria-checked="true"]` or `.is-selected`, neither of which this renderer ever writes, so `card`
        # was always null: no product_id, price_id or quantity reached /shipping-quote, every quote was
        # computed from the offer's first item regardless of the tier chosen, and the order summary had no
        # subtotal to show. Found by reading the PUBLISHED page rather than the source (2026-10-01).
        "      var cards = document.querySelectorAll('.sl-price-option');",
        "      var card = document.querySelector('.sl-price-option.selected') || cards[0] || null;",
        "      return { product_id: (card && card.dataset.productId) || '', price_id: (card && card.dataset.priceId) || '',",
        "               quantity: (card && card.dataset.quantity) || '1', card: card };",
        "    };",
        "    var money = function(cents){",
        "      try { return (cents/100).toLocaleString(undefined,{style:'currency',currency:'USD'}); }",
        "      catch (e) { return '$' + (cents/100).toFixed(2); }",
        "    };",
        "    var say = function(text, state){",
        "      note.textContent = text || ''; note.hidden = !text;",
        "      box.dataset.shippingState = state || '';",
        "      retry.hidden = state !== 'error';",
        "    };",
        # What each `needs` MEANS to a buyer. Never "free": an unknown rendered as free is a promise the
        # tenant did not make. `carrier` no longer claims shipping is calculated at checkout, because it
        # is not -- an unpriceable destination is one we cannot ship to today.
        "    var reasons = {",
        "      country: 'Choose where to ship to see the cost.',",
        "      postal_code: 'Enter your postal code to see shipping options.',",
        "      carrier: 'We could not get shipping rates for this address right now.',",
        "      services: 'No shipping service is available to this address.',",
        "      box_price: 'No shipping option is available to this address yet.',",
        "      zones: '',",
        # Never reached -- `setup` returns before the box is revealed -- but present so that a future
        # branch which forgets to return finds an empty string rather than `undefined` painted at a buyer.
        "      setup: ''",
        "    };",
        "    var subtotal = function(c){",
        "      var card = c.card; if (!card) return null;",
        "      var raw = card.dataset.expired === 'true' ? card.dataset.regularAmount : card.dataset.saleAmount;",
        "      var amount = parseInt(raw, 10); if (isNaN(amount)) return null;",
        "      return amount * (parseInt(c.quantity, 10) || 1);",
        "    };",
        "    var showTotals = function(shipping){",
        "      var sub = subtotal(cart());",
        "      if (sub === null || shipping === null) { summary.hidden = true; return; }",
        "      box.querySelector('.sl-shipping-subtotal').textContent = money(sub);",
        "      box.querySelector('.sl-shipping-cost').textContent = shipping ? money(shipping) : 'Free';",
        "      box.querySelector('.sl-shipping-total').textContent = money(sub + shipping);",
        "      summary.hidden = false;",
        "    };",
        # The SERVICE and the QUOTE ID travel to checkout; the amount never does. The server reads the
        # price off its own row, so a browser cannot submit a $2 option it was never offered.
        "    var choose = function(token, amount){",
        "      window.__jbShipService = token || '';",
        "      showTotals(typeof amount === 'number' ? amount : null);",
        "      syncCta();",
        "    };",
        # The CTA's href is built ONCE at page load and rebuilt only when a PRICE CARD changes -- never
        # when a shipping service is chosen. Since the quote is fetched asynchronously, the href was always
        # frozen before `__jbShipQuote` existed, so the globals were set and nothing ever read them: the
        # buyer picked a service, saw a total, and checked out with no postage. Setting the globals is not
        # enough; the link has to be rewritten.
        "    var syncCta = function(){",
        "      var cta = document.querySelector('.sl-cta[data-checkout-base-url], [data-checkout-base-url]');",
        "      if (!cta || !cta.href) return;",
        "      try {",
        "        var url = new URL(cta.href, window.location.href);",
        "        var put = function(key, value){",
        "          if (value) { url.searchParams.set(key, value); } else { url.searchParams.delete(key); }",
        "        };",
        "        put('ship_to_country', window.__jbShipTo);",
        "        put('shipping_quote', window.__jbShipQuote);",
        "        put('shipping_service', window.__jbShipService);",
        "        cta.href = url.toString();",
        "      } catch (e) {}",
        "    };",
        "    var ask = function(){",
        "      var c = cart(), country = select.value || '';",
        "      var url = api.replace(/\\/$/,'') + '/shipping-quote?clientID=' + encodeURIComponent(tenant)",
        "        + '&offer=' + encodeURIComponent(offer)",
        "        + (c.product_id ? '&product_id=' + encodeURIComponent(c.product_id) : '')",
        "        + (c.price_id ? '&price_id=' + encodeURIComponent(c.price_id) : '')",
        "        + '&quantity=' + encodeURIComponent(c.quantity)",
        "        + (country ? '&country=' + encodeURIComponent(country) : '')",
        "        + (postal.value ? '&postal_code=' + encodeURIComponent(postal.value.trim()) : '')",
        "        + (region.value ? '&region=' + encodeURIComponent(region.value.trim()) : '')",
        # The server cart wins over the selected card: it IS what is being posted. Absent on a plain
        # buy-now page, where the card is the only cart there is.
        "        + (window.__jbCartId ? '&cart_id=' + encodeURIComponent(window.__jbCartId) : '');",
        "      var mine = ++seq;",
        "      return fetch(url).then(function(r){ return r.ok ? r.json() : null; })",
        # A slow first answer must never overwrite a fast second one: the buyer has typed since.
        "        .then(function(data){ return mine === seq ? data : undefined; })",
        "        .catch(function(){ return mine === seq ? null : undefined; });",
        "    };",
        "    var paintRates = function(data){",
        "      rates.innerHTML = '';",
        "      (data.options || []).forEach(function(option, index){",
        "        var id = 'sl-ship-' + index;",
        "        var row = document.createElement('label'); row.className = 'sl-shipping-rate';",
        "        row.setAttribute('for', id);",
        "        var input = document.createElement('input');",
        "        input.type = 'radio'; input.name = 'sl-shipping-rate'; input.id = id;",
        "        input.value = option.service_token || '';",
        "        input.addEventListener('change', function(){ choose(input.value, option.amount); });",
        "        if (index === 0) { input.checked = true; choose(input.value, option.amount); }",
        "        var text = document.createElement('span'); text.className = 'sl-shipping-rate-text';",
        "        var label = document.createElement('strong'); label.className = 'sl-shipping-rate-label';",
        "        label.textContent = option.label || 'Shipping';",
        "        text.appendChild(label);",
        "        var days = estimateText(option);",
        "        if (days) {",
        "          var est = document.createElement('small'); est.className = 'sl-shipping-rate-estimate';",
        "          est.textContent = days; text.appendChild(est);",
        "        }",
        "        var price = document.createElement('span'); price.className = 'sl-shipping-rate-price';",
        "        price.textContent = option.amount ? money(option.amount) : 'Free';",
        "        row.appendChild(input); row.appendChild(text); row.appendChild(price);",
        "        rates.appendChild(row);",
        "      });",
        "    };",
        "    var estimateText = function(option){",
        "      var lo = option.transit_days_min, hi = option.transit_days_max;",
        "      if (lo == null && hi == null) return '';",
        "      if (lo != null && hi != null && lo !== hi) return 'Estimated ' + lo + '-' + hi + ' business days';",
        "      var one = lo != null ? lo : hi;",
        "      return 'Estimated ' + one + ' business day' + (one === 1 ? '' : 's');",
        "    };",
        "    var paint = function(data){",
        "      if (data === undefined) return;",                   # a stale answer; the buyer has moved on
        "      if (data === null) { say(reasons.carrier, 'error'); return; }",
        "      lastData = data;",
        "      if (!data.ships) return;",                          # nothing physical: stay hidden
        "      if (data.needs === 'zones' || data.needs === 'setup') return;",               # the tenant has configured nowhere to ship
        "      if (!select.options.length) {",
        # NAMES, NOT CODES. Two countries could wear their codes; a catch-all zone expands to 233, and
        # "AD / AE / AF" is not a list anyone can shop from. `Intl.DisplayNames` resolves them in the
        # BUYER's language with nothing shipped in the page -- the same call `dashboard/src/utils/
        # countries.js` makes, for the same reason: ~250 label strings nobody should hand-maintain.
        "        var NAMES = null;",
        "        try { NAMES = new Intl.DisplayNames(undefined, { type: 'region' }); } catch (e) { NAMES = null; }",
        "        var nameOf = function(code){",
        "          try { return (NAMES && NAMES.of(code)) || code; } catch (e) { return code; }",
        "        };",
        "        var add = function(code){",
        "          var opt = document.createElement('option');",
        "          opt.value = code; opt.textContent = nameOf(code);",
        "          select.appendChild(opt);",
        "        };",
        # The tenant's OWN destinations first, in the order they wrote them -- that order is a statement
        # about where they mainly sell, and burying the United States between Ukraine and Uruguay throws
        # it away. The catch-all's expansion follows, alphabetical by the name actually displayed, which
        # is why it is sorted here and not on the server: the server has codes and no locale.
        "        var all = data.countries || [];",
        "        var primary = (data.primary_countries || []).filter(function(c){ return all.indexOf(c) >= 0; });",
        "        primary.forEach(add);",
        "        var rest = all.filter(function(c){ return primary.indexOf(c) < 0; });",
        "        rest.sort(function(a, b){ return nameOf(a).localeCompare(nameOf(b)); });",
        "        if (primary.length && rest.length) {",
        "          var sep = document.createElement('option');",
        "          sep.disabled = true; sep.textContent = '\u2500\u2500\u2500';",
        "          select.appendChild(sep);",
        "        }",
        "        rest.forEach(add);",
        "        if (!select.options.length) return;",
        "      }",
        "      box.hidden = false;",
        "      var country = data.country || select.value || '';",
        "      window.__jbShipTo = country;",
        "      window.__jbShipQuote = data.quote_id || '';",
        "      postalLabel.textContent = POSTAL_LABEL[country] || 'Postal code';",
        "      var needsRegion = REGION_REQUIRED[country];",
        "      regionField.hidden = !needsRegion;",
        "      if (needsRegion) { regionLabel.textContent = needsRegion; }",
        "      if ((data.options || []).length) {",
        "        paintRates(data); say('', 'rates');",
        "      } else {",
        "        rates.innerHTML = ''; summary.hidden = true; choose('', null);",
        "        say(reasons[data.needs] || '', data.needs === 'carrier' ? 'error' : 'idle');",
        "      }",
        "      syncCta();",
        "    };",
        "    var run = function(){ say('Checking rates...', 'loading'); ask().then(paint); };",
        # Typing a postcode fires per keystroke; a carrier call per keystroke does not. Debounced, and
        # only once there is enough of a code to be worth asking about.
        "    var timer = null;",
        "    var runSoon = function(){",
        "      clearTimeout(timer);",
        "      timer = setTimeout(function(){ if (postal.value.trim().length >= 3) run(); }, 450);",
        "    };",
        "    ask().then(function(data){",
        "      paint(data);",
        "      if (data && data.ships && (data.countries || []).length && !data.country",
        "          && data.countries.length === 1) {",
        # One country is not a choice: settle it rather than making the buyer pick from a list of one.
        "        select.value = data.countries[0]; ask().then(paint);",
        "      }",
        "    });",
        "    select.addEventListener('change', run);",
        "    postal.addEventListener('input', runSoon);",
        "    region.addEventListener('input', runSoon);",
        "    retry.addEventListener('click', run);",
        # Adding or removing a cart line changes the parcel, so it changes the price. Without this the
        # quote stayed on whatever the cart held when the page loaded.
        "    document.addEventListener('sl:cart-changed', function(){ if (select.value) run(); });",
        # A tier change changes the parcel, so it changes the price -- AND it rebuilds the CTA href from
        # scratch, dropping the shipping params. Re-quoting puts them back, but asynchronously.
        "    document.addEventListener('click', function(event){",
        "      if (!event.target.closest || !event.target.closest('.sl-price-option')) return;",
        "      setTimeout(function(){ syncCta(); if (select.value) run(); }, 0);",
        "    });",
        # The belt to that braces: rewrite the link in the CAPTURE phase, before the CTA's own click
        # handler reads `cta.href`. Without this, a buyer who picks a tier and immediately hits Buy beats
        # the re-quote and checks out with no postage -- a race that would be rare, silent, and only ever
        # cost the tenant money.
        "    document.addEventListener('click', function(event){",
        "      if (event.target.closest && event.target.closest('.sl-cta, [data-checkout-base-url]')) syncCta();",
        "    }, true);",
        "  })();",
        "  </script>",
    ])


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
                # Carried so the markup can tell "this costs nothing" from "the buyer decides" -- both
                # arrive here as unit_amount 0, and only one of them may be quoted as a price.
                "pricing_model": str(price.get("pricing_model") or "one_time"),
            })
    return prices


_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def heading_outline_warnings(html: str, offer: dict[str, Any] | None = None) -> list[str]:
    """Page-health checks on the rendered document outline (plans/SEMANTIC_HTML.md, the quality baseline from
    plans/LANDING_PAGE_GOAL_COMPOSITION.md). Warnings, never gates — a correct outline (one H1, ordered
    H2/H3, no empty or skipped levels) is foundational for SEO, accessibility, and LLM parsing, and this
    catches regressions the renderer's by-construction guarantees don't.

    Validates the visible body only: `<head>` (meta/JSON-LD) carries no headings.

    The missing-H1 check does not apply to a LINK HUB. Its composition has no `hero`, so there is no headline
    element to add and no control that would silence the notice -- the tenant can only read it and be stuck.
    A notice needs an action the tenant must take, or it is noise that teaches them to ignore the panel. The
    page is also always noindex, so the SEO argument the check exists for has no purchase on it either. Every
    OTHER outline rule still applies: this suppresses one unactionable line, not the standard.
    """
    link_hub = bool(offer) and composition_key(offer) == "lead_social"
    body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
    headings = [
        (int(level), _TAG_RE.sub("", text).strip())
        for level, text in _HEADING_RE.findall(body)
    ]
    warnings: list[str] = []

    h1_count = sum(1 for level, _ in headings if level == 1)
    if h1_count == 0 and not link_hub:
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


def thin_content_warnings(html: str, offer: dict[str, Any] | None = None,
                          page: dict[str, Any] | None = None) -> list[str]:
    """Builder page-health nudge (SEO-08): a page below the unique-content floor is too thin to index, so tell
    the tenant what to add. Warning, never a gate — publishing is never blocked.

    Phrased CONDITIONALLY on purpose. The thin-content demotion in publishing.py only runs on an already
    indexable artifact — live mode, published, verified custom domain, eligible page_type. A test-mode or
    platform-hosted page is noindex for those reasons regardless of word count, so claiming the word count
    causes it would be false, and adding 200 words would not change anything the tenant can observe.

    EVERY LEAD SHAPE is skipped (author, 2026-09-10: "lead-gen pages don't care about word count"), and the
    bridge page shows why the conditional phrasing could not save them. Being short is the FORM of these pages,
    not a defect in them: a squeeze page converts by asking one thing, a click-to-call page puts a number above
    the fold, and a link hub is a list of links. Padding any of them to 150 words would damage the page to
    silence a notice. A warning has to name something the tenant can do AND should do.

    Checkout pages keep it. There, thin really is thin -- a product with no description is a page a crawler has
    no reason to rank, and adding one is work worth doing. A TIP JAR is not one of those: it has no product,
    so every remedy the notice offers is uncallable (author, 2026-09-14)."""
    from stripe_link.domain.composition import is_thin_by_design

    if offer is not None and is_thin_by_design(offer):
        return []
    count = indexable_word_count(html)
    if count >= THIN_CONTENT_MIN_WORDS:
        return []
    # The remedies have to be things THIS page can actually do. Three of the four below -- a product
    # description, a specifications table, condition details -- do not exist on a storefront, a category
    # page or a store profile, and that notice became reachable the moment those pages started opening in
    # the builder (plans/OFFERLESS_PAGES_IN_BUILDER.md P2). A notice naming remedies the tenant cannot take
    # reads as a dead end, which is the same defect as warning about correct behaviour.
    if page is not None and is_offerless_page(page):
        remedy = ("Add an intro paragraph about your store, a content block, or an FAQ to make it "
                  "eligible.")
    else:
        remedy = ("Add a product description, a specifications table, an FAQ, or condition details to "
                  "make it eligible.")
    return [
        f"This page has only about {count} words of unique content (under {THIN_CONTENT_MIN_WORDS}). On a "
        "verified custom domain that is too thin to index, so it would publish as noindex — hidden from "
        f"search — to protect your site's ranking. {remedy}"
    ]


def _catalog_markup_warnings(page: dict[str, Any]) -> list[str]:
    """What would keep an offer-less page's own markup from being emitted.

    Only things the tenant can act on. A store profile derives its Organization node from the Site's
    business profile, so the one thing that can be missing there is the business name; a catalog page's
    ItemList needs cards to list. Everything else about these pages is derived and cannot be wrong.
    """
    warnings: list[str] = []
    if offerless_composition(page) == "store_profile":
        if not str(_RENDER_ORG.get("name") or "").strip():
            warnings.append(
                "Your business has no name set, so this page cannot tell search engines who you are. "
                "Add one under Sites → business profile.")
        return warnings
    if not _grid_item_count(page):
        warnings.append(
            "This page's product grid is empty, so there is no catalogue for search engines to read. "
            "Publish some product pages on this Site and they will appear here.")
    return warnings


def structured_data_warnings(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
    page: dict[str, Any] | None = None,
) -> list[str]:
    """What is missing for this page's markup to earn a rich result.

    Warnings only, never a gate — the quality baseline is surfaced as nudges, never as a block on publishing
    (plans/LANDING_PAGE_GOAL_COMPOSITION.md). Thin markup isn't invalid, it just gets ignored by Google,
    which is exactly the failure a tenant can't see for themselves.

    An OFFER-LESS page is checked against what IT can emit, not against Product markup. Every check below
    reads a product this page does not have, and the first of them would have told the tenant of a
    storefront "No price is shown on this page, so no Product markup can be emitted." — which describes
    correct, intended behaviour and names nothing they could do about it. That notice was unreachable until
    these pages started opening in the builder (P2), so the exposure arrived with the fix
    (plans/OFFERLESS_PAGES_IN_BUILDER.md P4).
    """
    if page is not None and is_offerless_page(page):
        return _catalog_markup_warnings(page)
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
    every page, SEO-13) plus the primary menu. Rendered only when there's a home host; "" on a post-checkout
    page (a Home link would leak the buyer out) or when there's nothing to show.

    `has_brand_mark` means "this page's brand is already handled" -- either it renders its own mark, or the
    tenant has switched the brand OFF. Both must silence the header: a brand turned off is not a brand to be
    supplied from somewhere else in a different style. The header's brand is for pages that have neither --
    an offer-less storefront or category page, or one whose sections predate brand_label."""
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
    if not _RENDER_STATE.get("breadcrumb", True):
        return []   # composition says this shape has no hierarchy, or the tenant turned it off for this page
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
    offers_by_id: dict[str, dict[str, Any]] | None = None,
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
    # A CATALOG page (storefront / category) describes a list of other pages, not a product. product_json_ld
    # returns "" for it -- there are no prices to read -- which is why these pages emitted no markup at all
    # for the one thing they do contain (plans/OFFERLESS_PAGES_IN_BUILDER.md P4).
    collection_ld = collection_json_ld(page, offers_by_id or {}, composed_sections)
    if collection_ld:
        blocks.append(collection_ld)
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


def collection_json_ld(
    page: dict[str, Any],
    offers_by_id: dict[str, dict[str, Any]],
    composed_sections: list[dict[str, Any]],
) -> str:
    """ItemList markup for a catalog page's grid — the machine-readable form of the page's only content
    (plans/OFFERLESS_PAGES_IN_BUILDER.md P4).

    A storefront homepage and a category page ARE a list of links to other pages, and they emitted no
    structured data whatever: `product_json_ld` returns "" without prices, and the grid renderer emits none
    of its own. So the two page types that carry the catalogue were invisible to structured-data consumers
    while the store-profile page — which carries no products at all — emitted three node types.

    Each entry is a `ListItem` with a url and a name, and deliberately NOT a nested Product with an Offer.
    The listing page's job is to link; the full Product/Offer markup belongs on the product's own page,
    where it already is, and restating prices here would duplicate a claim in two places that can disagree.
    Names and urls are exactly what the cards show, which keeps the rule this file holds everywhere: markup
    describes what is on the page.

    Wrapped in a `CollectionPage` only when nothing else on the page already claims to be one.
    `render_seller_profile` emits its own `CollectionPage` (mainEntity: the Organization), so an about page
    that also carries a grid would otherwise publish two contradictory CollectionPage nodes for one URL.
    """
    home = (_RENDER_STATE.get("home_url") or "").rstrip("/")
    items: list[dict[str, Any]] = []
    for section in composed_sections:
        if not isinstance(section, dict) or section.get("type") != "catalog_grid":
            continue
        for entry in section.get("items") or []:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            linked = offers_by_id.get(str(entry.get("offer_id") or "")) or {}
            name = headline_plain_text(
                str((linked.get("presentation") or {}).get("headline") or linked.get("name") or "")
            ).strip()
            # No url means no card a crawler could follow, which is the same condition that makes
            # render_catalog_grid emit a plain tile instead of a link. An entry with nothing to point at
            # does not belong in an ItemList.
            if not (home and slug):
                continue
            node: dict[str, Any] = {
                "@type": "ListItem",
                "position": len(items) + 1,
                "url": f"{home}{slug if slug.startswith('/') else '/' + slug}",
            }
            if name:
                node["name"] = name
            items.append(node)
    if not items:
        return ""
    item_list = {"@type": "ItemList", "numberOfItems": len(items), "itemListElement": items}
    has_collection_page = any(
        isinstance(section, dict) and section.get("type") == "seller_profile"
        for section in composed_sections
    )
    if has_collection_page:
        return json_ld_dump({"@context": "https://schema.org", **item_list})
    canonical = _RENDER_STATE.get("canonical") or ""
    payload: dict[str, Any] = {"@context": "https://schema.org", "@type": "CollectionPage"}
    if canonical:
        payload["url"] = canonical
    name = str((page.get("seo") or {}).get("title") or "").strip()
    if name:
        payload["name"] = name
    payload["mainEntity"] = item_list
    return json_ld_dump(payload)


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


def render_reviews_section(section: dict[str, Any], offer: dict[str, Any],
                           products_by_id: dict[str, dict[str, Any]]) -> str:
    """The reviews block AS A SECTION, so the composer orders it with everything else.

    It used to be appended after the whole body, which is why it rendered BELOW the footer: `legal_footer`
    is a `pinned_bottom` element *inside* the body (reported 2026-10-15). Being a section is the fix, and
    it is also what lets a tenant move it and retitle it (plans/REVIEWS.md Phase 2.5).

    Visibility is the composer's business, not this function's -- `compose_page` has already decided
    whether this section is on the page by the time a renderer is called for it.
    """
    return render_reviews_block(offer, products_by_id, heading=str(section.get("heading") or ""))


def render_reviews_block(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]],
                         heading: str = "") -> str:
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
        f'      <h2 class="sl-section-heading">{escape(heading or "Customer reviews")}</h2>\n'
        f'{summary}\n'
        f'      <ul class="sl-reviews-list">{items}</ul>\n'
        '    </section>'
    )


def render_business_reviews_block(page: dict[str, Any] | None = None) -> str:
    """VISIBLE business-target reviews (what customers say about the store) — trust content only, NO
    AggregateRating markup (self-serving business ratings are suppressed by Google; plans/REVIEWS.md). Renders
    on any page of the business's Site. All approved render; no cherry-picking. Empty when there are none."""
    # NON-TRANSACTIONAL SURFACES ONLY (plans/REVIEWS.md "Where each kind of review surfaces"). These are
    # reviews of the FIRM, which carry no markup -- the self-serving rule -- so on a checkout page they sit
    # beside the one review set that can earn a snippet and compete with it for the same attention.
    #
    # Decided on the page being offerless, which is the question that actually separates the two kinds of
    # surface, rather than on offer_type: a storefront or profile page has no meaningful offer_type and
    # would fall back to `single`, withholding them from the one place they belong.
    if not is_offerless_page(page or {}):
        return ""
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

    NOT ON A PAGE THAT DOES NOT SELL. A lead shape excludes every price-bearing element by composition --
    `lead_roundup` names checkout_cta, offer_price_selector, price_highlight and product_details in its
    `excludes` precisely because "a price on the listing would be a second claim about money that can
    disagree with the one on the offer page". The offer still carries items and prices, so this function
    read one and published exactly that second claim, invisibly: a Roundup with no buy button anywhere on
    it emitted `Product` with `offers.price` and `availability: InStock`. That is the same fabricated claim
    the tip jar's `priceSpecification` exists to avoid, and it breaks the rule the rest of this file keeps
    -- markup describes what is on the page. A TIP JAR is deliberately not caught here: it takes money, so
    its markup should say so, and `is_lead_composition` is false for it.
    """
    if is_lead_composition(offer):
        return ""
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
    # Only when the visible block is on the page: the markup is a claim about text a reader can check, so
    # it goes when the text goes.
    product_reviews = (markup_eligible(_RENDER_REVIEWS.get(str(product.get("product_id") or "")) or [])
                       if _RENDER_STATE.get("reviews_visible") else [])
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
    if is_tip_price(selected):
        # A TIP JAR has no price to state, and stating the absent unit_amount would tell Google this is
        # free -- a fabricated claim, which is the one thing this markup may never carry. The honest shape
        # for "the buyer decides" is the RANGE they may decide within.
        offer_payload.pop("price")
        offer_payload["priceSpecification"] = {
            "@type": "PriceSpecification",
            "minPrice": money_string(TIP_MIN_AMOUNT),
            "maxPrice": money_string(TIP_MAX_AMOUNT),
            "priceCurrency": str(selected.get("currency") or "usd").upper(),
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
    # schema.org has ONE streetAddress, so a suite/unit joins the street line rather than being dropped.
    # Losing it would send a crawler an address a courier could not deliver to.
    street = ", ".join(part for part in (str(address.get("street") or "").strip(),
                                         str(address.get("street2") or "").strip()) if part)
    if street:
        node["streetAddress"] = street
    for source, target in (
        ("locality", "addressLocality"), ("region", "addressRegion"),
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
    same_as = verified_same_as_urls(organization)
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
            return {
                "unit_amount": int(price.get("unit_amount") or 0),
                "currency": price.get("currency") or "usd",
                "pricing_model": str(price.get("pricing_model") or "one_time"),
            }
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
# `small` is 800, not 640, and MUST match the ladder in image-processing/src/imageProcessorApp.js -- these
# numbers are the `w` descriptors in the srcset, so a mismatch tells the browser a file is a size it is not
# and it picks the wrong one. 800 exists so a phone (412 CSS px at DPR 1.75 ~ 721px) stops being served the
# 1080 file; 1080 stays so a DPR-1 desktop does not jump to 1920.
# `thumb` is NOT here, and that is the point: it is a different CROP, not a different size. The processor
# builds it `fit: "cover"` at 200x200 while every other rung is `fit: "inside"` and keeps the source's
# aspect -- measured on a real asset: thumb 200x200 (1.000) against small 493x800 (0.616).
#
# A srcset's candidates must be interchangeable renderings of ONE image; the browser may pick any of them.
# While `object-fit:cover` was doing the framing, picking the square thumb was invisible. The moment a
# surface applied a CSS CROP -- which sets explicit width and height computed from the source's aspect --
# the square got stretched to those dimensions and the author's photo came out visibly bent (2026-10-12).
#
# A square thumbnail is still a perfectly good thing to ASK for by name; it is just not a resolution step.
IMAGE_RENDITION_WIDTHS = {"small": 800, "medium": 1080, "large": 1920, "full": 2560}
THUMB_RENDITION = "thumb"
# `original` is listed alongside the sized renditions on purpose. When an upload stores the ORIGINAL url
# rather than a rendition, this regex used to miss, responsive_img fell through to its plain-tag branch, and
# the page shipped the full-size source with no srcset -- a 2000px 250KB PNG where a 12KB small.webp existed
# for the same asset. It is NOT in IMAGE_RENDITION_WIDTHS, so it never appears in the srcset itself; it only
# lets the base be recovered so the real renditions can be offered.
#
# The extension list keeps this to images: `original.mp4` deliberately does not match, because a video has no
# webp renditions to point at.
_RENDITION_URL_RE = re.compile(
    r"^(?P<base>.+)/(?:thumb|small|medium|large|full|original)\.(?:webp|jpe?g|png)$", re.IGNORECASE
)


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
_RENDER_EVENTS: dict[str, dict[str, Any]] = {}


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


_RENDER_ALTS_INDEX: dict[str, str] = {}

# The tenant's own preferences for this render. Render-scoped like the two indexes above, so the font
# resolution can reach them without threading `preferences` through _render_page_body, render_template_styles
# and every head-channel helper in between. A PAGE override still beats whatever is in here -- resolve_families
# applies the tenant default first and lets the page win, which is the whole point of the four levels.
_RENDER_PREFERENCES: dict[str, Any] = {}


def render_preferences(explicit: dict[str, Any] | None = None) -> dict[str, Any]:
    """The preferences to resolve fonts against: an explicit argument, else this render's."""
    return explicit if explicit is not None else _RENDER_PREFERENCES


def collect_image_alts(*documents: dict[str, Any] | None) -> dict[str, str]:
    """Merge the image_alts sidecars of every supplied document into one base -> alt map.

    Same keying as collect_image_dims: rendition bases are globally unique, so merging across
    page/offer/products/services is conflict-free. Blank entries are dropped rather than stored, so an
    empty description behaves as "no override" instead of blanking an alt the renderer would otherwise
    derive -- an empty alt on a content image is exactly what accessibility_warnings flags.
    """
    merged: dict[str, str] = {}
    for document in documents:
        alts = (document or {}).get("image_alts")
        if not isinstance(alts, dict):
            continue
        for key, text in alts.items():
            if not isinstance(text, str) or not text.strip():
                continue
            base = rendition_base(str(key)) or str(key)
            merged[base] = text.strip()
    return merged


def described_alt(url: str, fallback: str) -> str:
    """The tenant's own description of this asset, else whatever the call site derived.

    The sidecar WINS: a description typed against the image is more specific than a name borrowed from
    the surrounding product or block, which is how alt text was produced before this existed. Absent or
    blank, nothing changes -- every call site keeps the fallback it always passed.
    """
    base = rendition_base(url) or url
    return _RENDER_ALTS_INDEX.get(base) or fallback


# A CROP STATES ITS OWN SIZE. The processor writes `<base>custom_<w>x<h>_<suffix>.<ext>`
# (image-processing/src/onDemandResize.js), so the output dimensions are in the filename and need no
# sidecar at all. `rendition_base` does not match these -- its pattern is the fixed rendition names --
# so a cropped image fell through to a full-URL sidecar lookup that nothing ever writes, and published
# with no width/height. On a Roundup that is every entry picture, because an entry crops to a square.
_CROP_URL_RE = re.compile(r"/custom_(?P<w>\d{1,5})x(?P<h>\d{1,5})_[^/]*\.(?:webp|jpe?g|png)$", re.IGNORECASE)


def crop_url_dims(url: str) -> tuple[int, int] | None:
    """(width, height) read off a processor crop URL, or None when it is not one."""
    match = _CROP_URL_RE.search(str(url or ""))
    if not match:
        return None
    width, height = int(match.group("w")), int(match.group("h"))
    return (width, height) if width > 0 and height > 0 else None


def _resolved_dims(url: str, dims: tuple[int, int] | None) -> tuple[int, int] | None:
    """This image's intrinsic size: an explicit override, else the sidecar, else the crop's own filename.

    The sidecar WINS over the filename. It is measured from the asset, while the filename states what
    the crop was ASKED for -- the same answer in every case we know of, and the measured one is the one
    to trust if they ever disagree.
    """
    if dims:
        return dims
    # Rendition URLs key by their shared base; external/custom URLs key by the full URL (that is how
    # collect_image_dims normalizes them), so a non-rendition image can still carry dimensions.
    base = rendition_base(url)
    found = _RENDER_DIMS_INDEX.get(base) if base else _RENDER_DIMS_INDEX.get(url)
    return found or crop_url_dims(url)


def _dims_attrs(url: str, dims: tuple[int, int] | None) -> str:
    """width/height attributes for an <img>, from an explicit override or the render-scoped index.

    The pair encodes the intrinsic aspect ratio; the browser reserves layout space from it (no CLS)
    while CSS still governs the displayed size. Where CSS pins aspect-ratio (object-fit:cover slots)
    the attributes only inform crawlers; where it does not (listicle contain slots) they reserve the
    box. Absent dimensions emit nothing — identical to prior behavior.
    """
    dims = _resolved_dims(url, dims)
    if not dims:
        return ""
    return f' width="{int(dims[0])}" height="{int(dims[1])}"'


def _source_long_edge(url: str, dims: tuple[int, int] | None) -> int:
    """The source image's long edge, from the image_dims sidecar. 0 when unknown."""
    if dims is None:
        base = rendition_base(url)
        dims = _RENDER_DIMS_INDEX.get(base) if base else _RENDER_DIMS_INDEX.get(url)
    if not dims:
        return 0
    try:
        return max(int(dims[0]), int(dims[1]))
    except (TypeError, ValueError, IndexError):
        return 0


def available_renditions(long_edge: int) -> list[str]:
    """Which renditions may be named in a srcset for a source whose long edge is `long_edge`.

    Two problems, one rule. The processor does not emit a distinct file for every nominal size: it clamps
    each target to the source and skips a size that collapses onto the previous one, so a 225px upload has
    thumb and small and NOTHING above them. Naming medium/large/full for that asset gives the browser three
    URLs that 403, and the <img> renders broken even though the file it was given is fine -- reported
    2026-09-09 on a link card whose small.webp loaded perfectly in the address bar.

    The rule is not "guess what the processor emitted" -- that depends on upscale settings this module
    cannot see, and guessing wrong reintroduces the 403. It is: NEVER NAME A RENDITION WIDER THAN THE
    SOURCE. Those can only ever be upscales, so they cost bytes and carry no extra detail; excluding them
    is the right call even where the file does happen to exist.

    thumb and small are always safe: the processor emits the smallest ladder entry unconditionally, clamped
    to the source.

    With no dimensions we cannot reason at all, so nothing changes -- the full ladder, exactly as before.
    Legacy images predate the sidecar and mostly come from large sources, and breaking them to fix a case
    we cannot detect would trade a known-good for a guess.
    """
    if long_edge <= 0:
        return list(IMAGE_RENDITION_WIDTHS)
    ladder = [size for size, width in IMAGE_RENDITION_WIDTHS.items()
              if size in ("thumb", "small") or width <= long_edge]
    return ladder or ["thumb"]


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
    # One lookup HERE covers every surface -- present and future -- instead of fourteen call sites each
    # having to remember a sidecar they do not know about.
    alt_attr = escape(str(described_alt(url, str(alt or ""))))
    loading = "eager" if eager else "lazy"
    priority = ' fetchpriority="high"' if eager else ""
    dims_attrs = _dims_attrs(url, dims)
    match = _RENDITION_URL_RE.match(url)
    if not match:
        return f'<img src="{escape(url)}" alt="{alt_attr}"{dims_attrs} loading="{loading}" decoding="async"{priority}>'
    base = match.group("base")
    ladder = available_renditions(_source_long_edge(url, dims))
    srcset = ", ".join(
        f"{escape(f'{base}/{size}.webp')} {IMAGE_RENDITION_WIDTHS[size]}w"
        for size in ladder
    )
    # Prefer medium as the plain `src` (what a no-srcset client gets, and the default candidate), but never
    # name a rendition the ladder excluded -- that is exactly the 403 this guards against.
    fallback = "medium" if "medium" in ladder else ladder[-1]
    return (
        f'<img src="{escape(f"{base}/{fallback}.webp")}" srcset="{srcset}" sizes="{escape(sizes)}" '
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
    section_id = str(section.get("id", "faq"))
    # ONE OPEN AT A TIME, by the browser rather than by us. A shared `name` on <details> makes an exclusive
    # accordion natively: opening one closes its siblings, the toggle still closes the open one, and the
    # keyboard behaviour is the browser's own. A JS version would re-implement all of that and only run
    # once the script had.
    #
    # Default ON, and absent counts as on, so a page republished after this gains it without being edited.
    # A browser without exclusive <details> simply keeps today's behaviour -- every panel independent --
    # which is a degradation nobody can be harmed by.
    exclusive = section.get("one_at_a_time") is not False
    # Scoped to the section so two FAQ blocks on one page could never fight over the same group.
    name_attr = f' name="faq-{escape(section_id)}"' if exclusive else ""
    rendered = [
        "\n".join([
            f"      <details{name_attr}>",
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
        f"    <section class=\"sl-faq\" data-section-id=\"{escape(section_id)}\" data-section-type=\"faq\">",
        f"      <h2 class=\"sl-faq-heading\">{escape(heading)}</h2>",
        *rendered,
        "    </section>",
    ])


def render_content_blocks(section: dict[str, Any]) -> str:
    blocks = section.get("blocks") or []
    rendered = []
    for block in blocks:
        image_url = block.get("image_url")
        title = str(block.get("title") or "").strip()
        rendered.append("\n".join(row for row in [
            "      <article class=\"sl-content-block\">",
            "        <div>",
            # No title means NO <h2>, not an empty one: a heading with nothing in it is a hole in the
            # page's outline (plans/SEMANTIC_HTML.md) and reads as a blank line to a screen reader.
            f"          <h2>{render_headline_markup(title)}</h2>" if title else "",
            render_body_markup(block.get("text"), "", "          "),
            "        </div>",
            "        " + cropped_media(
                responsive_img(image_url, str(block.get("title") or "Content image"), sizes=CONTENT_BLOCK_SIZES),
                block.get("image_crop"), "content_block", "sl-content-media",
            ) if image_url else "",
            "      </article>",
        ] if row))   # an absent title or image contributes "", which would otherwise leave a blank line
    if not rendered:
        return ""
    centered = " sl-content-blocks--centered" if section.get("centered") else ""
    divided = " sl-content-blocks--divided" if section.get("divider") else ""
    return "\n".join([
        f"    <section class=\"sl-content-blocks{centered}{divided}\" data-section-id=\"{escape(str(section.get('id', 'content-blocks')))}\" data-section-type=\"content_block\">",
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


def render_shipping_eta(section: dict[str, Any]) -> str:
    """When the parcel is due — the first thing after the headline on a physical order's thank-you page.

    plans/THANK_YOU_PAGE.md P2. The page is a static artifact serving every buyer, so the DATE cannot be
    baked in: the shell renders with a neutral line and an island fills it from the order behind the
    `session_id` already in the URL.

    That shell is deliberately truthful on its own. A buyer whose JavaScript never runs reads "we'll email
    tracking details" — not a date nobody computed for them, and not the "Free Shipping / arrives within
    5–7 business days" that this element exists to delete.

    The tenant owns the icon and the title. The body is generated, which is the point: a sentence nobody
    can type is a sentence that cannot claim free shipping on an order that paid $39.59.
    """
    title = str(section.get("title") or "Shipping").strip()
    icon = str(section.get("icon") or "").strip()
    icon_html = f'<span class="sl-ship-eta-icon">{escape(icon)}</span>' if icon and icon != "\u2014" else ""
    # What a BUILDER PREVIEW shows, where there is no order to ask about. Marked as an example, or the
    # first thing every tenant does is report the page as broken.
    example = str(section.get("example") or "").strip()
    sentence = example or "We'll email tracking details as soon as it ships."
    section_id = escape(str(section.get("id", "shipping-eta")))
    api_base = escape(str(_RENDER_STATE.get("api_base_url") or ""))
    tenant_id = escape(str(_RENDER_STATE.get("tenant_id") or ""))
    parts = [
        f'    <section class="sl-ship-eta" data-section-id="{section_id}" data-section-type="shipping_eta"'
        f' data-api-base-url="{api_base}" data-tenant-id="{tenant_id}">',
        '      <div class="sl-ship-eta-card">',
        f"        {icon_html}" if icon_html else "",
        f"        <strong>{escape(title)}</strong>",
        f'        <p class="sl-ship-eta-line">{escape(sentence)}</p>',
        ('        <p class="sl-ship-eta-note">Example &mdash; your buyers see their own date.</p>'
         if example else ""),
        "      </div>",
        "    </section>",
        _shipping_eta_island() if not example else "",
    ]
    return "\n".join(part for part in parts if part)


def _shipping_eta_island() -> str:
    """Fill the element, and any `{{arrival}}` in the cards below it, from the order behind `session_id`.

    **One fetch, two consumers.** The element's sentence and the token in a tenant's own card are the same
    promise worded differently, so they must come from the same response -- two requests could disagree,
    and a date that disagrees with itself on one page is worse than no date.

    **Removes the element when there is no parcel.** Only the ORDER knows whether anything ships, and this
    page is one artifact serving every buyer, so the decision cannot be made at render time. A digital
    order gets `{}` back and the element deletes itself rather than reassuring someone about a delivery
    they are not expecting.

    Silent on failure: the shell's own line already says tracking is coming, which is true whatever
    happened to the request.
    """
    return "\n".join([
        "    <script>",
        "    (function(){",
        "      var box = document.querySelector('.sl-ship-eta');",
        "      if (!box) return;",
        "      var api = box.dataset.apiBaseUrl || '';",
        "      var tenant = box.dataset.tenantId || '';",
        "      var session = new URLSearchParams(window.location.search).get('session_id') || '';",
        # No session means a preview or a direct visit: leave the honest shell alone rather than asking
        # about an order that does not exist.
        "      if (!api || !tenant || !session) return;",
        "      var tokens = function(text, phrase){ return String(text).split('{{arrival}}').join(phrase); };",
        "      fetch(api.replace(/\\/$/, '') + '/upsell/session?session_id=' + encodeURIComponent(session)",
        "            + '&clientID=' + encodeURIComponent(tenant))",
        "        .then(function(r){ return r.json(); })",
        "        .then(function(body){",
        "          var promise = (body && body.delivery) || null;",
        # `{}` is a real answer: this order has no parcel, so the element must go rather than linger --
        # AND so must any card whose text depends on an arrival date. Returning here left
        # "Your order is expected to arrive {{arrival}}." on screen with the token unsubstituted, which
        # a buyer of a digital product saw on a live purchase (2026-10-09). A card that needs a delivery
        # date is a shipping card whatever it is titled; substituting a vague phrase would still leave
        # "Wait for Your Package" above a download.
        "          if (!promise || !Object.keys(promise).length) {",
        "            box.remove();",
        "            Array.prototype.forEach.call(document.querySelectorAll('.sl-next-step'), function(card){",
        "              var p = card.querySelector('p');",
        "              if (p && p.textContent.indexOf('{{arrival}}') >= 0) card.remove();",
        "            });",
        "            return;",
        "          }",
        "          var line = box.querySelector('.sl-ship-eta-line');",
        "          if (line && promise.sentence) { line.textContent = promise.sentence; }",
        "          if (promise.service) {",
        "            var svc = document.createElement('p');",
        "            svc.className = 'sl-ship-eta-service';",
        "            svc.textContent = promise.service;",
        "            box.querySelector('.sl-ship-eta-card').appendChild(svc);",
        "          }",
        # The SAME promise, worded by the tenant. Substituted after the element so both land together or
        # neither does.
        "          var phrase = promise.arrival_phrase || '';",
        "          if (!phrase) return;",
        "          Array.prototype.forEach.call(document.querySelectorAll('.sl-next-step p'), function(el){",
        "            if (el.textContent.indexOf('{{arrival}}') >= 0) el.textContent = tokens(el.textContent, phrase);",
        "          });",
        "        })",
        "        .catch(function(){});",
        "    })();",
        "    </script>",
    ])


def render_digital_download(section: dict[str, Any]) -> str:
    """The file this buyer just paid for, on the thank-you page.

    **Starts hidden and fills itself in.** The link is purchase-verified -- it exists only once there is a
    paid order to verify -- and this page is one published artifact serving every buyer, so the URL cannot
    be baked in at render time. Unlike the shipping element there is no honest fallback sentence to leave on
    screen: "your download is ready" above no link is a broken promise, so nothing shows until the server
    has answered, and the element removes itself when the answer is that this order has no file.

    The builder gets a marked example instead, because the Live Preview has no order to ask about and a
    tenant who cannot see the element cannot know their buyers get one.
    """
    title = str(section.get("title") or "").strip() or "Your download is ready"
    example = str(section.get("example") or "").strip()
    section_id = escape(str(section.get("id", "digital-download")))
    api_base = escape(str(_RENDER_STATE.get("api_base_url") or ""))
    tenant_id = escape(str(_RENDER_STATE.get("tenant_id") or ""))
    parts = [
        f'    <section class="sl-ty-dl" data-section-id="{section_id}" data-section-type="digital_download"'
        f' data-api-base-url="{api_base}" data-tenant-id="{tenant_id}"'
        + ("" if example else " hidden") + ">",
        '      <div class="sl-ty-dl-card">',
        '        <span class="sl-ty-dl-icon" aria-hidden="true">\u2b07\ufe0f</span>',
        f"        <strong>{escape(title)}</strong>",
        (f'        <p class="sl-ty-dl-file">{escape(example)}</p>' if example else
         '        <p class="sl-ty-dl-file"></p>'),
        ('        <span class="sl-cta sl-ty-download">Download</span>' if example else
         '        <a class="sl-cta sl-ty-download" href="#" download>Download</a>'),
        ('        <p class="sl-ty-dl-note">Example &mdash; your buyers get their own purchase-verified link.</p>'
         if example else
         '        <p class="sl-ty-dl-note">We\u2019ve emailed this link to you as well.</p>'),
        "      </div>",
        "    </section>",
        _digital_download_island() if not example else "",
    ]
    return "\n".join(part for part in parts if part)


def _digital_download_island() -> str:
    """Ask the order behind `session_id` for its file, then reveal the element or remove it.

    The SAME endpoint and the same `session_id` the shipping element already uses -- one fetch per concern
    rather than one route per concern, because the stack is at CloudFormation's transform limit.

    The URL it is handed is the purchase-verified `/download` link, not the file: clicking it re-checks the
    order server-side, so a link scraped off this page is worth no more than the order behind it.
    """
    return "\n".join([
        "    <script>",
        "    (function(){",
        "      var box = document.querySelector('.sl-ty-dl');",
        "      if (!box) return;",
        "      var api = box.dataset.apiBaseUrl || '';",
        "      var tenant = box.dataset.tenantId || '';",
        "      var session = new URLSearchParams(window.location.search).get('session_id') || '';",
        # No session means a direct visit: there is no order to verify, so there is no link to offer.
        "      if (!api || !tenant || !session) { box.remove(); return; }",
        "      fetch(api.replace(/\\/$/, '') + '/upsell/session?session_id=' + encodeURIComponent(session)",
        "            + '&clientID=' + encodeURIComponent(tenant))",
        "        .then(function(r){ return r.json(); })",
        "        .then(function(body){",
        "          var file = (body && body.download) || null;",
        "          if (!file || !file.url) { box.remove(); return; }",
        "          var link = box.querySelector('.sl-ty-download');",
        "          var name = box.querySelector('.sl-ty-dl-file');",
        "          if (name && file.filename) { name.textContent = file.filename; }",
        "          if (link) { link.setAttribute('href', file.url); }",
        "          box.removeAttribute('hidden');",
        "        })",
        # Removed rather than left hidden: a failed fetch is still no verified link, and the receipt email
        # carries the same one, so the buyer is not stranded.
        "        .catch(function(){ box.remove(); });",
        "    })();",
        "    </script>",
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


# No "download": a CTA type is what a BUTTON does, and the only thing that ever produced one was an
# extension sniff on a bridge page's destination (removed 2026-09-17). File delivery is the page
# ribbon's download action, backed by an uploaded asset rather than a guess about a URL.
CTA_TYPES = {"buy", "call", "email", "external", "booking", "appointment"}


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
            f"          <blockquote>\n{render_body_markup(quote, '', '            ')}\n          </blockquote>",
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


# A perforated ticket, drawn rather than fetched: an inline SVG cannot fail to load, needs no CDN the
# artifact CSP would block, and inherits currentColor so the applied state colours it in one place.
COUPON_APPLIED_MARK = (
    '<svg class="sl-coupon-applied-mark" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 9V7a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v2a2 2 0 0 0 0 4v2a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-2a2 2 0 0 0 0-4Z"/>'
    '<path d="m9 12 2 2 4-4"/></svg>'
)


def coupon_is_live(section: dict[str, Any], now: int | None = None) -> bool:
    """Whether this coupon can still be redeemed. An absent expiry means it does not expire."""
    expires_at = section.get("expires_at")
    try:
        expires_at = int(expires_at) if expires_at not in (None, "") else 0
    except (TypeError, ValueError):
        return True
    if expires_at <= 0:
        return True
    return int(now if now is not None else time.time()) < expires_at


# The five coupon looks. `modern` is the default for new and unstated sections.
COUPON_STYLES = ("modern", "minimalist", "ribbon", "bold", "dark")


def render_coupon(
    section: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]] | None = None,
    checkout_url: str = "",
    now: int | None = None,
    page: dict[str, Any] | None = None,
    resolved_offer: dict[str, Any] | None = None,
) -> str:
    """The campaign coupon: a ticket the visitor arrived for, and can click.

    Layout follows the paper coupons it imitates: the PICTURE of what you get on the left, the VALUE large
    on the right, and the business named above it so the ticket says whose it is. A coupon that does not
    name its business is a voucher for nowhere -- it is the first thing a recipient checks.

    The WHOLE ticket is the click target, not a button inside it. Someone who tapped a coupon in an email
    expects to tap the same thing again, and a coupon with a small button beside it makes them hunt for the
    part that works.

    Smart by the offer's own shape rather than a setting the tenant can get wrong:
      * a transacting offer -> the ticket carries the code INTO checkout, so the discount is already applied
        when they arrive and they never retype it
      * a lead offer (which by composition HAS no checkout) -> the ticket links to the destination named on
        the section, which is what a bridge page does with its redirect anyway

    Text values are DENORMALIZED onto the section when the tenant picks a coupon in the builder, not looked
    up here: a published artifact has to be self-contained, and a renderer that queried the coupon table
    would make every page render depend on it. The IMAGE falls back to the offer's own product picture, so
    a tenant who picks a coupon and nothing else still gets a ticket that looks like something.
    """
    code = str(section.get("code") or "").strip()
    if not code:
        return ""

    live = coupon_is_live(section, now)
    value_text = str(section.get("value_text") or "").strip()
    headline = str(section.get("headline") or "").strip()
    terms = str(section.get("terms") or "").strip()
    business = str(section.get("business_name") or "").strip() or resolve_business_name()
    # "Click to redeem" rather than "Redeem": the ticket no longer navigates, it applies in place, and a
    # label that names the gesture is what tells a visitor the whole coupon is the control (author,
    # 2026-09-22). A tenant's own cta_label still wins.
    cta_label = str(
        section.get("cta_label") or ("Click to redeem this offer" if live else "This offer has ended")
    ).strip()

    # The tenant SAYS which picture, rather than a fallback chain deciding for them. It used to walk
    # image_url -> the offer's product photo -> the platform favicon, which meant a coupon always had an
    # image and there was no way to say "none" -- reported 2026-10-15 as "no way to get rid of the default
    # image", and there was no way to upload one either.
    #
    # Absent means NONE, deliberately: the complaint was about an image nobody asked for, so a coupon that
    # never chose one stops having one at its next publish.
    source = str(section.get("image_source") or "none").strip().lower()
    image = ""
    crop = None
    if source == "upload":
        image = str(section.get("image_url") or "").strip()
        crop = section.get("image_crop")
    elif source == "hero":
        # The page's own hero, resolved the SAME way the hero renders it, so the two cannot disagree about
        # which picture the page leads with.
        hero_section = next((row for row in ((page or {}).get("sections") or [])
                             if isinstance(row, dict) and row.get("type") == "hero_media"), {})
        hero_product = first_offer_product(offer or {}, products_by_id or {})
        hero_images = hero_media_images(hero_section, offer or {}, hero_product)
        image = str(next((row for row in hero_images if row), "") or "").strip()
    # Kept for the one case where a picture is a MARK rather than a photograph: a square logo contained and
    # padded instead of cropped to fill. Nothing reaches it now that the favicon fallback is gone, and it
    # stays because the layout branch below still reads it.
    is_logo = False

    transacts = not composition_key(offer or {}).startswith("lead_")
    if not live:
        href = ""
    elif transacts:
        href = coupon_checkout_href(checkout_url, code, page, offer, resolved_offer)
    else:
        href = str(section.get("destination_url") or "").strip()

    expiry_line = ""
    expires_at = section.get("expires_at")
    if expires_at:
        try:
            stamp = datetime.fromtimestamp(int(expires_at), tz=timezone.utc).strftime("%b %-d, %Y")
        except (TypeError, ValueError, OSError):
            stamp = ""
        if stamp:
            expiry_line = f'        <p class="sl-coupon-expiry">{"Expires" if live else "Expired"} {escape(stamp)}</p>'

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    # Which of the five looks. One markup shape, five stylesheets — the renderer stays a renderer, and a
    # new look is a CSS question rather than a new branch here. Absent means `modern` (author, 2026-10-15).
    coupon_style = str(section.get("style") or "modern").strip().lower()
    if coupon_style not in COUPON_STYLES:
        coupon_style = "modern"
    style_attr += f' data-coupon-style="{escape(coupon_style)}"' 
    themed = " sl-section-themed" if style else ""
    section_id = escape(str(section.get("id", "coupon")))
    state = "" if live else " sl-coupon-expired"
    # No picture -> no empty panel. The ticket becomes a single column and the value still leads.
    layout = "" if image else " sl-coupon-noimage"

    media = ""
    if image:
        # A decorative logo carries no information the text does not, so it gets an EMPTY alt rather than a
        # description a screen reader would read out before the offer itself.
        alt = "" if is_logo else escape(headline or business or "Offer")
        logo_class = " sl-coupon-media-logo" if is_logo else ""
        # Through the shared cropper like every other croppable surface, so the class, the custom
        # properties and the "no crop means no extra markup" rule are decided in one place.
        media = "      " + cropped_media(
            f'<img src="{escape(image)}" alt="{alt}" loading="lazy" decoding="async">',
            crop, "coupon", f"sl-coupon-media{logo_class}",
        )

    body = [
        media,
        '      <div class="sl-coupon-body">',
        f'        <p class="sl-coupon-brand">{escape(business)}</p>' if business else "",
        f'        <p class="sl-coupon-headline">{render_headline_markup(headline)}</p>' if headline else "",
        f'        <p class="sl-coupon-value">{escape(value_text)}</p>' if value_text else "",
        '        <p class="sl-coupon-code-row"><span class="sl-coupon-code-label">Code</span>'
        f'<span class="sl-coupon-code">{escape(code)}</span></p>',
        expiry_line,
        f'        <p class="sl-coupon-terms">{escape(terms)}</p>' if terms else "",
        f'        <span class="sl-coupon-cta">{escape(cta_label)}</span>',
        # Rendered but hidden, and revealed by the page script when the visitor applies it. In the markup
        # rather than built in JS so a crawler and a no-JS visitor still see honest, complete copy, and so
        # the wording lives with the rest of the element instead of inside a string in the runtime.
        '        <span class="sl-coupon-applied" hidden>',
        f'          {COUPON_APPLIED_MARK}',
        '          <span class="sl-coupon-applied-text">Coupon Applied'
        '<small>Your discount will appear at checkout</small></span>',
        "        </span>",
        "      </div>",
    ]
    inner = "\n".join(line for line in body if line)

    # An expired coupon still RENDERS -- an email campaign outlives its deadline and the visitor deserves to
    # be told, not dropped on a page with a hole in it or sent to a checkout that refuses them.
    if href:
        # Still an anchor, and still pointing at a working checkout: the script intercepts the click and
        # applies instead, so a visitor without JS gets the old behaviour rather than a dead ticket.
        opener = (f'    <a class="sl-coupon{layout}{state}{themed}" href="{escape(href)}"'
                  f' data-section-id="{section_id}" data-section-type="coupon"'
                  f' data-coupon-code="{escape(code)}"'
                  f' data-coupon-grant-prefix="{escape(grant_prefix(code))}"{style_attr}>')
        closer = "    </a>"
    else:
        opener = (f'    <div class="sl-coupon{layout}{state}{themed}"'
                  f' data-section-id="{section_id}" data-section-type="coupon"{style_attr}>')
        closer = "    </div>"
    return "\n".join([opener, inner, closer])


def coupon_checkout_href(checkout_url: str, code: str, page=None, offer=None, resolved_offer=None) -> str:
    """Checkout with the promotion code already on it, so the discount is applied before the buyer looks.

    Built through `checkout_context`, the same thing the Buy button uses, rather than by appending to the
    base URL: that URL carries no tenant, offer or price, so a hand-made link reached checkout as
    "clientID or tenant_id is required" (found 2026-09-22). One builder means the coupon link cannot drift
    from the button beside it.
    """
    checkout_url = str(checkout_url or "").strip()
    if not checkout_url:
        return ""
    href = checkout_context(page or {}, offer or {}, resolved_offer or offer or {}, checkout_url).get("href") or ""
    if not href or href == "#checkout":
        return ""
    joiner = "&" if "?" in href else "?"
    return f"{href}{joiner}coupon={quote(code)}"


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
        rows.append(render_body_markup(body, "sl-author-body", "      "))

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
# The subset a catalog entry may wear. `centered` is the ribbon's no-image presentation, and an entry in a
# product listing exists to show the product -- see render_catalog_grid.
ENTRY_RIBBON_PRESENTATIONS = ("image_left", "compact")
RIBBON_PURPOSES = ("promote_offer", "capture_lead", "promote_content", "custom")
# Named after the existing action vocabulary (CTA_TO_ACTION below) rather than a new set of words for the
# same ideas. `none` is explicit: a ribbon with nothing to click is a content block, and should say so.
# `promote_page` is a redirect whose target the BUILDER resolves from the tenant's own page list, so the
# renderer treats it identically — the difference is where the URL comes from, not what happens on click.
RIBBON_ACTIONS = ("redirect", "promote_page", "download", "email_file", "call_phone", "email",
                  "cta", "none")
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


def lead_form_is_open(offer: dict[str, Any] | None,
                      products_by_id: dict[str, dict[str, Any]] | None) -> bool:
    """Is there a registration form to open at all?

    An offer with no scheduled event always has one. An event-backed offer has one only while a sitting is
    open: during the session the page pushes the join link instead, and afterwards it shows the closed
    notice. Resolved with the SAME `first_offer_lead_capture` / `event_open_occurrences` the CTA uses, so
    every ask on the page turns off together instead of each forming its own opinion
    (plans/RIBBON_ACTIONS.md §7).
    """
    capture = first_offer_lead_capture(offer or {}, products_by_id or {}) or {}
    event_id = str(capture.get("event_id") or "")
    scheduled = _RENDER_EVENTS.get(event_id) if event_id else None
    if scheduled is None:
        return True
    now_epoch = int(time.time())
    if event_live_occurrence(scheduled, now=now_epoch) is not None:
        return False
    return bool(event_open_occurrences(scheduled, now=now_epoch))


def lead_dialog_enabled(page: dict[str, Any] | None) -> bool:
    """Does this page's lead CTA open from a button? Read from the page's own sections, so the answer does
    not depend on which element the renderer happens to reach first."""
    for section in ((page or {}).get("sections") or []):
        if isinstance(section, dict) and section.get("type") == "checkout_cta":
            return str(section.get("form_presentation") or "inline").strip().lower() == "dialog"
    return False


def page_ask_attrs(page: dict[str, Any] | None, offer: dict[str, Any] | None,
                   resolved_offer: dict[str, Any] | None, checkout_url: str | None,
                   api_base_url: str | None,
                   products_by_id: dict[str, dict[str, Any]] | None = None) -> tuple[str, str] | None:
    """`(tag_open_attrs, element)` for a button that does what the page's own CTA does, or None.

    THE point of this function is that there is one of it. `render_buy_cta` resolves the price, the Stripe
    mode, the coupon, the cart endpoint, the post-purchase funnel and the BNPL methods into its button; a
    second emitter that re-derived any of that would disagree the first time one changed -- a stale price on
    one button, a bypassed upsell funnel on the other. "Acts exactly like the page's CTA" has to mean the
    same code, not similar code (plans/RIBBON_ACTIONS.md §7).

    Returns None when the page has no repeatable ask: a lead page whose form is shown inline has nothing to
    open, and a closed event has nothing to offer at all. The caller then renders no button, which is the
    honest outcome -- an ask that cannot be honoured is worse than no ask.
    """
    if not offer:
        return None
    if str(offer.get("product_intent") or "") == "lead_gen":
        # A lead page in dialog mode: every ask opens the ONE form. Read from the PAGE rather than from a
        # flag the CTA sets while rendering, because a tenant may drag a ribbon ABOVE the CTA and then the
        # flag would not be set yet -- the ribbon would silently lose its button depending on where it sat.
        if not lead_dialog_enabled(page):
            return None
        if not lead_form_is_open(offer, products_by_id):
            # A closed or live event replaces the form entirely, so there is no dialog to open. Asked with
            # the SAME functions the CTA uses rather than inferred from whether the CTA has rendered --
            # otherwise the answer would depend on where the tenant dragged this element.
            return None
        return ('type="button" data-lead-open', "button")
    context = checkout_context(page or {}, offer, resolved_offer or {}, checkout_url, api_base_url)
    href = escape(str(context.get("href") or ""))
    if not href:
        return None
    attrs = " ".join(
        f'data-{escape(key)}="{escape(str(value))}"'
        for key, value in (context.get("data") or {}).items()
        if value is not None and value != ""
    )
    return (f'href="{href}" {attrs}'.strip(), "a")


def render_page_ribbon(section: dict[str, Any], page: dict[str, Any] | None = None,
                       api_base_url: str | None = None, *, offer: dict[str, Any] | None = None,
                       resolved_offer: dict[str, Any] | None = None,
                       checkout_url: str | None = None,
                       products_by_id: dict[str, dict[str, Any]] | None = None) -> str:
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
        copy.append(render_body_markup(body, "sl-ribbon-body", "        "))
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
    elif action == "cta" and label:
        # Whatever the page's own CTA does, done by the same code (plans/RIBBON_ACTIONS.md §7). `None` means
        # the page has no repeatable ask right now -- an inline lead form, or an event that has closed --
        # and then this renders NO button, because an ask that cannot be honoured is worse than no ask.
        ask = page_ask_attrs(page, offer, resolved_offer, checkout_url, api_base_url, products_by_id)
        if ask:
            attrs, tag = ask
            copy.append(f'        <{tag} class="sl-ribbon-cta sl-ribbon-cta-ask" {attrs}>{escape(label)}</{tag}>')
    elif href and label:
        external = href.startswith(("http://", "https://"))
        rel = ' rel="noopener"' + (' target="_blank"' if external else "")
        copy.append(f'        <a class="sl-ribbon-cta" href="{escape(href)}"{rel}>{escape(label)}</a>')
    copy.append("      </div>")
    parts.extend(copy)

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    # The same named tone the call panel uses. A ribbon has always been able to take a picked colour; this
    # is the theme-following half of the pair, and it costs one class.
    ribbon_tone = f" {tone_class(section.get('tone'))}".rstrip()
    return "\n".join([
        f'    <section class="sl-page-ribbon is-{presentation}{themed}{ribbon_tone}" data-section-id="{section_id}"'
        f' data-section-type="page_ribbon"{style_attr}>',
        *parts,
        "    </section>",
    ])


NUMBERED_LIST_MAX = 12


BEFORE_AFTER_SIZES = "(min-width: 60rem) 60rem, 100vw"
BEFORE_AFTER_DEFAULT_RATIO = 4 / 3


PHOTO_SIZES = "(min-width: 52rem) 52rem, 100vw"
PHOTO_PAIR_SIZES = "(min-width: 52rem) 26rem, 50vw"


def render_photo(section: dict[str, Any]) -> str:
    """Plain images on the page: screenshots used as proof, a portrait, a diagram.

    Every other element that carries an image attaches it to something else -- a content block's prose, an
    author's name, a before/after comparison. There was no way to put an image on a page as the content,
    which is what a stack of screenshotted reviews is: the picture IS the argument.

    A LIST with one shared heading rather than one image per element, because the screenshots that prompted
    this arrive as a set under a single claim, and three separate rows would let them drift apart in the
    order. Deliberately NOT repeatable for the same reason: a second click of the palette button means
    "another photo", which appends to this block's list, not "another photo block". (The video element IS
    repeatable, and the difference is real -- it holds ONE video with its own heading, shape and autoplay
    setting, so a second one is a separate argument elsewhere on the page rather than another item here.)

    Stacked at full width by default: a review screenshot is only proof while its text is readable, and a
    grid shrinks it until it is not. `side_by_side` opts into a 2-up grid for photos that do not carry text.
    """
    images = [image for image in (section.get("images") or []) if str((image or {}).get("url") or "").strip()]
    if not images:
        return ""

    heading = str(section.get("heading") or "").strip()
    pair = bool(section.get("side_by_side"))
    sizes = PHOTO_PAIR_SIZES if pair else PHOTO_SIZES

    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-photo-heading">{render_headline_markup(heading)}</h2>')

    for image in images:
        url = str(image.get("url") or "").strip()
        caption = str(image.get("caption") or "").strip()
        # The tenant's own alt first; a caption describes the picture to everyone, so it is the honest
        # fallback rather than inventing one. Never the heading: it describes the SET, and repeating it on
        # each image announces the same words three times.
        alt = str(image.get("alt") or "").strip() or caption
        figure = cropped_media(
            responsive_img(url, alt, sizes=sizes),
            image.get("crop"), "photo", "sl-photo-media",
        )
        # A real <figure>/<figcaption> when there is a caption: the caption belongs TO this image, and that
        # pairing is what a screen reader needs. Without one a bare figure would add a landmark saying
        # nothing (plans/SEMANTIC_HTML.md).
        if caption:
            rows.append(f'      <figure class="sl-photo">{figure}<figcaption>{escape(caption)}</figcaption></figure>')
        else:
            rows.append(f'      <div class="sl-photo">{figure}</div>')

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    grid = " is-side-by-side" if pair else ""
    section_id = escape(str(section.get("id", "photo")))
    return "\n".join([
        f'    <section class="sl-photos{grid}{themed}" data-section-id="{section_id}" data-section-type="photo"{style_attr}>',
        *rows,
        "    </section>",
    ])


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


VIDEO_BLOCK_DEFAULT_ASPECT = 16 / 9


def render_video(section: dict[str, Any]) -> str:
    """One video anywhere on the page: an uploaded file, or a YouTube/Vimeo link.

    Autoplay and the control bar are OPT-IN choices, and both default to the quiet setting: a video that
    starts itself halfway down a page is noise the reader did not ask for, so nothing autoplays unless the
    tenant says so.

    Autoplay always implies `muted` and `loop`, because a browser will not start a video with sound and a
    silent clip that stops dead on its last frame reads as broken. Hiding the control bar swaps it for
    tap-to-pause rather than removing the ability to stop the video (WCAG 2.2.2) -- see render_media_slide.

    **Both settings apply to an uploaded FILE only.** A YouTube or Vimeo link renders a click-to-load
    facade that deliberately contacts the provider only once a visitor asks for it; autoplaying one would
    mean loading a megabyte of third-party script and setting cookies on the tenant's customers before
    anyone chose to watch. The builder hides both checkboxes for an embed rather than offering a control
    that would quietly do nothing.

    Everything about picking between a file and an embed already lives in render_media_slide, so this
    element is placement and a caption -- it inherits the click-to-load facade, the poster handling and the
    provider parsing without restating any of it.
    """
    url = str(section.get("url") or "").strip()
    if not url:
        return ""

    heading = str(section.get("heading") or "").strip()
    caption = str(section.get("caption") or "").strip()
    poster = str(section.get("poster") or "").strip()
    section_id = escape(str(section.get("id", "video")))

    # The shape follows the VIDEO, not the page. Vertical video is the common case now, and forcing 16/9
    # on it either letterboxes it into a stripe or crops the subject out of frame. An uploaded file's
    # natural ratio is measured at upload; an embed cannot be measured without an API call, so the tenant
    # says which it is.
    try:
        aspect = float(section.get("aspect") or VIDEO_BLOCK_DEFAULT_ASPECT)
    except (TypeError, ValueError):
        aspect = VIDEO_BLOCK_DEFAULT_ASPECT
    if not 0.2 <= aspect <= 5:
        aspect = VIDEO_BLOCK_DEFAULT_ASPECT
    # Taller than square: bound it so it cannot run the height of a desktop screen.
    tall = " is-tall" if aspect < 1 else ""

    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-video-heading">{render_headline_markup(heading)}</h2>')
    rows.append(
        '      <div class="sl-video-frame">'
        + render_media_slide(url, heading or caption or "Video", autoplay=bool(section.get("autoplay")),
                             controls=not section.get("hide_controls"), poster=poster)
        + "</div>"
    )
    if caption:
        # A <figcaption> would need the whole thing to be a <figure>; this is a plain caption, and the
        # video is not an illustration of surrounding prose.
        rows.append(f'      <p class="sl-video-caption">{escape(caption)}</p>')

    style = f'--sl-video-ar:{aspect:g};--sl-embed-ar:{aspect:g}'
    return "\n".join([
        f'    <section class="sl-video-block{tall}" data-section-id="{section_id}"'
        f' data-section-type="video" style="{style}">',
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


INFO_CARDS_MAX = 10
INFO_CARD_PRESENTATIONS = ("numbered", "labelled")


def render_info_cards(section: dict[str, Any]) -> str:
    """Titled points, each with its own explanation. A numbered_list carries LINES; this carries cards.

    Kept apart from numbered_list rather than growing it, because that element's items are plain strings
    and its whole argument is that it is a list -- a real <ol> whose order is the content. Turning its
    items into objects would migrate every existing page to say something it does not mean.

    Two presentations, which is what the author asked for:

    * `numbered`  -- an auto-numbered card with the title in a narrow column and the body beside it. The
                     number is a CSS counter, never authored, so reordering cards cannot strand it.
    * `labelled`  -- an authored eyebrow ("TOOL 01") above a larger title, body underneath, full width.

    Per card: an optional `badge` -- the sticker overhanging the corner -- and `featured`, which outlines
    one card to mark it as the one to look at. Both appear in the author's references and neither changes
    the card's meaning, only its weight.
    """
    items = [
        item for item in (section.get("items") or [])
        if isinstance(item, dict) and (str(item.get("title") or "").strip() or str(item.get("body") or "").strip())
    ][:INFO_CARDS_MAX]
    if not items:
        return ""

    presentation = str(section.get("presentation") or "numbered")
    if presentation not in INFO_CARD_PRESENTATIONS:
        presentation = "numbered"
    numbered = presentation == "numbered"

    heading = str(section.get("heading") or "").strip()
    rows: list[str] = []
    if heading:
        rows.append(f'      <h2 class="sl-info-heading">{render_headline_markup(heading)}</h2>')

    # An <ol> when the cards are numbered: the sequence is then in the markup, which is what lets assistive
    # technology announce "2 of 4" rather than reading a decorative glyph. A labelled set is not ordered,
    # so it is a plain list and claims nothing about sequence.
    list_tag = "ol" if numbered else "ul"
    rows.append(f'      <{list_tag} class="sl-info-cards">')
    for item in items:
        label = str(item.get("label") or "").strip()
        marker_icon = str(item.get("icon") or "").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        badge = str(item.get("badge") or "").strip()
        featured = " is-featured" if item.get("featured") else ""

        card: list[str] = []
        if badge:
            # aria-hidden: it repeats a price or aside that the body already states, and a screen reader
            # meeting it before the title hears the aside first.
            card.append(f'          <span class="sl-info-badge" aria-hidden="true">{escape(badge)}</span>')
        # ONE marker slot, so the numbered grid keeps its three columns. An icon and a label can share it
        # ("TOOL 01" beside a glyph); the counter appears only when the tenant chose neither, which is what
        # makes "no icon" mean "number it".
        marker = "".join(part for part in (
            f'<span class="sl-info-icon" aria-hidden="true">{escape(marker_icon)}</span>' if marker_icon else "",
            escape(label) if label else "",
        ) if part)
        if marker:
            card.append(f'          <p class="sl-info-label">{marker}</p>')
        elif numbered:
            card.append('          <p class="sl-info-label sl-info-count" aria-hidden="true"></p>')
        if title:
            card.append(f'          <h3 class="sl-info-title">{render_headline_markup(title)}</h3>')
        if body:
            # Real paragraphs: these bodies carry a second thought ("Who buys it: ...") under the first,
            # which is exactly what a blank line means.
            card.append(render_body_markup(body, "sl-info-body", "          "))

        rows.append(f'        <li class="sl-info-card{featured}">')
        rows.extend(card)
        rows.append("        </li>")
    rows.append(f"      </{list_tag}>")

    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    themed = " sl-section-themed" if style else ""
    # Per BLOCK, not per card: the references tilt the whole set or none of it.
    crooked = " has-crooked-badges" if section.get("crooked_badges") else ""
    section_id = escape(str(section.get("id", "info-cards")))
    return "\n".join([
        f'    <section class="sl-info is-{presentation}{crooked}{themed}" data-section-id="{section_id}"'
        f' data-section-type="info_cards"{style_attr}>',
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

    quote_html = f'<blockquote class="sl-quote-text">{render_body_markup(text)}</blockquote>'
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
    Links resolve against the Site home host, so cards render as plain (unlinked) tiles off a custom domain.

    THREE LAYOUTS, one renderer (plans/ROUNDUP_PAGES.md §3). The card CONTENT is identical in all three --
    image, title, price, wrapped in the same anchor -- and only the container differs, so a layout cannot
    drift into rendering different data:

      grid      uniform cards. The default, and what every collection rendered before this existed.
      masonry   CSS multi-column, variable heights. For UNORDERED browsing only: `column-count` fills
                each column top-to-bottom, so ten items in five columns read 1,3,5,7,9 across the top.
                The DOM order stays correct -- crawlers and screen readers get the real sequence -- which
                is why this is easy to miss in review: the markup is right and the layout misleads.
      listicle  one row per member, in a real <ol>. The sequence is in the MARKUP, not just the styling,
                for the same reason `render_numbered_list` uses one: assistive technology announces the
                position and the visible number is a CSS counter carrying no content of its own.
    """
    layout = str(section.get("layout") or "").strip().lower()
    if layout not in ("grid", "masonry", "listicle", "editorial"):
        layout = "grid"
    # WHICH RIBBON each editorial entry wears. The element's own presentations, by their own names, so a
    # tenant who knows the ribbon knows this. `centered` is deliberately not offered: it is the ribbon's
    # NO-IMAGE presentation (render_page_ribbon drops the image for it), and an entry in a product listing
    # without its picture is not a thing to put on a menu. The other two both keep it, and `compact` is the
    # denser one for a long list.
    entry_presentation = str(section.get("entry_presentation") or "").strip().lower()
    if entry_presentation not in ENTRY_RIBBON_PRESENTATIONS:
        entry_presentation = "image_left"
    # Both ordered layouts read the per-entry overrides; only the container and the chrome differ.
    ordered = layout in ("listicle", "editorial")
    # THE CARD TITLE'S LEVEL FOLLOWS WHAT IS ABOVE IT. The cards were a fixed <h3> on the reasoning that
    # they "sit under the grid's section heading" -- true only when the section HAS one. `heading` is
    # optional and a Roundup leaves it empty, so the page went h1 (hero) straight to h3 and
    # `heading_outline_warnings` flagged its own renderer's output: "The heading order skips from H1 to
    # H3." Reading the heading here rather than at the return makes the level a fact about the section
    # instead of a constant that happened to be right for the pages this started on.
    heading = str(section.get("heading") or "").strip()
    entry_level = 3 if heading else 2
    # The panel is the same item presented again, not a new subsection, so it goes one level deeper --
    # never a sibling of the title above it.
    panel_level = entry_level + 1
    home = (_RENDER_STATE.get("home_url") or "").rstrip("/")
    cards = []
    for item in section.get("items") or []:
        offer = offers_by_id.get(str((item or {}).get("offer_id") or ""))
        if not offer:
            continue
        presentation = offer.get("presentation") or {}
        name = str(presentation.get("headline") or offer.get("name") or "")
        # Resolved ONCE, up here, because every editorial default below reads it -- the name, the category,
        # the reason to buy. It used to be fetched twice lazily (for the image, then for the pitch), which
        # was fine while two callers wanted it and is the shape drift starts from once five do.
        product = first_offer_product(offer, products_by_id) or {}
        image = str(presentation.get("hero_image_url") or "").strip()
        if not image:
            image = str((product.get("images") or [""])[0])
        # THE PITCH, listicle only. A card is a glance and a row is a read: the grid and masonry layouts
        # stay as they were. Optional, with a fallback, because "very little design" is the goal -- a
        # tenant who writes nothing still gets a working page (plans/ROUNDUP_PAGES.md open question 2).
        #
        # Keyed by PAGE, not offer: the tenant picked a page, and two pages can serve one offer. Falls
        # back to the offer's own subheadline, then the product's description -- the same ladder
        # `hero_copy` climbs, so an entry reads as its own page's hero does.
        pitch_html = ""
        page_id = str((item or {}).get("page_id") or "")
        if ordered:
            pitch = str((section.get("entry_copy") or {}).get(page_id) or "").strip()
            if not pitch:
                pitch = str(presentation.get("subheadline") or "").strip()
            if not pitch:
                pitch = str(product.get("description") or "").strip()
            if pitch:
                pitch_html = f'<p class="sl-catalog-pitch">{escape(pitch)}</p>'
        # NO PRICE IN AN EDITORIAL ENTRY. The author asked for it out, and the composition already agreed
        # with him: `lead_roundup` excludes every other price-bearing element (offer_price_selector,
        # price_highlight, product_details) because a price on a LISTING is a second claim about money
        # that can disagree with the one on the offer page. The grid's own price had simply never been
        # read as one of those. His hand-built ribbons carry none either.
        #
        # Editorial ONLY. grid, masonry and listicle predate this work and storefront and category pages
        # render prices through them today; changing those would be a regression nobody asked for.
        price_html = ""
        if layout != "editorial":
            try:
                resolved = resolve_offer(offer, products_by_id, None, services_by_id=services_by_id)
                price_html = f'<p class="sl-catalog-price">{escape(format_money(int(resolved.get("subtotal", 0)), str(resolved.get("currency") or "usd")))}</p>'
            except Exception:  # noqa: BLE001 - a broken card must not break the page
                pass
        # The words go in ONE wrapper, in every layout. A listicle row is a three-column grid -- number,
        # image, words -- and with the title, pitch and price as separate grid children there were five
        # items for three columns: the row wrapped, so the title sat beside the image while the pitch and
        # the price dropped onto a second line under the number. Grouping them makes the child count match
        # the column count instead of relying on the card never gaining another paragraph.
        #
        # Added for grid and masonry too, not only where it was needed, because the card CONTENT being
        # identical in all three layouts is the property that stops one drifting from another.
        # EDITORIAL extras: parallel page_id maps, the shape `entry_copy` already established, so each is
        # independently absent and nothing needs migrating.
        #
        # EVERY ONE OF THEM NOW CARRIES A DEFAULT READ OFF THE PRODUCT. The first cut defaulted only the
        # headline, on the argument that an eyebrow and a button label are CLAIMS the tenant must write
        # themselves. That argument was wrong about where the words come from: a category and a product
        # name are the tenant's own data, already typed once on the product, and making them retype it per
        # listing page is the "fill it in yourself" form this builder exists to avoid. The standing
        # formula, in the author's words: the software fills the data in and the tenant edits the wording.
        #
        # The dashboard writes these same defaults into the editor's boxes when an entry is first opened,
        # so what publishes is what the tenant can see and change. The ladder stays here as well, for the
        # entry added to the Collection after that modal was last open -- it must still render as an
        # argument rather than as four empty slots.
        eyebrow_html = headline_html = cta_html = support_html = panel_headline_html = ""
        if layout == "editorial":
            # THE CATEGORY. Stored either as a typed label ("Electronics") or as a key
            # ("dietary_supplement"); the underscores are swapped out here for the same reason the
            # product search humanises them. CSS uppercases it, so no case fixing is needed.
            eyebrow = str((section.get("entry_eyebrow") or {}).get(page_id) or "").strip()
            if not eyebrow:
                eyebrow = str(product.get("product_category") or "").replace("_", " ").strip()
            if eyebrow:
                eyebrow_html = f'<p class="sl-ribbon-eyebrow">{escape(eyebrow)}</p>'
            # TWO HEADLINES, because an entry is a content block THEN a ribbon and each has one. The
            # author proved it with a side-by-side: his hand-built ribbon carried a big bold product name
            # inside the panel, and the generated one -- eyebrow, one line, price, button -- read thin
            # next to it. The panel was missing the element's own headline.
            #
            # They take DIFFERENT defaults, which is what stops the name appearing twice. The offer
            # headline is a sales line ("Homeowners Are Trading in Their Doorbell Cams") and the product
            # name names the thing; the prose is the editorial hook and the panel is the product. His own
            # mock-up splits them exactly that way -- "Watch Your Sales Improve With These Landing Page
            # Insider Secrets" above, "Digital Marketing 101" in the ribbon.
            entry_name = (str((section.get("entry_headline") or {}).get(page_id) or "").strip()
                          or name or str(product.get("name") or "").strip())
            headline_html = (f'<h{entry_level} class="sl-catalog-title">'
                             f'{render_headline_markup(entry_name)}</h{entry_level}>'
                             if entry_name else "")
            # The panel's own, styled by the ribbon's class, one level under the prose title above it.
            panel_name = (str((section.get("entry_ribbon_headline") or {}).get(page_id) or "").strip()
                          or str(product.get("name") or "").strip() or name)
            # NOT THE SAME WORDS TWICE. The two defaults were meant to differ -- the offer's sales line
            # above, the product's name in the panel -- but an entry whose offer carries no headline of
            # its own falls back to the offer NAME, which is usually the product name, so both resolved
            # to "Security Mini Cam" and every entry published the heading twice.
            #
            # The PANEL's goes, not the prose one: the prose title is the entry's heading in the outline
            # and the only thing wearing the rank badge (`.sl-catalog-title::before` is the counter), so
            # dropping that would cost the number the whole layout is built around. Give an entry a
            # distinct offer headline and the panel heading comes back, which is the shape the author's
            # own mock-up has -- a sales line above, the product name in the ribbon.
            if panel_name and entry_name and panel_name.casefold() == entry_name.casefold():
                panel_name = ""
            panel_headline_html = (f'<h{panel_level} class="sl-ribbon-headline">'
                                   f'{render_headline_markup(panel_name)}</h{panel_level}>'
                                   if panel_name else "")
            # THE REASON TO BUY, product-level and asked once (Product.selling_point). The last resort is
            # deliberately bland: "Available now" states a fact about stock and claims nothing about the
            # product, which is the only kind of sentence we may put in a seller's mouth unasked.
            support = str((section.get("entry_support") or {}).get(page_id) or "").strip()
            if not support:
                support = str(product.get("selling_point") or "").strip() or "Available now"
            # The ribbon's own body RENDERER, not just its class name. `render_body_markup` is what turns
            # a blank line into a second paragraph and a single newline into a <br>; a bare <p> throws
            # both away and publishes a run-on block. It also emits `sl-para`, which is what spaces
            # consecutive paragraphs -- so the class list only matched the element by accident before.
            support_html = render_body_markup(support, "sl-ribbon-body", "            ")
            # NAVIGATION, not a claim -- the row goes to that page and the button says so. "Shop Now"
            # rather than the earlier "See {name}": a generated label built from a name gets unreadable the
            # moment the name is long, and every button on the page reading the same thing is correct here
            # because every button does the same thing.
            cta = str((section.get("entry_cta") or {}).get(page_id) or "").strip() or "Shop Now"
            # A SPAN, not a nested <a>: the whole card is already the link, and an anchor inside an anchor
            # is invalid markup that browsers silently un-nest -- which would put the button outside the
            # card and break the row.
            cta_html = f'<span class="sl-ribbon-cta">{escape(cta)}</span>'
        # ALT falls back to the PRODUCT's name. `name` is the offer headline, which on a landing page is a
        # sales line ("Homeowners Are Trading in Their Doorbell Cams") -- a description of the pitch, not
        # of the picture. A tenant's own words still win over both: responsive_img resolves the image_alts
        # sidecar typed against the asset before it ever reaches this fallback.
        img_alt = str(product.get("name") or "").strip() or name or "Product"
        img_html = (responsive_img(image, img_alt, sizes=CONTENT_BLOCK_SIZES) if image else "")
        if layout == "editorial":
            # TWO PARTS per entry, which is what the author drew and what the first two cuts of this got
            # wrong. He assembled it by hand as a CONTENT BLOCK followed by a PAGE RIBBON, and the point
            # of the split is editorial: the headline and the paragraph argue for the product in his
            # words, and only then does a panel show it and offer the way through.
            #
            # Folding all of it into one ribbon-shaped row -- the previous attempt -- reads as a product
            # tile however generously it is spaced, because the prose has nowhere to be. The prose is the
            # thing a Roundup is FOR; the panel is the call to action it earns.
            # THE PANEL IS A PAGE RIBBON -- the element itself, not a copy of it. The first version of
            # this hand-rolled a `.sl-catalog-panel` with the ribbon's grid, gap, padding, radius and
            # background typed out again, and the bug that exposed it is the one duplication always
            # produces: the copy left out `color`, so every word in the panel inherited the surrounding
            # <a> and rendered in the browser's VISITED-LINK purple. `.sl-page-ribbon` sets the colour,
            # the responsive collapse at 700px and the accent-safe button ink, and now all of it arrives
            # for free and cannot drift from the element the author builds pages out of by hand.
            panel_copy = "\n".join(line for line in [
                (f"            {eyebrow_html}" if eyebrow_html else ""),
                (f"            {panel_headline_html}" if panel_headline_html else ""),
                support_html,  # already indented by render_body_markup
                (f"            {price_html}" if price_html else ""),
                (f"            {cta_html}" if cta_html else ""),
            ] if line)
            # A <div>, where render_page_ribbon emits a <section>: this one lives inside the card's
            # anchor and inside the page's heading outline, and a sectioning element there would add a
            # rung to that outline for a thing that is not a section of the document.
            panel = "\n".join(line for line in [
                f'          <div class="sl-page-ribbon is-{entry_presentation}">',
                (f'            <div class="sl-ribbon-media">{img_html}</div>' if img_html else ""),
                f'            <div class="sl-ribbon-copy">\n{panel_copy}\n            </div>',
                "          </div>",
            ] if line)
            body = "\n".join(line for line in [
                headline_html and f"          {headline_html}",
                (f"          {pitch_html}" if pitch_html else ""),
                panel,
            ] if line)
            inner = f'        <div class="sl-catalog-body">\n{body}\n        </div>'
        else:
            body = "\n".join(line for line in [
                f'          <h{entry_level} class="sl-catalog-title">'
                f'{render_headline_markup(name)}</h{entry_level}>',
                (f"          {pitch_html}" if pitch_html else ""),
                (f"          {price_html}" if price_html else ""),
            ] if line)
            inner = "\n".join(line for line in [
                (f"        {img_html}" if img_html else ""),
                f'        <div class="sl-catalog-body">\n{body}\n        </div>',
            ] if line)
        slug = str((item or {}).get("slug") or "").strip()
        href = internal_href(slug) if home and slug else ""  # host-relative so the card works on any serving host
        if href:
            card = f'<a class="sl-catalog-card" href="{escape(href)}">\n{inner}\n      </a>'
        else:
            card = f'<div class="sl-catalog-card">\n{inner}\n      </div>'
        # The listicle's rows are <li> so the order lives in the markup; the anchor is unchanged inside it,
        # which is what keeps every layout equally crawlable.
        cards.append(f'      <li class="sl-catalog-row">{card}</li>' if ordered
                     else f'      {card}')
    if not cards:
        return ""
    # `heading` was read before the loop -- the card level depends on it.
    heading_html = f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>' if heading else ""
    section_type = escape(str(section.get("type") or "catalog_grid"))
    # The <ol> is unchanged: the SECTION already carries `sl-layout-{layout}`, so editorial scopes its
    # styling off that rather than adding a second class saying the same thing in another place.
    open_tag, close_tag = (('<ol class="sl-catalog-list">', "</ol>") if ordered
                           else (f'<div class="sl-catalog-cards sl-catalog-{layout}">', "</div>"))
    return "\n".join(line for line in [
        f'    <section class="sl-catalog-grid sl-layout-{layout}" data-section-id="{escape(str(section.get("id", "catalog-grid")))}" data-section-type="{section_type}" data-layout="{layout}">',
        heading_html,
        f"      {open_tag}",
        *cards,
        f"      {close_tag}",
        "    </section>",
    ] if line)





def render_link_cards(section: dict[str, Any]) -> str:
    """A grid of arbitrary EXTERNAL destinations — "my Amazon storefront", "my Substack".

    A separate element from `catalog_grid` on purpose (plans/SOCIAL_MEDIA_PAGES.md §8a). catalog_grid
    builds every href with internal_href(slug) because it exists to make the crawlable subfolder hierarchy
    work; its links MUST be followable. These links must carry rel="nofollow ugc noopener" — the exact
    opposite. One element holding both would be a conditional someone eventually inverts without knowing
    why it was there, and it would force §7's trust policy into a renderer that otherwise has nothing to
    do with it. Keeping them apart gives that policy exactly one home.

    Carries no offer_id, no price and no resolve_offer: this element cannot convert. It is visitor
    navigation, not catalog, so it also stays out of the sitemap and structured data.

    §7 in force: on the tenant's own custom domain any destination may be linked, because the reputation
    at stake is theirs. On platform infrastructure the domain is shared with every other tenant, so only
    allowlisted hosts become anchors — the rest render as plain unlinked tiles, mirroring what
    catalog_grid already does for a card it cannot resolve a host for. Unlinked rather than dropped: a
    card that silently vanishes tells the tenant nothing about why.
    """
    on_custom_domain = bool(_RENDER_STATE.get("own_domain"))
    cards = []
    for item in section.get("items") or []:
        url = str((item or {}).get("url") or "").strip()
        label = str((item or {}).get("label") or "").strip()
        if not url or not label:
            continue
        image = str((item or {}).get("image") or "").strip()
        description = str((item or {}).get("description") or "").strip()
        inner = "\n".join(line for line in [
            (f"        {responsive_img(image, label, sizes=CONTENT_BLOCK_SIZES)}" if image else ""),
            f'        <h3 class="sl-catalog-title" title="{escape(label)}">{render_headline_markup(label)}</h3>',
            (f'        <p class="sl-link-card-note" title="{escape(description)}">{escape(description)}</p>'
             if description else ""),
        ] if line)
        if on_custom_domain or linkable_on_platform_host(url):
            cards.append(
                f'      <a class="sl-catalog-card sl-link-card" href="{escape(url)}" '
                f'rel="nofollow ugc noopener" target="_blank" data-sl-link="{link_click_id(url)}"'
                f'{' data-sl-adult="1"' if is_adult_host(url) else ""}>'
                f'\n{inner}\n      </a>')
        else:
            cards.append(f'      <div class="sl-catalog-card sl-link-card">\n{inner}\n      </div>')
    if not cards:
        return ""
    heading = str(section.get("heading") or "").strip()
    heading_html = f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>' if heading else ""
    return "\n".join(line for line in [
        f'    <section class="sl-catalog-grid sl-link-cards" data-section-id="{escape(str(section.get("id", "link-cards")))}" data-section-type="link_cards">',
        heading_html,
        '      <div class="sl-catalog-cards">',
        *cards,
        "      </div>",
        "    </section>",
    ] if line)


# A coin being handed over: the gesture the button asks for, drawn rather than named. Stroked in
# currentColor so it takes the CTA's text colour on a themed button and the muted ink when the destination
# is not linkable -- one glyph, never two states to keep in sync. aria-hidden because the label beside it
# already says "Leave a tip"; announcing the drawing again would just make the button take twice as long.
TIP_JAR_ICON = (
    '<svg class="sl-tip-jar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<circle cx="12" cy="6.1" r="4.6"/>'
    # The $ is drawn thinner than the rest. At this size a 1.7 stroke inside a 9px coin closes up into a
    # blob -- the glyph has to be lighter than the shape holding it to stay a glyph.
    '<path d="M13.3 4.6a1.3 1.3 0 0 0-1.3-.75c-.78 0-1.4.42-1.4 1s.55.85 1.4 1.05 1.4.5 1.4 1.05-.62 1-1.4 1a1.3 1.3 0 0 1-1.3-.75"'
    ' stroke-width="1.15"/>'
    '<path d="M12 3.1v.75M12 8.35v.75" stroke-width="1.15"/>'
    '<path d="M2.6 15.6l2.5-1.1a2.2 2.2 0 0 1 1.9.05l2.4 1.15h3a1.45 1.45 0 0 1 0 2.9H9.8"/>'
    '<path d="M9.4 18.6h4.2c.4 0 .8-.08 1.2-.24l4.9-2.1a1.55 1.55 0 0 1 1.25 2.83l-6.4 3a4.4 4.4 0 0 1-3.1.3l-5.8-1.55-2.7-.95"/>'
    "</svg>"
)


def render_tip_jar(section: dict[str, Any]) -> str:
    """A single prominent outbound button: "Leave a tip", pointing at wherever the creator takes them.

    A LINK, not a checkout. A link hub sells nothing -- `lead_social` has no checkout_cta and its product
    carries no price -- so a tip has to land somewhere that already handles money: Ko-fi, Buy Me a Coffee,
    Patreon. Building a payment flow here would mean giving a page that takes no money a way to take money.

    §7 applies exactly as it does to link_cards, and it is why the destination matters. On the tenant's own
    verified domain any host is linkable; on shared platform infrastructure only curated ones are, and
    payment HANDLES (paypal.me, venmo, cash.app) are deliberately absent from that list -- a payment request
    is the highest-value phishing target there is, and one on a domain shared with every tenant is the single
    thing most likely to cost us the domain (plans/CREATOR_LINK_POLICY.md §4). So a paypal.me tip jar renders
    as an inert button on a free address, which is the honest outcome rather than a silent one.
    """
    url = str(section.get("url") or "").strip()
    if not url:
        return ""
    label = escape(str(section.get("label") or "").strip() or "Leave a tip")
    heading = str(section.get("heading") or "").strip()
    note = str(section.get("note") or "").strip()
    linkable = bool(_RENDER_STATE.get("own_domain")) or linkable_on_platform_host(url)
    inner = f"{TIP_JAR_ICON}<span>{label}</span>"
    button = (
        f'<a class="sl-tip-jar-btn" href="{escape(url)}" rel="nofollow ugc noopener" target="_blank"'
        f' data-sl-link="{link_click_id(url)}">{inner}</a>'
        if linkable else
        f'<span class="sl-tip-jar-btn is-unlinked">{inner}</span>'
    )
    return "\n".join(line for line in [
        f'    <section class="sl-tip-jar" data-section-id="{escape(str(section.get("id", "tip-jar")))}"'
        f' data-section-type="tip_jar">',
        (f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>' if heading else ""),
        f"      {button}",
        (f'      <p class="sl-tip-jar-note">{escape(note)}</p>' if note else ""),
        "    </section>",
    ] if line)


def _social_link_item(url: Any, *, linkable: bool = True) -> str:
    """One profile link: the network's brand glyph where there is one, the worded label where there is not.

    A link hub is scanned, not read -- a visitor looking for the YouTube channel finds the YouTube mark
    faster than the word among nine other words. The name is still carried for anyone who cannot see the
    glyph: aria-label on the link, and the SVG itself is aria-hidden so a screen reader announces the
    network once rather than twice.

    There is ALWAYS a glyph: the network's own mark, or a globe when we do not recognise the host. Spelling
    the host out -- which is what this used to do -- put a wide text pill in a row of 44px circles and broke
    the one visual property a link hub has (author, 2026-09-11: "adversely disrupts the organized look").
    Nothing is lost by it, because the NAME was never in the glyph; it is on the link, where a screen reader
    and a hover both still find it.
    """
    href = escape(str(url).strip())
    label = escape(network_label(url))
    named = f' aria-label="{label}" title="{label}"'
    inner = (f'<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor" aria-hidden="true"'
             f' focusable="false"><path d="{escape(network_glyph(url))}"/></svg>')
    # §7, the same trust boundary render_link_cards applies, for the same reason and with the same shape: on a
    # shared platform host only allowlisted destinations become anchors, because a human tapping a phishing
    # link on someone.jbay.uk is a browser-blocklist problem for OUR domain and every tenant on it. Unlinked
    # rather than dropped -- a tile that silently vanishes tells the tenant nothing about why.
    if not linkable:
        return f'<li><span class="sl-social-glyph is-unlinked"{named}>{inner}</span></li>'
    adult = ' data-sl-adult="1"' if is_adult_host(url) else ""
    return (f'<li><a class="sl-social-glyph" href="{href}" rel="nofollow ugc noopener" target="_blank"'
            f'{named} data-sl-link="{link_click_id(url)}"{adult}>{inner}</a></li>')


def render_social_links(section: dict[str, Any]) -> str:
    """A standalone row of the business's social profiles — the identity header of a link-in-bio page.

    Reads the SITE's organization.same_as, so a tenant fills it in once on the Business Profile rather than
    re-typing it per page.

    Display is NOT gated on verification, and that is the whole point of the two-tier model
    (plans/SOCIAL_MEDIA_PAGES.md §7a-i): Instagram and TikTok cannot be confirmed by any unauthenticated
    fetch, and they are the two platforms this page exists to be linked FROM. Gating display would empty
    the row of exactly the links that matter. Verification gates `sameAs` — the machine-readable identity
    claim, emitted elsewhere — never what a visitor can see and tap.

    Every link is rel="nofollow ugc noopener": these are tenant-entered destinations, so they must never
    pass authority from our domain, and `ugc` says what they are.
    """
    entries = social_section_entries(section, _RENDER_ORG)
    if not entries:
        return ""
    on_custom_domain = bool(_RENDER_STATE.get("own_domain"))
    parts = [f'    <section class="sl-social-links" data-section-id="{escape(str(section.get("id", "social-links")))}" data-section-type="social_links">']
    heading = str(section.get("heading") or "").strip()
    if heading:
        parts.append(f'      <h2 class="sl-section-heading">{render_headline_markup(heading)}</h2>')
    links = "".join(
        _social_link_item(
            entry.get("url"),
            linkable=on_custom_domain or linkable_on_platform_host(entry.get("url")),
        )
        for entry in entries
    )
    parts.append(f'      <ul class="sl-social-row">{links}</ul>')
    parts.append("    </section>")
    return "\n".join(parts)


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
        parts.append(render_body_markup(description, "sl-seller-desc", "      "))
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
    socials = verified_same_as_urls(org)
    if socials:
        links = "".join(f'<li><a href="{escape(u)}" rel="nofollow ugc noopener" target="_blank">{escape(network_label(u))}</a></li>' for u in socials)
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
    "call": {"render": lambda c: render_call_cta(c.cta, c.section), "version": 1},
    "external": {"render": lambda c: render_external_cta(c.cta, c.section), "version": 1},
    "email": {"render": lambda c: render_email_cta(c.page, c.offer, c.cta, c.products_by_id, c.api_base_url, c.section), "version": 1},
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
    # The PAGE's label overrides the offer's snapshot. render_buy_cta already did this for itself; the lead
    # CTAs did not, so the builder's "Button Label" field was a no-op on exactly the pages whose whole job is
    # that button (author, 2026-09-16). Resolved once here so all five types behave the same.
    section_label = str(section.get("label") or "").strip()
    if section_label:
        cta = {**cta, "label": section_label}
    entry = CTA_REGISTRY.get(cta["type"], CTA_REGISTRY["buy"])
    ctx = CtaRenderContext(
        cta=cta, page=page, section=section, offer=offer, resolved_offer=resolved_offer,
        checkout_url=checkout_url, api_base_url=api_base_url, products_by_id=products_by_id or {},
    )
    return entry["render"](ctx)


LEAD_FIELD_INPUT_TYPES = {"email": "email", "phone": "tel", "tel": "tel", "number": "number"}

# What each input tells the BROWSER, and what it shows before anything is typed. A placeholder of "Phone" is
# a restatement of the label; a shaped example tells the visitor which number and in what form.
LEAD_FIELD_HINTS = {
    "email": {"autocomplete": "email", "inputmode": "email", "placeholder": "you@example.com"},
    "tel": {"autocomplete": "tel", "inputmode": "tel", "placeholder": "(555) 555-0100"},
}


def render_email_cta(
    page: dict[str, Any],
    offer: dict[str, Any],
    cta: dict[str, str],
    products_by_id: dict[str, dict[str, Any]],
    api_base_url: str | None,
    section: dict[str, Any] | None = None,
) -> str:
    """Inline lead-capture form. Renders the primary product's declared lead_capture.fields[], a honeypot,
    and two independent GDPR opt-ins (tenant list + Junior Bay list). Submits to POST /leads via JS."""
    lead_capture = first_offer_lead_capture(offer, products_by_id)
    declared = lead_capture.get("fields") or [{"name": "email", "type": "email", "required": True}]
    # A REGISTRATION is this form plus the session it is for (plans/WEBINAR.md §5-6). The event is resolved
    # here rather than passed, from the render-scoped index.
    scheduled_event = _RENDER_EVENTS.get(str(lead_capture.get("event_id") or "")) if lead_capture.get("event_id") else None
    label = escape(cta["label"] or "Get Started")
    # The PAGE first, then the product's. A phone capture is a different business on every page that uses it
    # -- a roofer's "Where can we reach you?" is not an insurance broker's -- so the seeded default has to be
    # a starting point the tenant can replace rather than a fixed string (author, 2026-09-16).
    section = section or {}
    title = escape(str(section.get("form_title") or lead_capture.get("title") or "").strip())
    description = escape(str(section.get("form_description") or lead_capture.get("description") or "").strip())
    endpoint = escape(f"{str(api_base_url or '').rstrip('/')}/leads")
    tenant_id = escape(str(page.get("tenant_id") or offer.get("tenant_id") or ""))
    offer_id = escape(str(offer.get("offer_id") or ""))
    page_id = escape(str(page.get("page_id") or ""))
    # WHOSE list this is -- and it is a BUSINESS's, never a product's. The same chain the brand label at the
    # top of the page resolves, for the same reason: "Join Free Roof Inspection's mailing list" asks the
    # visitor to consent to something that does not exist. `offer_brand_fallback` ends at the offer's
    # headline, which IS the product name, so it sits below the tenant's own business identity rather than
    # above it (author, 2026-09-16 -- fixed on the brand label first, and this was the half left behind).
    brand = escape(str(
        str(_RENDER_ORG.get("name") or "").strip()
        or str(_RENDER_PREFERENCES.get("business_name") or "").strip()
        or str((offer.get("presentation") or {}).get("brand") or "").strip()
        or str(_RENDER_PREFERENCES.get("display_name") or "").strip()
        or "us"
    ))

    inputs = []
    for field in declared:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        field_type = str(field.get("type") or "text").strip().lower()
        input_type = LEAD_FIELD_INPUT_TYPES.get(field_type, "text")
        required = "required" if field.get("required") else ""
        hints = LEAD_FIELD_HINTS.get(input_type, {})
        placeholder = escape(hints.get("placeholder") or name.replace("_", " ").title())
        # autocomplete + inputmode, because this form is ONE field and the visitor is on a phone. Without
        # them a tel input offers no numeric keypad and neither field offers the browser's saved value --
        # on a page whose entire conversion is "type the one thing we asked for", that is the whole funnel.
        extras = f' autocomplete="{hints["autocomplete"]}"' if hints.get("autocomplete") else ""
        if hints.get("inputmode"):
            extras += f' inputmode="{hints["inputmode"]}"'
        inputs.append(
            f"        <input class=\"sl-lead-input\" type=\"{input_type}\" name=\"{escape(name)}\" "
            f"placeholder=\"{placeholder}\"{extras} {required} />"
        )

    # MAILING-LIST consent belongs on a page that collects a mailing address. A phone capture has no email to
    # add to a list, so both boxes were asking the visitor to agree to something that cannot happen -- and
    # recording a consent nothing can act on is worse than not asking (author, 2026-09-16).
    #
    # Note for whoever adds SMS or call marketing later: this is NOT the box to reuse. Marketing calls and
    # texts to a submitted number are governed separately (TCPA in the US requires prior express WRITTEN
    # consent, and a callback the visitor asked for is a different thing from a marketing campaign).
    collects_email = any(
        str(field.get("type") or "").strip().lower() == "email"
        or str(field.get("name") or "").strip().lower() == "email"
        for field in declared
    )
    # "Join us's mailing list." is what the possessive did with the last-resort brand. When we cannot name
    # the business, say it the way a person would.
    tenant_consent_text = f"Join {brand}'s mailing list." if brand != "us" else "Join our mailing list."
    platform_consent_text = "Also hear from Junior Bay about offers like this."
    consent_rows = [
        "        <label class=\"sl-lead-consent\"><input type=\"checkbox\" data-consent=\"tenant_marketing\" "
        f"data-consent-text=\"{escape(tenant_consent_text)}\" /> {escape(tenant_consent_text)}</label>",
        "        <label class=\"sl-lead-consent\"><input type=\"checkbox\" data-consent=\"platform_marketing\" "
        f"data-consent-text=\"{escape(platform_consent_text)}\" /> {escape(platform_consent_text)}</label>",
    ] if collects_email else []
    # UNTICKED, and it has to stay that way. GDPR recital 32 says in terms that "silence, pre-ticked boxes or
    # inactivity" do not constitute consent, and Art. 4(11) requires "a clear affirmative action" -- a box the
    # visitor must UNtick is the absence of one. Settled in CJEU Planet49 (C-673/17), which reasoned straight
    # from that definition. The platform box is the weaker of the two by a distance: third-party marketing is
    # never covered by the ePrivacy soft opt-in that can otherwise excuse a tenant's own list.
    #
    # Briefly shipped pre-ticked on 2026-09-15 and reverted the same day once the rule was checked. Left here
    # so the next person reaches for the citation instead of the checkbox (author's decision: "we must comply
    # to legal statutes").
    if scheduled_event is not None:
        now_epoch = int(time.time())
        # A webinar is a free event whose point is that people WATCH it, so the page's job changes at the
        # start time: collect a lead before, push them at the join URL during, say they missed it after
        # (author, 2026-10-14). The live window is checked FIRST -- a form shown while the host is already
        # talking is the page failing at the only moment that matters.
        live = event_live_occurrence(scheduled_event, now=now_epoch)
        if live is not None:
            return render_event_live(scheduled_event, live, section, title=title)
        # Asked at PUBLISH with the same function the endpoint uses, so a page cannot offer a session the
        # server will refuse. A page is a cached artifact, so the server still checks -- this decides what
        # the visitor is shown, not whether the registration is allowed.
        open_rows = event_open_occurrences(scheduled_event, now=now_epoch)
        if not open_rows:
            return render_event_closed(scheduled_event, section, description=description)
        inputs = [render_occurrence_picker(open_rows)] + inputs

    # SHOWN ON THE PAGE, or opened from a button. Inline is the default, so no existing page changes:
    # inline forms often convert better (the field is already in front of the visitor), modals win when
    # the page is long and the form would otherwise sit far from the argument that earned the click. It is
    # A/B-dependent, so the tenant chooses (plans/LANDING_PAGE_CTA_AND_COMPOSITION.md).
    #
    # Only the dialog mode makes the ask REPEATABLE: the form stays a single instance -- the lead handler
    # is `querySelector('[data-lead-form]')`, singular, so a second copy would never be bound -- and every
    # button on the page opens that one. Recorded render-scoped so a ribbon can find it.
    as_dialog = str(section.get("form_presentation") or "inline").strip().lower() == "dialog"
    form_rows = [
        f"      <form class=\"sl-lead-form\" data-lead-form data-endpoint=\"{endpoint}\" "
        f"data-tenant-id=\"{tenant_id}\" data-offer-id=\"{offer_id}\" data-page-id=\"{page_id}\" "
        f"data-stripe-mode=\"{'live' if str(offer.get('stripe_mode') or '').strip().lower() == 'live' else 'test'}\""
        + (f" data-event-id=\"{escape(str(lead_capture.get('event_id') or ''))}\"" if scheduled_event is not None else "")
        + ">",
        (f"        <p class=\"sl-lead-title\">{title}</p>" if title else ""),
        (f"        <p class=\"sl-lead-description\">{description}</p>" if description else ""),
        *inputs,
        # Honeypot — visually hidden, off-screen; bots fill it, humans don't.
        "        <input class=\"sl-hp\" type=\"text\" name=\"company_website\" tabindex=\"-1\" autocomplete=\"off\" aria-hidden=\"true\" />",
        *consent_rows,
        f"        <button class=\"sl-cta\" type=\"submit\">{label}</button>",
        "        <p class=\"sl-lead-status\" data-lead-status role=\"status\" aria-live=\"polite\"></p>",
        "      </form>",
    ]
    if not as_dialog:
        return "\n".join(line for line in [
            "    <section class=\"sl-checkout-cta sl-email-cta\" data-section-type=\"checkout_cta\" data-cta-type=\"email\">",
            *form_rows,
            "    </section>",
        ] if line)

    _RENDER_LEAD_DIALOG["open_selector"] = "[data-lead-open]"
    # Native <dialog>, not a hand-rolled overlay: focus trapping, Escape-to-close and an inert background
    # come with showModal(), and a registration form is exactly where hand-rolling those goes wrong.
    # The section is ONLY the button. The title and description stay inside the dialog, where they head the
    # form -- repeating them on the page under a button that opens them is the same two lines twice.
    # Whatever pitches the button is the page's own content: the hero, or the ribbon that hosts it.
    return "\n".join(line for line in [
        "    <section class=\"sl-checkout-cta sl-email-cta is-dialog\" data-section-type=\"checkout_cta\" data-cta-type=\"email\">",
        f"      <button class=\"sl-cta\" type=\"button\" data-lead-open>{label}</button>",
        "    </section>",
        f"    <dialog class=\"sl-lead-dialog\" data-lead-dialog aria-label=\"{title or 'Registration'}\">",
        "      <form method=\"dialog\" class=\"sl-lead-dialog-dismiss\">",
        "        <button class=\"sl-lead-dialog-close\" type=\"submit\" aria-label=\"Close\">&times;</button>",
        "      </form>",
        *form_rows,
        "    </dialog>",
    ] if line)


def render_occurrence_picker(open_rows: list[dict[str, Any]]) -> str:
    """Which session. A radio group when there is a choice, a hidden field when there is not.

    Radios rather than a <select>: there are two or three of these and each needs a date AND its zone, which
    a one-line option truncates on a phone. With a single occurrence there is nothing to choose, so asking
    would be a question with one answer -- the value still travels, because the server needs to know which.
    """
    if len(open_rows) == 1:
        row = open_rows[0]
        return (f'        <input type="hidden" name="occurrence_id" '
                f'value="{escape(str(row.get("occurrence_id") or ""))}" />')
    rows = ['        <fieldset class="sl-occurrence-picker">',
            '          <legend>Choose a session</legend>']
    for index, row in enumerate(open_rows):
        occurrence_id = escape(str(row.get("occurrence_id") or ""))
        when = escape(format_event_date(event_starts_at(row), str(row.get("timezone") or ""), with_time=True))
        checked = ' checked' if index == 0 else ''
        left = event_seats_left(row)
        # Only when it is nearly gone: "497 seats left" is not scarcity, it is arithmetic.
        remaining = f'<span class="sl-occurrence-seats">{left} left</span>' if left is not None and left <= 20 else ''
        rows.append(
            f'          <label class="sl-occurrence"><input type="radio" name="occurrence_id" '
            f'value="{occurrence_id}"{checked} /> <span>{when}</span>{remaining}</label>'
        )
    rows.append('        </fieldset>')
    return "\n".join(rows)


def render_event_live(scheduled_event: dict[str, Any], occurrence: dict[str, Any],
                      section: dict[str, Any] | None, *, title: str) -> str:
    """The session is running. One job: get the visitor into it.

    The join link is the whole page at this moment, so the form is replaced rather than sat beside -- a
    visitor who arrives mid-session does not want to fill anything in, they want the room. Someone who
    never registered is let in too: a free event exists to be watched, and turning away an attendee to
    protect a lead record has the priority backwards.

    No join URL yet is the one case this cannot rescue, so it says so plainly instead of rendering a button
    that goes nowhere.
    """
    section = section or {}
    join_url = safe_href(str(scheduled_event.get("join_url") or ""))
    heading = escape(str(section.get("live_title") or "We're live now"))
    rows = [
        '    <section class="sl-checkout-cta sl-email-cta sl-event-live" data-section-type="checkout_cta"'
        ' data-cta-type="email" data-event-live="true">',
        '      <div class="sl-lead-form">',
        (f'        <p class="sl-lead-title">{title}</p>' if title else ""),
        f'        <p class="sl-event-live-heading">{heading}</p>',
    ]
    if join_url:
        rows.append(
            f'        <a class="sl-cta sl-event-join" href="{escape(join_url)}" target="_blank" '
            f'rel="noopener">{escape(str(section.get("live_label") or "Join the session"))}</a>'
        )
    else:
        rows.append('        <p class="sl-lead-description">The host has not posted the link yet. '
                    'Check your email — it will be sent there.</p>')
    rows.extend(["      </div>", "    </section>"])
    return "\n".join(row for row in rows if row)


def render_event_closed(scheduled_event: dict[str, Any], section: dict[str, Any] | None,
                        *, description: str = "") -> str:
    """What the page says once no session is open.

    The form is REPLACED, not disabled: a disabled form invites people to try, and a registration page that
    silently keeps collecting addresses for a session that already ran is the worst failure available here.

    **It does not keep the form's title.** This used to lead with the lead-capture title -- "Reserve your
    spot" -- in the card's boldest type, with "Registration has closed" below it in body weight. A reader
    who got one line in read an invitation and moved on, which is exactly what happened to the first person
    who looked at it (2026-10-15). An offer you cannot accept is not a heading.

    Styled as an ALERT rather than as a price card, for the same reason: the one thing on the page that
    contradicts everything above it has to look different from everything above it.
    """
    section = section or {}
    heading = escape(str(section.get("closed_title") or "Registration has closed"))
    note = escape(str(section.get("closed_text")
                      or "This session has already taken place. Check back for the next one."))
    return "\n".join([
        '    <section class="sl-checkout-cta sl-email-cta sl-event-closed" data-section-type="checkout_cta"'
        ' data-cta-type="email" data-event-closed="true">',
        '      <div class="sl-lead-form" role="status">',
        f'        <p class="sl-event-closed-heading">{heading}</p>',
        f'        <p class="sl-lead-description">{note}</p>',
        '      </div>',
        '    </section>',
    ])


def render_buy_cta(
    page: dict[str, Any],
    section: dict[str, Any],
    offer: dict[str, Any],
    resolved_offer: dict[str, Any],
    checkout_url: str | None,
    api_base_url: str | None = None,
) -> str:
    # The composition gets a say before the generic fallback: on a tip jar the button reads "Send tip", since
    # nothing is being bought and the verb is the last thing a supporter reads before their card is charged.
    label = escape(str(
        section.get("label")
        or (offer.get("presentation") or {}).get("cta_label")
        or default_cta_label(offer)
        or "Checkout"
    ))
    subtotal = int(resolved_offer.get("subtotal", 0))
    currency = str(resolved_offer.get("currency") or "usd")
    # An upsell screen bakes the price into its accept label ("… for $22.17"), so it suppresses the CTA's own
    # amount to avoid "$22.17 - $22.17". The flag is echoed to the island so its updateCta doesn't re-append it.
    # The decline link's text is the scaffold's decline_label (falls back to the generic default).
    hide_amount = bool(section.get("hide_amount"))
    decline_label = escape(str(section.get("decline_label") or "No thanks, continue"))
    every = _RENDER_STATE.get("tip_frequency_word") or ""
    cta_text = label if hide_amount else f"{label} - {escape(format_money(subtotal, currency))}"
    if every and not hide_amount:
        cta_text += f" / {escape(every)}"
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


def dialable_number(phone: str) -> str:
    """The number as a human reads it aloud, from the E.164 the tenant stored.

    NANP only, deliberately. "+12065654418" is a string of digits nobody scans; "(206) 565-4418" is a phone
    number. Every other country keeps its E.164 form, which is correct and universally dialable -- getting
    the rest right means libphonenumber, and a 220KB dependency in the PUBLISH path to prettify a label is
    not a trade worth making. The tel: href always uses the raw digits either way.
    """
    digits = re.sub(r"[^\d]", "", phone or "")
    if phone.strip().startswith("+1") and len(digits) == 11:
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    if not phone.strip().startswith("+") and len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
    return phone.strip()


def destination_label(url: str) -> str:
    """Where a bridge button GOES, as the visitor would say it: the HOST.

    Always the host. It briefly returned a filename when the path looked like one, which put "index.html" on
    a live advertorial in 4.4rem type (author, 2026-09-16: "an eyesore"), and the file case is gone entirely
    now -- a bridge button redirects, full stop (author, 2026-09-17).
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    without_scheme = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", raw)
    host = without_scheme.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return re.sub(r"^www\.", "", host) or raw


def render_cta_panel(
    section: dict[str, Any],
    *,
    variant: str,
    lead: str,
    lead_href: str,
    label: str,
    link_attrs: str = "",
    default_tone: str = "contrast",
    default_show_lead: bool = True,
) -> str:
    """The panel every lead CTA now wears: an optional kicker, the thing that identifies the destination,
    and a button -- plus a sticky bar that follows the visitor down the page.

    ONE implementation for call / external / download (author, 2026-09-16: "re-using elements rather than
    create special ones is the best way to go"). They differ only in what the big line says: a phone number,
    a hostname, a filename. Writing that three times is how three pages come to look like three products.

    `lead` is a tap target in its own right -- the number dials, the host navigates -- because on a page with
    one job the identifying detail should be clickable, not decorative.
    """
    tone = tone_class(section.get("tone"), default=default_tone)
    style = section_theme_vars(section)
    style_attr = f' style="{escape(style)}"' if style else ""
    kicker = str(section.get("kicker") or "").strip()
    # SUPPRESSIBLE, and the default differs by what the line is. A phone number IS the call page -- hiding it
    # would leave a button with nothing to say. A destination host is a useful answer to "leave for where?"
    # only when the host means something to the visitor; when it is a CDN hostname or an artifact URL it is
    # noise, and we cannot tell which from here. So the tenant decides, and the quiet default wins the tie.
    show_lead = section.get("show_destination")
    if show_lead is None:
        show_lead = default_show_lead
    if not show_lead:
        lead = ""
    panel = [
        f'    <section class="sl-checkout-cta sl-{variant}-cta" data-section-type="checkout_cta"'
        f' data-cta-type="{variant}">',
        f'      <div class="sl-cta-panel {tone}"{style_attr}>',
        (f'        <p class="sl-cta-kicker">{escape(kicker)}</p>' if kicker else ""),
        (f'        <a class="sl-cta-lead" href="{lead_href}"{link_attrs}>{escape(lead)}</a>' if lead else ""),
        f'        <a class="sl-cta sl-cta-panel-button" href="{lead_href}"{link_attrs}>{label}</a>',
        "      </div>",
        "    </section>",
    ]
    # A SECOND, sticky tap target. Someone scrolling a phone should never have to find their way back to the
    # action (author, 2026-09-16: "it pays to have that call button stick to the bottom no matter what").
    # Its own element rather than making the panel sticky, so the panel can be read in place.
    sticky = [
        f'    <div class="sl-cta-sticky" data-cta-sticky="{variant}">',
        f'      <a class="sl-cta sl-cta-panel-button" href="{lead_href}"{link_attrs}>{label}</a>',
        "    </div>",
    ]
    return "\n".join(line for line in panel + sticky if line)


def render_call_cta(cta: dict[str, str], section: dict[str, Any] | None = None) -> str:
    """The call panel: a ribbon-shaped block built around the NUMBER, plus a sticky bar that follows.

    Rebuilt 2026-09-16 on the author's design. The number was a line of small text above a short button on an
    otherwise empty page; it is the single most important thing here, so it is now the size of one. Borrowed
    from the page ribbon rather than invented, because the author reached for a ribbon to mock this up -- the
    shape was already right, it was just not reachable from a CTA.

    The number itself is a tap target, not decoration: on a phone it dials, and on a desktop it is the thing
    the visitor writes down.
    """
    section = section or {}
    phone = cta["target"].strip()
    tel = re.sub(r"[^\d+]", "", phone)
    return render_cta_panel(
        section,
        variant="call",
        # Read aloud, not stored: "(206) 565-4418" rather than "+12065654418".
        lead=dialable_number(phone),
        lead_href=f"tel:{escape(tel)}" if tel else "#",
        label=escape(cta["label"] or "Call Now"),
    )


def render_external_cta(cta: dict[str, str], section: dict[str, Any] | None = None) -> str:
    """External-link CTA: the shared panel, with the DESTINATION as its identifying line.

    A bridge page asks someone to leave the site, and the question that earns the click is "leave for
    where?". A bare button never answered it; the hostname does, in the form a person would say it.
    """
    url = cta["target"].strip()
    return render_cta_panel(
        section or {},
        variant="external",
        lead=destination_label(url),
        lead_href=escape(url) if url else "#",
        label=escape(cta["label"] or "Learn More"),
        link_attrs=' target="_blank" rel="noopener noreferrer"',
        default_show_lead=False,
    )


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


def refund_page_tenant_query() -> str:
    """`?tenant=` for the footer's Refund Policy link, or "".

    The self-service action lives ON the refund policy page rather than beside it in the footer: someone
    opens Refund Policy because they want the money to stop, and a second footer link would compete with the
    page they are already going to (author, 2026-09-14). That page is platform-global, so the tenant has to
    travel with the link — this is the whole of that plumbing.

    Only added to the PLATFORM refund page. A tenant who supplies their own absolute refund_url owns that
    page, and we do not rewrite it.
    """
    tenant_id = str(_RENDER_STATE.get("tenant_id") or "")
    return f"?tenant={quote(tenant_id, safe='')}" if tenant_id else ""


def _legal_href(stored_url: Any, page_id: str, api_base_url: str) -> str:
    """Resolve a footer legal link: honor an explicit absolute URL, else point at the
    platform legal page. Empty values and bare-anchor placeholders (e.g. '#terms') are
    treated as unset and default to {api_base_url}/legal/{page_id}."""
    stored = str(stored_url or "").strip()
    if stored.startswith("http://") or stored.startswith("https://"):
        return stored
    base = str(api_base_url or "").rstrip("/")
    if not base:
        return ""
    # The refund page carries the "manage a purchase" action, and needs to know whose purchase.
    suffix = refund_page_tenant_query() if page_id == "refund" else ""
    return f"{base}/legal/{page_id}{suffix}"


def report_link(api_base_url: str = "") -> str:
    """"Report this page", for pages WE host on a shared domain (plans/CREATOR_LINK_POLICY.md §6).

    link.me carries one beside Privacy and Terms, and it is the half of the abuse story that answers for what
    gets through the allowlist. Shown only on a LINK HUB: those are the tenant-authored, outbound-link pages
    that share an apex with every other creator, so one bad actor's page is everyone's problem. A tenant's own
    storefront on their own domain is their business, and a Report link there would be ours interfering.
    """
    base = str(api_base_url or "").rstrip("/")
    page_id = str(_RENDER_STATE.get("report_page_id") or "")
    if not base or not page_id:
        return ""
    return (f"      <a class=\"sl-legal-report\" href=\"{escape(base)}/report?page={escape(page_id)}\""
            f" rel=\"nofollow noopener\">Report this page</a>")


def render_legal_footer(legal: dict[str, Any], section: dict[str, Any] | None = None, api_base_url: str = "") -> str:
    rendered_links = [
        f"      <a href=\"{escape(href)}\" target=\"_blank\" rel=\"noopener\">{label}</a>"
        for page_id, label, field in LEGAL_FOOTER_LINKS
        if (href := _legal_href(legal.get(field), page_id, api_base_url))
    ]
    if (reporting := report_link(api_base_url)):
        rendered_links.append(reporting)
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


def render_price_description_toggle_script(page: dict[str, Any]) -> str:
    """"See more" on a clamped price description.

    Gated on ACTUAL OVERFLOW, not on a media query. A toggle that appears whenever the viewport is narrow
    would sit under short descriptions doing nothing, which teaches the buyer to ignore it; measuring
    scrollHeight means it appears exactly where there is something hidden, at any width. It also
    re-measures on resize, because rotating a phone changes the answer.

    stopPropagation is load-bearing. Clicking anywhere on a price option selects that tier
    (`card.addEventListener('click', () => selectCard(card))`), so without it, reading a description would
    silently change what the buyer is about to purchase.
    """
    types = {str(section.get("type") or "") for section in (page.get("sections") or [])}
    if not types & {"offer_price_selector", "listicle_tiers"}:
        return ""
    return "\n".join([
        "  <script>",
        "    (function () {",
        "      try {",
        "        var pairs = [];",
        "        document.querySelectorAll('.sl-price-description').forEach(function (copy) {",
        "          var btn = copy.parentNode && copy.parentNode.querySelector('.sl-price-more');",
        "          if (!btn) return;",
        "          pairs.push([copy, btn]);",
        "          btn.addEventListener('click', function (ev) {",
        # Without this the click bubbles to the card and selects the tier -- reading becomes buying.
        "            ev.stopPropagation();",
        "            ev.preventDefault();",
        "            var open = copy.classList.toggle('is-expanded');",
        "            btn.setAttribute('aria-expanded', open ? 'true' : 'false');",
        "            btn.textContent = open ? 'See less' : 'See more';",
        "          });",
        "        });",
        "        var sync = function () {",
        "          pairs.forEach(function (pair) {",
        "            var copy = pair[0], btn = pair[1];",
        "            if (copy.classList.contains('is-expanded')) return;",
        "            btn.hidden = copy.scrollHeight <= copy.clientHeight + 1;",
        "          });",
        "        };",
        "        sync();",
        "        var t; window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(sync, 150); });",
        "      } catch (e) {}",
        "    })();",
        "  </script>",
    ])


def render_view_beacon(page: dict[str, Any], kind: str, api_base_url: str | None) -> str:
    """Count this view, on the PUBLISHED artifact only.

    The gate is the artifact kind, not a runtime check, so preview and test artifacts do not merely skip
    counting -- the script is not in them. A tenant editing their own page all afternoon cannot inflate
    their own numbers, because the page they are looking at has no tracker in it.

    Deliberately minimal: no cookie, no third-party script, no identifier we did not already have. The
    first-party id is a random token in localStorage that survives a changed IP; when storage is
    unavailable the endpoint falls back to a salted hash of IP + user-agent, which dedupes for the day and
    cannot be correlated beyond it. Anything richer than "how many people looked at this" is what the GA4
    and Meta adapters above are for.

    The key is namespaced PER TENANT. It was a bare `sl_vid`, which is correct exactly as long as every Site
    has its own hostname -- localStorage is per-origin, so the tenant boundary was doing the work for free.
    Link-in-bio serving breaks that assumption: `jbay.page/alice` and `jbay.page/bob` are ONE origin, and a
    bare key would have handed unrelated tenants the same visitor identifier, turning a deliberately
    first-party token into a cross-tenant one. Namespacing costs nothing on the hostname-per-Site pages and
    is the difference between first-party and third-party tracking on the shared apex.
    """
    if kind != "published":
        return ""
    page_id = str((page or {}).get("page_id") or "")
    if not page_id:
        return ""
    tenant_id = str(page.get("tenant_id") or "")
    base = str(api_base_url or "").rstrip("/")
    if not base:
        return ""
    return (
        "  <script>\n"
        "    (function () {\n"
        "      try {\n"
        f"        var k = 'sl_vid_' + {json.dumps(tenant_id)}, v = '';\n"
        "        try { v = localStorage.getItem(k) || ''; if (!v) { v = (Math.random().toString(36).slice(2) + Date.now().toString(36)); localStorage.setItem(k, v); } } catch (e) { v = ''; }\n"
        f"        var u = {json.dumps(base)} + '/t/view?p=' + encodeURIComponent({json.dumps(page_id)}) + (v ? '&v=' + encodeURIComponent(v) : '');\n"
        "        if (navigator.sendBeacon) { navigator.sendBeacon(u); }\n"
        "        else { var i = new Image(); i.src = u; }\n"
        "      } catch (e) {}\n"
        "    })();\n"
        "  </script>"
    )


def render_outbound_link_script(page: dict[str, Any], kind: str, api_base_url: str | None) -> str:
    """Everything that happens when a visitor taps an outbound link: counting it, and the age gate.

    ONE script rather than two because both need the same beacon URL, and the age gate has to be able to
    SUPPRESS the count -- a visitor who backs out of the interstitial did not click through to anything, and
    reporting that they did would put a number in the dashboard that no one earned.

    Published artifact only, exactly as the view beacon is: the gate is the artifact kind, so a tenant editing
    their own hub all afternoon has no tracker in the page they are looking at.

    Counting is on `pointerdown` for ordinary links -- a tap that opens a new tab often unloads or backgrounds
    the page before a click handler's beacon flushes, which would under-report on exactly the platform this
    page exists for. Adult links are the exception: they count from the Continue button instead, because
    until then nothing has been followed.

    Still a beacon and not a redirector. `/go/{page}/{link}` would count perfectly and turn the shared
    platform host into an open redirect, which is the abuse surface plans/SOCIAL_MEDIA_PAGES.md §7 exists to
    prevent. A lossy count is the honest price.

    The interstitial reuses `.sl-notice-backdrop` / `.sl-notice-card` -- the page's OWN dialog, added when the
    checkout script needed one because a server-rendered page cannot use the dashboard's ConfirmDialog.vue.
    It is never `window.confirm`: a browser chrome dialog on a creator's page reads as a malware warning.

    **It asks EVERY time, and remembers nothing** (author, 2026-09-11, after checking what linkcloud.ai and
    link.me actually do). Remembering would also mean storage on a shared creator origin, which is the hazard
    plans/SOCIAL_MEDIA_PAGES.md §6 flags for the cart keys -- so the category norm and our architecture agree.

    The wording is hedged on purpose: "may contain" is a claim about the PLATFORM, which is what we know.
    "Contains" would be a claim about the creator, which we do not know and must not assert about a named
    person. And it is an attestation, not age verification -- it earns its place by preventing accidental
    exposure and by demonstrating a content policy, not by stopping anyone determined.
    """
    page_id = str((page or {}).get("page_id") or "")
    base = str(api_base_url or "").rstrip("/")
    # COUNTING is published-only -- a tenant editing their own hub all afternoon must not inflate their own
    # numbers, so the tracker is simply not in the artifact they are looking at.
    #
    # The AGE GATE is not, and conflating the two was a bug: it rendered on nothing but the published artifact,
    # so it could not even be TESTED from a draft's preview link, and anyone the tenant sent that link to got
    # no warning at all. It is a safety control, not analytics. It needs no page id and no API base either, so
    # it survives both being absent.
    counting = kind == "published" and bool(page_id and base)
    return (
        "  <script>\n"
        "    (function () {\n"
        "      try {\n"
        f"        var API = {json.dumps(base)}, PAGE = {json.dumps(page_id)}, COUNT = {'true' if counting else 'false'};\n"
        "        var count = function (a) {\n"
        "          if (!COUNT) { return; }\n"
        "          try {\n"
        "            var v = ''; try { v = localStorage.getItem('sl_vid') || ''; } catch (x) { v = ''; }\n"
        "            var u = API + '/t/view?p=' + encodeURIComponent(PAGE)\n"
        "              + '&l=' + encodeURIComponent(a.getAttribute('data-sl-link'))\n"
        "              + (v ? '&v=' + encodeURIComponent(v) : '');\n"
        "            if (navigator.sendBeacon) { navigator.sendBeacon(u); }\n"
        "            else { var i = new Image(); i.src = u; }\n"
        "          } catch (x) {}\n"
        "        };\n"
        "        document.addEventListener('pointerdown', function (e) {\n"
        "          var a = e.target && e.target.closest ? e.target.closest('[data-sl-link]') : null;\n"
        "          if (a && !a.hasAttribute('data-sl-adult')) { count(a); }\n"
        "        }, true);\n"
        "        document.addEventListener('click', function (e) {\n"
        "          var a = e.target && e.target.closest ? e.target.closest('[data-sl-adult]') : null;\n"
        "          if (!a) { return; }\n"
        "          e.preventDefault();\n"
        "          var o = document.querySelector('.sl-notice-backdrop.sl-age-gate');\n"
        "          if (!o) {\n"
        "            o = document.createElement('div');\n"
        "            o.className = 'sl-notice-backdrop sl-age-gate';\n"
        "            o.innerHTML = '<div class=\"sl-notice-card\" role=\"alertdialog\" aria-modal=\"true\""
        " aria-labelledby=\"sl-age-title\"><div class=\"sl-notice-icon\" aria-hidden=\"true\">18+</div>"
        "<p class=\"sl-notice-msg\" id=\"sl-age-title\">This link may contain adult content. You must be 18"
        " or older to continue.</p><div class=\"sl-notice-actions\">"
        "<button type=\"button\" class=\"sl-notice-cancel\">Cancel</button>"
        "<button type=\"button\" class=\"sl-notice-ok\">Continue (18+)</button></div></div>';\n"
        "            document.body.appendChild(o);\n"
        "            var close = function () { o.classList.remove('is-visible'); o.dataset.href = ''; };\n"
        "            o.addEventListener('click', function (ev) { if (ev.target === o) close(); });\n"
        "            o.querySelector('.sl-notice-cancel').addEventListener('click', close);\n"
        "            o.querySelector('.sl-notice-ok').addEventListener('click', function () {\n"
        "              var href = o.dataset.href || '';\n"
        "              var id = o.dataset.link || '';\n"
        "              if (id) { count({ getAttribute: function () { return id; } }); }\n"
        "              close();\n"
        "              if (href) { window.open(href, '_blank', 'noopener'); }\n"
        "            });\n"
        "            document.addEventListener('keydown', function (ev) {\n"
        "              if (ev.key === 'Escape' && o.classList.contains('is-visible')) { close(); }\n"
        "            });\n"
        "          }\n"
        "          o.dataset.href = a.getAttribute('href') || '';\n"
        "          o.dataset.link = a.getAttribute('data-sl-link') || '';\n"
        "          o.classList.add('is-visible');\n"
        "          var ok = o.querySelector('.sl-notice-ok'); if (ok) { ok.focus(); }\n"
        "        }, true);\n"
        "      } catch (e) {}\n"
        "    })();\n"
        "  </script>"
    )


def _page_is_live(page: dict[str, Any]) -> bool:
    """Whether this page belongs to the LIVE books. Absent means live: every page written before Stripe
    mode existed is a live one, and silently dropping a long-standing tenant's analytics would be a worse
    surprise than the thing this guards."""
    raw = str((page or {}).get("stripe_mode") or "").strip().lower()
    return raw != "test"

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


def render_favicon_tags(seo: dict[str, Any], default_url: str = "", small_default_url: str = "") -> str:
    """The three favicon links.

    A browser fetches `rel="icon"` on first paint of every page, so it gets the SMALL file -- 32x32 at
    ~3KB rather than 200x200 at 30KB, which is roughly 15x oversized for something drawn at 32 pixels.
    `apple-touch-icon` keeps the large one: it genuinely wants a big square, and it is only fetched when
    someone adds the page to a home screen.

    The split applies to the PLATFORM DEFAULT only. A tenant who uploaded their own favicon gave us one
    file at one size, and inventing a smaller URL for it would 404.
    """
    tenant_url = str(seo.get("favicon_url") or "").strip()
    large = tenant_url or str(default_url or "").strip()
    small = tenant_url or str(small_default_url or "").strip() or large
    if not large and not small:
        return ""  # no tenant favicon and no configured default — emit nothing rather than a broken empty href
    small_href = escape(small or large)
    large_href = escape(large or small)
    return "\n".join([
        f"  <link rel=\"icon\" href=\"{small_href}\" sizes=\"32x32\">",
        f"  <link rel=\"shortcut icon\" href=\"{small_href}\">",
        f"  <link rel=\"apple-touch-icon\" href=\"{large_href}\">",
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
    # A video whose control bar is hidden NEEDS this script -- the tap handler is the only thing left that
    # can pause it. Without this flag a page carrying nothing else interactive returned no script at all,
    # and hiding the bar really would have removed the last way to stop the video.
    has_chromeless_video = any(
        section.get("type") == "video" and section.get("hide_controls")
        for section in page.get("sections", [])
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
    if not any([has_countdown, has_price_selector, has_current_year, has_checkout_cta, has_hero_carousel, has_pp_carousel, has_ribbon_download, has_before_after, has_video_embed, has_chromeless_video]):
        return ""
    page_id = escape(str(page.get("page_id") or "page"))
    return "\n".join([
        "  <script>",
        "    document.addEventListener('DOMContentLoaded', () => {",
        "      document.querySelectorAll('[data-sl-current-year]').forEach((node) => {",
        "        node.textContent = String(new Date().getFullYear());",
        "      });",
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
        "          box.appendChild(frame);",
        "        });",
        "      });",
        # CHROMELESS VIDEO. The control bar was hidden, so the video itself becomes the control -- this is
        # what keeps hiding it from being a WCAG 2.2.2 failure rather than a style choice. Click or
        # Enter/Space toggles; the element carries tabindex="0" so a keyboard reaches it at all.
        "      document.querySelectorAll('[data-sl-video-tap]').forEach((video) => {",
        "        const toggle = () => { if (video.paused) { video.play(); } else { video.pause(); } };",
        "        video.addEventListener('click', toggle);",
        "        video.addEventListener('keydown', (event) => {",
        "          if (event.key !== ' ' && event.key !== 'Enter') return;",
        # Space scrolls the page by default, which would move the video out of view as it paused.
        "          event.preventDefault();",
        "          toggle();",
        "        });",
        "      });",
        # BEFORE / AFTER. The range input already handles drag, touch, click-to-jump, keyboard and
        # assistive technology; all that is left is moving its value into the custom property the clip-path
        # and the handle read. Without this the divider simply stays where the tenant authored it, which is
        # a legible side-by-side rather than a broken control.
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
        # One dialog, any number of buttons. `showModal()` gives focus trapping, Escape-to-close and an
        # inert background for free, which a hand-rolled overlay has to earn and usually does not.
        "      const leadDialog = document.querySelector('[data-lead-dialog]');",
        "      if (leadDialog) {",
        "        document.querySelectorAll('[data-lead-open]').forEach((trigger) => {",
        "          trigger.addEventListener('click', () => {",
        "            if (typeof leadDialog.showModal === 'function') { leadDialog.showModal(); }",
        # Older browsers without <dialog>: show it in the flow rather than leaving a dead button. The form
        # is a real form either way, so the only thing lost is the overlay.
        "            else { leadDialog.setAttribute('open', ''); leadDialog.scrollIntoView({behavior: 'smooth', block: 'center'}); }",
        "          });",
        "        });",
        "      }",
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
        # A webinar registration names its session. The picker is a radio group or a hidden input, so one
        # read covers both; the event id rides the form so the server can resolve the occurrence without
        # trusting anything else the page says about it.
        "          const occurrence = leadForm.querySelector('[name=\"occurrence_id\"]:checked')",
        "            || leadForm.querySelector('input[type=\"hidden\"][name=\"occurrence_id\"]');",
        "          if (occurrence && occurrence.value && leadForm.dataset.eventId) {",
        "            payload.event_id = leadForm.dataset.eventId;",
        "            payload.occurrence_id = occurrence.value;",
        "          }",
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
        "              const slideIndex = Math.round(convTrack.scrollLeft / convTrack.clientWidth);",
        # The slide SAYS which target it stands for. Falling back to the ordinal keeps a page published
        # before this attribute existed behaving exactly as it did.
        "              const slide = convTrack.children[slideIndex];",
        "              const declared = slide && slide.dataset ? slide.dataset.convIndex : undefined;",
        "              const index = declared === undefined || declared === '' ? slideIndex : Number(declared);",
        # Range-checked HERE as well as inside applyTarget: applyTarget returning early still left the
        # emit firing, so an out-of-range slide told every listener to switch to a target that does not
        # exist -- which hides a listicle's tier block and leaves nothing to add to the cart.
        "              if (index !== currentIndex && index >= 0 && index < convTargets.length) {",
        "                applyTarget(index); emit('conversion:itemChanged', { index: index, target: convTargets[index] });",
        "              }",
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
        "          const applyServerCart = (data) => { if (data && data.cart) { serverCart = data.cart; if (data.cart_id) setCartId(data.cart_id); } renderMinicart(); publishCart(); };",
        # The shipping element quotes the CART when there is one, so it has to know the cart exists and
        # when it changes. A buyer with three things in their basket was being shown one item's postage,
        # and the number never moved as they added more (author, 2026-10-01).
        "          const publishCart = () => {",
        "            window.__jbCartId = getCartId();",
        "            try { document.dispatchEvent(new CustomEvent('sl:cart-changed')); } catch (e) {}",
        "          };",
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
        "              const nextp = new URLSearchParams(); nextp.set('outcome', 'accept'); if (tenantId) nextp.set('tenant_id', tenantId); nextp.set('mode', cartMode); nextp.set('origin', window.location.origin);",
        "              cartSuccessUrl = `${cartApiBase}/pages/${cartPageId}/post-checkout/next?${nextp.toString()}&session_id={CHECKOUT_SESSION_ID}`;",
        "            }",
        # A coupon the visitor applied on the page rides along with the CART too, not just the single-offer
        # CTA. Until 2026-09-23 the cart body carried no coupon at all and the handler never looked for one,
        # so a cart paid full price however the buyer arrived.
        "            fetch(cartEndpoint + '/checkout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_id: tenantId, cart_id: id, mode: cartMode, page_id: cartPageId, coupon: window.__jbCoupon || '', ship_to_country: window.__jbShipTo || '', shipping_quote: window.__jbShipQuote || '', shipping_service: window.__jbShipService || '', success_url: cartSuccessUrl, cancel_url: ret + '?checkout=cancel' }) })",
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
        # Leaving a slide must silence it. Otherwise a YouTube and a Vimeo embed play over each other and
        # the visitor cannot see which one is making the noise -- the iframe is off-screen by then.
        "          heroCarousel.querySelectorAll('.sl-hero-slide').forEach((slide, i) => {",
        "            if (i === index) return;",
        "            slide.querySelectorAll('video').forEach((v) => { if (!v.paused) v.pause(); });",
        "            slide.querySelectorAll('[data-sl-embed] iframe').forEach((f) => f.remove());",
        "          });",
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
        # One-time vs repeating. The tenant offers ONE interval; this is the supporter choosing whether to
        # use it, so a recurring jar still takes one-off tips.
        "      const tipFreq = document.querySelector('[data-tip-frequency]');",
        "      const tipRecurring = () => Boolean(tipFreq && tipFreq.dataset.tipChosen === 'recurring');",
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
        # The funnel step is a LOOKUP in the buyer's Stripe mode: post_checkout resolves the mode from this
        # request and reads pages/offers/products in it. `resolve_stripe_mode` defaults to TEST when it is
        # absent (fail-safe, so a forgetful caller cannot touch live data), which made a live funnel search
        # `PAGE#test#...` for a page stored at `PAGE#live#...` and answer "Page not found." A test purchase
        # matched the default and worked, so only live buyers ever saw it.
        "        next.set('mode', cta.dataset.checkoutMode || 'test');",
        "        next.set('origin', window.location.origin);",
        "        return `${cta.dataset.checkoutApiBaseUrl}/pages/${funnelPageId || cta.dataset.checkoutPageId}/post-checkout/next?${next.toString()}`;",
        "      };",
        "      const successUrl = () => {",
        "        const current = pageUrl();",
        "        if (cta && cta.dataset.checkoutApiBaseUrl && cta.dataset.checkoutHasPostCheckout === 'true') {",
        "          const next = new URLSearchParams();",
        "          next.set('outcome', 'accept');",
        "          if (cta.dataset.checkoutTenantId) next.set('tenant_id', cta.dataset.checkoutTenantId);",
        "          next.set('mode', cta.dataset.checkoutMode || 'test');",  # the funnel step is a lookup in this mode
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
        # Which SERVICE the buyer picked. A choice offer's cards are alternatives, and without this the
        # checkout could not tell them apart: the service cards carry data-service-id with an EMPTY
        # data-product-id, so product_id/price_id alone said nothing about which one was selected.
        "        const serviceId = card?.dataset.serviceId || '';",
        "        const quantity = card?.dataset.quantity || cta.dataset.checkoutQuantity || '1';",
        "        if (cta.dataset.checkoutTenantId) params.set('clientID', cta.dataset.checkoutTenantId);",
        "        if (cta.dataset.checkoutOfferId) params.set('offer', cta.dataset.checkoutOfferId);",
        "        if (cta.dataset.checkoutPageId) params.set('page_id', cta.dataset.checkoutPageId);",
        "        params.set('mode', cta.dataset.checkoutMode || 'test');",
        "        if (productId) params.set('product_id', productId);",
        "        if (serviceId) params.set('service_id', serviceId);",
        "        if (priceId) params.set('price_id', priceId);",
        "        if (quantity) params.set('quantity', quantity);",
        # A TIP JAR line has no per-amount Stripe price: the buyer's choice travels as tip_amount and the
        # server re-decides it (a preset must be one it offers; a typed amount must sit in the platform's
        # range). tipKeyed is what the supporter typed, BEFORE fees -- the charge is the server's to compute.
        "        if (card?.dataset.tipSource && tipRecurring()) params.set('tip_recurring', '1');",
        "        if (card?.dataset.tipSource) {",
        "          const keyed = card.dataset.tipSource === 'custom' ? card.dataset.tipKeyed : card.dataset.tipAmount;",
        "          if (keyed) { params.set('tip_amount', keyed); params.set('tip_source', card.dataset.tipSource); }",
        "        }",
        "        const current = pageUrl();",
        "        params.set('success_url', successUrl());",
        "        params.set('cancel_url', current);",
        # A coupon the visitor applied on the page rides along with WHICHEVER card they picked. The ticket
        # used to be a direct link built at publish from the offer's FIRST item, so on a tiered or
        # multi-product offer it sent everyone to tier one regardless of their choice (found 2026-09-22).
        "        if (window.__jbCoupon) params.set('coupon', window.__jbCoupon);",
        # Where the buyer said to send it, if a shipping element asked. This NARROWS Stripe's allowed
        # countries to that one, so a buyer quoted for Canada cannot switch to the US at the pay button and
        # pay Canadian postage (plans/SHIPPING_ELEMENT.md phase 5).
        "        if (window.__jbShipTo) params.set('ship_to_country', window.__jbShipTo);",
        # The QUOTE and the SERVICE, never the amount (plans/LIVE_SHIPPING_RATES.md phase 3). The server
        # looks the price up on its own row, so the worst a tampered parameter can do is name a service
        # that is not in the quote -- which falls back to the quote's own cheapest option. Until this
        # shipped the radio buttons were decorative: the buyer's choice never left the page.
        "        if (window.__jbShipQuote) params.set('shipping_quote', window.__jbShipQuote);",
        "        if (window.__jbShipService) params.set('shipping_service', window.__jbShipService);",
        "        const separator = cta.dataset.checkoutBaseUrl.includes('?') ? '&' : '?';",
        "        return `${cta.dataset.checkoutBaseUrl}${separator}${params.toString()}`;",
        "      };",
        "      const currentAmount = (card) => card?.dataset.expired === 'true' ? card.dataset.regularAmount : card?.dataset.saleAmount;",
        # Applying a coupon deliberately does NOT restate the price. The card already carries a
        # strike-through and a "Save X%" badge, and a second recalculation invites the question "is this
        # before or after my code?". It is also the only version that stays true under restrictions the
        # browser cannot evaluate. The discount lands at checkout, the way an electronic coupon at a
        # supermarket till does (author, 2026-09-22).
        "      const coupon = document.querySelector('[data-section-type=\"coupon\"][data-coupon-code]');",
        "      if (coupon) {",
        # A TARGETED code cannot be baked into the page: one artifact is published for everyone, so the
        # code minted for a single recipient reaches them in their OWN link (COUPONS_COMPLETION.md C5).
        # It is accepted only when it belongs to the campaign shown here, so a stray ?coupon= on somebody
        # else's link changes nothing -- and the server still decides whether it is honoured at all.
        "        const grantPrefix = (coupon.dataset.couponGrantPrefix || '').toUpperCase();",
        "        const personal = (new URLSearchParams(location.search).get('coupon') || '').toUpperCase();",
        "        if (grantPrefix && /^[A-Z0-9_-]{4,200}$/.test(personal)"
        " && personal.startsWith(grantPrefix + '-')) {",
        "          coupon.dataset.couponCode = personal;",
        "          const shownCode = coupon.querySelector('.sl-coupon-code');",
        "          if (shownCode) shownCode.textContent = personal;",
        "        }",
        "        const applyCoupon = (event) => {",
        "          if (!cta || !cta.dataset.checkoutBaseUrl) return;   // no checkout here: let the link be",
        "          if (event) event.preventDefault();",
        "          window.__jbCoupon = coupon.dataset.couponCode || '';",
        "          coupon.classList.add('is-applied');",
        "          const live = coupon.querySelector('.sl-coupon-applied');",
        "          if (live) live.hidden = false;",
        # Re-point the CTA at the card the visitor already has selected, the same expression the script's
        # own bootstrap uses -- a fresh href is what carries the code.
        "          updateCta(document.querySelector('.sl-price-option.selected') || document.querySelector('.sl-price-option'));",
        "        };",
        "        coupon.addEventListener('click', applyCoupon);",
        "      }",
        "      const updateCta = (card) => {",
        "        if (!cta || !card) return;",
        "        const amount = currentAmount(card);",
        "        const currency = card.dataset.currency || cta.dataset.ctaCurrency || 'usd';",
        "        const label = cta.dataset.ctaLabel || 'Checkout';",
        "        cta.dataset.ctaAmount = amount || '0';",
        "        cta.href = checkoutHref(card);",
        # The tip box with nothing typed in it: the CTA says what is missing instead of offering to charge
        # $0.00, and refuses the click (below) rather than letting the server answer with an error page.
        "        const needsTip = card.dataset.tipSource === 'custom' && !card.dataset.tipKeyed;",
        "        cta.dataset.tipNeedsAmount = needsTip ? 'true' : 'false';",
        "        if (needsTip) { cta.textContent = 'Enter an amount'; return; }",
        # An upsell CTA bakes the price into its label, so don't re-append the amount (avoids '$X - $X').
        "        const every = tipRecurring() && tipFreq ? ` / ${tipFreq.dataset.tipWord || 'monthly'}` : '';",
        "        cta.textContent = cta.dataset.ctaHideAmount === 'true' ? label : `${label} - ${money(amount, currency)}${every}`;",
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
        "          if (cta.dataset.tipNeedsAmount === 'true') {",
        "            event.preventDefault();",
        "            const box = document.querySelector('.sl-tip-custom [data-tip-input]');",
        "            if (box) box.focus();",
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
        # --- Tip jar: the "Other" card is a box, and what it charges depends on who pays the fees.
        # The figure shown comes from the SERVER's own calculation (/prices/calculate, the same endpoint the
        # authoring form uses) rather than from a copy of the fee formula living in this script -- a second
        # implementation of the fee maths is how the number on the button and the number on the statement
        # come to disagree. Standard fees need no call at all: the tip IS the charge.
        "      if (tipFreq) {",
        "        const tipFreqWord = tipFreq.dataset.tipWord || 'monthly';",
        "        const options = Array.from(tipFreq.querySelectorAll('[data-tip-frequency-value]'));",
        "        const applyFrequency = (value) => {",
        "          tipFreq.dataset.tipChosen = value;",
        "          options.forEach((option) => {",
        "            const on = option.dataset.tipFrequencyValue === value;",
        "            option.classList.toggle('is-selected', on);",
        "            option.setAttribute('aria-pressed', on ? 'true' : 'false');",
        "          });",
        # Every card restates it, so whichever amount is selected says what it is about to charge.
        "          document.querySelectorAll('[data-tip-freq]').forEach((label) => {",
        "            label.textContent = value === 'recurring' ? tipFreqWord : 'one-time';",
        "          });",
        "          const current = document.querySelector('.sl-price-option.selected') || cards[0];",
        "          updateCta(current);",
        "        };",
        "        options.forEach((option) => option.addEventListener('click', () => applyFrequency(option.dataset.tipFrequencyValue)));",
        "        applyFrequency(tipFreq.dataset.tipChosen || 'recurring');",
        "      }",
        "      const tipCard = document.querySelector('.sl-tip-custom');",
        "      if (tipCard) {",
        "        const tipInput = tipCard.querySelector('[data-tip-input]');",
        "        const tipNote = tipCard.querySelector('[data-tip-note]');",
        "        const tipCurrency = tipCard.dataset.currency || 'usd';",
        "        const tipMin = Number(tipCard.dataset.tipMin || 100);",
        "        const tipMax = Number(tipCard.dataset.tipMax || 50000);",
        "        const tipRange = `${money(tipMin, tipCurrency)} to ${money(tipMax, tipCurrency)}.`;",
        # The card's own endpoint first: a PREVIEW has no checkout_url, so the CTA carries no api base, and
        # reading it off the CTA made the box quote the tip without its fees (author, 2026-09-13).
        "        const tipBase = tipCard.dataset.tipApi || (cta && cta.dataset.checkoutApiBaseUrl) || '';",
        "        const tipTenant = tipCard.dataset.tipTenant || (cta && cta.dataset.checkoutTenantId) || '';",
        "        const tipApi = tipBase ? `${tipBase}/prices/calculate` : '';",
        "        let tipSeq = 0;",
        "        const setTip = (keyed, charge, note) => {",
        "          tipCard.dataset.tipKeyed = keyed ? String(keyed) : '';",
        "          tipCard.dataset.saleAmount = charge ? String(charge) : '0';",
        "          if (tipNote) tipNote.textContent = note;",
        "          if (tipCard.classList.contains('selected')) updateCta(tipCard);",
        "        };",
        "        const tipChanged = async () => {",
        "          const keyed = Math.round(Number(tipInput.value || 0) * 100);",
        "          if (!keyed) { setTip(0, 0, tipRange); return; }",
        "          if (keyed < tipMin || keyed > tipMax) { setTip(0, 0, `Please choose ${tipRange}`); return; }",
        "          const feeHandling = tipCard.dataset.tipFeeHandling || 'standard';",
        "          if (feeHandling === 'standard') {",
        # The creator absorbs the fees, so the tip IS the charge -- no round trip, and nothing to add.
        "            setTip(keyed, keyed, `You will be charged ${money(keyed, tipCurrency)}.`);",
        "            return;",
        "          }",
        "          if (!tipApi || !tipTenant) {",
        # Fees apply but we cannot price them here. Say so, rather than quote a total that is wrong by
        # exactly the fees -- the server adds them at checkout either way.
        "            setTip(keyed, keyed, `${money(keyed, tipCurrency)} plus the card and platform fees.`);",
        "            return;",
        "          }",
        "          const seq = ++tipSeq;",
        "          setTip(keyed, keyed, 'Working out the total...');",
        "          try {",
        "            const response = await fetch(tipApi, {",
        "              method: 'POST',",
        "              headers: { 'Content-Type': 'application/json' },",
        "              body: JSON.stringify({",
        "                tenant_id: tipTenant,",
        "                tenant_keyed_amount: keyed,",
        "                currency: tipCurrency,",
        "                product_type: tipCard.dataset.tipProductType || 'digital',",
        "                pricing_model: 'customer_chooses',",
        "                fee_handling: feeHandling,",
        "              }),",
        "            });",
        "            const data = await response.json();",
        "            if (seq !== tipSeq) return;",   # a later keystroke already won
        "            const charge = Number(data && data.unit_amount) || keyed;",
        "            setTip(keyed, charge, charge > keyed",
        "              ? `You will be charged ${money(charge, tipCurrency)} — ${money(charge - keyed, tipCurrency)} covers the fees.`",
        "              : `You will be charged ${money(charge, tipCurrency)}.`);",
        "          } catch (err) {",
        # The server prices it again at checkout, so a failed estimate must not block the tip -- it only
        # means we cannot promise the total here.
        "            if (seq === tipSeq) setTip(keyed, keyed, `${money(keyed, tipCurrency)} plus the card and platform fees.`);",
        "          }",
        "        };",
        "        let tipTimer = 0;",
        "        tipInput.addEventListener('input', () => {",
        "          selectCard(tipCard);",
        "          window.clearTimeout(tipTimer);",
        "          tipTimer = window.setTimeout(tipChanged, 350);",
        "        });",
        "        tipInput.addEventListener('change', () => { window.clearTimeout(tipTimer); tipChanged(); });",
        "      }",
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
        # `&offer=` so the response can carry the postage this upsell will add. The accept label states a
        # price, and charging more than it says is a misstatement to a buyer
        # (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P1).
        "        fetch(`${cta.dataset.checkoutApiBaseUrl}/upsell/session?session_id=${encodeURIComponent(funnelSessionId)}&clientID=${encodeURIComponent(cta.dataset.checkoutTenantId || '')}&offer=${encodeURIComponent(cta.dataset.checkoutOfferId || '')}&product_id=${encodeURIComponent(cta.dataset.checkoutProductId || '')}&mode=${encodeURIComponent(cta.dataset.checkoutMode || 'test')}`)",
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
        # Said out loud, beside the button, rather than folded into its number: the label is the tenant's
        # own words and rewriting their price inside it would be a different kind of lie.
        "            const ship = (body && body.shipping) || {};",
        "            if (ship.amount > 0) {",
        "              const line = document.createElement('p');",
        "              line.className = 'sl-upsell-shipping';",
        "              try { line.textContent = '+ ' + (ship.amount/100).toLocaleString(undefined,{style:'currency',currency:'USD'}) + ' shipping'; }",
        "              catch (e) { line.textContent = '+ $' + (ship.amount/100).toFixed(2) + ' shipping'; }",
        "              if (!cta.parentNode.querySelector('.sl-upsell-shipping')) cta.parentNode.insertBefore(line, cta.nextSibling);",
        "            }",
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
        "            .catch((err) => {",
        "              cta.dataset.connecting = 'false';",
        "              cta.removeAttribute('aria-disabled');",
        "              cta.classList.remove('is-connecting');",
        # THE REASON, not a guess at it. This said 'Card declined' for every failure -- a 400, a 500, a
        # dropped connection -- so a buyer whose card was fine was told it was not, and the tenant
        # debugging it had nothing to go on (2026-10-05). The card IS the likely cause, so it stays the
        # fallback, but a server that explained itself is believed over our guess.
        "              cta.textContent = (err && err.message) ? err.message : 'Card declined - try again';",
        "              try { console.error('[upsell] charge failed:', err); } catch (e) {}",
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
        "        const digits = section.querySelector('[data-countdown-digits]');",
        "        const label = section.querySelector('[data-countdown-label]');",
        # A DEADLINE is an absolute moment: everyone sees the same number, so there is nothing to persist
        # and nothing to restart. A DURATION is this visitor's own clock, which is what localStorage below
        # is for -- mixing the two would let a stored duration override the date the tenant set.
        "        const deadlineMode = section.dataset.mode === 'deadline';",
        "        const endsAt = Number(section.dataset.endsAt || 0);",
        "        if (!display && !digits) return;",
        "        if (deadlineMode ? !endsAt : !duration) return;",
        "        const persistent = !deadlineMode && section.dataset.persistent === 'true';",
        # Funnel-step timers scope to the session so a NEW purchase gets a fresh clock (a prior run may have
        # stored 'expired'); landing-page persist timers stay page-scoped, persisting across visits as intended.
        "        const cdScope = (isFunnelStep && funnelSessionId) ? ':' + funnelSessionId : '';",
        "        const storageKey = `stripe-link:${pageId}${cdScope}:countdown:${section.dataset.sectionId || 'timer'}`;",
        "        let deadline = deadlineMode ? endsAt * 1000 : Date.now() + duration * 1000;",
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
        "        const pad = (n) => String(n).padStart(2, '0');",
        "        const render = () => {",
        "          const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));",
        "          if (digits) {",
        "            const set = (k, v) => { const el = digits.querySelector(`[data-countdown-${k}]`); if (el) el.textContent = v; };",
        "            set('days', String(Math.floor(remaining / 86400)));",
        "            set('hours', pad(Math.floor((remaining % 86400) / 3600)));",
        "            set('minutes', pad(Math.floor((remaining % 3600) / 60)));",
        "            set('seconds', pad(remaining % 60));",
        "          } else if (deadlineMode) {",
        # Days only once there ARE days: "0d 00:04:12" on the last afternoon of a sale reads as broken.
        "            const d = Math.floor(remaining / 86400);",
        "            const h = Math.floor((remaining % 86400) / 3600);",
        "            const body = `${pad(h)}:${pad(Math.floor((remaining % 3600) / 60))}:${pad(remaining % 60)}`;",
        "            display.textContent = d ? `${d}d ${body}` : body;",
        "          } else {",
        "            const minutes = Math.floor(remaining / 60);",
        "            const seconds = String(remaining % 60).padStart(2, '0');",
        "            display.textContent = `${minutes}:${seconds}`;",
        "          }",
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
        # A DEADLINE cannot be re-armed: it is a moment, not a stopwatch, and a downsell does not move
        # Black Friday. Without this the restart would set `deadline = now + 0`, expiring it instantly and
        # firing the funnel's decline path again on a page that had simply reached its date.
        "          if (deadlineMode) return;",
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
        "          next.set('mode', ppMode);",  # the funnel step is a lookup in this mode
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
        "              .catch((err) => {",
        "                btn.dataset.connecting = 'false';",
        "                btn.removeAttribute('aria-disabled');",
        # Same reasoning as the sequential upsell above: say what happened.
        "                btn.textContent = (err && err.message) ? err.message : 'Card declined - try again';",
        "                try { console.error('[upsell] add failed:', err); } catch (e) {}",
        "              });",
        "          });",
        "        });",
        "      }",
        "    });",
        "  </script>",
    ])
