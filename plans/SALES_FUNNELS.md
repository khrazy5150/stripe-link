# Sales Funnels in the Sites Paradigm

**Status:** design LOCKED (author-clarified 2026-07-24; only the "upsells = separate offers" resolution
awaits a final ✓), not built. **HIGH PRIORITY.** Home: closes the loop for
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
| `/flash-sale` | *context view of `/`* | The same sales page with the **flash_sale**-context price, a 🔥 "Flash Sale" badge, and a **countdown banner** — driven by page dates (upcoming/active/ended). Standard when no flash price, not started, or expired. |
| `/upsell` | funnel-step page | Post-purchase, one-click: walks the main offer's `upsells[]` (separate offers) one by one. Only reachable when the offer references upsells. |
| `/downsell` | funnel-step page | Post-purchase, one-click: walks the main offer's `downsells[]`, **after** the whole upsell chain. |
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

Both render the `/` sales page, swapping only the price card(s). **Both are per-Landing-Page TOGGLES** (not
auto-enabled). When a tenant toggles one on, if the offer's product has **no** matching price context, show a
warning: *"This product doesn't have a Sale pricing context. Please go to the products page and set it there."*
For a multi-item (listicle) offer, only the items **with** a sale/flash price change; items without keep
Standard.

### `/sale`
- Optional **expiration date** on the Landing Page. No expiration → **perpetual** sale.
- Shows the `sale`-context price + a **"Sale"** badge. Past expiration (or no sale price) → Standard, no badge.

### `/flash-sale` — dates live on the Landing Page (`flash_sale_starts_on?`, `flash_sale_ends_at`)
Dates on the **page** (not the price, not a campaign) so a tenant just sets a window for a TikTok/IG Live.
- **Expiration is REQUIRED to enable.** Toggling on without one → block with: *"You must set an expiration
  date in order to enable this feature."*
- **Three states** (start date optional):
  - **Upcoming** (before `flash_sale_starts_on`): banner *"Flash Sale Coming Up on {date}"*, price stays
    **Standard**.
  - **Active** (between start and end, or before end when no start): banner **countdown** to `ends_at`, price
    cards show the **flash_sale** price + a **🔥 "Flash Sale"** badge (where the Sale badge would sit).
  - **Ended** (after `flash_sale_ends_at`): banner *"Flash Sale ended"*, price reverts to **Standard**.

## Post-purchase chain: `/upsell` → `/downsell` → `/thank-you`

### Upsells/downsells are SEPARATE OFFERS, not products inside the main offer (resolves the listicle conflict)

**The conflict (author-spotted):** a multi-product offer auto-infers to `listicle`, and listicles ignore
funnels by design — so you can't put "the main product + separate upsell products" in one offer's `items[]`
without turning it into a listicle. **Resolution:** an upsell/downsell is **its own Offer** (`context:
"upsell"` / `"downsell"`), referenced by the main offer — **exactly how order bumps already work**
(`resolve_order_bumps` merges separate `context: "order_bump"` offers by id). So:
- The main offer's `items[]` alone drive `offer_type` (single/bundle/listicle) — **untouched** by funnel steps.
- An upsell can be an **unrelated product** (or a bundle) — it's just another Offer, with its own
  headline/image/CTA for `/upsell`. No new `offer_type`; the existing `context` field is the marker.
- Funnel reference on the main offer: `offer.funnel = { upsells: [offer_id…], downsells: [offer_id…] }`
  (ordered). Order bumps stay as they are (checkout add-ons).
- Funnels apply to **single/bundle** main offers; **listicles ignore them** (shop mode → cart, not funnel).

### Flow

- After the `/` checkout is **paid**, the buyer is routed into the funnel (Site-aware routing already exists:
  `handlers/post_checkout.py`). One-click charging against the saved payment method already exists
  (`handlers/upsell.py` — `get_upsell_session` + `process_upsell`, idempotent by `sequence`).
- **`/upsell` — one slug, a programmatic chain.** It walks the main offer's `upsells[]` array **one by one**
  (NO `/upsell-1`/`/upsell-2` in the URL — a single `/upsell` slug advancing by an internal step index).
  Accept → one-click charge → next upsell. Decline → next upsell.
- **`/downsell` — one slug, after the ENTIRE upsell chain.** Once the upsell chain finishes, walk the
  `downsells[]` array the same way, one by one, on a single `/downsell` slug.
- → `/thank-you`.
- `/upsell` / `/downsell` are **only reachable when the main offer references** such offers — mirroring
  stripe-cart (only showed the upsell page if the offer had an upsell).

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
render path (price swap + Sale/🔥 badges + countdown) driven by **page-level** dates
(`flash_sale_starts_on?` / `flash_sale_ends_at`, `sale_ends_at?`) with the three flash states + toggles +
"no context" warning + "expiration required" block; the `offer.funnel = {upsells[], downsells[]}` reference
(separate `context: upsell/downsell` offers); auto-provisioning of funnel pages from the offer; wiring the
`/upsell` then `/downsell` **chains** onto the existing one-click charge; and reconciling the current
arbitrary `funnel_steps` config with the reserved-slug model (reserved slugs become the canonical funnel).

## Resolved decisions (author, 2026-07-24)

1. **Upsell sequencing:** ONE `/upsell` slug, a programmatic chain over the `upsells[]` array (no
   `/upsell-1`/`-2` in the URL). ✓
2. **Downsell:** ONE `/downsell` slug, walked **after the entire upsell chain** completes. ✓
3. **Flash-sale dates live on the Landing Page** — `flash_sale_ends_at` (required) + optional
   `flash_sale_starts_on` (no separate campaign object). `/sale` gets an optional expiration (perpetual if
   none). ✓
4. **`/sale` and `/flash-sale` are per-page toggles** (not auto), with a warning when the product lacks the
   context; flash-sale is **blocked** without an expiration; three flash states (upcoming/active/ended). ✓
5. **Upsells/downsells are separate Offers** (`context: upsell`/`downsell`) referenced by the main offer,
   like order bumps — resolving the "multi-product = listicle" conflict. Listicles ignore funnels; `/sale`
   on a listicle swaps only items that have a sale price. ✓ *(Recommendation — confirm to fully lock.)*

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
