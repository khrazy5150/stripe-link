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

### P0 — Honest inputs, and no price without them

> **✅ BUILT and deployed to dev, 2026-10-01.** P0a–P0e all shipped. **P2 shipped with P0e** rather than
> separately: the order-bump exposure is computed in the rate estimator, which is where a tenant is already
> looking at shipping, so it needed no second surface. Remaining: P1 (upsell shipping), P3 (the
> double-count invariant and the `free_above_amount` control), P4, P5.

Revised 2026-10-01 after the author reviewed the product modal. Three parts, and the first is a live
correctness bug rather than a UX improvement.

#### P0a — A parcel nobody measured must not produce a price

The author: *"Right now the shipping calculator invents charges without dimensions. I don't want the
estimator to show any shipping charges without dimensions and weight. In those cases the software must
assume free shipping and be done with it."*

It does not invent from nothing — which is worse, because the result looks legitimate. `shipping_packing`'s
`declared` strategy fires as a **silent fallback** whenever item dimensions are missing, using
`fulfillment.dimensions` even when `ships_alone` is unchecked. Stored dev data has the identical
`10×8×4 @ 1 lb` on a paint set, a shaker bottle and whey protein — a leftover default, not a measurement —
and a real buyer was quoted and charged **$6.57** rated from it.

**The rule:** a parcel may only be built from data a tenant actually supplied about THIS product —
item dimensions plus a weight, or a box they explicitly declared by ticking *"always ships in its own
box"*. Absent that, there is no parcel, and therefore **no shipping charge**: the offer quotes free and
the order ships free.

That requires one behaviour change: **drop the declared-box silent fallback.** A declared box applies when
`ships_alone` is set and not otherwise. `plans/SHIPPING_PROVIDERS.md` already calls the declared box *"an
EXCEPTION, not the default route"*; this finishes that inversion instead of leaving a path that quietly
contradicts it.

**This refines the "never render an unknown as free" rule rather than breaking it.** Two different
unknowns:

| Unknown | Who can fix it | What the buyer sees |
| --- | --- | --- |
| Carrier unreachable, rate call failed | us, by retrying | *"We could not get shipping rates"* + retry |
| Tenant supplied no dimensions | the tenant, later | **free shipping** — quietly, and the sale completes |

A buyer cannot act on a missing measurement, and showing them an error over it costs the tenant the order.
The tenant is the one who must hear about it, which is P0b.

#### P0b — Tell the tenant the truth, which depends on their zones

The proposed warning — *"leaving this blank will prevent you from charging shipping"* — is true for two of
the four zone rules and false for the other two:

| Zone rule | Works with no dimensions? |
| --- | --- |
| `free` | yes |
| `flat` | **yes** — $7 is $7 |
| `flat_rate_box` | no — nothing to match to a box |
| `live` | no — nothing to rate |

A tenant on flat zones told they cannot charge shipping, who then finds they can, stops believing every
other warning the product shows. So the message is **derived from their own configuration**: live zones get
*"orders containing this product will ship free"*; by-box gets *"cannot be matched to a box"*; flat and free
get the milder truth, *"you will not be able to buy labels for this"*; a tenant with no shipping configured
at all gets nothing, because at step 2 of 5 they have not made that decision yet.

Same for the `optional` badge: optional to **save**, required to **quote**, and which applies depends on
configuration.

#### P0c — Remove what does not help, and show what was worked out

The **Shipping Box** section collects four numbers that, in the common case, are read by nothing. Verified
against the author's own screenshot — item `3.3×5×1.8 @ 2.5 lb`, declared box `10×8×4`, *ships alone*
unchecked:

```
chosen parcel -> Small (6x4x4) | 2.65 lb | strategy: packed
declared box 10x8x4 used? NO - item dimensions won
```

- **Reveal the box fields only when they are read**: when *"always ships in its own box"* is ticked. Once
  P0a lands that is their only remaining use.
- **Show the derived parcel instead**, because the section's own copy already promises it (*"Normally we
  work the box out from the sizes above"*): *"This ships in your Small box (6×4×4), 2.65 lb — about $6.57
  to Denver."* Both halves exist and are deployed (`pack` + `shipping_rating.rate_parcels`). An override
  you can see the baseline for is a decision; one you cannot is a guess.
- **Reject impossible values.** The same screenshot has a packed weight of 1 lb on an item weighing 2.5 lb.

#### P0d — Make the filling-in cheap

`product_readiness` has warned since 2026-09-24 and the numbers have not moved: **2 of 15 dev and 0 of 4
prod** shippable products carry item dimensions. A better warning will not move them either.

- A one-click default from the tenant's own box catalog or a carrier parcel template.
- Carry forward from the last product in the same category, pre-filled and editable.
- Block nothing — dimensions stay optional to create a product.

### P0e — The rate estimator rates OFFERS, not hand-picked products

The author, 2026-10-01: *"The estimator should use offers instead. Offers contain bundles which give a more
accurate estimate of order packing. There is no point in forcing tenants to select products one by one when
the offer already presents this for free."*

Correct, and the gain is larger than the convenience. `handlers/shipping.preview_rates` takes
`product_ids[]` and quantities the tenant assembles by hand, which means **the preview rates a cart no
buyer will ever have**. A tenant checks one product, sees $6.57, and ships a three-item bundle for $19.
The offer is the real cart: its items, its quantities, its bumps.

Changing the input makes the preview **authoritative instead of indicative** — the same offer, the same
packer, the same rater, the same code path a buyer's `/shipping-quote` runs. A preview that cannot disagree
with checkout is worth more than one that is merely easier to drive.

- **Primary input: an offer picker.** Pack `offer.items` exactly as checkout does, through `_quote_parcels`.
- **Show the parcel breakdown, not just a price** — *"3 parcels: Small ×2, Medium ×1"* is what tells a
  tenant their products are unmeasured, far more plainly than a readiness list does.
- **Show the order bump line too**, when the offer has one: this is where P2's exposure number comes from,
  computed in the place a tenant is already looking at shipping.
- **Keep an ad-hoc product picker as the secondary path**, not the default. Measuring a new product before
  it belongs to any offer is a real case; making it the only case was the mistake.
- **Offers with unmeasured products say so in those words** — *"2 of 3 products have no size, so this offer
  ships free"* — rather than returning a rated parcel built from a default (P0a).

`preview_rates` also rates **`parcels[0]` only**, by design, because a tenant comparing boxes wanted one
box's price. An offer-shaped estimator wants the whole order, which `shipping_rating.rate_parcels` already
does for buyers. The two should converge on that function.

### P1 — Shipping on upsells and downsells ✅ (shipped 2026-10-01)

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

**The delta needs the whole box measured** (fixed 2026-10-02). Both call sites — the button's disclosure
and the charge — build `products_by_id` from the ONE product being sold, which is all either needs to
price the item. The delta needs more than that: it re-packs the *first sale's* lines together with the
upsell, so it needs the dimensions of things the upsell handler was never asked about. Handing it the
one-product map did not fail. `packable_items` reads an absent product document as a shippable thing of
unknown size and the packer gives each one a parcel, so the "combined" rate came back as three phantom
parcels plus the real one — larger than the baseline, and the difference looked like a quote. Live test:
**+ $6.27** on the first upsell of an order already paying $6.11, **+ $0.37** on the second. Rated with a
complete map, both are **$0.00** — the author's own bundle rates identically at 3.55 lb and 3.85 lb, so
nothing is owed. Two changes: `quote_upsell_shipping` takes a `products_repo` and loads the baseline's
missing products, and it refuses outright to rate a line whose product is not in the map rather than
letting the packer invent a box for it. A map it cannot complete falls back to the standalone rate,
which over-charges in the one direction a tenant can refund.

### P2 — Order-bump exposure ✅ (shipped with P0e)

> Built as part of the rate estimator rather than the offer builder: the estimator already packs the
> offer's items, so adding the bump and re-packing is the same computation. "Your order bump adds 1
> parcel. A buyer who adds it on the payment page is not charged for it." The builder-side warning below
> remains worth having if tenants do not visit the estimator.

Since it cannot be priced at checkout, it must be **visible before publish**. The builder runs the §3
computation and states the number:

> *Adding this bump takes a typical order from 1 parcel to 2 — about **$6.40** of postage that will not be
> charged. Price it into the bump, make the bump digital, or accept it as a cost of conversion.*

Rejected alternative: quoting all bumps into the shipping price from the start. It overcharges every buyer
who declines the bump, which is worse than the problem.

#### P2b — Charging it, not just disclosing it ✅ (shipped 2026-10-05)

P2 said disclosure was "the whole remedy available". It was not, and the exposure number it disclosed was
measuring the wrong thing.

**What the parcel count missed.** `_bump_exposure` reported how many EXTRA PARCELS a bump forces, on the
reasoning that a bump adding no parcel ships free. A real order disproved it: quoted at **620c**, shipped
at **669c**, one parcel throughout — the single parcel simply had to become a **Large (14x11x8)** instead
of a **Medium (10x8x6)**. The count said *zero exposure* for the case that produced the loss. Scaling the
same unquoted bump: 1–3 units **49c**, 4 units **163c**, 5 units **734c**. Box sizes are cliffs, so the
exposure was never bounded by pennies.

Measured the same day, and worth recording because the first diagnosis was wrong: the two **post-purchase
upsells** on that order added **nothing at all** (669c → 669c → 669c). P1's zero-delta answer was correct;
the bump had already moved the box before the first upsell page loaded.

**The remedy: `price.shipping_surcharge`.** A flat postage amount folded into what Stripe charges for the
bump, via `domain/stripe_products.charged_unit_amount`, so only the buyers who TAKE the bump pay it.

- Flat rather than live because `optional_items` require a **pre-synced Stripe Price** — there is no
  per-destination hook at the moment the buyer ticks the box. This is the ceiling of what the hosted page
  allows, not a preference.
- **Confined to `order_bump` prices**, enforced by the document validator. That confinement is a safety
  property: any other price can also be bought as an ordinary cart line, and an ordinary cart line is
  already inside the live shipping quote, so folding postage in would bill it twice.
- **Every reader goes through `charged_unit_amount`** — the price builder, `price_differs`, and the drift
  check. Writing price+surcharge while comparing bare `unit_amount` would find a difference on every sync
  and replace the Stripe Price forever.
- **Recorded as postage, not merchandise.** Checkout stamps `metadata[order_bump_shipping]`; the webhook
  turns it back into `order.bump_shipping_amount` for the bumps actually taken, and the ledger adds it to
  `shipping_revenue`. Kept OUT of `order.shipping_amount`, which means one specific thing (what Stripe
  reported for the shipping LINE) and drives the fee split that must keep agreeing with the
  `application_fee_amount` checkout actually sent.
- **The estimator now reports the box change and prices the delta** (`bump_box_change`, and
  `bump_postage` under the opt-in `price_bump_postage`, which costs a second carrier call). Verified live
  against the order above: suggested **49c**, exactly the hand-measured gap. The banner fires on a bigger
  box as well as an extra parcel, and names the figure to type into the field.

Still open: the surcharge is per-bump and destination-blind, so it under-collects on a far zone and
over-collects on a near one. The deferred alternative below remains the only way to make it exact.

Deferred alternative, worth revisiting: move **physical** bumps pre-checkout onto our own page, where the
shipping element already re-quotes on cart change. Correct shipping — at the cost of the payment-step
placement that makes bumps convert.

### P3 — Enforce the invariant, and give the threshold a control ✅ (shipped 2026-10-01)

- Call `smart_pricing_conflict` where offers are saved and published, and surface it as a blocking
  validation: `charged + cost line` is a double charge to a real buyer.
- A `free_above_amount` control in the offer builder, shown with what it implies: *"Free shipping over $50
  — your cost profile needs a shipping line, or this comes out of your margin."*

### P4 — Derive the shipping cost line from a real rate ⛔ BLOCKED

> **Not built, 2026-10-01, and deliberately not faked.** It needs somewhere to put the number, and there
> is none: `cost_profile` is not a stored field anywhere in `src/`, `schemas/` or the dashboard
> (`plans/SMART_PRICING.md` build order **step 1** is unbuilt), and there is no pricing panel (**step 3**).
>
> The derivation half could be written today -- `shipping_rating.rate_parcels` already rates a real parcel
> to a real destination, which is exactly what SMART_PRICING.md §10 said was missing. But a function no
> caller can reach is the pattern this session has now removed three times: `fees.fee_base` let the
> platform charge a fee on postage in the books for weeks, `ledger` `cogs` still reports profit without
> goods, and `smart_pricing_conflict` would have let a buyer be charged twice. Adding a fourth to look
> finished would be worse than leaving it clearly unfinished.
>
> **Unblocked by:** SMART_PRICING.md step 1 (`cost_profile` on the Price + `domain/smart_pricing.py`),
> then step 3 (the panel). The work itself is then small -- one action on the shipping cost line that
> packs the product, rates it to a representative destination, and stamps the figure with its date and
> destination so staleness stays visible (§6).

In the Smart Pricing panel, a **"Get this from my carrier"** action on the "Shipping to customer" line:
pack this product, rate it to a representative destination, fill the number, stamp it with the date and
destination so staleness is visible (`plans/SMART_PRICING.md §6`). Typed stays allowed — a tenant with no
carrier connected still needs a number.

### P5 — A stated combined-shipping policy ✅ (shipped 2026-10-01)

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
P0a no price without real dimensions   LIVE BUG: buyers are charged from an unmeasured box
P0b config-driven warning              small; stops the warning being wrong for flat-rate tenants
P0c trim the box fields, show the derived parcel
P0e estimator takes an OFFER           makes the preview authoritative, not indicative
P0d cheap fill-in                      the thing that actually moves 2-of-15 to 15-of-15
P1  upsell / downsell shipping         the big one, and unconstrained
P3  invariant + threshold UI           hours of work; stops a buyer being charged twice for postage
P2  bump exposure warning              needs P0 to be meaningful
P4  derived cost line                  needs the Smart Pricing panel (SMART_PRICING.md step 3)
P5  combined-shipping policy           last; a policy over machinery that must exist first
```

**P0a first, and on its own if nothing else follows.** Every other item here improves something; P0a stops
real buyers being charged a real amount computed from a box nobody measured. P3 is out of order for the
same reason — the failure it prevents is a buyer charged twice for postage.
