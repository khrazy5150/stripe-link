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
- Order bumps currently reference separate `context: order_bump` offers (already built via
  `resolve_order_bumps`); they can fold into `offer.funnel.order_bumps` later for consistency, or stay as-is.

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

Order bumps (`context: order_bump`) fold into the initial `/` Stripe checkout as add-on checkboxes (built).

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
| price `context` enum, `resolve_order_bumps` | **REUSE** as-is. |

**Net:** one default funnel model (Site-native, offer-derived, single `/upsell`) that reuses the built
routing/charge plumbing; the generic step-graph becomes the opt-in advanced tier.

## Plan of action (phased)

- **P0 — already built (inventory):** price `context` enum; order-bump folding; one-click upsell charging;
  Site-aware post-checkout routing + the transition engine; `SITE_PAGE_TYPES` includes `thank_you`/`funnel_step`.
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
- **P2 — Post-purchase default funnel:** the `offer.funnel` block; auto-provision funnel pages from the offer;
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

## Ties
`plans/SITE_OBJECT.md` (Site = funnel container, `SITE_PAGE_TYPES`); `plans/AI_AND_COMMERCE_ARCHITECTURE.md`
(Part C — contexts, focused-funnel vs shop-mode); `plans/LISTICLE_AND_CART.md` (listicles ignore funnels);
`schemas/Funnel.schema.json` + `domain/funnels.py` + `handlers/upsell.py`/`post_checkout.py`/`checkout.py`
(the reused/advanced engine); stripe-cart (behavioral reference: default-page provisioning + upsell gating).
