# Reviews — first-party review aggregator (organic star snippets + trust)

Status: **PROPOSED — awaiting sign-off.** Not built.

## Goal

Collect, moderate, and render **first-party** reviews so our backend-rendered pages earn organic
**star snippets** (Product `AggregateRating`/`Review` rich results) and stronger on-page trust — without a
third-party widget. Reviews also become the data backbone for the future **AI-managed GBP** product and feed
the existing `social_proof` pack.

## Why build it (Scenario A), not a third-party widget (Scenario B)

Our stack is an unusually good fit, and a widget would be a regression:

- **No data drift.** We render JSON-LD server-side from the document, in the same pass as the visible HTML.
  There is no client-side widget mutating the DOM while a static schema lags — the exact failure Google flags.
- **All content in the initial HTML.** `reviewBody` + `author` are emitted server-side; Googlebot sees them
  without executing JS. Third-party widgets often inject reviews client-side (snippet risk + LCP cost on pages
  we deliberately keep clean).
- **No cherry-picking, by construction.** The aggregate is computed from **all approved reviews**, low ones
  included. (We already have this discipline: `runtime/html.py` **refuses to emit `AggregateRating` from a
  hand-typed number** — a real review store is what unlocks it honestly.)
- **Only first-party reviews are markup-eligible.** Google requires ratings *sourced directly from your users*
  — you **cannot** aggregate third-party/Google reviews into your own `AggregateRating` markup. So our own
  collected reviews are the *only* legal path to star snippets; GBP/Google reviews are **display-only**.

## The policy reality that shapes the design

**1. Two different Google surfaces — don't conflate them.**

| Surface | Requires | For us |
|---|---|---|
| **Organic rich results** (stars in normal search) | `AggregateRating` + `Review` JSON-LD from your own reviews. No minimum, no paywall. | The prize — free/now, just render it. |
| **Google Shopping / Merchant Center** product stars | 50+ reviews **and** a Merchant Center *product review feed* (XML) | Separate, gated; only relevant once we run Merchant Center feeds (not yet). Later add-on on the same store. |

**2. The "self-serving" rule — products vs services differ.** Since 2019 Google suppresses organic star
snippets for **self-serving reviews on `LocalBusiness`/`Organization`** (a review *about your business* on
*your own* site). `Product` is **not** restricted (self-hosted product review stars still show). `Service`
isn't a review-snippet-eligible type at all. Consequence:

| Review target | On-page organic stars? | Value |
|---|---|---|
| **Product / Offer** (incl. a bookable service sold as an offer) | ✅ `Product` + `AggregateRating` | Highest-CTR; the real snippet win |
| **Business** (`Site.organization` / `LocalBusiness`) | ❌ suppressed (self-serving) | On-page trust; feeds GBP; **display-only** for markup |

So a dentist/plumber/lawyer's **firm** gets its stars from **Google Business Profile / Maps** (the GBP sync,
Phase 2), *not* from self-markup — but a **discrete bookable service sold as an Offer** ("$99 cleaning") is
`Product`/`Offer`-eligible and **does** earn organic stars. Our review store powers both, plus on-page trust.

## Canonical design: a target-agnostic Review entity

A review references a **target**, and the target decides the payoff. One store, three consumers (Product
markup, business trust/GBP, social_proof pack).

- **Entity** — table-per-entity `jb-reviews-{env}`, keyed `(tenant_id, review_id)`, GSI by target for fast
  per-target queries. Fields (starter):
  - `target`: `{ type: "offer" | "product" | "business", id: <offer_id|product_id|site_id> }`
  - `rating` (1–5 int), `author` (display name), `body`, `title?`, `review_date`
  - `status`: `pending | approved | rejected` (nothing renders until `approved`)
  - `source`: `manual` (tenant enters real existing reviews) | `first_party` (submitted on our page) |
    `gbp` (imported, **display-only**, never in markup)
  - `verified_purchase?`, `response?` (tenant reply), abuse metadata (ip hash / idempotency key)
- **Aggregate** — computed from **approved, markup-eligible** reviews per target (avg + count). Recomputed on
  write; may be denormalized onto the target's render context for cheap rendering. `gbp`-sourced reviews are
  **excluded** from the marked-up aggregate (display-only).

## Sourcing

- **Manual / import (Phase 1).** Tenant enters *real* existing reviews (legit — they're genuine). Bulk import
  later.
- **Public submission (Phase 2).** `POST /reviews` reusing the **Leads** abuse-gate + idempotency pattern
  (`LeadsTable`, public POST with rate/abuse gate — nearly a copy). Lands as `pending` for moderation.
- **GBP import (ties to GBP Phase 2).** Pulled via the GBP sync; **display-only**, never in `AggregateRating`
  markup (self-serving + third-party-source policy).

## Moderation

A dashboard screen to approve/reject (spam/abuse control; required before anything renders). Bulk actions,
filter by target/status. Rejected reviews never render and never count toward the aggregate.

## Rendering (the strict-compliance part)

- **Product/Offer target** → emit `Product` `review` array (each `Review`: `author`, `reviewRating`,
  `reviewBody`, `datePublished`) + `aggregateRating` (`ratingValue`, `reviewCount`), extending the existing
  Product JSON-LD in `runtime/html.py`. Render the **visible** reviews in initial HTML — same data, same pass
  (exact match, no drift).
- **Business target** → render visible reviews + on-page rating for trust, but **do not** emit self-serving
  `LocalBusiness`/`Organization` `AggregateRating` (it's ignored at best, flagged at worst). Keep the
  anti-fabrication discipline that already exists.
- **No cherry-picking** — the aggregate and the visible list include all approved reviews across the rating
  range. Never filter out low ratings from the source.
- **social_proof pack** — approved reviews feed the existing testimonials/ratings slots (a new source into
  existing surfaces, no new page vocabulary).

## Phasing

- **Phase 1 SHIPPED (2026-07-23): store + manual entry + moderation + Product markup + visible render.**
  Target-agnostic entity; tenant enters real reviews; moderation dashboard; `AggregateRating`/`Review` on
  Product pages (organic stars); visible reviews on-page; all-ratings, exact-match. Lit up the
  `AggregateRating` hook the renderer intentionally left dark. (Slices: entity+API, render, dashboard.)
- **Phase 2: post-purchase verified-review invitation + public submission** — the two are one flow (below).
  Also: business-target reviews for on-page trust + `social_proof` wiring.
- **Phase 2.5 (builder integration):** a **"Reviews" builder element** that *controls* the auto-rendered
  reviews block (heading / placement / show-hide) instead of it silently auto-appending. And **re-label the
  existing hand-typed "Rating" element** — it is NOT the reviews system; it's an *external/cited* rating
  ("4.9 ★ on Google"), visible-text-only, no markup (the fabrication guard). Rename to e.g. "Star-rating
  badge", and later **auto-populate it from the GBP sync** so it's derived, not hand-typed. Do NOT rename
  "Rating" → "Reviews" (they're different things; two conflicting star displays would result).
- **Phase 3 (optional, later): Merchant Center product-review XML feed** for Google Shopping stars — only when
  we run Merchant Center feeds and have 50+ reviews.
- **GBP reviews** land with the **Business Profile GBP sync (that plan's Phase 2)** — display-only, never in
  our markup.

## Post-purchase review invitation (Phase 2 centerpiece)

Ask real buyers to review, a day or two after they receive the product/service. This is the best review
source: it's the strongest anti-spam gate (only actual purchasers get the link) AND makes each review a
**verified purchase** (highest trust + markup value), and it makes the whole system self-sustaining.

- **Flow:** on a completed purchase we schedule a review-invite email carrying a **tokenized, one-time,
  order-bound public link** → opens the public review form (the Phase-2 `POST /reviews` submission, which the
  token authorizes — no separate abuse gate needed for invited reviews). The submitted review is stamped
  `source: first_party`, `verified_purchase: true`, and the resolved `target` (product/offer).
- **Timing (key off fulfillment, not just purchase):**
  - Products: shipping **delivered** signal + N days; fallback to a fixed delay after purchase when there's no
    delivery tracking.
  - Services: N days after the **appointment/service date**.
- **Reuse:** the appointment-**reminders engine** is the same shape (a scheduled one-shot send — EventBridge
  Scheduler or the sweep) pointed at a purchase/delivery/service trigger; plus the existing email/notification
  infra. Honor unsubscribe/opt-out.
- **Anti-abuse:** the token is single-use and bound to (order, product); an invited submission skips the
  public abuse gate but still lands `pending` unless we auto-approve verified-purchase reviews (a moderation
  policy choice). One invite per purchased line.
- **Payoff loop:** real buyers → verified reviews → real AggregateRating → star snippets → conversions.

### Route invited buyers to Google reviews too (compliant "push", future phase)

**You cannot programmatically post a review to Google** — the Business Profile API has **no create-review
endpoint** (deliberate anti-fraud; a review must be left by the real user in their Google account). So there
is no "push our review to Google." The achievable, high-value version:

- **Route, don't push.** Google's native write-review deep link is
  `https://search.google.com/local/writereview?placeid={PLACE_ID}`, built from `Site.organization.place_id`
  (already stored in Business Profile Phase 1). The customer leaves the review on Google themselves.
- **ONE destination per invite, tenant-chosen (do NOT ask twice).** The invite routes to a *single*
  destination — **Junior Bay** (first-party form → our Product AggregateRating snippets) OR **Google** (the
  writereview link → the business's Google/Maps presence) — never both. The destination is a **per-Site
  preference** (multi-Site: a product store and a service business get their own), whose **default derives from
  `Site.organization.entity_type`**: product/`OnlineStore` → Junior Bay; `LocalBusiness`/service subtypes →
  Google. Tenant can override. This maps to the SEO reality: products win with on-site markup, services win on
  Google/Maps (their on-site business reviews earn no stars — self-serving rule).
  - **Compliant, not gating:** the destination is a *uniform tenant policy*, applied to every invited buyer the
    same way. Gating = branching on the individual customer's likely sentiment; this never does.
  - **Guard:** destination = Google requires a valid `place_id`; if missing, fall back to Junior Bay rather
    than send a dead link.
- **Read back via the API** (once enabled): the Business Profile API can **read** the Google reviews into our
  store (display-only — GBP reviews never feed OUR markup) and **reply** to them (AI-managed GBP, Phase 3).
  This is the "integration" — routing out + reading back, not writing.
- **COMPLIANCE — no review gating.** Google prohibits sentiment-filtering (sending only happy customers to
  Google / diverting unhappy ones to a private form). Every invited buyer gets the SAME ask and the SAME
  links, unconditionally. Build the invite so it can never branch on rating/sentiment.
- **Game-changer for small businesses:** automated post-purchase emails that reliably funnel real buyers into
  leaving Google reviews (the top local-SEO signal) — the growth engine they can't build themselves — while
  also collecting on-site first-party reviews for product star snippets.

## Ties into existing work

- [[BUSINESS_PROFILE_AND_GBP]] — reviews are the deferred piece of that plan; business-target reviews + GBP
  import live there. Business Profile = `Site.organization` (already shipped).
- [[PAGE_COMPOSER]] / goal composition — reviews feed the `social_proof` pack; `AggregateRating` rides the
  `discoverability`/head channel like the other structured data.
- Offers/Products (incl. services-as-Offers) — the Product/Offer target is what makes **service** businesses
  work: review the bookable offer, not the firm.
- `runtime/html.py` Product JSON-LD (already emits `Product`/`Offer`/seller) — extend with `review` +
  `aggregateRating`. The existing "no hand-typed AggregateRating" guard is the compliance baseline.

## Open decisions

- **First target: Product/Offer** (recommended — highest CTR, the classic rich result, and it's the correct
  path for service-offers too) vs business-first. Leaning Product/Offer.
- **Review ↔ target granularity** — per `product_id`, per `offer_id`, or both? (An offer bundles products;
  decide whether a review is about the offer or a specific product in it.)
- **Aggregate scope for a Product across offers/sites** — one product reviewed on several pages: aggregate per
  product globally, or per page/offer?
- **Verified-purchase gating** — tie `first_party` submissions to a real order (checkout → review invite) for
  trust + `verified_purchase` markup, vs open submission with moderation only.
- **Denormalization** — store the aggregate on the target (product/offer/site) for cheap render vs compute at
  publish. Leaning denormalize-on-write, recompute on moderation change.
