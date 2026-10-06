# One way to store a Stripe mode

**Status:** URGENT, not built. Cheapest possible moment — the tables are being wiped, so this is a schema
decision rather than a migration.

Sibling to `plans/STRIPE_MODE_DECOUPLING.md`, which settled *where mode comes from* (the request, not the
deployment). This settles *how it is stored and read*.

---

## 1. One concept, three mechanisms, two field names

| family | tables | mechanism | field |
|---|---|---|---|
| documents | 14 (products, pages, offers, sites…) | mode in the **sort key** — `SK = PRODUCT#live#id` | — |
| tenant-range | orders, customers, refunds | **server-side** `FilterExpression` | `stripe_mode` |
| ledger | ledger | **client-side Python** `_in_mode()` | **`mode`** |

Three ways to express one fact, across 46 tables and 18 distinct key shapes. None of it is legacy
inheritance — the shapes are accretion, added one entity at a time, each reasonable alone.

## 2. Why the sort key wins, concretely

`begins_with(SK, "ORDER#live#")` is a **key condition**: DynamoDB seeks to the matching range and reads
only those items.

`FilterExpression` is applied **after** the read. Read capacity is charged for every row examined, then
the non-matching ones are discarded. The client-side variant is worse again — it pays the same capacity
*and* ships every discarded row to the Lambda.

So the cost of the current design scales with **the rows you throw away**:

- a tenant with 100k orders, 95% of them test, pays to read ~95k rows on every live report;
- the same query against a mode-prefixed SK reads ~5k;
- and it is not only money — `_query_all_pages` must page through all of them, so latency tracks the
  discarded rows too.

**This matters most exactly where the tables are biggest.** Orders and the ledger grow per transaction,
forever. Products grow per catalogue edit and plateau — which is the inversion worth naming: *the one
family that already does it right is the one that needed it least.*

## 3. The bug the drift was hiding ✅ fixed 2026-10-07

`sale_entry_from_order` derived a ledger entry's mode from `order["mode"]`. The webhook's checkout path
writes that field; **nothing else does.** An upsell's `order_record` has 28 keys and none of them is
`mode` — its mode reaches storage only as `stripe_mode`, stamped by the repository on write, *after* the
in-memory dict has already been handed to the ledger.

So a **live upsell wrote a ledger entry stamped `test`**, and the fail-safe default made it silent: live
upsell revenue would be absent from live financial reports with nothing anywhere saying so. Invisible in
both deployments today only because every order in them is test-mode.

Fixed in two places, because the reader alone would have been a patch over the symptom:

- the **upsell order record now declares `"stripe_mode": mode`** itself, so the dict handed to the ledger
  carries the answer rather than relying on a stamp that happens afterwards (the author, 2026-10-07:
  *"you will also need to fix the upsells so they too include the mode"*);
- `_order_mode` reads `stripe_mode` first, so an older record still resolves correctly.

Both webhook builders already declared it; the upsell was the only gap. A test now asserts that **every**
order-record builder that feeds the ledger declares a mode, because a fourth one added later would be
just as silent — and it was verified failing against the unfixed source rather than merely passing
against the fixed one.

Two names for one fact remains the cause, and this plan is the cure.

## 4. What to change

1. **One field name.** `stripe_mode` everywhere — it is the one the repositories already stamp. `mode`
   on an order document is retired. (On a Stripe *session*, `mode` means `payment`/`subscription`; the
   collision is itself an argument for the rename.)
2. **Mode in the sort key for the tenant-range family**, matching the 14 document tables:
   `SK = ORDER#{mode}#{order_id}`, and likewise for customers, refunds and ledger entries.
3. **The GSIs need the same treatment or they reintroduce the problem.** They are the part to think
   about, not the base table:
   - `OrdersTable.CreatedAtIndex` (`tenant_id` + `created_at`) — a date-ranged report over one mode would
     filter again. Prefix the partition: `GSI1PK = TENANT#{id}#{mode}`.
   - `OrdersTable.PaymentIntentIndex` (`payment_intent_id`) — globally unique and mode-implicit. Leave it.
   - `LedgerTable.OrderIndex` (`order_id` + `occurred_at`) — order ids are globally unique. Leave it.
   - `RefundsTable.StripeRefundIndex` — same. Leave it.
4. **Keep the fail-safe.** `normalize_stripe_mode` must stay "anything not explicitly live is test".
   Under-reporting real revenue is recoverable; reporting test money as real is not.
5. **Keep the loud refusal.** A mode-scoped repository constructed without a mode already raises rather
   than reading a third, empty key space. That guard is why this was findable at all.

## 5. Why now

The tables are being wiped, so there is no migration to write, no dual-read window, and no backfill. The
same change after real tenants have volume means rewriting every order and ledger row's sort key — a
migration that cannot be done in place, because the sort key is part of the primary key.

**This is the last cheap moment.**

## 6. Deliberately out of scope

- Collapsing the 46 tables. The bespoke shapes earn their keep: orders are genuinely queried by
  payment-intent and by date, the ledger by order and by `occurred_at`. Table count is not the problem.
- `plans/STRIPE_MODE_DECOUPLING.md`'s own phases. That plan decides which deployment serves which mode;
  this one only changes how a row records the answer.
