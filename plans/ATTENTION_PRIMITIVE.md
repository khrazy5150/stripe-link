# ATTENTION_PRIMITIVE.md — customer acquisition as a native primitive

Status: **design draft, not built** (author direction 2026-08-28). HIGH priority, **extra-premium tier (~$69/mo)**.
**Video generation lives here and nowhere else (2026-11-01)** — see §9a. Consumes
`plans/HIGGSFIELD_INTEGRATION.md`.
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

## 2a. Where it lives — its own project, `../sam/attention`

**Name CONFIRMED by the author 2026-11-01, and SCAFFOLDED the same day** once A0 had shipped and there
was real work to put in it — deliberately not before, because an empty stack is how
`../sam/ai-video-generator` became the three-file trap documented below. It holds A1's domain layer and
no `template.yaml`: a project, not yet a deployment. See §10a.

**Not `stripe-link`.** That stack is at CloudFormation's 1MB transform limit with ~138KB of headroom, at
~441 of 500 resources, and at 225 of a 240-event route guard. This plan needs tables, a post queue, a
scheduling sweep, publishing adapters and an OAuth reconnection flow — it would not fit, and it would be
competing for the budget every other feature needs.

**And not `../sam/ai-image-generator`.** That is the GENERATOR service: metered media against a platform
key, a server-side quality ceiling, permanent CDN URLs, takedown with purge. `plans/HIGGSFIELD_INTEGRATION.md`
§1 puts video generation there because video is another generator beside images. **Attention is not a
generator — it is a consumer of one.** Campaign derivation, scheduling, publishing and attribution have
nothing in common with "turn a prompt into a file", and folding them together would make one service with
two unrelated failure modes and two unrelated deploy cadences.

So: **two distinct projects**, and the dependency runs one way.

```
  stripe-link            offer, semantic model, attribution sink
       │
       ▼
  attention              AttentionContext, campaigns, calendar, publishing, attribution
       │
       ▼
  ai-image-generator     images + video, metered against the platform key
```

It shares what the admin site already shares, the same way: the **Cognito pool** by parameter and the
**tenant profile** by a scoped IAM read. Being signed in is not being entitled — entitlement is read per
call, as `platform_status` and `entitlements` already do.

**NOT `../sam/ai-video-generator`** either. That folder exists and is an abandoned three-file scaffold for
an unrelated idea ("workout videos with music"), with its own Cognito pool and Python 3.11. The name is the
trap; see `plans/HIGGSFIELD_INTEGRATION.md` §1.

## 3. Attention Context — **4 of 5 SHIPPED 2026-11-01, inside the semantic model**

Derived from the semantic model + tenant business profile; cached per offer, regenerated on offer change.

> **A0 absorbed most of this.** `problems`, `misconceptions`, `transformations` and `objections` now live
> on `OfferSemanticModel.facts.positioning`, derived by `domain/semantic_enrich.py` and cached on the offer
> — not because A1 was built early, but because §2's own rule says a consumer needing a fact the analyzer
> does not expose must EXTEND THE ANALYZER rather than keep a private copy. More than one consumer wants
> these: a landing page answering objections and a campaign answering objections must not derive them
> twice and disagree.
>
> **`hooks` deliberately did NOT move.** A high-contrast pattern interrupt is a FORMAT decision — how to
> open a Reel versus a subject line — and §2's hard rule is that channel logic never enters the model.
> It stays here, derived per channel, which is exactly what AttentionContext is for.
>
> **So A1 reduces to:** `hooks`, the five-pillar prompt templates, and the per-offer campaign-side cache.
> All three live in `../sam/attention`, which now exists — `hooks` and the pillar templates are built,
> the cache's *identity* is built and its *store* is not. See §10a.
>
> **Second-consumer debt: PAID 2026-11-01.** An FAQ element now seeds its questions from
> `positioning.objections` — an FAQ exists to answer friction blocking the purchase, which is exactly what
> that field is. So a tenant who enhanced their offer stops facing one blank row and only has to write the
> ANSWERS. The answers are deliberately left empty: we know what worries a buyer, we do not know this
> tenant's policy, and generating one would be the platform making a commercial promise on their behalf.
>
> That settles why `positioning` lives on the shared model rather than inside this plan — a page and a
> campaign now both read it, from one derivation, and cannot disagree.

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

## 8. Attribution — ship this EARLY — **A2 SHIPPED 2026-11-01**

> **Built in `stripe-link`, not in `../sam/attention`.** The published page, the view beacon and both
> checkout paths all live here, which is exactly why this was buildable before the Attention project
> exists — and why the plan calls it the cheap early piece. The campaign-side *reporting* belongs in
> `attention` when that lands; the SINK is here.
>
> **The chain, end to end:** `?src=` on a published page → captured and held in `localStorage` →
> beaconed to `/t/view?s=` → counted as an arrival per (page, source, visitor, day) → carried into
> checkout → `metadata[src]` at Stripe → `order.attribution_source`. GMV per post is a join on one string.
>
> **Four decisions worth keeping:**
>
> - **The slug is readable, not hashed.** Unlike `link_id`, this IS the tenant's own label and has to come
>   back on a report — "ig-reel-nov-03" is the answer they want, and a hash would need a second table to
>   turn it back into words. That makes it the one place tenant text reaches a key, so the character set is
>   an allow-list and the length is capped.
> - **FIRST TOUCH WINS.** A visitor who arrives from a Reel and later returns by bookmark is still credited
>   to the Reel. Overwriting on each visit reassigns the sale to whatever they touched last, which is the
>   attribution mistake that makes a channel look worthless. 30-day expiry.
> - **A source counts the view AS WELL.** Unlike `l` (a click, which is exclusive), `s` is the same arrival
>   on a second axis. And a mistyped slug never costs the page view — losing a view because a tenant fumbled
>   a campaign label would be the analytics equivalent of refusing the page.
> - **Absent attribution writes NO field**, rather than `""`. An order nobody tracked and a post whose slug
>   failed to arrive must not look the same in the column.
>
> **The join landed too.** `GET /pages/{id}` now returns `attribution: [{source, arrivals, conversions,
> revenue_cents}]` — arrivals from the counters, money from the same fold over paid orders the page cards
> already use, keyed on the post instead of the page so the two can never disagree about what a conversion
> is. The order's slug lives at `attribution.source`, beside `page_id`: the page is WHERE they converted,
> the source is WHAT brought them to it, and putting it there means all three order builders (checkout,
> subscription renewal, upsell) carry it from one change.
>
> The report is the **UNION** of arrivals and sales, not the intersection. A source with attention and no
> sales is the most useful row on it — the post that got looked at and sold nothing is the whole reason to
> measure — and a source with sales but no arrivals is real too (the visitor came before the tracker
> shipped, or cleared their storage), so dropping it would quietly understate revenue.
>
> **Still to build:** the per-PILLAR view and the weighting loop — "problem carousels convert 3.8x better
> than transformation videos". That needs campaigns to exist before a pillar is a thing, so it waits for
> A3. Per-POST is answerable today.
>
> **The dashboard renders it** as a "Traffic sources" accordion in the builder — source, people, sales,
> revenue — shown only when something was actually measured, because the rows come from the published
> artifact's tracker and a table of zeros would stand in for traffic nobody counted. A source with sales
> and no arrivals shows an em dash rather than 0: someone bought before the tracker shipped, and zero
> would claim we measured and found none. The panel also says how to feed it (`?src=your-label`, first
> touch wins), because a report nobody knows how to feed is a report nobody feeds.
>
> It rides the SAME single-page read the link clicks already used (`loadPageNumbers`, renamed from
> `loadLinkClicks`) — a second request would double the cost of opening the builder to show two panels of
> one document.
>
> **The panel also BUILDS the link**, which A2 shipped without: a tenant had to know `?src=` existed and
> append it by hand, and a measurement feature nobody can easily feed is one nobody feeds. Type a label,
> copy the tagged URL. The label is sanitised in the browser by the SAME rule `page_views.source_slug`
> applies server-side — sanitising only on the server would mean the tenant posts `IG Reel` while the
> report keys on `igreel`, so the label they chose and the row they read would disagree.
>
> The panel therefore opens on any PUBLISHED page rather than only once something is measured: gating it
> on having rows is a chicken-and-egg — no link, no arrivals; no arrivals, no way to make a link. A draft
> is excluded because it has nowhere to send anyone, and a link that works nowhere gets posted before
> anyone discovers it.



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

## 9a. ⭐ Video generation belongs to THIS tier, and to no lower one (2026-11-01)

`plans/HIGGSFIELD_INTEGRATION.md` supplies the video; this plan supplies the reason anyone may buy it. A
"$39 creative" rung selling generation without distribution was proposed and **rejected**: it is the
weakest §11.5 position available, it is the rung that attracts the tenant who signs up to farm cheap
generation, and under a platform key that farming is billed to us.

**The product is the channel, not the clip.** A tenant holding a Higgsfield key can generate video. They
cannot schedule a Reel, post to three platforms on a calendar, or learn which post produced a sale. That
is the independent value Higgsfield's §11.5 requires, and it needs no argument — it is a capability the
vendor does not have. The five pillars in §4 are what the video is *for*; §8's attribution is what makes
it worth paying for twice.

**Consequences for this plan:**

- **The $69 allowance is in SECONDS of video** (`video#<period>`), expiring monthly, no rollover — the
  reasoning is in the Higgsfield plan's §8 and is not repeated here.
- **The allowance is large because campaigns consume it**, not because the tier is expensive. A 30-day
  plan across five pillars needs an order of magnitude more clips than a landing page would. That is what
  makes the number defensible rather than arbitrary.
- **Generation is bounded by AttentionContext** (§3), which is the same bound that separates this from
  sludge — and it is also the §0b "generate from the offer" rule arriving from the other direction.
- **Nothing ships before this tier does.** There is no earlier rung to fund the build, so A0–A4 are the
  runway and the revenue starts at launch.
- **Do not fund the Higgsfield balance early.** Concurrency is tiered on a ROLLING 28-day window, so money
  added before there is traffic buys capacity that expires unused. Fund it as launch approaches.

**The earliest defensible launch point is A4, not A5.** With attribution (A2) and the calendar's export /
copy-to-clipboard (A4), the tenant gets a derived 30-day campaign, the generated assets, a schedule, and a
report of what sold — a complete product with **zero publishing APIs**, and one that still cannot be
mistaken for a generation endpoint. A5 automates the posting; it is not what makes the tier legitimate.

## 10. Phases

| Phase | Deliverable |
|---|---|
| **A0 — Prereq** | ✅ **SHIPPED 2026-11-01** — `OfferSemanticAnalyzer` + the `facts.positioning` enrichment tier |
| **A1 — Context** | 🟡 **domain layer built 2026-11-01, NOTHING DEPLOYED** — see §10a |
| **A2 — Attribution** | `?src=` slugs, click ingestion, checkout attribution, per-post/per-pillar GMV *(early — see §8)* |
| **A3 — Campaign engine** | intensity-aware 30-day generation; batch-write the post queue |
| **A4 — Calendar UI** | edit/drag/reschedule/inject; **export & copy-to-clipboard** (delivers value with zero publishing APIs) |
| **A5 — Publishing** | adapter interface + Outstand (Managed Keys); reconnection state; the 15-min publish sweep |
| **A6 — BYOK migration** | own developer apps once reviews land; guided reconnect while tenant count is small |
| **Later** | performance-weighted pillar selection; more platforms; direct per-platform adapters |

## 10a. A1 as built — `../sam/attention` (2026-11-01)

The project §2a described exists, with its own private GitHub repo and its own SAM stack, like every
sibling. **A1's read surface is complete**; A3 onwards is not started.

```
src/attention/domain/pillars.py    the five pillars -- WHAT to say, pure meaning, no platform
src/attention/domain/channels.py   formats + hooks -- HOW it opens, the ONLY channel-aware module
src/attention/domain/context.py    AttentionContext: the join, the cache identity, a brief sequence
src/attention/entitlement.py       the gate -- a mirror of stripe-link's rule, fail-closed
src/attention/stripe_link.py       the ONLY file that knows stripe-link's storage shape
src/attention/cache.py             the per-offer context store, read-through and allowed to fail
src/handlers/api.py                /health, /me/context, /me/briefs
```

§2's hard rule is enforced one level down, which is the point of the split: `pillars.py` names, per pillar,
the single field of `OfferSemanticModel` it is grounded in (`positioning.problems`, `taxonomy.hierarchy`,
`positioning.misconceptions`, `positioning.transformations`, `positioning.objections`), and a *test* asserts
no platform word appears in it. A fourth channel therefore costs one entry in `channels.FORMATS`, not five
rewritten pillars.

Two guarantees are structural rather than remembered:

- **A pillar with no material is SKIPPED, not filled.** `available()` returns only supported pillars, so an
  un-enriched offer supports **Education alone** — a true answer, and the reason the "Understanding" button
  exists upstream. Inventing a Problem post about a real product is exactly the sludge §1 refuses.
- **Every hook pattern contains `{anchor}`.** A hook cannot drift off the offer's own material into a stock
  opener, which is what "high-contrast pattern interrupt" degenerates into when generated free-form. Hooks
  are anchored in `problems` and `misconceptions` only — never in `transformations`, because opening on the
  payoff is the "amazing results!" post everybody scrolls past.

`AttentionContext` **joins rather than extracts**: four of §3's five attributes are read straight from
`facts.positioning`, and only `hooks` is derived. Its `cache_key` folds in `model_version`, so the day a
pillar's grounding changes every cached context is stale by construction instead of by someone remembering
to purge — and an unknown cache state counts as **stale, not fresh**, since a gate built from absences
passes anything that does not exist.

### How the offer reaches this stack — decided 2026-11-01

§2 forbids a second extraction, so the offer's cached `semantic_model` is the only input, and there were two
ways to get it. **A scoped cross-stack `GetItem`, not an HTTP hop.** §2a had already accepted that shape for
the tenant profile, entitlement must be read per call so that read is not optional, and `stripe-link` sits
at 225 of a 240-event route guard — a second hop would spend route budget to re-fetch data the caller's own
IAM role can already see.

The cost is a **schema coupling**: this stack knows that an offer is `PK=TENANT#<tenant>`,
`SK=OFFER#<mode>#<offer_id>` and that a profile's PK and SK are both `TENANT#<tenant>`. That is contained in
one file, `attention/stripe_link.py`, whose tests are keyed by the literal PK/SK strings — a fake keyed by
arguments would accept any format the code invented, which is how the sibling stack once shipped a lookup
for a key that could never exist. The IAM policy grants `GetItem` on two named tables and nothing else: no
`Scan` (one bug would otherwise read every tenant's catalogue) and no write at all.

### The gate, and the one bug a test found

Entitlement is read **before** the offer, because a read performed first has already answered the question
the gate exists to ask. `attention` is now a capability in `stripe-link`'s `CAPABILITIES` **and in its
`BETA_CAPABILITIES`** — the first member that set has ever had. That is what keeps an unreleased, unpriced
feature off every comped account and every live trial, which is the one thing a beta must not do. Today the
ways in are a `beta: ["attention"]` grant or a plan that sells it explicitly. **Graduating it means deleting
it from `BETA_CAPABILITIES` here AND from `BETA_ONLY` in `attention/entitlement.py`** — doing one without
the other makes two stacks disagree about who may use a paid feature.

The mirror diverges from the original three times, all fail-closed, and the second was found by a test
rather than by review: run unchanged, `stripe-link`'s rules compose into a **free pass for `{}`** — no
status means "trial", no subscription means a platform trial, no clock means grandfathered, and a live trial
is feature-complete. Three correct rules, one free pass. Right in the original, whose question is "may this
store keep selling?"; wrong for admitting someone to a paid tier.

Relatedly, an **unreadable** profile is a 503, never a 403. An outage reported as an upgrade prompt sends a
tenant to buy something they already have.

### Deployed, and what dev proved

`jb-attention-stack-dev` is **live** (2026-11-02): one table, one function, `GET /health` answering
unauthenticated. The prod changeset is created and audited — 9 adds, no modifications, parameters pointing
at the prod tables — and awaits execution.

Three things only a real deployment could establish:

- **The cross-stack read works.** Invoking the dev function with a real tenant's claims returns
  `403 not_entitled`, not `503 profile_unavailable`. A wrong key or a missing IAM grant would have produced
  the 503, so the 403 proves the profile read end to end — and proves the beta gate refuses a live trial.
- **The key formats match real data, and the read is genuinely MODE-SCOPED.** Dev offers are stored
  exactly `PK=TENANT#<tenant>`, `SK=OFFER#<mode>#<offer_id>`, and a profile's PK and SK are both
  `TENANT#<tenant>`. Proven against a pair that exists in one mode only: `offer_EpxWZToCae7` (test-only)
  resolves in `?mode=test` and **404s in `?mode=live`**, and `offer_Ou5hhPV3WNf` (live-only) does the
  reverse. A mode-blind read would have answered both. A probe that accidentally sent an empty mode got
  `400 mode_required`, which is the never-default rule holding on real traffic rather than in a test.
- **⚠️ `semantic_model` is persisted by ONE thing, and almost no offer has it.** 0 of 12 dev offers carried
  one. It is written only by the enrich operation behind the "Understanding" button (`ai_generate.py:404`);
  **saving an offer does not produce it** — `offers.py` derives a model transiently for the slug and throws
  it away. So A1's `409 no_semantic_model` is the common FIRST answer rather than an edge case, and its
  message names that button. The consequence for A3 is larger: a campaign cannot be generated for an offer
  nobody has enriched, so **enrichment is a prerequisite step in the campaign flow**, not an optional
  polish — either the UI walks the tenant through it or the campaign route runs it on their behalf.

**Both stacks are live, and tenant `586173f0…` (keithdecosta@gmail.com) is entitled on dev and prod**
(granted 2026-11-02). The Cognito pool is shared, so that one `sub` is the tenant id in both — there is no
second identity to grant. Each grant is a targeted `update_item` using
`list_append(if_not_exists(beta, []), …)` guarded by `attribute_exists(PK) AND NOT contains(beta, …)`, not
a load-mutate-put: a tenant profile has many writers and a wholesale put loses the siblings, and the
condition makes the grant idempotent.

The grant is verifiable without reading a single offer. On dev the gate moved `403 not_entitled` →
`409 no_semantic_model`; on prod, probed with a deliberately bogus offer id, `403` → `404 offer_not_found`.
The 404 rather than a 503 also proves the prod function's cross-stack read of `jb-offers-prod` works.

| | dev | prod |
|---|---|---|
| stack | `jb-attention-stack-dev` | `jb-attention-stack-prod` |
| API | `bjhabjf4q1` | `n1fpqq3mae` |
| tenant entitled | ✅ | ✅ |

### The dashboard surface — shipped dev 2026-11-02

An **Attention** panel in the offer edit modal, immediately after Understanding. That adjacency is the
design: post angles are derived from that understanding and nothing else, so the service's commonest
refusal is answered by the button directly above the banner reporting it.

It is **gated on `attention_api_base` being configured** for the channel (`app_config`, per environment,
no hardcoded host) — so an environment without it renders nothing rather than firing at a guessed host.
The sibling base is an *argument* to the dashboard's existing `apiRequest`, not a second fetch wrapper:
the id-token choice, the proactive renewal and the single 401 retry are what matter around that fetch, and
a copy of them would be a second place for the 2026-10 access-token bug to return. `apiRequest` already
sends the current Stripe mode, which is exactly what the service requires.

The panel holds **no campaign logic** — §2 again. Which pillars an offer supports, which it cannot, every
anchor and every hook come from the service; the component contributes a label map and a clipboard. A test
asserts the Attention code names no pillar, format or hook style. **Copy-all exports the set as plain
text**, which is the whole deliverable until A5 can publish, and is worth more than nothing by a long way.

**Still open in A1:** the five-pillar generation call over the BYO-key adapter — turning a brief into
finished copy. The angles themselves are usable by a human today.

**Prod needs one write** that is not code: `environments.{dev,prod}.attention_api_base` in the prod
`app_config` document. Until then the prod dashboard shows no panel, which is the gate working.

## 11. Verify before A5 hardens
Run a **paid one-week spike** with the chosen vendor: one real IG account, publish a carousel and a video,
then **deliberately revoke the token mid-queue** and read the error. That single test validates pricing,
embedding rights, and — most importantly — the failure behavior the whole scheduling design depends on.
Vendor claims in §6.2 are unverified marketing until this passes.
