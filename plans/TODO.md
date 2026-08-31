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

## Security

### ⭐⭐ stop returning the Connect OAuth token ciphertext to the browser — SHIPPED dev+prod 2026-08-30 (175bce7)

`SENSITIVE_FIELDS` (src/stripe_link/security.py) is a DENYLIST that never grew with the
schema. It lists only the BYO-key era fields:

    secret_key, secret_key_ref, webhook_secret, webhook_secret_ref

When Connect OAuth was added later, `connect_access_token_ref` and
`connect_refresh_token_ref` were introduced (encrypted at stripe_connect.py:274,281) but
nobody added them to the list. So `redact_sensitive_fields` runs on every response path,
dutifully masks the four fields it knows about, and passes the two Connect refs through
in full KMS ciphertext.

Three endpoints ship them to the dashboard:

  - stripe_keys.py:34,51        GET/PUT /stripe/keys
  - stripe_connect.py:315,328,356  connect status
  - billing.py:63              /billing/connect-card

Severity: NOT directly exploitable — the values are `kms:v1:` envelope ciphertext and
decrypting needs KMS permission the browser does not have. But these are the tenant's
Stripe OAuth tokens, the highest-value credential in the system, and they have no reason
to leave the backend. One over-broad key policy, one log sink, or one support screenshot
away from mattering. Treat as defence-in-depth, not an active incident.

NOT a problem, for the record: `publishable_key` (pk_live_...) appears in these payloads
and is meant to be public — it ships in every checkout page's client JS. Nothing to
rotate there.

DONE (175bce7): both fields added to SENSITIVE_FIELDS. The naive two-line version would
have introduced a WORSE bug -- stripe_connect.status_handler spreads the client body into
its write (**document), so once a mask exists any caller echoing back a redacted GET would
persist "********" over the stored ciphertext and destroy the connection. So the restore
guard is now shared and driven by SENSITIVE_FIELDS itself (security.restore_redacted_fields),
applied in both stripe_connect.py and stripe_keys.py. tests/test_secret_redaction.py pins
the whole field set so the denylist cannot drift again. Confirmed on sandbox and prod:
refs read "********", and saving keys leaves the account connected.

STILL OPEN (the better fix): invert to an ALLOWLIST — build responses from the fields
the UI actually needs rather than subtracting the ones it must not see. A denylist fails
silently and invisibly every time the schema grows, which is exactly what happened here.
Pairs naturally with hiding the raw JSON panels (below).

### MEDIUM — audit for silent agreement failures (framing agreed 2026-08-30)

Not a general bug hunt. Every defect found on 2026-08-30 shared one shape: TWO THINGS THAT
MUST AGREE, WITH NOTHING FORCING THEM TO. All four were silent -- no error, no failing test,
no broken build. Three shipped to prod.

  1. styles.css had an unterminated `/*`. A CSS comment runs to the next `*/`, 65 lines
     later, so nine rules were commented out. Valid CSS, so the build passed. (e65a4e6)
  2. MediaListField bound :disabled="busy" with busy = ref(""). Vue's includeBooleanAttr
     treats "" as TRUE for boolean attributes (HTML disabled="" means disabled), so every
     button was permanently disabled. (d4b1d35)
  3. SENSITIVE_FIELDS was a denylist that never grew with the schema. Connect OAuth token
     refs added later were never listed, so they shipped to the browser in full ciphertext
     on three endpoints. (175bce7)
  4. schemas/UserPreferences.schema.json declares additionalProperties:false and other
     constraints that NOTHING enforces -- the file is never loaded at runtime or in tests,
     and the hand-written validator does not police unknown keys.

The audit is therefore mechanically searchable rather than open-ended. Look for:

  - hand-maintained lists that mirror a schema or document shape (denylists, allowlists,
    field tuples, enum copies) with no test pinning them together
  - schemas/*.schema.json files that nothing loads -- which ones are enforced, which are
     merely aspirational documentation? Say so in each file.
  - build/lint steps that accept malformed input silently. CSS is the known one; check
    whether the Vue/Vite pipeline warns on anything comparable.
  - client-side copies of server-side constants (see the Phase 2 warning in
    plans/DEVELOPER_MODE.md -- the diagnostics bundle must reuse SENSITIVE_FIELDS, not
    restate it)
  - boolean-ish bindings where the falsy value is "" or 0 rather than false

The cure already exists in the repo and generalises: OfferSemanticModel pins its validator
to its schema with a test (domain/semantic_schema.py:5; documents.py:1764 -- "the validator
IS the schema"). Adopt that wherever a second source of truth is found, or delete the
second source.

Caveat for whoever picks this up: the density found on 2026-08-30 partly reflects that one
area was being read very closely that day. Do not assume it is uniform across the codebase
-- sample broadly before concluding anything about overall quality.

### MEDIUM — stop storing credentials nothing reads (audit stripe_keys document, 2026-08-30)

Fallout from the redaction fix: three credential fields on the stripe_keys document are
written and never consumed. Each is blast radius with no upside.

  connect_access_token_ref   written stripe_connect.py:274, read NOWHERE
  connect_refresh_token_ref  written stripe_connect.py:281, read NOWHERE
  webhook_secret_ref         written/redacted in stripe_keys.py only; signature
                             verification uses get_platform_webhook_secret
                             (stripe_webhook.py:66,152,182), never the tenant's

Why they are unused: connected tenants call Stripe with the PLATFORM secret key plus a
Stripe-Account header (checkout_credentials, stripe_platform_secrets.py:136-149), and
Connect webhooks arrive at the platform endpoint signed with the platform secret. Note the
Standard-account OAuth access_token is effectively a live secret key for the connected
account, so this is real credential material, not a token of convenience.

Still genuinely used, do NOT remove:
  secret_key_ref    the BYO-keys fallback path for tenants who never connect via OAuth
                    (checkout_credentials' second branch). Unused by CONNECTED tenants
                    only. Retiring it is a product decision about whether BYO onboarding
                    stays supported -- not a cleanup.
  publishable_key   BNPL on-page messaging (publishing.py:897, html.py:1348/1433/2392);
                    documents.py:1325 also requires it OR connect_account_id to validate.

Decide per field: stop persisting it, or write down why it is retained (e.g. refresh
tokens kept for a future token-refresh flow). Whatever is kept stays in SENSITIVE_FIELDS.

Prereq/related: the allowlist rewrite in the HIGH item above -- doing both together means
touching the response shape once.

### MEDIUM — pre-launch QA: lead-capture end-to-end verification

The lead rail is more complete than assumed (see FORM_BUILDER.md §2.5 correction), so this is
VERIFICATION, not repair. Exercise each shipped action against a published page, not just the dashboard:

  capture_email / capture_phone / capture_email_phone
    - submit valid -> lead lands in LeadsTable and appears on the Leads screen
    - omit a required field -> server rejects (client attrs bypassed; post directly)
    - send an undeclared field -> silently dropped, not stored
    - email without "@" and phone without a digit -> rejected
    - oversize: >25 fields, >2000-char value -> rejected
    - honeypot filled -> HTTP 202 accept-and-drop, nothing stored
    - same idempotency_key twice -> one lead, second returns "duplicate"
    - both GDPR opt-ins recorded correctly, independently
  call_number / external_url
    - CTA renders and navigates
    - KNOWN: neither records a lead (tel:/redirect only), so nothing reaches the Leads screen.
      Confirm that is intended -- call tracking is how lead-gen businesses in these verticals
      actually measure, and its absence may be a product gap rather than a QA finding.

KNOWN DEFECT, do not re-report: fields render with placeholders derived from the field name and no
<label>. Live in production, fixed by FORM_BUILDER P0/P1.

### LOW — revisit image-processing: utility micro-service vs. a real media service (noted 2026-08-30)

`../sam/image-processing` (see docs/EXTERNAL_SERVICES.md) is a thin utility: presign, copy, resize
photos with sharp. Non-images are stored and served verbatim -- no transcode, no adaptive streaming.

Fine for hero video. NOT fine for the online-course direction the author intends it to carry:

  - no transcode -- every student streams the tenant's original file at full bitrate, no adaptive
    quality, no bandwidth ladder
  - `/upload/multiple` is presigned-POST only; the multipart branch exists in createUpload.js but is
    not on the path stripe-link uses. S3 caps a single POST at 5GB, and reliability degrades long
    before that on a phone
  - no HLS/DASH packaging, no thumbnails/poster frames, no duration or dimension metadata for video
  - no signed/expiring playback URLs, so course video would be as public as a hero clip

Decide then whether to grow this service (MediaConvert + HLS + packaging) or adopt one (Mux,
Cloudflare Stream, api.video). Buying is likely cheaper than building an encoding ladder, but it
changes where tenant media lives -- an architectural call, not a feature.

Not urgent: nothing about the current design blocks either path, and the size ceilings are now
deploy-time parameters rather than code (b7a0f27 in that repo).

### Form Builder — plan plans/FORM_BUILDER.md, 2026-08-30, not built

An EXTENSION of lead capture, not a new subsystem: `lead_capture.fields[]` is already declared,
validated and rendered, and `lead_submission.fields` is already a free-form dict, so richer forms need
NO storage change. Decision: NO `Form` entity -- the Product is already the reusable unit, and a field
list is "what is collected", which the offer/product rule puts on the product.

Found while planning:
  - `field.type` is not an enum (any string validates; the renderer silently falls back to "text")
  - every field renders as `<input>` -- no textarea/select/checkbox/radio
  - labels are DERIVED FROM THE FIELD NAME and used as placeholders. That is a live accessibility
    defect in shipped code, not just a missing feature -- it affects today's email capture
  - no dashboard UI at all (stores/products.js hardcodes the field list per action)
  - submissions are NOT validated against declared fields; `required` is client-side only

Multi-step (quiz-funnel) forms are FIRST-CLASS, not deferred (plan 4a): one question per screen, card
options, auto-advance, contact last. A flat form is just one step, and `fields[]` normalizes to
`steps:[{fields}]` so there is no migration. Get the nesting into the schema at P0 -- retrofitting steps
into a flat renderer means rebuilding it. `form_id` is inert (written, never read): remove the prompt
rather than auto-generating a value, since product_id already identifies the form.

Resilience/"continue later" = a CLIENT-SIDE localStorage draft (TTL, cleared on submit), NOT server-side
partials: "save but don't use" fails under GDPR because storage is processing (Art. 4(2)), and partial
rows would pollute the leads list and entitlement gate. Cross-device resume needs an identifier, so it is
only reachable post-contact -- i.e. the already-consent-clean abandoned-funnel capture. Drafts MUST be
tenant-namespaced: every creator page shares the jbay.page origin in the VISITOR's browser, same hazard
as the sl_cart_id_* keys.

P3 EXTENDS the existing validator: `validate_and_extract_fields` (domain/leads.py:48) already enforces
declared-only, required-present, email/phone shape and size caps. `options[]` membership for
select/radio must ship WITH that renderer -- an unconstrained choice field is a free-text field in
disguise. Retires `open_form` + `form_id`, which with
`social_redirect` takes the action vocabulary from seven to five, both by removal.

### ⭐ HIGH — Builder section order: make the form the page map (plan plans/BUILDER_SECTION_ORDER.md, 2026-08-30)

Invariant to create: THE BUILDER FORM READS TOP-TO-BOTTOM IN THE SAME ORDER THE PAGE RENDERS. cart has
this; link does not, and two attempts to bolt ordering on without it both shipped and both are wrong --
the Section order list (4f1fe07) is correct but invisible, and the form-block handles (e5428e3) are a
ghost drag where the page reorders but the dragged block does not move.

Three groups, not two: SETTINGS (favicon/theme/colours/SEO/analytics -- not sections at all, no
position), FIXED SECTIONS (countdown, hero+H1, footer), DRAGGABLE (everything else incl. element cards,
index 0 = first after hero). Maps onto the placement bands already shipped in 6f2676d. Settings are
currently INTERLEAVED with sections, which is much of why order is unreadable.

Also re-phrases the semantic rule: "the FIRST pinned_top section carries the H1 and is the LCP element",
not "the hero does" -- a heroless quiz page (FORM_BUILDER §4a) must still have a defined H1 owner.

Also defines a RESEARCHED BASELINE order (plan 4a) so tenants need not reorder anything: trust badges
move beside the price/CTA (seals work at the moment of commitment, not a screen away), and elements get
a default sequence at all -- today it is insertion order, so adding FAQ before testimonials pins FAQ
first forever. Deliberately does NOT move price/CTA above the fold: checkout_cta is non-repeatable, so
the single ask belongs after the persuasion. The baseline lives as default_order per offer_type with
per-goal overrides in composition_rules.json; page.goal already encodes traffic temperature. Goal stays
on the PAGE (one offer can have a cold-ads page AND a bio page) and is DERIVED from the offer when
unset, never stored twice.

Replaces both earlier attempts. Reshapes the most-used screen, so sandbox-soak before prod.

PHASE 2 (agreed 2026-08-30, not built): compact rows + MODAL editing. Phase 1's rows are expanded
editors, which leaves a long page as metres of form and -- decisively -- makes tall cards undraggable: a
testimonials section with 20 items is a ~2000px card you cannot drag without scrolling mid-gesture. Rows
become handle/name/summary/Edit/Remove; editing happens in a modal and ONLY there, so there is no
inline-vs-modal split. Adding opens the same modal empty, so Cancel creates nothing and empty cards stop
existing (superseding 6ce24e1).

### ⭐ HIGH — Social Media Pages (link-in-bio) — plan plans/SOCIAL_MEDIA_PAGES.md, 2026-08-30, not built

The "Social page" lead-capture action was a placeholder for this and is currently WRONG:
`Offers.vue:1214` handles `social_redirect` in the SAME branch as `external_url` and emits
an identical CTA contract, so it is a duplicate of "Go to URL" with an unread `platform`
field. The intent was a creator link-in-bio page (Stan / juicy.bio / linkcloud).

Key finding: this is a COMPOSITION, not a new page type, and a ZERO-primary-offer (storefront-shaped)
page -- so it needs no exception to "one primary offer per page". That rule is now stated precisely in
PAGE_COMPOSER.md § Cardinality after the loose "one offer, one landing page" wording caused the same
design conversation three times. `seller_profile` already renders
identity + social links, `catalog_grid` is repeatable and already resolves each card's own
offer, and the avatar tokens exist. The gap is that every offer_type composes to one
`checkout_cta`; nothing pairs an identity header with a repeated per-destination grid.

GAP found while planning (plan 8a): `catalog_grid` cards are internal-only by design
(`internal_href(slug)`, for crawlable subfolder authority), so a creator's external links cannot be
cards. Resolved with a separate external-only `link_cards` element rather than adding a url field to
`catalog_grid` -- keeps the SEO contract intact and gives the §7 trust policy one enforcement site
instead of two that must agree.

BLOCKERS found while planning:
  - `same_as` has NO dashboard UI — validated, never enterable. Nothing works until P0.
  - `same_as[].verified` is READ (html.py:3256, 4050) but SET NOWHERE, so no social link
    renders today and "verified" is self-assertable — the anti-impersonation guarantee does
    not currently exist. Same silent-drift shape as the SENSITIVE_FIELDS denylist.

Trust model reuses the existing "reputation-isolation floor" (html.py:1193): verified
business links render + feed sameAs; tenant overrides render nofollow but NEVER enter
sameAs, and are blocked at publish on platform hosts. Gate on `on_custom_domain`, NOT on a
plan tier (landing pages are free-forever post-pivot).

Vanity URL DECIDED 2026-08-30: `jbay.page/username` (path-on-apex, $10.20/yr). Top constraint
is surviving Instagram/TikTok link filters -- `.cc` was the front-runner until testing found it
blocked. `.page` is HSTS-preloaded at TLD level (Google Registry, like .app/.dev) so abuse never
concentrated there. Two consequences are now REQUIRED, not optional: namespace the localStorage
cart keys by tenant_id (all creator pages share one origin), and reserve a path wordlist before
the first username is claimed.

Also supersedes: retire `social_redirect`; decide whether `open_form` gets a renderer or is
removed (see the form-builder plan, to be written).

### ⭐ HIGH — Developer Mode: hide the raw JSON panels (plan: plans/DEVELOPER_MODE.md, 2026-08-30, not built)

13 `<pre>{{ JSON.stringify(...) }}</pre>` dumps across 10 components (Products, Offers x2,
Orders, Customers, Invoices, Coupons, Services, Notifications, LandingPages x3, StripeKeys).

Considered and REJECTED: a support-issued 5-minute unlock key. It buys no confidentiality
— every panel renders an object the browser already holds from the tenant's own
authenticated API calls, so DevTools > Network shows the identical JSON. It would cost a
week (issuance, expiry, redemption, audit, support tooling) and would RAISE support load,
since support must mint a key before the tenant can gather what support asked for.

Do instead:
  1. One shared <JsonPanel> replacing all 13 sites, gated on a PER-USER preference. A
     user preferences store already exists (/preferences keyed by tenant_id+user_id,
     backing theme/default_stripe_mode/dashboard_home/sidebar_collapsed, reached from the
     avatar dropdown), so developer_mode extends it -- NOT Configuration.vue, which
     governs the whole tenant, and not localStorage, which is per-device. Keep ?debug=1
     as a non-persistent one-shot for support. Note UserPreferences.schema.json says
     additionalProperties:false but is NEVER LOADED (runtime or tests) -- the hand-written
     validate_user_preferences does not police unknown keys and the repository stores
     **document as-is, so the field works WITHOUT the schema edit. Declare it anyway: the
     schema is the only written spec of the shape, and letting it drift is how the
     SENSITIVE_FIELDS denylist leaked the Connect token refs.
  2. A "Copy diagnostics" action emitting a purpose-built REDACTED bundle (entity id,
     schema_version, environment, app version, scrubbed document) — more useful to
     support than a raw dump and safe to paste into a ticket.

Note the schema itself cannot be kept secret: shipping a JSON API to a browser SPA
discloses it. These changes are about polish and accidental exposure, not secrecy.

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

### Multiple legal entities (tenants) under one dashboard login — DEFERRED (assessed 2026-08-28)
- **Today:** one login (Cognito user) = one tenant = one Stripe Connect account per mode. A second legal entity
  (LLC, corp) needs a second Junior Bay account. Tenant identity is resolved from the auth session across every
  handler, so a switcher is a wide (not deep) change.
- **Assessment — not worth building now:** the population needing it is small (multi-entity owners, agencies)
  and the creator competitors don't offer it either (Stan = one store per account; Shopify only at the org tier).
  The per-Site statement descriptor above covers the far more common "appear separate" need for sole props;
  true risk isolation only comes from genuinely separate entities anyway, which means separate Stripe accounts
  = separate tenants.
- **If/when demanded, the shape is an "Organization/workspace" layer:** a `user ↔ tenant` membership table with
  roles, a tenant switcher in the topbar, and tenant_id resolved from membership + selected workspace instead of
  from the user — the same layer that would give **team/staff logins to one tenant** (the more common ask, and
  adjacent to the existing fulfillers concept). Build both together, not piecemeal.
- **Cheap interim:** separate logins per entity (browser profiles); optionally a "linked accounts" quick-switch
  that just re-auths another Cognito identity (no data-model change).

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
- **✅ Reuse VERIFIED 2026-08-28 (no code change needed):** controlled test — baseline 1 connected account per mode,
  ran the full flow (intro modal → Stripe → **"Select the account you'd like to connect" → Connect**), result **still
  1 per mode**, tenant wired to the existing `acct_1TA08M…`. So the account **chooser reuses correctly**; the
  June duplicates came from taking **"Create a new account"** on that screen during rehearsals, NOT from our
  `stripe_user[]` prefill. Prefill stays as-is. Guidance for tenants/rehearsals: on Stripe's screen pick the
  existing account, never "Create a new account".
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

### Show the connected Stripe account under the avatar (topbar user pill) — SHIPPED PROD 2026-08-28
- **What:** the topbar user pill's subtitle is the static word "user" (App.vue `.user-pill small`). Replace it with
  the **connected Stripe account for the active mode** — the Connect email (`connect_email`, e.g.
  keith@juniorbay.net) or business name (`connect_business_name`) from `stripeKeys.connectCard.stripe_connect`;
  fall back to "Not connected" / "user" when there is none. **Truncate** (CSS `max-width` + `text-overflow:
  ellipsis`, ~22ch, full value in `title=`) so a long email can't distort the pill.
- **Why:** during onboarding verification the author mixed up which tenant owned which Stripe account (a Payments
  screen showed a live acct on the yahoo test tenant while the Dashboard — a different login — said "not
  connected"). Surfacing the connected account's identity at the top of every screen makes "which Stripe am I
  wired to?" glanceable and prevents that confusion for tenants with multiple logins/accounts.
- **Where:** App.vue user pill markup + `stripeKeys` store (already loads the connect card per mode; reuse, no new
  API). Mode-aware: shows the test account in Test, the live account in Live.
- **SHIPPED 2026-08-28:** pill shows business name → email → acct id (truncated 22ch + full value in the tooltip:
  "Connected Stripe (live): Keith Harris · keithdecosta@gmail.com · acct_…"), "No Stripe connected" when none.
  Falls back to `stripeKeys.modes[env]` so it names the account as soon as `/stripe/keys` returns.
  **Also fixed (same pass):** the onboarding wizard's step 3 asked to "Configure {other} environment"
  UNCONDITIONALLY — a legacy test-first-then-live leftover. It now checks `stripeKeys.modeConfigured(mode)` and
  shows "You're all set — Test and Live are both connected" (title "Setup complete") when both are done.

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

### ⭐ Pricing pivot — free-forever + transaction-fee model — FULLY SHIPPED PROD 2026-08-27
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

### ⭐⭐ HIGH — Digital Marketplace (starter inventory + provisioning engine) — plan 2026-08-28, not built
- **What:** a curated, **first-party** catalog of ready-to-sell digital assets. A tenant buys one and Junior Bay
  provisions the whole business in one click — license + product + offer + draft landing page. Solves the
  **empty-catalog cold start**; monetized not by the item margin but by the **GMV it creates** (the free-forever
  transaction fee). Full design: **`plans/DIGITAL_MARKETPLACE.md`**.
- **Keystone decision — FIRST-PARTY CONTENT ONLY in v1:** a `SourceContractSha256` proves a supplier's contract
  wasn't altered, **not that they ever held the rights**. A "Verified by Junior Bay" badge over third-party
  content makes *us* the target of any claim. Owning the content removes supplier warranties, indemnification,
  DMCA cascades, and revocation-across-live-stores entirely. Third-party supply is deferred and needs its own design.
- **Never say "PLR" customer-facing** — "starter inventory" / "done-for-you products". The rights schema stays.
- **The durable primitive is the PROVISIONING ENGINE**, not the catalog (pluggable supply source).
- **Architecture caveats:** source proposal assumed single-table DynamoDB + TypeScript; this repo is **Python 3.12,
  table-per-entity**. Also **DynamoDB transactions don't span tables**, so provisioning is an **idempotent,
  resumable state machine** (+ stuck-license sweep), NOT `TransactWriteItems`. Provisioned Product/Offer/Page must
  be ordinary tenant entities (reuse existing repos/validators/screens).
- **Money flow:** platform is the seller → rides the **existing platform-billing rail** (as Premium), not Connect.

### ⭐⭐ HIGH — Attention Primitive (offer → campaign → attribution) — plan 2026-08-28, not built
- **What:** derive a multi-platform social campaign **from the offer itself**, schedule it, publish it, and
  attribute real GMV back to each post and pillar. Solves the second cold start — **"nobody visits my store"** —
  and is the most differentiating item on the roadmap. Full design: **`plans/ATTENTION_PRIMITIVE.md`**.
- **Architecturally it's the sibling of ConversionContext:** `AttentionContext` is a **consumer of
  `OfferSemanticModel`** (`plans/OFFER_SEMANTIC_ANALYZER.md`, design-locked, **prerequisite**) — not a second
  semantic extraction. The analyzer already names Meta/TikTok listings among its intended consumers.
- **COGS is largely solved already:** `AI_AND_COMMERCE_ARCHITECTURE.md` §A.1 locks **BYO AI key ("cost is the
  tenant's")** + §A.2's provider adapter — so text generation costs the platform **nothing** and this does NOT
  reverse the "integrations, not in-house metered features" decision. **Only AI video** is a real platform cost →
  ration it, meter it, show remaining credits.
- **Trial:** keep the shipped homepage promise ("Full access for 14 days — free") by capping **usage**, not
  features — e.g. a 7-day sample campaign, one video. Never feature-gate it out of the trial.
- **Publishing:** vendor-agnostic adapter; aggregator first because **platform app review is the real blocker**
  (weeks–months). Candidate **Outstand.so** (unverified: $19/mo base incl. 3,000 posts, unlimited profiles →
  first ~50 tenants inside the base). **Managed Keys → BYOK forces tenant re-authorization** (OAuth tokens are
  bound to the issuing app) → launch on Managed Keys, run app reviews in parallel, **migrate while the tenant
  count is small**. Treat reconnection as a first-class state (queue posts, banner, auto-resume).
- **Scheduling:** reuse the existing `rate(15 minutes)` sweep pattern (3 already exist), NOT per-post EventBridge.
- **Ship attribution EARLY** (before autopilot generation) — it makes hand-posted content measurable, is cheap,
  and produces the data that makes generation smart.
- **Tier:** extra-premium ~$69/mo, modeled as a **higher plan tier** (billing is single-line-item today).
- **Verify before building A5:** paid one-week vendor spike incl. deliberately revoking a token mid-queue.

### ⭐ HIGH — Per-Site statement descriptor (dynamic descriptor suffix) — noted 2026-08-28, not built
- **What:** let each **Site** carry an optional `statement_descriptor_suffix` so charges from different storefronts
  on ONE Stripe account read differently on the buyer's card statement (e.g. `KEITH HARRIS* CODERBAY` vs
  `KEITH HARRIS* JBSTORE`). Most tenants are sole proprietors with one Stripe account and (soon) several
  brands/Sites — this is how those businesses *appear* separate without separate legal entities.
- **How Stripe does it:** the account's descriptor is NOT fixed for life. Card charges support a **dynamic
  suffix**: `payment_intent_data[statement_descriptor_suffix]` on Checkout Sessions / `statement_descriptor_suffix`
  on PaymentIntents. Stripe renders `<account shortened descriptor prefix>* <suffix>`, **22 chars total**, so the
  allowed suffix length = 22 − len(prefix) − 2. The prefix comes from the connected account's
  `settings.payments.statement_descriptor_prefix` (readable by the platform) — **if the tenant hasn't set a
  shortened descriptor in Stripe, the suffix is ignored**, so the UI must read the prefix, show the remaining
  budget, and prompt the tenant to set a prefix in Stripe when missing. Allowed chars: letters/digits/spaces,
  no `< > \ ' " *`; must contain a letter. Subscriptions (recurring Checkout) don't take the suffix on the
  session — set it on the subscription's invoices (`subscription_data` / invoice settings) or accept the account
  default for recurring.
- **Where:** `Site.schema.json` (+ Sites screen field with live "reads as: PREFIX* SUFFIX" preview + length
  budget); apply in every charge path — `checkout.py`, `cart_checkout.py`, `upsell.py` (PaymentIntent), `booking.py`,
  `invoices.py` — resolved from the page's Site (fallback: none → account default). Validate server-side with the
  live prefix length.
- **Why high:** the single real seam in "one Stripe account, several brands" — the author (tenant #1) will run
  a digital store + coderbay.net services on one account and needs buyers to recognize each charge.

### "Sabbath mode" — optional weekly store closure (noted 2026-08-27, not built)
- **What:** an opt-in toggle (OFF by default) letting a tenant close their store for the Sabbath. When enabled:
  - The closure window runs from **Friday sundown − buffer** to **Saturday sundown + buffer** (the full Sabbath
    plus the buffer at each end), sundown computed for the tenant's **local location/timezone** (varies daily).
    **CONFIRMED by the author 2026-08-27.** The resume message shows the **Saturday** date + end time.
  - **Two INDEPENDENT buffers (author, 2026-08-28):** *before Friday sundown* and *after Saturday sundown*, each
    tenant-adjustable **0–60 min** — do NOT assume they match. Jewish practice commonly uses **~18 min before**
    (candle-lighting) and **~40 min after** (nightfall; some customs go to ~50), so those are the natural
    defaults — *pin the shipped defaults at build time* (18/40 common practice vs 60/60 maximum). **Zero on both =
    the checkout closes exactly at Friday sundown and reopens exactly at Saturday sundown.** (The Sabbath itself
    is ~24h sundown-to-sundown, so 60/60 spans ~26h — the earlier "25-hour" figure was a slip.)
  - **Polar edge case (author, 2026-08-27):** in far-northern/southern locations (Alaska, northern Norway/Russia,
    etc.) the sun may not set — or rise — for weeks. When the solar algorithm yields no sundown for the date, the
    tenant supplies an **arbitrary manual window** instead: a start day/time + duration of **no less than 24 hours
    and no more than 25 hours** (validated). Detect automatically (e.g. `astral` raises when there is no sunset)
    and prompt for / fall back to the manual window; optionally let any tenant use the manual window as an
    override.
  - During the window, checkout is **replaced by a branded closure page**: *"Happy Sabbath! This store is
    temporarily closed for business in observance of God's Holiday. We will resume business again on {date} at
    {end-of-Sabbath-mode time}."* — same design family as the existing "This store is temporarily offline"
    billing page (dark-blue card, JB wordmark, status chip, orange-accent headline, trust strip). Resume time
    rendered in the tenant's local time with zone abbreviation.
- **Design notes for the build:**
  - **Sundown math:** needs the tenant's coordinates + IANA timezone. Source: Business Address (Profile) geocoded
    once, or explicit lat/long + timezone fields on the setting. Compute with a solar algorithm (e.g. the `astral`
    package or NOAA formula) — pure math, no external API, works offline in Lambda.
  - **Where to enforce:** at the **checkout/cart/booking/upsell handlers** (dynamic API — reliable), returning the
    closure page instead of a Stripe session; published landing pages are CloudFront-cached so don't rely on
    page-render gating (optionally add a small "closed for Sabbath" notice via the JS island). This is a
    TENANT-chosen gate, so it doesn't conflict with the free-forever "never block a sale" rule.
  - **Scope of the setting:** the UI lives in **User Preferences**, but the closure is a **store (tenant)** property —
    store it on the tenant profile/config, not per-user preferences, so every login sees the same state.
  - Future: additional holy days (Yom Kippur etc.) as a date list; a "closed now / reopens at" preview in the
    Preferences UI so the tenant can sanity-check their buffer.
- **Why deferred:** feature idea captured for prioritization; no code.

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

### Brand logo in the email sender avatar (BIMI) — LOW priority / deferred on cost, noted 2026-08-28
- **What:** show the Junior Bay logo instead of Gmail's generic letter avatar on mail from
  `support@juniorbay.net` (the treatment PayPal/Apple have). The standard is **BIMI**.
- **Prereqs ALREADY met on `juniorbay.net`** (verified 2026-08-28): SPF `include:amazonses.com`, SES **DKIM
  verified**, and **DMARC at `p=quarantine`** — the enforcement policy most senders fail. Nothing to fix there.
- **⚠️ Blocker is cost, not tech:** Gmail (and Apple Mail) render BIMI logos only with a **Verified Mark
  Certificate (VMC)**, which requires a **registered trademark** for the logo and runs **~$1,000–1,500/yr**
  (Entrust/DigiCert). **Deliberately deferred** — not worth it pre-revenue; revisit only if/when the trademark
  exists and the revenue justifies it.
- **Do instead (free, most of the benefit):** set a **profile photo on the `support@juniorbay.net` Google
  Workspace account** — Gmail recipients then see the logo with no BIMI, no certificate, no cost.
- **Cheap prep if wanted later:** produce the logo as **SVG Tiny PS** (square, solid background, no external
  refs, no scripts) and publish a `default._bimi.juniorbay.net` TXT record (`v=BIMI1; l=<svg url>; a=<vmc url>`).
  Some non-Gmail clients honor BIMI without a VMC; the record is harmless without one.

### Email auth for `juniorbay.com` — anti-spoofing SHIPPED PROD 2026-08-28 (sending-from-.com still deferred)
- **Today:** all platform mail sends from **`juniorbay.net`**, which is fully authenticated and has a **pristine
  reputation** — SPF `v=spf1 include:amazonses.com ~all`, SES DKIM verified, DMARC `p=quarantine` with rua/ruf to
  support@. Verified 2026-08-28; form submissions land in the inbox. **`juniorbay.com` has NO SPF and NO DMARC**,
  and nothing sends from it.
- **⚠️ History that must inform any change:** `juniorbay.com` was **lost and recently recovered**, and carries a
  **poor historical spam reputation** from earlier misuse. `.net` is deliberately the sending domain *because* of
  this. **Do NOT move platform sending to `.com`** on a whim — that would trade a pristine reputation for a
  damaged one.
- **What to do when it matters** (e.g. if tenant-facing mail should ever appear to come from the apex brand):
  1. ✅ **DONE 2026-08-28** — `HomepageApexSpfRecord` + `HomepageApexDmarcRecord` in `template.yaml` publish
     **`v=spf1 -all`** and **`v=DMARC1; p=reject; rua=mailto:support@juniorbay.net; fo=1;`** on the apex. Chose
     `p=reject` over `p=none` because the domain sends nothing, so nothing can break. The apex TXT record set
     also carries the pre-existing **Google site-verification** string (a TXT set holds all its strings — an
     SPF-only record would have deleted it). Verified live via public DNS.
  2. **Only if/when sending from `.com`:** verify it in SES, enable DKIM, switch SPF to `include:amazonses.com`,
     then **warm it slowly** (low volume first) and watch the DMARC reports — a recovered domain with past abuse
     needs re-earned reputation, not a cold cutover.
- **Why deferred:** nothing sends from `.com` today and `.net` works perfectly; this is protection + future
  optionality, not a fix.

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

### ⭐ HIGH — Media field parity: video FILE upload + drag-reorder (BEFORE LAUNCH) — 2026-08-30, not built
- **What:** `MediaListField.vue` (the ported stripe-cart "HERO MEDIA" component) supports **Upload Image** and
  **Video URL** today. **Upload Video** is behind an `allowVideoUpload` prop that is OFF, because stripe-link has
  no video-upload path — `handlers/upload.py` proxies an **image** service (`/upload/multiple`).
- **What stripe-cart did** (reference, `dist/dashboard/js/lp-media.js`): `POST /admin/video-upload-url` returns a
  **presigned S3 POST**; the client uploads directly, then **polls for a transcoded `web.mp4`** ("Video optimized
  for fast playback"). It also supported a per-video **poster image** upload.
- **To build:** presigned-POST endpoint + a video bucket/prefix, optional transcode (MediaConvert) + poll, then
  flip `allow-video-upload` on. Poster images would need a storage shape change (today media is a flat URL array,
  and kind is DERIVED from the extension by `runtime/html.py is_video_url()` — no schema change so far).
- **⭐ ALSO IN SCOPE — drag-reorder parity.** stripe-cart lets the tenant **drag page SECTIONS** to reorder them
  (the ⠿ handles on HERO MEDIA / HEADLINE); stripe-link only drags the addable `builder.elements`, not the fixed
  sections. `MediaListField` already drags media items WITHIN the list; section-level reordering is the gap.
- **Why HIGH / pre-launch (author 2026-08-30):** the field currently advertises media management the backend
  can't complete, and reordering is core builder UX. Both must work before launch.

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

### ⭐ HIGH — AI provider adapter (AI_AND_COMMERCE Phase 1) — SEQUENCED AFTER the other modules

**Priority HIGH, but deliberately NOT next.** Author's sequencing 2026-08-30: pick this up
once the remaining modules are complete — the pre-launch work first (see "Media field
parity: video FILE upload + drag-reorder", tagged BEFORE LAUNCH).

**Why it is on the critical path at all:** it is the gate on the Offer Semantic Analyzer's
last phase. P1-P3 and P4.0 are SHIPPED; `smart_offer_slug` is already a thin wrapper over
`slug_from_model(analyze_offer(...))`. The only thing left is **P4.1, the AI enrichment
tier**, and per plans/OFFER_SEMANTIC_P4.md it deliberately does NOT build its own AI stack —
it reuses the provider adapter from `AI_AND_COMMERCE_ARCHITECTURE.md` §A.2. So "continue the
analyzer" actually means "build the provider adapter first". Recording that here so the real
first task is not mistaken for a small next step.

**Also unblocks:** P4.2a ad-copy generator (AI; a deterministic floor can ship without it),
P4.2c AI content (needs AI_AND_COMMERCE Part A page-gen too). NOT a blocker for P4.2b
Merchant feed, which is deterministic and gated on the Site object instead.

**Cost note:** §A.1 locks BYO AI key ("cost is the tenant's"), so text generation costs the
platform nothing — this is an engineering-time decision, not a COGS one.

**Do not start with P4.1.** Start by scoping AI_AND_COMMERCE Phase 1 (the provider adapter);
P4.1 is downstream of it.

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
- **Gated on:** P4.1 cannot start until the AI provider adapter exists — see the ⭐ HIGH entry at the top of this
  section, which the author sequenced AFTER the remaining modules (2026-08-30).
