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

### Sales funnels in the Sites paradigm — P1 + order bumps + P2b SHIPPED (2026-07-29)
- **Now shipped (dev):** on top of the P1 pre-purchase work (below), the post-purchase funnel is Sites-native.
  A 3-agent code audit (2026-07-29) found the plan doc badly stale — far more was already built than it said:
  P1a–d **including P1b-2 flash client-side time-states**, and **order bumps via Stripe `optional_items`**
  end-to-end (model → validation → both checkout handlers → sync-skip guard → builder inference; the old
  `merge_resolved_offers`/`resolve_order_bumps` stopgap is retired — `merge_resolved_offers` is now dead code,
  a cleanup candidate). The post-purchase funnel ENGINE + synthesis was also done but served ONLY on the
  platform host via internal `{page_id}__upsell_N` artifact ids (custom-domain buyers bounced off their domain).
- **P2b — reserved-slug custom-domain funnel (this session):** `route_table` now carries resolver-visible
  entry fields (fixes a real bug: `price_context` was dropped, so `/sale`//`/flash-sale` broke on custom
  domains via the index); `attach_funnel_slugs` (publishing.py) attaches `/upsell` (+ `/downsell` in carousel
  mode) + `/thank-you` to the Site root with `funnel_role`+`strategy`; the resolver derives the synthetic
  artifact from role+strategy+`funnel_step`; the post_checkout router emits custom-domain reserved-slug URLs;
  the checkout entry gate is offer-aware (`_offer_has_upsell_funnel`). +10 tests.
- **Re-publish on domain verification — SHIPPED dev (2026-07-30):** the Site `check_domain` (handlers/sites.py),
  on the FIRST verified transition, re-puts every page attached to the Site → fires the publish stream → each
  page re-publishes with the verified domain in effect, so the funnel + `/sale` slugs and canonical/robots
  attach even for pages published BEFORE verification. Best-effort; no-op on re-checks of an already-verified
  domain. SitesFunction gained PagesTable write. (Note: the legacy TenantConfig `custom_domains.py:179` minimal
  index write is a separate, pre-Sites path; the Site flow syncs the full `domain_index_record`.)
- **Still to do (funnel):**
  - **Editable funnel Page docs (stripe-cart parity, plan §Auto-provisioning / P2).** Today the funnel steps are
    ephemeral synthesized S3 artifacts, not tenant-customizable Page docs. Converges with the Upsell Phase 2
    "scoped landing builder" idea. Deliberately deferred (user chose reserved-slug routing over editable pages).
  - **P3 advanced tier** — the detached `Funnel` doc (`schemas/Funnel.schema.json`, `funnel_id`) for bespoke
    multi-page/branching funnels; its resolver is stubbed (`funnels.py` raises "not yet supported").
  - **Server-side flash-window guard** — a crafted request can still post an expired flash `price_id` (P1 client
    guard only; plan flags this acceptable for P1).
- Original plan (now partly historical): `plans/SALES_FUNNELS.md`.

### ⭐ (historical) Sales funnels — original scoping note
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
