# Reporting

**Status:** planned. The Reports menu item in `App.vue` is `disabled` because nothing is behind it.

---

## 1. What already exists (more than expected)

`/ledger` returns every entry plus `domain/ledger.summarize()`, and on real dev data that summary is
already correct and complete:

| | |
|---|---|
| gross | $7,796.12 |
| stripe_fee | −$205.09 |
| platform_fee | −$258.63 |
| shipping_revenue | $895.71 |
| shipping_cost | −$31.58 |
| **net** | **$7,332.40** |
| **profit** | **$7,300.82** |
| merchandise_revenue | $6,900.41 |

76 entries across two sources (`webhook` 52, `upsell` 24). Sales, refunds and shipping costs all post to
it; fees are trued against Stripe's balance transactions by the reconciliation sweep.

**So reporting is mostly a presentation and slicing job, not a new accounting layer.** That is the good
news and it should stay that way: a second place that adds money up is a second place for it to be wrong.

## 2. What blocks it

### 2a. The ledger does not know what was sold ✅ fixed 2026-10-06

`sale_entry_from_order` read `order["offer_id"]` and `order["product_id"]` **flat**. Both order paths
write them **nested** (`attribution.offer_id`, `product.product_id`), so both were always `None` and were
dropped — **not one entry ever written carries a product or an offer.**

Every question a report exists to answer — which product earns, which offer converts, what a funnel is
worth — was unanswerable, and nothing said so, because an absent field looks exactly like a sale that
genuinely had none. Identical in shape to the `fees` bug recorded twelve lines above it in the same
function.

Fixed for new entries, and **the 67 fillable existing entries were backfilled from their orders**
(2026-10-06). The ledger now answers the question it exists for — top products by revenue: Creatine
Gummies $2,700.55, Aipas M2 Max Electric Bike $1,666.35, Electric Scooter $284.93; top offers: Workout
Bundle $2,952.06, E-Transport $1,951.28. $2,539.13 remains unattributed by product (subscription and
invoice entries that carry no product block) and is reported as such rather than hidden.

### 2b. `shipping_margin` is honest per-entry and misleading in aggregate

The summary reports **$864.13** of shipping margin. It is arithmetically correct and practically a lie:
only **5 of 71** sales have had a label bought, so `shipping_cost` is missing for the other 66 and the
figure reads as a ~96% margin on postage.

`summarize` already refuses to invent a margin when `shipping_cost` is entirely absent (returns `None`
rather than `revenue + 0`, deliberately). The partial case was not considered. ✅ `/ledger` now returns
`shipping_cost_coverage: {shipped, sales}` and the report states it beside the figure — *"Shipping paid
covers 5 of 71 sales — the rest have no label bought yet, so shipping margin reads higher than it will
finish."* Stated, never silently corrected.

### 2c. Orders do not record which TIER was bought

A tiered offer sells 1 / 2 / 3 bottles as three **Prices of the same product**. Stripe's line item
therefore says `quantity: 1` and `name: "Creatine Gummies"` whatever the buyer chose; the tier lives only
in our own price document's `quantity`. So neither the Orders screen nor any report can say which tier
sold — and "which tier converts" is one of the questions a tiered offer exists to answer.

✅ **Shipped 2026-10-06, and it needed no product read at all.** The key back was always in the payload:
`build_price_params` stamps our own `price_id` into every Stripe Price's metadata and the line-item fetch
already expands `data.price` — it was simply discarded. The offer's `selectable_prices` then supplies both
the size and the tenant's own label, so it is **one offer read** per order and no product lookup.

The label **cannot** be stamped onto the Stripe Price at sync time, which is what settled the design: it
belongs to the (offer, price) PAIR. Proven in real data — `price_NxQYoPLerzo` is "1 Item" in one offer and
"Every day" in another. Stamping would describe the second offer's orders in the first offer's words.

**And it uncovered a live shipping bug.** `resolve_order_lines` kept Stripe's `quantity: 1`, so a "3
Items" tier was packed and labelled as ONE unit — a box too small and a label too cheap, re-billed by the
carrier weeks later. The buyer's own quote was right all along (the landing page passes the tier quantity
to `shipping_quote`), so the two halves of one sale disagreed and only the label said so. Fixed: the
packer multiplies by `unit_quantity`, and the packing slip counts rather than repeats ("NAD Supplement
x3").

## 3. Shape of the reports themselves

One screen, date-ranged, reading `/ledger`. Sections in the order a tenant actually asks:

1. **Money** ✅ shipped 2026-10-06 — gross, merchandise, shipping collected, Stripe and platform fees,
   shipping paid, net, profit; period-selectable, compared against the same length of time immediately
   before. Filtering is server-side on `occurred_at`. The Reports menu item is no longer disabled.
2. **What sold** ✅ shipped 2026-10-06 — revenue, units and orders by product, with the order-bump share
   called out, ranked by revenue.

   **It could not be grouped on `entry.product_id`.** That names the order's PRIMARY product while
   `gross` is the whole order, so a bump's revenue lands on the headline product and the bump reads as
   never having sold: Creatine Gummies $2,700.55 against $320.38 of its own lines, and a bump that had
   genuinely sold $28.90 reading zero. 20 of 73 orders had more than one line.

   So each sale entry now records `lines[]` — product, price, units, gross, and whether it was a bump —
   and the endpoint rolls them up. Money is still added up in exactly one place; a report that summed
   line revenue for itself would be a second ledger.

   Two double-counts surfaced only because the total had to reconcile: an **upsell**'s `amount_total` is
   postage-inclusive while that postage is also shipping revenue ($449.12 over across 39 upsells), and a
   **bump surcharge** sits inside its line's price and in shipping revenue too ($1.50). Both are now
   subtracted, and lines + unitemised + shipping equals gross to the cent — $8,026.95 on real data.

   Sales with no breakdown are reported as **"Not itemised"** rather than spread across products or
   dropped: a product table whose rows do not add up to the money table is worse than one that says which
   part it cannot place. All 73 entries were backfilled, so that row is currently $0.00.
3. **Funnel** — checkout vs bump vs upsell revenue, take-up rate per step. `entry.source` already
   separates upsells; bumps need `is_order_bump` rolled up from the order's line items.
4. **Shipping** — collected vs paid, per the coverage caveat in 2b. The one report that pays for itself:
   it is where a tenant discovers a product that loses money to post.
5. **Export** — CSV of the underlying entries. Cheap, and it is what an accountant will ask for first.

## 4. Rules

- **One place adds up money.** Reports slice and present `domain/ledger`; they never re-derive a total
  from orders. Where a report needs a figure the ledger does not have, the fix is to record it on the
  entry, not to compute it in the report.
- **Never a figure whose basis is partial without saying so** (2b). This repo has been bitten twice by
  authoritative-looking numbers that were structurally wrong: `tax_liability`, and `shipping_margin`
  before `shipping_cost_entry` existed.
- **Date filtering server-side.** `occurred_at` is on every entry; shipping the whole ledger to the
  browser to filter it stops working on the first real tenant.
- **Mode-scoped, like `/ledger` already is.** Test money must never be added to real money.

## 5. Order of work

1. ✅ **Backfill 2a** — 67 entries filled from their orders.
2. ✅ **2c** — tier recorded, and a packing bug fixed with it.
3. ✅ Report 1 (**Money**).
4. ✅ Report 2 (**What sold**) — shipped 2026-10-06, and it needed more than the backfill.
5. Reports 3–5 (**Funnel**, **Shipping**, **Export**) as wanted.

## 6. The Dashboard's "Net Revenue" card contradicts the ledger (found 2026-10-08)

The headline card on the Dashboard is wrong twice over, and in the direction that flatters. Measured on
four real live transactions — two $1.45 sales, both fully refunded:

| | |
|---|---|
| Dashboard "Net Revenue" | **$2.90** |
| ledger, and Stripe's own Net volume | **−$0.88** |

`dashboard.js` `revenueCents()` sums `amounts.amount_paid` across orders. So it is **gross**, not net — no
fee is subtracted, though the order carries `fees.platform_fee` and `fees.stripe_fee` — and it **never
reads refunds**, though `amount_refunded` sits on the same document. Two refunded sales therefore read as
$2.90 of revenue that no longer exists. The label says "Net Revenue" and the subtitle "From paid
invoices", and neither is true: it is gross, and they are orders.

**The fix is small, because the right answer already exists.** `Reports.vue` reads `/ledger`, which nets
fees and reverses refunds and reconciled to Stripe to the penny on these same four transactions. The
Dashboard card should read the same source rather than re-deriving a second, worse answer from orders.

Two things to settle while doing it:

- **Say which number it is.** Gross, net-of-fees and net-of-fees-and-refunds are three different figures a
  tenant cares about. The card should name the one it shows, per §4's rule about figures whose basis is
  not stated.
- **An order is not an invoice.** `state.invoices` holds orders, and "Total Orders: 2" counts the same
  list. The naming predates the split and misleads anyone reading the getter.
