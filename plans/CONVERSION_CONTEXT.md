# Conversion Context — offer-driven landing page rendering

Status: **proposed** (design; author-approved direction 2026-07-13). Formalizes the offer-as-contract +
CTA-component work already shipped. Supersedes the ad-hoc listicle sync (price card listening to the hero's
scroll; field-populated hero images) with a single shared model.

## The reframe

Not "Landing Page → references Offer" but:

```
Offer → provides Conversion Context → Landing Page components render that context
```

A landing page holds **layout only**. Every product fact (image, name, description, badges, price, CTA)
comes from the offer. No component loads products, prices, or discounts; they all read the same context.
The carousel changes one number — `currentItemIndex` — and hero, price card, and CTA all follow. No
component talks to another.

## The constraint that shapes it (locked)

Published pages are **server-rendered (Python, `runtime/html.py`)** for SEO/perf/no-framework; the Vue
components live only in the **builder preview**. So the Conversion Context is a **data contract realized
twice**, not a single Vue provide:

- **Published** → the Python renderer builds it; section renderers read it; **one JS island** owns
  `currentItemIndex` and syncs the DOM.
- **Preview** → a Vue `useConversionContext` composable (`provide`/`inject`); section + CTA components
  inject it.

Same contract, two consumers. (Vue-everywhere/SSR was considered and rejected — too big a platform shift.)

## Locked decisions

1. **Expand on read.** The API expands each offer item's `product_id` into a lightweight **product
   snapshot** when returning an offer; **storage stays normalized**. Renderers do **zero** lookups.
2. **Shared contract, two renderers** (above).
3. **Registry-based rendering** for both sections and CTAs.
4. **Sections are declarative** — drop per-section `offer_id`; the page references one offer at the
   document level, and every section renders from the shared context.

## The ExpandedOffer contract (expand on read)

```jsonc
{
  "offer_id": "...",
  "offer_type": "single | bundle | listicle",
  "presentation": { "cta": { "type": "...", "label": "...", "target": "..." }, ... },
  "items": [
    {
      "product": {                 // snapshot, expanded by the API from product_id (not stored)
        "product_id": "...",
        "headline": "...", "subheadline": "...",
        "hero_image": "...", "gallery": ["...", "..."],
        "badges": [...]
      },
      "pricing": {
        "default_price_id": "...",
        "single_unit_price": { "price_id": "...", "unit_amount": 5201, "compare_at_amount": 6900, "currency": "usd" },
        "selectable_prices": [ ... ]
      }
    }
  ]
}
```

- Built by a domain function (`expand_offer(offer, products_by_id, services_by_id)`) reused by the page
  render, the offers GET (`?expand=1`), and the preview resolve. Single source of truth for the shape.
- `single_unit_price` uses the existing `single_unit_price` resolver; `selectable_prices` the existing
  landing-page price logic. Services expand the same way (service snapshot + price).

## ConversionContext

```
ConversionContext {
  offer: ExpandedOffer         // immutable
  page: {                      // mutable UI state
    currentItemIndex: number
    selectedPriceId: string | null
    quantity: number
    couponCode?: string
  }
  currentItem   // = offer.items[page.currentItemIndex]
  selectedPrice // resolved from currentItem.pricing + page.selectedPriceId
}
```

Immutable offer data separated from transient interaction state.

## Component responsibilities (identical intent in both renderers)

- **HeroMedia** — shows `currentItem.product.hero_image` (+ gallery). One item → image; multiple →
  carousel automatically. On slide change → `currentItemIndex = n`. Nothing else.
- **Hero** — `currentItem.product.headline/subheadline`. Follows the index.
- **OfferSelector** — `currentItem.pricing.selectable_prices` (single/bundle); for a listicle it's the
  syncing single-unit **price card**. Selecting → `selectedPriceId`.
- **CTA** — reads `offer.presentation.cta.type`, renders via the **CTA registry**
  (buy / email_capture / phone_call / download / appointment / external). BuyCTA reads `selectedPrice`.

## Registries

- **Section registry**: `type → renderer` (Python fn / Vue component). Adding a section = register one.
- **CTA registry**: `cta.type → renderer`. Adding a CTA type = register one. (We already branch by type;
  this formalizes it.)

## Declarative sections

```jsonc
[ { "type": "hero_media" }, { "type": "hero" }, { "type": "offer_selector" }, { "type": "cta" } ]
```

No `offer_id` per section. The renderer is generic; inconsistencies (the "which offer?" per section)
become impossible.

## Carousel / sync flow

Load → `currentItemIndex = 0` → Hero/Pricing/CTA render item 0. User swipes → `currentItemIndex = 2` →
all three re-render for item 2. **No inter-component events, no prop drilling — only shared state.**
Published: the JS island sets the index on hero scroll/nav and re-renders the DOM sections from embedded
per-item data. Preview: Vue reactivity does it.

## Phasing (per the proposal — infra first, keep the renderer working throughout)

### Phase 1 — Infrastructure (no new UI features)
- `expand_offer()` domain fn + `ExpandedOffer` shape; offers GET `?expand=1`.
- Section registry (server dict + Vue map) — refactor existing sections onto it.
- CTA registry (server + Vue) — refactor the existing per-type CTA branch onto it.
- Shared context: server = one JS island owning `currentItemIndex`; preview = `useConversionContext`.
- Refactor hero_media / hero / offer_selector / cta to read the context (replaces the listicle
  scroll-listener hack + field-driven hero with `currentItemIndex`).

### Phase 2 — Capabilities on the new foundation
- Listicle fully on the context (hero carousel ↔ price card ↔ CTA all via `currentItemIndex`).
- CTA registry filled out (download / appointment / … as needed).
- Future context-aware blocks: testimonials, FAQ, comparison, guarantees that react to `currentItem`.

## What we already have (so this is incremental, not a rewrite)
- Offer-as-contract `presentation` snapshot; per-type CTA rendering; `single_unit_price`; the hero +
  listicle carousels. Phase 1 mostly **reorganizes** these behind the context + registries; the
  offer-driven listicle hero (shipped) is the first piece.

## Relationship to other plans
- Builds on `LANDING_PAGE_CTA_AND_COMPOSITION.md` (CTA components → registry) and
  `LISTICLE_AND_CART.md` (listicle → the first real multi-item consumer of the context).
- The cart (LISTICLE_AND_CART L2) becomes a `page`-context concern (`selectedPrice`/cart), clean to add.
