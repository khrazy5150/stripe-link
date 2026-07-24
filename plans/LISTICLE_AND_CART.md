# Listicle Offers + Server-Side Cart

Status: **L1 + L2 (Slices A–C) shipped dev+prod 2026-07-23** (server-side cart + multi-line checkout).
L2 Slice D (abandoned-cart recovery) + service-line checkout deferred. L3 (order-model ripples) not started.
(design author-approved 2026-07-10).
Supersedes the multi-offer `product_carousel` interpretation shipped in
`LANDING_PAGE_CTA_AND_COMPOSITION.md` phase 4c — see "Course correction" below. Extends
`AI_AND_COMMERCE_ARCHITECTURE.md` **Part C**. L2 outline in "Phasing → L2" below.

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

### L2 — Server-side cart + multi-line checkout (Slices A–C SHIPPED dev+prod 2026-07-23; D pending)
**Shipped (commits ad4e35a / d1c9718 / c31d8b7, 971 tests):** the client-side cart is now server-backed and
checks out. `domain/cart.py` (`resolve_cart_line` reuses `single_unit_price` so a line's price == the page's;
add/merge/qty/remove + `resolved_items_for_checkout`), `validate_cart`, `carts_repository`, `CartsTable`
(30-day TTL). Public `handlers/cart.py` — `POST`/`GET /cart`, `PATCH`/`DELETE /cart/items/{line_id}`,
anonymous, prices always re-resolved server-side. `handlers/cart_checkout.py` — `POST /cart/checkout` builds
ONE multi-line Stripe session by reusing `handlers.checkout.build_checkout_payload` +
`create_stripe_checkout_session` (single-offer path untouched), tags `metadata[cart_id]`. The listicle JS
island posts adds, hydrates via `GET`, per-line remove, and a mini-cart Checkout button → redirect to Stripe,
with a localStorage fallback when the cart API is unreachable.
**Deferred:** service lines are not yet cart-checkout-eligible (`resolved_items_for_checkout` rejects them —
booking has its own pay-then-book/book-then-pay flow); Slice D below.

Original design (delivered above):

1. **Data model — `cart` document.** Keyed to the client-minted `sl_cart_{offerId}` id (already in
   localStorage; start sending it to the API). Holds `line_items[]` (`product_id` / `price_id` / `qty` /
   `offer_id`) + derived totals + `tenant_id` + timestamps. New table-per-entity (`jb-carts-{env}`, GSI1) +
   `carts_repository` in `repositories/documents.py`; `validate_cart` in `domain/documents.py`. Server
   **re-resolves price** per line (single-unit resolver, per "Price resolution" below) — never trusts a
   client-sent amount.
2. **Endpoints (public, anonymous shopper — same abuse posture as `/leads`).** `POST /cart/items` (add),
   `GET /cart`, `PATCH /cart/items/{id}` (qty), `DELETE /cart/items/{id}`, `POST /cart/checkout` (one Stripe
   session with **all** line items). New `handlers/cart.py`; wire routes + table perms in `template.yaml`.
3. **Multi-line Stripe checkout.** Build the Stripe session's `line_items` from the cart's items rather than
   a single offer — reuse the existing `line_items[{index}]` construction in `handlers/checkout.py`; **keep
   the single-offer compat path** untouched. Attach cart_id → order for attribution.
4. **Renderer / JS island.** Point the listicle island's add-to-cart + mini-cart at the endpoints (optimistic
   local write, reconcile with `GET /cart`); mini-cart "Checkout (N) · $NN.NN" triggers `POST /cart/checkout`.
   Degrade gracefully to the L1 localStorage-only behavior if the cart API is unreachable.
5. **Abandoned-cart recovery (Slice D — pending).** A stored cart with an email (captured at checkout start
   or via the lead form) feeds the existing email system for recovery — mirrors the reminder/invite sweep
   pattern (`scan_type("cart")` + a `rate()` sweep). **Prerequisite not yet built: the cart has no email
   field** — capturing the shopper's email (checkout-start form or lead capture) is step 0 of Slice D.

**Suggested slice order:** (A) data model + `POST`/`GET` + persist the existing client cart; (B) mutate/delete
+ mini-cart wired to the API; (C) `POST /cart/checkout` multi-line session; (D) abandoned-cart sweep.

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
