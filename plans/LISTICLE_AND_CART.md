# Listicle Offers + Server-Side Cart

Status: **proposed** (design; author-approved direction 2026-07-10). Supersedes the multi-offer
`product_carousel` interpretation shipped in `LANDING_PAGE_CTA_AND_COMPOSITION.md` phase 4c — see "Course
correction" below. Extends `AI_AND_COMMERCE_ARCHITECTURE.md` **Part C**.

## Course correction

Phase 4c shipped a `product_carousel` **page element** that referenced several separate **offers**. In
practice tenants model a listicle as **one offer containing several products** and expect *that* to render
as a carousel. Locked decision: **the offer is the source** — an offer marked `offer_type: listicle`
renders its own items as a carousel. The multi-offer carousel element is **retired** (not "both").

## Locked decisions

- **`offer_type` becomes a first-class, validated Offer field**: `single | bundle | listicle` (default
  `single`; currently the concept is UI-only and stripped). It drives rendering:
  - `single` / `bundle` → today's `offer_price_selector` (pick-one radio + one Buy).
  - `listicle` → a **carousel of the offer's items**, each slide independently **add-to-cart** (not
    pick-one). Rendered by adapting the price-selector section to a carousel when the offer is a listicle.
- **Server-side cart** (the "pick several, check out later" model the tenant expects). Buy-now-only is
  **not** enough for a listicle. This is the deliberate cart project from `AI_AND_COMMERCE` C.3.
- **Listicle offers ignore upsell funnels** (deterministic), per `AI_AND_COMMERCE` C.1.
- **Mixed fulfillment types allowed** in a listicle/cart (physical + digital-bonus), per `AI_AND_COMMERCE`
  C.2. The transactional-vs-lead-gen restriction stays (enforced in `offers.py`).

## Phasing

### L1 — `offer_type` + listicle item-carousel (no cart yet)
- Add `offer_type` to the Offer schema + `validate_offer_document` (enum, default `single`).
- Offers.vue: an offer-type selector; a 3-product offer can be marked `listicle`.
- Render: when `offer.offer_type == "listicle"`, the page renders the offer's **items** as a carousel
  (one slide per item: image/name/price), reusing the multi-offer carousel markup but iterating items.
  For now each slide is **Buy-now** (its item's checkout) as an interim until L2 wires the cart.
- Retire the multi-offer `product_carousel` builder element (keep the section renderer, repurposed to
  items, until L2). Existing pages: none in prod — safe to reshape.

### L2 — Server-side cart (the deliberate project)
- **`cart` document** keyed to a visitor/session id (a `sl_cart` id minted client-side, stored in
  localStorage + sent to the API). Holds `line_items[]` (product_id/price_id/qty/offer_id) + totals.
  Unlocks abandoned-cart recovery (via the existing email system), attribution, cross-device later.
- **Endpoints**: `POST /cart/items` (add), `GET /cart`, `PATCH /cart/items/{id}` (qty), `DELETE
  /cart/items/{id}`, `POST /cart/checkout` (one Stripe session with **all** line items). Public
  (anonymous shopper), same abuse posture as `/leads`.
- **Carousel slides** get **Add to cart**; a persistent **mini-cart** ("Checkout (3) · $34.97") on the
  page; a JS island manages the cart + calls the endpoints.
- **Multi-line Stripe checkout**: extend the checkout path to build `line_items` from the cart (vs a
  single product). Keep a single-product compat path.

### L3 — Order-model ripples (deferred; documented so they aren't forgotten)
Per `AI_AND_COMMERCE` C.3, a multi-line order ripples into things already built — **refunds ledger**
(per-line), **receipts** (itemized), **digital downloads** (per-line links), **fees** (per-line rates).
Keep a single-product compat path so existing orders still render. Build only when L2 is proven.

## Price resolution (listicle slide) — from AI_AND_COMMERCE C.1
Per slide: single-unit prices (`quantity <= 1`), exclude `upsell/downsell/order_bump`, prefer discounted;
tie-break `flash_sale > sale > standard`, then lowest `unit_amount`. One price → use it.

## Relationship to other plans
- Corrects `LANDING_PAGE_CTA_AND_COMPOSITION.md` phase 4c (multi-offer → offer-item listicle).
- Implements the cart from `AI_AND_COMMERCE_ARCHITECTURE.md` Part C.
- Cart ingest mirrors the public-endpoint + abuse posture of `LEAD_CAPTURE.md`.
