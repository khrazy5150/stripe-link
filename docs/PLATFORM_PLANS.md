# PLATFORM_PLANS — managing the SaaS subscription plans

How to add, modify, or remove the plans tenants can subscribe to (the platform → tenant Stripe Billing
subscription, e.g. **Premium $19/mo**). Plans are **table data, not code** — the Billing screen, checkout,
and the entitlement/fee wiring all read the table. Edits take effect within the **~5-minute cache TTL**,
no deploy.

> Related: `plans/SAAS_BILLING_PAYWALL.md` (the rail's design), `plans/TODO.md` "Pricing pivot" (free-forever
> model), `docs/APP_CONFIG.md` (the equivalent runbook for URLs/legal identity).

## Where plans live

| Environment | Table | Partition key |
|---|---|---|
| dev / sandbox | `jb-platform-plans-dev` | `PK = PLATFORM_BILLING#test` |
| prod / app | `jb-platform-plans-prod` | `PK = PLATFORM_BILLING#live` |

The PK is the platform's **billing mode** (`PlatformBillingMode` stack param: dev=test, prod=live), so test
plans reference test-mode Stripe prices and live plans reference live-mode prices. Item types under that PK:

- `SK = PLAN#{plan_key}` — one item per plan (the editable source of truth).
- `SK = CONFIG` — singleton: `default_plan_key`, `exempt_emails`, `exempt_tenant_ids` (comped accounts).
- `SK = PROMO#{CODE}` — promo codes (e.g. `PROMO#TRIAL14` grants a trial override).

## Plan item — every field

```json
{
  "PK": "PLATFORM_BILLING#live",      // env's billing mode (see table above)
  "SK": "PLAN#premium",                // PLAN#{plan_key}
  "plan_key": "premium",               // stable id; also stamped on the Stripe subscription metadata
  "label": "Premium",                  // what the Billing screen shows
  "billing_mode": "live",              // mirrors the PK mode
  "monthly_amount": 1900,              // display price in CENTS ($19.00) — display only, see price_id
  "price_id": "price_...",             // the Stripe Price actually charged (MUST match monthly_amount!)
  "product_id": "prod_...",            // the Stripe Product the price belongs to (bookkeeping)
  "trial_days": 0,                     // Stripe-side trial on subscribe; 0 = platform trial only (promo codes
                                       //   can override — see PROMO items)
  "active": true,                      // false hides the plan from the Billing screen (soft retire)
  "sort_order": 1,                     // display order when multiple plans exist
  "highlight": true,                   // visually emphasized plan card
  "features": [],                      // optional display-only bullet strings for the plan card
  "fee_tier": "pro",                   // ⭐ the TRANSACTION-FEE tier this plan grants (see below)
  "entitlements": { "...": true }      // ⭐ the FEATURES this plan unlocks (see below)
}
```

### `fee_tier` — what transaction fee subscribers pay

On subscribe, the billing webhook writes this value onto the tenant as `tier_id`; checkout reads it live
(`fees.build_fee_context`) to compute the application fee. Valid tiers come from the fee table
(`fees.py DEFAULT_GLOBAL_BILLING_CONFIG` / S3 `global_billing_config.json` — see `docs/APP_CONFIG.md`):

| tier | physical | service | digital | tip_jar |
|---|---:|---:|---:|---:|
| `basic` (free tier) | 5% | 6% | 7% | 5% |
| `pro` (premium) | 2% | 2% | 2% | 0% |

On cancellation (`customer.subscription.deleted`, fired at period end), `tier_id` reverts to `basic`
automatically — the tenant keeps premium fees until their paid-through date.

### `entitlements` — what features this plan unlocks

A map of capability → `true`/`false`. The full capability list lives in code
(`src/stripe_link/domain/entitlements.py CAPABILITIES`); as of 2026-08-27 the 10 keys are:

| key | screen | free-forever floor? |
|---|---|---|
| `landing_pages` | Landing Pages | ✅ always free |
| `sites` | Sites | ✅ always free |
| `collections` | Collections | ✅ always free |
| `booking` | Services / Booking | premium |
| `ab_testing` | A/B Testing | premium |
| `reviews` | Reviews | premium |
| `lead_capture` | Leads | premium |
| `invoicing` | Invoices | premium |
| `custom_domains` | (inside Configuration) | premium |
| `bnpl` | (toggle on Payments) | premium |

Notes:
- **The free floor is code, not table data**: every non-suspended tenant always has
  `landing_pages + sites + collections` (`entitlements.py FREE_TIER_CAPABILITIES`) — a canceled/expired
  tenant reverts to that floor, never to nothing. Changing the floor is a deploy (deliberately rare).
- Entitlements gate **dashboard management only**. Public serving (published pages, checkout, public
  booking, lead-form ingest) is NEVER gated — a downgraded store keeps selling at the free-tier fee.
- On subscribe, the plan's enabled capabilities are **denormalized onto the tenant profile**
  (`tenant.entitlements`) by the platform-billing webhook. Editing a plan's entitlements affects **new**
  subscribe/webhook events; already-subscribed tenants pick the change up on their next subscription
  webhook (or need a manual resync — a known follow-up in `plans/TODO.md`).
- Adding a brand-new capability (e.g. a future "trends" tool) = add the key to `CAPABILITIES` in code,
  gate its handler with `entitlement_gate.require_capability`, then flip it in plan rows here.

## How to ADD a plan

1. **Create the Stripe Price** (platform account, correct mode). Prices are immutable — always a new Price:
   ```bash
   curl https://api.stripe.com/v1/prices -u "$SK:" \
     -d unit_amount=1900 -d currency=usd -d "recurring[interval]=month" \
     -d "product_data[name]=Junior Bay Premium"
   ```
   Use `sk_test` for the dev table, `sk_live` for prod (both live in the Secrets Manager platform secret,
   `stripe-cart/{env}/platform/stripe`). Note the returned `price_...` and `prod_...` ids.
2. **Put the plan item** into the right table/PK with the fields above (`aws dynamodb put-item`, or the
   console). Set `monthly_amount` to match the Price amount.
3. Optionally point `CONFIG.default_plan_key` at it.
4. Wait ≤5 min (cache TTL) → it appears on the Billing screen. Verify with a test subscribe in sandbox.

## How to MODIFY a plan

- **Label / features / sort_order / highlight / entitlements / fee_tier**: edit the item in place. Display
  fields apply within the TTL; entitlements/fee_tier apply to tenants on their next subscription webhook.
- **Price change**: you canNOT edit a Stripe Price. Create a NEW Price (step 1 above), update `price_id` +
  `monthly_amount` on the plan item. **Existing subscribers keep renewing at their old locked-in Price**
  until migrated (the price-migration batch tool is a deferred TODO) — new subscribers get the new price.

## How to REMOVE a plan

- Prefer a **soft retire**: set `active: false` (hides it from the Billing screen; existing subscribers are
  untouched and keep renewing).
- Hard delete (`aws dynamodb delete-item` on the `PLAN#{key}` item) only when **no tenant references it**
  (`tenant.billing_plan_key`) — check `jb-tenant-profiles-{env}` for subscribers first. If it was the
  `default_plan_key`, point CONFIG at a remaining plan.
- Optionally archive the Stripe Price/Product in the Stripe dashboard (cosmetic; nothing breaks either way).

## History

- **2026-08-27**: retired `PLAN#basic` "Bay Pass" ($9.58/mo, fee_tier basic) in both envs (0 subscribers) and
  replaced it with `PLAN#premium` "Premium" ($19/mo, `fee_tier: pro`, all 10 entitlements) —
  test `price_1U97GkEcxlWjis9iT6HnMxWb` / live `price_1U97GkEcxlWjis9ieWDXeFEX`. Part of the free-forever
  pricing pivot (`plans/TODO.md`).
