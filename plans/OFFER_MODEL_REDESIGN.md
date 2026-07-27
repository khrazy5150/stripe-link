# Offer Model Redesign — Purchase Opportunities

**Status:** Design locked (author + assistant, 2026-07-26). Not built. Supersedes the ad-hoc
`items[]` + `offer.funnel.*` + inferred `offer_type` model. Reconciles and reshapes the Sales Funnel
work (`plans/SALES_FUNNELS.md` P2): order bumps and upsells/downsells fold into this model.

---

## 1. The breakthrough

**The Offer owns the purchase opportunity, not the Product.**

- **Product = pure catalog.** A product answers only: *What am I? What prices do I have? What Stripe
  Product/Price IDs do I map to? What media/description/specs do I carry?* It knows **nothing** about where
  or how it is sold.
- **Offer = presentation across the journey.** An offer answers: *How and when should these products be
  presented during this customer's purchase journey?*

Today `items[]` conflates five roles at once (primary landing product, bundle tier selector, order bump,
upsell, downsell), and `offer.funnel.order_bumps` duplicates data already implied by items. That
denormalization is why `offer_type` inference got messy. We normalize all of it into **one collection**.

---

## 1a. Definition — what IS a purchase opportunity

**A purchase opportunity is one distinct product or service presented as a chargeable moment in the funnel.**
The count of opportunities = the count of distinct *transaction moments*, NOT the number of price tiers/bottles.

- A product offered with **tiered prices** (Creatine 1/2/3 containers) is **ONE** opportunity — the tiers are
  variants the buyer picks *one* of per checkout, held inside that single opportunity as `selectable_prices` +
  `default_price_id`. Not three opportunities.
- A **landing purchase + an order bump** = **TWO** opportunities (one `landing`, one `checkout`).
- **Each upsell / downsell** = an additional opportunity (each `post_purchase`).

This is what makes the derivation work: **1 landing opportunity → single/tiered (bundle); N landing
opportunities → carousel (shop/cart)** (§3).

## 2. The model: `purchase_opportunities[]`

Replace `items[]` **and** `offer.funnel.{order_bumps,upsells,downsells}` with a single normalized array.
Each entry is: *"present this product, at this **stage**, in this **placement**."* The same product may
appear multiple times (e.g., a landing item AND a post-purchase upsell) — that is legal and expected.

```jsonc
{
  "opportunity_id": "opp_...",
  "stage": "landing",                 // WHEN the customer sees it
  "placement": {                      // HOW it is rendered at that stage
    "surface": "primary",             // primary | order_bump | upsell | downsell
    "group": "main_offer",            // opportunities sharing a group check out together
    "order": 1,                       // sort within the placement
    "strategy": "single"              // single | carousel | sequence (default derived; see §4)
  },
  "product_id": "local_...",
  "default_price_id": "price_...",    // for a selectable (tiered) opportunity
  "selectable_prices": [ ... ]        // OR a single fixed price via "price_id"
}
```

- **`price_id`** (fixed) is used for bumps/upsells/downsells and single-price landing items.
- **`default_price_id` + `selectable_prices`** express a tier/variant selector (today's "bundle").

### Stages
| stage | when | rendered by |
|---|---|---|
| `landing` | the landing page | **our** renderer |
| `checkout` | Stripe's hosted checkout | **Stripe** (`optional_items[]`) — see §5 |
| `post_purchase` | after a successful checkout | **our** upsell/downsell page(s) |

### Placement surfaces
`primary` (the thing being bought) · `order_bump` (checkout add-on) · `upsell` · `downsell`.

---

## 3. `offer_type` is removed

There is no stored `offer_type`. Presentation is **derived** from the landing opportunities + their
placement:

| landing opportunities | placement | derived presentation |
|---|---|---|
| 1 opp, 1 price | — | single-product page |
| 1 opp, N selectable_prices | — | tier/variant selector ("bundle" today) |
| N opps, one shared `group` | `group: main_offer` | **fixed bundle** — all in ONE checkout |
| N opps, distinct groups / `surface: catalog` | catalog | **shop** — add-to-cart, cart checkout |

The one bit not derivable from count alone — *fixed multi-product bundle (one checkout)* vs *shop (cart)* —
lives in **placement grouping**, not a type field. Everything else the renderer infers.

> **Author decision (2026-07-16):** for now, **N distinct landing products → shop (cart)** is the ONLY
> multi-product path the editor offers. A *fixed bundle of distinct products in one checkout* (e.g. Creatine
> Powder + Whey) is an **advanced feature not built yet** — today tenants approximate it via order bumps. When
> we do build it, revisit the word "bundle": today "bundle" means *one product, tiered prices*; the
> industry-standard meaning is *several distinct products sold as one unit*. A future plan should reconcile the
> two (likely: rename today's tiered case to "tiers/variants", reserve "bundle" for the multi-product-one-
> checkout case). The `placement.group` field already reserves the data slot for it, so no model change is
> needed to add it later.

> This also folds in Sale/Flash: those are **price contexts** on a landing opportunity's prices
> (`standard/sale/flash_sale`), orthogonal to stage/placement. Unchanged by this redesign.

---

## 4. Rendering: the carousel is a strategy, not a type

Every stage's renderer runs the same rule:

1. Gather opportunities for the current stage.
2. Group them by `placement.group` (and `surface`).
3. A group with **one** opportunity → render it directly.
4. A group with **multiple** opportunities → render by its **strategy**:
   - **`carousel`** — show them together (a reusable carousel primitive), buyer browses/picks.
   - **`sequence`** — show one at a time, advance on decision (the classic one-click funnel).

The carousel becomes a reusable UI primitive usable on the landing page **and** the post-purchase page —
not a feature welded to "listicle." Defaults per stage: landing → `carousel` when multiple; post_purchase →
`sequence` (see §6).

---

## 5. Checkout stage = Stripe `optional_items` (no checkout carousel)

We keep Stripe's **hosted** Checkout (for Stripe Tax — settled). So a `stage: checkout, surface: order_bump`
opportunity does **not** render in our carousel; it maps to Stripe `optional_items[]` (a flat opt-in list on
Stripe's page). The "each stage has a renderer" abstraction holds; the checkout renderer simply **is Stripe**,
and it can only do a flat list — there is intentionally no checkout carousel.

Requires a **synced `stripe_price_id`** (Stripe forbids inline `price_data` for `optional_items`) — guaranteed
by product auto-sync (`plans/SALES_FUNNELS.md` P1.5). Unsynced bump → skipped + dashboard warning.

---

## 6. Post-purchase: sequence OR carousel — DERIVED from count, capped (author-locked 2026-07-27)

Both reuse the same idempotent one-click charge (`process_upsell`, off-session PaymentIntent, keyed by
`sequence`). Strategy is **not a free tenant toggle** — it's derived from the number of upsell slots, with a
hard cap on serialized screens so a tenant can't march a customer through 7 "No thanks" clicks:

- **`MAX_SEQUENTIAL_UPSELLS = 3`** (named constant, tunable).
- **≤ 3 upsell slots → `sequence`.** One upsell at a time: *Yes, add it!* (one-click charge) / *No thanks* →
  its downsell swaps in **in place** (see below) → next slot → … → thank-you. Highest AOV.
- **≥ 4 upsell slots → `carousel`** (forced — sequence is not offered past the cap). **ALL** upsells show in
  ONE "bargains just for you" grid (never "3 sequenced then the rest carouselled" — it's all-or-nothing at the
  cap). Each card has a one-click **Add**; a single **"No thanks, I'm good!"** dismisses the whole grid.

### Upsell ↔ downsell pairing (author-locked 2026-07-27)
A downsell is **the same product's `downsell`-context price** — NOT a separately-picked product. An upsell slot
is a product with an `upsell` price; if the tenant also set a `downsell` price on that product, declining the
upsell shows that cheaper price of the **same product** in place ("ok, just 1 more for $12?"). No downsell
price → the decline just advances. Pairing is by `product_id`. The editor therefore only picks **upsell
products**; the downsell rides along automatically.

- **Sequence mode:** decline the upsell → same slot swaps to the product's downsell price (one screen, no
  separate downsell page) → decide → next slot.
- **Carousel mode:** the single "No thanks, I'm good!" dismiss has no per-card decline, so on dismiss — IF any
  of the shown products carry a downsell price — show ONE **downsell carousel** (those products' downsell
  prices) with its own single dismiss → thank-you. Bounds carousel mode to **≤ 2 post-purchase screens**.

**Documented gap (accepted):** a product with a `downsell` price but **no** `upsell` price is **never shown**.
The old design would have surfaced it on a standalone downsell page; we accept the gap for the simpler model.
Downsells only exist as the fallback of a chosen upsell product.

---

## 7. Offer naming — "brainless by default, override anytime"

Two names, previously blurred:

- **Offer name** — *internal* label for the tenant's dashboard organization; **never shown to a customer**.
- **Presentation headline** — *customer-facing* text on the landing page (`offer.presentation.headline`,
  already exists). Unchanged.

Rules for the internal offer name:
- **Auto-by-default with override.** Default = the **primary landing opportunity's product name**, with **no
  type suffix** (the "… Single Offer / … Listicle" suffix dies with `offer_type`).
- Stays in sync with the primary product **until the tenant edits it**; once edited, we never clobber it.
- The default must be good enough that the tenant just reads it and clicks **Create**. On a name collision with
  an existing offer, append a minimal qualifier (e.g. the goal, or a numeric suffix) — never a type word.

---

## 8. Migration (read-time adapter, then backfill)

Existing offers map mechanically:

| old | new opportunity |
|---|---|
| each `items[i]` | `{stage: landing, placement: {surface: primary, group: main_offer, order: i}, product_id, default_price_id/selectable_prices or price_id}` |
| each `funnel.order_bumps[i]` | `{stage: checkout, placement: {surface: order_bump, order: i}, product_id, price_id}` |
| each `funnel.upsells[i]` | `{stage: post_purchase, placement: {surface: upsell, order: i, strategy: sequence}, product_id, price_id}` |
| each `funnel.downsells[i]` | `{stage: post_purchase, placement: {surface: downsell, order: i}, product_id, price_id}` |
| `offer_type` | dropped (derived) |

Strategy: a **read-time adapter** (`opportunities_from_offer(offer)`) that returns the normalized shape for
BOTH new and legacy offers, so every consumer can migrate to it before any document is rewritten. Backfill +
drop the legacy fields last.

---

## 9. Blast radius

- **Validation** (`documents.py`): `purchase_opportunities` schema + validation; retire `items`/`funnel`
  validation once cut over.
- **Pricing** (`pricing.py`): `resolve_offer`/`expand_offer`/`single_unit_price` operate on **landing**
  opportunities; checkout bumps come from **checkout** opportunities.
- **Landing renderer** (`html.py`): price selector / bundle / carousel all derive from landing opportunities +
  placement strategy; the listicle carousel becomes the general carousel primitive.
- **Page Composer** (`composition_rules.json` + `compose_page` + `pageComposer`): today keys the section list
  off `offer_type × goal`; re-key off the **derived landing presentation** (single/bundle/carousel) × goal.
- **Checkout + cart** (`checkout.py`, `cart_checkout.py`): line items from landing (group) opportunities;
  `optional_items` from checkout opportunities. Retire `offer.funnel` reads.
- **Post-purchase** (`upsell.py`, `post_checkout.py`, `funnels.py`): drive from post_purchase opportunities +
  strategy; reuse `process_upsell` + `resolve_funnel_transition`.
- **Dashboard**: `Offers.vue` is a **pure-inference editor** (author-locked 2026-07-27). The tenant picks
  products ONCE in the unified "Select Items" list; **every role is inferred from each product's pricing
  contexts** — the tenant never re-decides bumps/upsells/downsells per offer (they did that work assigning
  contexts on the Products screen). Rules: `standard/sale/flash_sale` → landing card · `order_bump` → checkout
  bump · `upsell` → post-purchase upsell · `downsell` → that upsell's in-place fallback. A product may fill
  several roles (standard + order_bump = landing card that can also be bumped). A **funnel-only** product
  (bump/upsell/downsell price, NO landing price) is selected in the offer but is never a landing card. The
  dedicated bump/upsell/downsell pickers are **removed**; a read-only **visual purchase funnel** ("Purchase
  Flow") renders what was derived — a top-down diagram *Offer → Landing → At checkout → After purchase →
  Thank-you*, each stage showing opportunity cards with an **intent badge**, product name, and pricing-option
  chips (standard / N quantity tiers / subscription / sale / flash), plus the ≤3-sequence / ≥4-carousel label
  and each upsell's downsell fallback. So the tenant *sees* the flow without choosing it.
  `LandingPages.vue` `isListicleOffer` / offer-type branches derive from the adapter instead.

  **Intent (author idea, 2026-07-27):** a friendly label naming WHY a product sits at its stage —
  `primary` (main buy) · `cross_sell` (order bump) · `upgrade` (upsell) · `recovery` (downsell). Currently
  **DERIVED 1:1 from `placement.surface`** (no new stored field); if we ever want intent decoupled from surface,
  promote it to a stored `placement.intent`.
- **Migration**: every persisted offer.

---

## 10. Phasing (keep the app working throughout)

- **P0 — Adapter.** Ship `opportunities_from_offer(offer)` (legacy → normalized) + the derivation helpers
  (presentation shape, per-stage opportunities). Pure, tested, consumed by nobody yet.
- **P1 — Read side onto the adapter.** Point pricing/resolve, the landing renderer, checkout/cart, and the
  Page Composer at the adapter (still reading legacy fields underneath). No behavior change; big test surface.
- **P2 — Write side + editor.** `Offers.vue` writes `purchase_opportunities` directly; new offers stop
  writing `items`/`funnel`/`offer_type`. Internal-name defaulting (§7).
- **P3 — Post-purchase strategies.** Sequence + carousel upsell placements (§6), wired to `process_upsell`.
  (This is the remainder of Sales Funnel P2b, re-pointed onto opportunities.)
- **P4 — Backfill + cleanup.** Backfill legacy offers to `purchase_opportunities`; drop `items`/`funnel`/
  `offer_type` and the adapter's legacy branch.

---

## 11. Reconciliation with Sales Funnels (`plans/SALES_FUNNELS.md`)

- **P2a order bumps (shipped dev):** `offer.funnel.order_bumps` → `stage: checkout` opportunities. The
  checkout emission (`optional_items`) and webhook itemization stay; only their **source** moves to the
  adapter. The P2a `cart_checkout` bump fix and the `requires_prior_purchase` reclassify are absorbed here.
- **P2b upsell/downsell (P2b-1 derivation shipped):** `offer.funnel.upsells/downsells` → `stage:
  post_purchase` opportunities; `funnel_context_items`/`funnel_reserved_slugs` re-point at the adapter.
- Net: the funnel stops being a separate `offer.funnel` block and becomes ordinary opportunities at the
  `checkout` / `post_purchase` stages — exactly the normalization this redesign is about.
