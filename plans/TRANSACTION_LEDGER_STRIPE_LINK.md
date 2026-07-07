# Transaction Ledger — stripe-link redesign

**Status:** design, not yet built · **Home:** PRD Phase 5 (Commerce Foundations) · **Supersedes:**
the stripe-cart `plans/TRANSACTION_LEDGER_IMPLEMENTATION.md` (behavioral reference only — do **not**
port it verbatim; it is single-merchant, raw-boto3, and scans full partitions).

## Why

stripe-link tracks money as **mutable per-order summary state** (`amount_paid`, `amount_refunded`,
`stripe_fee`, `platform_fee`, `net_payout`) plus a `RefundsTable` and a `WebhookEventsTable`. That
answers "what is this order's status" but not "what did the tenant actually *make*," and the
summaries are authored by overwrite — when a webhook is missed or double-applied they drift with no
record to reconcile against.

This ledger makes an **append-only record of financial events the canonical source of truth**, and
demotes the order aggregates to a *derived cache*. It adds the P&L layer we completely lack
(fees + COGS + shipping → profit) and is the substrate the tax reporting in PRD Phase 8 needs
(collected tax is trust money that must be reported by jurisdiction).

## Principles

1. **Append-only.** Entries are immutable. A correction is a new **reversing entry**
   (`reverses_entry_id`), never an edit or delete.
2. **Canonical, not parallel.** The ledger is the source of truth; order payment aggregates and the
   refund history are **derived** from it. We consolidate — we do not add a fourth money table
   beside Orders/Refunds/WebhookEvents (see [Consolidation](#consolidation)).
3. **Additive amounts.** Every monetary component is a **signed** integer (minor units) from the
   tenant's-cash perspective — inflow positive, outflow negative. Summing any component over a date
   range yields that component's running total. **No `abs()` gymnastics, no stored `net`/`profit`
   that can drift** — derived metrics are pure sums, computed in one tested domain function.
4. **Two-party aware.** Direct-charge Connect means the charge/balance-transaction live on the
   **tenant's** connected account and the platform earns an **application fee**. The ledger is the
   **tenant's book**; the **platform's revenue** (sum of `platform_fee`) is a *derived rollup*, not a
   second write stream. Every entry is explicit about both.
5. **stripe-link idioms.** JSON-first document + validator, a document repository, `mode` dev/prod
   routing, thin handlers, pure domain builders — like Orders/Refunds/Offers.
6. **Fast reads by construction.** Dashboards read **daily rollups**, not raw entries. Ad-hoc
   queries are **date-range-bounded** via the sort key — never "scan the whole partition and sum in
   Python" (the stripe-cart plan's flaw).

## Data model — `LedgerEntry`

`document_type: "ledger_entry"`, stored in a `LedgerTable` (one per stack; `mode` selects dev/prod
resources, consistent with the existing `mode` primitive). Validated by `validate_ledger_entry`
(domain) — schema below is the contract.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.stripe-link.local/LedgerEntry.schema.json",
  "title": "LedgerEntry",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "document_type", "tenant_id", "entry_id", "entry_type",
    "occurred_at", "mode", "currency", "amounts", "idempotency_key"
  ],
  "properties": {
    "schema_version": { "type": "string" },
    "document_type": { "const": "ledger_entry" },
    "tenant_id": { "type": "string" },
    "entry_id": { "type": "string", "description": "le_… — platform-generated, unique." },
    "entry_type": {
      "enum": [
        "sale", "refund", "dispute", "dispute_won",
        "shipping_cost", "cost_adjustment", "fee_adjustment",
        "tax_remittance", "adjustment"
      ]
    },
    "occurred_at": {
      "type": "integer",
      "description": "Epoch seconds of the financial event (from Stripe when available). Drives reporting periods; the repository derives the ISO sort-key from it."
    },
    "mode": { "enum": ["test", "live"] },
    "currency": { "type": "string" },

    "order_id": { "type": "string" },
    "line_item_id": { "type": "string", "description": "Optional per-line attribution; ties to the Phase 5 line-item order model." },
    "offer_id": { "type": "string" },
    "product_id": { "type": "string" },
    "customer_ref": {
      "type": "object",
      "additionalProperties": false,
      "properties": { "email": { "type": "string" }, "name": { "type": "string" } }
    },

    "stripe": {
      "type": "object",
      "additionalProperties": false,
      "description": "References for reconciliation and idempotency.",
      "properties": {
        "charge_id": { "type": "string" },
        "payment_intent_id": { "type": "string" },
        "balance_transaction_id": { "type": "string" },
        "refund_id": { "type": "string" },
        "dispute_id": { "type": "string" },
        "event_id": { "type": "string" }
      }
    },

    "amounts": {
      "type": "object",
      "additionalProperties": false,
      "description": "Signed minor units. Additive across entries; sign is tenant-cash perspective (inflow +, outflow -). Absent field = 0.",
      "properties": {
        "gross": { "type": "integer", "description": "Customer-facing amount. + on sale, - on refund." },
        "stripe_fee": { "type": "integer", "description": "ACTUAL Stripe fee from the balance transaction. <= 0 on sale." },
        "platform_fee": { "type": "integer", "description": "Application fee earned by the platform; from the tenant's book an expense. <= 0 on sale." },
        "tax": { "type": "integer", "description": "Tax collected (+) or remitted (-). Liability / trust money — never counted as profit." },
        "cogs": { "type": "integer", "description": "Cost of goods sold. <= 0. Populated only when product cost data exists." },
        "shipping_cost": { "type": "integer", "description": "Actual shipping-label cost. <= 0." }
      }
    },

    "idempotency_key": {
      "type": "string",
      "description": "Stable key for this financial effect, e.g. 'sale:{charge_id}', 'refund:{refund_id}', 'dispute:{dispute_id}'. Guards against double-recording; unique per tenant."
    },
    "source": { "enum": ["webhook", "manual", "migration", "reconciliation"] },
    "reverses_entry_id": { "type": "string", "description": "For corrections: the entry_id this reversing entry offsets." },
    "description": { "type": "string" },
    "metadata": { "type": "object" },
    "created_at": { "type": "integer", "description": "When we recorded it (epoch). Immutable — no updated_at; the ledger is append-only." }
  }
}
```

### Entry types & sign conventions (enforced by domain builders)

| entry_type | gross | stripe_fee | platform_fee | tax | cogs | shipping_cost |
|---|---|---|---|---|---|---|
| `sale` | + | − (actual) | − | + (if collected) | − (if known) | — |
| `refund` | − | + (only if Stripe returns fee) | 0 (platform keeps its fee) | − (reverse collected) | + (if goods restocked) | — |
| `dispute` | − | − | 0 | − | — | — |
| `dispute_won` | + | + | 0 | + | — | — |
| `shipping_cost` | 0 | 0 | 0 | 0 | 0 | − |
| `cost_adjustment` | 0 | 0 | 0 | 0 | ± | 0 |
| `fee_adjustment` | 0 | ± | ± | 0 | 0 | 0 |
| `tax_remittance` | 0 | 0 | 0 | − | 0 | 0 |
| `adjustment` | ± | ± | ± | ± | ± | ± |

Callers use typed builders (`sale_entry(...)`, `refund_entry(...)`, …) that set the correct signs;
raw entries never carry ad-hoc signs.

### Derived metrics (pure sums — single tested domain function, never stored redundantly)

- **Net to tenant** (Stripe balance change) = Σ `gross` + Σ `stripe_fee` + Σ `platform_fee`.
- **Gross revenue** = Σ `gross`.
- **Profit** = Net to tenant + Σ `cogs` + Σ `shipping_cost` − Σ `tax` (tax is a pass-through
  liability, not profit).
- **Platform revenue** (platform book) = −Σ `platform_fee` across **all** tenants.
- **Tax liability by jurisdiction** = Σ `tax` grouped by `metadata.tax_jurisdiction` (feeds Phase 8).

## Keys & indexes

| | PK | SK | Projection | Use |
|---|---|---|---|---|
| **Table** | `TENANT#{tenant_id}` | `ENTRY#{occurred_at_iso}#{entry_id}` | — | Per-tenant timeline; **date-range** queries |
| **GSI1 OrderIndex** | `ORDER#{order_id}` | `ENTRY#{occurred_at_iso}#{entry_id}` | ALL | Every movement for one order |
| **GSI2 IdempotencyIndex** | `IDEMP#{tenant_id}#{idempotency_key}` | `ENTRY#{entry_id}` | KEYS_ONLY | Dedup before write |
| **GSI3 TypeIndex** | `TENANT#{tenant_id}#TYPE#{entry_type}` | `ENTRY#{occurred_at_iso}#{entry_id}` | ALL | "all refunds", "all disputes" |

The platform-wide book is served by **rollups** (below), not a cross-tenant GSI, to avoid a hot
partition.

## Rollups (fast dashboards)

`document_type: "ledger_rollup"`, keyed `PK TENANT#{tenant_id}` / `SK ROLLUP#{mode}#{yyyy-mm-dd}`,
holding summed components + per-type counts for that day. Maintained by a **DynamoDB Stream** on the
`LedgerTable` → rollup-updater Lambda that `ADD`s the entry's components into the day bucket (and a
`PLATFORM#{mode}#{yyyy-mm-dd}` bucket for platform revenue). Dashboards read O(days), not O(entries).
Rollups are a cache — always rebuildable by replaying entries.

## Consolidation

- **Refunds:** refund events become `refund` ledger entries. The `RefundsTable` is either dropped or
  kept as a thin projection; order refund aggregates are recomputed from ledger writes. No second
  refund source of truth.
- **Webhook idempotency:** the ledger's `idempotency_key` + GSI2 is the guard for *financial*
  dedup. `WebhookEventsTable` remains only for non-financial handler-level dedup (or is retired if
  unused after migration).
- **Order aggregates:** `amount_paid` / `amount_refunded` / `payment_status` become a derived cache
  updated from ledger writes (same transaction/stream), so the order screen stays fast while the
  ledger stays authoritative.

## Recording flows

Pure builders in `domain/ledger.py` (`sale_entry`, `refund_entry`, `dispute_entry`, …) return a
validated entry dict; a thin `LedgerRepository.append(entry)` does a **conditional put** keyed on
GSA2 idempotency (no-op if the key exists). Wiring:

- **Sale** — `checkout.session.completed`: retrieve the charge's **balance_transaction** for the
  **actual** `stripe_fee`/net (this is the PRD's fee true-up), set `platform_fee` from the known
  application fee, `cogs` from product cost if present → `sale_entry`.
- **Refund** — `charge.refunded` / refund execution: `refund_entry` (platform keeps its fee per the
  existing decision).
- **Dispute** — `charge.dispute.created` → `dispute_entry`; `charge.dispute.closed` (won) →
  `dispute_won`.
- **Shipping** — when a label is bought → `shipping_cost` entry.
- **Manual** — dashboard cost/fee adjustments → `cost_adjustment` / `fee_adjustment`.

## Prerequisites (so "profit" is real, not aspirational)

- **COGS capture:** add `unit_cost` to the Product model; without it `cogs` = 0 and reports show
  **contribution margin before COGS**, labeled as such (never a fake profit number).
- **Actual shipping cost:** captured at label purchase; absent it, `shipping_cost` = 0.
- **Line-item order model (Phase 5):** entries carry optional `line_item_id`; per-line sale entries
  unlock per-product profit. Build the ledger **on top of** the line-item model, not the current
  single-product order — otherwise it's reworked when line-items land.

## Reporting & dashboard

- Backend: `ledger_stats(tenant_id, mode, start, end)` reads rollups for the range and returns
  gross / net / fees / COGS / shipping / **profit** / tax-liability + counts.
- Dashboard: net-revenue and **profit** cards (profit hidden/labeled "before COGS" until cost data
  exists), an order-level money timeline (GSI1), and a "sales/tax by state" view (feeds Phase 8).

## Migration

Backfill from existing orders + `RefundsTable`, pulling **balance_transaction** actuals from Stripe
for historical fees/net. Dry-run first; idempotency_key makes re-runs safe. Rebuild rollups by
replaying entries.

## Testing

Pure-domain unit tests for every builder's sign convention; additivity property test (Σ components
== derived totals); idempotency (same key → one entry); reversing-entry correctness; rollup =
replay-of-entries equivalence; dispute lifecycle; refund-keeps-platform-fee.

## Sequencing (within PRD Phase 5)

1. Line-item order model + `unit_cost` on Product.
2. Actual-fee true-up (balance-transaction) — feeds `sale_entry`.
3. `LedgerEntry` schema + validator + repository + Stream rollups.
4. Wire webhook/refund/dispute/shipping recorders; derive order aggregates from the ledger.
5. `ledger_stats` + dashboard P&L; migration/backfill.

## Open questions

- Per-line vs per-order sale entries for the MVP (recommend order-level first, `line_item_id`
  reserved).
- Retire `RefundsTable`/`WebhookEventsTable` outright, or keep as thin projections during transition?
- Where COGS/shipping-cost data originates for tenants who don't enter it (leave 0 + label reports
  "before COGS").
