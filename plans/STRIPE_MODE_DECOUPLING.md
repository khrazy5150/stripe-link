# Decouple Stripe mode (test/live) from platform environment (dev/prod)

Status: **IN PROGRESS.** Design 2026-08-02. Foundational re-architecture. Approved to plan in full while
**pre-launch** (all "tenants" are the operator's test emails → no real data to migrate; cheapest time to do it).
Build workflow: **feature branch `stripe-mode-decoupling`** (main stays deployable), **dev-first cutover**.
- **P0 DONE** (committed to `main`): `resolve_stripe_mode`/`normalize_stripe_mode` request helper + inert dashboard
  `stripeMode`/`hostnameReleaseChannel` scaffolding. No behavior change (default mode = test/live per fail-safe).
- **P0.5 DONE** (branch): stripe-keys → one per-deployment table keyed (tenant_id, mode); tenant-profiles dual-write
  retired; StripeKeysTable gains `mode` SK; fixed `_DEV/_PROD` env pairs + IAM grants collapsed to per-env `!Ref`.
- **P1 DONE** (branch): backend base now hostname-derived (`getApiBase`); toggle → Stripe mode sent as `?mode=` +
  `X-Stripe-Mode` on every `apiRequest`; `getStripeMode` single source of truth; cross-mode copy targets the other
  mode on the same backend; all `getApiEnvironment` call-sites repointed. Dashboard builds clean.
- **P2 IN PROGRESS** — **DESIGN CHANGE (2026-08-02): mode goes in the KEY, not just an attribute.** The plan's
  "attribute + filter" collides with the ID-preserving test→live copy: same `(tenant,id)` in one table = one item,
  so promoting a test offer would overwrite it. Author chose *mode-in-key*: `DynamoDocumentRepository(mode=…)`
  bakes mode into SK + GSI1PK (`{TYPE}#{mode}#{id}`) so test/live copies coexist; put stamps `stripe_mode`,
  get/list/delete/find_by_id are mode-scoped; `mode=None` = legacy layout.
  - **P2 part 1 DONE** (0cfef7c): dashboard CRUD — products/offers/coupons/pages/collections. Repo + handler tests.
  - **P2 part 2a DONE** (experiments, invoices, sites), **2b** (services + booking; services mode-scoped, booking
    Stripe-key mode from request), **2c** (checkout, cart_checkout, cart, upsell, post_checkout, leads, downloads,
    refunds, reviews_public, orders dashboard; orders/customers via TenantRangeRepository = mode as a filtered
    ATTRIBUTE since ids are unique/no cross-mode reuse; sweeps cart_recovery + reminders = `mode="live"`).
  - **Mode-scoped set**: products, offers, coupons, pages, sites, collections, carts, cart_tokens, invoices,
    appointments, services, experiments (DynamoDoc, mode-in-key); orders, customers (TenantRange, mode-attribute).
    **Left mode-agnostic**: leads, reviews/review_invites, refund_requests, fulfillers, availability, routes,
    custom_domains, legal_pages, notifications, tenant/user profiles (no per-mode Stripe state).
  - **P2 REMAINING**: page_publish + page_render — mode comes from the page record (stream) / serving host, not a
    request → done in **P4** (per-mode publish path). Until it lands, publishing can't see mode-keyed records
    (branch not deployed; tests inject → all pass).
- **P3 DONE** (branch): webhook derives mode from `event.livemode`, not the deployment. Parse body first (unverified)
  to read livemode + pick the per-mode signing secret, then verify signature. Removed `_mode_for_environment` + the
  mode-mismatch reject (the old dup-order guard — now moot: dev gets no Stripe traffic, dedup stays per-events-table
  by event_id). Threaded the mode into every reconcile path's repo writes/reads; `order_record_from_session` stamps
  `stripe_mode` so the raw order write matches the dashboard filter. **OPS at cutover**: point BOTH test + live
  Stripe webhook endpoints at the prod URL and configure both per-mode signing secrets on prod.
- **P4 NEXT** — publishing (page_publish per-mode, from the page record's stripe_mode) + host-agnostic checkout URL
  that bakes `?mode=` into published Buy links (closes the loop on P2's checkout mode-sourcing).

## The problem — mode and infra are conflated

Two orthogonal concepts are currently ONE switch:
- **Platform environment (dev/prod)** = software release channel (dev = unreleased/staging code, prod = released).
  Should be a *platform-team / hostname* concern.
- **Stripe mode (test/live)** = Stripe's test ("sandbox") vs live keys/transactions. Should be a *per-tenant*
  toggle available **within** the production app.

Today they're the same toggle:
- Dashboard test/live swaps the **whole backend base URL** — `test→dev.juniorbay.com`, `live→prod.juniorbay.com`
  ([client.js:1-8](../dashboard-vue/src/api/client.js#L1)); no `mode` param, a different backend. No hostname
  binding — it's purely `localStorage["stripeLinkVueEnvironment"]` ([client.js:40](../dashboard-vue/src/api/client.js#L40)).
- Webhook hard-binds mode to the deploy: `_mode_for_environment()` = `"live" if ENVIRONMENT=="prod" else "test"`
  ([stripe_webhook.py:84](../src/handlers/stripe_webhook.py#L84)); it even rejects mismatched `livemode` (`:190`).
- Published pages bake mode→backend-host: a test page's Buy button points at `dev.juniorbay.com/checkout`
  ([publishing.py:705](../src/stripe_link/runtime/publishing.py#L705)); test pages render into the **dev** S3 bucket.
- Offers/pages/orders live in **per-`Environment` tables** (`jb-offers-dev` vs `-prod`, template.yaml `:3276`);
  `stripe_mode` is only a data attribute on the offer ([Offer.schema.json:68](../schemas/Offer.schema.json#L68)),
  never a key — so in practice test data lands in dev, live in prod.

**The one seam already spanning both modes:** `stripe_keys`. Its two tables (`jb-stripe-keys-dev`/`-prod`) have
**FIXED names wired into every function** (template.yaml `:140-141`), and `table_for_mode(mode)` routes by mode
([documents.py:357](../src/stripe_link/repositories/documents.py#L357)) — so ANY backend can already read a tenant's
test AND live keys. This is the existing precedent we generalize.

**Net:** "test mode" IS structurally the dev backend today. Making a tenant's Stripe-test sandbox run on **prod**
requires threading Stripe mode as data through the whole stack.

## Decision (2026-08-02): Axis 1 only — NO cross-silo data sharing

Author confirmed the target after distinguishing two axes:
- **Axis 1 (DO):** Stripe mode (test/live) is a per-record ATTRIBUTE within EACH deployment's own tables, so a
  tenant's test + live coexist on prod (test-on-prod + easy test→live promote).
- **Axis 2 (DO NOT):** dev sharing prod's content/account data. Rejected as a data-governance hazard — dev runs
  UNRELEASED code and would expose/endanger real tenants' businesses + impose a permanent cross-version schema tax.
  Each deployment gets **fully isolated data**; dev is for testing CODE, not viewing prod data. (Matches how
  stripe-cart worked pre-silo.) A future `staging.juniorbay.com` is the isolation tier, not a shared-DB.

**This means UN-SHARING the account tables that are shared today** (the exception to the per-env rule):
- **stripe-keys** are mode-split across two SHARED tables (`table_for_mode`: test→`-dev`, live→`-prod`,
  `documents.py:378`) — both wired into every function. → Make per-deployment; `mode` becomes a record attribute.
- **tenant-profiles** DUAL-WRITE at registration (`tenant_profiles_registration_repositories()` writes BOTH
  `-DEV`+`-PROD`, `documents.py:742`) — the "seamless switching" glue. → Remove the dual-write; per-deployment only.

## Target architecture

- **Hostname → backend (release channel):** `app.juniorbay.com → prod`, `sandbox.juniorbay.com → dev`,
  `localhost → Vite proxy`. Tenants only ever use `app` (prod = released code). `sandbox`/dev = **pure software
  staging with its OWN isolated data** — no tenant-test role, no window into prod.
- **A per-tenant Stripe-mode toggle (test/live) WITHIN a deployment.** Each deployment's tables hold BOTH modes'
  data (mode = a record attribute). The toggle flips a `mode` that flows as a request param/header, not a backend
  swap. (`sandbox`/dev also supports both Stripe modes — against its own dev data.)
- **`offer.stripe_mode` stays the source of truth for checkout key selection** (already is, `checkout.py:134`).

## The mode-routing contract (how `mode` flows end-to-end)

1. **Dashboard:** backend base = **hostname-derived** (not the toggle). A new `stripeMode` (localStorage, test|live)
   is sent as **`?mode=`** (or an `X-Stripe-Mode` header) on every tenant-scoped API call. Views key on `stripeMode`.
2. **Backend handlers:** read `mode` from the request; **stamp `stripe_mode` on every create** (offer/page/product/
   order/cart…) and **filter every list/get by `stripe_mode`** so a test-mode dashboard sees only test records
   (and vice-versa) within the same prod tables.
3. **Checkout:** unchanged in spirit — resolves `offer.stripe_mode` → `stripe_keys.get(tenant, mode)` (the keys
   table already spans modes). Just stop baking a mode-specific *host* into the checkout URL.
4. **Webhook:** derive mode from the **event's `livemode`** (test event→test, live→live), NOT the deployment, so one
   prod endpoint processes both. Rework the livemode guard (the dup-order fix) to route-by-livemode instead of
   reject-on-mismatch; dedup stays per events-table.
5. **Published pages / CDN:** publish to the **serving backend's** bucket, **mode-partitioned** (e.g.
   `published/{mode}/{page_id}`), test pages `noindex`; bake a **host-agnostic** checkout URL (mode comes from the
   offer). Custom-domain + platform-hostname serving become mode-aware.

## Subsystem changes

0. **Un-share the account tables + drop the dual-write (the exception to per-env today).**
   - `stripe-keys`: replace the two-shared-table `table_for_mode` design (`documents.py:335-395`) with a
     per-deployment table + `mode` as a record attribute; `get(tenant, mode)` filters within one table.
   - `tenant-profiles`: remove `tenant_profiles_registration_repositories` dual-write (`documents.py:742`);
     registration writes only the local per-env table.
   - Retire the fixed `STRIPE_KEYS_TABLE_DEV/PROD` + `TENANT_PROFILES_TABLE_DEV/PROD` env-var pairs
     (`template.yaml:140-146`) in favor of the per-`Environment` table each function already gets.
1. **Dashboard / api-client** — `client.js`: `getApiBase` from hostname; replace the env toggle with a `stripeMode`
   toggle that adds `?mode=`; `App.vue` keys views on `stripeMode` not `activeEnvironment`; every store's fetches
   pass mode. **Supersedes the just-shipped mode-follows-environment fix** (`stripeKeys.js verifyMode =
   getApiEnvironment()`) — verifyMode becomes the standalone `stripeMode`.
2. **Per-mode data model** — thread `mode` through every tenant-entity handler (offers, pages, products, orders,
   carts, coupons, sites, collections, appointments…): stamp `stripe_mode` on write, filter on read. Decide
   attribute-filter vs a `stripe_mode` GSI for list efficiency (start with filter; add GSI if hot).
3. **Webhook** — `stripe_webhook.py`: mode from `event.livemode`; rework `_mode_for_environment` + the livemode
   guard; point BOTH test and live Stripe webhook endpoints at the prod URL (Stripe dashboard config, both modes).
4. **Publishing + checkout URL** — `publishing.py checkout_base_url_for_page` (`:697`): host-agnostic checkout URL;
   publish per-mode path; test pages `noindex`.
5. **Pages CDN / buckets** — serve test pages from the prod pages distribution under a mode-partitioned prefix (or a
   `test.` sub-path); keep test `noindex`; make custom-domain (`custom_domains_resolve.py`) + platform-hostname
   serving mode-aware. **Trickiest area.**
6. **Env/config plumbing** — `_mode_for_environment` and any `ENVIRONMENT`-derived mode logic replaced by explicit
   mode; keep `ENVIRONMENT` for release-channel concerns only (which code/tables version).

## Phasing

- **P0 — Contract + scaffolding:** a `resolve_stripe_mode(event)` request helper (param/header) + a dashboard
  `stripeMode` store; hostname→backend in `client.js`. No behavior change yet (default mode = live).
- **P0.5 — Un-share account tables:** stripe-keys + tenant-profiles → per-deployment, `mode` as attribute, drop the
  registration dual-write. Migrate the commingled pre-launch account data. (Do early — it's the data-governance fix
  and unblocks treating mode as an attribute consistently.)
- **P1 — Dashboard decouple:** toggle becomes Stripe-mode (adds `?mode=`); backend base hostname-bound; views key on
  mode. (Backend must serve both modes — needs P2 for full effect; until then test mode on prod shows empty.)
- **P2 — Backend per-mode data:** stamp + filter `stripe_mode` across all tenant entities so prod holds both modes.
  The big one; do entity-by-entity with tests.
- **P3 — Webhook mode-from-livemode:** one prod endpoint handles both; Stripe webhook reconfig; guard rework.
- **P4 — Publishing + checkout URL:** host-agnostic checkout; per-mode publish path; test `noindex`.
- **P5 — CDN / serving:** serve test pages on prod (mode-partitioned); mode-aware custom-domain + platform-hostname.
- **P6 — Migration + cleanup:** move the operator's existing test-mode data from dev tables → prod tables tagged
  `test` (low-stakes, all self-owned); retire dev's tenant-test role (dev = pure staging); rebuild the onboarding
  flow (live-first + opt-in Stripe-test sandbox, `plans/` onboarding streamline) on the clean model.

## Migration — CLEAN-SLATE CUTOVER (chosen 2026-08-02)

All current data is the operator's own disposable test data, so we **do NOT write migration/back-compat code**.
Build every phase against the **target schema only** (per-env tables, `mode` as attribute); keep the current app
running on current data throughout the build; then at **cutover**: tear down + recreate the tables via the SAM
stack (or scan-delete), **clear the pages S3 buckets**, **re-seed config** (global billing config, tier policies),
and **re-onboard** the handful of test tenants in the new model. **Cognito is untouched** (logins survive; profiles
re-create via registration). Optionally clean Stripe test data. This removes the P0.5/P6 migration burden entirely
— they become "define fresh tables + re-onboard," not "write and debug a data migration." One-time re-setup chore:
re-run Stripe Connect OAuth per mode + re-add custom domains to the resolver.

## Risks / tricky bits

- **Webhook reconfiguration** (P3): both test + live Stripe events must reach the prod endpoint; verify the livemode
  routing + the existing per-env dedup still prevents the cross-env double-processing the earlier guard fixed
  (see [[project_webhook_mode_guard]]).
- **CDN/serving** (P5): serving test pages on prod without leaking them into indexing or colliding with live slugs;
  reuse the custom-domain resolver + platform-hostname worker, made mode-aware.
- **Breadth of P2:** many handlers touch tenant entities; risk is missing a read path that then leaks cross-mode
  data. Mitigate with a shared mode-filter helper + tests per entity.
- **Supersedes recent work:** the mode-follows-environment dashboard fix is folded/rewritten here.

## Relationship to other plans

- **Prerequisite for the clean onboarding streamline** (live-first + opt-in Stripe-test sandbox) — that flow assumes
  test runs on prod, which only exists after this.
- Independent of but complementary to `plans/SAAS_BILLING_PAYWALL.md` (billing mode is a third, separate axis —
  "how Junior Bay bills the merchant" — already distinct in stripe-cart's design; don't conflate).
- stripe-cart reference: `stripe-cart/plans/SAAS_BILLING_PAYWALL_PLAN.md` explicitly separates "billing mode" from
  "storefront/payment mode" — the same separation-of-axes principle.
