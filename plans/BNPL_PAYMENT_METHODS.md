# BNPL / Installment payment methods — per-tenant, platform-controlled

**Status:** design proposed 2026-07-31, not built. **HIGH PRIORITY** (author request). Adds Stripe-native
Buy-Now-Pay-Later methods (Klarna, Afterpay/Clearpay, Affirm, Zip) as per-tenant toggles the platform controls,
surfaced on a new/expanded **Payments** settings screen. Klarna leads; Sezzle is explicitly out of scope
(not a Stripe-native payment method — would need a separate non-Stripe integration).

## Goal

Let each tenant offer installment options at checkout, toggled from **our** dashboard (not the merchant's Stripe
dashboard), with the platform deciding which methods are on offer. Klarna is the priority; the other three ship
as additional toggles. Buyers see the method(s) on the hosted Stripe Checkout page; the merchant is paid upfront.

## Why our setup fits (verified 2026-07-31)

- **Charge model = DIRECT charges on Standard OAuth-connected accounts** (`checkout.py create_stripe_checkout_session`
  posts to `/v1/checkout/sessions` with the platform key + `Stripe-Account: acct_…`; platform cut via
  `payment_intent_data[application_fee_amount]`; **no** `transfer_data`/`on_behalf_of`). BNPL is cleanest on
  direct charges — the connected account is merchant-of-record, and application fees coexist with BNPL here.
- **Standard accounts let the PLATFORM request payment-method capabilities via the API** —
  `POST /v1/accounts/{acct} capabilities[klarna_payments][requested]=true`. So our toggle can enable Klarna on the
  tenant's account programmatically; we don't have to send merchants into their own Stripe dashboard.
- **Checkout currently sends NO payment-method list** (`build_checkout_payload` sets no `payment_method_types` /
  `payment_method_configuration` / `automatic_payment_methods`), so today BNPL shows only if a merchant enabled it
  in their own Stripe dashboard. This feature makes it deliberate + platform-controlled.

## The two moving parts

1. **Enable (capability):** toggling a method ON requests the matching capability on the tenant's connected
   account — `klarna_payments` / `afterpay_clearpay_payments` / `affirm_payments` / `zip_payments`. Activation is
   **eligibility-gated + asynchronous**: Stripe returns `active` | `pending` | `inactive` | `unrequested` based on
   the account's country, currency, MCC, and underwriting. The toggle reflects that live status — it is NOT a
   plain local boolean.
2. **Display (checkout):** `build_checkout_payload` emits an explicit `payment_method_types` = `['card']` + each
   enabled BNPL method whose capability is `active` **and** whose supported-currency set contains the checkout
   currency. (Amount-out-of-range → Stripe just doesn't render the method; currency-mismatch with explicit
   `payment_method_types` can error, so we gate on currency.) See "Checkout mechanism" for the pmc alternative.

## Data model — the `stripe_keys` doc (per tenant+mode)

**Implementation refinement (2026-07-31):** stored on the **`stripe_keys` document** (per `(tenant_id, mode)`),
NOT `tenant_config`. Rationale: BNPL capabilities are per **connected account = per mode**, `stripe_keys`
already holds `connect_account_id` per mode, and both checkout handlers already load it — so no new
`tenant_config`-into-checkout plumbing. Same shape either way:

```jsonc
tenant_config.payment_methods = {
  bnpl: {
    klarna:   { enabled: true,  capability_status: "active",  updated_at: 1730000000 },
    afterpay_clearpay: { enabled: false, capability_status: "unrequested" },
    affirm:   { enabled: false, capability_status: "unrequested" },
    zip:      { enabled: false, capability_status: "unrequested" }
  }
}
```

- `enabled` = the tenant's intent (drives the toggle + checkout inclusion).
- `capability_status` = last-known Stripe capability state (cache; refreshed on settings-screen load and/or via a
  Connect `account.updated` webhook later). A method is offered at checkout only when `enabled && status==active`.
- Keyed per `(tenant_id, mode)` like the rest of Stripe config — **test and live capabilities are independent**,
  so the toggles are per-mode.

## Checkout wiring

- `build_checkout_payload` (`checkout.py`) + the cart path (`cart_checkout.py`, which reuses it) must **load
  `tenant_config`** (they don't today — even the existing `checkout.phone_number_collection` setting isn't wired
  in, so this is net-new plumbing) and, when a connected account is present, append the eligible BNPL methods to
  `payment_method_types` alongside `card`.
- **Currency/eligibility gate:** maintain a small per-method support map (supported currencies + rough country
  set) so we only list a method when the checkout currency is supported and the capability is active. Amount
  limits are left to Stripe (it hides an out-of-range method).
- Only applies to **direct-charge** sessions (`bool(stripe_account)`); legacy non-Connect tenants are unaffected.

### Checkout mechanism — v1 vs robust
- **v1 (recommended):** explicit `payment_method_types` gated on active-capability + supported-currency. Minimal
  new objects; works for the common single-currency tenant.
- **Robust upgrade (later):** a per-connected-account **child `payment_method_configuration`** whose display
  preferences mirror the toggles; pass its id on the session. Stripe then evaluates per-transaction eligibility
  itself (no currency/amount edge cases). More Stripe objects to manage; fold in if multi-currency tenants or
  edge-case errors show up.

## Capability request + status flow

- **On toggle ON:** `POST /v1/accounts/{connect_account_id}` (platform key, no `Stripe-Account` header — we edit
  the account object) with `capabilities[{cap}][requested]=true`. Store the returned status.
- **On toggle OFF:** set `requested=false` (or just stop offering it at checkout + set `enabled=false`; requesting
  removal is cleaner). Store status.
- **Status refresh:** on Payments-screen load, `GET /v1/accounts/{acct}` and read `capabilities.{cap}` +
  `requirements` (so we can show "pending — Stripe needs X" if applicable). A Connect `account.updated`/
  `capability.updated` webhook is the eventual push-based refresh (P3); polling-on-load is enough for v1.
- Reuse the existing raw-HTTP Stripe client (`stripe_client.py stripe_request`, platform key) — no SDK.

## Eligibility (approximate — verify against Stripe at build time; methods/countries evolve)

| Method | Countries (connected account) | Currencies | Amount (approx) |
|---|---|---|---|
| **Klarna** | US, UK, most of EU (AT/BE/CZ/DK/FI/FR/DE/GR/IE/IT/NL/NO/PL/PT/ES/SE/CH), CA, AU, NZ | USD, GBP, EUR, DKK, NOK, SEK, CHF, PLN, CZK, CAD, AUD, NZD | ~$10 min, varies by buyer |
| **Afterpay/Clearpay** | US, CA, UK, AU, NZ, FR, IT, ES | USD, CAD, GBP, AUD, NZD, EUR | ~$1–$4k, region-varying |
| **Affirm** | **US, CA only** | USD, CAD | $50–$30,000 |
| **Zip** | **US, AU only** | USD, AUD | varies |

Eligibility is the connected account's country + the checkout currency + the buyer's location. A tenant outside a
method's country can still *see* the toggle but it stays disabled with a "not available in your country" note.

**Determining eligibility (author 2026-07-31):** we already capture the tenant's location at onboarding, and the
Stripe connected-account object carries its `country` — so we can pre-compute per-method eligibility + the
default currency for a tenant *before* they toggle, driving which toggles are enabled and the currency gate on
`payment_method_types`. Stripe's returned `capability_status` remains the source of truth for whether it's
actually live; the location data just lets the UI show the right enabled/disabled state up front.

## Dashboard — the new **Payments** screen (also fixes "Connect is invisible after setup")

Author pain point: once Stripe Connect is linked it's "set once, never seen again." Turn today's **Stripe Keys**
screen into a **Payments** settings home (rename the menu item, or add a "Payments" section) that always shows:
1. **Connect status** — connected account id (test/live), connected/needs-attention, reconnect/deauthorize — so
   the merchant can always see + manage the link (surfaces what `StripeKeys.vue` already has, made prominent).
2. **Installments (BNPL)** — a toggle per method (Klarna first), each showing live capability status:
   - **Active** — green; offered at checkout.
   - **Pending review** — Stripe is underwriting; shown but not yet live.
   - **Not available in your country** — disabled toggle + an **info icon** popping the eligible-country list.
   - **Action needed** — Stripe `requirements` outstanding; link to resolve.
3. Copy explaining "buyers pay in installments; you're paid in full upfront; a platform fee still applies."

Storage/API: a `PUT /tenant-config` (or a focused `/payment-methods` endpoint) persists `payment_methods.bnpl`
and triggers the capability request; a `GET` returns toggles + refreshed capability status for the screen.

## Constraints & caveats to honor

- **Test vs live** capabilities are independent (per-mode config; toggles per mode).
- **Async activation** — a just-toggled method may be `pending`; the UI must not imply it's live yet.
- **Currency/amount/country** gating (above) — don't blindly list a method in `payment_method_types`.
- **Application fee** stays on the base subtotal; BNPL doesn't change our fee model (direct charge, unchanged).
- **Fulfillment unaffected** — BNPL settles like a card to the connected account; the webhook order flow is
  unchanged (the payment method is just Klarna/etc. instead of card).
- **Subscriptions:** BNPL (except Klarna in some cases) doesn't support recurring — gate BNPL to `mode=payment`
  (one-time) checkouts; skip for `mode=subscription`.
- **Sezzle:** out — not a Stripe payment method.

## Phased plan

- **P1 — Klarna, end to end (highest value):**
  - `tenant_config.payment_methods.bnpl` schema + `validate_tenant_config`.
  - Capability request/read helpers (`stripe_request` against `/v1/accounts/{acct}`), status mapping.
  - `PUT`/`GET` payment-methods endpoint (persist toggle + request capability + return status).
  - `build_checkout_payload` loads tenant_config, appends `klarna` to `payment_method_types` when active +
    currency-eligible (payment mode only); cart path inherits it.
  - **Payments screen**: Connect status made prominent + a Klarna toggle with live status + not-available/info-icon.
  - Tests: capability request payload, status gating, checkout payload includes/excludes klarna correctly,
    currency/mode gates, cart parity.
- **P2 — Afterpay/Clearpay, Affirm, Zip:** same plumbing, add the three toggles + their capability names + the
  eligibility map + info-icon country lists. Mostly config/UI once P1's machinery exists.
- **P3 — Robustness:** Connect `account.updated`/`capability.updated` webhook to push capability-status changes
  (drop polling reliance); optional per-account child `payment_method_configuration` for multi-currency
  eligibility; `requirements`-driven "action needed" deep-links.

## Decisions (author-locked 2026-07-31)

1. **Menu:** rename "Stripe Keys" → **"Payments"** (one home for Connect + BNPL). ✓
2. **Checkout mechanism:** explicit **`payment_method_types`** (v1); `payment_method_configuration` deferred to
   P3 if multi-currency edge cases appear. (Buyer still chooses their method on Stripe's page either way.) ✓
3. **Toggle-off:** fully **revoke** the capability (`requested=false`) on off. ✓

## Post-BNPL follow-up (look into later — not now)

- **Consolidate the side menu.** It has grown cluttered and lost its original simplicity; group items into
  collapsible sections. Revisit AFTER BNPL ships — the right grouping will be clearer then. (Tracked in
  plans/TODO.md → Dashboard / UX.)

## Ties
`src/handlers/checkout.py` + `cart_checkout.py` (payload build), `src/handlers/stripe_connect.py` (connected
account id), `src/stripe_link/stripe_client.py` (raw Stripe HTTP), `src/stripe_link/domain/documents.py`
(`validate_tenant_config`), `dashboard-vue/src/components/StripeKeys.vue` (→ Payments screen). Stripe docs:
[Account capabilities](https://docs.stripe.com/connect/account-capabilities),
[Connect payment methods](https://docs.stripe.com/connect/payment-methods),
[Payment method configurations](https://docs.stripe.com/connect/payment-method-configurations),
[Klarna](https://docs.stripe.com/payments/klarna).
