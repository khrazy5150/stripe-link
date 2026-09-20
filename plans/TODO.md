# TODO

Deferred, non-blocking follow-ups. Each item notes what, why it was deferred, and where to fix it.

## Shipping

### Wire the shipping providers (Shippo first)
- **What:** the module supports four providers in its schema and its `<select>` -- shippo, easypost,
  shipstation, easyship -- and **none of them is wired**. There is no provider code at all: not one HTTP
  call to any of them. Design: **`plans/SHIPPING_PROVIDERS.md`** (written 2026-09-20).
- **Built and good, do not rewrite:** `ShippingConfig.schema.json` is complete; `handlers/shipping.py` does
  KMS key encryption, preserve-on-unchanged, drop-on-provider-change and redact-on-read -- better than the
  legacy implementation; `Shipping.vue` is a full settings form.
- **The blocking gap, and it is not in the shipping module:** `order_record_from_session` never reads
  `shipping_details` off the Stripe session, so **no order in either environment has a destination
  address** and no label can be bought for any of them. Checkout does collect one (US + CA, payment mode).
- **Also missing:** `connection_status` can never say `connected` (nothing tests it, and there is no test
  endpoint); no rates/labels/tracking routes; no shipment/label document, so no idempotency to stop a
  double-click buying two labels; and no Stripe `shipping_options` anywhere, so shipping is silently free
  on every order ever placed.
- **Legacy:** `../stripe-cart` has real Shippo REST call shapes worth reading
  (`layers/shipping/python/shipping_providers.py`) but the code cannot be copied -- it is built on
  `requests` in a Lambda layer, and `src/requirements.txt` here is deliberately empty. Its own plan's
  "Known gaps" says it was never finished, and it stores API keys unencrypted.
- **Also planned: "Calculate Price"** -- estimated shipping folded into the price at pricing time, feeding
  the EXISTING `calculate_price()` gross-up in `domain/fees.py` as one more component of
  `tenant_keyed_amount`. Same mechanism as Net-Guaranteed, not an analogy to it. Needs the packer, and
  needs zone sampling because there is no destination at pricing time -- an estimate is a distribution, not
  a number. Treated as a HYPOTHESIS: record estimate vs actual from the first label onward (it cannot be
  backfilled) and expect to replace the strategy after measuring.
- **Tracking emails reuse the existing mail path**, not a new one: a pure content builder in
  `domain/receipts.py` beside `receipt_content`/`tip_renewal_content`, branded from
  `load_tenant_email_context` so it comes from the TENANT's business, sent via `mailer.send_email`
  (injectable), and wrapped so it can never fail the label purchase that triggered it. The in-app bell
  (`docs/NOTIFICATION_EMITTERS.md`) is a separate channel and optional.
- **Two tenants, opposite needs.** The beginner has no carrier account and today drives to the post
  office -- a plain buy-and-print-a-label screen is transformative for them, and it does not matter that it
  is less capable than ShipStation because they were never going to use ShipStation. The experienced
  merchant already runs ShipStation daily and wants their orders to arrive in the tooling they have.
  Beginner first (they arrive first); integration is the LAST phase (PI), because it serves the later
  tenant, depends on the providers we cannot test for free, and reuses everything the beginner path builds.
- **Bundles are a packing problem, not a shipping one.** Weight is additive, dimensions are not. Decided:
  volume-fit into a box catalog, falling back to one parcel per item. The packer is shared by label buying
  and estimation, so it is built once in P1.
- **Eight decisions before any code** (plan ??Decisions needed??): post-purchase labels only for P1; one
  shipment doc per order vs a list; tenant picks a rate vs auto-pick; whether `test_mode` is independent of
  the platform env (mirrors `plans/STRIPE_MODE_DECOUPLING.md`); default percentile for Calculate Price;
  the `free_shipping_threshold` double-count rule; who owns the box catalog; whether the buyer ever sees a
  shipping line.

## Services / Booking

### Tomorrow (2026-09-21): first booking ever made in stripe-link, + the plan link
- **Status:** planned in full, **tabled until 2026-09-21**. Design: **`plans/BOOKING_WITH_STAFF_AND_PLAN_LINK.md`**.
- **The fact that shaped it:** dev AND prod both hold zero fulfillers, zero appointments, zero availability
  and zero calendar connections. **No booking has ever been made in stripe-link on either environment** —
  the working booking remembered from before was stripe-cart. Part A is a first run, not a regression check.
- **Part A — first booking with staff (QA walk, no new code).** Create a fulfiller + availability, buy the
  ONE-TIME service (not the plan; see Part B), book it. Try it BEFORE connecting Google Calendar: "does
  booking survive a tenant who never connected a calendar" is a real tenant state, cheapest to answer now.
- **Part B — the customer's plan link (build).** A recurring service grants credits and NO appointment, and
  spending one needs an `entitlement_id` that nothing ever hands the customer — `grep entitlement
  runtime/html.py` is empty, so the booking widget cannot send one. They paid, they hold credits, and the
  page offers no way to use them. It is also why the plan → booking → staff path cannot be tested by
  anyone, us included. Copy `handlers/tip_manage.py` (opaque token minted in the webhook, emailed, no buyer
  account) rather than inventing a second mechanism.
- **Four decisions needed before Part B is built** (listed in the plan §B5): token on the entitlement vs a
  separate doc; whether the link also cancels the plan; refill email every cycle or only on change (a
  daily-interval plan would otherwise email daily); what the page shows once credits run out.
- **Also pending tomorrow:** the day-two renewal on dev — the **refill path has still never executed
  anywhere**, prod included. It fires only on a second `invoice.paid`. Watch the product subscription renew
  at the 5.01% application fee, and `jb-booking-credits-dev` RESET rather than accumulate (no rollover).

### Booking credits and staff routing have never met
- **What:** `test_booking_credits.py` mentions a fulfiller **zero times**; the spend tests call
  `_spend_plan_credit` directly with a fake repo and never go through `reserve_route`, which is where
  fulfiller resolution, availability and calendar delegation actually happen. `test_delegation.py` (31
  fulfiller references), `test_scheduling.py` and `test_booking.py` cover staff routing — separately.
- **Why it matters:** both halves are well covered and their COMBINATION is not, which is the same shape as
  the subscription bug found 2026-09-20 (every layer tested with fakes, and Stripe rejected the result).
- **Where to fix:** a test that reserves through `reserve_route` with both a plan credit and a fulfiller.
  Blocked on Part B only for the end-to-end version; the unit-level one can be written now.


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

### ⭐⭐ HIGH — the API never verifies who is calling; tenant_id is taken from the request (found 2026-09-15)

Noticed while smoke-testing a newly deployed endpoint on prod, NOT introduced by it. This is repo-wide and
pre-existing.

**What was verified, concretely:**

- `template.yaml` defines no `Auth:`, no `Authorizer`, no `DefaultAuthorizer`. The RestApi has none.
- `tenant_id_from_event` (`stripe_link/common.py:109`) reads the tenant from, in order: the JSON body, `?
  tenant_id=`, `?tenantID=`, `X-Tenant-Id`, `X-Client-Id`. All client-supplied.
- The `Authorization: Bearer` header the dashboard sends on every request (`api/client.js`) is named in the
  CORS allow-list and **read nowhere else in `src/`**. There is no JWKS fetch, no token decode, no signature
  check anywhere in the repo.
- `POST /pages`, `POST /offers` and `POST /tip-jar` with no credentials all return **400** ("tenant_id is
  required") rather than 401/403 — the Lambda ran. Supplying a tenant_id is what the handler is waiting for.

**So, on the face of it:** anyone who knows or guesses a tenant_id can call the tenant-scoped write endpoints
as that tenant. `require_capability` does not help — it reads the tenant's plan, it does not establish who is
asking.

**NOT verified, deliberately:** no cross-tenant write was attempted against prod. The reasoning above is from
the code and from unauthenticated status codes only. Confirm with a deliberate test in dev before sizing the
fix — it is possible something outside this repo (a WAF rule, a CloudFront function, an edge Worker) is
checking the token, and that would change the answer.

**Why it matters more now than last week:** provisioning endpoints create real, externally-visible things. A
tip jar provision writes four documents and claims a GLOBALLY UNIQUE platform subdomain that is never
recycled by design. Squatting those under another tenant's id is the kind of damage that cannot be fully
undone by deleting rows.

**The fix is not small**, which is why it is recorded rather than attempted: a Cognito authorizer on the
RestApi, `tenant_id` derived from the verified claims instead of the request, and every handler that calls
`tenant_id_from_event` re-pointed at it — including the genuinely public endpoints (`/purchase/manage`,
`/leads`, published-page checkout) which must keep working WITHOUT a token and therefore need the boundary
drawn explicitly rather than by omission. Pre-launch is the cheapest time.

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

### MEDIUM — Junior Bay Partner Program (design locked 2026-09-06)

Turn the tenant base into a distribution network: any merchant can refer businesses to Junior Bay and earn
a share of the platform fees those businesses generate. **Junior Bay pays only when Junior Bay is paid** —
commission is a percentage of collected platform fees, never a per-signup bounty, which makes fraud
self-defeating (a fake tenant that never sells generates nothing to pay on).

Full design in **`plans/PARTNER_REFERRAL_PLAN.md`**. Locked: 20% for 12 months then a 5% lifetime tail;
first-touch attribution stamped write-once at registration; the commission clock starts at the referred
tenant's **first qualifying sale**, not signup; v1 pays account credit only, with the balance modelled as
cash-capable from day one.

The foundation already exists and is why this is worth doing here: the append-only ledger is per-tenant and
idempotent and already records `platform_fee` on every sale, the fee rate is server-authoritative, and the
email footer shipped 2026-09-06 is already on every free tenant's outbound mail.

Three things to settle before building:

- **Does `?ref=` survive the signup round-trip?** Captured client-side on a static homepage, it has to
  reach `register_tenant` through the auth redirect. If that flow round-trips a hosted auth UI, query
  params can be dropped. A broken chain here is invisible — it looks exactly like nobody referring anyone —
  so verify it against the real flow FIRST.
- **The redemption gap.** `application_fee` is collected atomically at charge time, so credit cannot
  retroactively offset a fee already taken. Credit can cleanly pay a Premium invoice; a free tenant who
  never upgrades has nowhere to spend it. Either accept that (it drives upgrades) or bring the cash rail
  forward.
- **The footer must revert to quiet wording.** What shipped is promotional ("Want to start your own online
  store?"), which is too much on a customer's receipt once it also earns the merchant money. It becomes
  "Powered by Junior Bay" with the code invisible in the link, and the destination page does the selling.
  Counsel should review the final copy — an earning link is a material connection under FTC guidance.

Also note: a commission accrues to the *partner's* ledger from the *referred tenant's* sale — the one
deliberate cross-tenant write in the system. It needs to be an explicit reviewed exception, not a side
effect of passing a different `tenant_id`.

### MEDIUM — modify the Leads screen (raised 2026-09-04, details to come)

Leads now arrive from two sources — the inline lead form and a Page Ribbon's gated download — and all three
shapes (email only, phone only, both) were confirmed captured on 2026-09-04. The screen does its job but
was built before the ribbon existed.

Author will specify. Things visible from the current screen that are worth raising when they do:

- **A lead does not say where it came from.** Ribbon downloads store `provenance.source = "page_ribbon"`
  and the `section_id`, but the card shows neither, so a tenant cannot tell a form fill from a download.
- **The card title is whichever field exists** — an email address for one lead, a bare phone number for the
  next. Fine for three leads, hard to scan at three hundred.
- **No search, and status filter only.** The other list screens moved to the shared indexed-list machinery
  (paged projections + server-side search); this one did not.
- **Which page or offer produced it** is shown as the offer name only.

### MEDIUM — look deeper into the visual picker (Offers + Page Ribbon, 2026-09-04)

`SelectorCard.vue` was extracted when the ribbon's page picker, written by copying the Offers item
selector's classes, diverged from it — images cropped where the original's did not, and the title was
clipped out of a card whose rows were sized for a price line it never had. Both now render one component.

What the extraction did NOT settle, and should be looked at properly:

- **`contain` vs `cover`.** `contain` shows the whole product, which is the point of a visual selector, but
  leaves neutral space around off-ratio images. Offers' grid changed appearance as a side effect. Either
  tune the image row height, or decide per-screen — but a `fit` prop would let the two diverge again,
  which is what the extraction removed.
- **Whether the two selectors should share more than the card.** Both have a search box, an empty state, a
  scroll region and a footer; only the card is shared today.
- **Other pickers that predate this.** `coupon-selector-grid` and `wizard-offer-list` are the same idea
  with their own markup, and were not touched.
- **The overlay variant.** Currently a boolean prop. If a third caller wants something between the two
  layouts, that flag becomes a mode and wants naming rather than extending.

### MEDIUM — audit for silent agreement failures (framing agreed 2026-08-30)
- **New instance, 2026-09-01:** `handlers/offers.py` documented that the offer label and slug come from ONE
  OfferSemanticModel "so they can't diverge" — but a tenant-typed name bypassed the model while the slug kept
  deriving from products ("Workout Bundle" -> `dietary-supplement-bundle`). Stated invariant, nothing enforcing
  it. Fixed + asserted.
- **Related debt — RESOLVED 2026-09-01.** The slug rules now live in `domain/slugs.py` + its mirror
  `composables/slugs.js`, and `tests/test_slug_parity.py` runs BOTH over `tests/fixtures/slug_cases.json`.
  Note the technique: an algorithm can't be shared across runtimes the way `composition_rules.json` is, so
  the FIXTURES are shared instead. Verified the guard actually bites by breaking the JS deliberately.
  `smartOfferSlug`/`smart_offer_slug` (the semantic-model half) is NOT yet covered by fixtures — it needs a
  product/service model as input, so its cases are a bigger fixture. Next candidate.

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

### MEDIUM — Junior Bay Courses: sell knowledge from the same storefront (raised 2026-09-07)

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

**Reframed and raised to MEDIUM 2026-09-07 — full design in `plans/COURSES.md`.**

The framing changed, and it changes what gets built. This is not a video delivery service; it is
**knowledge as another thing a tenant can sell**, through the storefront, checkout, customers and
analytics they already have. The pitch is *"you already have a store, now sell a course from it"* —
which is a different and much stronger position than competing with Teachable or Kajabi.

Three things the earlier note did not have:

- **Entitlement is NOT the delivery mechanism.** Commercial rules (purchased, subscription, enrolled,
  drip, free preview) live above a video system that knows only *"user X may access resource Y"*. Half of
  that is already built — `downloads.serve_handler` does exactly this for paid downloads.
- **⚠️ CloudFront signed cookies will not reliably work here.** A published page can be served from a
  tenant's custom domain, `*.jbay.uk`/`*.jbay.be`, or the platform host, so a cookie set for a media
  distribution is a THIRD-PARTY cookie — blocked by Safari, being removed by Chrome. The textbook AWS
  answer assumes player and media share an origin; here they usually will not. Signed-manifest is the
  recommended alternative. **This blocks Phase 1 and must be settled first.**
- **Video costs DELIVERY, not storage** — a different business from images. Instrument GB delivered from
  day one, and do not bury it inside an unlimited $19/month plan before that ratio is known.

Sequencing also inverted: build the video primitive BEFORE the course product. It is independently
useful, and designing curriculum against a delivery layer that does not exist yet is backwards.

**Live streaming is Phases 5-6 of the same plan, not a separate feature** (addendum, 2026-09-07). VOD and
live differ only in the backend -- MediaConvert processes a file, MediaLive continuously processes a feed
-- and both emit HLS, so one player and one commerce layer serve both. Live events, paid workshops and
subscriber-only broadcasts are the existing offer -> payment -> entitlement chain with a different
resource on the end. Live -> VOD then sells the replay with no new infrastructure.

**Phase 7 is Livestream SEO** (2026-09-07): `BroadcastEvent` markup makes a stream ELIGIBLE for Google's
LIVE badge, and Google's Indexing API can be told to crawl at start and at end. Eligibility and timing,
not a ranking boost -- but a live event is worthless to discover an hour late, so timing is the value.
Livestreams are one of only TWO things the Indexing API officially supports (the other is JobPosting), so
this is well-supported rather than a trick. The URL survives the broadcast and becomes the replay, which
is the SEO flywheel and the clearest instance of the Attention primitive yet.

**Phase 8 is IndexNow / Bing**, and it is SMALLER than Phase 7 despite looking bigger from outside: SEO-15
already scopes an IndexNow submitter, so this adds the live transitions as extra triggers rather than a
new integration. Microsoft explicitly names "Live Stream Announcements" as an IndexNow use case, and one
submission reaches multiple participating engines -- so there is no separate Yahoo integration to write.

It is also EASIER to automate than the Google path, for a concrete reason: Google's Indexing API needs a
service account owning a Search Console property (an account-level relationship per tenant domain), while
IndexNow needs a key FILE at the domain root -- a publishing operation this platform already performs. It
may therefore ship before Phase 7. Be more cautious about the payoff though: Bing documents no LIVE-badge
equivalent, only rapid discovery and video indexing.

The philosophy to hold: build ONE live-discovery system and broadcast through the appropriate protocols,
not "Google SEO + Bing SEO + Yahoo SEO".

Its architectural consequence lands in Phase 5, not 7: published pages are STATIC S3 artifacts that change
only when a human saves them, and a live page must change state three times at event-driven moments with
the markup in the SERVED html. So the publish pipeline has to become triggerable by the stream lifecycle.
Design that in Phase 5.

Two hazards recorded there because they are not obvious from the architecture: a MediaLive channel bills
for every hour it RUNS, so a tenant who forgets to end a stream burns money all night (needs idle-stop and
a hard maximum, not a reminder); and the real barrier is that MediaLive ingests RTMP, so the tenant needs
OBS -- which most small tenants do not have. **AWS IVS is likely the better fit** for "small tenants go
live occasionally" and should be evaluated before committing to MediaLive.

Still open, and only for Phase 1: grow this service (MediaConvert + HLS) or adopt one (Mux, Cloudflare
Stream, api.video). Phases 2-4 are the same work either way. Nothing in the current design blocks either
path, and the size ceilings are deploy-time parameters rather than code (b7a0f27 in that repo).

### MEDIUM — icon-picker is an imperative DOM helper, not a Vue component (noted 2026-08-31)

`dashboard/src/icon-picker.js` exports `showIconPicker(current, onPick, title)` — a function that builds
and tears down its own DOM, called imperatively from templates. Everything else in the dashboard is a
Vue component. Consequences: no reactivity, no `v-model`, state lives outside Vue, it cannot be styled
by the app's scoped rules, and each call site passes a callback instead of binding a value.

Convert to a component (`shared/IconPicker.vue`) with `v-model` + a `title` prop, then update every
call site. Callers today: trust badges, and the countdown start/end icons (wired to the existing helper
2026-08-31 so the countdown at least matches trust-badge behaviour).

Not urgent — the helper works. It is an architectural inconsistency, and the kind that quietly spreads
as more icon fields appear.

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

### ⭐ HIGH — add the font service to published pages — SHIPPED dev+prod 2026-09-08 (plan plans/FONT_SERVICE.md §12)

**DONE:** pages emit the stylesheet; presets carry pairings; per-page picker in Page Settings → Appearance;
catalogue audited (34 families, zero broken entries) and the picker widened 11 → 31; Source Code Pro and
Source Sans 3 moved to variable; every pairing subset to Latin — **4,228 KB → 1,344 KB** weighted by preset
usage, which moved a real page +18 PageSpeed points.

**STILL OPEN, tracked in the plan, not here:**
- §9's tenant-wide preference **UI** (the four-level resolution order it feeds is already live)
- §10 font import (TTF→WOFF2) — the only step with a legal surface, deliberately last
- **The CORS failure is unexplained** (§12e). `fs=true` embeds the bytes and removes the request rather than
  explaining it; every server-side layer measures correct from the user's own machine while their browsers
  still refuse the header. Read §12b's ruled-out list before re-investigating.
- The font stylesheet is **never edge-cached** — every first load invokes a Lambda for a render-blocking
  resource. Seven pairings could be pre-generated as static CSS behind a real CloudFront distribution, which
  would also let the service serve its own font files and close the two-host split (§12e).

The original entry follows.

### LOW — adding a font is five manual steps across three repos (noted 2026-09-08)

Registering a new family means: upload the WOFF2; add it to `fonts-api/src/font_definitions.py` and deploy
that stack; add it to `SERVABLE_FAMILIES` in `src/stripe_link/domain/fonts.py`; add it to
`builderFontFamilies` in `LandingPages.vue`; deploy stripe-link + dashboard. **The builder dropdown does not
update on its own.**

Two of the three seams are already guarded; one is not:

| seam | guard |
|---|---|
| bucket ↔ fonts-api catalogue | `fonts-api/tools/sync_catalogue.py` — but only when someone remembers to run it |
| catalogue ↔ `SERVABLE_FAMILIES` | **nothing** |
| `SERVABLE_FAMILIES` ↔ dropdown | `tests/test_font_picker_options.py`, automatic |

So steps 3 and 4 cannot drift apart, but **nothing reports a font that was registered and never reached the
picker** — it is simply servable and invisible. Skipping step 3 is worse than invisible: the picker would
offer a family `families_to_load` filters out, so the page names it in the CSS stack, never downloads it,
and silently renders the fallback.

Benign today — the only unoffered families are the three deliberate exclusions (Themify is an icon font,
Futura is a licensing exposure, Ubuntu Titling is the Junior Bay wordmark) — but a font added tomorrow lands
in the same silent gap.

**Preferred fix: a test**, not automation. It reads the fonts-api catalogue and fails when a family is
servable but neither offered nor on an explicit exclusion list, which also forces the exclusions to be
*stated* rather than implied. Deriving `SERVABLE_FAMILIES` from the catalogue instead would remove steps 3
and 4, but the dashboard cannot import Python and a runtime fetch adds a request to the builder — and the
exclusions need a human anyway: no derivation would have caught that Themify maps 0 of 62 Latin letters.


### LOW — the font pipeline is Latin-only, deliberately (decided 2026-09-09)

Every font we accept is subset to Latin (ASCII + Latin-1 + Latin Extended-A) and, when it is variable,
instanced down to the `wght` axis alone. That is what makes tenant font import work at all: before
subsetting, Noto Sans, Noto Serif and Merriweather all returned 504 at API Gateway's 29-second ceiling;
after subsetting and axis pinning, Merriweather is 273K and everything else is under 60K.

**The cost is that a non-Latin script is not merely unsupported — it is silently stripped.** A tenant who
uploads a Cyrillic, Greek, Arabic or CJK font gets a working file back with their glyphs removed.

**Why we are not fixing it now.** The obvious-looking fix — a presigned S3 upload, so a font larger than
Lambda's 6MB request ceiling can be ingested — does not work. Measured 2026-09-09 against Noto Sans SC:

| | |
|---|---|
| source file | 14 MB (over the 6MB ceiling, hence the presigned idea) |
| what Google emits for ONE weight | **101** `@font-face` blocks, ~23 KB each, 2,353 KB total |
| what our pipeline would emit | ONE file per weight, ~2.3 MB, downloaded whole by every visitor |

Google splits CJK across 101 `unicode-range` slices so a visitor fetches only the ranges their text
touches. We would hand the tenant a single file more than twice the size of the unpinned Merriweather we
rejected as too heavy. **The uploader unlocks a worse outcome than the one it was meant to fix.**

**So the real work is a data-model change, not an uploader.** There is no `unicode-range` anywhere in either
codebase, and `fonts-api/src/app.py` `generate_single_font_css` emits exactly one `src: url(...)` per face.
Supporting non-Latin means a face becomes a *set* of files, which touches the CSS generator, the font
definitions, and the tenant `@font-face` emission in `runtime/html.py`.

**Revisit when a tenant asks for a script we cannot slice** — not when a font is merely heavy, which axis
pinning already solved. For that first tenant the cheapest correct answer is probably a Google Fonts
*reference* (`fonts.googleapis.com` has already done the slicing), accepted only as a validated family name
we build the tag from — never as pasted markup. That path was declined for heavy Latin fonts on 2026-09-09
because it sends every visitor's IP to Google for no benefit; for a script we genuinely cannot serve, the
trade is different, and a CJK store is less likely to be an EU establishment.

Related: the Latin subset itself is defined in `font-converter/src/handler.mjs` (`LATIN_SUBSET`), which
deliberately includes Latin Extended-A so Polish, Czech, Turkish, Hungarian, Romanian, Croatian and the
Baltic languages keep their characters.

### 📄 SUPERSEDED — add the font service to published pages (found 2026-09-03, plan plans/FONT_SERVICE.md)

**This is the ORIGINAL entry, kept for its design reasoning. The work SHIPPED — see the entry above.**
It no longer carries a priority: it was still marked ⭐ HIGH on 2026-09-09 and read as an eighth open HIGH item.

**Scope extended 2026-09-07 (§9-§11 of the plan).** Presets will carry font PAIRINGS, not just colour —
"presets already carry the page's whole visual identity except its type" — but they PROPOSE rather than
own, so a tenant's explicit choice survives a preset change. Four-level resolution, most specific winning:
system fallback ← preset ← tenant preference (behind an explicit "Override font presets with these"
toggle) ← page override. Same shape as the colour-token override in ADVANCED_COLOR_SETTINGS, deliberately,
so type and colour need one mental model rather than two.

Also adds tenant font IMPORT, which is mostly wiring: `../sam/font-converter` already exists (Node 20,
ttf2woff2, upload endpoint). Two things recorded there because they are easy to get wrong: **a static TTF
cannot become a variable WOFF2** -- WOFF2 compresses, it does not add axes, which is exactly what bit us
on 2026-09-03 when a full Google TTF set converted to statics -- and the converter's current variable
detection is a substring search over file bytes plus a filename guess, where it needs to read the fvar
table. Licensing needs an upload-time affirmation of web-embedding rights: desktop licences frequently do
not cover serving a font publicly from the platform's CDN.


Published landing pages load NO webfonts. `runtime/html.py` emits no `@font-face` and no link to
`fonts.juniorbay.com`; its only preconnect is for the hero image host. `font_stack()` still produces
`Montserrat,-apple-system,...`, so the named family applies only if the visitor happens to have it
installed — in practice every page renders in whatever sans that device ships. **The same page looks
different on macOS, Windows and Android.** The homepage wires the service up correctly; published pages
never got the same treatment.

Found while checking whether the service carries Inter for the Quote element (it does not — 404).

Second finding, and the reason the fix is two-part: **nothing writes `theme.fonts`.** The renderer reads
it, but no builder control and none of the 16 presets set it, so every page is `family: "system"` and
loading the service alone would change nothing visible. Presets need typography before this is real.

Preview and published both render through `render_page` (the preview POSTs to `/pages/render`), so ONE
change covers both surfaces with nothing to keep in sync.

Service capabilities, probed rather than assumed: `?family=X:400,700` gives both weights, a bare
`?family=X` silently gives regular only (every 700 heading would be faux-bold), and the Google `wght@`
syntax 404s.

**The service advertises 30 families and the bucket holds THREE** (Montserrat, Roboto, Ubuntu Titling).
`?family=Poppins` returns valid CSS whose every `@font-face` 404s, so the text silently falls back with no
visible error — the same failure mode this task exists to fix. The catalogue is 221 hardcoded entries in
`../fonts-api/src/font_definitions.py`.

Inter was uploaded 2026-09-03 but into the LEGACY `s3://juniorbay.com` bucket; the live origin is
`jb-homepage-prod-150544707159` (distribution E1RX3M3RT2BWUZ), managed by this repo's template. Its
18/24/28pt split is Inter's optical sizes and constrains nothing — the catalogue maps file name to family
name already. The real cost is that the files are full-charset at ~116KB each, unsubsetted.

### ⭐ HIGH — the dashboard is not usable on a phone (found 2026-08-31, plan plans/MOBILE_EDITING.md)

Reported from a real device: from `sandbox.juniorbay.com` on a phone, the menus cannot be navigated to
reach the landing-page builder at all. Not "awkward" — unreachable.

Scale of the gap: `dashboard/src/styles.css` carries THREE responsive breakpoints (two `max-width:900px`,
one `max-width:60rem`) and NOTHING below that. The sidebar has no collapsed/drawer state. The dashboard
was built desktop-first and phone width was never designed for.

Known work:
  - **Sidebar → drawer.** It is a fixed column today, so on a phone it either eats the screen or the
    content is unreachable behind it. This is the blocker.
  - **The builder is inherently two-pane** (form + Live Preview side by side). On a phone that has to
    become tabbed or stacked — a design decision, not just a media query. Note the preview already has a
    Desktop/Mobile toggle whose Desktop mode hides the form; that pairing may be the seed of the answer.
  - **Modals should go full-screen below a phone breakpoint.** Page Settings and the section editor are
    centred cards sized for a laptop.
  - **Tap targets and control heights.** The 2026-08-29 density pass tuned everything for a mouse:
    3.2rem controls and 1.2rem text are fine on a desktop and small on a phone.
  - **Tables/wide rows** (Orders, Customers, Leads) need a card layout or horizontal scroll containers.

Related symptom already fixed (8994e6d, and the follow-up removing overflow:hidden from the settings
accordion): at a merely SHORTER viewport the open accordion collapsed to one line and would not scroll,
because `overflow:hidden` on a grid item sets its automatic minimum size to zero and therefore makes it
compressible. Expect more of this class — the layout has not been exercised at small sizes, so bugs that
only appear when space is tight have had nowhere to surface.

**DECIDED 2026-08-31: full parity — a tenant should be able to do EVERYTHING on a phone.** That is the
larger of the two possible targets, and it makes the builder in-scope rather than view-only.

### Consequence: drag-reorder does not work on touch AT ALL

The section reorder shipped in this work uses the HTML5 drag-and-drop API (`draggable`, `dragstart`,
`drop`). Mobile browsers do not fire those for touch — iOS Safari and Android Chrome both ignore them.
So on a phone, section order is not awkward, it is IMPOSSIBLE. Same for the media list in
MediaListField and the element cards.

The identical gap exists on desktop for keyboard users: there is no way to tab to a handle and reorder.
So one fix serves both, and the accessible answer is the simpler one:

  - **Explicit move controls** (▲/▼ on each row, or a "Move to…" affordance) driving the same
    `moveSectionBefore`. Works with touch, mouse, keyboard and screen readers, and needs no gesture
    library.
  - Keep the drag as a mouse-only enhancement on top; do NOT try to reimplement dragging with pointer
    events, which is where this normally goes wrong.

Worth doing regardless of the mobile timeline — the keyboard gap is a real accessibility defect today
(WCAG 2.1.1 Keyboard), not just a phone problem.

### ✅ Builder section order: the form IS the page map — SHIPPED (verified 2026-09-07)

**Verified shipped 2026-09-07.** The invariant holds: Page Settings is a separate group above Page
Content (the builder cites `BUILDER_SECTION_ORDER.md §2` at the code site), rows are compact with modal
editing, `default_order` lives in `composition_rules.json` and is read by `composition.baseline_order()`,
and the standalone Section-order list was retired (`b51078e`, `023ab04`, `ae013c0`, `5dd7659`).

Original framing, kept for the reasoning:

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



### MEDIUM — verify the social backlink check host by host, with real tenant profiles (raised 2026-09-09)

The checker works. What is NOT yet known is whether a real tenant can complete the round trip on each
allowlisted network, because the two halves are independent: can the tenant get our URL onto that profile
at all, and does the profile then expose it in HTML we can fetch?

**Proven end to end (real tenant profile, real backlink, green badge):**

| host | status |
|---|---|
| github.com | ✅ CONFIRMED 2026-09-09 — profile URL field, no ownership proof needed |

**Probed only, with a public proxy profile (nasa/sindresorhus), NOT with a tenant link:**

| host | probe result | what is still unknown |
|---|---|---|
| youtube.com | website found, via the /redirect? shim | whether a tenant's channel links behave the same |
| linkedin.com | website found | company page vs personal profile may differ |
| x.com | website found | whether a low-follower/new account is served the same HTML |
| facebook.com | website found (honest UA only) | Pages vs profiles; login-walling varies by page |
| pinterest.com | website found | **BLOCKED, see below** |
| threads.net | website found (honest UA only) | |
| yelp.com / trustpilot.com / bbb.org / crunchbase.com | UNPROBED | these are third-party listings ABOUT the business — the tenant may not control the website field at all |

**Pinterest — half unblocked 2026-09-09.** Claiming the domain is required before Pinterest shows a
website at all, and `seo.pinterest_site_verification` now emits `<meta name="p:domain_verify">` on every
page of the Site, alongside the google/bing tokens. What is STILL outstanding is a page at `/`: the Site
root 404s because nothing is attached there, and Pinterest is expected to fetch the root (unconfirmed — it
may accept any URL on the domain, in which case the existing pages already carry the tag). The Homepage
picker on the Sites form should cover it. Note the claim is PER DOMAIN, so claiming a `.jbay.be` sandbox
address is throwaway work — claim on the live Site, or wait for the tenant's real custom domain.
Facebook domain verification uses the identical mechanism (`facebook-domain-verification`) and would be
one more line if it is ever wanted.

**Known unverifiable by design:** instagram.com, tiktok.com (login wall / JS shell). wikipedia.org,
wikidata.org excluded on purpose — anyone can edit them, so a positive result proves nothing.

**Record per host as it is tested:** where the tenant enters the URL, whether ownership proof is required
first, and whether the check goes green. The probes used high-profile public accounts as proxies; a new or
low-traffic tenant account may well be served different HTML, which is exactly the assumption this item
exists to retire.


### ⭐ HIGH — the dashboard has no linter, and it cost nine days of broken product editing (2026-09-10)

`Products.vue` called `productStore.fetchFull(row)` while declaring `const store = useProductsStore()`.
Editing any product failed with `ReferenceError: productStore is not defined`. Shipped 2026-09-01
(97186eb7), reported 2026-09-10.

**Nothing caught it because nothing could.** Vite does not resolve identifiers inside a function body, so
the build succeeded. The error only exists when the handler runs, and no test exercises the dashboard's
JavaScript. There is no ESLint config in `dashboard/` at all — so `no-undef`, the rule that exists precisely
for this, has never run against this codebase.

`tests/test_dashboard_store_references.py` now pins the one shape that bit us: every `*Store` a component
references must be declared in that component. That is a stand-in, not a fix. It catches `productStore`
and would have caught this bug nine days earlier; it catches nothing about a mistyped method, an undefined
helper, or an unused import.

**The real fix is ESLint with `no-undef` + `eslint-plugin-vue`**, wired into the dashboard build so a
broken identifier fails the build rather than the browser. That is a dependency and config decision rather
than a code change, which is why it is recorded here instead of done: it needs a call on whether the build
should fail on lint errors (it should) and how noisy the first run will be on an existing codebase.


### ✅ "Recurring" pricing saves cleanly and then charges ONCE — FIXED dev 2026-09-15

Raised by the author against the wizard's Pricing step ("Recurring — needs work"). It is not only a missing
interval picker; the model is not wired end to end, and it fails as a **plausible wrong answer** — the same
shape as the half-imported tip jar, and the worst shape there is.

**What I verified in the code today:**

1. **No interval is ever asked for.** `PricingCard` offers the radio and nothing else — no interval, no
   interval count. `defaultPriceForm()` in `stores/products.js` has no field to hold one either. (The flat
   `recurring_interval` on `utils/priceForm.js` belongs to TIPS and is only read on the `customer_chooses`
   branch.)
2. **Nothing is written.** `buildPriceDocument` (`stores/pricing.js`) writes `pricing_model: "recurring"` and
   never writes a `recurring` object.
3. **So Stripe gets a one-off price.** `build_price_params` (`domain/stripe_products.py`) sets
   `params["recurring"]` only when `price["recurring"]["interval"]` is present. It never is.
4. **And checkout would not subscribe even if it were.** `checkout.py` flips the session to
   `mode: "subscription"` on `item.get("recurring")` (line ~307), while the price-level fallback
   (`item.get("recurring") or price.get("recurring")`, line ~365) is read further down when building the line
   — so a price-level interval alone does not reach the mode decision.

**So today:** a tenant picks Recurring, the product saves with no error, the Stripe price is one-time, and the
buyer is charged once. Nothing anywhere says so.

**What the fix needs.** An interval control on `PricingCard` (interval + interval_count) writing a nested
`recurring` object; `buildPriceDocument` carrying it; the offer resolver lifting it onto the line so the mode
decision sees it; and a validator rule that a `recurring` price MUST have an interval, so this can never
again save as a silent one-off. The tip jar's own repeating path is separate and already works — reuse its
interval vocabulary (`tips.INTERVALS`), and note §5h's decision that the UI offers only month/year while the
runtime supports all four.

**What shipped**, built against the legacy spec the author supplied
(`stripe-cart/plans/one-time-and-recurring-payment-product-implementation.md` §1.3 and its Recurring screen):

- **Builder** — `PricingCard` grew a Billing block: interval (all four of Stripe's), "every N unit(s)"
  capped per interval, and an optional trial with a length and a price. The interval starts EMPTY and both
  the save and the wizard's Continue refuse without it; defaulting it to "month" would have been the same
  bug wearing a hat, silently choosing a billing frequency on the tenant's behalf.
- **Document** — `buildPriceDocument` writes the nested `recurring {interval, interval_count}` Stripe takes,
  plus `trial_period_days` / `trial_price`. `priceFormFromDocument` reads that nested shape back rather than
  through the tip's month-or-year field, which would have turned a weekly subscription into a monthly one.
- **Validator** — `validate_recurring_price`: an interval is REQUIRED and enum-checked, interval_count is
  bounded by what Stripe will actually bill, a trial is bounded at 730 days, and a trial fee with no trial is
  refused. This is the rule that makes the original bug impossible to reproduce.
- **Resolver** — `ResolvedOfferItem` carries `recurring` / trial terms, gated on `pricing_model` so a stale
  block left on a price switched back to one-time cannot resubscribe anybody.
- **Checkout** — the session flips to `subscription` off the resolved line (so it works for a SYNCED Stripe
  price too, where there is no inline `price_data` to read), adds `subscription_data[trial_period_days]`, and
  charges a PAID trial as its own one-time line indexed past every real line. Stripe has no paid trial — its
  trial is free by definition and Checkout always renders "X days free" — so this matches the legacy shape.
- **Published page** — `recurring_suffix` appends "/month" or "every 3 weeks" to the amount. A subscription
  rendered as a bare number was the buyer-facing half of the same bug.

32 tests in `tests/test_recurring_pricing.py` walk the whole chain, because every link was individually
reasonable and the gap only existed BETWEEN them.

**Why a PAID trial exists at all** (author, 2026-09-15, and worth protecting from being "simplified" into a
free one): a physical product has a real unit cost before shipping is even counted, so giving one away for a
trial period is a straightforward way to lose money on every sign-up. A paid trial covers that cost and keeps
freeloaders out, while still pricing the first period below the subscription. It is not a watered-down free
trial — it is the only trial a physical subscription can afford to offer.

**The fee class for a subscription follows the PRODUCT TYPE** — confirmed by the author 2026-09-15, closing
the question this entry previously left open. `fee_class_for` keying off `product_type` is correct and
deliberate: a physical subscription and a digital one have different costs behind them and the fee schedule
already distinguishes them. `pricing_model` does not enter into it (except for `customer_chooses`, which is
its own class because a tip is its own kind of transaction). Nothing to change; recorded so the next person
does not re-derive it as a bug.

**QA is outstanding and is tracked as its own HIGH item below** — the author owns it (see "QA: watch a real
subscription renew"). Nothing here has been exercised against live Stripe.

### ⭐ HIGH — QA: watch a real subscription renew (author's, 2026-09-15)

**Owner: the author.** This is manual QA against live Stripe test mode, not a code task — recorded here so it
is not mistaken for done just because the unit tests are green.

Recurring pricing shipped to dev on 2026-09-15 with 32 tests walking the chain (see the entry above), but
every one of them stops at the payload. **Nothing has been watched actually happen at Stripe.** That matters
more than usual here: the bug this replaced was precisely "correct everywhere except in production" — a price
that saved cleanly, synced cleanly, and charged once.

**What only a live run can tell us**, because it is where the interval, the trial boundary and the fee all
meet for the first time:

1. The Stripe Price is created as `type: recurring` with the interval and count the builder sent.
2. Checkout opens in `subscription` mode and the buyer sees the interval before paying.
3. A **free trial** delays the first charge by the right number of days.
4. A **paid trial** charges its one-time line up front AND still starts the trial — Checkout renders "X days
   free" regardless, so the two have to be seen together to confirm the fee was not lost.
5. The **renewal invoice** arrives on schedule, for the right amount, with
   `subscription_data[application_fee_percent]` taking the platform's cut — the percent is computed from the
   subtotal at session time, so this is the first moment it is applied to a real charge.
6. Editing the interval on a live product replaces the Stripe price rather than mutating it (`price_differs`),
   and existing subscribers keep their original terms.

Stripe test clocks are the practical way to do 5 without waiting a month.

### ✅ SHIPPED PROD 2026-09-18 — `jbay.page` link-in-bio serving is LIVE

Application side is done and shipped behind `CreatorServingEnabled="false"` — plans/CREATOR_DOMAIN_SERVING.md.
A Site now emits a THIRD domain-index record (`jbay.page/{username}`) alongside its custom-domain and
platform-host records; no second Site, no duplicated infrastructure.

**DONE:** zone + `A jbay.page` (proxied) + `jbay.page/*` Worker route + `CreatorServingEnabled=true` on prod
+ the hub 301 off the platform host. `jbay.page/poliaxis-nutrition` serves; `jbay.uk/link-bio` redirects to
it; the apex is `X-Robots-Tag: noindex`. Sequence recorded in plans/CREATOR_DOMAIN_SERVING.md §5.

**STILL OPEN, and it is the one that matters:**

1. ⭐ **plans/CREATOR_LINK_POLICY.md — code complete 2026-09-20, ops half outstanding.** Allowlist and adult
   interstitial shipped 2026-09-11; reporting (`POST /report`, footer link, throttle) and the §7 staleness
   test shipped 2026-09-20; fast suspension was already true via Site archive. **Still needed before the
   domain carries third-party traffic: a monitored abuse address, a named owner, and a written target
   response time.** An endpoint recording reports nobody reads is worse than none — it implies a process
   that does not exist. The queue that makes it actionable is recorded in **plans/ADMIN_SITE.md §1**, whose
   §3 notes the prerequisite: an admin surface needs an admin ROLE, and this repo has none — it lands on the
   ⭐⭐ authorization gap below.
2. Public Suffix List submission — slow, start early.
3. Dev serving (`test.jbay.page`) has no DNS or route; dev stays dark until someone needs it.

Then the dashboard surface: show a tenant their creator URL, and decide whether a username may differ from
the store label (today it IS the platform subdomain label, which buys one namespace, one registry and the
reserved wordlist for free — see the doc §3 before adding a second field).

### MEDIUM — the "Search-friendly" goal does not mean what a tenant reads it to mean (raised 2026-09-17)

Author, 2026-09-17: *"if I want to create a page that can rank on Google, that's the choice I want to make.
Clearly adding structured data and FAQ are not nearly enough."*

**What it does today.** `search_seo` carries exactly one pack, `discoverability`, whose entire contents are
seeding an `faq` element and making `structured_data` available (`composition_rules.json`). The tenant picks
a goal named "Search-friendly", is shown the note "adds search-friendly content", and gets an FAQ box. Two of
the five goals (`email_list`, `minimal`) already carry no packs at all, so the goal layer is thin generally --
but this is the only one whose LABEL promises an outcome the product is responsible for delivering.

**What the tenant reads it as.** "Set this page up to rank." That is a real job, and most of its parts either
exist unconnected or are already planned:

1. **On-page fundamentals** -- heading outline, unique-content floor, image alt. All three already have
   checkers (`heading_outline_warnings`, `thin_content_warnings`, `accessibility_warnings`, runtime/html.py)
   and surface in the builder's Page health panel. They are not connected to the goal in either direction.
2. **Google Business Profile** -- plans/BUSINESS_PROFILE_AND_GBP.md Phase 2 (GBP OAuth + sync), deferred.
   The canonical NAP that feeds LocalBusiness JSON-LD is Phase 1 of the same doc.
3. **Backlinks** -- the social backlink verification already built for `sameAs` is the nearest existing
   machinery; whether an SEO goal should do more than verify is undecided.
4. **Indexability itself** -- the thing a tenant would most expect this switch to control, and the one thing
   it has no bearing on whatsoever. `page_robots_directive` (html.py:1697) needs a verified custom domain and
   verified Connect; a platform host is noindex,nofollow regardless of goal. A tenant who picks
   "Search-friendly" on a platform-hosted page has been told they are optimising for a search index the page
   cannot enter.

**The sharpest single change, and the reason this is worth doing.** The page-health warnings matter MOST when
the goal is search, and mostly do not matter otherwise -- so gate them on the goal:

- **SEO-only, gate on `goal == "search_seo"`:** thin content, heading outline. Both are about ranking. Note
  `thin_content_warnings` has already been carved back twice by hand (every lead shape, then tip jars) for
  exactly this reason -- "a warning has to name something the tenant can do AND should do". The goal is the
  general form of those two special cases, and would subsume both.
- **ALWAYS, never gated:** image alt text. A screen-reader user does not care what the page's marketing goal
  is, and alt text is an accessibility floor with legal weight, not an SEO nicety. Heading outline is
  genuinely dual-purpose (screen readers navigate by headings), so if it moves behind the goal the
  accessibility half of its value moves with it -- worth deciding deliberately rather than by omission.

Also consider suppressing the SEO-only warnings on any page whose robots directive is already noindex: today
they fire on pages that cannot be indexed at all, which is the same unactionable-notice failure in bulk.

**Not** an argument for making the goal picker do more work at create time. The goal governs composition; the
gap is that a name promising search performance is attached to a pack that seeds an FAQ.

### ⭐ HIGH — the Products wizard promises a booking flow that does not exist (raised 2026-09-18)

Plan: **plans/SERVICE_WIZARD.md**. Picking "Service — opens booking flow" runs the physical-product path,
package dimensions and all: `WIZARD_FLOWS` branches on intent and nothing in Products.vue branches on
product_type. Meanwhile the only way to create a Service is a 22-field modal for a document whose validator
requires three fields.

The scope is smaller than it looks. The SELLING half is built and tested -- expand_offer resolves service_id,
checkout handles service lines, `booking` is a real CTA with a handler behind it, 59 tests pass across five
service/booking files, multi-calendar shipped. The gap is authoring: nobody can create a service.

Blocked on one decision (doc §3): is a "service" a Product with product_type=service, or a Service document
with fulfillment_mode scheduled|no_booking? Today both exist and nothing links them. Recommendation is the
latter -- one concept, two modes -- which dissolves the confusion instead of documenting it.

Zero service products and zero prod Services exist, so there is nothing to migrate. Cheapest possible moment.

### ✅ FIXED + MIGRATED 2026-09-20 — one domain-index row served TWO mode-partitioned Sites

Found on prod while baselining a deploy: `poliaxis-nutrition.jbay.uk/link-bio` 404s, and so does
`jbay.page/poliaxis-nutrition`.

Not a bug in the creator domain. The Sites table holds **two rows for one Site** -- `SITE#live#site_GCT...`
and `SITE#test#site_GCT...` -- because Sites are partitioned by Stripe mode. The domain index holds **ONE**
row per hostname (`CUSTOM_DOMAIN#poliaxis-nutrition.jbay.uk`), carrying a single `stripe_mode` field to pick
the artifact partition. So both mode copies project onto the same row and the last publish wins.

Today the LIVE Site is archived and the TEST Site is active. The shared row says `status=archived,
stripe_mode=live`, so the hostname serves nothing in either mode.

**The collision is pre-existing; the 2026-09-18 archive change made it consequential.** Before it, platform
records were always `status: "active"`, so mode-fighting only swapped `routes`/`target_page_id` and the
damage was invisible. Now one mode's archive is a kill switch for the other.

**DECIDED (author): a hostname per mode**, "that's how it was set up in stripe-cart" — where test pages
served on their own `test.juniorbay.com` (`src/test_page_serve.py`), separate from live.

Shape: **`{label}-test.{domain}`**. One label level, so the existing `*.jbay.uk` certificate and the
zone-wide Worker route cover it with no new infrastructure. `{label}.test.{domain}` would be collision-proof
but sits two levels deep, which Universal SSL does not cover and Advanced Certificate Manager charges for.

Because `maria-test` is itself a legal label, claiming `maria` now claims **both** names in the registry —
otherwise a second tenant could register `maria-test` and take over the first tenant's sandbox host.

`jbay.page/{username}` is **live-mode only** for the same reason: one public name per creator, and the apex
is an identity rather than a sandbox.

**DONE.** Code shipped dev+prod and `deploy/migrate_mode_hostnames.py --apply` run on both (1 Site on
prod, 6 on dev). Verified after: **zero hostnames shared by two modes** in either environment — prod went
from 1 shared hostname to 2 distinct, dev from 7 to 8. The script is idempotent; a second dry run finds
nothing. The code also self-heals on save, so a Site created before this corrects itself when next edited.

**Left for the author, and neither is a defect:**

- Re-publish an affected Site's pages to push its new hostname into the edge index. Until then the new host
  has no row and 404s; the old host keeps whatever the surviving mode last wrote, which is now correct.
- `poliaxis-nutrition.jbay.uk` is free for the LIVE Site again, but that Site is archived — so `/link-bio`
  and `jbay.page/poliaxis-nutrition` stay 404 until it is reactivated. That is the sunset feature working,
  not the collision.

### ✅ FIXED 2026-09-20 — a recurring SERVICE price silently charged once

Plan: **plans/RECURRING_SERVICES.md**. Proven, not suspected:

```
service price says:   pricing_model=recurring, monthly
resolved line says:   recurring = None
Stripe session mode:  payment  ->  charged ONCE
```

`resolve_service_offer_item` never applies `recurring_terms(price)` (the PRODUCT resolver does), and
`validate_service` accepts a recurring service price. The only thing preventing a mis-charge is the pricing
dropdown offering one option — the same "two things that must agree with nothing forcing them to" shape as
the product recurring bug of 2026-09-15.

**FIXED by refusing, not honouring** — honouring would ship half a feature: Stripe billing monthly while
nothing creates the appointments each cycle pays for.

- `validate_service` refuses any `pricing_model` but `one_time`, in BOTH the `prices[]` entries and the
  legacy single `price` every service still carries. The message names the plan.
- `resolve_service_offer_item` refuses one too, as defence in depth. Refusing a checkout is bad; charging a
  subscriber once and never again is worse, and silent. Only a hand-edited or imported document can reach it.
- A test binds the services form's offered models to what the validator accepts — the two things that must
  agree, with something now forcing them to. Verified by making the dropdown drift and watching it fail.

Zero services in dev or prod carried a non-`one_time` price, so nothing needed migrating.

Also corrects a stale note: plans/BOOKING_AS_PRIMITIVE.md says "no code yet". Appointments already use the
canonical `services[]` shape, with slot locks, manage/cancel/reschedule tokens and real Google Calendar sync.
What does not exist is anything producing appointments OVER TIME.

### LOW — a draft page's Site URL serves a raw CloudFront 403 (found 2026-09-18)

Noticed while verifying the new edge error page. A page attached to a Site but still a DRAFT has no published
artifact, so the resolver hands the Worker an origin_url that does not exist and the visitor gets
CloudFront's own 403 — platform plumbing, in the one place a stranger might land. Three dev Sites do this
today (`/creatine-gummies`, `/mini-guard-cam`, `/emergency-water-damage`).

It should be the same 404 page everything else now gets. Pre-existing and unrelated to the archive work, but
the same class: a visitor seeing our internals because a URL resolved further than the content did. Cheapest
fix is probably the Worker treating a non-OK origin response as a not-found rather than proxying it through.

### LOW — three shipped presets pair their CTA gradient with white below WCAG AA (measured 2026-09-17)

Found while fixing the section tones, and deliberately NOT fixed there. Measured on the shipped
`UNIVERSAL_BUNDLE_THEME_PRESETS`, `cta_text` (`#ffffff`) against the first gradient stop:

| preset | first stop | contrast | AA-large |
|---|---|---|---|
| natural-calm | `#22c55e` | 2.28 | 3.0 |
| clean-slate | `#0ea5e9` | 2.77 | 3.0 |
| coral-sunrise | `#f97316` | 2.80 | 3.0 |

This is not a tone bug and not a regression: it is the pair those presets have always used, so it is already
true of **every ordinary CTA button** on every page wearing them — the tones only made it measurable. The
other thirteen presets clear 3.0 on all three tones (`tests/test_section_tone_contrast.py` prints the grid).

Why it is left alone: changing a preset's `cta_text` or gradient restyles every page already wearing it,
including pages whose artifacts were baked at publish time and would then disagree with pages republished
later. Nudging the stops darker (`#16a34a`, `#0284c7`, `#ea580c` all clear 3.0) is the small fix, but it is
a product-wide visual change and the author's call, not a quiet one to make inside a bug fix.

### MEDIUM — a just-provisioned tip jar shows no URL until the page is refreshed (found 2026-09-15)

Reported by the author immediately after the provisioner shipped. Clicking "Create your free Tip Jar page"
creates everything correctly and the toast is right, but the "Goes to …" line stays empty until a reload.

**Cause, confirmed not guessed.** `deriveOfferType()` calls `offerIsTipJar(offer)`, which looks the offer's
items up in `products.value` to find a `customer_chooses` price. The provisioning response pushes the new
PAGE and OFFER into their lists but not the PRODUCT, so the lookup misses, the offer reads as `single`, the
brand-new page is filtered out of `tipJarPages`, and `applyTipJarPage` resolves nothing. A refresh reloads
products and it all resolves.

**Two fixes, and the second is the real one.**

1. Push `body.product` into `products.value` alongside the other two. One line, fixes this screen.
2. Stamp `pricing_model: "customer_chooses"` onto the SEEDED OFFER document. `stamp_tip_jar()` already does
   exactly this at render time, for exactly this reason — "the composer takes the OFFER and never its
   products". A seeded offer that says what it is needs no product lookup from anyone, ever, and the class of
   bug (a derivation that silently needs a second document to be loaded) stops applying to it.

Do both. (2) alone would fix this symptom, but (1) is what keeps the three lists this screen reasons about
honest after a write.

### ⭐ HIGH — Tip Jar ("Customer chooses") is half-imported and MIS-PRICES TODAY (plan plans/PAY_WHAT_YOU_WANT.md, 2026-09-13)

A live bug, not a missing feature. stripe-cart ships this; stripe-link imported the fee class and the form
control and stopped. `pricing.js` writes `min_amount`/`suggested_amount` on top of a normal `unit_amount` from
the Sales price field, and `pricing_model` appears NOWHERE in `checkout.py`, `pricing.py` or
`runtime/html.py` — so a tip jar saves without error and **sells at whatever the tenant typed**. A plausible
wrong answer, which is the worst failure shape.

**Nothing ever tracked it.** The only mention of `tip_jar` in this file was the FEE TABLE below — the pricing
decision was recorded, the feature was not, and the gap had no owner. Noted because that is the failure worth
learning from: a fee class for a thing nobody built reads as evidence the thing exists.

`additionalProperties: false` on `Price.schema.json` was NOT a deliberate deferral — every schema in the repo
is closed, it is house style. It silently refused the rest of the legacy model without anyone noticing, which
is the closed-schema default doing its job with nobody reading the result.

- ✅ **Price model DONE 2026-09-13** — `presets[]`, `preset_charges[]`, `max_amount`, `allow_custom`,
  `allow_recurring`, `recurring_interval`; a `customer_chooses` price must now offer SOME way to choose,
  which is the rule that stops this recurring. A preset stores BOTH numbers — what the tenant keeps and what
  the buyer pays (§5e, reversing the first day's "presets are charged amounts").
- ✅ **Product wizard DONE 2026-09-13** (`LEAD_GEN_PAGES.md` §10) — intent first, tip jar as a third answer;
  tips file themselves as `digital`/`tip`, and each amount previews "customer pays / you keep".
- ✅ **Runtime DONE 2026-09-13** — a card per preset plus an optional "Other" box priced through the server's
  own `/prices/calculate`; `apply_tip_amount` re-decides the charge at checkout; a repeating tip becomes a
  Stripe subscription; the page composes as `tip_jar` (no trust badges — nothing ships).
- ⭐ **Refund a tip NET, not gross** (DECIDED 2026-09-14, plan §5f): a refund returns the TIP, and whoever
  paid the fees loses them — the fee mode applied a second time. Under `net_guaranteed` (the default) the
  creator ends at $0.00 on a refunded tip; under `standard` they absorb ~11% for doing nothing, which the
  wizard should say. Needs, in order: (1) **record the keyed amount on the order** — a typed custom amount
  exists only in the checkout request today (`handlers/checkout.py` writes no `tip_keyed_amount`), so the
  net is uncomputable afterwards; (2) refund the net in `handlers/refunds.py`, which today refunds
  `order.amount_total`; (3) say it on the receipt and the refund confirmation, not only on the card.
- **Open: the refund policy WORDING** (plan §5f, raised 2026-09-13). There is nothing to return, so the policy has
  to answer a different question: how long may a supporter change their mind, and who decides? Known so far:
  Stripe sets no card-refund deadline (the 180-day limit is ACH/SEPA); Ko-fi and Buy Me a Coffee both say
  tips are non-refundable and leave it to the creator, and Ko-fi caps its own refund flow at 180 days; the
  binding deadline is really the chargeback window (~120 days, longer in some cases). Still unanswered:
  whether a gratuity is a "sale" under consumer statutes at all (jurisdictional — needs someone qualified),
  who owns the decision under direct charges, what happens to the platform fee, and how a recurring tip is
  cancelled (there is no buyer-facing way today). Pairs with the tip-income tax question.
- ✅ **Recurring tips are unblocked**: the cancel link shipped 2026-09-14 (next entry). The re-send page and
  the support runbook are still open, so a supporter whose receipt never arrived still has no self-serve
  route.
- **Open: is a tip an ORDER** — receipts/refunds/fees/ledger all assume one, and a tip has nothing to
  fulfil. Plus gratuity tax treatment.

### ⭐⭐ HIGH — the DEPLOYED fee table was three weeks stale, on dev AND prod (found 2026-09-14)

The Payments screen showed a free tenant "Physical 10% / Digital 15%". Not a display bug: `/prices/calculate`
on dev really answered 10% (probed live — $100 keyed, split fees, came back $107.06 with a $10.71 platform
fee instead of $104.27 / $5.21).

**Cause.** `deploy.sh` uploads `schemas/examples/global-billing-config.json` to the config bucket, and
`cached_billing_config()` prefers that S3 object over `DEFAULT_GLOBAL_BILLING_CONFIG`. The 2026-08-26 pricing
pivot updated the code default (5/6/7 free, 2/2/2/0 premium) and never touched the file, so the deployed
config silently outranked the decision. The file still said basic 10/15, standard 8/13, pro 5/10/2, and had
no `service` class at all — services fell through to the code default and were accidentally right while
physical and digital were wrong. `tip_jar` was 5% in BOTH tables, which is why three weeks of tip-jar work
never tripped over it.

**It was visibly inconsistent the whole time.** The dashboard's own `TIER_RATES` mirror in `stores/pricing.js`
carried the correct post-pivot rates, so the authoring preview quoted $104.27 while the server charged
$107.06. A tenant could read one number and be billed another.

**A test was pinning it in place.** `test_billing_connect_card_uses_tenant_tier_and_billing_config` asserted
`physical == 10.0` against that fixture — the bug had a passing test.

**Second bug, same cause.** `set -euo pipefail` plus `sam deploy` exiting non-zero on "No changes to deploy"
meant the script stopped BEFORE the config upload whenever the stack itself was unchanged — so a
config-only change could never be deployed. Fixed with `--no-fail-on-empty-changeset`.

- ✅ Fixed 2026-09-14: file now matches the code default; `deploy.sh` reaches the upload; the stale test
  assertion corrected; `tests/test_billing_config_deployed.py` pins the deployed document to
  `DEFAULT_GLOBAL_BILLING_CONFIG` field for field, checks every tier prices every fee class, and asserts the
  path `deploy.sh` actually uploads.
- ✅ Dev config re-uploaded and verified in the bucket (the running Lambdas pick it up within the 300s
  `BILLING_CONFIG_CACHE_TTL_SECONDS`).
- ⛔ **PROD IS STILL STALE — needs a deploy.** Until then live tenants are charged 10%/15% instead of 5%/7%,
  and premium subscribers 5/10/2 instead of 2/2/2/0 (proportionally the worst hit).
- ⛔ **Decide what to do about fees already over-collected on prod** since 2026-08-27. The money went to the
  platform as `application_fee_amount`, so it is ours to give back if that is the call. Needs a number first:
  sum the platform fees on prod orders in that window and compare against the pivot rates.
- **Deeper smell worth fixing:** the canonical RUNTIME config lives in `schemas/examples/` and reads as test
  data, which is exactly why a pricing change skipped it. Move it to a real config path (e.g.
  `config/global_billing_config.json`) so the next person editing fee rates finds it.

### MEDIUM — say on the refund dialog that the fees are not coming back (DECIDED 2026-09-14)

`handlers/refunds.py` issues refunds without `refund_application_fee`, which defaults to **false** — so the
platform keeps its application fee on every refunded order. The module docstring calls it "legacy behavior",
carried from stripe-cart; it had never been a decision and was stated to tenants nowhere in the product.

**DECIDED: keep the fee, and disclose it** (author, 2026-09-14). Keeping it prices refund risk to the only
party who can reduce it — the tenant chooses what to sell, how to describe it and how to fulfil it, and we
do not. A tenant whose products generate constant refunds would otherwise be subsidised by every tenant
whose products do not. What was missing was not the policy but the sentence.

**Where it goes: the "Issue refund?" confirm dialog** (`dashboard/src/components/Refunds.vue`) — the last
screen before money moves, where the tenant can still choose a replacement or a partial instead. Wording to
be plain and NON-numeric (author): *Stripe's fee and the Junior Bay fee are not returned. You refund the
full amount your customer paid, and those fees come out of your own pocket.*

**NOT on the pricing form** (author overruled the earlier proposal, and was right): a refund caveat beside a
price is unactionable at that moment — the tenant is deciding what to charge, and the only "action" it
suggests is switching fee mode, which the break-even below shows is the wrong move. It would be a scare that
costs them money.

✅ **The sentence SHIPPED 2026-09-14** on the confirm dialog (`Refunds.vue`), with a test that also pins it
OFF the pricing form.

**Still to add: "this refund will cost you $X", in the same dialog** (author approved the placement). Not
free, which is why it did not ship with the sentence: a refund request carries `amount.paid_amount` and
nothing about fees, and the accurate figure needs the ORDER (its `amount_total` + the `product_type` /
`tenant_plan` metadata `fee_breakdown_from_session` reads). Two ways:
- Look the order up in `list_refund_requests` — a new Orders read from the Notifications function, so a
  template grant too, and a per-row lookup.
- **Freeze the fee cost onto the refund request when it is created** (`save_refund_request`). Preferred: it
  matches the derive-vs-freeze rule this codebase already follows for financial records, needs no grant and
  no lookup, and the number is then the one that was true at the time rather than a recomputation. Pairs
  with the tip work, which must freeze `tip_keyed_amount` on the order for the same reason.
Do NOT compute it in the dashboard: the fee maths has one implementation, server-side, and a second copy on
a refund screen is the drift this repo keeps paying for.

What it costs them, run through `calculate_price` on a $100 keyed product, free tier, physical (5%):

| mode | buyer pays | Stripe | Junior Bay | tenant nets | **after a refund** | if we returned ours |
|---|---|---|---|---|---|---|
| `standard` | $100.00 | $3.20 | $5.00 | $91.80 | **−$8.20** | −$3.20 |
| `split` | $104.27 | $3.33 | $5.21 | $95.73 | **−$8.54** | −$3.33 |
| `net_guaranteed` | $108.91 | $3.46 | $5.45 | $100.00 | **−$8.91** | −$3.46 |

Digital (7%, free tier) is worse: −$10.20 / −$10.74 / **−$11.32**. Premium (2%): −$5.20 / −$5.33 / −$5.47.

**The finding that matters: `net_guaranteed` is the WORST mode for a tenant on a product refund** — exactly
inverted from tips (§5f), where it is the mode that saves them. The fees scale with the gross, and
`net_guaranteed` has the biggest gross: the tenant received $100 and returns $108.91. The net-refund trick
that makes a tip cost $0.00 cannot rescue this, because for a product the grossed number IS the advertised
price and the buyer is owed all of it back.

The only lever is our own fee, worth $5.00–$7.79 per refunded $100 to the tenant. Weighed and KEPT (above).
The case against keeping it, recorded because it is the one a tenant will make: the fee is the entire revenue
model of a free tier whose pitch is "you keep more", and a charge levied on a sale that no longer exists is
the kind of thing tenants screenshot.

**But `net_guaranteed` is NOT the risk it looks like, and a warning aimed at it would mislead.** Per $100
order it earns the tenant **+$8.20** on every completed sale and costs **+$0.71** on a refunded one
(digital: +$10.21 / +$1.12). Break-even is a refund rate of **92%** (digital 90%) — so `net_guaranteed` is
the better deal for any real business, and steering a tenant to `standard` to dodge $0.71 would cost them
$8.20 per sale. The ~$8.20 baseline loss is the REFUND, not the mode. Any disclosure has to be about what a
refund costs, in every mode, not about net-guaranteed.

Good news on defaults: products already default to `standard` (`utils/priceForm.js` defaultPriceForm) and
only tips default to `net_guaranteed` (the wizard sets it). That split is already right.

For proportion: a CHARGEBACK costs the tenant the full $108.91 plus a ~$15 dispute fee. A refund at −$8.91
is the cheap outcome, which argues for making refunds easy however this is decided.

NOT the same question as tips, where §5f settles it: there the buyer volunteered the fee and the page says
so, so keeping it costs the tenant nothing. For products under `net_guaranteed` the grossed amount IS the
advertised price — a net refund there short-changes the buyer for a returned good, so the refund must stay
gross and the only live question is whether WE return our cut.

Decide, then say it somewhere a tenant reads before their first refund.

### ⭐ HIGH — one button for "stop charging me / I want my money back" — v1 SHIPPED dev 2026-09-14 (plan plans/PURCHASE_SELF_SERVICE.md §9)

**Still open after v1** (the lookup POST is now gated — honeypot + per-contact and per-tenant counters,
failing open): policy-aware copy on the transaction page ("6 days left"
vs "non-refundable", which is where PAY_WHAT_YOU_WANT.md §5f's tip rule gets written for buyers); SMS
delivery for the phone path; and re-download / booking cancellation as actions.

A customer who wants to cancel or be refunded has two routes today: find our email, or find the tenant. This
is the third and the one they will look for — a link at the bottom of the page NEXT TO THE REFUND POLICY,
because that is where someone goes when they want the money to stop (author). Tenant-agnostic: any Junior
Bay page can start a request about any Junior Bay purchase.

The rule it runs on: **actions that cost the tenant nothing are self-serve (cancel a subscription, download
again); actions that move money are a REQUEST the tenant answers.** And it identifies exactly ONE
transaction — the latest, or the nearest to an approximate date the customer gives — and never enumerates.
A list behind one emailed link is both a privacy target and the screen that ends three subscriptions instead
of the one they came for.

It is the missing FRONT DOOR for things already built: `refund_request` documents, the tenant notification,
approve/reject/execute on the Refunds screen, and a creation endpoint (`PUT /notifications/refund-requests`)
that nothing calls.

**v1 is TENANT-SCOPED** — the button handles purchases made from that tenant's page. Stripe cannot do better:
`customers/search` matches email/phone but only within ONE account, and under direct charges every tenant is
their own; charges and payment intents cannot be searched by email at all; and a Customer object only exists
for subscriptions or when we ask, so a one-off purchase is invisible to an email search. Our own orders are
the index.

- ⬜ **Widen to cross-tenant in a later version** (plan §5a). Wanted because a link-in-bio page can be
  SWAPPED by the creator, so the page a charge came from may be gone (author, 2026-09-14) — though the
  receipt link is page-independent and already covers that case. Needs an index spanning every tenant, which
  is the buyer graph of the whole platform in one place and wants its own access rules. Build it when
  support volume shows people arriving at the wrong page, not on speculation.
- ⬜ **No GSI needed for v1**: orders are keyed `(tenant_id, order_id)`, so once the tenant is known the
  lookup is a query on that tenant filtered by email — the index is a scale optimisation, not a
  prerequisite. Still **add `contact_key` to the order record BEFORE any index** (plan §5b). A GSI can be added to a live table
  with no downtime, but it only indexes items that carry its key attribute, and CloudFormation allows ONE
  index change per stack update. Stamping the attribute early means a later backfill covers history only.

Supersedes the tip-specific re-send page in PAY_WHAT_YOU_WANT.md §5g, which becomes one narrow answer here.

### ✅ HIGH — a supporter cannot cancel a recurring tip — SHIPPED dev 2026-09-14 (plan §5g)

Checkout now opens a real `mode: subscription` session for a repeating tip. Nothing lets the supporter stop
it: the only path today is asking the creator to cancel it in their Stripe dashboard — the Ko-fi behaviour
we spent a design conversation arguing against. **Recurring tips must not be enabled for live tenants until
this ships.** Not a polish item: a recurring charge nobody can stop is a chargeback generator, and under
direct charges the dispute fee AND the ratio land on the TENANT's account.

**DECIDED: a tokenized link, not a buyer account** (author: "NO, we don't want to create a buyer-side
product, at least not initially... I certainly don't want to create friction between customers and tenants
when it comes to giving them a tip or purchasing a product"). The reasoning, including the lost-email
objection and why an account does not actually answer it, is §5g — worth reading before anyone reopens it.

- ✅ **Receipt link**, minted as an opaque `secrets.token_urlsafe(24)` when the subscription is created,
  stored with a 400-day TTL (a supporter may cancel a year in).
- ✅ **Portal session** on the CONNECTED account (`handlers/tip_manage.py`, `GET /tips/manage?t=`).
- ✅ **`metadata[tip_keyed_amount]`** stamped on the session — the §5f refund prerequisite, captured here
  because this is what first put a tip through checkout.
- ✅ **A fresh link on every charge** (`notify_tip_renewal`): each renewal emails a short notice carrying a
  new token, so the newest email always works. Also the first time a repeat charge produced any email from
  us at all. Intervals narrowed to monthly + yearly in the BUILDER only — the runtime still handles all four.
- ⬜ **The re-send path** — SUPERSEDED by plans/PURCHASE_SELF_SERVICE.md, where it becomes one answer from
  a tenant-agnostic "manage a purchase" flow rather than a tip-specific page. NOT built.
- ⬜ **A support runbook**: verify ONE of card last-4 + expiry / exact amount + date / billing postcode, then
  cancel. The bar is low on purpose — cancellation is fail-safe, and an agent who refuses to act sends the
  supporter to their bank instead, which costs the tenant a dispute fee. NOT written.
- ⬜ **Verify the portal is configured** on a connected account in live mode before relying on it: Stripe
  requires a billing-portal configuration per account, and an unconfigured one answers an error the endpoint
  currently renders as "try again in a minute".

**Deferred, on its own merits:** buyer-side accounts. The question they belong to is "do we want a
buyer-side product?" (a supporter dashboard across creators, i.e. plans/DIGITAL_MARKETPLACE.md), not "how do
people cancel?". If they ever arrive they are ADDITIVE — an optional prompt after the tip, never a gate
before it.

### FUTURE — SMS capture is its OWN page, not a checkbox on the phone one (author, 2026-09-16)

Decided while finishing the phone-capture page, and recorded because the cheap-looking version is wrong.

A phone capture collects a number so the tenant can **call the person back**. That is an inquiry the visitor
asked for. Marketing texts to the same number are a different permission entirely: in the US, TCPA requires
prior express **written** consent for marketing calls and texts, with its own disclosure wording, its own
record-keeping, and statutory damages per message when it is missing. The email opt-ins were removed from
the phone page for a related reason — no address means no list — and reusing either box for SMS would
manufacture a consent that does not meet that bar.

So when marketing SMS is enabled it gets its own page shape (a fifth alongside capture / call / bridge /
social), with its own consent language, not a third checkbox on this one. Gated on the SMS capability being
live; the note in `render_email_cta` points here.

### ⭐ HIGH — Lead-generation pages: four shapes, not one (plan plans/LEAD_GEN_PAGES.md, 2026-09-10)

A lead-gen offer currently builds a **checkout page with the price hidden**. Observed on a real page: trust
badges, a refund policy, the product name as both brand and headline, and a "Social page" CTA redirecting
to one profile. The composer switching on `product_intent` (shipped) removes the price selector and is not
enough — the seven lead-capture actions want genuinely different pages.

- **Seven actions collapse to FOUR shapes:** capture form (the three `capture_*`), call, bridge
  (`external_url`), link-in-bio (`social_redirect`).
- **`open_form` is REMOVED, not deferred** — `form_id` read by nothing, blocked on a form builder that does
  not exist, and verified ZERO products use it in dev or prod.
- **The bridge page is ALWAYS noindex,nofollow**, no override. It is a thin bridge page by definition;
  indexing one risks the Site's reputation for a page with no content of its own. Legitimate beyond
  affiliate links — redirecting a stale but popular domain to a new one — and those uses do not want
  indexing either.
- **The composer must see the ACTION**, which means denormalising `lead_capture_action` onto the Offer the
  way `product_intent` already is.
- **Fix FIRST:** `builderIntent` and `deriveOfferType` derive intent differently, and the offer index row
  stores `""` rather than null. That split is what put trust badges on the observed page.
- Product creation becomes a WIZARD (intent first, then action, skipping transactional fields). A separate
  top-level section like Services was considered and rejected: a lead-gen product is the same entity.

### MEDIUM — Reddit is its own study, NOT another entry in the social allowlist (raised 2026-09-09)

**Deliberately excluded from `SAME_AS_HOSTS` on 2026-09-09.** Adding it would have been a one-line change
and it would have been wrong. Recording why, so it is not "fixed" later by someone adding the line.

**1. It does not fit `sameAs` semantically.** `sameAs` asserts *this entity IS that profile*. A subreddit is
a COMMUNITY, ordinarily not owned by the business — asserting `sameAs` on `r/whatever` claims an identity
relationship that does not exist, and on a general-topic or competitor subreddit it is a false claim we
would be emitting in our own structured data. A `/user/` account is a person, not the business. So the one
field we would slot it into is the one place it does not belong. Yelp, BBB and Crunchbase are all
third-party pages ABOUT the business; a subreddit is not.

**2. The value on offer is CITATION, not identity.** The reason to care about Reddit is that its threads
rank well and are heavily cited in AI answers — a visibility and content play. That is the
`ATTENTION_PRIMITIVE.md` family (offer → channel → attribution), not a Business Profile field. Slotting it
into `same_as` would file a content strategy under an identity claim and guarantee it gets built wrong.

**3. Getting it wrong is worse than not doing it.** Reddit removes self-promotion, subreddits enforce their
own rules, and astroturfing is bannable and reputationally expensive — for the TENANT, whose account and
brand carry the damage, and for us if we built a feature that encouraged it. A naive "post your link"
integration is a liability, not a channel. This is the strongest reason to design before building.

**What to study before designing anything:**
- Which URL shape, if any, we would ever record: `/r/<sub>`, `/user/<name>`, or a specific thread. They have
  different owners and different meanings; only one of them could plausibly be an identity claim, and it is
  probably `/user/` for a solo creator whose Reddit account IS their public presence.
- Whether verification is even possible: `old.reddit.com` serves more in raw HTML than `www`, so a sidebar
  or profile backlink check may work where the modern UI does not. UNMEASURED — probe before promising it,
  the way Instagram/TikTok were probed (§7a-i).
- Reddit's API terms and rate limits post-2023, which are paid and restrictive, and its robots policy. What
  is technically possible and what is permitted are different questions here.
- Whether the right primitive is participation (a tenant genuinely answering in their niche) rather than
  anything automated. If so the product is guidance and measurement, not posting.

**Do not add `reddit.com` to `SAME_AS_HOSTS` as a step toward any of this.** The allowlist is for identity
claims. If Reddit earns a place in the product it will be somewhere else.

### ⭐ HIGH — Social Media Pages (link-in-bio) — P0–P4 SHIPPED PROD 2026-09-10 (plan plans/SOCIAL_MEDIA_PAGES.md)

**Built and live in prod:** server-owned `same_as` verification + the backlink verifier (P0), the
`social_media` composition with `social_links` and `link_cards` and builder support for both (P2),
republish-on-domain-disconnect (P3), and derived page conversions/revenue plus the view-counting rail (P4).

**What remains:**
- `profile_avatar` — belongs to `SOCIALITE_PARITY.md`, not here.
- **`PLATFORM_LINKABLE_HOSTS` is still just the 16 identity hosts**, so Amazon, Etsy, Substack and Patreon
  render as inert tiles on a free `*.jbay.uk` address. This is the gap between "built" and "usable" for a
  free-tier creator page, and it needs an abuse story rather than a longer list — see §7 on why the reason
  is the URL bar and not SEO. **The abuse story is now written: `plans/CREATOR_LINK_POLICY.md` (2026-09-11)**
  — creator-shaped allowlist, host-derived adult warning, reporting/takedown, and why it gates `jbay.page`.
- Per-link click counts: the rail exists (P4) and takes a second event type; not wired.

The original entry follows.

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

BLOCKERS found while planning (both RE-VERIFIED 2026-09-09, still true; line numbers had drifted):
  - `same_as` has NO dashboard UI — validated, never enterable. Nothing works until P0.
  - `same_as[].verified` is READ (now html.py:3646 and 5089) but SET NOWHERE, so no social link
    renders today and "verified" is self-assertable — the anti-impersonation guarantee does
    not currently exist. Same silent-drift shape as the SENSITIVE_FIELDS denylist.

**Verification DECIDED 2026-09-09 — see SOCIAL_MEDIA_PAGES.md §7a-i.** Measured with a throwaway Lambda,
not assumed: `rel="me"` is emitted by just ONE of the ten hosts tested (GitHub, as `rel="nofollow me"` —
corrected from an initial "zero" that came from a regex requiring the value to be exactly `me`), so a
rel-parser would verify one host where a URL-presence check verifies eight. Lambda fetches BETTER than a laptop, and an honest user-agent beats
a browser string (Facebook returned 400 to Chrome, 200 to us). 8 of 10 hosts verifiable; Instagram and TikTok
are not, by any unauthenticated means. Wikipedia/Wikidata excluded — anyone can edit them, which is the
impersonation vector itself. Two-tier result: unverifiable links still RENDER, they just never enter `sameAs`,
so the traffic-dominant platforms are unaffected. IG/TikTok verification later rides the aggregator already
planned for campaign publishing.

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

~~Also supersedes: retire `social_redirect`~~ — **REVERSED 2026-09-10**, see `SOCIAL_MEDIA_PAGES.md` §10:
it is unfinished, not redundant, and the whole `lead_social` composition is now built on it. `open_form`
was REMOVED 2026-09-10 (`LEAD_GEN_PAGES.md` §6). Admission ticket for the domain:
`plans/CREATOR_LINK_POLICY.md`.

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

### LOW — a creator directory: find a tenant by NAME (raised 2026-09-14)

**What:** a platform-level way to look a creator up by name and land on their storefront, the way an
Instagram profile works. Raised while designing the refund button — a customer who cannot find the page they
bought from could search for the creator instead.

**A Site is NOT this** (author, 2026-09-14). A Site is a BUSINESS — one tenant can run many — and a tenant
profile identifies the PERSON, which is exactly the creator case: someone who may run three businesses but
is one identity to their audience. An Instagram profile is person-level; a Site is not. So this is a real
missing layer, not a renaming of one we have.

**It is LOW because the refund button does not need it.** That button lands on every page of a Site
(including its home), and the receipt link works regardless of what happened to any page. What a profile and
a directory add is DISCOVERABILITY — finding a creator by name — which is worth deciding on its own merits.

**Decide it on its own merits, not as a side effect:**
- It is the marketplace direction (plans/DIGITAL_MARKETPLACE.md) and adjacent to the `jbay.page/name` vanity
  idea in plans/CREATOR_LINK_POLICY.md — the same identity, so decide them together.
- It is a small reopening of "do we want a buyer-facing surface?" (plans/PAY_WHAT_YOU_WANT.md §5g settled
  the ACCOUNT half as no). A directory is not an account, but it is a platform-owned page listing other
  people's creators.
- **It is a moderation surface.** A directory is closer to endorsement than hosting is, which is precisely
  the abuse argument that gates `jbay.page`. Whatever allowlist/takedown policy that lands on, this inherits.

### ✅ MEDIUM — migrate `fonts-api` off python3.9 — SHIPPED 2026-09-09 (fonts-api 2898a7a)

- **What:** `fonts-api/template.yaml` declares `Runtime: python3.9`, which AWS has deprecated. It is the only
  stack still on it that we actively develop; `stripe-link` is on `python3.12` (141 deployed functions) and
  `image-processing` on `nodejs20.x`, both current.
- **Target `python3.12`, not the newest.** `python3.13` is the latest Lambda offers (confirmed against the
  runtime enum 2026-09-08), but matching `stripe-link` is worth more than being newest: one Python version
  across the platform removes "which version does this service use" as a question anyone has to ask.
- **Low risk — confirmed.** `fonts-api` is pure Python — no requirements.txt, boto3 comes from the runtime — so
  there was no native wheel to rebuild. It was a one-line template change plus a redeploy, exactly as predicted.
- **DONE 2026-09-09.** `Runtime: python3.12`, deployed and confirmed on the live function. Verified by
  equivalence, not inspection: the live endpoint WAS the 3.9 build, so its output was captured first and
  re-diffed after the deploy. All eight queries byte-identical, including `family=*` (the whole catalogue) and
  three `fs=true` embeds up to 317KB / 10 faces.
- **The one real risk was `fs=true`**, which reads font files from S3 via boto3 — and 3.12 bundles a newer
  boto3 than 3.9 did. It also fails SOFT: `font_bytes()` swallows the exception and falls back to a plain
  `url()`, so a broken S3 read still returns 200 with a plausible stylesheet and merely stops embedding.
  Counting `data:` URIs rather than status codes is what makes that visible. Worth remembering as the same
  shape as every other silent-degradation bug on this list.
- **Raised while asking whether the Node image processor was at risk.** It is not: AWS deprecates runtime
  VERSIONS, not languages, and Python gets the same treatment. Worth recording so the question is not
  re-litigated — and `sharp` is Node-only anyway (libvips binding; Python's equivalent is `pyvips`), so a
  port would swap one platform-specific binary trap for an identical one while putting the working crop
  geometry and rendition ladder back on the table for no functional gain.
- **Also visible in the account, unrelated to this stack:** 29 functions on `nodejs12.x`, 17 on `nodejs8.10`,
  23 on `python3.9`. Most are almost certainly the legacy stacks already being retired — worth a sweep to
  confirm nothing live is hiding among them.

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
- **NEW 2026-09-02 — §4a, the OWNED channel.** Every channel in the plan is RENTED (IG/TikTok/YT decide who
  sees a post); the tenant's published page is the one surface they own, and it carries no attention surface
  today. **Attention Block** is the primitive, **Page Ribbon** its first presentation (image · eyebrow ·
  headline · copy · CTA, mid-scroll).
- Ten of the twelve uses the author listed are STATIC; only the cart-threshold and live-count ones need
  per-visitor state. Published pages are static S3 artifacts rendered once at publish time, so those need
  client-side hydration — a separate phase, not part of the element.
- A-P1 is buildable now and is a normal element build (~26 refs in html.py, ~11 in LandingPages.vue by the
  FAQ yardstick). Capped at two per page: three ribbons become wallpaper, which destroys the only property
  that makes it work.
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
  - **Artwork already exists (found 2026-09-07).** `s3://www.juniorbay.net/images/frontpage/sabbath/` holds
    **16 curated Sabbath photos** (`1.jpg`…`16.jpg`), from a 2020 attempt at this same idea — the old
    homepage was to show them during Sabbath hours, and it died when the external sunset API it depended on
    went away. The Lambda and its stack are deleted; the images are deliberately kept. The closure page
    needs exactly one, so pick from there rather than sourcing new art.
  - **Do not reach for an external sunset service.** That dependency is precisely what killed the 2020
    version. Sundown is pure math from lat/long and date, which is why this plan already specifies a local
    solar algorithm (`astral`) — no availability risk, and the polar no-sundown case surfaces as an
    exception rather than a failed HTTP call.
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

### ✅ Additional content elements for the landing page builder — COMPLETE, shipped prod 2026-09-06

Step 0 (the section-scoped theme override) plus all seven elements are built, deployed and verified
in prod. Sequence and per-element notes in **`plans/LANDING_ELEMENTS_UNIT.md`**; the Page Ribbon's
five CTA actions in **`plans/RIBBON_ACTIONS.md`**.

- **Built as a unit (2026-09-02 → 2026-09-06):**
  1. **Page Ribbon** — new element. Attention Block's first presentation; see ATTENTION_PRIMITIVE.md §4a.
     Image · eyebrow · headline · copy · CTA, capped at two per page, three presentations. A-P1 there is the
     static version; the context-aware layer is A-P3 and needs client-side hydration, because published
     pages are static S3 artifacts.
  2. **Price Highlight** — new element (legacy "Price & Urgency"); see plans/PRICE_HIGHLIGHT.md. Standalone
     bargain block: regular price struck through + sale price + two authored lines, no CTA. Numbers DERIVED
     from the offer, tokens reused from `offer_price_selector` so every preset styles it already. Open
     Tiered offers show the LOWEST price behind a locked "as low as" prefix — which makes it a claim about
     the range rather than about the visitor's selection, so it cannot contradict the price selector and
     needs no script. The strikethrough must pair with that same tier's compare-at, never a higher one.
  3. **Author Bio** — new element; see plans/AUTHOR_BIO.md. Fixed structure (photo → name → credibility
     headline → paragraph) and an OPTIONAL pattern break that overrides the page preset for that section.
     Build the override as a general section-scoped `theme` map, not two fields on this element, or the next
     pattern-breaking element duplicates it. The foreground must be DERIVED from the chosen background by
     luminance — the legacy offers background and border pickers but no text colour, so a wrong pick makes
     the paragraph invisible with no warning.
  4. **Bragging Points** — new element; see plans/AUTHOR_BIO.md §4a. Repeatable `{value, label}` cards that
     reflow (1 wide / 2 columns / 2+1). STANDALONE (decided 2026-09-02) — it is the "stats band" already
     wanted ("10,000 customers served") and the author's brag, with one implementation. It is also the SECOND consumer of the section-scoped theme override, which
     confirms building that mechanism generally rather than as per-element colour fields.
  5. **Quote** — new element; pull-quote with a vertical accent bar, plus the OPTIONAL attribution the
     legacy lacks. Not `testimonials`: that carries an endorsement, this carries an idea.
  6. **Numbered List** (legacy "Benefit List") — heading + ordered authored lines on numbered cards, cap 12.
     ONE element for benefits AND "how it works" steps — same component, the title is the only difference —
     so it is named for the shape, not one use. Heading markup (`**coloured**`, `^^highlighted^^`) already
     exists in `render_headline_markup`.
  7. **Brand Marquee** — ENHANCEMENT of the existing `client_marquee`; see plans/BRAND_MARQUEE.md.
- **Sequenced in plans/LANDING_ELEMENTS_UNIT.md, with a STEP 0:** four of the six break the page preset, so
  the section-scoped theme override is built first, once. Quote proves it must be a TOKEN MAP rather than a
  background field — it needs an accent (the bar) as well as a background.
     Text-or-logo entries (text is silently dropped today — a bug), three-state scroll control, and the
     countdown's 🐢/🐇 speed slider reused rather than re-derived.
- **Absorbed by design, not skipped:** *how-it-works steps* became Numbered List (one element; the
  heading is the only difference between the two uses) and *stats band* became Bragging Points, which was
  made standalone precisely so it could serve both it and the author's brag.
- **Deferred by decision, tracked in their own plans:** the ribbon's part-2 event capture + analytics
  screen (`RIBBON_ACTIONS.md` §0 — a click record with nothing to consume it is write-only), true call
  tracking (§5b, v2, low priority), and the ribbon's A-P2 attribution / A-P3 hydration layers
  (`ATTENTION_PRIMITIVE.md`).

### MEDIUM — image cropper: crop/zoom/reposition behind every image button (plan 2026-09-06)

A shared `ImageCropper.vue` used by every image uploader in the dashboard, so a tenant controls what part
of a photo survives instead of accepting whatever `object-fit` picks. Full design in
**`plans/IMAGE_CROPPER.md`**.

**It is one stack extended, not a new service.** `OnDemandResizeFunction` in `image-processing-stack`
already has sharp, source-bucket read, target-bucket write, the metadata table and immutable cache headers.
Cropping is `sharp.extract()` plus query params — roughly 40–60 lines. The bulk of the work is the Vue
component, so this is mostly a front-end project.

Key decisions already made: the **consuming element declares the aspect ratio** and the cropper enforces it
(which is what makes one component serve avatars, heroes and a Before/After pair alike); the crop rect is
stored as **normalized fractions**, not pixels, so it survives every rendition the processor makes; and it
is applied via `object-position` first, with derivative baking as a later delivery optimisation.

Three traps recorded in the plan, all of which survive naive testing:

- **The `/resize` cache key omits the transform** (`custom_{w}x{h}.{fmt}`), so two crops at the same output
  size overwrite each other — behind `max-age=31536000, immutable`. Must be fixed BEFORE any crop param.
- **`.extract()` must come after `.rotate()`**, or portrait phone photos crop the wrong region while every
  landscape desktop test image passes.
- **`ALLOWED_ORIGINS` on that function excludes `app.juniorbay.com` and `sandbox.juniorbay.com`**, so a
  direct browser call is blocked by CORS. Proxy through `upload.py` if baking is ever wanted.

Also fixes a live latent bug: builder file-input refs are keyed by `element.id` alone, so any element with
two images collides (second ref wins, shared spinner, shared error). Nothing hits it today because no
element has two images — Before/After would be the first. Fixed structurally by the shared component
owning its own input.

### ✅ Three remaining landing elements — ALL RESOLVED 2026-09-07

Named in the original discussion. Two shipped, one dropped on the author's call — recorded so the
dropped one reads as a decision rather than an omission:

- ~~**Comparison table**~~ — **DROPPED 2026-09-07 (author).** Narrowest use, hardest mobile problem
  (a three-column table has to become card-per-column below ~600px), and the only element carrying
  third-party legal exposure, since it makes claims about competitors rather than about the tenant. If a
  need resurfaces, the safe shape is a single-column "What's included" checklist with no competitor column
  at all.
- ~~**Standalone video**~~ — **SHIPPED 2026-09-07.** Takes an uploaded file OR a YouTube/Vimeo link,
  inheriting the click-to-load facade, poster handling and provider parsing from `render_media_slide`
  rather than restating any of it. Deliberately never autoplays: the hero can, because the visitor has
  just arrived and the media is the first impression, but a video that starts itself halfway down a page
  is noise, and content playing past five seconds with no stop fails WCAG 2.2.2.
- ~~**Before / after**~~ — **SHIPPED 2026-09-07.** The divider is a real `<input type="range">`, so
  keyboard, touch, click-to-jump and assistive technology come from the browser and the script is one
  assignment; without JS it rests at the authored position, which is a legible side-by-side rather than a
  broken control. Both layers are the SAME box with the top one **clipped**, not resized — sizing it to
  the divider would make its image narrower than the one beneath and the seam would visibly jump. The
  element owns ONE shape that both photos crop to, which is what removed the alignment problem entirely.

Social and lead-specific elements still wait for those page types to exist.

### Shared indexed-list machinery — ALL FOUR SCREENS MIGRATED, SHIPPED 2026-09-02
- SHIPPED: `composables/indexedList.js` (loadIndex / fetchFullDocument / searchText / matchesSearch /
  filterRows / shownMessage) + `domain/service_index.py` + `?view=index` on the shared `document_route`,
  so registering an entity in `_INDEX_PROJECTIONS` gives it an index. **Services is the pilot consumer.**
- SHIPPED: **Products** migrated 2026-09-02 — `filteredProducts` is now `filterRows(...)` with
  `PRODUCT_SEARCH_FIELDS`, its type filter passed as the new `where` predicate, and `load`/`fetchFull`
  going through `loadIndex`/`fetchFullDocument`.
- SHIPPED: **Offers and Landing Pages** migrated 2026-09-02. All four screens now filter through
  `filterRows`. The item join became `extraText`, the Site filter became `where`, and `route.slug` and the
  template label became function fields — configuration, not code, exactly as the shapes were designed for.
- **Landing Pages has no page index yet** and still loads full page documents (they carry sections):
  measured at ~2.9KB avg, so 1,000 pages is 2.74MB, 46% of the ceiling. Less urgent than products or
  offers were — tenants have fewer pages than products — but it is the last unindexed list. Registering
  one is now a small job: a `domain/page_index.py` plus an entry in the projections map.
- **Known gap:** store modules cannot be loaded under raw node (their import graph is extensionless, the
  Vite convention), so the shared machinery is tested directly and the per-entity FIELD LISTS are not
  covered by a test that reads them. Closing that means an extension pass across the store graph — worth
  doing if these migrations keep going, not worth a detour now.
- Why it matters more than the current field lists: virtualized rendering and any future server-side search
  land ONCE in the composable instead of four times. The field lists differ legitimately and stay per-entity.

### List virtualization — BLOCKED on a UX decision, not effort (plans/LIST_VIRTUALIZATION.md)
- Prerequisites are done: one shared filter path, uniform row heights, payload already solved by the
  indexes. This is purely render cost.
- **Blocker:** no list has its own scroll container — `.product-card-list` is a plain grid and the PAGE
  scrolls. So it is either window-scroll virtualization (no UX change, more code, nastier failure modes)
  or giving the list `overflow-y: auto` (simple code, introduces a nested scrollbar — a real UX change).
- Recommendation: window-scroll, triggered when a real list passes ~1,000 rows. ~156px per row, so 1,000
  rows is ~156,000px of DOM and ~4,000 elements. No hard failure, just degradation — unlike the payload
  cliff.
- Deliberately NOT built blind: scroll math looks right in code and is wrong in the browser, and there is
  no list of that size to test against yet.

### Clamp overflow in ListCard — SHIPPED 2026-09-02
- `shared/ListCard.vue` IS already shared by Offers, Products and Services (the card chrome is done). What
  is missing is overflow protection: `min-width: 0` prevents a grid blowout but there is no line clamp and
  no ellipsis, so a 500-word product description just makes a very tall card.
- The Offers card only looks robust because the limiting lives in its CONTENT (`itemSummary`: 3 names,
  `+N more`, 90-char cap, full text in the title). Products and Services pass raw text and get nothing.
- SHIPPED: `-webkit-line-clamp: 2` on the description, single-line ellipsis on the title, `min-width: 0`
  so a long title truncates instead of pushing the status badge out, `overflow-wrap: anywhere` so an
  unbreakable string (a pasted URL, an id) cannot widen the card, and the full text on each element's
  `title` attribute — clamping may hide characters, it must not hide information.
- Content composition left alone: "3 names then +N more" is offer semantics and belongs with the offer.
- Landing Pages deliberately excluded: its cards carry a URL row, copy button, stats, preset and kebab menu.
- **This unblocks virtualization.** Rows are now uniform height per list, so the remaining work is
  fixed-height windowing (~50 lines) rather than measuring virtualization with an offset map.
- Guarded by tests/test_list_card_clamp.py, which reads the stylesheet directly — CSS is not covered by the
  renderer tests, and a clamp is easy to delete during an unrelated edit. Verified it fails without it.

### Slim indexes — BOTH SHIPPED 2026-09-02 (plans/OFFER_ITEM_VISIBILITY.md §7)
- SHIPPED: `GET /offers?view=index` (10% of a document) and `GET /products?view=index` (34% — prices are
  irreducible, the Offers screen derives funnel roles from them). Both consumed by the dashboard; View and
  Edit fetch the single full document they need. 2,000 products: 4.74MB -> 1.61MB.
- REMAINING: virtualized list RENDERING (window the DOM). A render-cost problem, not payload. NOT infinite
  scroll — the indexes load whole, which is what keeps client-side search complete.
- **The product payload is the bigger half and arrives first.** Product documents average ~3.1KB (larger
  than offers) and tenants usually have more of them; the Offers screen loads the whole catalog on mount
  for item names, funnel-role derivation and the image fallback. 2,000 products = 5.9MB = 99% of the limit.
  A product index is the same shape of work as the offer one.
- Then virtualize the list RENDERING — window the DOM. Not infinite scroll: the index loads whole, which is
  what keeps client-side search complete. Paginating it would leave search covering only what was fetched.
- Ordering gap, relevant to mobile infinite scroll: the sort key is `OFFER#{mode}#{offer_id}`, so pages
  come back in id order and there is no chronological index. While the index loads whole you can sort
  client-side on its `created_at`; past that you need a GSI. The GSI solves ORDER, never the cliff.
- Watch `JuniorBay/Api` -> `ResponseBytes` (docs/RESPONSE_SIZE_MONITORING.md). Alarm at 3MB, half the
  ceiling, so there is room to act. Trigger on BYTES, not record counts.

### Cached suggestion field — SHIPPED 2026-09-02 (plans/CACHED_SUGGESTION_FIELD.md §7)
- The product category autocomplete calls the API on every focus AND every 180ms typing pause, each one a
  Lambda invoke plus a full DynamoDB scan. No cache in the util, the component, or apiRequest.
- `plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md` line 90 already asked for fetch-once-and-filter-locally. It said
  "may", nothing enforced it, and it fell out — the SECOND dropped requirement found on 2026-09-01, after
  service-only offer naming. Neither had a test.
- Extract as a composable FROM the category field, which is the only server-backed typeahead in the
  dashboard today. Thin, not a generic search engine; let a second consumer reshape it.

### Offer items invisible on cards and in search — phases 1-3 SHIPPED 2026-09-01; phase 0 OPEN (plans/OFFER_ITEM_VISIBILITY.md)
- A product added as an order bump appears NOWHERE on the Offers screen: not on the card (which reads the
  landing-only `items[]`) and not in search (which matches only name/slug/type/intent). The only way to
  find it is to open every offer and read its Purchase Flow. Landing items like "Whey Protein" are equally
  unsearchable, so this is not just a funnel problem.
- Same hole one screen over: Landing Pages searches `offer_id` but not the offer's NAME or any item name.
  The general pattern is that a list screen searches its OWN document's fields and never the entities it
  references. Fixing only the offer card would leave the sibling gap in place.
- SHIPPED: card role counts, offer search through item names/ids across every stage, and Landing Pages
  searching through to its offer. Shared composable + node-run regression tests.
- Phase 0 CONTRACT SHIPPED 2026-09-02: `GET /offers?limit=&cursor=`, opaque cursor, 500 cap, byte-identical
  when unused; `list_page_for_tenant` added alongside the untouched `list_for_tenant`. Client adoption and
  the card projection are deferred on purpose — see plans/OFFER_ITEM_VISIBILITY.md §7, which records why
  paginating without moving search first would break search.
- ORIGINAL NOTE — **phase 0, list projection + pagination.** `list_for_tenant` fetches all pages uncapped and
  returns full documents (~2.9KB each): 500 offers = 1.4MB, 2000 = 5.8MB, which BREACHES the 6MB Lambda
  proxy limit and the screen stops loading entirely. A cliff, not a slope. Do the API shape + pagination
  pre-launch, while nothing else consumes these endpoints; keep filtering client-side over the projection.
  Trigger for moving filtering server-side: any tenant past ~500 offers, or p95 list payload over 1MB.


### Flesh out the search_seo / discoverability pack in depth — MEDIUM
- FAQ + `structured_data` already ship (they are the `discoverability` pack today). What is NOT decided is
  the rest of the modern discoverability surface: llms.txt, breadcrumb/Organization schema, IndexNow,
  sitemap/robots. Several are already blocked on the Site object in the On-page SEO Phase 2 item — this is
  the goal-axis half of that work, and the two should be planned together rather than twice.
- Placeholder seeding + the FTC-accurate warning copy: see plans/GOAL_SEEDING_AND_PACKS.md.



### Contrasting theme accents — the lever is the PRESET, not the element — LOW, worth considering later
- **Where this came from:** the FAQ chevron uses `--sl-accent`; the refund policy's `+` falls back to `brand`.
  On `tiktok-dark` that produced a striking two-tone (cyan chevron against a magenta `+`/CTA) the author liked
  a lot. It was NOT designed — it is an accident of two different token defaults meeting.
- **The finding:** measured across all 16 presets, `accent` is the same hue as `brand` (median gap **2 degrees**),
  just a few points lighter. `tiktok-dark` is the ONLY preset where they differ in hue (**163 degrees**, near
  complementary) — faithful, because that IS TikTok's brand identity.
- **So:** *if you want that contrast on other themes, the lever is the preset's accent value, not the chevron.*
  Give `coral-sunrise` a teal accent instead of a paler orange and you get the same effect there. Cheap to try,
  one value per preset in `UNIVERSAL_BUNDLE_THEME_PRESETS`, entirely separate from any element's CSS.
- **Still open (deliberately deferred):** the `+` and the chevron use different tokens for the same interaction.
  Unifying both on one token (recommended: `accent`, the decorative token already used for the testimonial quote
  mark, avatar ring and notice icon) would make the affordance consistent and keep TikTok's cyan. Not done —
  the author paused the design thread.


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

### Media field parity — SHIPPED (verified 2026-09-02)
- `MediaListField` has Upload Image / Upload Video / Video URL and drag-reorder; `uploadVideo()` posts to the
  image-processing service (`../sam/image-processing`, see docs/EXTERNAL_SERVICES.md), which gained video
  support and raised caps. Confirmed working on a live hero carousel (image + video, reordered).
- The notes below are the original stripe-cart reference, kept for the transcode/poster ideas that were NOT
  ported (no MediaConvert step; the service returns the uploaded asset directly).

### Original plan notes (reference only)
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

**Note 2026-09-09: that specific gate has CLEARED.** Media field parity shipped and was verified
2026-09-02. The sequencing intent (finish the remaining modules first) still stands, but the one
blocker this entry named by name is done — so re-read the intent rather than treating this as
still-blocked.

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
