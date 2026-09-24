# Order fulfilment — the Orders screen, and buying labels from it

**Status: DESIGN, nothing built. 2026-09-24.**

This is the detailed design for `plans/SHIPPING_PROVIDERS.md` **P2** ("rates and label purchase from an
order"), which existed only as a six-line sketch. It also covers the Orders screen itself, which is not
purely a shipping concern — a tenant selling downloads has orders too.

Decisions taken by the author, 2026-09-24, recorded here so they are not re-litigated:

1. **One label per order.** Bulk means printing many labels at once, not combining orders into one parcel.
2. **A saved rate policy picks the rate**, with a per-row dropdown to override.
3. **Domestic US first.** Canada is already reachable (see below) and must be handled honestly, not silently.

---

## What is there today, and why it has to change

The Orders screen renders each order as a **card** in a grid. Three orders fill the viewport. The card
shows product name, a truncated `order_id`, amount, customer, date, and a Details button.

For a sales ledger that is merely inefficient. For fulfilment it is unusable, because **the card does not
contain a single fact you need in order to ship anything**: no destination, no item count, no weight, no
parcel, no rate, no way to select more than one. A tenant with twelve orders to post cannot see twelve
orders, let alone act on them.

The reference is the conventional fulfilment table (Shippo's is the example the author gave): one row per
order, a checkbox per row, a header checkbox for select-all, and the shipping facts inline so the decision
is made from the list rather than by opening twelve modals.

### What the data says about the orders that will fill this table

Measured on prod, 2026-09-24:

- **5 of 13 orders carry a `shipping_address`.** The rest are subscriptions, digital goods and services.
  So "every row is shippable" is false on day one, and the table must say why a row is not.
- **Checkout allows `US` and `CA`** (`handlers/checkout.py:728`). A Canadian order can already be taken
  today, and a Canadian label needs a customs declaration we will not have in v1. It must be refused
  clearly at the row, not at the moment money is spent.
- **0 of 4 prod products carry item dimensions.** Most rows will start un-shippable for want of a
  measurement, which makes the readiness gate the most-seen part of this feature, not an edge case.

---

## One screen, two audiences

Orders is both the **sales record** (what did I sell, what was refunded, what were the fees) and the
**work queue** (what do I have to post today). Splitting them into two screens duplicates search, filter
and permissions, and forces the tenant to learn which screen an order lives on.

**Decision: one screen, one table, columns that adapt.**

- A tenant with **no shippable catalogue and no shipping config** sees the ledger columns only. No
  checkboxes, no package column, no rate column. The shipping feature is invisible until it is relevant —
  consistent with the standing rule that the shipping module must never become compulsory by the back door.
- A tenant **with shipping configured** additionally sees the selection, package and rate columns, and the
  status filter defaults to **Needs fulfilment**, because that is the question they open the screen to
  answer. The legacy app did exactly this with its `toggle-fulfilled` filter, and it was right.

---

## The row

| column | content | empty state |
|---|---|---|
| ☐ | selection checkbox | disabled, with the reason, when the row cannot ship (see gates) |
| Order | `order_id` (elided middle, copyable) + date | — |
| Customer | name, then `city, ST postal` | — |
| Items | `2 × Creatine Gummies`, total weight, order value | — |
| Package | the box `pack()` chose, `7.5 oz · 4×4×4 in` | **+ Add package info** → deep link to the product that is missing measurements |
| Rate | carrier, service, price, transit days, with a ▾ for alternatives | **Rates unavailable** + the reason |
| | **Buy** (single) or **View order** | — |

The header checkbox selects every row that is *currently eligible*, never the ineligible ones. Selecting
all and being told afterwards that four of them failed is the behaviour to avoid.

### Three gates, and they are not the same gate

Conflating these produces the unhelpful "Rates Unavailable" with no path forward. Each has a different
owner and a different fix:

1. **Tenant gate — blocks every row.** No provider key, no ship-from address, connection untested. This is
   exactly `label_readiness()`, which already exists and is already surfaced on the Shipping screen. On
   Orders it belongs in **one banner above the table**, not repeated on forty rows.
2. **Order gate — blocks this row, and the tenant cannot fix it.** No shipping address (digital,
   subscription, service); destination outside `US`; already fulfilled; refunded. The row is not a failure,
   it simply is not a parcel. Say which, in the row.
3. **Product gate — blocks this row, and the tenant CAN fix it.** An item with no dimensions. This is
   `product_readiness()` narrowed to one order's items, and it is the only gate that deserves a call to
   action: **+ Add package info**, linking to that product's edit form. This is the author's requirement
   that a row is not checkable until its shipping information is complete.

A row failing gate 3 must name the product. "Package required" is what Shippo says and it is the weakest
part of their screen; *"Creatine Gummies has no size"* is actionable.

---

## The rate question, which is the hard one

> *"Where do tenants find the best shipping charge for the package? How to change items to overnight?"*

The answer is that **they should not hunt for it per order at all.** Hunting is what makes bulk impossible.
Instead the tenant states a preference once, the system applies it to every order, and the dropdown exists
for the exceptions.

### The rate policy (new, on the Shipping screen)

Stored on `ShippingConfig`. Four fields, all optional, with sane defaults:

- **Prefer** — `cheapest` (default) · `fastest` · `best value`. Shippo already tags rates `CHEAPEST`,
  `FASTEST` and `BESTVALUE`, and `_shippo_rate()` **already returns those in `attributes`** — this costs
  nothing to honour. We still rank ourselves from `amount` and `estimated_days` (both already returned) so
  the behaviour is identical on a provider that does not tag, and use the tags as corroboration.
- **Must arrive within N days** — narrows the candidate set before Prefer is applied. This is how a tenant
  who promised two-day delivery stops ground service being picked silently. `estimated_days` is already on
  every rate.
- **Preferred carrier, within a tolerance** — "USPS, if within $2 of the cheapest". Tenants consolidate on
  one carrier for pickup and drop-off reasons that have nothing to do with price.
- **Never auto-select above $X** — the row still shows the rate, but selection is withheld and the row
  says *"$41.20 — above your $25 limit, choose a rate"*. A guardrail on a flow whose whole point is that
  one click spends money on twenty parcels.

The row then shows **one** rate with its justification — *"cheapest of 7"* — not a menu. That single line
is what makes select-all → Buy honest rather than reckless.

### Changing one order to overnight

The ▾ on the row opens every rate for that parcel, sorted by the policy, each with price and transit days
and its carrier tags. Pick one; it overrides the policy **for that row only** and the row marks itself
*overridden* so a later bulk action does not quietly revert it.

### Changing many orders at once

With rows selected, an **Apply service** control offers the service levels **common to every selected
row** — and says so, because "Priority Overnight" that exists for eleven of twelve selections is a trap.
Rows without that service keep their policy rate and are listed before the purchase is confirmed.

### Why not simply "cheapest", like the legacy app

The legacy `createShippingLabel()` did `rates.reduce(...)` for the minimum and opened a modal. It was
correct for one order at a time and cannot survive twenty: it offers no way to express a delivery promise,
no way to prefer a carrier, and no ceiling. The policy is the smallest thing that makes bulk safe.

---

## Buying

### Rates are fetched late, not on page load

Every rate lookup is a Shippo *shipment* creation — a network call per order, rate-limited and slow.
Rating forty rows to render a table nobody has acted on is wasteful and makes the screen feel broken.

- Rate a row when it is **selected** or **expanded**, not when the page renders.
- Cache the result on the shipment document with a fetched-at timestamp, and treat it as **display only**.
- **Re-rate immediately before purchase, always.** A cached rate id can be stale or expired, and a price
  shown ten minutes ago is not a price. If the re-rate differs from what was displayed by more than a
  trivial amount, stop and show the difference rather than spending the new amount.

### Buying twenty labels is a job, not a request

Twenty purchases cannot happen inside one API Gateway request: it will time out, and a timeout mid-batch
leaves the tenant not knowing which labels were bought — the worst possible failure for an action that
spends money.

- `POST /shipping/labels` takes **one order**, is **idempotent on `order_id`**, and is the only thing that
  ever buys. An order that already has a purchased label returns that label rather than buying a second.
- Bulk is the **client driving that endpoint with limited concurrency**, showing per-row progress, and
  continuing past failures. Row-level outcome, not batch-level.
- The confirm step states the **total about to be spent** and the count: *"Buy 5 labels — $19.35"*.
- Idempotency is what makes a retry safe, and a bulk flow will be retried.

### What must be said at the moment of purchase

`plans/SHIPPING_PROVIDERS.md` §PA established these and they are requirements, not caveats:

- The quote is what the carrier quoted, **and a carrier that re-measures the parcel bills the difference
  later**. Say it where the money is spent.
- Flag any parcel whose dimensions were **defaulted rather than entered** — the packer knows which. It is
  the single biggest cause of an adjustment.

### After a successful purchase

Persist to the shipment: carrier, service, tracking number and URL, label URL, cost, provider transaction
id. Then, if `auto_fulfill_after_label_purchase` is set (already in the schema), mark the order fulfilled
and send the buyer the shipping notification. The label PDF opens for printing.

---

## Manual fulfilment stays

The legacy **Mark as Fulfilled** button — which emailed the customer and set `fulfilled` — must survive
alongside Buy label. A tenant who walks parcels to the post office is a first-class tenant; that is the
standing rule, and removing the manual path would break it. **Mark as shipped** takes an optional tracking
number and carrier, so a tenant who bought postage elsewhere still gives the buyer tracking.

---

## What has to change under the surface

- **`order.line_items` carries `stripe_product_id`, not our `product_id`** — and `packable_items()` keys on
  `product_id`. So an order cannot be packed today without a resolver from Stripe ids to catalogue
  products. `catalog_names_by_stripe_id()` (added 2026-09-24 in the webhook) already builds exactly this
  index for receipts; generalise it rather than writing a second one.
- **A test-mode order in prod reads `jb-products-prod`, where its test products do not live.** The same
  split that stops a renewal receipt resolving a product name will stop a parcel being packed. It does not
  block live tenants, and it will make sandbox testing of this flow misleading unless it is understood.
  Belongs to `plans/STRIPE_MODE_DECOUPLING.md`; named here so it is not mistaken for a bug in this feature.
- **`GET /orders` must return fulfilment state** — shipment, readiness per order, destination — or the
  table needs one request per row. Compute readiness server-side, as the Shipping screen already does, so
  there is one implementation and the screen cannot disagree with the buy endpoint about whether a row is
  eligible.
- `OrdersFunction` will need read grants on ProductsTable, ShippingConfigTable and ShipmentsTable.
  `test_table_grants` will catch these; expect it to.

---

## Phases

- **F1 — the table.** Replace the cards. Ledger columns, sorting, the status filter, Details preserved. No
  shipping anything. Immediately better for every tenant, and independently shippable.
- **F2 — the gates.** Per-order readiness from the server, selection checkboxes, the three gate messages,
  **+ Add package info** deep links, the tenant banner. Still buys nothing. At the end of F2 the tenant can
  see exactly what stands between them and a label, which is most of the value.
- **F3 — rates.** The rate policy on the Shipping screen, rate-on-select, the row's chosen rate with its
  justification, the ▾ override. Still buys nothing — `MockProvider` walks the whole flow.
- **F4 — buying.** `POST /shipping/labels`, idempotent, one order. Client-driven bulk with per-row
  progress. Spend confirmation, the adjustment disclosure, auto-fulfil, the label PDF.

Voiding, refunds and adjustment reconciliation stay where §PA put them — after F4, as their own slice.

## Deliberately not in this plan

- **Consolidating several orders into one parcel** (decided against for now). Worth revisiting once the
  1:1 flow is real; it changes Shipment→Order to many-to-many and splits tracking across orders.
- **International labels and customs.** Canada is reachable from checkout today, so until F4 supports it
  the row must say *"International labels not supported yet — mark as shipped manually"* rather than
  failing at purchase.
- **Charging the buyer for shipping.** Shipping is free on every order today; the tenant absorbs postage.
  Quoting a rate at *checkout* time is a different problem with a different latency budget, and it is
  already scoped as §PE "Calculate Price".
- **Pickup scheduling, SCAN forms, multi-parcel orders.** Each is real and none belongs in v1.

## Open, and worth deciding before F3

- **Where does the rate policy live** — one policy per tenant, or per shipping config profile? One per
  tenant is assumed above.
- **Does an offer's delivery promise feed the policy?** If a tenant sells "2-day shipping" as part of an
  offer, the order should carry that promise and the policy should honour it per order rather than
  tenant-wide. Needs the promise to exist on the offer first.
- **Partial fulfilment.** An order with two items where one is in stock. The schema assumes one shipment
  per order; multi-parcel is listed above as out of scope, but partial *fulfilment* may arrive sooner.
