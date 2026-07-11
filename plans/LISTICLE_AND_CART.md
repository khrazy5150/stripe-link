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

- **`offer_type` is AUTO-INFERRED, never chosen by the tenant** (the software knows from what's selected):
  - **1 product, 1 price → `single`.**
  - **1 product, buyable in 2+ units of the SAME product (multiple quantity/price options) → `bundle`.**
  - **Multiple products, services, or both → `listicle`.**
  It's a validated Offer field the API stamps at save (no UI selector). It tells the renderer how to build
  the page.
- **`single` / `bundle`** → today's `offer_price_selector` (pick-one). **`listicle`** → a **carousel**.
- **Listicle price = the SINGLE-UNIT price** (one unit of that product), **ignoring** bundle/upsell/downsell
  prices. Resolver (per `AI_AND_COMMERCE` C.1): single-unit (`quantity <= 1`), exclude
  `upsell/downsell/order_bump`, prefer discounted; tie-break `flash_sale > sale > standard`, then lowest
  `unit_amount`. **Flash sale (NOT yet built):** when a landing-page flash-sale toggle is on, show a
  top countdown banner + each product's **flash_sale** price; when it ends, revert to the single regular
  price. With no flash sale, default to the single discounted price if any.
- **Carousel UX (TikTok-Shop style):** ONE swipeable image carousel; the **price card below syncs to the
  currently-shown item** (discount % / price / compare-at / title); an **Add to cart** button adds the
  shown item. The customer shops several, checks out later.
- **Listicle pages drop the fluff** — no badges / FAQ / blurbs / testimonials. Just **hero image (the
  carousel) + headline + description + the syncing price card**. Same universal template, minimal sections.
  - *Optional later:* a per-product blurb component **synced to the carousel position** (image +
    subheadline + paragraph for the shown product).
- **This phase: client-side cart only** (localStorage accumulation + a mini-cart indicator). The
  **server-side cart** (persistence + abandonment tracking) + **multi-line checkout** are the NEXT phase —
  the existing `handlers/checkout.py` already builds multi-line Stripe sessions, so the checkout wiring is
  feasible when we do it.
- **Mixed fulfillment types allowed** in a listicle/cart (physical + digital-bonus), per `AI_AND_COMMERCE`
  C.2. The transactional-vs-lead-gen restriction stays (enforced in `offers.py`).

## Phasing

### L1 — offer_type + listicle carousel (SHIPPED dev, then corrected)
- `offer_type` promoted to a validated Offer field; retired the multi-offer carousel element. ✅
- **Correction (this pass):** offer_type is **auto-inferred** (selector removed); listicle price is the
  **single-unit price**; the carousel is redesigned to the **TikTok-Shop syncing-price-card** style with
  **Add to cart** (client-side cart accumulation); listicle pages **strip the fluff**.

### L2 — Server-side cart + multi-line checkout (NEXT)
- `cart` document keyed to a client-minted session id (localStorage + sent to API) + repository +
  endpoints (`POST /cart/items`, `GET /cart`, `PATCH`/`DELETE /cart/items/{id}`, `POST /cart/checkout`).
- Promote the client-side cart to server-side (persistence → abandoned-cart recovery via the email system).
- **Multi-line Stripe checkout** from the cart — `handlers/checkout.py` already emits `line_items[{index}]`,
  so wire the cart's items through it (keep the single-offer compat path).

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
