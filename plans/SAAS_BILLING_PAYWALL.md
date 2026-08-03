# SaaS Billing Paywall (platform → tenant subscriptions), table-driven

Status: **PLANNED, not built.** Design 2026-08-02. Port + modernize stripe-cart's billing paywall
(`stripe-cart/plans/SAAS_BILLING_PAYWALL_PLAN.md`, `stripe-cart/src/billing.py`, `platform_config.py`) into
stripe-link, but **DynamoDB-table-driven** (editable without deploys) instead of code/app-config-embedded.
Foundational: it's the rail the Identity-verification charging (`plans/IDENTITY_VERIFICATION.md`) and any future
metered feature need. It was in stripe-cart and never made the migration.

## Why / current gap

stripe-link today has only the *shape* of tenant billing: `tier_id` (basic/pro) drives the **transaction fee
RATE** (`fees.py:20`, applied as `application_fee` at `checkout.py:348`), and `billing_status` is a placeholder set
to `"trial"` at registration (`registration.py:40`) that **never transitions**. There is **no Stripe subscription,
no monthly charge, no webhook-driven status**. So tenants aren't actually billed the ~$9/mo. This plan adds the
real platform→tenant subscription.

**Two separate money flows (keep distinct, like stripe-cart Decision #1):**
- **Stripe Connect** = how the TENANT charges THEIR buyers (already built — direct charges + application_fee).
- **Stripe Billing (this plan)** = how Junior Bay charges the TENANT the monthly SaaS fee. Separate Stripe
  customer/subscription on the PLATFORM account. Do NOT conflate "billing mode" (how we bill the merchant) with
  "storefront mode" (test/live for the merchant's own sales).

## Data model

### Plan catalog — a new DynamoDB table (the editable source of truth)

`PlatformPlansTable` — per-mode plan catalog, hand-editable (admin screen later). One item per plan:
- **Key:** `PK = PLATFORM_BILLING#{billing_mode}` (test|live), `SK = PLAN#{plan_key}`.
- **Item shape** (mirrors the tenant's attached JSON):
  ```
  { plan_key, label, tagline, badge, cta_label, product_id, price_id, monthly_amount (cents),
    trial_days, active (bool), highlight (bool), sort_order, features[],
    fee_tier (→ links to the transaction fee-rate tier in global_billing_config, e.g. "basic"),
    exempt (bool, default false) }
  ```
- A tiny config item holds `default_plan_key` + the **bypass list** (`exempt_tenant_ids[]`, `exempt_emails[]`).
- **Per-mode** (`platform_billing_plans_test` / `_live` in stripe-cart) so test plans use test Stripe prices.
- Table declared in `template.yaml` mirroring `CartsTable` (`:3149`) — PAY_PER_REQUEST, SSE; read by the billing +
  webhook + checkout/page-serving functions.

**Loader:** `platform_plans_repository()` (mirror `carts_repository`, `repositories/documents.py:832`) + a cached
`platform_plan(mode, plan_key)` helper (mirror `cached_billing_config`, `fees.py:130`). Manual edits take effect on
the cache TTL. **Document the table name + item shape in the repo** so it's safe to hand-edit (Q2).

### Tenant profile additions (TenantProfile.schema.json + validator)

Reuse existing `tier_id`/`billing_status`; add:
- `billing_plan_key` (which plan), `billing_price_id` (the Stripe Price currently on their sub — so a later catalog
  price change doesn't silently move them), `stripe_customer_id`, `stripe_subscription_id`,
  `billing_exempt` (bool — the comp path for test accounts), `current_period_end` (cache for UI / migrations).
- `billing_status` becomes real: `trial | active | past_due | canceled | suspended` (stripe-cart's canonical set).

## Subscription lifecycle

1. **Choose a plan → subscribe.** A dashboard billing screen lists active plans (from the table). Selecting one
   creates a Stripe **Customer** (platform account, keyed to tenant) + a **Subscription** on that plan's `price_id`
   with `trial_period_days = trial_days`. Simplest: Stripe **Checkout in `subscription` mode** (hosted) → redirect;
   or the API directly. Store `stripe_customer_id` / `stripe_subscription_id` / `billing_plan_key` /
   `billing_price_id` on the tenant.
2. **Manage / upgrade / cancel.** Stripe **Billing Portal** session (hosted) for card updates, plan changes, cancel
   — least code, Stripe-hosted. Upgrades between tiers can also be an API `subscription.update`.
3. **Webhook-driven status** (NOT live reads — stripe-cart Decision #3). New branches in `stripe_webhook.py`
   (routing chain `:219`): `customer.subscription.created|updated|deleted`, `invoice.paid`,
   `invoice.payment_failed` — **for the PLATFORM's own customer** (distinguish from tenant→buyer invoices, which
   already map at `:814`; platform-billing events have no connected `account` and carry our customer/subscription).
   Map → tenant `billing_status` + `current_period_end`. Idempotent via the events table (`:206`/`:281`).
4. **Enforcement.** `assert_billing_in_good_standing` already gates checkout (`checkout.py:91`, 402 on hold); extend
   the same guard to page-serving/publishing so a suspended tenant's pages fail intentionally (stripe-cart Decision
   #4/#5). Exempt/trial/active = allowed; past_due (after grace) / suspended = blocked.

## Exempt / comp path (Q3 — your test accounts)

- A tenant with `billing_exempt: true` (or whose id/email is in the config bypass list) is treated as
  **in-good-standing** and **no Stripe subscription is created** — Stripe never charges them. This is how you run
  your test tenants (multiple emails) without paying.
- Optionally an `exempt` plan_key (`monthly_amount: 0`, `active: false` so it's not publicly selectable) that you
  assign manually. Either mechanism works; the flag is simpler.

## Changing prices later (Q1 — confirmed)

Stripe Prices are **immutable**. To change a tier's price:
1. Create a **new** Stripe Price (e.g. basic → $19) under the same Product.
2. Update the plan item's `price_id` in `PlatformPlansTable`. **New signups get the new price immediately.**
3. **Existing subscribers:** either
   - **grandfather** — leave them on their stored `billing_price_id` until they choose to switch, or
   - **migrate at cycle end** — `subscription.update` the item to the new Price with `proration_behavior='none'`
     (or a Subscription Schedule), so they're not charged mid-cycle and simply renew at the new amount. Notify
     first. A P4 admin action can batch this.
Because each tenant stores their own `billing_price_id`, a catalog edit never silently re-prices anyone — migration
is deliberate.

## Dashboard

- **Billing screen** (`dashboard-vue`): show plans from the catalog, current plan + status + trial/next-renewal
  date, "Subscribe / Manage" → Stripe Checkout(subscription) / Billing Portal. Extends the read-only
  `BillingConnectCardFunction` (`billing.py`) into a real subscribe/manage flow.

## Phasing

- **P1 — Rail:** `PlatformPlansTable` + repo/loader + tenant-profile fields; subscribe flow (Checkout subscription
  mode) + Billing Portal; webhook status branches; extend the good-standing guard to page-serving; **exempt flag +
  bypass list**. Manual table edits (documented shape). ← the foundation.
- **P2 — Dashboard billing screen** (subscribe / manage / show status + renewal).
- **P3 — Admin screen** to CRUD plans in the table (and create the Stripe Product/Price for you, so you never touch
  the Stripe dashboard).
- **P4 — Price-migration tooling** (batch-move existing subs to a new Price at cycle end).

## Open decisions

1. **Plan set + prices** (from your attached config): **basic "Bay Pass" $9/mo, 14-day trial** (active); **pro "Bay
   Pass Pro" $19/mo, 14-day trial** (currently inactive). Confirm these + whether pro launches now or later.
2. **Subscribe UX:** Stripe Checkout(subscription) + Billing Portal (hosted, least code — recommended) vs a fully
   custom in-dashboard flow.
3. **Trial + enforcement grace:** 14-day trial (from config); grace window on `past_due` before `suspended`?
4. **fee_tier link:** does each billing plan map 1:1 to a transaction-fee tier (basic plan → basic fee rate), or are
   they independent? Recommendation: 1:1 via `fee_tier` for coherence.
5. **Does a tenant with no active subscription (never subscribed, trial expired) get blocked, or read-only?**
   stripe-cart blocks page-serving; confirm the exact gate.

## Relationship to other plans

- **Unblocks `plans/IDENTITY_VERIFICATION.md` §6** — verification charging rides this subscription (a metered
  SubscriptionItem or a "verified" plan tier, gated by plan).
- Reuses the existing good-standing guard (`domain/billing_status.py`) + fee-rate tiers (`fees.py`) + the
  table-per-entity + cached-config patterns (`carts_repository`, `cached_billing_config`).
- Source to port/adapt: `stripe-cart/plans/SAAS_BILLING_PAYWALL_PLAN.md`, `stripe-cart/src/billing.py`,
  `stripe-cart/src/platform_config.py` (the embedded catalog we're replacing with a table).
