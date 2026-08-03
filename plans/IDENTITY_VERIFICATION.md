# Age / Identity Verification Gate (Stripe Identity)

Status: **PLANNED, not built.** Design + charging model drafted 2026-08-02. Awaiting greenlight + a decision on
the charging model (see §6).

## Goal & strategic framing

Let a tenant mark certain products/offers as **age- or identity-restricted**, so a buyer must pass a
**Stripe Identity** check (scan a government ID + selfie) before they can check out. The platform bills the
tenant for each verification. This is a **differentiating platform feature** — most Stripe merchants don't know
Stripe Identity exists — that unlocks age-restricted verticals (alcohol, vaping, CBD, 18+/21+ goods, firearms
accessories, etc.). Our current tenants sell supplements (not age-gated), so this is **plan-now, build-when a
tenant needs it** — but the design is cheap to hold and the charging rail (§6, Phase 2) benefits other features.

## What Stripe Identity gives us (verified 2026-08-02)

- **Product:** Stripe Identity (GA since 2021). A `VerificationSession` guides the buyer through document + selfie
  capture (or an id_number/SSN lookup) and returns a pass/fail plus verified data.
- **Runs on the PLATFORM account**, not the connected account. This is *buyer* verification, distinct from
  Connect's *connected-account* KYC — so the tenant's Stripe account is never involved in the call. Use
  `get_platform_secret_key(mode)` with **no `Stripe-Account` header** (`stripe_platform_secrets.py:70`).
- **Check types:** `document` (+ optional `selfie`) — the ID-scan flow; or `id_number` (US SSN → name/DOB).
- **Age data:** `verified_outputs.dob` (also `first_name`, `last_name`, `address`, `id_number`). Compute age from
  `dob`. **GOTCHA: reading `dob` requires a RESTRICTED API key** (Stripe gates that PII) — a standard secret key
  can't read it. We must provision a restricted key scoped to Identity verified-outputs and store it alongside the
  platform secret. (Alternative if we want to avoid holding DOB at all: read only the pass/fail + a boolean age
  result — but the boolean still derives from `dob`, so the restricted key is required either way.)
- **Buyer UX:** a hosted redirect URL (single-use, expires 48h) OR an embedded modal via
  `stripe.verifyIdentity(client_secret)` in Stripe.js. Modal keeps the buyer on our page — preferred.
- **Webhooks:** `identity.verification_session.verified` / `.requires_input` / `.processing` / `.canceled`.
- **Pricing (platform cost):** **$1.50** per document+selfie verification, **$0.50** per id_number lookup
  (US SSN only). **No monthly minimum**, strictly per-verification.

## Data model

**Offer/product flag** (opt-in per product or per offer):
- `Offer.schema.json` `eligibility` object (`:332`, already holds `requires_prior_purchase`/`starts_at`) gains
  `requires_identity_verification: bool` + `minimum_age: int` (0 = identity only, no age floor). Validated in
  `documents.py` `validate_offer_document` (`:862`) — must NOT be classed UI-only (`OFFER_UI_ONLY_FIELDS :864`).
- Optionally mirror on `Product.schema.json` (`:22`) for catalog-level defaults (`validate_product_document :634`).
  Offer-level is the enforcement point; product-level is a convenience default.

**Verification record** — a new table-per-entity, mirroring the `cart` / `cart_token` opaque-token precedent
(`domain/cart.py:47`, `repositories/documents.py:832`, `template.yaml CartsTable :3149` with TTL on
`retention_expires_at`):
- `{document_type:"identity_verification", tenant_id, buyer_token, buyer_email?, offer_id,
  stripe_verification_session_id, status (requires_input|processing|verified|canceled), min_age, verified_age?,
  verified_at, retention_expires_at}`.
- `buyer_token` is an opaque handle the page holds (like `cart_token`) so a returning buyer's PASSED status is
  reused without re-verifying — and without re-charging (see §6). Cache window TBD (e.g. 12 months).
- New `verification_sessions_repository()` (~5 lines, mirror `carts_repository :832`); can share a table with the
  cart store via `document_type`, or get its own `VerificationsTable`. Own table is cleaner here.

## End-to-end flow

1. **Buyer clicks Buy Now / cart Checkout** on a gated offer. The checkout handler (single: `checkout.py:42`;
   cart: `cart_checkout.py:31`), **after the billing + publish guards and after the offer is loaded**
   (`checkout.py:117` / `cart_checkout.py:97`, before building the payload `:153`/`:132`), checks the offer's
   `eligibility.requires_identity_verification`.
2. If required AND the buyer has no cached PASSED verification (by `buyer_token`), **return a 403 with
   `code="verification_required"`** — mirror the publish-guard's dual HTML/JSON shape (`checkout.py:96`-`:115`),
   including a freshly created VerificationSession `client_secret` (+ session id) in the body.
   - Create the session on the platform key: `POST /v1/identity/verification_sessions` with
     `type=document`, `options[document][require_matching_selfie]=true`,
     `metadata[tenant_id]`, `metadata[offer_id]`, `metadata[buyer_token]` (so the webhook can resolve the tenant —
     platform events have no `account`, so tenant comes from `metadata`, `stripe_webhook.py:121`). Use the `urllib`
     POST pattern of `create_stripe_checkout_session` (`checkout.py:424`) with NO `Stripe-Account` header.
3. **Client launches the Identity modal.** The cart island's checkout `fetch` already reads the JSON body on a
   non-2xx and surfaces `d.message` (`html.py:4837`-`:4846`) — branch there: on `verification_required`, call
   `stripe.verifyIdentity(client_secret)` (load Stripe.js) instead of showing an error. The single-offer Buy CTA
   (`render_buy_cta :4219`, `checkout_context :4346`) intercepts the click similarly.
4. Buyer completes the ID scan in the modal. Stripe fires `identity.verification_session.verified`.
5. **Webhook** (`stripe_webhook.py`, new branch in the routing chain `:219`-`:279`): resolve tenant via
   `metadata.tenant_id` (`_metadata_tenant_id :121`), retrieve the session with the **restricted key** expanding
   `verified_outputs`, compute age from `dob`, and write/patch the verification record `status=verified`
   (+ `verified_age`). Idempotent via the events table (`:206`/`:281`). If `minimum_age` isn't met → record a
   FAILED/under-age result (do not pass).
6. **Client retries checkout** (poll the record or re-submit) — the gate now finds a cached PASSED record and
   proceeds to build the Stripe Checkout Session as normal.
7. On the resulting **paid order**, the platform collects the verification fee via the order's application_fee
   (see §6, Phase 1).

## Client-side integration

- Load Stripe.js (already used for the BNPL messaging element) and call `stripe.verifyIdentity(client_secret)`.
- Insertion points: the cart-island checkout handler (`html.py:4837`-`:4846`) and the single-offer Buy CTA click
  (`html.py:4219`). Both already have a redirect/`fetch`→`window.location` precedent and a themed notice
  (`slNotice`) for messaging.
- Keep it fail-safe (try/catch) like the BNPL init — a Stripe.js hiccup must not brick the page.

## §6 — Charging tenants (THE key decision)

**Industry models** (Regula / Shufti / ComplyCube): pay-per-verification (pass-through + markup), prepaid credits,
plan-tier bundling, volume/enterprise. Best practice = **pass-through-with-markup + governance (per-tenant caps)**.
Unique-to-checkout question: **who eats a verification that doesn't convert** (buyer verifies, then abandons)?

### What our tenant-billing actually is today (CORRECTED)

Tenants are on **paid tiers** (`tier_id` on TenantProfile — `basic`, `pro`; product model ~\$9/mo for basic). In
the **code**, a tier currently drives only the **transaction fee RATE** (basic 10% / pro 5% on sales, via
`application_fee` — `fees.py:20`, `checkout.py:348`), plus:
- `tier_id` + `billing_status` fields (`billing_status` is set to `"trial"` at registration `registration.py:40`
  / `auth.py:112` and **never transitions** in code),
- a read-only billing card endpoint (`billing.py connect_card_handler`),
- a `TierPoliciesTable` (per-tier feature/policy gating).

**No code in this repo creates a Stripe subscription or collects the monthly tier fee** — no
`customer.subscription.*` handling, no platform-price/subscription-create, no `billing_status` → active/past_due
transition. So the monthly tier CHARGE is **external to this repo or not yet wired here.** ← must confirm (Open #7).
The `invoice.paid`/`invoice.payment_failed` webhook events (`stripe_webhook.py:814`) are the tenant's OWN
tenant→buyer invoices, not platform→tenant.

**Implication:** the right home for a verification charge is the **tenant tier / subscription** (the tenant's
suggestion), NOT the buyer's application_fee. That's cleaner (the tenant pays for their own traffic, converting or
not) and avoids the "who eats a non-converting verification" problem — the tenant does, because it's their gate.

### Recommendation — ride the tier/subscription model

**Preferred: metered per-verification on the tenant's subscription, gated by tier.**
- **Feature-gate by tier:** verification is a **paid capability** — only tenants on a tier that includes it (e.g. a
  new **`verified`/`plus` tier**, or `pro`+) may flip a product's `requires_identity_verification` on. Enforced via
  the existing tier machinery (`normalize_tier_id`, `TierPoliciesTable`).
- **Meter each verification** and bill it on the tenant's platform subscription: a metered Stripe **SubscriptionItem**
  (usage-based price, e.g. \$2.50/verification after an included monthly allowance) added to the tenant's
  platform-billing subscription. Pass-through of Stripe's \$1.50 + margin. Allowance (e.g. 25/mo included in the
  tier) absorbs light users; overage covers heavy ones — so the flat tier never loses money on a high-volume tenant.
- **Governance:** per-tenant **daily/monthly cap** so a bad actor spamming the modal can't run up cost; soft-fail
  past the cap.
- **Prereq:** this needs the **platform→tenant subscription to actually exist as Stripe Billing** (tenant = customer
  of the platform). If tier billing is currently external/manual, that rail is the real first build — and it's a
  **broadly reusable investment** (it also lets us bill other metered features, enforce past_due/suspended for real,
  etc.), not verification-specific.

**Simplest first cut (the tenant's "special tier" idea): a flat verification-enabled tier / add-on.**
- A dedicated tier (or monthly add-on) that INCLUDES verification with a generous allowance; overage billed or a
  higher tier for volume. Rides tier selection with no metering code — but a flat tier alone doesn't track cost, so
  it MUST carry an allowance + overage/upgrade path or a heavy tenant costs the platform \$1.50 × volume.
- Good MVP **if** the tenant subscription is a real Stripe subscription we can price; otherwise it's still gated by
  the same "build the subscription rail" prerequisite.

**Fallback if we must ship before the subscription rail exists:** collect the verification fee on the **converting
order's application_fee** (add \$2.50–3.00 to `application_fee_amount`, `checkout.py:357`) — no new rail, tenant nets
it out of the gated sale, platform absorbs non-converting verifications in the markup. Weaker (doesn't bill
non-converting traffic, and mixes a subscription-shaped cost into a per-transaction take) — a stopgap, not the goal.

## Phasing (build order)

- **P1 — Gate + verify + pass:** Offer flag + validator; checkout gate (403 `verification_required`); platform
  VerificationSession create; restricted-key retrieval + webhook `verified` handler; verification record table +
  repo; client modal + retry. (No charging yet — verification is free to tenants in P1a to de-risk the flow.)
- **P2 — Charge (Phase-1 model):** verification fee in GlobalBillingConfig; add to the converting order's
  application_fee; `fee_collected` bookkeeping; per-tenant daily cap.
- **P3 — Dashboard:** per-product/offer toggle + min-age in the builder; a verifications log/usage view;
  surface the fee to tenants.
- **P4 (deferred) — Proper metered billing rail** (Phase-2 charging), if volume warrants.

## Open decisions (need answers before building)

0. **← RESOLVED / now BLOCKED ON A PREREQ:** the platform→tenant subscription is NOT built in stripe-link (it exists
   in stripe-cart, never ported). So verification charging is blocked on **`plans/SAAS_BILLING_PAYWALL.md`** (port
   the SaaS billing paywall, table-driven). Build that rail first; verification then rides it as a metered
   SubscriptionItem or a "verified" plan tier.
1. **Charging model:** metered-per-verification-on-subscription (preferred) vs a flat verification-enabled tier
   vs the application_fee stopgap. Recommendation: meter on the subscription, gated by tier + allowance/overage.
2. **Verification fee + allowance:** e.g. ~$2.50/verification, N included per tier/month, overage billed.
3. **Re-verification cache window** (a passed buyer skips re-verifying): e.g. 6–12 months.
4. **Modal vs hosted redirect.** Recommendation: embedded modal (stays on-page).
5. **DOB handling / restricted key:** provision a restricted Identity key; store `verified_age` only, never raw DOB.
6. **Priority:** hold the design vs build now (no gated tenants yet) vs ship P1a (feature, no charge) as a
   differentiator. Recommendation: hold, or build P1a free, until an age-restricted tenant onboards.

## Relationship to other plans

- Charging Phase-2 overlaps a general **platform→tenant billing rail** that would also serve BNPL-messaging fees,
  usage-metered features, etc. — worth designing once, broadly.
- Reuses the `cart`/`cart_token` opaque-token + table-per-entity pattern (`plans/LISTICLE_AND_CART.md` Slice D).
- The buyer-facing gate mirrors the existing billing-paywall + publish-guard checkout blocks.
