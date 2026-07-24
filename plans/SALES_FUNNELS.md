# Sales Funnels — the Sites-native funnel

**Status:** design LOCKED (author-clarified 2026-07-24), not built. **HIGH PRIORITY.** Closes the loop for
transaction (Stripe) landing pages. **Unifies** the pre-Sites funnel work (`schemas/Funnel.schema.json`,
`domain/funnels.py`, `page.post_checkout`, `handlers/upsell.py`/`post_checkout.py`) with the Sites paradigm
into one model.

## Why this supersedes the old funnel plan

The earlier funnel design predates the **Site** concept. It modeled a funnel as a hand-authored **graph of
standalone pages** (`page.post_checkout.funnel_steps` inline, or a detached `Funnel` document), with slugs
**derived from each step_id** (`upsell_1` → `/upsell-1`) and arbitrary `on_accept`/`on_decline` branching.
That was the only option when pages were standalone artifacts with no container.

Now a **Site = one funnel**. A Site already aggregates pages via a `slug → page` route map and is dedicated
to one offer. So the funnel is no longer a hand-built page graph — it's **derived from the offer**, rendered
across a Site's **reserved-slug** pages. This plan makes that Site-native funnel the default and **reframes
the old engine as (a) reusable routing plumbing and (b) a future "advanced" tier** — nothing built is wasted.

| | Old (pages paradigm) | This plan (Sites paradigm) |
|---|---|---|
| Container | none — standalone pages | **Site = the funnel** |
| Structure | hand-authored page graph (`funnel_steps` / `Funnel` doc) | **derived from the offer** (contexts + `offer.funnel`) |
| Upsell URLs | one page per step → `/upsell-1`, `/upsell-2` | **one `/upsell`** cycling products internally |
| Branching | arbitrary `on_accept`/`on_decline` | linear chain; decline → paired downsell |
| Audience | power users | **everyone** (advanced graph kept for power users) |

## The unified model

**A Site is a sales funnel for one offer.** Its steps/views are **reserved slugs** tenants may never use for
their own pages. Two kinds:

| Slug | Kind | Renders |
|------|------|---------|
| `/` | sales page | The offer at its **Standard** price. |
| `/sale` | *context view of `/`* | The same page, price swapped to the **sale** context + a "Sale" badge. Standard when none/expired. |
| `/flash-sale` | *context view of `/`* | The same page with the **flash_sale** price, 🔥 "Flash Sale" badge, and a countdown — driven by page dates (upcoming/active/ended). Standard when none/not-started/expired. |
| `/upsell` | funnel-step page | Post-purchase one-click: cycles `offer.funnel.upsells` **one by one** on a single slug. |
| `/downsell` | funnel-step page | Post-purchase one-click: after the upsell chain, the paired downsells of the **declined** upsells. |
| `/thank-you` | funnel-step page | Funnel end. |

- **Context views** (`/sale`, `/flash-sale`) are NOT separate pages — they re-render `/` with a different
  price context + chrome. A routing + render-context feature.
- **Funnel-step pages** (`/upsell`, `/downsell`, `/thank-you`) are real pages the builder auto-provisions and
  the tenant can customize; their **product content is derived** from the offer.
- **Pricing context IS the funnel wiring.** A product's prices carry a `context`
  (`standard`/`sale`/`flash_sale`/`order_bump`/`upsell`/`downsell`, enum already validated) — the funnel reads
  these, so there's almost no separate funnel config.
- Funnels apply to **single/bundle** offers. **Listicles ignore funnels** (shop mode → cart, not a funnel —
  `AI_AND_COMMERCE_ARCHITECTURE.md` Part C).

## One offer per funnel — the in-offer `funnel` block

The whole funnel is driven by the **one** offer on `/` (honors the one-offer-per-landing-page paradigm). Upsell
/downsell products live in a block **inside that offer**, separate from `items[]`:

```
offer.funnel = {
  upsells:   [{ product_id, price_id /* upsell   context */ }, …],  // ordered
  downsells: [{ product_id, price_id /* downsell context */ }, …],  // paired to an upsell product
}
```

- `offer_type` is inferred from **`items[]` only**, so funnel products **don't** inflate a single/bundle offer
  into a listicle. `items[]` = the `/` sale; `funnel` = the post-purchase steps.
- No second Offer document — the entire funnel renders from this one offer.
- An **unrelated product** can be an upsell: reference *its* `product_id` + *its* upsell-context `price_id`.
- Entries are product+price refs (lighter than full Offers). A per-entry presentation override is a future
  extension if bespoke upsell layouts are ever needed (YAGNI).
- Order bumps also live in this block (`offer.funnel.order_bumps`), but they are **pre-purchase** and render
  on **Stripe's hosted checkout page**, not on `/` — see the "Order bumps" section below.

## Pre-purchase: `/`, `/sale`, `/flash-sale`

`/sale` and `/flash-sale` re-render `/`, swapping only the price card(s). **Both are per-Landing-Page toggles**
(not auto). On enable, if the offer's product has no matching context price → warn: *"This product doesn't have
a Sale pricing context. Please go to the products page and set it there."* For a multi-item (listicle) offer,
only items **with** a sale/flash price change; the rest stay Standard.

- **`/sale`** — optional **expiration** on the page (no expiration → **perpetual**). Shows the `sale` price +
  a **"Sale"** badge; past expiry / no sale price → Standard.
- **`/flash-sale`** — dates on the **Landing Page** (`flash_sale_starts_on?`, `flash_sale_ends_at`), so a
  tenant sets a window for a TikTok/IG Live with no separate campaign object. **Expiration is REQUIRED to
  enable** (else block: *"You must set an expiration date in order to enable this feature."*). Three states:
  - **Upcoming** (before start): banner *"Flash Sale Coming Up on {date}"*, price stays **Standard**.
  - **Active**: countdown banner to `ends_at`, price = **flash_sale** + 🔥 **"Flash Sale"** badge.
  - **Ended**: banner *"Flash Sale ended"*, price reverts to **Standard**.

Order bumps are **pre-purchase** but do NOT render on `/` — they appear on Stripe's hosted checkout page (see
"Order bumps" below).

### Price mechanism for context views — pair by quantity + context (author-confirmed 2026-07-24)

An offer's price options are **quantity tiers** referencing specific *standard* price IDs; there's no built-in
link to a "sale version." Product prices already carry both `quantity` and `context`, so the mapping is
schema-free: **for each displayed tier (quantity Q), the `/sale`//`/flash-sale` view uses the product's price
with `context = sale`/`flash_sale` AND `quantity = Q`; tiers with no such price fall back to Standard** (and
carry no badge). Whole-page fallback: if no tier has a sale/flash price, the view renders as Standard.
Implication: tenants add a sale price per quantity tier they want discounted (no per-option config on the offer).

**Checkout implication (NOT free — corrects "no payment changes"):** when a buyer converts on `/sale`, the
CTA carries the **sale** price ID, and checkout must charge it. `resolve_offer` today rejects a non-standard
price context unless the offer's `allowed_price_contexts` includes it. So P1 must either (a) include the
relevant contexts in `allowed_price_contexts` when a page's sale/flash toggle is on, or (b) make the checkout
resolve context-aware for the active view. Small, but it touches the checkout resolve path — fold into P1b.

## Post-purchase: `/upsell` → `/downsell` → `/thank-you`

- After `/` checkout is **paid**, the buyer enters the funnel. **Reuse** the built runtime: Site-aware routing
  (`handlers/post_checkout.py`), the accept/decline→next engine (`domain/funnels.py`
  `resolve_funnel_transition`), and one-click charging on the saved payment method (`handlers/upsell.py` —
  `get_upsell_session` + `process_upsell`, idempotent by `sequence`).
- **`/upsell`** — one slug; walk `offer.funnel.upsells` one by one (internal step index, **no numbered slugs**).
  Accept → one-click charge → next. **Decline → queue that product's paired downsell** (if any).
- **`/downsell`** — one slug; after the whole upsell chain, walk the paired downsells of the **declined**
  upsells, one by one. (A downsell shows **only if its upsell was declined.**)
- → **`/thank-you`**. `/upsell`//`/downsell` are only reachable when `offer.funnel` actually has those entries.

## Order bumps — Stripe `optional_items` on the hosted checkout page (author-decided 2026-07-24)

**Decision: keep Stripe's hosted Checkout; order bumps appear on Stripe's page, NOT on the landing page.**
The alternative — a custom Stripe **Elements** checkout — would give full control over bump styling but means
re-owning the entire checkout (payment UI, 3-DS, wallets, and critically **Stripe Tax**, which is a one-toggle
feature on hosted Checkout). Not worth trading business-critical tax handling for bump styling. Elements is a
possible far-future initiative, not this.

**Mechanism:** a bump is a designated product+price (`context: order_bump`) rendered as a Stripe Checkout
**`optional_items[]`** — Stripe shows an opt-in "add this?" line on its hosted page; if the buyer adds it, it's
charged in the same session. This replaces today's stopgap.

**Current state (accurate — the plan's earlier "built" note was wrong):**
- `resolve_order_bumps` → `merge_resolved_offers` appends bump items as **mandatory `line_items`** (force-added,
  not opt-in), and nothing feeds `order_bump_ids` anyway, so **no bump ever actually shows.** No landing-page
  element, no `optional_items`. The render/dashboard also **mislabel** `order_bump` as post-purchase
  ("requires prior purchase", grouped with upsell/downsell) — it is **pre-purchase**.

**Build:**
1. **Designate bumps:** `offer.funnel.order_bumps = [{product_id, price_id /* order_bump context */}]` on the
   sales offer.
2. **Checkout:** in `build_checkout_payload`, emit each resolved bump price as `optional_items[<i>][price] =
   {stripe_price_id}` (+ `adjustable_quantity` as desired). **Retire** the `merge_resolved_offers` bump path.
   Caveat: `optional_items` requires a **synced Stripe Price ID** (no inline `price_data`) — guaranteed by the
   auto-sync below.
3. **Reclassify** `order_bump` as **pre-purchase** in the renderer's context comments and the dashboard
   (`Offers.vue` `requires_prior_purchase` must exclude `order_bump`).
4. **Guard (fails loudly only on a real problem):** attaching a bump product that isn't Stripe-synced (or whose
   sync failed) warns + offers Retry; otherwise silent.
5. **No landing-page bump element.**

## Product → Stripe auto-sync (enabler; a general product improvement)

**Author-decided 2026-07-24: kill the separate "Sync to Stripe" button — one Save, sync happens automatically.**
Today a tenant clicks **Save Product** and then a *separate* **Sync to Stripe** button — awful UX. The sync
engine already exists and is idempotent: `POST /products/{id}/sync` (`run_product_sync`) pushes the product +
**every price** (all contexts, incl. `order_bump`) to the tenant's Stripe account, creating a Stripe Price per
local price and storing `stripe_price_id`; re-syncing an unchanged product is a near-no-op (it diffs).

**Design — server-side, asynchronous, invisible:**
- On product **create/edit** (the products handler, after persist), when Stripe is connected, **fire the sync
  asynchronously** — a fire-and-forget Lambda `Event` invoke of the sync function (`{tenant_id, product_id}`
  payload; the sync handler re-resolves Stripe creds). Save returns immediately; the tenant only ever clicks
  **Save**. Chosen over a client-side "save then fire sync" chain because server-side **still completes if the
  tenant closes the tab** — the "they shouldn't have to think about it" property.
- **Status UX:** the existing `sync.status` drives a chip — *Saved · Syncing… → Synced*, or *Sync failed —
  Retry*. The old "Sync to Stripe" button is **demoted to a Retry** shown only on failure.
- **Idempotent + safe to over-fire:** every save re-syncs; `run_product_sync` only creates new Stripe prices
  for new/changed local prices. (Guard against a self-trigger loop — this is a direct invoke from the save
  path, NOT a DynamoDB-stream on the sync's own writeback, so there is no loop.)
- **Failure = the "real problem":** a failed async sync sets `sync.status = failed`, surfaces on the product,
  and is what the order-bump guard keys off. Optional: a `system` notification emitter for sync failures.
- **Infra:** the products function gets permission to `lambda:InvokeFunction` on the sync function; the sync
  function accepts an internal `{tenant_id, product_id}` invoke payload in addition to its API event.

**Benefit beyond bumps:** every product stays Stripe-synced without the tenant babysitting it; order bumps
just ride on it (the bump's `stripe_price_id` is always ready for `optional_items`).

## Reserved slugs + enforcement

Reserved set: `{"" (=/), "sale", "flash-sale", "upsell", "downsell", "thank-you"}`. **Reject** them as
tenant-chosen slugs (page creation + Site page-assignment validation + the builder slug picker). The Site
route resolver maps context-view slugs (`/sale`, `/flash-sale`) → the `/` page + a render context, and
funnel-step slugs → their pages.

## Auto-provisioning (builder), like stripe-cart

Creating a funnel Site auto-creates its pages from the offer + the tenant's funnel-configuration defaults
(the `page_defaults.upsell`/`thank_you` config already in Configuration): always `/` + `/thank-you`; add
`/upsell` iff `offer.funnel.upsells` is non-empty, `/downsell` iff any paired downsells exist. Port
stripe-cart's default-page generation + "only show the upsell page if the offer has an upsell" gating.

## Reconciliation with the existing funnel engine

| Existing artifact | Disposition |
|---|---|
| `resolve_funnel_transition` (accept/decline → next) | **REUSE.** The default funnel is a fixed reserved-slug sequence (`upsell` → `downsell` → `thank_you`) with internal product cycling; drive it through this engine (fixed step_ids → clean slugs, no numbers). |
| `funnel_slug_entries` / `attach_funnel_pages` (funnel pages → Site route map) | **REUSE**, emitting the reserved slugs. |
| `handlers/post_checkout.py` (Site-aware post-checkout routing) | **REUSE.** |
| `handlers/upsell.py` (one-click charge) | **REUSE** for each upsell step. |
| `funnel_step_slug` (step_id → `/upsell-1`) | **ADVANCED-tier only.** The default uses fixed reserved slugs, not numbered derivations. |
| `page.post_checkout.funnel_steps` (inline hand-authored graph) | **DERIVE, don't hand-author.** The default synthesizes the reserved-slug step sequence from `offer.funnel`; keep inline authoring available for the advanced tier. |
| `schemas/Funnel.schema.json` (detached `Funnel` doc, `funnel_id`) | **DEFER → advanced tier.** Powers bespoke multi-page/branching funnels for power users (Phase 3+). Its Phase-2 resolver stays stubbed until then. |
| price `context` enum | **REUSE** as-is. |
| `resolve_order_bumps` / `merge_resolved_offers` bump path | **REPLACE** with Stripe `optional_items` (see "Order bumps"); the mandatory-line-item merge was a non-functional stopgap. |
| `run_product_sync` (`POST /products/{id}/sync`) | **REUSE**, but auto-fire it async on product save (see "Product → Stripe auto-sync"). |

**Net:** one default funnel model (Site-native, offer-derived, single `/upsell`) that reuses the built
routing/charge plumbing; the generic step-graph becomes the opt-in advanced tier.

## Plan of action (phased)

- **P0 — already built (inventory):** price `context` enum; one-click upsell charging; Site-aware
  post-checkout routing + the transition engine; `SITE_PAGE_TYPES` includes `thank_you`/`funnel_step`; the
  product→Stripe sync engine (`run_product_sync`, manual today). (NOT the order-bump checkout — that stopgap
  is replaced in P2.)
- **P1.5 — Product → Stripe auto-sync (enabler; do before/with P2 order bumps):** fire `run_product_sync`
  async (Lambda `Event` invoke) from the products save handler; demote the manual "Sync" button to a
  failure-only Retry; sync-status chip. Benefits all products, and makes bump Price IDs always ready.
- **P1 — Pre-purchase (highest value / lowest risk):**
  - **P1a — SHIPPED dev (commit 8717cca):** reserved-slug set (`RESERVED_SITE_SLUGS`) + `is_reserved_slug` +
    enforcement in the Site `attach_page` handler; page `sale`/`flash_sale` config blocks + validation
    (flash-enabled requires an expiration; `starts_on` < `ends_at`); Page.schema.json updated.
  - **P1b — next:** render context views — pair-by-quantity+context price swap + Sale/🔥 badges + the
    per-tier/whole-page Standard fallback; the three flash time-states + countdown (client-side, since pages
    publish statically — embed both prices + dates, JS picks the state); the small checkout-accepts-sale-price
    piece (see "Checkout implication" above).
  - **P1c — routing/publish:** Site route resolver mapping `/sale`//`/flash-sale` → the `/` page + context;
    publish the context-view artifacts.
  - **P1d — dashboard:** per-page toggles + dates + the "no context" warning + the "expiration required" block.
- **P2 — Checkout: order bumps + post-purchase default funnel:**
  - **Order bumps:** `offer.funnel.order_bumps`; emit Stripe `optional_items` in `build_checkout_payload`
    (retire the `merge_resolved_offers` stopgap); reclassify `order_bump` as pre-purchase; sync guard.
  - **Post-purchase funnel:** the `offer.funnel` upsells/downsells; auto-provision funnel pages from the offer;
    wire `/upsell` (cycle upsells + one-click) then `/downsell` (declined-with-downsell) → `/thank-you` onto the
    reused transition engine + `post_checkout` routing; gate reachability on `offer.funnel`.
- **P3 — Advanced tier + polish:** activate the detached `Funnel` doc for bespoke multi-page/branching funnels
  (power users); builder funnel UX; per-step analytics; AI-assisted funnel copy.

## Resolved decisions (author, 2026-07-24)

1. **`/upsell`** — one slug, programmatic chain over `offer.funnel.upsells` (no numbered slugs).
2. **`/downsell`** — one slug, after the whole upsell chain, paired downsell **only for declined** upsells.
3. **Flash-sale dates on the Landing Page** — `flash_sale_ends_at` (required) + optional `flash_sale_starts_on`;
   `/sale` optional expiration (perpetual if none). No campaign object.
4. **`/sale` and `/flash-sale` are per-page toggles** with a context-missing warning; flash blocked without an
   expiration; three flash states.
5. **Upsells/downsells live in an in-offer `offer.funnel` block** (product+price refs, separate from `items[]`)
   — one offer per funnel; keeps `offer_type` clean; unrelated product allowed. (Separate-offers idea retracted.)
6. **Default funnel = Site-native, offer-derived, single `/upsell`;** the generic step-graph `Funnel` engine is
   the future advanced tier and the reused routing substrate.
7. **`/sale` sale-price mechanism = pair by quantity + context** (schema-free; per-tier + whole-page Standard
   fallback). Buyer converts on `/sale` → checkout charges the sale price (needs `allowed_price_contexts` / a
   context-aware resolve).
8. **Order bumps = Stripe `optional_items` on the hosted Checkout page** (kept hosted Checkout for Stripe Tax;
   rejected an Elements custom checkout). Bump = designated `offer.funnel.order_bumps` product+price;
   `order_bump` reclassified pre-purchase; retire the mandatory `merge_resolved_offers` stopgap; no
   landing-page element. Needs synced Stripe Price IDs.
9. **Product → Stripe auto-sync = server-side, async, on save** (fire-and-forget Lambda `Event` invoke of
   `run_product_sync`). One Save button; the separate "Sync" button demoted to a failure-only Retry. Robust
   (completes even if the tab closes). Benefits all products; makes bump Price IDs always ready.

## Ties
`plans/SITE_OBJECT.md` (Site = funnel container, `SITE_PAGE_TYPES`); `plans/AI_AND_COMMERCE_ARCHITECTURE.md`
(Part C — contexts, focused-funnel vs shop-mode); `plans/LISTICLE_AND_CART.md` (listicles ignore funnels);
`schemas/Funnel.schema.json` + `domain/funnels.py` + `handlers/upsell.py`/`post_checkout.py`/`checkout.py`
(the reused/advanced engine); stripe-cart (behavioral reference: default-page provisioning + upsell gating).
