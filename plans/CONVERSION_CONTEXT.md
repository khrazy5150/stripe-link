# Conversion Context — offer-driven landing page rendering

Status: **proposed** (design; author-approved direction 2026-07-13). Formalizes the offer-as-contract +
CTA-component work already shipped. Supersedes the ad-hoc listicle sync (price card listening to the hero's
scroll; field-populated hero images) with a single shared model.

## The reframe — a page is a *conversion*, not an offer

Not "Landing Page → references Offer" but:

```
Offer → provides Conversion Context → Landing Page components render that context
```

The deeper reframe (review point 8): stop thinking "Offer" and think **"what is the user trying to do on
this page?"** — buy, subscribe, book, download, call, join. Every page is a **conversion**. Pricing, CTA,
hero, carousel, listicle, bundle, services are all describing that one thing. `ConversionContext` is
deliberately named for it; the abstraction is the conversion, and the offer is its data.

A landing page holds **layout only**. Every product fact (image, name, description, badges, price, CTA)
comes from the context. No component loads products, prices, or discounts; they all read the same context.
Changing one thing — the **current target** (below) — makes hero, price card, and CTA all follow. No
component talks to another.

## The constraint that shapes it (locked)

Published pages are **server-rendered (Python, `runtime/html.py`)** for SEO/perf/no-framework; the Vue
components live only in the **builder preview**. So the Conversion Context is a **data contract realized
twice**, not a single Vue provide:

- **Published** → the Python renderer builds it; section renderers read it; **one JS island** owns the
  current-target index and syncs the DOM, and emits the event model (below).
- **Preview** → a Vue `useConversionContext` composable (`provide`/`inject`); section + CTA components
  inject it.

Same contract, two consumers. (Vue-everywhere/SSR was considered and rejected — too big a platform shift.)

## Locked decisions (incl. the 2026-07-13 review refinements)

1. **Expand on read.** The API expands each offer item's `product_id`/`service_id` into a lightweight
   snapshot when returning an offer; **storage stays normalized**. Renderers do **zero** lookups.
2. **Shared contract, two renderers** (above).
3. **Registry-based rendering** for sections and CTAs — and registries carry **metadata**, not just a
   component (see Registries).
4. **Sections are declarative** — drop per-section `offer_id`; every section renders from the context.
5. **`OfferView`, not `ExpandedOffer`** (review 3). It's a **rendering projection**, not merely an
   expansion — later it also projects inventory/shipping/reviews/videos, which aren't "expanded." Names
   survive years; call it what it is.
6. **`currentTarget`, not `currentItem`** (review 1). The core cursor is **semantic**, not listicle-only.
   Today `currentTarget = offer.items[index]`; tomorrow it may be `selectedService` / `selectedMembership`
   / `selectedLeadOffer` **without changing any component**. Never bake "items" into the core.
7. **Read-only `derived` values** (review 5). Components **display**, never compute. All calculations live
   in `derived`.
8. **CTAs are plugins that own their own validation** (review 2) — `render / validate / serialize /
   execute`. The renderer never knows validation rules.
9. **Media is its own concern** (review 4). A `MediaViewer` handles *rendering modes* (image / carousel /
   video / gallery / 360); `Hero` doesn't own the carousel.
10. **Semantic event model** (review addition) — the context emits `conversion:*` events so analytics /
    pixels / A-B / affiliate subscribe without coupling to UI.
11. **A hydration contract** (review 2026-07-13) — the *whole* OfferView is serialized once into the page,
    and sections bind to it through **standardized `data-conversion-*` attributes**, so the JS island is
    never brittle about DOM selection. See "Published hydration contract."
12. **Localization is page state, not baked at read** (review 2026-07-13) — currency/locale live in the
    mutable `page` state (visitor-scoped, e.g. from geo/IP), and the OfferView pricing must not lock to a
    single currency. `derived` resolves the displayed price. See "Localization."

## The `OfferView` contract (expand on read)

An `OfferView` is the **rendering projection** of an offer (review 3): everything required for the
**first render**, denormalized.

```jsonc
{
  "offer_id": "...",
  "offer_type": "single | bundle | listicle",
  "presentation": { "cta": { "type": "...", "label": "...", "target": "..." }, ... },
  "targets": [                       // "targets", not "items" — a target is what the user converts on
    {
      "kind": "product | service",
      "product": {                   // snapshot, projected from product_id (not stored)
        "product_id": "...", "headline": "...", "subheadline": "...",
        "hero_image": "...", "gallery": ["...", "..."], "badges": [...]
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

- Built by one domain function (`expand_offer()` → returns an `OfferView`; **shipped**, currently keyed
  `items` — rename to `targets` when the context lands). Reused by page render, offers `?expand=1`, preview.
- **Lazy is allowed** (review 6): *The `OfferView` contains everything required for first render.
  Section-specific data (reviews, live inventory, shipping estimates) may be loaded lazily by individual
  sections.* Don't project 50k reviews into the first payload.

## ConversionContext

```
ConversionContext {
  offer: OfferView              // immutable
  page: {                       // mutable UI state
    currentTargetIndex: number
    selectedPriceId: string | null
    quantity: number
    couponCode?: string
    locale?: string             // visitor-scoped (geo/IP) — see Localization
    currency?: string           // active display currency; may differ from the OfferView's base
  }
  derived: {                    // read-only; components display these, never compute
    currentTarget              // = offer.targets[page.currentTargetIndex]
    selectedPrice              // resolved for page.currency/locale
    unitPrice                  // localized
    discountPercent
    total                      // localized
    ctaLabel
  }
  emit(event, payload)          // semantic events (see Event Model)
}
```

Immutable projection, mutable interaction state, read-only derived values — cleanly separated.

## Component responsibilities (identical intent in both renderers)

- **MediaViewer** (not "HeroMedia") — displays `derived.currentTarget.product` media in a **mode**
  (image / carousel / video / gallery / 360), delegating to an `ImageRenderer` / `CarouselRenderer` /
  `VideoRenderer`. On slide change → `currentTargetIndex = n` + `emit('conversion:itemChanged')`. It grows
  by adding *modes*, not responsibilities.
- **Hero** — `derived.currentTarget.product.headline/subheadline`. Follows the cursor.
- **OfferSelector** — `derived.currentTarget.pricing.selectable_prices` (single/bundle) or the syncing
  single-unit **price card** (listicle). Selecting → `selectedPriceId` + `emit('conversion:priceChanged')`.
- **CTA** — reads `offer.presentation.cta.type`, renders the plugin from the **CTA registry**; the plugin
  reads `derived` (e.g. BuyCTA → `derived.selectedPrice`, label `derived.ctaLabel`).

## Actions — `presentation.actions[]` + ActionBar (review 2026-07-14)

The CTA is not one button — it's an **ordered list of actions** rendered by a generic **ActionBar**. "CTA
Registry" is renamed **Action Registry** ("action" is broader than "button": submit a form, launch
checkout, add to cart, start a call, copy a coupon, download, open WhatsApp — the button is just one
presentation of it).

```jsonc
"presentation": {
  "layout": "single | split | stack | floating",   // how the ActionBar arranges its buttons
  "actions": [
    { "type": "buy_now", "label": "Buy Now" },
    { "type": "add_to_cart", "label": "Add to Cart" }   // a listicle simply has two
  ]
}
```

- **No special code per page type.** Normal → `[buy_now]`; listicle → `[buy_now, add_to_cart]`; lead →
  `[submit_form]`; phone → `[call_phone]`; redirect → `[redirect]`.
- **ActionBar** only *arranges* actions (`v-for` / a loop) by `layout`. It knows nothing about them.
- **Each action is a plugin** in the Action Registry: `render / execute / validate` + `icon / label /
  enabled`. `buy_now`, `add_to_cart`, `submit_form`, `call_phone`, `sms`, `download`, `appointment`,
  `redirect`, `external_checkout`, `whatsapp`, … Adding one = one plugin, no ActionBar/schema change.
- **The sticky footer is an ActionBar too** — one button, a split, or a non-commerce action, all the same.
- **Back-compat, no breaking migration:** the resolver reads `presentation.actions[]` if present, else
  derives a one-element list from the legacy `presentation.cta` (buy→buy_now, email→submit_form,
  call→call_phone, external→redirect, download→download, booking/appointment→appointment). New offers
  write `actions[]`.

## One display price card, reused (polymorphic — review 2026-07-14)

There is **one** landing-page display price card design (image / name / description / price / compare-at /
"Save %" / border). The standard selector renders it per price tier (with a radio); the **listicle renders
the same card as a single instance, reactive to `currentTarget`** (content updates via
`data-conversion-bind`, the action button comes from the ActionBar). No bespoke listicle card. (`sl-price-
option` on the server; a shared card component/markup in the preview. Note: `shared/PricingCard.vue` today
is the price *editor* used in Products/Services — the display card is separate.)

## Hero is fixed marketing copy, not target-bound (review 2026-07-14)

For a listicle (and every page), the **hero headline + subheadline are FIXED page-level copy** — they do
NOT change as the carousel scrolls. This is the TikTok-Shop pattern: the hero is the tenant's pitch ("this
curated set solves *your* problem"), and it stays put like the trust badges. **Only the price card and the
product-details block track `currentTarget`** (product name, description, price, image, gallery, badges).
Binding the hero to the target was both redundant with the card and a lost marketing slot — so the hero
carries no `data-conversion-bind`. `currentTarget` is still the shared cursor; the hero simply isn't a
subscriber to it.

## Registries (carry metadata — review 7)

Each entry is a **contract**, not just a component, because the registry becomes the source of truth for
both the renderer **and the builder** (defaults, editable props, validation, migrations):

```
RegistryEntry {
  component       // Python renderer fn / Vue component
  schema          // the section/CTA's data shape (validation)
  defaults        // what a freshly-added instance looks like
  editor          // builder editor metadata (which props are editable, controls)
  rendererVersion // for migrations
}
```

- **Section registry**: `type → RegistryEntry`. Adding a section = register one entry (renderer + editor).
- **CTA registry**: `cta.type → CTAPlugin` (review 2):

```
CTAPlugin {
  render()      // markup / component
  validate()    // owns its rules: buy → needs selectedPrice; email → needs email;
                //                  appointment → needs selectedDate; download → nothing
  serialize()   // the payload for execute / checkout
  execute()     // perform the conversion (checkout, submit lead, dial, download, book)
}
```

The page renderer never knows a CTA's validation or execution — the plugin owns it.

## Declarative sections

```jsonc
[ { "type": "hero_media" }, { "type": "hero" }, { "type": "offer_selector" }, { "type": "cta" } ]
```

No `offer_id` per section. The renderer is generic; inconsistencies (the "which offer?" per section)
become impossible.

## Carousel / sync flow

Load → `currentTargetIndex = 0` → Hero/Pricing/CTA render target 0. User swipes → `currentTargetIndex = 2`
→ all three re-render for target 2. **No inter-component events between UI, no prop drilling — only shared
state + one semantic event out.** Published: the JS island sets the index on scroll/nav, re-renders the DOM
sections from embedded per-target data, and `emit`s. Preview: Vue reactivity does it.

## Event Model (review addition — the piece that makes it "complete")

The context emits **semantic conversion events**. UI components don't need them; **analytics, pixels, A/B,
affiliate, heatmaps** do — and this lets them subscribe **without coupling to any UI component**.

```
conversion:itemChanged        // { index, target }
conversion:priceChanged       // { priceId, unitAmount }
conversion:quantityChanged    // { quantity }
conversion:ctaInvoked         // { ctaType }
conversion:couponApplied      // { code, ok }
conversion:checkoutStarted    // { total, targets }
conversion:checkoutCompleted  // { orderId }
```

- Published: the JS island exposes `window.slConversion.on(event, fn)` + `emit(...)`; analytics adapters
  (GA/Meta/TikTok/internal) are thin subscribers. Preview: a mitt-style emitter on the composable.
- One list, defined now, so instrumentation is a subscription — never a component edit.

## Published hydration contract (the "one JS island" done safely)

The Python renderer emits static HTML; a vanilla-JS island changes `currentTargetIndex` and updates the
other sections. Two rules keep it robust:

1. **Serialize the whole OfferView once.** Embed it as a single
   `<script type="application/json" data-conversion-offer>…</script>` (JSON, `<` escaped to `<`). The
   island parses it on load; **every** per-target value (image, headline, price, compare-at, badges) comes
   from that payload — never re-fetched, never scraped back out of the DOM. (This replaces today's ad-hoc
   per-widget `data-*` on the listicle items.)
2. **Bind through a standardized attribute contract**, so DOM selection never gets brittle:
   - Sections: `data-conversion-section="hero|media|offer_selector|cta|…"`.
   - Dynamic values: `data-conversion-bind="headline|subheadline|hero_image|price|compare_at|discount|cta_label"`.
   - The island, on `currentTargetIndex` change, walks `[data-conversion-bind]` and writes each from
     `offer.targets[index]` (text nodes, `src`, etc.), then `emit('conversion:itemChanged')`.
   A section is "context-aware" simply by carrying `data-conversion-bind` attributes — no bespoke JS per
   section. The registry's `editor`/`schema` metadata declares which binds a section exposes.

## Localization (multi-currency / dynamic tax)

Currency/locale are **visitor-scoped page state**, resolved late — not frozen into the read model:

- The `OfferView` pricing does **not** hardcode one currency. It carries either per-currency variants
  (`amounts: { usd: 5201, eur: 4899, … }`) or a base amount + FX/rounding rules the derived layer applies.
  (Today's single `unit_amount`/`currency` is the degenerate one-currency case — leave the shape open.)
- `page.locale` / `page.currency` come from geo/IP (or a picker) at render/first-paint.
- `derived.unitPrice` / `derived.total` resolve the **displayed** price from `OfferView.pricing` +
  `page.currency`. Components display `derived` and stay currency-agnostic.
- Tax/VAT is the same shape: a `page`-scoped input (region) → `derived.total`. No component computes tax.

This means adding international pricing later is a change to the pricing projection + `derived`, **not** a
refactor of every component.

## Phasing (per the proposal — infra first, keep the renderer working throughout)

### Phase 1 — Infrastructure (no new UI features)
- `expand_offer()` → `OfferView` (shipped); offers GET `?expand=1` (shipped). Rename the key to `targets`
  when the context lands.
- Section registry (server dict + Vue map) with **metadata entries** — refactor existing sections onto it.
- CTA registry as **`CTAPlugin`s** (render/validate/serialize/execute) — refactor the per-type branch onto it.
- Shared context with `currentTargetIndex` + read-only `derived` + the **event emitter**: server = one JS
  island driven by the **hydration contract** (single embedded OfferView JSON + `data-conversion-bind`
  attributes); preview = `useConversionContext`.
- Keep the `OfferView` pricing shape **currency-open** (variants/base+FX) even while today is single-USD,
  and thread `page.locale/currency` → `derived` so localization is a later projection change, not a refactor.
- `MediaViewer` (modes) replacing the hero-owns-carousel coupling.
- Refactor hero / media / offer_selector / cta to read the context (replaces the listicle scroll-listener
  hack + field-driven hero).

### Phase 2 — Capabilities on the new foundation
- Listicle fully on the context (media ↔ price card ↔ CTA all via `currentTargetIndex`).
- CTA registry filled out (download / appointment / … as `CTAPlugin`s).
- Analytics adapters subscribe to the event model.
- Future context-aware blocks: testimonials, FAQ, comparison, guarantees that react to `currentTarget`.

## What we already have (so this is incremental, not a rewrite)
- Offer-as-contract `presentation` snapshot; per-type CTA rendering; `single_unit_price`; `expand_offer()`
  / `?expand=1`; the hero + listicle carousels (offer-driven hero shipped). Phase 1 mostly **reorganizes**
  these behind the context + registries and adds the event model + derived layer.

## Relationship to other plans
- Builds on `LANDING_PAGE_CTA_AND_COMPOSITION.md` (CTA components → registry) and
  `LISTICLE_AND_CART.md` (listicle → the first real multi-item consumer of the context).
- The cart (LISTICLE_AND_CART L2) becomes a `page`-context concern (`selectedPrice`/cart), clean to add.
