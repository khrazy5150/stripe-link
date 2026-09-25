# Order fulfilment — the Orders screen, and buying labels from it

**Status: BUILT 2026-09-24 — F1–F4 and R1–R3 all shipped to dev. See "What shipped" at the end.**

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

## The manual path is a first-class path, not a fallback

A tenant who walks parcels to the post office is a first-class tenant — the standing rule — so **Mark as
shipped** is not a degraded Buy label. It is the whole flow for tenants who will never connect a provider,
and it must produce the same outcome for the buyer: an email, at that moment, with a working tracking link.

### What the tenant does

Clicking **Mark as shipped** opens a small form, not a confirm dialog, because there are facts to capture:

- **Carrier** — required when a tracking number is given, because it is what turns a number into a link.
- **Service** — optional free-ish text with the carrier's common services offered (USPS Ground Advantage,
  Priority Mail, UPS Ground…). It does not change the URL; it changes what the buyer is TOLD, and it is
  what records that a parcel went First-Class rather than Priority.
- **Tracking number** — **optional**, and this is the important part (see below).
- **Ship date** — defaults to today.

On save: the shipment records the carrier, service, number and a derived `tracking_url`; the order is
marked fulfilled; the buyer is emailed.

### Not every parcel has a tracking number, and the form must not pretend otherwise

This is the trap in "enter the tracking number so it can be emailed". **USPS First-Class Mail** — letters,
flats, postcards — carries **no tracking at all** unless extra services were bought. USPS *parcel* service
(First-Class Package Service, renamed **Ground Advantage** in 2023, though tenants still say "first class")
does include it. A tenant who posted a padded envelope at letter rate has no number to type, and a form
that demands one leaves them unable to mark their own order shipped.

So:

- The tracking number is **optional**. Marking shipped without one is a legitimate, complete action.
- When the chosen service is one we know carries no tracking, say so **in the form** — *"USPS First-Class
  Mail does not include tracking. Leave the number blank; the buyer will be told it is on its way."*
- The email adapts rather than degrading: with a number it carries the link; without one it says the parcel
  is on its way and, when the service simply has no tracking, says that plainly. It must never promise a
  link that will never arrive — an email that says "track your parcel" with nothing to track generates
  exactly the support message the email was meant to prevent.

This is the standing rule about notices — a notice needs an action, and "wait for a tracking number that
does not exist" is not one.

### Turning a number into a link

When a **provider** sells the label it hands us the URL: Shippo returns `tracking_url_provider`, and the
legacy adapter read it from every provider it supported. Only the direct-USPS path ever built a URL by
hand. So the carrier→URL table is needed **for the manual path and nowhere else**, which keeps it small:

| carrier | pattern |
|---|---|
| USPS | `https://tools.usps.com/go/TrackConfirmAction?tLabels={n}` |
| UPS | `https://www.ups.com/track?tracknum={n}` |
| FedEx | `https://www.fedex.com/fedextrack/?trknbr={n}` |
| DHL Express | `https://www.dhl.com/en/express/tracking.html?AWB={n}` |

Note that USPS uses **one URL for every service** — First-Class, Priority and Ground Advantage all track at
the same place. The service is recorded for the buyer's benefit and for the tenant's own records, not
because it changes the link.

Three requirements on that table:

1. **It is data, not code.** Carrier tracking URLs change; a tenant must not wait for a deploy when one
   does. Seed it in the repo, let it be overridden without a release, the same way the fee table already is.
2. **"Other carrier" takes a pasted URL.** Regional carriers, freight, a courier, a friend with a van. The
   tenant pastes the tracking link and the email uses it verbatim. This is what stops the feature being
   permanently incomplete for want of an entry in a table.
3. **Offer carrier auto-detect, never rely on it.** `1Z…` is UPS, 20–22 digits is USPS, 12 or 15 digits is
   FedEx. Prefill the carrier from the number and let the tenant correct it. A prefill that is usually
   right saves a click; a detection that is silently wrong sends the buyer to the wrong carrier's website.

### The email, and how it differs from the label-purchase path

Same builder, same mailer, same branding as §P3 in `plans/SHIPPING_PROVIDERS.md` — `shipment_tracking_content`
in `domain/receipts.py`, from the tenant's business name with their support address as reply-to. One
implementation for both paths; the only difference is where the facts came from.

**But the failure behaviour must differ, and this is easy to get wrong.** §P3 says a tracking email must
never break what triggered it, because on the purchase path a label is already bought and paid for by the
time we send. On the **manual** path nothing irreversible has happened, and the tenant clicked the button
*in order to* notify the buyer. Swallowing an SES failure there means the tenant believes their customer
was told, and the customer hears nothing.

- **Purchase path:** send best-effort, never fail the purchase. Unchanged.
- **Manual path:** the mark-as-shipped still succeeds (the parcel did ship; that fact is not contingent on
  email), but the tenant is **told** the notification failed and offered **Resend**. Record `notified_at`
  so the row can show "buyer notified 14:32" versus "not notified".

### Correcting a mistake

Tracking numbers get typed wrong. Editing one on an already-shipped order must be possible, and doing so
offers to re-notify rather than silently emailing again — a buyer who receives two tracking emails with
different numbers is worse off than one who receives a correction they were told about.

An order already fulfilled by a purchased label does not offer Mark as shipped; it has a tracking number
already, and a second notification would contradict the first.

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

## Returns — the reverse leg, and why the refund waits

**The rule (author, 2026-09-24): if a product requires a physical return, no Stripe refund is issued until
the product is received.**

### Most of this is already built — do not rebuild it

- `RefundRequest` exists with states `new · manual_review · approved · rejected · refunded · closed`, and
  already carries `policy_snapshot`, `risk_level`, `handling` and `decision_reason`.
- `handlers/refunds.py` already approves, rejects and executes the Stripe refund.
- A refund request already raises a tenant notification (`refund_request`, severity warning, deep-linked).
- The buyer already has a link-based route — `/purchase/manage`, reached from the page footer beside the
  refund policy — and there are deliberately **no buyer accounts**, so the return flow is an opaque-token
  link like abandoned-cart recovery and tip cancellation. Do not invent a login for this.
- `refund_policy` already exists on offer and product, already states a return window in days, and already
  feeds `hasMerchantReturnPolicy` in the Product JSON-LD.

**What is missing is the leg between `approved` and `refunded`.** Today approval leads straight to money
going back. The return inserts itself there, and nothing before or after it needs redesigning.

### The states

```
new ─► manual_review ─► approved ──────────────────────────────► refunded
                            │                                       ▲
                            │  return required                      │
                            ▼                                       │
                    return_pending ─► return_in_transit ─► return_received
                            │                                       │
                            │ expired / never shipped               │ inspection fails
                            ▼                                       ▼
                          closed                          rejected · partial refund
```

`approved` keeps its current meaning — *the claim is valid* — and stops implying *the money is going back
now*. That separation is the whole change.

### The cost of this rule, which must be stated plainly

Holding a refund pending receipt is the right default for physical goods and it is **not free**. Three
clocks start when a buyer asks for their money back, and the rule makes all three tighter:

1. **The dispute clock.** A buyer who waits three weeks for a refund files a chargeback. The tenant then
   loses the dispute fee *and* may lose the goods. Withholding a refund does not remove risk, it **trades
   refund risk for dispute risk** — and a dispute costs more than the refund would have. This is the real
   argument for the keep-it threshold below, and for telling the buyer clearly what is happening and when.
2. **The refund window.** A refund cannot be issued indefinitely. Card refunds have a practical limit, and
   **BNPL methods have their own, and shorter** — Klarna, Afterpay, Affirm and Zip are all live on prod
   since 2026-07-31, so this is not hypothetical. **Verify the current window per payment method against
   Stripe's documentation before building**, and record the deadline on the request so a return that
   cannot be refunded is caught while there is still time to act rather than at the moment it fails.
3. **The buyer's patience.** Which is what the emails are for.

The return therefore has an **expiry**: a label issued and never used closes the request after N days
(policy, default 14 or the return window, whichever is shorter) with an email before it happens, not after.

### Who decides a return is required

Not a global setting. **Per product**, on the same `refund_policy` that already exists:

- `return_required` — the goods must come back before money goes out. Meaningless for digital and service
  products; the flag must be unavailable there rather than ignored, so a tenant cannot set a trap for
  themselves.
- `returnable` — some things cannot come back at all (perishable, hygiene, custom-made). A non-returnable
  item refunds without a return or is refused outright, per the tenant's policy; it must never sit in
  `return_pending` waiting for a parcel that is not allowed to be sent.
- `keep_it_below` — **when return postage exceeds what the item is worth, asking for it back loses money.**
  Below this value, approve and refund without a return. Standard industry practice, and the cheapest
  defence against the dispute clock above.

**All three are snapshotted into `policy_snapshot` at request time** — the field already exists for exactly
this reason. A tenant editing their policy must not retroactively change the terms of a return already in
flight; the buyer agreed to the policy as it was.

### The return label

Reverse of F4 and built on the same primitive: same `pack()`, same rates, same purchase — with `from` and
`to` swapped. What differs:

- **A return label is usually pay-on-scan.** Carriers commonly charge only when the label is actually
  used, which is what makes issuing one cheap and makes the expiry above safe. **Verify this with Shippo
  per carrier before relying on it** — if a carrier charges at creation, issuing labels for returns that
  never ship is a slow leak.
- **Who pays** is policy: tenant absorbs, or it is deducted from the refund. Whichever it is, the buyer
  must be told **before** they accept the label, not discovered in the refunded amount.
- **A manual path is required here too**, for the same reason as everywhere else: a tenant with no provider
  gives the buyer an address and an RMA number, and marks the parcel received by hand. The refund gate is
  the feature; the label is a convenience on top of it.

### Received is a decision, not an event

`return_received` must be a deliberate act by the tenant, not a carrier scan. A delivery scan says a box
arrived; it does not say the right item was in it, or what condition it was in.

- A tracking scan **advances the request to `return_in_transit`** and notifies the tenant, so they are not
  refreshing a screen.
- **Marking received is the tenant's** — and it is where the refund amount can still change. An item back
  damaged, used, or not the item sent is a partial refund or a rejection. So the amount is **decided at
  receipt, not fixed at approval**, and the reason is recorded on the request, because this is the step a
  buyer is most likely to dispute.
- Restocking fees and non-refundable outbound shipping both land here, and both must appear in the buyer's
  email as line items rather than as an unexplained shortfall.

### What the buyer sees

Through `/purchase/manage`, using the existing token link. Each transition emails them, because a return is
the part of commerce where silence is most expensive:

- **Approved, return required** — what to send back, by when, the label or the address, who pays postage,
  and what they will get back.
- **We have it** — received, and the refund is on its way.
- **Refunded** — the amount, and every deduction itemised.
- **Expiring** — before the window closes, not after.

## Phases

- **F1 — the table.** Replace the cards. Ledger columns, sorting, the status filter, Details preserved. No
  shipping anything. Immediately better for every tenant, and independently shippable.
- **F2 — the gates, and manual fulfilment.** Per-order readiness from the server, selection checkboxes,
  the three gate messages, **+ Add package info** deep links, the tenant banner. **Plus the whole manual
  path**: Mark as shipped, the carrier table, the tracking email, resend and correction. Still buys
  nothing, and connects to no provider — so at the end of F2 a tenant who never touches Shippo has a
  complete, working fulfilment flow, and every other tenant can see exactly what stands between them and a
  label. This is the phase with the most value per unit of work, and it is why manual comes before rates
  rather than after buying.
- **F3 — rates.** The rate policy on the Shipping screen, rate-on-select, the row's chosen rate with its
  justification, the ▾ override. Still buys nothing — `MockProvider` walks the whole flow.
- **F4 — buying.** `POST /shipping/labels`, idempotent, one order. Client-driven bulk with per-row
  progress. Spend confirmation, the adjustment disclosure, auto-fulfil, the label PDF.
- **R1 — the refund gate.** `return_required`, `returnable` and `keep_it_below` on the refund policy,
  snapshotted at request time; the new states; the tenant marking received; the refund released only then.
  **No labels** — the manual path (address + RMA) proves the whole gate, and it is the part that protects
  the tenant's money.
- **R2 — return labels.** Reverse of F4 on the same primitive. Who-pays policy, buyer acceptance, expiry.
- **R3 — return tracking.** Scans advance `return_in_transit` and notify; folds into §P3's tracking work
  rather than duplicating it.

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
- **Does the carrier table ship seeded or empty?** Seeded with the four above is assumed. The list of USPS
  service names in particular should be **verified against current USPS products** before it is seeded —
  First-Class Package Service became Ground Advantage in 2023 and the retail names have moved more than
  once. Getting a URL wrong is recoverable; getting the "this service has no tracking" advice wrong tells a
  tenant to leave out a number they actually had.
- **The refund window per payment method.** Named as a risk above and unverified. It decides whether a
  return can safely be held at all for a BNPL order, and the answer may be that some methods must refund on
  approval regardless of the return. **Verify before R1.**
- **Does a return label get bought on issue, or on scan?** The expiry design assumes pay-on-scan. If a
  carrier charges at creation, R2 needs a different default (issue on request, not on approval).
- **Who arbitrates a disputed inspection?** The tenant decides what a returned item is worth, and the buyer
  has only the chargeback to disagree with. Whether the platform takes any position on this is a policy
  question, not an engineering one, and it should be answered before R1 ships rather than after the first
  complaint.
- **Should a manual shipment be trackable by us?** A tenant-entered USPS number could be registered with
  the provider's tracking API to drive delivery notifications (§P3), even though we did not sell the label.
  It would unify the two paths for the buyer. It also costs a provider call per parcel and may require an
  account we cannot assume — decide when §P3 is built, not now.


---

## What shipped, 2026-09-24

All seven phases, deployed to dev. Not yet in production.

| phase | what landed |
|---|---|
| **F1** | The table. `orderDisplay.js` holds the pure display helpers so the table and the details modal cannot describe an order two different ways. |
| **F2** | The three gates computed server-side and carried on every order; selection that takes only eligible rows; **the whole manual path** — Mark as shipped, the carrier table, the buyer's email, the optional tracking number. New `ShipmentsTable`: the schema existed, nothing had ever persisted one. |
| **F3** | The rate policy on `rate_options`, `POST /shipping/rates`, one rate per row with its justification, the override dropdown. |
| **F4** | `POST /shipping/labels` — idempotent, claim-before-spend, client-driven bulk with per-row progress, the spend confirmation and the adjustment disclosure. `buy_label` added to the provider contract and to `MockProvider`. |
| **R1** | The refund gate. `return_pending` / `return_in_transit` / `return_received`, snapshotted terms, `keep_it_below`, and `POST /refunds/{id}/received`. |
| **R2** | Return labels: reverse addresses, separate shipment id, the three-day window, forfeit enforced at issue. |
| **R3** | What a carrier scan means — `advance_to_in_transit`. The webhook that delivers the scan belongs to §P3 and is not built. |

### What the build changed about the design

- **The resolver was as central as predicted.** `product_index` / `resolve_order_lines` turned out to be
  needed by the gates, the rate quote, the packer AND the refund policy read. An unresolvable line is kept
  rather than dropped, or the parcel silently shrinks.
- **`notify_buyer` is shared, its failure handling is not.** One builder and one mailer for both paths, but
  the label path swallows a send failure (the label is already paid for) and the manual path reports it
  (the tenant pressed the button in order to notify). That split is the whole reason it took a comment.
- **The grants test earned its keep three times** and was itself too weak: it detected tables by env-var
  NAME, and `handlers/refunds.py` reaches products only through `products_repository()`. The missing grant
  would have failed *silently*, skipping the return gate on every refund. It now follows repository
  factories too, but only for single-entry-point modules — in a module serving several functions, a
  factory call says nothing about which one reaches it. It then immediately caught that refund requests
  live in the **Notifications** table, so a grant on "RefundRequestsTable" was a `!Ref` to a resource that
  does not exist — something `sam validate` accepts and CloudFormation would not.
- **`provider` is an object, not a string.** `Shipment.schema.json` always said so; the adapter returned a
  flat string. Corrected in both directions, and `manual` joined the provider enum — an honest answer to
  who provided the label: the tenant, at the post office.

### Still not built, deliberately

- **The tracking webhook** that would drive `advance_to_in_transit` automatically (§P3).
- **A sweep that closes lapsed returns.** The forfeit is enforced where the label is issued, because a
  lapsed window costs the buyer free postage — it does not by itself decide their refund, which stays the
  tenant's call.
- **Multi-parcel orders**, refused explicitly at rate time rather than quoting one box and shipping three.
- **International labels.** A non-US order is refused in the row, before money is spent.
- **Consolidating several orders into one parcel**, and **charging the buyer for shipping** (§PE).

### Verify before production

- **The per-payment-method refund window.** Unchanged from R1's warning and still the biggest open risk:
  BNPL windows are shorter than a card's, and some methods may have to refund on approval regardless of
  the return.
- **Whether return labels are pay-on-scan** for each carrier in use. The three-day window is safe if they
  are and punitive if they are not.
- **The seeded USPS service names**, particularly which carry no tracking.
