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

Fixed for new entries. **The 76 existing entries are still blank**, and the orders they came from are all
still present, so a backfill is possible and cheap. Worth doing before any report ships, or the first
thing a tenant sees is a year of "unattributed".

### 2b. `shipping_margin` is honest per-entry and misleading in aggregate

The summary reports **$864.13** of shipping margin. It is arithmetically correct and practically a lie:
only **5 of 71** sales have had a label bought, so `shipping_cost` is missing for the other 66 and the
figure reads as a ~96% margin on postage.

`summarize` already refuses to invent a margin when `shipping_cost` is entirely absent (returns `None`
rather than `revenue + 0`, deliberately). The partial case was not considered. A report must either
restrict the margin to orders that have a label, or state the coverage beside it ("5 of 71 shipped").
This is the one number in the summary a tenant could act wrongly on.

### 2c. Orders do not record which TIER was bought

A tiered offer sells 1 / 2 / 3 bottles as three **Prices of the same product**. Stripe's line item
therefore says `quantity: 1` and `name: "Creatine Gummies"` whatever the buyer chose; the tier lives only
in our own price document's `quantity`. So neither the Orders screen nor any report can say which tier
sold — and "which tier converts" is one of the questions a tiered offer exists to answer.

Fix at **write time**, not display time: resolve the line's `stripe_price_id` against the product's
prices in the webhook and stamp `unit_quantity` (and the offer's label where there is one) onto the line
item. The webhook already holds `products_repo` before `order_record_from_session` is called. Display-time
resolution would leave every historical order unreadable and put the same lookup in two screens.

## 3. Shape of the reports themselves

One screen, date-ranged, reading `/ledger`. Sections in the order a tenant actually asks:

1. **Money** — gross, fees, shipping, net, profit, for the period and against the previous one. Already
   computable today; this is `summarize` with a date filter.
2. **What sold** — revenue and units by product, then by offer. Needs 2a (shipped) and 2c.
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

1. **Backfill 2a** on existing entries from their orders.
2. **2c**, so the tier is recorded from now on.
3. Report 1 (**Money**) — almost free, and it is what enables the menu item.
4. Report 2 (**What sold**) — the first one that needs the work above.
5. Reports 3–5 as wanted.

Steps 1–3 are small and unblock the disabled menu. 4 onward is where the real work is.
