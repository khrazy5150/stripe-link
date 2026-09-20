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

### P1 — Shippo, actually connected

- `domain/shipping/providers/shippo.py` over `urllib`, behind a provider-neutral interface
  (`test_connection`, `rates`, `buy_label`, `track`) so P4 is additive.
- A `mock` provider (already in the schema enum) as the default in tests — no test ever touches the network.
- `POST /shipping/test` → sets `connection_status` to `connected` / `failed` and `last_tested_at`, which is
  what the dashboard field has always been waiting for. Never echo the key back.
- Dashboard: a **Test connection** button.

### P2 — rates and label purchase from an order

- `POST /shipping/rates` (order → parcel → rates) and `POST /shipping/labels` (rate → transaction).
- Parcel resolution: per-item `weight_lb` / `dimensions`, falling back to `default_parcel`.
- Persist carrier, service, tracking number, tracking URL, label URL, cost, provider transaction id, and
  any error, onto the shipment document.
- `auto_fulfill_after_label_purchase` (already in the schema) marks the order fulfilled.
- Dashboard: a Buy label action on `Orders.vue`.

### P3 — tracking and the buyer

- Tracking number into the order-status email; tracking webhook or poll.

### P4 — the other three providers

Behind the same interface. EasyPost is closest to Shippo; ShipStation needs basic-auth and has a different
label flow; Easyship is the least similar. The legacy file has working call shapes for all three.

### Later — return labels and refunds

The legacy plan has a full section. The rule worth carrying over verbatim: **never issue a Stripe refund
automatically just because a return label was created.**

## Risks worth naming before building

- **Buying a label spends real money**, immediately and irreversibly, at the carrier. `test_mode` is in the
  schema; it must be impossible to misread on screen. Shippo's test token buys nothing, which is exactly
  why it is the right provider to start with.
- **Double-buy.** A double-clicked button must not buy two labels. Idempotency keyed on the order, enforced
  in the document, not in the UI.
- **Default weights are a real hazard.** `products.js` defaults every physical product to 1 lb and
  10×10×10 in. A tenant who never edited those gets a label at the wrong postage — which the carrier bills
  or the package is returned for. Rates must be computed from real values, and the UI should say when it is
  falling back to a default.
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
