# Decouple Stripe mode (test/live) from platform environment (dev/prod)

Status: **COMPLETE (P0–P6) — merged to `main`, deployed, and cut over in prod (2026-08-02).** Design 2026-08-02.
Foundational re-architecture, done **pre-launch**. Built on feature branch `stripe-mode-decoupling` (now merged to
`main` — the "(branch)" labels in the phase log below are **historical**). **The prod cutover was executed and
verified 2026-08-02** (commit `774aaa3`): a Stripe-**test** purchase completed on the **prod** backend
(`app.juniorbay.com`), and both Stripe webhook endpoints were repointed at prod with per-mode signing secrets.
Test-mode data now lives on the prod tables (`OFFER#test#…`, `PAGE#test#…`).

**The migration is done; the CONSEQUENCE is not.** "Nothing left to do here" stood until 2026-09-23, when the
risk this plan had already written down came true twice in one afternoon — see **P7** at the end.
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
- **P4 DONE** (branch): `checkout_base_url_for_page` host-agnostic (single `PUBLIC_CHECKOUT_BASE_URL`, no dev/prod
  split); the offer's `stripe_mode` rides the Buy URL as `?mode=` (`build_checkout_url` + `checkout-mode` data attr
  + JS `checkoutHref`), closing P2's checkout loop. Threaded mode through every on-page money path (listicle cart
  add/remove/checkout/hydrate, post-purchase upsell session+charge for both islands, booking reserve+checkout, lead
  capture). `page_publish` (stream) builds its mode-scoped repos PER RECORD from each page's `stripe_mode`.
- **P5 DONE** (branch): `artifact_paths(mode=…)` — live keeps the root key (byte-identical), test goes under a
  `test/` prefix (default "live" so un-updated callers fail-safe to a 404, never a cross-mode serve). Write side
  (publish/delete/register_page_route) derives mode from the page; read side (custom_domains_resolve + platform,
  routes_resolve, test_page_serve, experiments_resolve, post_checkout) from each record/request. Domain index +
  route records carry `stripe_mode`. Test-mode pages forced `noindex`. page_render + dashboard preview/published URL
  builders mode-aware. The Cloudflare Worker is unaffected (it serves the resolver's origin_url). 1335 pass.
- **P5 follow-ups DONE** (branch): standalone `/book` page (booking_page.py) threads the service's mode into its
  availability/reserve/checkout JS; audited every on-page `fetch()` (html.py + booking_page.py are the only two
  sources) — the inline booking widget's availability GET was the last one defaulting to test, now fixed. No
  mode-sensitive on-page fetch defaults to test anymore.
- **Cutover SCRIPT DONE** (branch): `scripts/mode_decoupling_cutover.py` — jb--prefix guard + preserve allow-list +
  backup-first + dry-run default + dev-first (`--allow-prod`). Invariants locked by tests/test_cutover_classification.py.
- **P6 DONE (cutover, 2026-08-02, commit `774aaa3`)** — operational: ran the cutover script (dev then prod),
  re-onboarded, re-ran Stripe Connect OAuth per mode, re-added custom domains, and pointed both Stripe webhook
  endpoints at prod with per-mode signing secrets. **Verified:** a Stripe-test purchase completed on the prod backend
  (`app.juniorbay.com`); test-mode data now lives on the prod tables.

## The problem — mode and infra are conflated

Two orthogonal concepts are currently ONE switch:
- **Platform environment (dev/prod)** = software release channel (dev = unreleased/staging code, prod = released).
  Should be a *platform-team / hostname* concern.
- **Stripe mode (test/live)** = Stripe's test ("sandbox") vs live keys/transactions. Should be a *per-tenant*
  toggle available **within** the production app.

Today they're the same toggle:
- Dashboard test/live swaps the **whole backend base URL** — `test→dev.juniorbay.com`, `live→prod.juniorbay.com`
  ([client.js:1-8](../dashboard/src/api/client.js#L1)); no `mode` param, a different backend. No hostname
  binding — it's purely `localStorage["stripeLinkVueEnvironment"]` ([client.js:40](../dashboard/src/api/client.js#L40)).
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

## Serve-host naming + config-driven URLs (decided 2026-08-19)

**The bug that surfaced this.** `test.juniorbay.com` is hardwired to the **dev** backend (API `jm3ppyxos4`, stage
`dev`) and the dashboard **hardcodes** `TEST_PAGES_HOST = "test.juniorbay.com"` for *all* test-mode preview/publish
links in BOTH dashboards. So **app (prod) + test mode** points its preview links at the **dev** viewer, which reads
the **dev** buckets — but the prod backend writes its test-mode artifacts to the **prod** buckets → prod test-mode
previews are misrouted (a single-stage legacy from when test *was* the dev environment). Sandbox+test only works by
coincidence (all-dev).

**Principle: no hardcoded serve URLs — they come from `app_config` per channel.** This already holds for
`api_base_url` / `pages_base_url` / `pages_preview_base_url`; `TEST_PAGES_HOST` is the straggler. Split config into
two kinds:
- **Operator-tunable** (flags, business knobs) → hand-editable DynamoDB.
- **Infra identities** (CloudFront domains, API endpoints, serve hosts) → their canonical source is the **stack
  outputs**, so the **deploy populates `app_config` from them** — never hand-typed. (Hand-editing infra values is
  error-prone: proven 2026-08-19 when a hand-write of `pages_preview_base_url` landed under a bogus `config` key and
  silently did nothing until caught.)
- **Bootstrap exception:** the dev/prod **API base** stays hardcoded in `client.js` (the minimum needed to *fetch*
  `app_config`); everything downstream is table-driven.
- Terminology: **stage** = `dev`/`prod`/(future)`staging` (release channel / `Environment`); **mode** = `test`/`live`
  (Stripe mode). Never call test/live "environment" — that name already means dev/prod.

**Host scheme: `{stage}-{mode}.juniorbay.com`.** Stage token is `dev`/`prod` (NOT `app`/`sandbox` — those are the
*dashboard* hosts; keeping serve hosts on `dev`/`prod` avoids collision AND matches the `app_config` keys + stack
`Environment` so the deploy auto-populates with zero mapping). The **path** carries the artifact kind (`/preview/`
vs `/published/`) + id; **mode is in the host, NOT repeated in the path.**

| Host | Stage | Mode | Appears in |
|---|---|---|---|
| `dev-test.juniorbay.com`  | dev  | test | sandbox dashboard, test mode |
| `dev-live.juniorbay.com`  | dev  | live | sandbox dashboard, live mode |
| `prod-test.juniorbay.com` | prod | test | app dashboard, test mode |
| `prod-live.juniorbay.com` | prod | live | app dashboard, live mode |
| *(future)* `staging-test` / `staging-live` | staging | test/live | — |

**Mechanics (see `plans/SERVE_HOST_SCHEME.md` for the concrete build plan).** The pragmatic slice **reuses the two
serving front-ends that already exist**, one host per stage×mode — no unification, no CloudFront rewrite Function:
- **`{stage}-live`** → that stage's **CloudFront preview distribution** (full-path artifact) — the mechanism
  `preview.juniorbay.com` already uses.
- **`{stage}-test`** → that stage's **`TestPageServeFunction`** (regional API Gateway custom domain, short_code →
  artifact + `/sale`//`/flash-sale` variants) — the mechanism `test.juniorbay.com` already uses; the **prod** stack's
  copy just needs a custom domain (that's the misroute fix).
- Two cert stories by mechanism: CloudFront hosts use the **us-east-1** `*.juniorbay.com` wildcard; API Gateway
  regional hosts use the **us-west-2** `*.juniorbay.com` wildcard (both already exist and in use).
- De-hardcode: replace `TEST_PAGES_HOST` in `LandingPages.vue` with an `app_config`-driven `getTestPagesHost(channel)`
  (same shape as `getPreviewPagesBaseUrl`); add per-channel serve-host keys to `app_config`, **deploy-populated from
  stack outputs**.
- A *later, optional* unification (all previews onto the dist, drop the short_code viewer) is what would need a
  CloudFront host→prefix Function — deferred, not required.

**Supersedes the interim `preview.juniorbay.com`.** The prod-live preview host shipped 2026-08-19 as
`preview.juniorbay.com`; under this scheme it becomes **`prod-live.juniorbay.com`**. When implementing, either
rename it or keep `preview.juniorbay.com` as a legacy alias to avoid breaking any copied links. Likewise
`test.juniorbay.com` → `dev-test.juniorbay.com` (keep a redirect if any short links exist).

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
  Implements the **serve-host naming + config-driven URLs** section above: the `{stage}-{mode}.juniorbay.com` hosts,
  the CloudFront host→prefix Function, de-hardcoding `TEST_PAGES_HOST` into `app_config`, and deploy-time population
  from stack outputs. Fixes the prod-test preview misroute noted there. A cheap early slice of P5 can land the four
  hosts + config indirection *before* the full backend per-mode work, since it's additive.
- **P6 — Migration + cleanup — DONE 2026-08-02:** moved the operator's test-mode data onto the prod tables tagged
  `test`; retired dev's tenant-test role (dev = pure staging); the onboarding flow was rebuilt (live-first + opt-in
  Stripe-test sandbox) on the clean model.

## Migration — CURATED SELECTIVE WIPE (revised 2026-08-02 — supersedes "truncate all tables")

All per-tenant content is the operator's disposable test data, so we **do NOT write migration/back-compat code**;
build every phase against the target schema only. BUT the cutover is **NOT a blanket truncate / stack teardown** —
some tables hold platform reference data that must survive (operator flagged the categories table). Two facts make
a surgical wipe both necessary and easy:
- **Only `StripeKeysTable` has a key-schema change** (the P0.5 `mode` sort key), so a normal `sam deploy` replaces
  just that one table (fine — Stripe keys re-onboard). **Every other table is schema-unchanged** — mode-in-key uses
  the SK *value*, not a new key attribute — so a deploy preserves all their data. No teardown is needed to ship.
- "Clean slate" = a **selective scan-delete of the WIPE list only**; PRESERVE tables are never touched.

**PRESERVE (platform reference/config, NOT per-tenant test data — NEVER wipe):**
- `product-categories` — shared cross-tenant taxonomy (grows per seller, feeds AI product creation). Irreplaceable.
- `app-config` — deployment config (API base URLs, CDN/pages domains). Platform-global.
- `tier-policies` — fee-tier reference. `themes` — theme/preset data (reserved).
- (NOT a table: the global billing config lives in S3 `BILLING_CONFIG_BUCKET/global_billing_config.json` + a code
  default `DEFAULT_GLOBAL_BILLING_CONFIG` — leave that S3 object in place.)

**WIPE (per-tenant test content / accounts / transactions / funnel artifacts — re-created on re-onboard):**
products, offers, coupons, pages, sites, collections, carts, checkout-sessions, invoices, services, experiments,
orders, customers, lead-capture, reviews, notifications, refunds, routes, custom-domains, media, document-events,
webhook-events, ledger, calendar-connections, stripe-keys, tenant-profiles, user-profiles, user-preferences,
shipping-config, **platform-config** (misnamed — holds per-tenant TenantConfig).

**REVIEW before wiping (per-tenant but may hold hand-authored content):** `legal-pages` (hand-written ToS/privacy?),
the media S3 bucket (uploaded images).

**SCOPE GUARD — `jb-` prefix ONLY.** stripe-cart (legacy) and stripe-link coexist in the same AWS account with
names that differ only by the prefix (stripe-cart `platform-config-{env}` = GLOBAL system themes/Connect config;
stripe-link `jb-platform-config-{env}` = per-tenant tenant_config — DIFFERENT tables). The WIPE list above is the
**`jb-`-prefixed** stripe-link tables; the cutover script MUST refuse any table name not starting with `jb-`
(mirror `assert_jb_resource_name`) so it can never touch a stripe-cart table. All names below are `jb-<name>-<env>`.

**Cutover steps:** (1) **Back up every table first** — full scan-dump to JSON in S3 (cheap insurance, nothing
unrecoverable). (2) Selective scan-delete of the WIPE-list tables only. (3) Clear the **pages + preview** S3 buckets
(published artifacts, disposable); leave the billing-config bucket + (per review) media bucket. (4) Re-onboard the
handful of test tenants in the new model; **Cognito untouched** (logins survive; profiles re-create via
registration). (5) Re-run Stripe Connect OAuth per mode; re-add custom domains to the resolver; point both Stripe
webhook endpoints at prod with both per-mode signing secrets. (6) Optionally clean Stripe test data.

**Connect OAuth redirect-URI registration (per backend-host × mode).** Because both modes now run on each
backend, each backend's callback (`https://{dev|prod}.juniorbay.com/stripe/connect/callback`) must be registered
on BOTH Connect apps (TEST `ca_…IC0J4`, LIVE `ca_…Opkh4`). The old model only registered test→dev + live→prod, so
add the missing two in the Stripe dashboard: **dev callback → LIVE app** (live-onboard on dev; was the dev
re-onboard blocker) and **prod callback → TEST app** (test-onboard on prod). Purely Stripe app config, not code.

## Risks / tricky bits

- **Webhook reconfiguration** (P3): both test + live Stripe events must reach the prod endpoint; verify the livemode
  routing + the existing per-env dedup still prevents the cross-env double-processing the earlier guard fixed
  (see [[project_webhook_mode_guard]]).
- **CDN/serving** (P5): serving test pages on prod without leaking them into indexing or colliding with live slugs;
  reuse the custom-domain resolver + platform-hostname worker, made mode-aware.
- **Breadth of P2:** many handlers touch tenant entities; risk is missing a read path that then leaks cross-mode
  data. Mitigate with a shared mode-filter helper + tests per entity.
- **Supersedes recent work:** the mode-follows-environment dashboard fix is folded/rewritten here.

## P7 — the read paths that were missed (2026-09-23)

### The root cause is not "a read path was missed"

That was the first framing written here, and it is too kind. The author's, which is correct
(2026-09-23): **the old architecture was ported to the new one instead of being rewritten for it.**

Under the old model, `environment == mode`: prod WAS live, dev WAS test. Isolation was free — a
structural property of having separate stacks and separate tables, impossible to get wrong because
nobody had to do anything. The decoupling **removed that invariant** and replaced it with one every
reader must uphold by hand. Code written before the change kept compiling, kept passing tests, and
silently stopped being correct.

The history says so plainly. The decoupling landed **2026-08-02**; every repository that leaked was
written before it:

| repository | written | mode support added |
|---|---|---|
| `notifications_repository` | 2026-05-29 | **2026-09-23** (7 weeks late) |
| `review_invites_repository` | 2026-07-23 | **2026-09-23** (7 weeks late) |
| `orders_repository` | 2026-07-03 | 2026-08-02, revisited 2026-09-20 |
| `ledger_repository` | 2026-07-07 | 2026-08-02, revisited 2026-09-20 |

And the retrofit took **three passes** — `0cfef7c` + `869d12a` (2026-08-02), then `af18e0c`
("mode isolation: test money must never be read as real money", 2026-09-20), then this one. Each pass
found more, because each was **by inspection**: someone thought of a table, fixed that table, and
stopped. Nobody enumerated the class.

This plan's own Risks section had already named the shape of it:

> **Breadth of P2:** many handlers touch tenant entities; risk is missing a read path that then leaks
> cross-mode data. Mitigate with a shared mode-filter helper + tests per entity.

Neither the helper nor the per-entity tests were built, so inspection was the only method available.

### What the decoupling actually obliges

One prod endpoint serves both Stripe modes, so **a tenant's TEST activity writes to the PROD tables.** That
is the design working. It means the isolation cannot live in the infrastructure any more — it has to be
enforced by **every reader of every shared table**, forever, including tables that do not exist yet. A new
table is isolated only because someone remembered.

### The two that were missed

| | what leaked | consequence | mechanism used to fix |
|---|---|---|---|
| **notifications** | 9 unstamped rows in `jb-notifications-prod`, all from test orders | "New sale" in the production bell, indistinguishable from money | **attribute filter** |
| **review invites** | 4 invites in `jb-reviews-prod`, every one from a `cs_test_` session, 3 still active | a `rate(15 minutes)` sweep **emailing a real customer** about a product they never bought — one already delivered | **key partition** |

**The two mechanisms are deliberately opposite, and the reason is worth keeping.**

- Notifications needed their existing rows to stay *readable as test*. Key-partitioning would have moved
  the sort key and made all nine unreachable in **both** modes. So: stamp `mode` on write, filter the
  attribute on read, and treat an unstamped row as **test** — under-reporting activity is recoverable,
  showing test money as real is not.
- Review invites needed the opposite: the four existing ones had to become **invisible to the sweep**,
  because the sweep sends email. Key-partitioning does exactly that, with no data deleted and nothing
  emailed again. It also matches the abandoned-cart sweep, which had already settled this question:
  read `mode="live"` only, because a test purchase must never cause a real person to be contacted.

**So the rule is not "always partition" or "always filter". It is: decide what should happen to the rows
that already exist, and pick the mechanism that produces it.**

### The audit (every prod table, 2026-09-23)

Isolated and correct: orders, ledger, invoices, checkout sessions, customers, carts, pages, products,
offers, sites, routes, stripe-keys, custom-domains.

Deliberately mode-agnostic, verified not leaks:

- **leads** — documented in `handlers/leads.py` as CRM records; the offer/product context they capture is
  read in the request's mode.
- **purchase throttle** (in the carts table) — abuse control, keyed by contact hash.
- **page views** — the rows are TTL'd `VISITOR#<hash>` dedup keys; the actual counts live on mode-scoped
  page and experiment documents.

Also worth recording: **prod has never processed a real transaction.** Every order, ledger entry, invoice,
checkout session and customer in prod is test. That is why cleaning up the test data was declined — it is
the only evidence the fixes work, and deleting it this morning would have left nothing to audit and the
review-invite leak still running.

### The field names disagree, and it cost a misdiagnosis

`orders` stamp **`stripe_mode`**. `ledger` and `notifications` stamp **`mode`**. Scanning production for
`stripe_mode` therefore reported every ledger row as unstamped, and the ledger was briefly and wrongly
blamed. It is correct and always was.

Left as-is rather than renamed — a rename touches stored documents on a money path for cosmetic gain —
but **anyone auditing must check both spellings**, and anyone adding a table should prefer `mode` (two of
three, and what `LedgerRepository`/`ModeScopedNotificationsRepository` already read).

### Before adding any table that both modes write to

1. Does its repository take a `mode`?
2. Does every **reader** pass one? (Both bugs were callers not passing a mode the repository already
   accepted — `ledger_repository` had taken one for weeks.)
3. Does an **unstamped** row read as test?
4. If anything **sends** from it — email, SMS, a webhook out — is that sweep `mode="live"` only?
5. Is there a guard test that scans the handlers, rather than a list someone maintains?

### The guard tests, and what they do not cover

`tests/test_notification_mode_isolation.py` scans every handler for an unscoped
`notifications_repository()` or `review_invites_repository()`, derived from the source. Both were proven to
bite by removing a `mode=` and watching them fail by name.

**They are per-repository, which is the same mistake one level up.** A guard that names
`notifications_repository` and `review_invites_repository` is inspection with a test around it. It
protects the two instances already found and nothing else.

**Proof, from the same afternoon:** `refund_requests_repository` writes to the SAME notifications table
that was just fixed, takes no mode, and handles money. Fixing notifications and not noticing its
neighbour is precisely the failure being described — committed by the person writing this section, an
hour after diagnosing it.

### Latent, not yet leaking (2026-09-23)

Twenty-four repository factories still take no `mode`. Most are legitimately mode-agnostic — app config,
user profiles, OAuth states, slot locks, legal pages, product categories. **Three are not, and are
latent only because the tables are empty or the feature is unused:**

| repository | table | why it matters |
|---|---|---|
| `refund_requests_repository` | notifications | money, and shares the table just fixed for notifications |
| `refunds_repository` | refunds | money; `jb-refunds-prod` is empty **today** |
| `reviews_repository` | reviews | a test purchase could publish a review on a live storefront |

These are predictions, not observations — no leak has occurred. They are recorded so the next pass is an
enumeration rather than a fourth round of inspection.

## Relationship to other plans

- **Prerequisite for the clean onboarding streamline** (live-first + opt-in Stripe-test sandbox) — that flow assumes
  test runs on prod, which only exists after this.
- Independent of but complementary to `plans/SAAS_BILLING_PAYWALL.md` (billing mode is a third, separate axis —
  "how Junior Bay bills the merchant" — already distinct in stripe-cart's design; don't conflate).
- stripe-cart reference: `stripe-cart/plans/SAAS_BILLING_PAYWALL_PLAN.md` explicitly separates "billing mode" from
  "storefront/payment mode" — the same separation-of-axes principle.
