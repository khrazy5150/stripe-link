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

## Dashboard / UX

### Build the beginner-friendly custom-domain wizard
- **What:** Replace the current bare custom-domain form with the guided, auto-polling wizard designed
  in **`docs/CUSTOM_DOMAIN_WIZARD.md`** (single flow for beginners + power users; reveals DNS records
  progressively; explains propagation; auto-checks status so users rarely click "Check Status").
- **Current behavior:** the backend is in place (`src/handlers/custom_domains.py` +
  `custom_domains_resolve.py`, Cloudflare Worker + resolve API); the dashboard only exposes the simple
  TenantConfig-based form inside `dashboard-vue/src/components/Configuration.vue`.
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

### ⭐ HIGH PRIORITY — Sales funnels in the Sites paradigm (plan being scoped)
- **What:** close the loop for transaction (Stripe) landing pages with a coherent sales-funnel model under
  the **Sites** paradigm — order bumps, sale + flash-sale pricing, one-click **upsells/downsells**, and the
  **thank-you** page — driven by product/offer pricing **contexts**, with **reserved slugs**
  (`upsell`, `downsell`, `thank-you`, `sale`, `flash-sale`) that tenants may never use for their own pages.
- **Already exists (verified 2026-07-24):** offer/price `context` enum (standard/sale/flash_sale/upsell/
  downsell/order_bump); order-bump folding into the initial Stripe checkout (`resolve_order_bumps`);
  one-click post-purchase upsell charging via saved payment method (`handlers/upsell.py`); Site-aware
  post-checkout routing (`handlers/post_checkout.py` + page `post_checkout.funnel_steps`/`thank_you_page`);
  `SITE_PAGE_TYPES` already includes `thank_you` + `funnel_step`.
- **Missing / to design:** reserved-slug reservation + the reserved-slug URL convention (`/upsell` etc.);
  flash-sale runtime (countdown + flash pricing); `/sale` + `/flash-sale` page semantics; and a consolidated
  design reconciling per-offer/product contexts with per-Site reserved slugs. Listicle offers deliberately
  IGNORE upsell funnels (AI_AND_COMMERCE Part C — "focused funnel" vs "shop mode").
- **Design LOCKED (author-clarified 2026-07-24) → `plans/SALES_FUNNELS.md` (unified plan).** A Site = one
  funnel for one offer. Reserved slugs: `/` (Standard) · `/sale` + `/flash-sale` (context views of `/` — same
  page, swapped price + Sale/🔥 badge + countdown from page-level dates, fall back to Standard) · single
  `/upsell` + `/downsell` (post-purchase one-click, cycling the offer's `funnel` upsell/downsell product+price
  refs; downsell only for declined upsells) · `/thank-you`. Upsells/downsells live in an **in-offer
  `offer.funnel` block** (separate from `items[]` → keeps offer_type clean; one offer per funnel). Pricing
  context IS the wiring. **Unifies the pre-Sites `Funnel` engine** (schemas/Funnel.schema.json +
  domain/funnels.py): reuse its routing/charge plumbing; the generic per-page step-graph (numbered slugs)
  becomes the future ADVANCED tier. Phasing: **P1 pre-purchase** (reserved slugs + sale/flash views, no
  payment change) → **P2 post-purchase default funnel** → **P3 advanced tier + polish**.

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
    (no ledger view exists in `dashboard-vue`).
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

## Production setup

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

### Default "no image" placeholder so image-less products stay swipeable in the carousel
- **What:** the landing multi-product carousel syncs each product's tier block to the **hero image carousel** —
  the buyer swipes the hero image to change the active product. A product with **no image** produces no hero
  slide, so it can't be swiped to and its tier block never activates (the buyer can't reach it or add it). Give
  every product a **default "no image" placeholder** so slide count == product count and swipe→tier sync always
  holds.
- **Where to fix:** hero slides come from `listicle_slides()` (`src/stripe_link/runtime/html.py`), rendered by
  `render_hero_media`; the tier blocks are `render_listicle_carousel` (toggled on `conversion:itemChanged`).
  Emit a fallback placeholder image when a product has none (a served default asset or an inline SVG data-URI),
  and reuse it anywhere a product image is expected (tier cards, mini-cart rows). Keep the placeholder out of
  Product JSON-LD / SEO image signals (it's a UI fallback, not a real product image).
- **Alternative/complement:** add arrow/dot navigation on the carousel that drives the tier sync directly, so
  swipeability doesn't depend on images at all. See `plans/LANDING_CAROUSEL_FIXES.md`.
- **Why deferred:** works today for products *with* images (the common case); flagged during landing-carousel
  live testing 2026-07-28.

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

## Offer Semantic Model

### Look more closely at JSON-Schema ↔ model drift
- **What:** `schemas/OfferSemanticModel.schema.json` (P4.0) is a full JSON Schema, but the runtime contract is
  the hand-written `validate_semantic_model` (`src/stripe_link/domain/documents.py`), and the test that ties the
  two together (`tests/test_semantic.py :: SchemaConformanceTests`) is a **dependency-free structural walk**, not
  a real JSON-Schema validation — the repo keeps third-party deps out (`src/requirements.txt` intentionally
  empty), so there is no `jsonschema` at runtime or in tests. The structural walk only checks, at each documented
  object level, that `required` keys are present, that `additionalProperties:false` levels carry no undocumented
  keys, and the two enums (`entity.type`, `interpretation.source`). It does **not** check leaf types, numeric
  bounds, array-item shapes, `oneOf`, etc. So the schema file and the code can still drift on anything the walk
  doesn't cover.
- **Why it matters:** in **P4.1** the same JSON Schema becomes the **AI provider's structured-output contract**
  (OpenAI `response_format: json_schema`, Anthropic tool schema, Gemini `responseSchema`). If the schema has
  drifted from what `validate_semantic_model` (and the deterministic analyzer) actually produce/accept, the AI
  tier will emit objects that pass the provider but fail our validator, or vice-versa.
- **Where to look:** decide how to enforce agreement without adding a dep — options: (a) a small in-repo,
  dependency-free JSON-Schema-subset validator shared by the test and `validate_semantic_model` (single source of
  truth); (b) generate one artifact from the other; (c) accept a bundled `jsonschema` in **tests only** if the
  no-deps rule is relaxed for the test path. Revisit before building P4.1.
- **Why deferred:** P4.0's structural check is enough to catch the realistic drift (a field added/renamed) today;
  the tighter enforcement only becomes load-bearing when the AI tier consumes the schema. Flagged 2026-07-28.

### Semantic-model caching — defer until the model is finalized
- **What:** `resolve_semantic_model` (`src/stripe_link/domain/semantic.py`) already **reads** an
  `offer.semantic_model` cache (returning it only when `source=="ai"` and `version==MODEL_VERSION`, else
  recomputing deterministically), and the render consumers route through it — but **nothing writes the cache
  yet**. The write path, `generated_at` stamping, and invalidation-on-offer/product/brand-change were
  deliberately left for later.
- **Why deferred:** the deterministic model is cheap to recompute, so the cache only earns its keep once the
  **expensive AI enrichment** (P4.1) exists — and the caching/invalidation design shouldn't be finalized until
  the model shape and the enrichment flow are settled. Per decision 2026-07-28: **worry about cache when
  everything else is finalized.** The read seam is in place so adding the write later is a localized change.
