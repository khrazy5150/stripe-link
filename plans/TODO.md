# TODO

Deferred, non-blocking follow-ups. Each item notes what, why it was deferred, and where to fix it.

## Services / Booking

### Decouple Booking from Service (Booking = its own primitive)
- **What:** `Appointment` is 1:1 with a service today. Make a **Booking** its own primitive — a scheduled
  visit covering **one or more** service line items — and let a Service declare `fulfillment_mode`
  (`scheduled` | `no_booking`). The **Offer** coordinates delivery (`service_booking_mode`:
  `single_visit` | `separate_visits`). Full design in **`plans/BOOKING_AS_PRIMITIVE.md`**.
- **Deferred sub-phases that must not fall through:**
  - **Multi-fulfiller single visit (multi-resource scheduling)** — different delegates performing
    different services in the *same* visit (find a slot where all required fulfillers are free). v1
    restricts a combined booking to **one fulfiller / unassigned**; this is its own non-trivial phase.
  - **Per-item `booking_group` on offers** — mixed offers where some services share a visit and others
    are separate (beyond the offer-wide `single_visit`/`separate_visits` switch).
  - **Service tax categories** — `no_booking` services stay *services* for fiscal/tax reasons (differ
    from products); per-service tax classification pairs with the commerce tax/fee work.
- **Why deferred:** design locked 2026-07-08, no code yet; awaiting greenlight to start Phase 1
  (Booking.services[] + read adapter + Service.fulfillment_mode, no behavior change).

### Consider adding a wizard for the services page
- Idea only — not planned yet. The Create Service flow is dense; a guided wizard (Basics → Pricing
  → "fulfill yourself or delegate?" → conditional staff/calendar/check-in steps) could simplify it
  for tenants. Monitoring whether it's worth building; revisit later.

### Re-snapshot compensation on admin reassign
- **What:** When an admin reassigns an appointment to a different fulfiller via the lifecycle
  `assign` action, the appointment's `rule_snapshot` (frozen compensation) is **not** recomputed, so
  payout reporting could use the *previous* fulfiller's comp.
- **Current behavior (correct for the common path):** the **customer booking** flow snapshots comp at
  reserve time — `reserve_route` in `src/handlers/booking.py` calls
  `compensation_snapshot(service, fulfiller)` (`src/stripe_link/domain/booking.py`) and stores it on
  `appointment.rule_snapshot`. Only the *manual admin reassign* path is missing the re-snapshot.
- **Where to fix:** the `assign` action in `appointment_action_route`
  (`src/handlers/services.py`). It currently only sets `assigned_fulfiller_id` via
  `transition_appointment(..., "assign", ...)`. To re-freeze comp it must load the service and the new
  fulfiller and recompute `rule_snapshot = compensation_snapshot(service, fulfiller)` — which means
  giving that handler access to the services + fulfillers repos (it currently only has the appointments
  repo). Keep the domain `transition_appointment` pure; compute the snapshot in the handler and merge
  it into the saved document.
- **Why deferred:** manual reassignment is an edge case; the primary booking path is correct. Introduced
  in Phase B.5.

## Platform architecture

### ⭐⭐ Decouple Stripe mode (test/live) from platform environment (dev/prod) — SHIPPED + CUT OVER PROD 2026-08-02
- **What it did:** the dashboard test/live toggle used to swap the WHOLE backend (test→dev, live→prod), so a tenant's
  Stripe-**test** sandbox structurally WAS the dev backend. Now: hostname→backend (app=prod, sandbox=dev, dev = pure
  staging) + a per-tenant **Stripe-mode toggle within prod** — a tenant's test/"sandbox" mode runs on the production
  platform with test Stripe keys. Full plan + per-phase detail in **`plans/STRIPE_MODE_DECOUPLING.md`**.
- **DONE (P0–P6), merged to `main`, deployed, and CUT OVER in prod 2026-08-02** (commit `774aaa3`; verified by a
  Stripe-**test** purchase completing on the **prod** backend at `app.juniorbay.com`; test-mode data now lives on the
  prod tables, e.g. `OFFER#test#…`/`PAGE#test#…`):
  - P0 request helper + dashboard scaffolding · P0.5 stripe-keys → one per-deployment table keyed `(tenant, mode)` ·
    P1 hostname→backend + Stripe mode as `?mode=`/`X-Stripe-Mode` · P2 **mode-in-key** data model (`{TYPE}#{mode}#{id}`,
    so test/live copies coexist) across all tenant entities · P3 webhook mode-from-`livemode` · P4 host-agnostic
    checkout + Buy-URL `?mode=` · P5 mode-partitioned artifact paths (`test/` prefix) + forced `noindex` · P6 cutover
    (script run dev→prod, webhooks repointed with per-mode secrets, Connect OAuth re-run per mode). **1335 tests.**
- **Unblocked** the clean onboarding streamline; **superseded** the earlier mode-follows-environment fix.
- **Serve-host slice** (2026-08-19, `plans/SERVE_HOST_SCHEME.md`): the `{stage}-{mode}.juniorbay.com` hosts;
  `TEST_PAGES_HOST` + preview base de-hardcoded into `app_config`; `preview.juniorbay.com`/`test.juniorbay.com`
  retired — the config-driven serving layer on top of P5's artifact-path partitioning.

### Streamline Connect onboarding — live-first + opt-in Stripe-test sandbox — SHIPPED (code) 2026-08-02
- **What:** default new tenants to LIVE; the wizard onboards their live Stripe only (with expanded `stripe_user[]`
  prefill). A Payments-screen button "Set up a sandbox for your funnels" triggers the **Stripe-test** onboarding on
  demand, then reveals the top test/live toggle. Distinct TEST Connect branding (a no-code Stripe-dashboard setting).
  Eliminates the confusing double-onboarding for tenants who never need test, while preserving the sandbox for those
  who do. Author's chosen model (#4). Built on the Stripe-mode decoupling (sandbox = Stripe-test-on-prod).
- **Built:**
  - Default-to-live was already in place (`getStripeMode()` → `"live"`, api/client.js).
  - **Toggle gating:** the top test/live pill+button (App.vue) is hidden until the tenant has a test sandbox
    (`stripeKeys.hasTestSandbox` getter — test connected or test keys saved); a stale stored `"test"` mode is coerced
    to live on load so nobody is stranded in a hidden mode; `modes` is repopulated on every mode switch so the toggle
    can't vanish mid-use.
  - **"Set up a sandbox for your funnels"** card on the Payments screen (`StripeKeys.vue`, shown only when no test
    sandbox) — persists test mode then starts a test-mode Connect OAuth; on return the toggle is revealed in test mode.
  - **Expanded `stripe_user[]` prefill** (`stripe_connect.py` `_stripe_user_prefill`): email + business_name +
    first/last name + phone_number from the tenant profile.
  - **TEST Connect branding** steps documented in `docs/CONNECT_TEST_BRANDING.md` (no-code; author action).
- **Follow-ups (not built):** prefill business `url`/`country` once a canonical Business Profile exists (today the
  `business` identity on user_profile is Stripe-seeded and often empty pre-connect); optional auto-switch-to-test UX
  polish after sandbox setup.

### Branded Connect onboarding intro (Standard-account UX polish) — SHIPPED PROD 2026-08-27
- **Context:** onboarding redirects straight to Stripe's **OAuth** flow (Standard accounts), which feels intimidating
  vs Stan's branded intro + hosted/embedded flow. **Staying on Standard** — Express was rejected **NOT for fees**
  (`application_fee` works identically on Standard/Express/Custom) but because Standard keeps dispute / negative-balance
  **liability with the merchant** and avoids a go-forward account migration. Standard **cannot embed** onboarding, so
  the realistic win is a friendly wrapper around the OAuth redirect (Plan A).
- **Plan A (what to build):**
  - **Branded intro/interstitial page** in the dashboard before the redirect: "Set up payments — Junior Bay partners
    with Stripe," what to have ready (gov-ID + bank details), a reassuring "you'll finish securely on Stripe and come
    right back," home-country context, clear CTA. Removes most of the "leaving to a scary form" feeling.
  - **Maximize `stripe_user[]` prefill** (extend `stripe_connect.py` `_stripe_user_prefill`): add business `url` /
    `country` / address / MCC once a canonical Business Profile exists (already a follow-up on the streamline item
    above) so the Stripe form arrives pre-filled and fast.
  - **Platform Connect branding** (no-code Stripe setting): logo + brand color + platform name so the OAuth screens
    show Junior Bay (mirror the TEST-branding steps in `docs/CONNECT_TEST_BRANDING.md`, for live).
- **Not available on Standard:** embedded onboarding components (the never-leave-the-app screens Stan uses) require
  Express/Custom — out of scope while we stay Standard.
- **SHIPPED 2026-08-27:** `ConnectIntroModal` (mounted once in App.vue; every `startConnect()` entry point opens
  it) — JB 🤝 Stripe brandline, "Start selling & get paid", what-to-have-ready checklist, Home Country picker
  (→ `?country=` → `stripe_user[country]`), reassurance line, mode-aware TEST copy. **Still manual (author):**
  live-mode Connect branding in the Stripe Dashboard; deeper prefill waits on the Business Profile.

## Dashboard / UX

### Auto-attach a page to its Site on Publish (publish → attach in one action) — SHIPPED 2026-08-03
- **What:** publishing a page now attaches it to a Site in the same action, so a page never lands published-but-
  homeless (which stranded it on the bare artifact viewer URL instead of a real `{site}.jbay.uk/slug` store URL).
  Behavior by Site count: **one Site** → attach silently; **several** → publish, then the existing "Attach to a
  Site" modal opens to pick one (publish is not blocked); **zero** → publish only (nothing to attach to yet).
  Already-attached pages are left as-is (no re-attach, no prompt).
- **Where:** `dashboard/src/components/LandingPages.vue` — `ensureSiteAttachmentOnPublish()`, called from both
  publish paths (`publishPage` list menu + `saveBuilderPageWithStatus("published")` builder). Reuses the existing
  `attachPageToSiteCore` / `pageAttachKind` / attach modal and `sitesStore.attachPage` (backend `attach_page`);
  `attachPage._replace` refreshes the store so the list badge + nice URL update reactively. Frontend-only.
- **Draft URL hint — SHIPPED 2026-08-03:** an attached *draft* now shows a muted "Will publish to
  {site}.jbay.uk/slug" line (`pendingSiteUrl()`), so the tenant sees its real store home. The URL row above keeps
  the working preview link and Copy/Preview stay on the render (the store URL 404s until published), so the hint is
  informational only — "" for published pages (live URL is already the main line) and for unattached drafts.

### Fix the Live-mode dark theme — RESOLVED 2026-08-27 (dark theme RETIRED, option #2)
- **What:** the dashboard switches to a dark theme when the env toggle is on **Live** (`theme-live` class on the app
  shell; e.g. `.theme-live input { background:#1f2937 }` in `dashboard/src/styles.css`), but the dark styling is only
  partial: modals/cards/wizards (e.g. the 5-step Create Landing Page wizard) keep dark-on-dark fields with
  near-invisible borders, while **Test** stays light and looks correct. Screenshot evidence: same wizard, Live = murky
  low-contrast panels; Test = clean white modal.
- **Fix direction:** audit every surface under `.theme-live` (modals, cards, wizard steps, dropdowns, tables) and give
  the dark theme a complete token set (backgrounds, borders, text, focus rings) — or, simpler, **reconsider whether
  Live should be dark at all** (the mode pill + accent color may be enough env signal; a full theme swap doubles the
  styling surface to maintain). Decide, then make whichever theme(s) remain fully consistent.
- **Related:** the earlier env-toggle repaint issue in [dashboard env + caching] — same toggle, adjacent polish.

### Consolidate the side menu into collapsible groups
- The side menu has grown cluttered and lost its original simplicity. Look into grouping items into collapsible
  sections. Deferred to AFTER BNPL ships (plans/BNPL_PAYMENT_METHODS.md) — the right grouping will be clearer then.

### Build the beginner-friendly custom-domain wizard
- **What:** Replace the current bare custom-domain form with the guided, auto-polling wizard designed
  in **`docs/CUSTOM_DOMAIN_WIZARD.md`** (single flow for beginners + power users; reveals DNS records
  progressively; explains propagation; auto-checks status so users rarely click "Check Status").
- **Current behavior:** the backend is in place (`src/handlers/custom_domains.py` +
  `custom_domains_resolve.py`, Cloudflare Worker + resolve API); the dashboard only exposes the simple
  TenantConfig-based form inside `dashboard/src/components/Configuration.vue`.
- **Where to fix:** build the wizard as a dashboard component (its own multi-step flow) per the
  reference design; wire it to the existing custom-domains endpoints. No backend changes needed.
- **Why deferred:** the functional path works via the Configuration form; the wizard is a UX upgrade.
  Reference design written 2026-07-03, not yet built.

### Notification emitters + toasts (see docs/NOTIFICATION_EMITTERS.md)
- **Emitters — done:** `order`/sale (completed checkout, retitled "New sale" 2026-07-23), `paid_invoice`,
  `lead`, and `refund_request` (shipped 2026-07-23, commit 486fece).
- **Toasts (Tier 3) — SHIPPED 2026-07-23:** transient dashboard toasts for sale / refund request / set up
  Stripe (`stores/toasts.js` + `ToastHost.vue`, diffed in `App.vue`). See docs/NOTIFICATION_EMITTERS.md.
- **Still to build (blocked on other features):** `stripe_connect` status, `system`/Stripe-key-failure,
  `shipping` (needs shipping integration), `system`/support (needs a support system).

## Commerce

### ⭐ SaaS billing paywall + trial-first onboarding — SHIPPED PROD 2026-08-03
- **Shipped:** table-driven `PlatformPlansTable` (Bay Pass $9.58/mo, editable) + repo/cached loader; subscribe via
  Stripe Checkout(subscription) + Billing Portal; SEPARATE platform-billing webhook (`/webhook/platform-billing`,
  own signing secret kind=`platform_billing`) driving `billing_status`; EXEMPT flag + config bypass list; special-link
  promotions (trial override + Stripe discount); **plan entitlements** (per-feature on/off, denormalized onto the
  tenant, backend-gated at all 10 feature chokepoints + disable-menu UI); **trial-first onboarding** (14-day
  full-access platform trial stamped at registration, `TrialPeriodDays` env-configurable dev=1/prod=14, hard wall at
  expiry via `trial_expired` + guard backstop); Billing screen + trial banner; auth "Start your free trial" reframe.
  Full design in `plans/SAAS_BILLING_PAYWALL.md`. Deployed dev+prod, `main` consolidated, 1406 tests.
- **Follow-ups (non-blocking):** reload Billing on Checkout success-return; per-use promo `max_redemptions` counting;
  custom-domain takedown-on-suspension sweep; "trial ending/ended" emails (scheduled sweep); resync existing
  subscribers on a plan-entitlements edit; admin plan-CRUD screen (P3, MVP = hand-edit the table); price-migration
  batch tool (P4).

### ⭐ Pricing pivot — free-forever + transaction-fee model (decided 2026-08-26, NOT built)
- **Direction:** move from the shipped **hard-wall-at-trial-expiry** to a **free-forever** model. Basic is always free
  and never shuts a store down or blocks a sale — the tenant just pays the basic transaction fee. The 14-day trial
  grants **premium** features (booking, GMB, AI, shipping, A/B); at expiry those features gate off (existing
  entitlement chokepoints) but **pages/checkout keep serving at the basic fee**. Premium (~$19/mo target) unlocks
  those features **and** drops the transaction fee (~2%). Strategy = Beacons' free-forever acquisition + Shopify's
  fee-graduation + a Stan-style trial that **downgrades gracefully** instead of locking out — you never lose the
  tenant and keep earning the fee forever.
- **(a) Paywall change — SHIPPED DEV+PROD 2026-08-27:** hard wall replaced with the free-forever downgrade
  (entitlements floor `landing_pages+sites+collections`; BLOCKED statuses = suspended only; free-plan banner).
  Shipped alongside: **Premium $19 plan cutover** (docs/PLATFORM_PLANS.md), **tier_id sync** (subscribe→plan
  fee_tier, deleted→basic), **server-authoritative fee tier** in /prices/calculate (+ TenantProfiles IAM grant,
  tier-aware price-form preview), **webhook ordering guard** (last_billing_event_at; fixes incomplete-after-paid
  past_due), honest past_due presentation, and **in-app Cancel/Resume subscription** (cancel_at_period_end; the
  Stripe portal demoted to a muted card/invoices link + past_due-only button). Full upgrade→cancel→resume loop
  verified on sandbox (tenant 08f12390); prod verified via routes/calc/bundle checks.
- **(b) Fee table — SHIPPED DEV+PROD 2026-08-26** (`fees.py` defaults + both S3 `global_billing_config.json`
  objects + dashboard preview rates; new `service` fee class live; verified via `/prices/calculate` on
  dev.juniorbay.com AND prod.juniorbay.com — 5/6/7 free, 2% pro, 0% pro tips; 1420 tests green):

  | fee class | Free | Premium ($19/mo) |
  |---|---:|---:|
  | physical | **5%** | **2%** |
  | service *(new class)* | **6%** | **2%** |
  | digital | **7%** | **2%** |
  | tip_jar | **5%** | **0%** ("keep 100% of tips") |

  Ladder tracks margin (physical thinnest → lowest). Digital 7% **undercuts Beacons 9% / Gumroad 10%** — launch
  positioning. Crossovers (GMV where premium wins): digital ~$380/mo, service ~$475, physical ~$630. **Ratchet
  accepted:** fees can be *lowered* later (a gift) but never raised (scandal + baked net-guaranteed prices erode) —
  7% digital is the forever-ceiling, chosen deliberately (merchant's-eye: 7%+Stripe ≈ a bearable ~10% all-in).
  **Tier-key mapping:** Free=`basic`, Premium=`pro`; `standard` stays as a dormant legacy key (zero migration).
  **Code change (small):** `fee_class_for()` currently routes `service`→`digital` (deliberate, PRD STORY-4.1) —
  add a real `"service"` class + table entries + fallback for configs lacking the key.
- **(b2) Fee-split preset — SHIPPED DEV+PROD 2026-08-26** (generalized `calculate_price` around
  `MERCHANT_FEE_SHARES`; schema + service validation; third radio in shared PricingCard + preview; verified live
  both envs: digital $100→buyer $105.37/merchant $94.63, physical $100→$104.27/$95.73; 1423 tests): a THIRD
  fee-handling option, **"Split 50/50"**, on the price
  form's Fee handling radio group (Products → Pricing, between "Standard fees deducted" and "Net-guaranteed fees
  added on top"). Merchant and buyer share the fees: generalized gross-up
  `unit = (keyed + (1−s)·fixed) / (1 − (1−s)·rate)` where `s` = merchant's absorption share (standard s=1,
  net_guaranteed s=0, split s=0.5) — the existing `calculate_price` loop generalizes with one parameter. Worked
  example (digital free tier, $100 keyed): standard $100/$89.80, **split $105.36/$94.63**, net-guar $111.43/$100 —
  split lands the buyer markup at ~5.4% (surcharge-tolerance territory) while halving the merchant's fee hit; the
  **killer preset for thin-margin physical sellers**. **Presets only, NO slider** (store a numeric absorption share
  internally — 100/50/0 — for future flexibility; UI exposes exactly three radio choices). Plain-language labels:
  "I cover the fees / Split 50/50 / My buyers cover the fees," live buyer-price preview per option. Downgrade
  behavior identical to net_guaranteed (baked buyer price holds; merchant's realized net dips until re-price).
- **Already true in code (no work needed):** price is **baked at setup** (`prices.py` net-guaranteed gross-up →
  `Product.unit_amount`) while the **fee is computed live at checkout** from the tenant's current `tier_id`
  (`fees.py build_fee_context`). So upgrade/downgrade already "just work": buyer price stays stable; on **upgrade** the
  tenant keeps the ~8% windfall (their price was grossed for the old high fee). **No re-price prompt — deliberately
  not building it:** a tenant who wants a different price adds another `Product.prices[]` entry + flips
  `default_price_id` (self-serve in the UI today).
- **Wiring:** premium subscription (`billing_status` / `PlatformPlansTable`) → `tier_id` → live fee + entitlements
  (the subscription rail already ships; reuse it). Prereq for the homepage "always free" reword (Production setup).
- **(c) Feature packaging — FIXED vs METERED (deep-dive TBD):** the purpose of premium/value-add is to **mitigate
  metered COGS**, so split features by *cost-to-us*, not one-by-one:
  - *Free forever:* the core earning loop — landing pages, checkout, digital delivery, basic products, flat-rate
    shipping (never gate a sale).
  - *Premium (bundled, ~$19 + ~2% fee):* all **zero-marginal-cost** features — GMB, integrations (Zapier/HubSpot),
    A/B, booking, carrier-calculated shipping/labels. Already gateable by flipping each plan's **entitlements map**
    (`entitlements.py` / `PlatformPlansTable`) — minimal build. Resist Shopify-style à la carte add-ons for these
    (decision fatigue for a creator audience; the transaction fee already captures success-based upside).
  - *Metered (real per-use COGS — needs a usage-billing rail that is NOT built):* **AI generation, SMS, maybe email.**
    Flat-rating these is a margin sink; if offered in-house, price as an included monthly allowance + overage, or a
    metered add-on.
  - **⭐ V1 likely decision:** **side-step in-house metered features** and offer **simple integrations** instead
    (bring-your-own AI / email / SMS) so there is **no metered COGS to recover** and no usage rail to build
    (reportedly how Stan works today). Revisit in-house metered offerings only when demand/margin justifies the rail.
- **Code facts (verified 2026-08-26):** fee is config-driven (no hardcoded % at charge sites); plans + per-feature
  entitlements are **table-driven** (edits take effect within a cache TTL, no deploy). **Caveats:** Stripe Prices are
  **immutable** — editing a plan's dollar amount re-prices only NEW subscribers; existing ones need a new Price +
  migration (deferred tool). The subscription is a **single line item** today (no multi-item/add-on billing), and
  there is **no metered/usage rail** yet (same gap the Identity gate flagged).

### Age / identity verification gate (Stripe Identity)
- **UNBLOCKED 2026-08-03** — the SaaS billing subscription rail it needed now ships in prod. Verification charging can
  ride the tenant subscription (metered
  SubscriptionItem or a "verified" tier), so build the paywall rail first.
- **What:** let tenants mark products/offers age- or identity-restricted; the buyer must pass a **Stripe Identity**
  check (gov-ID + selfie) before checkout; the platform bills the tenant per verification. Full design in
  **`plans/IDENTITY_VERIFICATION.md`**.
- **Key facts:** VerificationSession runs on the PLATFORM account (buyer verification, not Connect KYC); reading
  `dob` for age gating needs a **restricted API key**; cost $1.50/verification (doc+selfie), no monthly minimum.
- **Charging (primary open decision):** **no platform→tenant billing rail exists** (application_fee is a take-rate
  on the buyer's payment). Recommended Phase-1 MVP = flat verification fee (~$2.50-3.00) added to the *converting*
  order's application_fee (tenant nets it out; platform absorbs non-converting verifications via the markup;
  per-tenant daily cap). Phase-2 (deferred) = a real metered platform→tenant billing rail (reusable for other
  features).
- **Why deferred:** planned 2026-08-02, no code. Current tenants sell supplements (not gated) — hold the design,
  build when an age-restricted tenant onboards (or ship P1a free as a differentiator). Awaiting the charging-model
  decision.



### Editable funnel Page docs — the only open item from SALES_FUNNELS.md
- **What:** the funnel steps (`/upsell`, `/downsell`, `/thank-you`) render from ephemeral synthesized S3
  artifacts, not tenant-customizable **Page** docs. Make them editable Page docs (stripe-cart parity, plan
  §Auto-provisioning / P2); converges with the Upsell Phase 2 "scoped landing builder" idea.
- **Why deferred:** deliberate — the author chose reserved-slug routing over editable funnel pages.
- **Tackle alongside this task:** "Draggable upsell order" (below, Commerce) and the carousel "Default 'no image'
  placeholder" (below, Landing Pages / SEO) — kept as their own entries, but slated to be done during this work.
- **Everything else in `plans/SALES_FUNNELS.md` is DONE and live in PROD** (verified 2026-07-31 against the
  deployed Lambda code): P1 pre-purchase (reserved slugs + `/sale`//`/flash-sale` price mechanism + flash
  client-side time-states), P2 (order bumps via Stripe `optional_items`, post-purchase funnel engine,
  reserved-slug custom-domain serving), the re-publish-on-domain-verification remediation, and the 3 landing
  multi-product/cart bugs (all fixed + tested). **P3** (advanced branching `Funnel` doc, funnel builder UX,
  per-step analytics, AI copy) is intentional FUTURE scope tracked in the plan — not part of closing this task.

### ⭐ Platform-hostname Site serving (`*.jbay.uk`) — navigable free/test stores + env parity
- **What:** serve every Site on its free `{label}.jbay.uk` platform hostname in BOTH environments, so storefronts
  / offer pages / funnels / sale views are fully navigable (clean slugs) without a custom domain. Fixes the core
  sticking point that clean-slug nav only exists on a live custom domain (prod) — the reason a storefront can't
  be built/previewed in test and its cards die (`mart.automizepro.com` NXDOMAIN, 2026-07-30). "Go live" becomes
  "connect a custom domain" (the indexed upgrade); unlocks free-tier stores + a clean test→live promote flow.
- **Design greenlit 2026-07-30 → `plans/PLATFORM_HOSTNAME_SERVING.md`.** Key point: it REUSES the custom-domain
  resolver, route table, funnel/context slugs, SEO toggle, and re-publish — additive, not a rewrite; the ~1218
  tests fence the custom-domain behavior. Low infra: we own the jbay.uk zone and Universal SSL covers one-level
  `*.jbay.uk` (no per-tenant cert). Careful area = decoupling `home_url` (navigable chrome) from indexing
  (platform host stays `noindex`). Phases: P1 serve on platform host (index record + `*.jbay.uk` Worker route +
  home_url decouple + host-relative links + host-aware funnel redirects) → P2 Site-level copy test→live → P3
  free-tier surface + dashboard store URL.
- **Not built.** Next step is the scoping pass on the open decisions in the plan.

### Draggable upsell order (tenant-controlled funnel sequence)
- **What:** let the tenant choose the order in which upsells are presented, by dragging the accordion steps in
  the builder's **Post-Checkout Flow** panel. Today the order is implicit — whatever order the upsell-context
  opportunities happen to sit in on the offer.
- **Current behavior:** `post_purchase_plan` (`src/stripe_link/domain/funnels.py`) builds the upsell list from
  `funnel_context_items(offer, …, "upsell")`, which walks `opportunities_from_offer(offer)` in document order
  and `enumerate(…, start=1)` assigns the 1-based **`sequence`**. So the sequence follows the offer's
  `funnel.upsells` array order — there is no UI to reorder it.
- **Where to build:** the Post-Checkout Flow accordion lives in `LandingPages.vue` (the `funnelSteps` computed +
  `openFunnelStep`/`toggleFunnelStep`); add drag-to-reorder over the **upsell** steps only (not thank-you).
  **Key architectural note:** the order is a property of the **offer** (`offer.funnel.upsells`), not the page,
  so a reorder must persist to the **offer document** (Offers.vue / the offer save path), not `page.post_checkout`.
  The builder edits a page; it would need to write the reordered `funnel.upsells` back to the owning offer (or
  surface the reorder control on the offer editor and mirror it read-only in the builder).
- **Watch out:** `sequence` is the idempotency key `process_upsell` charges under (`handlers/upsell.py`), so
  renumbering is fine for new funnel runs but must not silently rebind an in-flight session's already-charged
  sequence. Downsells pair to upsells **by product_id** (not sequence), so they follow the reorder for free.
- **Why deferred:** enhancement only; the software-chosen order is correct, just not tenant-adjustable. Noted
  2026-07-29 at author request.

### Listicle L2 — server-side cart + multi-line checkout + recovery (Slices A–D SHIPPED)
- **Shipped dev+prod 2026-07-23**: server-backed cart (ad4e35a/d1c9718), multi-line Stripe checkout
  (c31d8b7), and abandoned-cart recovery via opaque-token identified links (7993aae/9c4739f/018ffb8).
  Full detail in `plans/LISTICLE_AND_CART.md`.
- **Still pending:**
  - **Service-line cart checkout.** `resolved_items_for_checkout` rejects service lines today (booking has its
    own pay-then-book/book-then-pay flow); mixing cart + booking fan-out is its own slice.
    - **(Very low priority) Service-listicle abandonment recovery.** Once service lines are cart-eligible,
      extend the recovery sweep to service listicles too.
  - **Tenant-wide email suppression.** Cart-recovery unsubscribe is per-cart today; a tenant-wide email
    opt-out list is a future refinement.
  - **Tenant outreach campaign tooling.** The `cart_token` primitive supports identified "Items just for you"
    links, but composing/bulk-sending them (recipient lists, templates) is a separate feature; not built.
  - **L3 order-model ripples** (per-line refunds/receipts/fees/downloads) — build only when L2 is proven.

### Transaction ledger — finish P&L, canonicalization, and reporting
- **Core shipped:** append-only `domain/ledger.py` (sale/refund/dispute entries + `summarize()` derived
  totals) + `LedgerTable` + `ledger_repository` + read-only `GET /ledger`; sale/refund entries recorded from
  the Stripe webhook. Full design + accurate build state in **`plans/TRANSACTION_LEDGER_STRIPE_LINK.md`**.
- **Still to build (in rough priority order):**
  - **COGS + shipping-cost entries** so `profit` is real (today only fees are netted) — needs product-cost +
    shipping-cost inputs at sale time.
  - **Make the ledger canonical:** demote order `amount_paid`/`amount_refunded` to a *derived cache* off the
    ledger (currently authored by overwrite, so they drift on missed/double webhooks) — the plan's core aim.
  - **Tax-liability-by-jurisdiction** reporting (group `tax` by `metadata.tax_jurisdiction`; feeds PRD Phase 8).
  - **Rollups**, **reversing-entry corrections**, **migration/backfill**, and a **dashboard reporting UI**
    (no ledger view exists in `dashboard`).
- **Why deferred:** the money-movement substrate works and orders report correctly today; this is the P&L /
  tax-reporting layer on top.

## Business Profile & Reviews

### Business Profile — GBP Phases 2 & 3 (Google Business Profile sync)
- **What:** P1 (canonical Business Profile identity + LocalBusiness derive + category→specific `@type`) is
  **shipped**. **P2** = Google Business Profile OAuth + two-way sync (pull NAP/hours/reviews, push updates);
  **P3** = AI-managed GBP. Design in **`plans/BUSINESS_PROFILE_AND_GBP.md`**.
- **Verified not built** — no GBP OAuth / My Business API code exists yet.
- **Why deferred:** P1 already covers the on-page identity + local-SEO need; live GBP sync is a separate
  external-integration effort (Google API access + app verification), similar in shape to the calendar OAuth
  path — best started when GBP management becomes a priority.

### Reviews — future phases
- **What:** the first-party review aggregator + post-purchase invite sequence shipped (Phases 1–2). Still
  planned (all in **`plans/REVIEWS.md`**): Merchant Center product-review **feed** (P3); GBP/third-party
  review **read-back** (display-only, never in markup); **per-product** invite targeting; invite
  **timing-offset** setting; a **verified-review auto-approve** toggle; the **SMS** invite channel (gated on
  10DLC below); and testimonials/`social_proof` auto-wiring from approved reviews.
- **Why deferred:** core review capture + Product star snippets are live and compliant; these are additive
  enhancements.

## Stripe integrations (backlog — investigated 2026-08-02)

### Capture more Connect-onboarding data via account.updated
- **What:** we ALREADY capture the tenant's business identity (name/email/phone/address) from the `account.updated`
  webhook via `business_profile_seed` (`src/stripe_link/domain/connect_sync.py:66`) → seeds the business profile
  (fill-empty-only, `reconcile_account_updated` in `stripe_webhook.py`). Expand it to capture more `business_profile`
  fields (website/url, product_description, MCC, support contacts) + store on the tenant/business profile.
- **Caveats:** Stripe redacts sensitive KYC PII (tax_id/SSN/DOB/bank) on Standard accounts — business identity only,
  not raw PII. The tax product-type selection is a Stripe Tax setting (see below), not Connect onboarding data.
- **Small:** additive to the existing account.updated handler. Not built.

### Stripe Tax threshold monitoring — toggle + on-demand panel in the dashboard
- **What:** let a tenant enable Stripe's free sales-tax **threshold monitoring** ("when/where you need to collect")
  from our dashboard, popped out on demand. Stripe ships it as a **Connect embedded component**
  ([tax-threshold-monitoring](https://docs.stripe.com/connect/supported-embedded-components/tax-threshold-monitoring)):
  create an Account Session (`components[tax_threshold_monitoring][enabled]=true`) + render via `@stripe/connect-js`.
- **Notes:** monitoring is FREE; tax *calculation* on transactions costs (~0.5%/txn). Prereq: also render the Tax
  **settings** + **registrations** components (the [Tax-for-platforms](https://docs.stripe.com/tax/tax-for-platforms)
  setup). **VERIFY:** whether embedded components support our **Standard OAuth** connected accounts (platform-liable
  model fits Express/Custom better); if not, fall back to a deep-link to the tenant's own Stripe Tax settings or use
  the [Tax Settings API](https://docs.stripe.com/tax/settings-api) to read/enable status (BNPL-toggle pattern).
- **Own plan when prioritized.** Not built.

## Production setup

### ⭐ Public marketing homepage — `juniorbay.com` (apex) — SHIPPED PROD 2026-08-24 (open: "always free" reword)
- **What:** a public, SEO-facing **sales page** at `https://juniorbay.com` whose only job is **Start free trial** /
  **Sign in** → `app.juniorbay.com`. **Plain static HTML/CSS/JS** (no framework, no build — SEO + speed), hosted in
  **this repo** with an **isolated deploy** (own S3 bucket + CloudFront + apex Route 53 alias; reuses the existing
  `*.juniorbay.com`/apex cert `1a72b7c6`). **No pricing shown** (trial-first; affordability hint *"It costs less than
  your coffee habit"* — keep the money vague so it survives repricing); footer **Terms/Privacy/Refund → the `/legal/*`
  pages**; identity from `app_config.legal`. Full plan: **`plans/HOMEPAGE.md`**.
- **Front-end cleanup — DONE 2026-08-24:** retired the legacy plain-JS `dashboard/` folder and renamed
  `dashboard-vue` → `dashboard` (drop the `-vue` suffix); the new homepage folder will be `homepage/`. Updated the one
  functional reference (`deploy/deploy-dashboard.sh`), the npm package name, the `/dashboard/` `.gitignore` line, and
  the doc mentions.
- **Unblocks** the Google OAuth verification task below (which requires a public homepage + privacy policy on
  `juniorbay.com`), and gives the `legal.website` link a real destination.
- **SHIPPED PROD 2026-08-24:** homepage built + deployed and the apex `juniorbay.com` (+ `www`) cut over from the old
  classifieds distribution to the new homepage CloudFront (`HomepageEnabled`; bundled fonts; `/legal/*` proxied to the
  API; sitemap submitted to Search Console; Cloudflare Web Analytics beacon on). Old classifieds app → `juniorbay.net`
  (tenant to retire the old dist/bucket). Full record in `plans/HOMEPAGE.md`.
- **Pricing reword — SHIPPED PROD 2026-08-27:** CTA now **"Full access for 14 days — free"** + micro line
  **"No credit card · Always free checkout pages."** (hero + final CTA); coffee-habit hint retired; footer
  "© Junior Bay Corporation". No fee specifics on the front page (specifics live inside the app). Shipped after
  the paywall reversal made the promise true.

### Optimize prod CloudFront (pages) for indexing + aggressive caching
- **What:** Optimize prod CloudFront (`dlxn0y34f7dbz`) for indexing, follow, archiving, aggressive
  caching, long TTLs, and optimized compression.
- **Context:** non-prod pages are already locked down (dev pages dist `drjfn283z66uz` = X-Robots-Tag
  noindex,nofollow,noarchive + Managed-CachingDisabled), gated on the `IsNonProd` condition in
  `template.yaml`. Prod was deliberately left as-is: it currently uses Managed-CachingOptimized
  (`658327ea-f89d-4fab-a63d-7e88639e58f6`) and carries **no** distribution-level robots header — correct,
  because prod pages indexing is controlled **per-page** by the baked robots meta (`page_robots_directive`),
  and this distribution is the **origin custom domains reverse-proxy through**, so a blanket noindex header
  here would leak onto indexable custom-domain pages.
- **Where to fix:** `PagesDistribution` in `template.yaml` (the prod branch of the existing `!If [IsNonProd, …]`
  cache-policy expression). Consider a **custom CachePolicy** (longer default/max TTL than CachingOptimized's
  defaults) rather than the managed one, tuned for the published-page artifacts + crawl files; keep
  `Compress: true`. Do **not** add a distribution-wide noindex ResponseHeadersPolicy — indexing stays per-page.
- **Why deferred:** user's call to tune prod separately (2026-07-23). Dev is done.

### Pretty preview host — `preview.juniorbay.com` for live-mode draft previews — SHIPPED PROD 2026-08-19
- **What:** live-mode draft previews served on the raw preview-distribution domain; now branded as
  **`preview.juniorbay.com`** (→ the prod preview CloudFront dist). Test mode keeps its `test.juniorbay.com` viewer.
- **Shipped (all IaC + one config value):**
  - `PreviewDistribution` gets param-driven `Aliases` + `ViewerCertificate` (prod: `preview.juniorbay.com` on the
    existing `*.juniorbay.com` wildcard cert `1a72b7c6…`; dev leaves the params empty → no alias). `template.yaml`.
  - **Route 53** alias record `PreviewCustomDomainRecord` (A → the preview dist, zone `juniorbay.com` is in Route 53
    in the same account — NOT Cloudflare). Created by CloudFormation, prod-only.
  - Prod app-config **`environments.prod.pages_preview_base_url = https://preview.juniorbay.com`** (top-level
    `environments`, the shape the dashboard's `getPreviewPagesBaseUrl()` reads).
  - Verified: TLS valid, a real preview artifact serves HTTP 200 via the new host.
- **Bonus fix:** prod had no `pages_preview_base_url`, so the dashboard defaulted to the **dev** preview dist —
  prod live previews were misrouted. Now corrected.
- **Remaining tidiness:** the dev stack template lags `main` (params default empty → functional no-op); it syncs
  on dev's next deploy. Optional: add an AAAA alias (dashboard pattern is A-only) for IPv6-only clients.

### Create a separate prod Google OAuth client (calendar)
- **What:** Before enabling calendar sync in **prod**, create a *separate* Google OAuth 2.0 client
  for production (option #2 — isolated credentials per environment), in the same Google Cloud project
  / consent screen as dev.
- **Steps:** (1) Google Cloud → Credentials → create a new OAuth client (Web application);
  (2) add the prod redirect URI `https://prod.juniorbay.com/calendar/callback` to it;
  (3) store its creds with `./deploy/google-oauth-secrets.sh prod` (client_id + client_secret only —
  the refresh token is optional/test-only); (4) submit the app for **Google verification** (sensitive
  scopes) before serving real tenants — has lead time, start early.
- **Already handled:** the secret is per-env (`jb/google-oauth/prod`), the deploy auto-derives
  `CalendarRedirectUri` from the prod API domain, and the CalendarFunction reads the prod secret.
- **Why deferred:** dev calendar work is validated on the dev client; prod client is only needed when
  calendar sync goes live in prod.

### Apply for 10DLC (AWS End User Messaging SMS) — required before real SMS sending
Gates Phase C.2 (appointment reminders) and the SMS-delivery option for payable invoices. Submit-and-
wait review, **several business days to ~2–3 weeks**; start early. Code can be built/tested against a
fake in the meantime.
- **Prep:** legal business name + **EIN**, business address, website; a **website privacy policy that
  mentions SMS**; the **opt-in story** (customer enters phone at booking and is told they'll get
  reminders + "reply STOP to opt out" — the booking flow needs this consent line when C.2 is built);
  2–3 **sample messages** (e.g. "Reminder: your [Business] appointment is tomorrow at 2:00 PM. Reply
  STOP to opt out.").
- **Steps:** (1) AWS Console → **AWS End User Messaging SMS**; (2) Phone numbers → Registrations →
  **10DLC company (brand)** — legal name/EIN/address/website/vertical → submit (usually fast);
  (3) **10DLC campaign** tied to the brand, use case **Customer Care / Low Volume Mixed** (reminders
  are transactional), with sample messages + opt-in + HELP/STOP text → submit (the slow vetting step);
  (4) once approved, **request a 10DLC phone number** and associate it with the campaign;
  (5) create a **configuration set** for delivery receipts.
- **Costs (approx, pass-through):** one-time brand (~a few $) + campaign vetting (~$15) + **~$10–15/mo**
  per campaign + small per-message carrier fees.
- **Platform model:** register **one** platform brand + campaign; the platform number sends reminders
  that *reference* each tenant's business (simplest compliant model for multi-tenant SaaS).
- **C.2 code status (built 2026-07-07, dev):** the reminder engine ships and runs against a fake — pure
  `src/stripe_link/domain/reminders.py` (plan/due/cancel/format), the `src/stripe_link/sms.py` adapter
  (`pinpoint-sms-voice-v2`), and the `RemindersFunction` sweep (`handlers/reminders.py`, EventBridge
  `rate(15 minutes)`). Reminders are planned on confirm/paid/reschedule and canceled on cancel.
  **To go live once the number is approved:** run `./deploy/sms-origination-secrets.sh prod` and enter
  the approved 10DLC number (or phone-pool ARN) + optional configuration set. It is stored in Secrets
  Manager (`jb/sms-origination/{env}`) and read at **runtime** by the sweep — so it takes effect on the
  next sweep (~15 min) with **no redeploy**, and can be rotated the same way. Until it is set the sweep
  no-ops (`skipped: sms_not_configured`). The **opt-in consent line** is already on the public booking
  form; STOP/HELP + the opt-out list are handled by End User Messaging itself, and `sms_opted_out` on
  the customer is honored as a belt-and-suspenders. Use a test/simulator number in dev the same way.
- **Future precision upgrade (optional):** swap the 15-min sweep for a per-booking **EventBridge
  Scheduler** one-shot (exact-minute delivery). The `domain/reminders.py` planning is model-agnostic, so
  only the handler/infra changes; a two-way inbound-STOP SNS handler could also record app-level opt-out.

### Verify the Google OAuth app (Calendar sensitive scopes) — before prod calendar at scale
Removes the "unverified app" warning, the ~100-user cap, and the 7-day refresh-token expiry. Review
takes **days to a couple of weeks**. Calendar scopes are *sensitive* (not *restricted*), so **no**
third-party security assessment is required.
- **Prep:** a public **homepage** on the domain (`https://juniorbay.com`); a **privacy policy URL** on
  that domain disclosing Google user-data usage + **Limited Use** compliance (can be generated from the
  legal-pages system — needs the Google-specific language added); **verify domain ownership** in Google
  Search Console; an **unlisted YouTube demo video** showing the consent flow + each scope in use (the
  C.1b connect flow on dev can be screen-recorded for this).
- **Steps:** (1) Google Cloud → **APIs & Services → OAuth consent screen**; (2) complete app name, logo,
  support email, home page, privacy policy + terms URLs, **Authorized domains** (`juniorbay.com`);
  (3) confirm scopes `calendar.events` + `calendar.readonly`; (4) **Publish App** (Testing → In
  production); (5) **Prepare for verification** — submit scope justifications + demo video + policy URLs;
  (6) wait for approval.

## Landing Pages / SEO

### Default "no image" placeholder so image-less products stay swipeable in the carousel — SHIPPED 2026-08-03
- **What was broken:** the landing multi-product carousel syncs each product's tier block to the hero image
  carousel by index, but `render_hero_media` FILTERED OUT slides with no image — so an image-less product got no
  hero slide, the slide count no longer matched the product count, and the buyer couldn't swipe to it (its tier
  block never activated).
- **Fix (`src/stripe_link/runtime/html.py`):** a shared inline-SVG **`PLACEHOLDER_IMAGE`** data-URI (open box + "0"
  badge, matching the author's illustration — swap the `_PLACEHOLDER_IMAGE_SVG` string to change the art). The
  listicle hero now keeps **one slide per product** (`slide["image"] or PLACEHOLDER_IMAGE`), and price-option tier
  cards fall back to it too (`price_image(...) or PLACEHOLDER_IMAGE`). Kept **out of SEO** — Product/Offer JSON-LD
  and og:image read `product["images"]` directly, which is never mutated (regression test asserts this).
- **Not applicable:** the mini-cart renders name/qty/amount only (no image), so there was nothing to place there.
- **Still open (complement, not needed for the fix):** arrow/dot nav that drives the tier sync directly, so
  swipeability doesn't depend on images at all (`plans/LANDING_CAROUSEL_FIXES.md`).

### Reorganize the Landing Page Builder and optimize its CSS
- Reorganize the Landing Page Builder and optimize its CSS.
- **Context for when we pick this up:** the Live Preview is no longer a Vue reimplementation — it renders
  the real page through `POST /pages/render` into an iframe (see plans/PAGE_COMPOSER.md, "one renderer,
  not two"). So the builder is now *only* a form, and a lot of `styles.css` exists to style a preview that
  no longer exists: the `.preview-*` rules (hero, badges, price cards, blurbs, testimonials, marquee, faq,
  refund, legal, cta) are dead except `.landing-live-preview` preset blocks, which survive solely so
  `.preview-token-probe` can expose `--preview-*` values to Advanced Color Settings. Retiring them means
  deciding where the colour pickers read preset values from instead.
- Related dead JS left by the same change (price-preview cluster, `headlineHtml`, `defaultLegalLinks`, …)
  is listed at the end of plans/PAGE_COMPOSER.md.

### Match stripe-link's CSS style to stripe-cart's
- **What:** bring stripe-link's rendered visual style into line with the legacy **stripe-cart** look (the
  behavioral/visual reference). Audit where the two diverge and update stripe-link's CSS to match.
- **Scope to confirm when picked up:** primarily the storefront/landing-page styles
  (`src/stripe_link/runtime/html.py` style block); clarify whether the dashboard chrome is in scope too.
- **Why:** visual parity with the legacy experience users know; per CLAUDE.md, stripe-cart is the reference.

### Implement an on-page SEO checklist for landing pages
- **What:** Emit proper on-page SEO for rendered landing pages: unique `<title>`, `<meta name="description">`,
  canonical URL, **Open Graph** + **Twitter Card** tags, and **JSON-LD structured data** (e.g.,
  `Product`/`Offer` with price/availability, `BreadcrumbList`; `Service` for booking pages), plus
  sensible robots/`hreflang` defaults, semantic headings, and descriptive image `alt` text.
- **Where to fix:** the storefront renderer (`src/stripe_link/runtime/html.py`) is where page `<head>`
  and body markup are produced; the SEO fields should live on the **Page document** (title,
  description, social image, structured-data hints) so tenants — and the AI generator — can set them.
- **Ties into:** the composition/preset system (PRD Phase 1) — SEO metadata is part of the page
  vocabulary the AI emits; and product/offer data already on the page (for `Product`/`Offer` JSON-LD).
- **Why deferred:** functional pages render today; SEO is an enhancement layer. Best done alongside the
  Phase 1 composition refactor so the metadata surface is designed once.
- **Low-priority follow-up — localized (pretty) image URLs:** most on-page SEO signals for local/service
  pages are **shipped** (localized alt, `<figcaption>` NAP, LocalBusiness JSON-LD incl. category→specific
  `@type`, image dims — see `plans/LOCAL_SEO_SIGNALS.md`). The one remaining piece is **hybrid pretty image
  URLs** via a CloudFront edge-alias — fully designed in **`plans/LOCALIZED_IMAGE_URLS.md`**, not built.
  Lowest-leverage SEO item (incremental Image-Pack ranking only), so it waits for the higher-priority work
  above. That plan also carries a **separate, decoupled** task: renaming the media **API** endpoint to
  `https://media.juniorbay.com/v3` (agreed to plan, execution timing TBD).

### Future enhancement — SEO page analyzer with a score
- **What:** an SEO analyzer that checks every critical on-page SEO point for a landing page and returns a
  **score** (e.g. 0–100) plus a per-check breakdown with pass/warn/fail + a fix hint. Think Yoast/RankMath's
  content analysis, adapted to our renderer.
- **What it would check (build on signals we already compute):** title present + length + Buy-formula;
  meta description present + length; canonical; OG/Twitter tags; complete `Product`/`Offer` JSON-LD
  (`structured_data_warnings`); heading outline (one H1, ordered H2/H3 — `heading_outline_warnings`);
  image alt/dims; **thin-content word count vs the 150 floor** (`indexable_word_count`/`THIN_CONTENT_MIN_WORDS`,
  `thin_content_warnings`); the effective **robots state** (`page_robots_directive`) + WHY it's noindex
  (thin / eligibility pending / SEO toggle off / funnel page_type); internal links / breadcrumb; and Site-level
  eligibility (verified domain + Connect + `indexing.seo_enabled`).
- **Where:** the per-check pieces mostly EXIST as `*_warnings` helpers in `src/stripe_link/runtime/html.py`
  and are already returned by `/pages/render` as `warnings.page_health`. The analyzer would consolidate them
  into one scored report and surface it in the builder (and, if wanted, drive the deferred list-card SEO badge
  below).
- **Deferred sub-idea (2026-07-30 discussion): a per-page SEO/indexing BADGE on the Landing Pages list card**
  (Indexed / Thin — not indexed / Not indexed). Blocked on the same thing: the effective robots/thin status is
  computed at publish from the rendered HTML and is NOT on the page doc the list reads. To badge it, persist a
  tiny SEO summary on the page at publish (robots + `thin` flag + word count) **with a stream-filter guard** so
  writing it back doesn't re-trigger publish (page write → `should_publish_record` → re-publish loop). Chose
  "let it be" for now — the builder page-health panel already surfaces thin content when editing.
- **Why deferred:** nothing is broken; the raw signals already surface in the builder page-health panel. This
  is a visibility/UX polish layer. Noted 2026-07-30 at author request.

## Offer Semantic Model

### JSON-Schema ↔ model drift — RESOLVED 2026-07-28
- **Done (option (a) from the original note):** the model schema now lives in code as the single source of truth
  (`OFFER_SEMANTIC_MODEL_SCHEMA` in `src/stripe_link/domain/semantic_schema.py`), enforced by a small in-repo,
  dependency-free `check_schema` interpreter. `validate_semantic_model` now *is* the schema (no separate
  hand-written rules to drift), and a test locks `schemas/OfferSemanticModel.schema.json` equal to the code
  schema minus annotations — so validator, schema, and file cannot disagree. This is the contract P4.1 will hand
  to the AI provider's structured-output mode. No `jsonschema` dependency added.

### Semantic-model caching — write path still deferred to P4.1
- **Done in P4.0:** the `offer.semantic_model` field is now **reserved** — validated when present
  (`validate_offer_document`) and documented in `schemas/Offer.schema.json` — and the `resolve_semantic_model`
  read seam recomputes deterministically when it's absent/stale.
- **Still deferred (intentionally):** the cache **write** at offer-save, `generated_at` stamping, and
  invalidation-on-offer/product/brand-change. The deterministic model is cheap to recompute, so the cache only
  earns its keep once the **expensive AI enrichment** (P4.1) exists — build the write path then, alongside the
  enrichment flow, per the 2026-07-28 decision ("worry about cache when everything else is finalized").
