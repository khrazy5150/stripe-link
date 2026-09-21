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

## Who this serves — two tenants, opposite needs

The build-vs-integrate question has different answers depending on who is asking, and getting this wrong
means building the right thing for the wrong person.

**The beginner.** Sells a few physical things. Has no carrier account, no label printer workflow, no idea
what a zone is. Today their shipping process is *driving to the post office*. For them, a plain
buy-a-label-and-print-it screen is transformative — and it does not matter at all that it is less capable
than ShipStation, because they were never going to use ShipStation. **This is the platform's core tenant**,
and they are served by us building it.

**The experienced merchant.** Already runs ShipStation or Shippo daily, with carrier accounts, negotiated
rates, batch printing and scan forms. They do not want our label screen and will not switch to it. What is
valuable to them is that their orders from us arrive in the tooling they already have. **They are served by
us integrating, not building.**

Both are real, and the phases below serve the beginner first because that is who arrives first. Integration
is the last phase, not the first — see PI.

The two paths share almost everything: destination address, shipment document, provider auth, the packer,
rates. They diverge only at the last mile — we buy the label, or we hand the order over. So building the
beginner's path first costs the integration path nothing.

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

### P0 — make a label possible at all — BUILT 2026-09-20

- Persist the destination address on the order: read `shipping_details` (and the newer
  `collected_information.shipping_details`) off the Stripe session in `order_record_from_session`.
- Decide the **Shipment/Label document**: its own schema, keyed so one order can carry one outbound label
  and (later) one return label. Idempotency belongs here, not in the handler.
- Note: historic orders have no address. They can be re-fetched from Stripe by session id if it ever
  matters; assume not, and let old orders be unlabelable.

**Built:** `destination_address_from_session()` (reads both Stripe shapes, refuses a partial address rather
than half-filling one) wired into `order_record_from_session`; `schemas/Shipment.schema.json`; and
`build_shipment` / `mark_purchased` / `mark_failed` in `domain/shipping.py`.

Two decisions live in the document rather than in a handler, because both are ways to lose money:

- **The shipment id is DERIVED** — `shp_<order_id>_<kind>_<sequence>`. It IS the idempotency key, so a
  double-clicked Buy Label claims a row that already exists and returns the first shipment instead of
  buying a second label. A random id would have made two clicks two labels.
- **The row is claimed BEFORE the provider is called** (`status: "purchasing"`). A crash between spending
  and recording then leaves a row saying "we were buying this", carrying the provider idempotency key
  needed to find out whether it happened. Spend-then-record loses the label silently and bills the tenant.

Addresses and the parcel are snapshots: a label is a historical fact and an order corrected next week must
not change what was printed last week. `estimated_cost` is recorded from the first label so
estimate-vs-actual is measurable — it cannot be backfilled.

**Not built here:** the shipments TABLE and repository. They belong with the code that writes them (P2), and
an unused table is infrastructure without a caller.

### P1 — Shippo connected, and the packer — adapter + connection test + packer BUILT 2026-09-20

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
a box is not weightless and the carrier bills the whole parcel. Seed it with a platform starter list of
standard sizes; a tenant edits it to match their own shelf.

#### The product stores the BOX, not the ITEM — and that is the root cause

`ProductVariantsField.vue` heads these fields "Package Dimensions" and its own docstring calls them "the
box the thing ships in". The default is 10x8x4, which is box-shaped, not gummies-jar-shaped.

That works for a single-item order — ship it in what the tenant said — and it is exactly why a bundle
cannot be packed: **three products each declaring a box do not compose.** There is nothing to pack, only
boxes to add up, and boxes do not add.

Picking the smallest box that fits therefore needs an input that does not exist yet: the item's own size.
Do NOT reinterpret the existing field to mean that — every stored value is a box, so we would choose a box
big enough to hold a box and oversize every parcel.

**Add item dimensions; keep package dimensions as an explicit override.** A seller who knows "everything
goes in a 10x8x4" keeps saying so and is never second-guessed; a seller who describes the item gets
packing. Precedence:

1. One item AND the tenant declared a package → use it. They know their own operation.
2. Several items, or no declared package → pack the item dimensions into the smallest catalog box that
   fits.
3. No item dimensions → one parcel per item at its declared package size (today's behaviour, unchanged).

#### "Smallest that fits" is the packing rule, not the pricing rule

- Fit is 3D, not volume: every dimension must fit, with rotation allowed.
- The smallest box is not always the cheapest. Dimensional weight means a larger, lighter-dim box can win.
- **Carrier flat-rate boxes are a candidate, not a shortcut.** USPS Priority Flat Rate costs the same
  regardless of weight and zone, which makes the estimate an exact number instead of a percentile — but it
  wins on DENSITY, not on smallness. A small, light parcel (the beginner's typical package) is usually
  cheaper on computed rates; flat rate wins when something is heavy, compact and going far. Rate it
  alongside the fitting cartons and let the result decide.

So: pack to the smallest fitting box, then rate the candidates (fitting cartons + any fitting flat-rate
box) and let the cheapest win. The rate call is needed anyway; asking it about two or three candidates
instead of one is the same round trip.

**Multi-origin is out of scope.** `Product.fulfillment.ship_from` exists in the schema, but `products.js`
writes `ship_from: null` unconditionally, so no product has ever carried one. A bundle whose items ship
from different places would need several parcels by definition; defer until a product can express it.

### P2 — rates and label purchase from an order (the beginner's whole reason to be here)

- `POST /shipping/rates` (order → parcel → rates) and `POST /shipping/labels` (rate → transaction).
- Parcel resolution comes from `pack()` in P1 — never re-derived here.
- Persist carrier, service, tracking number, tracking URL, label URL, cost, provider transaction id, and
  any error, onto the shipment document.
- `auto_fulfill_after_label_purchase` (already in the schema) marks the order fulfilled.
- Dashboard: a Buy label action on `Orders.vue`.

### P3 — tracking and the buyer

The buyer is told their parcel is on its way **the same way this codebase tells them everything else** —
the receipt, the tip renewal, a download link. Reuse that path exactly; do not invent a shipping mailer.

The existing pattern, followed end to end:

1. **A pure content builder in `domain/receipts.py`** — `shipment_tracking_content(...) -> {subject, html,
   text}`, alongside `receipt_content` and `tip_renewal_content`. No I/O, so it is testable without a
   network or a mock, which is why those two are.
2. **Branding from `load_tenant_email_context(tenant_id)`** — `{business_name, support_email}`. The email
   comes from the TENANT's business, not from Junior Bay: `from_name=business_name`,
   `reply_to=support_email`. A buyer who replies asking where their parcel is must reach the person who
   sold it to them.
3. **Sent through `send_email` from `stripe_link/mailer.py`** (SES), injected as `mailer_send` so tests
   pass a fake and never send anything.
4. **It must never break the thing that triggered it.** `notify_tip_renewal` wraps its whole send in
   `except Exception` with the comment "a renewal notice must never fail the webhook". A tracking email is
   the same: a label is already bought and paid for by the time we try to send, so a bounced address or an
   SES hiccup cannot be allowed to fail the label purchase or the provider webhook.

**Two channels, do not conflate them.** `send_email` reaches the BUYER. The `Notification` documents in
`docs/NOTIFICATION_EMITTERS.md` drive the tenant's in-app bell (`order`, `lead`, `paid_invoice` emitters
exist today). A shipment is plausibly worth both — the buyer gets the tracking email, the tenant gets a
bell item — but they are separate mechanisms and the bell is optional.

**When it fires** differs by path and is the thing that makes PI harder than P2:

- **P2 (we buy the label):** immediately, because we have the tracking number in the purchase response.
- **P3/PI (tracking from the provider):** only when the provider tells us — webhook or poll. If a tenant
  buys labels in their own tool, nothing here knows a parcel shipped until that arrives.
- **Delivery updates** (out for delivery, delivered) are a second, noisier decision: a tracking webhook
  fires several times per parcel, and emailing on each one is how a helpful notice becomes spam. Designed
  separately in **`plans/SMART_NOTIFICATIONS.md`** — the short version is that the existing event-id dedupe
  cannot help, because a dozen scans are a dozen legitimately distinct events that happen to mean one
  thing. Dedupe belongs on the MEANING (a milestone recorded on the shipment), not on the event.

### P4 — the other providers, in the order we can prove them

**Gated on being testable without spending money.** Only two of the four can be:

| Provider | Test mode | Verifiable free? |
|---|---|---|
| Shippo | the API KEY carries it; test token, free test labels, production host | yes — P1 |
| EasyPost | same shape; free test key on signup | yes — P4a |
| ShipStation | `"testLabel": true` in the request, but the API needs a real (paid) account first | no |
| Easyship | unknown. The legacy adapter reads `test_mode` and never applies it to any request | no |

None of the four has a separate sandbox host — all four use production URLs, and test mode is a property
of the key or the request.

**The dropdown lists only what can be exercised** (`Shipping.vue`): Shippo, plus `mock` so the whole flow
can be walked with no provider account and no spend. The withdrawn options stay in the file as
commented-out lines with the reason attached — deleting them would lose why, and the next person would
restore them without knowing they had never been exercised.

Deliberately **UI only**. The schema still accepts every name, so nothing already stored is stranded and
restoring a provider when its turn comes is one template edit.

ShipStation and Easyship stay off until someone holds a working key. Building them behind a mock would
produce code that looks finished and has never been true — twice this codebase's cost in a single day (the
four-decimal `application_fee_percent`, the Decimal-vs-int validator): every layer green against fakes,
and the real API refusing the result.

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

### PC — the carrier calculator (a third caller of the same rate primitive)

A standalone "what would this cost, by whom, and how fast" tool. No order required: the tenant describes a
parcel and a destination and sees every carrier and service side by side.

**Why it is not a fourth integration.** It is the SAME `rates(parcel, origin, destination, options)` call
that P2 makes for an order and PE makes against sampled zones. Three callers, one primitive — which is the
argument for building that primitive carefully in P1 rather than inside whichever feature needs it first.

**Why a tenant needs it.** No carrier wins everywhere. USPS beats UPS on light parcels; UPS and FedEx take
weight and distance better; FedEx is usually the answer for overnight. A flat-rate box beats both when the
thing is heavy, compact and going far, and loses to Ground Advantage when it is light. A tenant choosing a
carrier without seeing the comparison is guessing, and they will be wrong in a direction that costs them
on every order they ever ship.

**Compare on two axes, not one.** Price AND transit time. "Cheapest" is the wrong default for a seller who
promises two-day delivery; the rate response carries estimated days and the table has to show it.

**Where the answer goes.** `rate_options.allowed_carriers` and `rate_options.default_service_level` already
exist in `ShippingConfig` and nothing writes them. The calculator is what fills them in: explore, decide,
save. That closes a loop that is currently open at both ends.

**Notes.**

- Which carriers are even available depends on the account: an aggregator supplies its own negotiated
  USPS/UPS/FedEx rates, and some carriers require the merchant to connect their own account for their own
  negotiated rates. The table must say which rates these ARE, or a tenant plans against numbers they
  cannot get.
- Rating is free but a comparison tool invites repeated querying. Cache on
  `(origin, parcel, destination, carrier set)`.
- It is also the cheapest honest calibration instrument we get: run a fixture set of real parcels to real
  postcodes and compare what it says against what a label actually costs.

### PI — integrating with the shipping stack a tenant already has (last)

For the experienced merchant, who has carrier accounts and a daily workflow and is not going to abandon
either. The goal is not to give them our tools; it is to make their orders show up in theirs.

Last, deliberately: it serves the tenant who arrives later, it depends on the providers we cannot test for
free (an experienced merchant is most likely on ShipStation), and it reuses the address, shipment document
and adapter built in P0-P2. Nothing about doing it last makes it more expensive.

Three shapes, cheapest first:

1. **A generic order webhook / export.** Provider-agnostic, testable for free, and serves any external
   tool — not only shipping. The cheapest integration that exists and probably the first to build. A
   merchant with an existing stack can usually wire an order feed themselves.
2. **Pull — the tenant configures us as a store in their tool.** ShipStation's *Custom Store* is an
   endpoint spec: they point it at a URL we expose, it polls for orders and posts shipment/tracking back.
   Often less work for us than pushing, and it is the canonical path for that product.
3. **Push — we create the order in their provider account.** Most control, most provider-specific code,
   and it needs the tracking number to come back to us afterwards or our order status goes stale.

Whichever shape, **tracking has to return**. If labels are bought in the tenant's own tool, our dashboard
and our order emails know nothing until the provider tells us — webhook or poll. That is real work in every
variant and must not be assumed free.

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
