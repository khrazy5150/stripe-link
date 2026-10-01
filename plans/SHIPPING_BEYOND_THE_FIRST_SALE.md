# Shipping beyond the first sale

**Status:** planned, 2026-10-01. Follows `plans/LIVE_SHIPPING_RATES.md` (built). Makes
`plans/SMART_PRICING.md` load-bearing rather than optional, and resolves one of its open questions.

Live carrier rates fixed the *first* sale: a buyer enters a postcode, sees real prices, and is charged
what they chose. Every **additional** sale opportunity still ships for nothing — order bumps, post-purchase
upsells and downsells — and a free-shipping threshold has no funding mechanism behind it.

The author, 2026-10-01:

> *"Most e-commerce platforms reward customers who order more with 'free shipping', which seems ironic
> because the more items they ship, the greater the shipping charge. This could only be possible IF
> shipping charges are already built into the product's price."*

That is exactly right, and it is why this plan ends at Smart Pricing rather than beginning there.

---

## 1. Three shapes, not one problem

| Where | Mechanism | Shipping today | Constrained? |
| --- | --- | --- | --- |
| **Order bump** | Stripe `optional_items` on the same Session | not charged | **yes** — see §2 |
| **Post-purchase upsell / downsell** | a PaymentIntent *we* build | not charged | **no** |
| **Free above a threshold** | `offer.shipping.free_above_amount` | frees the baseline option | no — needs funding |

Lumping them together is what makes the problem look unsolvable. Two of the three are not.

## 2. The asymmetry that decides the design

**An order bump is genuinely constrained.** `optional_items` are chosen on Stripe's hosted page *after*
`shipping_options` was fixed at session creation. Hosted Checkout offers no way to reprice shipping when a
bump is taken, and the dynamic-shipping flow that would (`permissions.update_shipping_details`) requires
`ui_mode=elements` and disables Apple Pay and Google Pay — a trade already rejected in
`plans/LIVE_SHIPPING_RATES.md §5`.

**An upsell is not constrained at all.** `handlers/upsell.py` builds a **PaymentIntent** (`amount=subtotal`),
not a Checkout Session. No fixed `shipping_options`, no session to reopen. The destination is already known
— `upsell_destination` reads it off the original order — and the packer and rater are already built and
deployed. Nothing stops us quoting the upsell's parcel and adding it to the amount. This was assumed
impossible by analogy with bumps; it is not.

## 3. The exposure, measured

Run against the author's own dev data, offer `Ux5fEyATDzE` ("Workout Bundle", with the Protein Shaker
Bottle as a checkout-stage bump):

```
QUOTED parcel     3 parcels    Creatine Gummies + NAD Supplement + Whey Protein
IF BUMP TAKEN     4 parcels
```

**A whole extra parcel**, not a weight delta — roughly a full shipping charge, unbilled. The prior
assumption that a bump is marginally near-free does not survive contact with real data.

**But the cause is upstream.** None of those products carry dimensions, so `shipping_packing`'s per-item
fallback assigns one parcel per item. With real sizes those four items very likely consolidate into one
box and the bump genuinely is near-free. **Product dimensions are the prerequisite for every number in
this plan being true**, and they are the cheapest shipping work available.

## 4. Why Smart Pricing stops being a convenience

`offer.shipping.free_above_amount` is implemented and validated — it frees the baseline option above a cart
threshold. It is also, on its own, **a promise to lose more money the more a customer buys**. The only way
it is coherent is if the cost was recovered in the product price, which is precisely what Smart Pricing is
for. `plans/SHIPPING_CHARGES.md` already states the invariant:

```
free    + cost line      = baked        (recovered in the price)
free    + no cost line   = absorbed     (a loss leader, deliberately)
charged + no cost line   = the buyer pays it
charged + cost line      = DOUBLE-COUNTED   <- forbidden
```

Three things follow, and all three are gaps today:

1. **The invariant is unenforced.** `shipping_charges.smart_pricing_conflict` implements it, has tests, and
   has **no production caller**. It is the third decision in this codebase encoded in a function nobody
   calls — after `fees.fee_base` (which let the platform charge a fee on postage in the books) and
   `ledger` `cogs` (still unwritten). A rule with no caller is not a rule.
2. **`free_above_amount` has no UI.** The engine honours it; no screen sets it. A tenant cannot offer free
   shipping over $50 today even though the code would do it.
3. **The cost line can now be real.** `plans/SMART_PRICING.md §10` lists as open:

   > *"Outbound shipping as a `fixed` line is an estimate until the carrier rate API is wired. The formula
   > does not change when it lands — only where that one number comes from."*

   **It landed.** `domain/shipping_rating.rate_parcels` rates a real packed parcel against a real
   destination. The "Shipping to customer" cost line can be derived from a carrier quote to a representative
   destination instead of typed — the tenant's own products, their own boxes, their own carrier account.

## 5. What to build

### P0 — Product dimensions (prerequisite)

Nothing below is accurate without them, and the gap is **not** a missing warning — `product_readiness`
already names it on the Shipping screen, added 2026-09-24 when the item/box inversion was fixed
(`plans/TODO.md`). The gap is that the data still is not there. Measured 2026-10-01:

```
dev    2 of 15 shippable products carry item dimensions
prod   0 of 4
```

Thirteen months of warnings nobody acted on is a different problem from no warning. So P0 is about making
the fill-in cheap rather than making the gap louder:

- **A carrier parcel template or a box as a one-click default.** Most products are posted in one of a
  handful of shapes the tenant already listed in their box catalog.
- **Carry dimensions forward** from the last product in the same category, pre-filled and editable.
- **Block nothing.** Item dimensions are optional to create a product, and the shipping module must not
  become compulsory sideways — the existing readiness copy is already careful about this.

A fourteenth product typed by hand is not the obstacle; fourteen empty forms is.

### P1 — Shipping on upsells and downsells

At upsell time: pack the upsell's items, rate to the stored destination, add the amount to the
PaymentIntent, and **show it on the upsell page before the buyer clicks**. Record it exactly as the first
sale does — `shipping_amount` on the order, `shipping_revenue` in the ledger — so one upsell is not a
second accounting shape.

Two cases, and the tenant chooses which applies:

- **The original order has not shipped.** The upsell item very likely rides in the same parcel, so the
  honest charge is the **delta**: re-rate the combined parcel, subtract what was already charged. Often
  near zero, which is also a good offer ("add it, it ships with your order").
- **The original order has shipped.** It is a second parcel at a second cost; quote it in full.

The tenant's existing `shipping.mode` applies unchanged — a `free` offer's upsells stay free.

### P2 — Order-bump exposure, measured at authoring time

Since it cannot be priced at checkout, it must be **visible before publish**. The builder runs the §3
computation and states the number:

> *Adding this bump takes a typical order from 1 parcel to 2 — about **$6.40** of postage that will not be
> charged. Price it into the bump, make the bump digital, or accept it as a cost of conversion.*

Rejected alternative: quoting all bumps into the shipping price from the start. It overcharges every buyer
who declines the bump, which is worse than the problem.

Deferred alternative, worth revisiting: move **physical** bumps pre-checkout onto our own page, where the
shipping element already re-quotes on cart change. Correct shipping — at the cost of the payment-step
placement that makes bumps convert.

### P3 — Enforce the invariant, and give the threshold a control

- Call `smart_pricing_conflict` where offers are saved and published, and surface it as a blocking
  validation: `charged + cost line` is a double charge to a real buyer.
- A `free_above_amount` control in the offer builder, shown with what it implies: *"Free shipping over $50
  — your cost profile needs a shipping line, or this comes out of your margin."*

### P4 — Derive the shipping cost line from a real rate

In the Smart Pricing panel, a **"Get this from my carrier"** action on the "Shipping to customer" line:
pack this product, rate it to a representative destination, fill the number, stamp it with the date and
destination so staleness is visible (`plans/SMART_PRICING.md §6`). Typed stays allowed — a tenant with no
carrier connected still needs a number.

### P5 — A stated combined-shipping policy

One tenant-level choice: *additional items (bumps, upsells) ship free with the original order.* For many
sellers that is both true and a selling point. The point is that it becomes **a decision with a number
attached** — the ledger now records real carrier cost, so `shipping_margin` reports what the policy costs
instead of hiding it. The failure today is not that extras ship free; it is that nobody knows.

## 6. What this does not solve

- **Subscriptions still charge no postage.** Unchanged, and still its own design
  (`plans/LIVE_SHIPPING_RATES.md`, "Known limitations").
- **A bump taken on Stripe's page can never be priced at checkout** while we stay on hosted Checkout. P2
  bounds and discloses the exposure; it does not remove it.
- **`cogs` is still unwritten.** It needs `unit_cost` on the Product, which belongs with
  `plans/INVENTORY_COST_BASIS.md`. Until then `summarize`'s `profit` omits the goods.

## 7. Sequencing

```
P0 product dimensions        prerequisite; cheapest win; unblocks every number here
P1 upsell / downsell shipping the big one, and unconstrained
P3 invariant + threshold UI   small, and stops a double charge reaching a buyer
P2 bump exposure warning      needs P0 to be meaningful
P4 derived cost line          needs the Smart Pricing panel (SMART_PRICING.md step 3)
P5 combined-shipping policy   last; it is a policy over machinery that must exist first
```

P3 is out of order deliberately: it is hours of work and the failure it prevents is a buyer charged twice
for postage.
