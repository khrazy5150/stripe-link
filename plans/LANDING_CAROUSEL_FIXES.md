# Landing-page carousel / multi-product fixes

**Status:** planned, not built. Logged 2026-07-28 from live testing of the post-purchase carousel (P3.4).
Sibling of [LISTICLE_AND_CART.md](LISTICLE_AND_CART.md) (L2 server-side cart) and
[OFFER_MODEL_REDESIGN.md](OFFER_MODEL_REDESIGN.md) §4 (carousel = a strategy, the general primitive).

The **post-purchase** carousel (offer-derived upsell/downsell grids, P3.4) works end to end. These three bugs
are all on the **landing** side — when a landing page has 2+ products it auto-renders as a carousel/shop, and
that path is still the interim "buy-now per slide" implementation, not the real multi-line cart.

---

## Bug 1 — a multi-product landing carousel only lets ONE product into the cart

**Symptom:** with 2+ landing products the page becomes a carousel; adding a second product replaces the first
(or the "cart" only ever holds one line).

**Root cause:** the client cart is the interim L1 implementation. The listicle "Add to cart" launches THAT
slide's *single-offer* checkout rather than accumulating lines in a real cart (`render_listicle_carousel`
docstring: "launches THAT offer's existing single-offer checkout. Server-side cart is a later project").

**Fix direction:** build **L2 server-side cart** (per LISTICLE_AND_CART.md): `/cart` add/patch/delete already
exist server-side; wire the landing carousel's Add to accumulate lines in the cart (multi-product), render a
real mini-cart, and check out ALL lines as one multi-line Stripe session (`cart_checkout.py` already builds a
multi-line session from a cart_id).

---

## Bug 2 — a product with multiple tiers shows only the first tier in the carousel

**Symptom:** a landing product that has several price tiers (e.g. quantity tiers) renders only its first/default
tier on its carousel slide; the buyer can't pick a tier.

**Root cause:** the carousel slide renders one resolved price per product (`single_unit_price` with the item's
default), with no per-slide tier selector. The single-product landing page DOES render a full tier selector
(`offer_price_selector`); the carousel slide doesn't reuse it.

**Fix direction:** give each carousel slide a compact tier selector (reuse the price-selector primitive per
slide, or a per-slide `<select>`), so `selectable_prices` on a landing item are pickable inside the carousel —
then the chosen tier is what's added to the cart (ties into Bug 1's cart line).

---

## Bug 3 — a multi-product landing purchase redirects back to the landing page, skipping the post-purchase funnel

**Symptom:** when the offer has upsells, buying via the multi-product (cart) path lands back on the original
landing page (`?checkout=success`) instead of entering the upsell/downsell funnel. Single-product purchases
correctly enter the funnel.

**Root cause:** the two checkout paths build different `success_url`s.
- **Single product** (`checkout_cta` island): success_url = `…/pages/{page_id}/post-checkout/next?outcome=accept&session_id={CHECKOUT_SESSION_ID}` → enters the funnel.
- **Cart** (minicart island → `cart_checkout.py`): success_url = `{landing page}?checkout=success` (verbatim
  from the client body) → never touches `/post-checkout/next`, so `post_purchase_plan` is never consulted.

**Fix direction:** when a page has a post-purchase plan, the cart checkout's success_url must also route through
`/pages/{page_id}/post-checkout/next` (first hop, no step_id → sequence upsell 1 or the upsell carousel). Either
build it client-side like the single-product CTA, or have `cart_checkout.py` rewrite the success_url to the
post-checkout entry when the page's offer derives upsells. Carry `session_id` so the one-click charge can bind
the saved payment method (the entry checkout must save the customer + PM, as the single-product path does).

---

## Sequencing note
Bugs 1 + 2 are the L2 cart build (bigger). Bug 3 is smaller and independently shippable (success_url routing)
— but it only matters once multi-product checkout is real, so it naturally rides with L2. Recommend: L2 cart
(Bug 1 + 2) then fold in Bug 3's success_url routing so multi-product buyers also see upsells.

---

## UPDATE 2026-07-28 — status + locked redesign

**L2 cart is already built** (server cart, multi-line checkout, recovery — LISTICLE_AND_CART.md). These are
DEFECTS, not missing features.

**Bug 3 — DONE (dev).** `render_listicle_carousel` emits `data-page-id` + `data-has-post-checkout`; the island's
cart Checkout builds `{api}/pages/{page_id}/post-checkout/next?outcome=accept&session_id={CHECKOUT_SESSION_ID}`
when the page has a post-checkout funnel (same gate as the buy CTA). Customer+PM already saved in
`build_checkout_payload` (reused by cart_checkout). Tests in test_page_render.py::ListicleCartFunnelTests.

**Bug 1 + Bug 2 — UNIFIED REDESIGN (author-locked 2026-07-28).** Author decision: *"Each carousel slide should
behave exactly like a single-product landing page — the product's image + its tiered pricing cards below it; the
customer selects ONE tier and clicks Add to Cart. The carousel handles single-price OR multi-price products per
slide."* This SUPERSEDES the old "listicle price = single-unit price, one synced card" model (LISTICLE_AND_CART.md
locked decisions). Root of Bug 1 (confirmed): today there's ONE shared image carousel + ONE synced price card +
ONE Add button reading `convTargets[currentIndex]`; the shared "current product" is ambiguous so adding a 2nd
product re-adds the visible one (merges to one line). Root of Bug 2: each slide binds only `single_unit_price`
(render_conversion_data), no tier selector.

Redesign = each carousel slide is a self-contained product card:
- **Slice 1 (render):** extract the per-item tier cards out of `render_offer_price_selector` into a shared helper
  (`_item_price_option_cards`); rebuild `render_listicle_carousel` so each slide = product image + that product's
  full tier selector (reused verbatim) + its OWN `data-listicle-add` button (carries `data-product-id`).
- **Slice 2 (island):** wire EVERY slide's Add button — read that slide's `input[type=radio]:checked` → add
  `{product_id, price_id}`. Drop the single-Add/`currentIndex` dependency for the cart.
- **Slice 3 (server):** `resolve_cart_line` honors the client `price_id` (a chosen landing tier), re-priced from
  the catalog + validated as a landing price for that product — NOT forced to single-unit. Update
  `test_resolve_line_uses_server_single_unit_price` to the new contract (still server-repriced, never client
  amount).
- **Slice 4:** CSS for the per-slide card carousel + tests + deploy.
