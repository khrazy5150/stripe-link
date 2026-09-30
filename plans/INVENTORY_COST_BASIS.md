# Inventory Cost Basis — what did the tenant actually pay for these units?

**Status: planned, nothing built · Written 2026-09-30.**

## Why this exists

The author, 2026-09-30: *"a lightweight inventory/cost-basis module is justified, but I would not build a
full inventory-management system yet."* And the reason it is justified:

> *"what did this tenant actually pay to acquire the units they're selling?"*

    100 units
    Product purchase:       $800
    Inbound freight:        $150
    Duties/other costs:      $50
    ────────────────────────────
    Total acquisition cost: $1,000
    Cost per unit:            $10

Smart Pricing can then reason from a real unit cost instead of asking the tenant to type `$10`.

**There is nothing to migrate.** stripe-link has no inventory concept at all — the only match for "stock" in
the repo is the SKU field's description. stripe-cart has an `inventory` key on the offer
(`api_offers.py:523,606`) that is written, defaulted on update, and **never read by anything**. So this is
not a port: the behavioural reference has no behaviour to preserve.

## What already exists, and the seam that follows from it

`plans/SMART_PRICING.md` §2 already models acquisition costs as per-unit cost lines:

    { "label": "Source cost",     "kind": "fixed",       "amount": 1000 }
    { "label": "Inbound freight", "kind": "fixed",       "amount": 150  }
    { "label": "Import duties",   "kind": "pct_of_cost", "rate": 0.075  }

**So the gap is not the vocabulary — it is that the tenant divides by hand.** They know they paid $800 for
100 units and they type `800`. That reframes the seam, and narrows it usefully: a lot does not introduce a
cost model, it **derives lines Smart Pricing already understands**.

    lot.product_cost     / units_received  ->  "Source cost"        (fixed)
    lot.inbound_shipping / units_received  ->  "Inbound freight"    (fixed)
    lot.other_cost       / units_received  ->  "Acquisition costs"  (fixed)

**One place this makes Smart Pricing more accurate rather than merely easier.** Duties are modelled as
`pct_of_cost` because customs levies on landed cost, and a rate is the only thing a tenant can state in
advance. A lot records what the broker actually invoiced. An actual beats an estimate, so where a lot exists
its duties become a `fixed` amount and the `pct_of_cost` rate is no longer guessed at for that batch.

**Staleness is already solved — do not build it twice.** SMART_PRICING §6 says a price is a *snapshot* of a
cost profile, recomputed on read, compared, and notified with the consequence rather than the event
(*"Your costs rose 8%. At today's price your markup is 4%, not 12%"*). A new lot at a higher unit cost is
exactly that event. Inventory gets the notification for free and must not grow its own.

## The primitive

Deliberately a cost-basis record, not a warehouse. Four questions and no more: how many units did I acquire,
what did the batch cost, what is my cost per unit, how many remain.

```jsonc
// InventoryLot
{
  "lot_id": "lot_7f3a",
  "product_id": "prod_abc",
  "units_received": 100,
  "units_remaining": 100,
  "product_cost": 80000,        // integer cents, the whole batch
  "inbound_shipping": 15000,
  "other_cost": 5000,           // duties, prep, labelling, brokerage
  "currency": "usd",
  "received_at": 1759190400,
  "reference": "PO-1042",       // free text: invoice no., supplier, container
  "note": ""
}
```

Per the author, the three cost components stay separate and the total is computed:

    total_acquisition_cost = product_cost + inbound_shipping + other_cost

### `total_cost` and `unit_cost` are DERIVED, never stored

The author's sketch lists both as fields. They should be read-model values computed on read, because
`unit_cost = total / units` usually does not divide evenly — $1,000 over 3 units is $333.33…, and a stored
rounded unit cost multiplied back by the unit count no longer equals the total. Two stored numbers that
disagree is a reconciliation bug with no correct answer. Store the three components and the two counts; round
only at the point of use.

This repo also has a specific reason to avoid a stored `unit_cost`: money read back from DynamoDB arrives as
`Decimal`, and `isinstance(x, (int, float))` is **False** for it. That footgun has already 404'd published
pages once (`feedback_decimal_from_dynamo`). Fewer stored money fields, fewer places to trip.

## The one decision the sketch leaves open: which lot?

> *"when an order sells 3 units, you can decrement the lot"* — **which lot?**

With two open lots at different unit costs, "decrement the lot" has no answer until a selection rule exists,
and a sale can span lots (3 units: 2 from lot A at $10, 1 from lot B at $11). This cannot be deferred — the
first tenant to reorder stock at a new price creates the situation.

**It is not the excluded item.** "FIFO/LIFO accounting" means offering the choice as a configurable method
with the reporting to match. Having *one* deterministic consumption order is a sort and a loop.

**DECIDED: oldest open lot first, by `received_at`. Not configurable.** It is what physically happens with
anything perishable or warrantied, it is the conservative answer for tax in most jurisdictions, and one
non-negotiable rule is a tenth of the work of two optional ones.

The lot's document key makes this nearly free. Following the repo's `(tenant_id, document_id)` repository
shape:

    document_id = f"{product_id}#{received_at:010d}#{lot_id}"

`begins_with(product_id)` lists a product's lots, and **the sort-key order IS the FIFO order** — oldest open
lot is a query, not a scan-and-sort, and no GSI is needed.

### Which forces the second decision: stamp the basis on the order line

Orders carry `items: [{product_id, price_id, quantity}]`. Add the resolved cost basis at sale time:

```jsonc
{ "product_id": "prod_abc", "quantity": 3, "cost_basis": 3100,
  "cost_basis_lots": [{"lot_id": "lot_7f3a", "units": 2, "unit_cost": 1000},
                      {"lot_id": "lot_91c2", "units": 1, "unit_cost": 1100}] }
```

Two reasons it must be stamped and not looked up later:

1. **Late invoices are normal.** A duty or brokerage bill arrives weeks after the container, and the tenant
   edits the lot. If margin is computed by reading the lot at report time, that edit **retroactively rewrites
   the margin of orders that already happened**. Stamping freezes history where it belongs.
2. **A lot reference cannot express a split.** `cost_basis` is one number covering units drawn from two lots
   at two prices; no single `lot_id` says that.

## V1 records, it does not enforce

**No oversell blocking.** Enforcement means a conditional decrement in the checkout path, a race between
session creation and payment, an oversell policy, and a buyer refused at the pay button. That is inventory
management, which is the thing being deliberately not built.

**`units_remaining` may go negative, and is not clamped.** Negative means "you sold more than you recorded
receiving" — true, and actionable: go and enter the receipt you missed. Clamping at zero would replace a
useful signal with a comfortable lie. Per `feedback_notices_only_when_actionable`, negative remaining earns a
notice; zero does not.

Decrementing reuses the atomic `ADD` + `ConditionExpression` pattern already in
`repositories/documents.py` (`consume_if_available`), rather than a read-modify-write.

## No lots means cost is UNKNOWN, not zero

Most of the catalogue — digital goods, services, subscriptions — will never have a lot. A product with no
lots has **no cost basis**, and Smart Pricing must go on asking the tenant rather than inferring $0. A zero
cost basis is a claim that the goods were free, and it would silently report infinite margin.

This is the same rule the shipping plan reached for `shipping_cost`: *nullable is honest, zero is not.*

## Three numbers called "shipping", three different names

The author's framing, and it should be written into the schemas as a naming rule:

| field | lives on | meaning |
|---|---|---|
| `inbound_shipping` | InventoryLot | cost of **acquiring** inventory |
| `shipping_cost` | Order | what the carrier charged to **fulfil** this order |
| `shipping_amount` | Order | what the **buyer paid** for shipping |

Inbound has no double-count risk — it is always a cost and is never charged to a buyer — so the
SHIPPING_CHARGES invariant does not extend to it. Outbound is the one that needs the invariant.

## The full economic model this completes

    ACQUISITION                          SALE
    product_cost                         cost_basis          (stamped from lots)
    + inbound_shipping                   + shipping_cost     (outbound, carrier)
    + other_cost                         + platform fees     (fees.py)
    ────────────────────                 + payment fees      (Stripe)
    total_acquisition_cost               - shipping_amount   (buyer-paid, revenue)
    ÷ units_received                     ────────────────────
    = unit_cost                          = actual contribution margin

Contribution margin is the first number in this system that is **measured rather than projected**. Smart
Pricing predicts it; this is what actually happened, and the difference between the two is the most useful
report the platform could show a tenant.

## Explicitly NOT in V1

Per the author: warehouse locations, bin management, purchase orders, supplier management, SKU receiving
workflows, barcode scanning, inventory transfers, FIFO/LIFO as a configurable accounting method,
multi-warehouse fulfilment, automatic carrier reconciliation. *"Those turn this into Shopify/ERP territory
very quickly."*

## Phases

1. **`domain/inventory_lots.py`** — pure: total, unit cost, and `consume(units, lots)` returning the FIFO
   allocation. No I/O, fully testable, and the only place the arithmetic lives.
2. **`InventoryLotsTable` + repository factory** — table-per-entity, matching `PRODUCTS_TABLE`/`OFFERS_TABLE`.
   Composite `document_id` as above. IAM grants on the functions that read it (the grant test follows domain
   imports, so a `domain/inventory_lots` import from a handler must come with the policy).
3. **Lot entry UI** on the product — three cost inputs, unit count, date, reference; total and unit cost shown
   live and read-only so the tenant sees the division they no longer have to do.
4. **Smart Pricing consumes it** — derived `fixed` lines, tenant-overridable, with §6 staleness doing the
   notifying. This is the step that pays for the module.
5. **`cost_basis` stamped on order items at sale**, with the FIFO allocation and the decrement.
6. **Contribution-margin reporting** — measured vs projected.

Steps 1–3 are useful alone: a tenant who only ever enters lots and reads the unit cost has already stopped
guessing. Step 4 is where it stops being data entry.

## Open

- **Returns and restocking** connect to `plans/REFUND_POLICY.md`. Its `return_method` vocabulary already
  distinguishes *customer keeps* from *must return*, which is exactly the fact that decides whether a
  refunded unit goes back to its lot. It cannot be answered yet, because "must return" also requires knowing
  the return was **received**, and that fulfilment event does not exist. **V1: refunds do not restock.** The
  hook belongs here when receiving exists.
- **Multi-currency acquisition.** An importing tenant pays a supplier in CNY and duties in USD. SMART_PRICING
  §Open already carries this ("convert at entry, store the rate"); a lot is where the rate would be stored,
  since it is a fact about one purchase on one date. V1: single currency, the tenant's.
- **Variants.** Lots key on `product_id`. If variants ever get their own cost — different sizes genuinely
  land at different costs — the key needs a variant segment. The composite `document_id` can absorb one
  without a migration of the table itself.
- **Resource ceiling.** Measured 2026-09-30: dev is at **443 of 500** CloudFormation resources. One table
  fits comfortably; the note is that several planned features each want one, and the ceiling is shared.

## The principle, carried forward

`plans/REFUND_POLICY.md` and `plans/SHIPPING_CHARGES.md` exist because *customer-facing commercial promises
should never be implicit*. This plan is the same rule turned inward: **a tenant's own economics should never
be implicit either.** A hand-typed `$10` unit cost is a number with no provenance — nobody can say later
which invoice it came from or whether it is still true. A lot is the receipt.

Together: **Inventory → Pricing → Shipping → Order → Fees → Refunds** — the author, 2026-09-30:
*"That's a much stronger architecture than adding isolated features one at a time."*
