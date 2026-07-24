# Sales Funnels in the Sites Paradigm

**Status:** design (author-clarified 2026-07-24), not built. **HIGH PRIORITY.** Home: closes the loop for
transaction (Stripe) landing pages. Extends — does not replace — the existing commerce pieces
(`plans/AI_AND_COMMERCE_ARCHITECTURE.md` Part C, the price-`context` model, `handlers/upsell.py`,
`handlers/post_checkout.py`).

## The core idea (author-confirmed)

**A Site IS a sales funnel** — for a single offer. The funnel's steps and views are addressed by **reserved
slugs** within the Site, which tenants may never use for their own pages:

| Slug | Kind | What it renders |
|------|------|-----------------|
| `/` | sales page | The offer at its **Standard** price. |
| `/sale` | *context view of `/`* | The **same** sales page, Standard price replaced by the **sale**-context price + a "Sale" badge. Falls back to Standard when no sale price. |
| `/flash-sale` | *context view of `/`* | The same sales page with the **flash_sale**-context price, a 🔥 "Flash Sale" badge, and a **countdown banner**. Falls back to Standard when there's no flash price **or it has expired**. |
| `/upsell` | funnel-step page | Post-purchase, one-click: presents each product in the offer that has an **upsell** price, one by one. Only reachable when the offer has ≥1 upsell price. |
| `/downsell` | funnel-step page | Post-purchase, one-click: the **downsell**-context price, shown when an upsell is declined (if the product has one). |
| `/thank-you` | funnel-step page | Funnel end. |

Two distinct kinds of reserved slug fall out of this:

- **Context views** (`/sale`, `/flash-sale`) — NOT separate page documents. They render the `/` page's own
  content with a different price context applied (price + badge + optional countdown). Removing the slug
  (back to `/`) shows Standard. This is a **routing + render-context** feature, not new pages.
- **Funnel-step pages** (`/upsell`, `/downsell`, `/thank-you`) — real page documents the builder
  auto-provisions and the tenant can customize (copy/layout); their **product content is derived** from the
  offer's contextual prices (which products, at what price).

Listicle offers deliberately **ignore** upsell funnels (AI_AND_COMMERCE Part C: "focused funnel" vs "shop
mode"). Funnels apply to `single`/`bundle` offers.

## Pricing contexts drive everything (already modeled)

A product's prices carry a `context`: `standard`, `sale`, `flash_sale`, `order_bump`, `upsell`, `downsell`
(enum already validated). The funnel reads these — **the pricing context IS the funnel wiring**, so there's
minimal separate funnel config:

- **Pre-purchase, on the sales page:** `standard` (default), `sale` (`/sale`), `flash_sale` (`/flash-sale`).
- **Pre-purchase, in checkout:** `order_bump` → a checkbox add-on folded into the initial Stripe session
  (already built: `resolve_order_bumps` in `handlers/checkout.py`).
- **Post-purchase, one-click:** `upsell` (`/upsell`), `downsell` (`/downsell`).

## Pre-purchase views: `/sale` and `/flash-sale`

Render the `/` sales page, swapping only the price card:
- Resolve the offer item's price at the requested context; if absent (or flash expired) → Standard, no badge.
- `/sale`: show the sale price + a **"Sale"** badge on the price card.
- `/flash-sale`: show the flash price + a **🔥 "Flash Sale"** badge + a **countdown banner** at the top of
  the page counting down to the flash's expiry. On expiry the page is just the Standard `/` page again.
- **Needs:** a flash-sale **expiry** (`flash_sale_ends_at`) — recommend storing it on the `flash_sale` price
  (per-product) so the countdown + fallback are derived, not hand-managed. (Open decision below.)

## Post-purchase chain: `/upsell` → `/downsell` → `/thank-you`

- After the `/` checkout is **paid**, the buyer is routed into the funnel (Site-aware routing already exists:
  `handlers/post_checkout.py`). One-click charging against the saved payment method already exists
  (`handlers/upsell.py` — `get_upsell_session` + `process_upsell`, idempotent by `sequence`).
- **Which products upsell:** iterate the offer's products; each with an `upsell` price becomes an upsell step,
  presented **one by one**. Products without an upsell price are **skipped**. Same rule for `downsell`.
- **Accept** → one-click charge → next upsell product (or `/thank-you`). **Decline** → the product's
  `downsell` price if present (`/downsell`), else next product → eventually `/thank-you`.
- `/upsell` (and `/downsell`) are **only provisioned/reachable when the offer actually has** those prices —
  mirroring stripe-cart, which only showed the upsell page if the offer had an upsell.

## Auto-provisioning (builder), like stripe-cart

Creating a funnel Site auto-creates the funnel pages from the offer's contexts + tenant "funnel
configuration" defaults (the `page_defaults.upsell` / `thank_you` config that already exists in
Configuration): always `/` + `/thank-you`; add `/upsell` (and `/downsell`) iff the offer has those prices.
Port stripe-cart's default-page generation behavior into the Sites/builder flow.

## Reserved-slug enforcement

- Define a reserved set — `{"", "sale", "flash-sale", "upsell", "downsell", "thank-you"}` (the empty slug is
  `/`, the sales page).
- **Reject** these as tenant-chosen slugs in page creation + the Site page-assignment flow (validation +
  the builder slug picker).
- The Site's route resolver maps the context-view slugs (`/sale`, `/flash-sale`) to the `/` page + a render
  context, and the funnel-step slugs to their pages.

## Extend vs. build

**Extend (already built):** price `context` enum; order-bump folding (`resolve_order_bumps`); one-click
upsell charging (`handlers/upsell.py`); Site-aware post-checkout routing + `page.post_checkout`
funnel_steps/thank_you config; `SITE_PAGE_TYPES` includes `thank_you` + `funnel_step`.

**Build:** reserved-slug set + enforcement; the Site route resolver for context views; `/sale` + `/flash-sale`
render path (price swap + badges + countdown) with `flash_sale_ends_at` + expiry fallback; auto-provisioning
of funnel pages from the offer; wiring the upsell/downsell **chain** (product-by-product, decline→downsell)
onto the existing one-click charge; and reconciling the current arbitrary `funnel_steps` config with the
reserved-slug model (the reserved slugs become the canonical funnel; `funnel_steps` becomes the derived
step graph rather than hand-authored).

## Open decisions (recommendations — confirm before Phase 2)

1. **Upsell sequencing across multiple upsell products:** one `/upsell` slug advancing by a **step index**
   (reuse the existing `sequence`/`funnel_step`) — *recommended* — vs. numbered slugs (`/upsell`, `/upsell-2`).
2. **Downsell trigger:** per-upsell-product (decline product A's upsell → A's downsell) — *recommended* — vs.
   a single `/downsell` after the whole upsell chain.
3. **Flash-sale expiry storage:** on the `flash_sale` **price** (`flash_sale_ends_at`, per product) —
   *recommended* — vs. on the page/offer (one campaign window).
4. **`/sale` `/flash-sale` availability:** auto-available whenever a sale/flash price exists — *recommended* —
   vs. an explicit per-Site enable toggle.
5. **Multiple products on `/sale`:** for a multi-item offer, does `/sale` swap every item's price to its sale
   price (recommended), and skip items with no sale price (keep Standard)?

## Phasing

- **P1 — Pre-purchase (no payment changes):** reserved-slug set + enforcement + Site route resolver;
  `/sale` + `/flash-sale` context views (price swap, Sale/🔥 badges, countdown + `flash_sale_ends_at`
  expiry fallback). Highest value, lowest risk — no checkout changes.
- **P2 — Post-purchase chain:** auto-provision funnel pages from the offer; wire the product-by-product
  upsell→(downsell)→thank-you chain onto the existing one-click charge + post_checkout routing; gate on the
  offer actually having those prices.
- **P3 — Polish:** builder UX for funnel configuration, analytics per funnel step, AI-assisted funnel copy.

## Ties
`plans/AI_AND_COMMERCE_ARCHITECTURE.md` (Part C, contexts), `plans/SITE_OBJECT.md` (Site = funnel container,
`SITE_PAGE_TYPES`), `plans/LISTICLE_AND_CART.md` (listicles ignore funnels; flash-sale noted-not-built there),
`handlers/upsell.py` + `handlers/post_checkout.py` + `handlers/checkout.py` (the built skeleton),
stripe-cart (behavioral reference for default-page provisioning + upsell gating).
