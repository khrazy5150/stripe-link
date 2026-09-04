# ATTENTION_PRIMITIVE.md — customer acquisition as a native primitive

Status: **design draft, not built** (author direction 2026-08-28). HIGH priority, **extra-premium tier (~$69/mo)**.
Companion plan: `plans/DIGITAL_MARKETPLACE.md` (the inventory half of the same flywheel).
Consumes: `plans/OFFER_SEMANTIC_ANALYZER.md` (**prerequisite**, design-locked, not built).
Reuses: `plans/AI_AND_COMMERCE_ARCHITECTURE.md` §A.1–A.2 (BYO AI provider + adapter).

> **No existing Attention plan was found** when this was written (searched 2026-08-28 — `SOCIALITE_PARITY.md`
> is a page *template*, unrelated). This file is new; it does not duplicate the semantic analyzer, it consumes it.

## 1. Thesis — the second cold-start problem

The marketplace solves "I have nothing to sell." This solves **"nobody visits my store."** Instead of treating
social media as an external chore (or as disconnected AI-automation sludge), Junior Bay derives a coordinated
acquisition campaign **from the offer the tenant already built** — then measures which posts actually produced
sales and feeds that back.

Competitors don't do this. It is the single most differentiating thing on the roadmap.

## 2. ⭐ Architectural position — this is the sibling of Conversion Context

`plans/OFFER_SEMANTIC_ANALYZER.md` is design-locked and already names its future consumers, explicitly
including *"Google/**Meta/TikTok**/Amazon listings"* and *"email campaigns."* **Attention is one of those
named consumers — not a second, parallel semantic extraction.**

```
                    OfferSemanticModel          ← answers "what is this offer?" ONCE
                    (analyzer, design-locked)
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
  ConversionContext              AttentionContext        ← this plan
  (landing page)                 (campaign strategy)
        │                              │
        ▼                     ┌────────┼────────┐
     Checkout                 IG      TikTok   YT Shorts
```

**Hard rule:** the analyzer emits *meaning only* — no channel, format, or platform logic ever leaks into it.
AttentionContext is the channel-aware consumer. If a campaign needs a fact about the offer that the analyzer
doesn't expose, extend the **analyzer**, not a private copy here.

## 3. Attention Context

Derived from the semantic model + tenant business profile; cached per offer, regenerated on offer change.

| Attribute | Semantic role |
|---|---|
| `problems` | the painful status quo the product eliminates |
| `misconceptions` | false beliefs holding the buyer back |
| `transformations` | before → after, emotional and operational |
| `hooks` | high-contrast pattern interrupts, POV framings |
| `objections` | friction blocking conversion (answered in copy) |

Generation is **bounded by this context** rather than a free-form "write me marketing" prompt. That bound is
what separates this from sludge.

## 4. The five content pillars

| Pillar | Goal | Anchor example |
|---|---|---|
| Problem | agitate latent friction | *"You don't need more ideas; you need a system for tomorrow morning."* |
| Education | give real utility | *"The 3-slide framework I use when I have zero caption inspiration."* |
| Mistakes | challenge current behavior | *"Three reasons your posts get likes but zero checkouts."* |
| Transformation | contrast before/after | *"From a blank screen to 30 days scheduled in 45 minutes."* |
| Product proof | contextual CTA | *"I packaged the exact system into a template so you can skip the setup."* |

**Platform adaptation, not duplication** — one insight compiled into native formats: IG multi-slide carousel;
TikTok 7–12s fast hook; YouTube Shorts 20–40s talking-head script.

## 4a. ⭐ The OWNED channel — Attention Blocks on the tenant's own page

Every channel in §2 is **rented**: IG, TikTok and YT Shorts each decide who sees a post. The tenant's own
published page is the one surface they own outright, and today it carries no attention surface at all.

```
  AttentionContext
        │
   ┌────┴──────────────┬──────────┬──────────┐
   ▼                   ▼          ▼          ▼
 ATTENTION BLOCK      IG        TikTok    YT Shorts
 (owned — this §)     └──────── rented ───────┘
```

**Attention Block** is the primitive; **Page Ribbon** is its first presentation. Naming it that way leaves
room for Attention Card / Grid / Modal / Feed without forcing every future mechanism into a ribbon shape —
and it matches how this codebase already works, where an element declares a presentation and the composition
layer places it.

### What it is

A horizontal interruption placed mid-scroll, after the visitor has enough context to care:

    [image]   EYEBROW
              Headline
              Supporting copy, with an optional inline link
              [ CTA → ]

Borrowed from YouTube's Premium banner, which is the same idea aimed at the same job.

### Why it is not a `content_block`

`content_block` is image + heading + text, repeatable. The Ribbon adds an **action**, and that changes its
category: a content block informs, a ribbon asks. Same reason `checkout_cta` is its own element rather than
a styled paragraph.

### The twelve uses, sorted by what they actually require

| Needs nothing new | Needs per-visitor state |
|---|---|
| promote an offer · upsell · cross-sell · limited-time sale · lead magnet · tenant content · video/channel · membership · affiliate · seasonal merchandising | free-shipping threshold ("you're $17 away") · live social-proof counts |

**Ten of twelve are static.** That is the whole argument for shipping the static Ribbon first and treating
the dynamic layer as separate work — it is not a compromise, it is most of the value.

### ⚠️ The constraint that decides everything: pages are STATIC artifacts

`runtime/publishing.py` renders a page ONCE at publish time and `put_object`s it to S3; CloudFront serves the
bytes. There is no per-request render, so **nothing on a published page can vary by visitor server-side.**

Every context-aware case — *has purchased Product A*, *cart is $75*, *returning visitor* — therefore needs
**client-side hydration**: the Ribbon ships as markup plus a small script that reads cart/purchase state and
swaps its content. That is a real project (a state source the page may read, a swap that does not shift
layout, a no-JS fallback) and it belongs after the static Ribbon exists, not inside it.

### The `purpose` field — only where it changes behaviour

A ten-value enum that renders identically in every case is a taxonomy without behaviour: a field the tenant
must think about for no return. `purpose` earns its place only where it CHANGES something — the default copy,
which fields appear, what the CTA may target, or where the block is placed.

Start with the three that genuinely differ:

| purpose | what it changes |
|---|---|
| `promote_offer` | CTA targets one of the tenant's own offers/pages; copy seeded from that offer's semantic model |
| `capture_lead` | CTA targets a form/email capture; no price shown |
| `promote_content` | CTA targets a URL; supports a video thumbnail |

`custom` covers everything else. Add a purpose when it does work, not when it names a use case.

### The wallpaper rule

Three ribbons stop being interruptions and become wallpaper — which destroys the only property that makes
this element worth having. **Cap: two per page**, warn on the second. A constraint that protects the feature
from its own users, in the same spirit as the single non-repeatable `checkout_cta`.

### Presentations (P1)

1. **image-left** — the YouTube formula, the default
2. **centered** — no image, headline + copy + CTA
3. **compact row** — image ┃ headline ┃ CTA on one line

A video/animated variant is deferred; `hero_media` already handles video and its lessons should be reused
rather than re-derived.

### Measurement

The chain the author described — impressions → ribbon views → clicks → offer views → checkout → purchase —
is exactly §8's attribution model applied to an owned channel, and it is the easiest place to prove that
model works: same-origin, no platform to ask, no redirect to lose. **Ship Ribbon attribution with the
Ribbon**, as §8 already argues for shipping attribution early.

### Phasing

- ~~**A-P1**~~ **SHIPPED 2026-09-04:** static Ribbon element — image/eyebrow/headline/copy/CTA, three presentations,
  repeatable capped at two, `free` placement so the tenant drags it where it belongs, CTA reusing the
  existing action vocabulary (`external_url`, `open_form`, `capture_email`, `call_number`, …) plus one
  internal target for "another of my offers/pages".
- **A-P2:** click attribution on the Ribbon, feeding §8.
- **A-P3:** client-side hydration for the dynamic cases — cart threshold, purchase state, returning visitor.
- **A-P4:** generation — the tenant says "promote my new product" and AttentionContext writes the Ribbon
  alongside the social variants, which is the point of putting it in this document rather than a separate one.

## 5. Data model (table-per-entity — adapted)

> Source proposal assumed single-table (`PK: TENANT# / SK: CAMPAIGN#…`) and TypeScript. This repo is
> **Python 3.12**, 36 tables, repository-per-entity. Port the spirit.

| Table (`jb-{name}-{env}`) | Key | Holds |
|---|---|---|
| `attention-contexts` | PK `tenant_id`, SK `offer_id` | derived context cache |
| `attention-campaigns` | PK `tenant_id`, SK `campaign_id` | intensity, duration, window, status |
| `attention-posts` | PK `tenant_id`, SK `{due_at}#{post_id}` | pillar, platform, format, payload, status, attribution |

Sorting posts by `due_at` in the SK makes "what's due now?" a cheap range query for the publishing sweep, and
"show me the calendar" a cheap range query for the UI. A GSI on `status#date` supports calendar filtering.

## 6. Publishing — vendor-agnostic adapter

### 6.1 The interface is the insurance
One normalized adapter contract (`publish(payload) -> {external_post_id, live_url}`) with the post payload
stored in **our** schema, never a vendor's request format. Direct per-platform adapters can slot in later
behind the same contract.

### 6.2 Aggregator first — the approval gauntlet is the real blocker
Direct Meta/TikTok/YouTube integration requires **app review measured in weeks-to-months**, which the author is
not positioned to do now. An aggregator has already passed those reviews. **Implementation #1: Outstand.so**
(candidate; also evaluated: Ayrshare). Claimed terms (2026-08-28, **not independently verified**): built for
SaaS embedding without white-label surcharge; **$19/mo base including 3,000 posts**, then $0.007/post
(→$0.005 over 10k), **unlimited connected profiles**; Managed Keys **and** BYOK with branded OAuth.

At 60 posts/tenant/month that means the **first ~50 premium tenants publish inside the $19 base**, and ~$40/mo
total at 100 tenants — publishing is <1% of a $69 tier. Per-*profile* pricing (the common alternative) is the
model that scales badly; avoiding it is the structural win.

### 6.3 ⚠️ Managed Keys → BYOK requires tenant re-authorization
Confirmed from OAuth first principles, not vendor claims: access tokens are bound to the issuing app's
`client_id`; platforms forbid using App A's token under App B. **Switching to your own developer app forces
every connected tenant to reconnect.**

**Strategy (the migration cost scales with connected accounts, so cross early):**
1. **Launch on Managed Keys** — zero platform review, feature ships, demand validated.
2. **Run Meta/TikTok app reviews in parallel** — paperwork on a background thread, not a blocker.
3. **Migrate to BYOK while the tenant count is small** — at 20–50 tenants a re-auth is an email + a banner;
   at 5,000 it is a project.

### 6.4 Reconnection is a first-class state, not an error path
Required regardless of BYOK — tokens expire, users revoke, platforms force periodic re-auth. The connection
layer must: detect invalid tokens → **queue** due posts instead of failing them → surface a "Reconnect your
Instagram" banner (**same pattern as the existing Stripe not-connected banner + avatar pill**) → resume the
queue automatically. Build this well and the BYOK migration is just "everyone taps reconnect once."

With Managed Keys the tenant sees an unfamiliar brand on the OAuth screen — front it with the **branded intro
modal pattern already built for Stripe Connect** (`ConnectIntroModal.vue`): explained-unfamiliar is fine,
surprising-unfamiliar erodes trust.

## 7. Scheduling — reuse the sweep, don't schedule per post

Three `rate(15 minutes)` scheduled sweeps already exist (appointment reminders, cart recovery, review
invites). The publisher is a **fourth of the same shape**: query posts due ≤ now, dispatch through the
adapter, mark published/failed with retry/backoff. This avoids per-post EventBridge Scheduler limits, matches
established patterns, and costs essentially nothing.

## 8. Attribution — ship this EARLY

`/offer/{id}?src={tracking_slug}` → click recorded → session context → on checkout, GMV attributed to the
**post and its pillar**. Feedback: *"problem carousels convert 3.8× better than transformation videos"* →
weight the Problem pillar higher in the next generation.

**Sequencing note:** attribution is worth building **before** autopilot generation. It makes even
hand-posted content measurable, it is cheap (checkout already exists), and it produces the data that makes
generation smart later. It is also the piece competitors most conspicuously lack.

## 9. Cost model, pricing, and the trial

### 9.1 ⭐ BYO AI key already resolves most of the COGS problem
`AI_AND_COMMERCE_ARCHITECTURE.md` §A.1 locks: per-tenant AI provider config, KMS-encrypted key, **"cost is the
tenant's (their key, their bill)."** §A.2 provides the normalized `generate_structured()` adapter. **Reuse
both.** Consequence: **text/copy generation costs the platform nothing**, and this plan does *not* reverse the
"integrations, not in-house metered features" decision recorded in the pricing pivot.

### 9.2 What actually costs money
| Asset | Cost | Treatment |
|---|---|---|
| Text (60 posts) | tenant's key → **$0 to platform** | unlimited |
| Carousel images | cheap; tenant key where supported | generous |
| **AI video** | **10–100× an image per clip** | **strictly rationed, metered, visible credit count** |
| Publishing | ~$0.42/tenant (often $0 inside base) | negligible |
| Stripe fee on the $69 | **~$2.30** | the largest fixed line item |

Video is the only line that can materially move the margin. Everything else is noise.
(Correcting an external "~99% gross margin" claim: that reflects publishing alone. Realistic gross margin is
strong but not 99% once Stripe fees and any platform-funded media are counted.)

### 9.3 Trial: feature-complete, usage-capped — the homepage promise stays intact
The homepage says **"Full access for 14 days — free."** Do **not** feature-gate Attention out of the trial;
that would contradict shipped public copy. Instead cap *usage*: e.g. a **7-day sample campaign** instead of
30, images included, **one** video. The tenant still gets the "wow" (a campaign already written for their own
product), platform spend stays near zero, and the promise remains true.

### 9.4 Tier
Extra-premium, **~$69/mo** (author). Model it as a **higher plan tier**, not a stackable add-on — the billing
rail is single-line-item today (see `docs/PLATFORM_PLANS.md`); multi-item add-on billing is deferred work.

## 10. Phases

| Phase | Deliverable |
|---|---|
| **A0 — Prereq** | `OfferSemanticAnalyzer` (its own plan; also independently improves SEO/slug/title) |
| **A1 — Context** | AttentionContext derivation + cache; 5-pillar prompt templates over the BYO-key adapter |
| **A2 — Attribution** | `?src=` slugs, click ingestion, checkout attribution, per-post/per-pillar GMV *(early — see §8)* |
| **A3 — Campaign engine** | intensity-aware 30-day generation; batch-write the post queue |
| **A4 — Calendar UI** | edit/drag/reschedule/inject; **export & copy-to-clipboard** (delivers value with zero publishing APIs) |
| **A5 — Publishing** | adapter interface + Outstand (Managed Keys); reconnection state; the 15-min publish sweep |
| **A6 — BYOK migration** | own developer apps once reviews land; guided reconnect while tenant count is small |
| **Later** | performance-weighted pillar selection; more platforms; direct per-platform adapters |

## 11. Verify before A5 hardens
Run a **paid one-week spike** with the chosen vendor: one real IG account, publish a carousel and a video,
then **deliberately revoke the token mid-queue** and read the error. That single test validates pricing,
embedding rights, and — most importantly — the failure behavior the whole scheduling design depends on.
Vendor claims in §6.2 are unverified marketing until this passes.
