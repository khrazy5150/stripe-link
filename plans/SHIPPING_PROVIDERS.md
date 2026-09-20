# Shipping providers: wiring Shippo, then the rest

## What is actually here today

Verified 2026-09-20, not assumed.

**Built and good:**

- `schemas/ShippingConfig.schema.json` — complete and well-shaped: provider + `api_key_ref` +
  `connection_status`, ship-from and return addresses, a default parcel, `rate_options`
  (`markup_amount`, `free_shipping_threshold`, `allowed_carriers`, `default_service_level`) and
  `label_options` (pdf/png/zpl, 4x6 / 8.5x11).
- `src/handlers/shipping.py` (101 lines) — `GET`/`PUT /shipping`. It encrypts a freshly-typed key with
  KMS, preserves an unchanged key, **drops the key when the provider changes**, and redacts on read. This
  part is better than the legacy implementation and should not be rewritten.
- `dashboard/src/components/Shipping.vue` (396 lines) — the full settings form, including a disabled
  `connection_status` field.
- `Product.fulfillment` already carries `requires_shipping`, `ship_from`, `weight_lb`, `dimensions`.

**Not built — this is the whole of "not wired":**

1. **No provider code exists.** Not one HTTP call to Shippo, EasyPost, ShipStation or Easyship. The four
   names appear only as enum values in the schema and options in a `<select>`.
2. **`connection_status` can never say `connected`.** `prepare_provider_secret` only ever writes
   `untested` or `not_configured`. The dashboard displays a field that nothing can advance, and there is
   no test endpoint to advance it.
3. **No rates, no labels, no tracking.** Routes are `GET /shipping` and `PUT /shipping`. That is all.
4. **No destination address is stored.** Checkout *does* collect one (`shipping_address_collection`,
   US + CA, payment mode only — checkout.py:442), but `order_record_from_session` never reads
   `shipping_details` off the session. **No label can be bought for any order that exists today**, because
   nothing knows where to send it. This is the blocking gap, and it is invisible from the shipping module.
5. **No shipment/label document.** Nothing to write a tracking number onto, and no idempotency key to stop
   a second label being bought for the same order.

There is also **no shipping cost anywhere**: no Stripe `shipping_options` are ever sent, so shipping is
silently free (or baked into the price) on every order ever placed here.

## The legacy implementation, and what to take from it

`../stripe-cart` has `layers/shipping/python/shipping_providers.py` (643 lines), `src/shipping_api.py`
(808 lines) and `plans/SHIPPING_IMPLEMENTATION.md` (392 lines).

**Take:** the Shippo REST call shapes. The legacy `ShippoProvider` makes real HTTP calls —
`/addresses/`, `/parcels/`, `/shipments/`, `/transactions/`, `/tracks/` — with the
`Authorization: ShippoToken <key>` header, and it already handles Shippo's awkward polymorphism (`rate`
and `servicelevel` arriving as either a string or an object). That knowledge is expensive to rediscover
and cheap to re-read.

**Do NOT take the code.** Two reasons, both hard:

- It is built on `requests` in a Lambda layer. `src/requirements.txt` in this repo is deliberately empty —
  "the AWS Lambda Python runtime already provides boto3/botocore… All other imports are the standard
  library." Stripe is called from `urllib` in `create_stripe_checkout_session`, and shipping must be too.
  No layer, no dependency.
- The legacy plan's own **Known gaps** section says it was never finished: front-end and back-end disagree
  on the payload shape, the backend depends on the `shippo` SDK while the layer ships `requests`, labels
  are returned but not persisted, and **API keys are not encrypted**. stripe-link is already ahead on the
  last point; adopting the legacy shape would be a regression.

Treat it as behavioural reference, exactly as CLAUDE.md prescribes: functional equivalence, not structural.

## The fork to settle before any code

**Where does the shipping COST live?** Three answers, and they are not compatible:

- **A. Post-purchase labels only (recommended for P1).** Shipping stays free or price-baked at checkout.
  The tenant buys a label from the order afterwards. No checkout change, no rate call in the buyer's path,
  and the tenant pays the carrier. This is the legacy plan's "minimum useful version" and it is genuinely
  useful on its own.
- **B. Flat rates at checkout.** Tenant-configured `shipping_options` on the Stripe session (Stripe
  supports up to 5). Buyer pays; no live carrier call. Needs `rate_options.markup_amount` and
  `free_shipping_threshold`, which the schema already has and nothing reads.
- **C. Live carrier rates at checkout.** Stripe hosted Checkout cannot call us mid-session, so this means
  computing rates *before* creating the session (needs the address first — a page-side address form) or
  moving off hosted Checkout entirely. Much larger, and it changes the buyer's flow.

A is the only one that ships without touching the buyer's path. B is a natural follow-on. C should not be
attempted until someone asks for it.

## Phases

### P0 — make a label possible at all (blocking, ~small)

- Persist the destination address on the order: read `shipping_details` (and the newer
  `collected_information.shipping_details`) off the Stripe session in `order_record_from_session`.
- Decide the **Shipment/Label document**: its own schema, keyed so one order can carry one outbound label
  and (later) one return label. Idempotency belongs here, not in the handler.
- Note: historic orders have no address. They can be re-fetched from Stripe by session id if it ever
  matters; assume not, and let old orders be unlabelable.

### P1 — Shippo connected, and the packer

- `domain/shipping/providers/shippo.py` over `urllib`, behind a provider-neutral interface
  (`test_connection`, `rates`, `buy_label`, `track`) so P4 is additive.
- A `mock` provider (already in the schema enum) as the default in tests — no test ever touches the network.
- `POST /shipping/test` → sets `connection_status` to `connected` / `failed` and `last_tested_at`, which is
  what the dashboard field has always been waiting for. Never echo the key back.
- Dashboard: a **Test connection** button.
- **`domain/shipping/packing.py` — `pack(items, boxes) -> [parcel]`.** Promoted out of P2 because it is
  shared by label buying AND price estimation; built once or it will be built twice and disagree.

#### Packing, and why it is not a sum

Weight is additive. **Dimensions are not.** Carriers bill `max(actual_weight, dimensional_weight)` where
dim weight is `L x W x H / divisor`, so three items in one carton costs neither three parcels nor one item.
Deciding which boxes items fit into is 3D bin packing — NP-hard, and not worth solving properly.

Decided approach, in order:

1. **Volume fit.** Sum item volumes, multiply by a void-fill factor (~1.25), and choose the smallest box in
   the tenant's box catalog whose volume clears it. One parcel.
2. **Fallback: one parcel per item**, when any single item does not fit the largest box, or the tenant has
   no catalog yet (then `default_parcel` is the only box).

This is deliberately an approximation, and it is the same one the big carriers' own tools make. It will be
wrong sometimes; see **Calibration** below, which is the part that makes being wrong survivable.

A **box catalog** is new: a short list of the boxes a tenant actually uses (name, inner L/W/H, empty
weight). Without it there is nothing to pack into and everything falls to (2). The empty weight matters —
a box is not weightless and the carrier bills the whole parcel.

**Multi-origin is out of scope.** `Product.fulfillment.ship_from` exists in the schema, but `products.js`
writes `ship_from: null` unconditionally, so no product has ever carried one. A bundle whose items ship
from different places would need several parcels by definition; defer until a product can express it.

### P2 — rates and label purchase from an order

- `POST /shipping/rates` (order → parcel → rates) and `POST /shipping/labels` (rate → transaction).
- Parcel resolution comes from `pack()` in P1 — never re-derived here.
- Persist carrier, service, tracking number, tracking URL, label URL, cost, provider transaction id, and
  any error, onto the shipment document.
- `auto_fulfill_after_label_purchase` (already in the schema) marks the order fulfilled.
- Dashboard: a Buy label action on `Orders.vue`.

### P3 — tracking and the buyer

- Tracking number into the order-status email; tracking webhook or poll.

### P4 — the other three providers

Behind the same interface. EasyPost is closest to Shippo; ShipStation needs basic-auth and has a different
label flow; Easyship is the least similar. The legacy file has working call shapes for all three.

### PE — estimated shipping at pricing time ("Calculate Price")

Independent of P2/P3 and arguably more valuable: labels serve tenants who already ship, this serves every
tenant at the moment they set a price. Depends only on P1 (provider + packer).

#### What it does

A **Calculate Price** button on the product/price form that produces:

```
tenant_keyed_amount = product_cost + margin + estimated_shipping
```

and then hands that to the EXISTING `calculate_price()` in `domain/fees.py` unchanged. This is not an
analogy to Net-Guaranteed pricing — it is the same mechanism. Shipping is one more component of what the
tenant wants to net, and the existing gross-up already makes the buyer cover the fees on it.

**Say the consequence out loud in the UI:** under `net_guaranteed` the tenant nets cost + margin + shipping
exactly; under `split` they pay half the platform and Stripe fees on the shipping portion too. That is a
money decision and it must not be discovered later.

#### The hard part: there is no destination at pricing time

Carrier rates depend on origin AND destination. When a tenant prices a product, no buyer exists. So an
estimate is **a statistic over destinations, not a number**.

Approach: rate the packed parcel against a set of representative destinations (US zones 2-8, one
representative postcode each), and present the distribution. N rate calls per click — acceptable because
this is a tenant action, not a checkout-path call, and it caches hard on
`(origin, parcel, carrier, service)`.

**Show the spread, not one number.** "Zone 2 $8.40 - median $11.20 - Zone 8 $16.90", with the tenant
choosing what they price at. They absorb the variance either way; seeing it is the difference between
intelligent pricing and a guess with a decimal point.

Carrier and service come from `rate_options.allowed_carriers` and `rate_options.default_service_level` in
the existing ShippingConfig. **Not a new User preference** — a second home would let the estimator and the
label buyer read different carriers and quietly disagree.

#### Store the basis, not just the number

```
price.shipping_estimate = {
  amount, carrier, service, zone_basis, percentile, packed_parcel, calculated_at, provider
}
```

Carriers raise rates annually (a GRI is typically several percent). A baked-in price calculated in January
is wrong by February and **nothing says so**. Storing the basis is what makes staleness detectable and
re-calculation meaningful; the amount alone is unauditable.

#### Calibration — the part that assumes we are wrong

**This is uncharted territory and the first approach is a hypothesis, not a design commitment.** The plan
is to start with zone sampling + volume-fit packing, measure, and expect to end up somewhere else.

What makes that survivable:

- **Record estimate vs actual.** Once P2 can buy labels, every purchased label has a real cost for a real
  parcel to a real address. Write the actual alongside the estimate that was used when the price was set.
  That data set is the only honest answer to "is the estimator any good", and it costs almost nothing to
  collect from day one. **Collect it before anyone needs it** — a comparison cannot be backfilled.
- **Keep the strategy swappable.** `estimate(parcel, origin, options) -> distribution` behind one
  interface, with zone-sampling as the FIRST implementation, not the only possible one. Plausible
  successors: a cached zone/weight matrix (far fewer API calls), a flat table per carrier, or a learned
  correction factor over the recorded error.
- **Expect the packer to be the bigger error source, not the rates.** Rates are a lookup; packing is a
  guess. If estimates come out wrong, suspect the box choice and the void-fill factor first.
- **Tighten with concrete tests.** Shippo test tokens rate for free, so a fixture set of real parcels to
  real postcodes can be run repeatedly without spending anything.

No part of this should be treated as settled until that comparison has data in it.

### Later — return labels and refunds

The legacy plan has a full section. The rule worth carrying over verbatim: **never issue a Stripe refund
automatically just because a return label was created.**

## Risks worth naming before building

- **Buying a label spends real money**, immediately and irreversibly, at the carrier. `test_mode` is in the
  schema; it must be impossible to misread on screen. Shippo's test token buys nothing, which is exactly
  why it is the right provider to start with.
- **Double-buy.** A double-clicked button must not buy two labels. Idempotency keyed on the order, enforced
  in the document, not in the UI.
- **Default weights are a real hazard, and Calculate Price makes it worse.** `products.js` defaults every
  physical product to 1 lb and 10×10×10 in. A tenant who never edited those gets a label at the wrong
  postage — which the carrier bills, or the package comes back. With estimated shipping baked into the
  price, the same defaults silently set the SELLING price of every product they touch. Rates must be
  computed from real values, and both the estimator and the label buyer must say loudly when a value is a
  default rather than something the tenant entered.
- **Address validation.** Shippo validates and returns messages; a label bought against an unvalidated
  address is money spent on a package that comes back.
- **Key handling.** The key is already KMS-encrypted and redacted on read. The test endpoint and any
  provider error must never echo it — a provider 401 body can contain the key that was sent.

## Decisions needed

1. **Confirm A** (post-purchase labels) for P1, with B as a later phase?
2. **One shipment document per order, or a list?** Split shipments (two boxes, two labels) are real but
   double the model. One now, list later, or list from the start?
3. **Does the tenant pick a rate, or do we auto-pick?** `default_service_level` + `allowed_carriers` exist
   in the schema, suggesting auto-pick with an override. Confirm.
4. **Test-mode boundary.** Should a tenant's `test_mode` flag be independent of the platform env (a live
   tenant testing labels), or follow it? This mirrors `plans/STRIPE_MODE_DECOUPLING.md` and should not be
   answered differently here by accident.
5. **Which percentile does Calculate Price offer by default?** Median under-prices half the orders; max
   over-prices nearly all of them. A default has to be picked even if the tenant can override it.
6. **`free_shipping_threshold` vs baked-in shipping — they double-count.** If shipping is already in the
   price, the threshold is either meaningless or discounts something the buyer has already paid for. One
   rule needed: threshold applies only when shipping is charged separately (B), or it is retired.
7. **Who owns the box catalog?** Per-tenant (most tenants use 3-5 box sizes) or a platform default list
   the tenant trims? A tenant with no catalog gets one-parcel-per-item, which over-estimates.
8. **Does the buyer ever see a shipping line?** Under A + Calculate Price, shipping is invisible and the
   page can legitimately say "free shipping". Confirm that is the intent, because it constrains B later.
