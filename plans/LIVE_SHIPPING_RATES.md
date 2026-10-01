# Live carrier rates in the buyer's path

**Status:** planned, 2026-10-01. Supersedes nothing; completes `plans/SHIPPING_ELEMENT.md` tier 3.

The engine has refused to quote live rates since the day the `live` zone rule shipped. `resolve_options`
returns `needs: "carrier"` and empty options, checkout logs *"shipping to US needs carrier, and Stripe
cannot ask again once checkout opens"*, and the buyer is charged nothing. The rating machinery is not
missing — `preview_rates` packs a real cart and returns real UPS and USPS prices today. **The missing
input is the buyer's postal code, and the missing wire is the one that carries their chosen service to
checkout.** That is the whole of this plan.

Constraint set by the author, 2026-10-01: **stay on Stripe Hosted Checkout.** Apple Pay, Google Pay and
Link are worth more than a dynamic shipping widget inside Stripe's form.

---

## 1. What already exists, and what it is reused for

| Capability | Lives in | Reused as |
| --- | --- | --- |
| Tenant config, carrier connection, key storage | `handlers/shipping.py`, `SECRET_MODE="shipping"` | unchanged; the quote path decrypts the same ref |
| Zones, `rule_for`, `allowed_countries`, `services_for` | `domain/shipping_zones.py` | unchanged; `services_for` is what narrows live rates to what the tenant sells |
| Product dims/weights → parcels | `domain/shipping.py:packable_items`, `domain/shipping_packing.py:pack` | unchanged; the quote path packs exactly as the label path does |
| Carrier rating | `domain/shipping_providers.py:rates()` | unchanged; returns `service_token`, `carrier`, `amount`, `estimated_days` — everything the buyer UI needs |
| Rate discovery for tenants | `handlers/shipping.py:preview_rates` | unchanged; stays the Services-adoption tool |
| Buyer quote endpoint | `handlers/checkout.py:shipping_quote` | **extended** — takes a postal code, calls a carrier for `live` zones |
| Three-layer resolution | `domain/shipping_charges.py:resolve_options` | **extended** — the `live` branch can now be satisfied instead of only reported |
| Stripe encoding | `domain/shipping_charges.py:stripe_option_payload` | unchanged; inline `shipping_rate_data` is already the right mechanism |
| Session creation | `handlers/checkout.py` | **extended** — consumes a quote instead of re-deriving from zones |
| Buyer-paid shipping readback | `domain/shipping_charges.py:buyer_paid_shipping` | unchanged; still the authority on what was actually paid |
| Short-lived opaque buyer rows with TTL | `CARTS_TABLE` + `cart_tokens` / `tip_tokens` / `purchase_tokens` | **the precedent the quote row follows** — no new table |
| Public-endpoint throttling | `purchase_throttles_repository` | **the precedent the quote throttle follows** |

**No second rate engine, and no second shipping config model.** The quote is a *record of an answer the
existing engine already gave*, not a new way of deciding it.

### What is NOT reusable, and why

- `preview_rates` rates **the first parcel only** and says so in its own docstring. A buyer quote must sum
  every parcel, so the carrier call is factored out rather than called through that handler.
- `checkout_shipping`'s unanimity rule ("only quote when every allowed destination agrees") exists because
  the session had no destination. With a quote, there is exactly one destination, so that path becomes the
  **fallback** for buyers who never touched the element — it is kept, not replaced.

---

## 2. UI changes

### Landing-page Shipping element (`runtime/html.py`)

Today: one country `<select>`, a rate list that paints `service_token` radios, and a note. The radios are
decorative — **the chosen service never leaves the page.**

Changes:
- Country select + **postal code input**, side by side (the author's mock).
- **State/province input**, shown only for countries where carriers require it (US, CA, AU, BR, IN, MX…).
- Rate rows gain the quoted **price** and a **delivery estimate**; selecting one updates a running order
  total shown under the list.
- Explicit states: `idle` (no postal code yet), `loading`, `rates`, `none` (carrier returned nothing for
  this destination), `invalid` (carrier rejected the address), `error` (carrier or network failed) with a
  **Retry** button. No state ever renders an unknown as "Free".
- Publishes `window.__jbShipQuote` and `window.__jbShipService` alongside the existing `__jbShipTo`; the
  CTA appends all three.

### Shipping settings (`dashboard/src/components/Shipping.vue`)

- **Demote manual box prices.** The per-box price grid stays — it is the only answer for a tenant with no
  carrier — but it is labelled as the fallback it is, and it is hidden entirely when the zone is `live`.
- New readiness line: *"Live rates are configured but no services are enabled — buyers will see no
  shipping options."* `services_for` returns `[]` when `enabled_services` is empty, which would otherwise
  be another silent zero.
- The `live` zone hint stops blaming a missing carrier (it reads *"Until a carrier is connected…"* today,
  which is wrong for a tenant who has one).
- Boxes gain an optional **carrier packaging template** (phase 7).

### Landing-page editor (`LandingPages.vue`)

No new controls. The element is already addable and already has heading/prompt copy fields; postal code is
not a tenant choice.

---

## 3. The buyer's flow

```
page load
  └─ GET /shipping-quote?clientID&offer&product_id&price_id&quantity
       → { ships, countries[], needs: "country" }                       no carrier call

buyer picks country + types ZIP
  └─ GET /shipping-quote?…&country=US&postal_code=80202[&region=CO]
       → packs the cart                                                 existing packer
       → rule_for(config, "US")
           free      → one option at 0                                  no carrier call
           flat      → one option at the rule's amount                  no carrier call
           flat_rate_box → packed_box_price                             no carrier call
           live      → provider.rates() per parcel, summed              ONE carrier call
                       ∩ services_for(config, "US")
       → mints a quote row (TTL 30 min) keyed by a cart+destination fingerprint
       → { quote_id, options[{service_token, label, amount, estimate}], mode, source }

buyer selects a service
  └─ window.__jbShipQuote / __jbShipService / __jbShipTo

CTA click
  └─ GET /checkout?…&shipping_quote=…&shipping_service=…&ship_to_country=US
       → validates the quote (§4)
       → shipping_options[0] = the stored amount for the chosen service
       → shipping_address_collection[allowed_countries] = ["US"]
       → metadata[shipping_quote_id|shipping_service|shipping_postal_code]

Stripe Hosted Checkout — shows the shipping line, buyer pays once
  └─ webhook checkout.session.completed
       → buyer_paid_shipping(session) as today
       → records the quote id, the service, and the address variance (§5)
```

A buyer who never interacts with the element still checks out: no quote is sent, and `checkout_shipping`'s
existing unanimity path runs exactly as it does now.

---

## 4. API shapes and quote integrity

### `GET /shipping-quote` (public, unchanged route)

New request params: `postal_code`, `region`.

```json
{
  "ships": true,
  "countries": ["US", "CA"],
  "country": "US",
  "postal_code": "80202",
  "quote_id": "shq_01JA…",
  "expires_at": 1759340000,
  "mode": "charged",
  "source": "zone",
  "needs": "",
  "options": [
    {"service_token": "ups_ground_saver", "carrier": "ups",
     "label": "UPS Ground Saver", "amount": 642,
     "estimated_days": 4, "transit_days_min": null, "transit_days_max": null}
  ]
}
```

`needs` keeps its existing vocabulary and gains `postal_code` (a live zone with only a country so far) and
`carrier_error` (the carrier was asked and failed — distinct from "we never asked").

### The quote row — `CARTS_TABLE`, `document_type="shipping_quote"`, TTL `retention_expires_at`

```
quote_id          opaque, 128-bit
tenant_id  mode   written and matched; a test quote can never price a live checkout
offer_id
fingerprint       sha256 of (offer_id, sorted[(product_id, price_id, quantity)],
                            sorted parcel (l,w,h,weight), country, postal_code, region)
destination       {country, postal_code, region}
parcels           [{length,width,height,weight,box_name,template}]
options           [{service_token, carrier, label, amount, currency, estimated_days}]
source            zone | offer_override | offer_options
created_at  expires_at  retention_expires_at
```

**The browser never sends an amount.** It sends `quote_id` + `service_token`; the server reads the amount
off its own row. An amount in the DOM is an amount someone can edit — the element already follows this
rule for service selection, and this extends it to the price.

### Validation at session creation — all must hold

| Check | Failure handling |
| --- | --- |
| Row exists, `tenant_id` and `mode` match | ignore the quote, fall back to `checkout_shipping`, log |
| `offer_id` matches | ignore + fall back + log |
| `fingerprint` matches the cart being checked out | **re-quote** (cart changed under the buyer) |
| `service_token` is one of the row's options | reject the service, use the row's cheapest, log |
| `expires_at` in the future | **re-quote** |
| Chosen amount > 0 or the rule genuinely says free | pass through |

**Re-quote** means one carrier call at session creation using the stored destination, then use the *new*
amount. The buyer still sees the final figure on Stripe's own page before confirming, so a changed price
is disclosed rather than hidden. If the re-quote fails, fall back to `checkout_shipping` and log — never
carry a stale number into a charge.

### Not spending money unnecessarily

- `free` / `flat` / `flat_rate_box` never call a carrier. Only `live` does.
- Repeat quotes for the same fingerprint inside the TTL return the stored row — a buyer toggling between
  services, or reloading, costs nothing.
- A per-IP throttle on `/shipping-quote` follows `purchase_throttles_repository`, scoped to live-rate
  requests only so tiers 1–2 stay free to abuse (they cost a config read).

---

## 5. Stripe Hosted Checkout: what it allows, and the one thing it does not

**Allowed, and already how this codebase works.** Inline `shipping_options[n][shipping_rate_data]` with a
`fixed_amount` we computed — same object a persisted Shipping Rate would be, no Dashboard litter, carries
`tax_code` and `delivery_estimate`. Collected in the same payment. Reported back on the completed session
as `shipping_cost.amount_total`, which `buyer_paid_shipping` already reads. Compatible with wallets.

**Country drift is already closed.** `ship_to_country` narrows
`shipping_address_collection[allowed_countries]` to the quoted country, so a buyer quoted for Canada
cannot pay Canadian postage to a US address.

**The unresolved one: within-country address drift.** Hosted Checkout *prefills* a shipping address from a
Customer object, but there is **no parameter that locks it** — `locked_prefilled_email` has no shipping
equivalent. A buyer quoted for 80202 can type a Beverly Hills address on Stripe's page and we cannot stop
them. This is irreducible without moving to Custom Checkout, which the author has ruled out.

**Chosen resolution — charge the quote, reconcile at fulfillment, never block the sale**
(author's decisions, 2026-10-01):

1. Charge the quoted amount. The buyer agreed to it and it is shown on Stripe's page.
2. On `checkout.session.completed`, store `shipping_quote_id`, `shipping_service`, the quoted amount, the
   **quoted** postal code and the **actual** one from `shipping_details.address`. Both postal codes are
   kept so a variance has an auditable explanation rather than an assertion.
3. At label time the tenant's flow already calls the carrier (`quote_rates`). That answer is written as a
   **separate record**, never over the quote.
4. Badge the order when the actual label cost exceeds the quoted rate by more than the threshold below.
   The tenant absorbs, invoices, or cancels. **Not a fulfillment block** — refusing to ship over $1.40 of
   postage is worse than the problem, and Refunds already exists for genuine disputes.

### The variance threshold

```
threshold = max($2.00, 25% x quoted_rate)
flag when  actual_label_cost - quoted_rate > threshold
```

| Quoted | Threshold | Flags above |
| --- | --- | --- |
| $4.00 | $2.00 | $6.00 |
| $8.00 | $2.00 | $10.00 |
| $12.00 | $3.00 | $15.00 |
| $20.00 | $5.00 | $25.00 |

**One-directional.** A label that costs *less* than quoted is recorded as a saving and flags nothing — a
tenant does not need an alert to tell them they made money.

### The quote is immutable — and *which* record that means

Clarified during phase 4, because the first reading did not survive contact with the cache. The quote row
is keyed by `(tenant, mode, cart, destination)` so it can serve as its own cache — one `get`, no index, no
carrier call for a buyer who reloads or toggles services. A derived key means a refresh writes over it.

So the immutable thing is **the agreement, not the cache row**. What a particular buyer agreed to is
stamped onto the Checkout Session and from there the order: `shipping_quote_id`, `shipping_service`,
`shipping_quoted_amount`, `shipping_postal_code`. That is what survives, and what a variance is measured
against. The cache row is a convenience with a TTL.

Everything that happens afterwards is a separate record pointing at it:

```
shipping_quote    what the buyer was offered and agreed to     written at quote time, never touched
shipping_actual   what the carrier charged for the label       written at label time, references quote_id
```

Three facts stay separately answerable: **what the customer was charged**, **what the carrier charged**,
and **the margin between them**. This is also what finally makes `ledger.shipping_margin` computable —
it returns `None` today precisely because carrier cost was unknown.

A re-quote (expired, or the cart changed) refreshes the cache row and charges the **fresh** price — never
the stale one — and the session records the amount actually transacted on. The buyer still sees the final
figure on Stripe's own page before confirming, so a changed price is disclosed rather than hidden.

### The order badge

Informative, not obstructive — it states the reason, the amounts and the destination discrepancy:

```
Shipping cost variance
  Quoted destination   80202          Actual destination   80205
  Customer charged     $6.42          Actual label cost    $9.10
  Cost variance        +$2.68         Exceeds the $2.00 threshold
  Order can still be fulfilled.
```

Acknowledging it marks the variance **resolved** and hides the badge. The underlying records are never
erased — acknowledgement is a flag on the order, not a delete.

### Service unavailable at label time — a separate exception

If the carrier cannot quote the **originally selected service** for the actual address, that is not a
variance and must not be treated as one:

- The label flow shows the tenant the alternative services available for that address **with their costs**.
- Nothing is silently substituted.
- The original delivery estimate is explicitly marked as no longer applicable — a buyer promised 4 business
  days by UPS Ground Saver has not agreed to whatever else the carrier will carry.

Rejected alternative: create a Stripe Customer per guest carrying the quoted address so Stripe prefills
it. It would cut the mismatch rate materially, but it litters the tenant's account with a Customer per
checkout and changes saved-payment-method semantics. Worth revisiting; not in this build.

### Known limitations — deliberate exclusions, not omissions

Both are distinct checkout paths. Neither is a reason to delay this one, and neither should be read as an
oversight in it.

- **Subscriptions charge no postage.** Payment mode only, unchanged. Recurring shipping needs its own
  design: whether postage recurs per invoice is unverified, the destination or carrier price can move
  between billing cycles, and a subscription's platform fee is a percent rather than an amount.
- **Post-purchase upsells charge no postage.** `handlers/upsell.py` reuses the original session's address
  and charges off-session. An upsell needs its own shipping-cost and fulfillment policy; it must **not**
  be assumed to inherit the original order's postage, which paid for a different parcel.

---

## 6. Carrier flat-rate packaging

`_shippo_parcel` already forwards a `template` to Shippo, so rating carrier packaging works the moment a
box declares one. What is missing is the list: nothing fetches Shippo's parcel templates, so a tenant
cannot pick one.

Phase 7 adds `GET /shipping/parcel-templates` (provider-backed, exact endpoint verified at build time), a
template picker on the box row, and persistence of `template` on the box. Live rating then returns
flat-rate services automatically because the carrier prices the named container.

**A tenant's own carton is never treated as destination-independent.** Only a carrier-supplied template
earns that, and only because the carrier says so.

---

## 7. Files

**New**
- `src/stripe_link/domain/shipping_quotes.py` — quote shape, fingerprint, validation, expiry. Pure.
- `tests/test_shipping_quotes.py`, `tests/test_live_rate_quote.py`,
  `tests/test_checkout_quote_integrity.py`, `tests/test_shipping_address_variance.py`

**Modified**
- `src/stripe_link/domain/shipping_charges.py` — `resolve_options(live_rates=…)`
- `src/handlers/checkout.py` — quote minting + consumption
- `src/stripe_link/runtime/html.py` — the element and its script
- `src/stripe_link/repositories/documents.py` — `shipping_quotes_repository`
- `src/handlers/stripe_webhook.py` — quote + variance persistence
- `src/handlers/shipping.py` — shared carrier-call helper, parcel templates
- `dashboard/src/components/Shipping.vue` — readiness, demoted box prices
- `template.yaml` — `CARTS_TABLE` env + grant on `CheckoutFunction` (it has neither today; KMS and the
  shipping-config read it already has)

## Phases — all built 2026-10-01, dev-only, not yet deployed

1. ✅ **Quote primitive** — `domain/shipping_quotes.py`, repositories, `CartsTable` grant on CheckoutFunction.
2. ✅ **Live rates in `/shipping-quote`** — `domain/shipping_rating.py`, `resolve_options(live_options=)`,
   carrier call, service narrowing, multi-parcel sum, the row as its own cache.
3. ✅ **The element** — postal code + conditional region, rate cards with price and estimate, order total,
   loading/none/invalid/error/retry, and the quote carried to the CTA. Also its first stylesheet.
4. ✅ **Checkout consumption** — `_shipping_from_quote`, validation actions, re-quote, fallback.
5. ✅ **Webhook + label** — `agreed_shipping` on the order, `shipping_actual` at label time,
   `quoted_service_status` on the rate list, variance on the Orders drawer.
6. ✅ **Shipping settings** — live-zone gap warning, honest `live` copy, manual box prices demoted.
7. ✅ **Carrier flat-rate packaging** — `parcel_templates()`, `GET /shipping/parcel-templates`, box picker
   with locked carrier dimensions.

### Throttle — still outstanding

The plan called for a per-IP throttle on `/shipping-quote` once tier 3 spends a carrier call per request.
The quote row's cache absorbs the repeat case (same cart, same destination, inside the TTL costs one
`get`), but a script varying the postal code still reaches a carrier every time. Shippo bills for labels
rather than rates, so this is a rate-limit and latency exposure rather than a billing one — but it should
follow `purchase_throttles_repository` before this goes to prod.

### Not built, deliberately

- Subscriptions and post-purchase upsells still charge no postage (see "Known limitations").
- Multi-parcel LABEL buying still refuses (`handlers/shipping.py`); multi-parcel QUOTING works.
- The variance badge is read-only — acknowledging it is not wired yet, so a flagged order stays flagged.
