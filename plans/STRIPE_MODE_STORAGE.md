# One way to store a Stripe mode

**Status:** ✅ BUILT 2026-10-07, not yet deployed. Tables were truncated first (the prerequisite below). Cheapest possible moment — the tables are being wiped, so this is a schema
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

## 4. What changed ✅

1. ✅ **One field name.** `stripe_mode` everywhere — it is the one the repositories already stamp. `mode`
   on an order document is retired. (On a Stripe *session*, `mode` means `payment`/`subscription`; the
   collision is itself an argument for the rename.)
2. ✅ **Mode in the PARTITION key for the tenant-range family** — `PK = TENANT#{tenant_id}#{mode}` — with
   synthetic `PK`/`SK` attributes and `tenant_id`/`order_id` kept as ordinary document fields, stripped on
   read exactly as the document family already does.

   **Not the sort key**, which this plan originally said and which is wrong. For the document family the
   SK is synthetic (`PRODUCT#live#id`) so mode costs nothing there. For orders the sort key *is*
   `order_id` — a business identifier written into Stripe PaymentIntent metadata (`metadata[order_id]`)
   and used as the partition key of **two** GSIs, `LedgerTable.OrderIndex` and `RefundsTable.OrderIndex`.
   Prefixing it would leak the mode into a value that travels to Stripe and joins three tables. Caught
   2026-10-07 before any code was written.

   Putting it in the partition instead keeps `order_id` clean, makes `list_for_tenant` a key condition,
   and makes `OrdersTable.CreatedAtIndex` mode-scoped for free because its partition key is the tenant.
3. ✅ **The GSIs mostly fell out of (2) for free**, which is the second reason to prefer the partition key:
   - `OrdersTable.CreatedAtIndex` (`tenant_id` + `created_at`) — becomes mode-scoped automatically once
     the tenant key carries the mode.
   - `OrdersTable.PaymentIntentIndex` (`payment_intent_id`) — globally unique and mode-implicit. Leave it.
   - `LedgerTable.OrderIndex` (`order_id` + `occurred_at`) — order ids stay clean, so leave it.
   - `RefundsTable.StripeRefundIndex` — same. Leave it.
4. ✅ **Kept the fail-safe.** `normalize_stripe_mode` must stay "anything not explicitly live is test".
   Under-reporting real revenue is recoverable; reporting test money as real is not.
5. ✅ **Kept the loud refusal**, and extended it. A mode-scoped repository constructed without a mode already raises rather
   than reading a third, empty key space. That guard is why this was findable at all.

## 5. Why now

The tables are being wiped, so there is no migration to write, no dual-read window, and no backfill. The
same change after real tenants have volume means rewriting every order and ledger row's sort key — a
migration that cannot be done in place, because the sort key is part of the primary key.

**This is the last cheap moment** — but note what "cheap" rests on. A KeySchema change (new key
attribute names) cannot be applied in place: CloudFormation REPLACES the table, and the data goes with
it. So this is free only if the tables are wiped anyway, and it is a hard prerequisite rather than a
convenience. **Sequence: wipe, then schema, then deploy, then live.**

## 6. Deliberately out of scope

- Collapsing the 46 tables. The bespoke shapes earn their keep: orders are genuinely queried by
  payment-intent and by date, the ledger by order and by `occurred_at`. Table count is not the problem.
- `plans/STRIPE_MODE_DECOUPLING.md`'s own phases. That plan decides which deployment serves which mode;
  this one only changes how a row records the answer.


## 7. What it turned up on the way

- **Refunds were not mode-scoped at all.** `RefundsRepository` took no `mode` parameter and nothing
  filtered — the ledger's gap, one table over, latent only because the table was empty. It would have
  surfaced the first time anyone refunded a live order. Now partitioned like the rest.
- **Five ledger call sites were reading both modes**, and the loud constructor found every one of them
  the moment it started refusing an absent mode. That is the refusal earning its keep rather than being
  a nuisance.
- **`OrdersTable.CreatedAtIndex` was dropped.** It partitioned on `tenant_id`, so it spanned both modes
  by construction — and nothing queried it. An unused index that can only answer the wrong question is a
  trap for whoever reaches for it next.
- **The mode-isolation tests were passing vacuously.** Their fake table returned every row for any query,
  which modelled a client-side filter well enough but cannot model a partition. Rewritten to partition,
  and verified by pointing the repository at the wrong key and watching three tests fail.
