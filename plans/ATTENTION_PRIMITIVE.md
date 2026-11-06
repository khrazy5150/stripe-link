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

## 1a. Competitive position — what the nearest product actually sells (2026-11-05)

**ViralSpy and Higgsfield are two different companies, and conflating them is easy to do.** ViralSpy was
this plan's *predecessor vendor candidate*, rejected in `HIGGSFIELD_INTEGRATION.md` §0 (*"no API, sold
single-seat accounts and forbade resale"*). It is not Higgsfield under another name, and it is not a
supplier — it is the nearest thing to a competitor the roadmap has.

**What it sells, read off its own pricing page ($47/mo, 14-day trial):** find the top viral videos in a
niche, score them, explain why each went viral, produce a tailored script, and give step-by-step filming
directions — plus a content library and a calendar.

**The test that separates it from this plan is where the WORK lands.** Its own words: *"so you know what
to capture **when you film**"*, *"where to stand, what to say, how to deliver it."* Every output ends
with the tenant holding a camera. It sells **the formula, not the artifact** — a brief. The tenant still
supplies production, posting, and somewhere for the traffic to land.

| | the brief-seller ($47) | this plan (~$69) |
|---|---|---|
| What to say | script + filming directions | derived from the offer itself (A0/A3) |
| **Who films it** | **the tenant** | nobody — generated (`HIGGSFIELD_INTEGRATION.md`) |
| **Who posts it** | **the tenant** | nobody — published (§6, A5) |
| **Did it sell anything** | **unanswerable** | per-post / per-pillar GMV (§8, A2 shipped) |

**The last row is structural, not a feature gap, and it is the whole §8 argument.** A research tool has
no checkout, so it can never attribute a sale — the money never passes through it. A calendar that cannot
say which post produced revenue is a planning tool. This is what §8 means by *"the piece competitors most
conspicuously lack"*, and the competitor's own pricing page is the evidence: a library, a calendar, and
no revenue number anywhere on it.

**The honest gap, recorded so it is a decision rather than a discovery.** Three of its eight bullets are
outward-looking trend research — what is blowing up in this niche, scored, with a reason. This plan's
pillars generate from the OFFER's own semantics and look outward at nothing. For a buyer who wants to
know what is trending, we are not better; we are different and dearer. `HIGGSFIELD_INTEGRATION.md` §5b
already notes why closing it would be cheap *if we choose to* — trend data is the one thing with a real
shared-cache lever, because every tenant asks about the same hashtags in the same week, which is exactly
what generated video is not.

**Trend-SEEKING is not trend-SETTING, and we should not build the seeking half (author, 2026-11-05).**
Recreating what already worked for a stranger is lagging by construction — the window has closed by the
time the pattern is visible, and "person centred, trendy caption" is an observation, not a moat. Building
our own version buys onto their axis, which is the one thing this section argues against.

**The feedback loop is the better version of the same idea, and §10's Later row already names it:
performance-weighted pillar selection.** A research tool reports what got VIEWS for someone else; §8
reports what got SALES for THIS tenant, on their own audience. That is trend-setting for an audience of
one — the only audience paying them. It needs no scraping, no data licensing and no platform-research
agreement, because the data is already ours: the click is our slug and the sale is our checkout.

The one rung missing from that loop is platform-side reach (views → clicks; §8 already owns clicks →
sales). Whether we get it cheaply depends on the publishing vendor's API, which is **§11a item 3** — a
free question during a week already paid for. Outstand is a PUBLISHER, so it may return metrics on posts
it sent; it will not return competitor intelligence, and expecting that of it is a category error.

**Evidential caveat.** All of the above is read from a public pricing page — their marketing, not a
product audit. §6.2's rule applies to competitors as well as vendors: treat it as a claim until something
tests it. The structural point (no checkout, therefore no attribution) is the part that does not depend
on their copy being accurate.

**Marketing rule (author, 2026-11-05): the campaign NAMES NO COMPETITOR.** Positioning is on our own
value — *a way to stop the headache of making attention-grabbing content for social media, and to find
out which of it produced business*. Comparative advertising would teach our buyer a cheaper product
exists and frame us as the expensive option, on an axis we did not choose.

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
(**CHOSEN 2026-11-05** — not a candidate; also evaluated: Ayrshare, no longer live). Claimed terms (2026-08-28, **not independently verified**): built for
SaaS embedding without white-label surcharge; **$19/mo base including 3,000 posts**, then $0.007/post
(→$0.005 over 10k), ~~unlimited connected profiles~~ **100 connected accounts — corrected 2026-11-05, see §6.2b**; Managed Keys **and** BYOK with branded OAuth.

At 60 posts/tenant/month that means the **first ~50 premium tenants publish inside the $19 base**, and ~$40/mo
total at 100 tenants — publishing is <1% of a $69 tier. Per-*profile* pricing (the common alternative) is the
model that scales badly; avoiding it is the structural win.

### 6.2b ✅ PERMISSION GRANTED — and the one claim it corrects (2026-11-05)

**Outstand granted written permission to resell on the $19 plan, limited to 100 CONNECTED ACCOUNTS.**
That closes both of §6.2a's blockers at once: resale is permitted (finding 1), and it is permitted on the
$19 tier rather than only on some unnamed production tier (finding 2). §11's Step 0 is done.

**⚠️ THE 100 IS NOT AUTOMATIC ON PURCHASE (2026-11-05).** Buying the $19 tier does not enable the
commercial 100-account allowance; it is enabled by them, by email, AFTER the purchase. So the critical
path is **buy → email → wait**, and the wait is a third party's reply, not a deploy. Start the email the
same hour as the purchase. There are also no public API docs on this tier: the documentation arrives with
the purchase, which is why no adapter can be written ahead of it (§6.1's fake exists for exactly this).

**One §6.2 claim is corrected: "unlimited connected profiles" is wrong. The ceiling is 100.** The post
economics are untouched — the 3,000-post base and the $0.007 overage are neither confirmed nor
contradicted by the permission reply, and remain unverified marketing until §11's spike.

**Where the ceiling actually bites.** The account cap and the post base run out at roughly the same
place, which is a coincidence worth knowing rather than relying on:

| Profiles a tenant connects | Tenants inside 100 accounts | Posts/mo at 60 per tenant | Inside the 3,000 base? |
|---|---|---|---|
| 1 (IG only) | 100 | 6,000 | No — ~$21/mo overage |
| **2 (IG + TikTok)** | **50** | **3,000** | **Exactly at it** |
| 3 | 33 | 2,000 | Yes |
| 4 | 25 | 1,500 | Yes |

So §6.2's "first ~50 premium tenants inside the $19 base" survives — at two profiles per tenant it is
almost exactly right, for a different reason than it gave. At 50 tenants × $69 that is $3,450/mo of
revenue against ~$19 of publishing cost, and §6.2's "<1% of a $69 tier" holds.

### 6.2d ⭐ THE REAL PRICING PAGE, read at last (2026-11-05) — §6.2c's cliff does not exist

Everything before this section priced the vendor from email and marketing copy. The actual billing page
says something different, and better:

| | Pay as you go — $19/mo | Business — $129/mo |
|---|---|---|
| Posts included | **3,000 / month** | 50,000 / month |
| Overage | $0.007 to 10,000, then $0.005 | $0.005 |
| Account slots | **100 initial; _more free through support_** | 1,000 initial; more free through support |
| Keys | Managed + BYOK | Managed + BYOK |
| Reselling | *(not listed)* | **"Reselling explicitly permitted"** |

**§6.2c's $19→$129 cliff at 101 accounts is WRONG and is withdrawn.** Accounts are not a hard ceiling:
*"Additional accounts can be requested via support — no additional charge."* There is no step to plan
around, so the dip, the recovery curves and the "four times sooner" warning all describe a wall that is
not there.

**The real constraint is POSTS, and it is gentle.** At 60 posts/tenant/month:

| Tenants | Posts/mo | Publishing | % of $69 revenue |
|---|---|---|---|
| 50 | 3,000 | $19.00 | 0.55% |
| 100 | 6,000 | $40.00 | 0.58% |
| 200 | 12,000 | $78.00 | 0.57% |
| **370** | **22,200** | **$129.00** | **0.51%** |

Publishing sits near **half a percent of revenue at every scale**, and Pay-as-you-go stays cheaper than
Business until about **370 tenants**. §6.2's original arithmetic — *"~$40/mo total at 100 tenants,
publishing is <1% of a $69 tier"* — was right all along and is hereby un-struck.

**What §6.2c got right and keeps.** The `connected_accounts` allowance is still worth having, but its
JUSTIFICATION changes: not a cost cliff, a product promise. "3 accounts on this tier" is a tier
difference a buyer understands, and a per-tenant bound still protects the post budget, which is the thing
that actually costs money. The default of 3 (one per channel) stands.

### ⚠️ 6.2e THE RESALE CLAUSE SITS ON THE £129 TIER, NOT THE $19 ONE

**"Reselling explicitly permitted" is listed as a BUSINESS feature. Pay-as-you-go does not list it.**
The author holds written permission to resell on the $19 plan (§6.2b), which reads as an exception to the
published tiering rather than a restatement of it.

That is not a reason to doubt the letter — a vendor may grant exactly this, and the page is marketing
copy, which §6.2 already warns is not the terms. It IS a reason to treat the letter as the load-bearing
document it is: **keep it retrievable, and have the reply name the plan explicitly.** §6.2a's finding
stands unchanged — *"without that letter there is no Outstand path at all"* — and a permission that
contradicts the public page is one worth being able to produce on demand.

**Cheap follow-up, same thread as the enablement request:** ask them to confirm in writing that resale is
permitted on Pay-as-you-go for this account. One sentence from them closes the only remaining ambiguity
in the whole vendor question.

### 6.2f ✅ CONFIRMED BY THE VENDOR, AND THE SHAPE OF THAT CONFIRMATION (2026-11-06)

Outstand repeated by word what they had already put in email: **the key is approved for 100 accounts for
resale purposes.** That answers §6.2b's open follow-up — resale is permitted on this account at this tier
— and §11 Step 0 is closed. **Proceed** (author, 2026-11-06).

**What it is NOT: a contract.** There is no formal documentation, no addendum, no signed term. The
arrangement is, in the author's words, *"ask us and we'll approve you"* — a discretionary grant sitting on
top of published terms that do not describe it (§6.2e). Two consequences worth stating once, not
re-litigating:

- **The email IS the artifact.** §6.2b called the letter load-bearing and asked that it be retrievable;
  with no formal document behind it, that is now the whole paper trail. Keep it somewhere that survives an
  inbox clear-out, and prefer a copy that names the **plan** as well as the 100 accounts.
- **Discretionary means revocable.** Nothing here is breached if they change their mind; the grant simply
  ends. §6.2a's exit table is the plan for that day and does not change. This is a known, accepted risk
  taken knowingly — not an unexamined one.

**Instagram: a PROFESSIONAL account is required; a linked Facebook Page is NOT (vendor, 2026-11-06).**
A product requirement, not a vendor detail: it lands in onboarding copy. "Professional" is Instagram's own
switch (Creator or Business) and is free, so the ask is a settings change rather than a new account — but
a tenant on a personal account cannot connect at all, and discovering that at the connect step is the
worst place to discover it. Say it **before** the OAuth hand-off, with the two words Instagram itself uses.
This also narrows §11a #5: the IG path is one connection, with no Page connection implied.

### 6.2g SPIKE ANSWERS FROM THE PUBLISHED DOCS (2026-11-06) — three closed, two new constraints

Read from `outstand.so/docs` and `/docs/configurations`, now that the account is open. §11a numbering.

**#2 — `publish()` does NOT return a live URL. §6.1's contract was wrong and must change shape.**
`POST /v1/posts/` returns `post.id` plus, per connected account, `status` (`pending|published|failed|deleted`),
`platformPostId`, `error` and `publishedAt`. So the external id is there and **the live URL is not**. The
adapter contract cannot promise `live_url`; a permalink has to be composed per network from
`platformPostId` + the account's `username`, or dropped. This is exactly the reason #2 was ranked second —
it is cheaper to learn now than to find every caller assuming a URL that never arrives.

**#4 — native scheduling EXISTS.** `scheduledAt` (ISO 8601) on the same endpoint, **capped at 30 days
ahead**; omitted or in the past publishes immediately. §7's 15-minute sweep is therefore a choice, not a
necessity — but the 30-day ceiling means the sweep still owns anything further out, so §7 stays.

**#7 — media limits are NOT documented.** The only stated figure is that confirmed uploads are retained
**60 days**. No size, length, codec or carousel limits on either page, so the ceiling
`HIGGSFIELD_INTEGRATION.md` must generate within is still unknown and remains a live-call question.
Upload is a three-step presigned flow: `POST /v1/media/upload` → `PUT` the bytes → `POST
/v1/media/{id}/confirm`.

**⚠️ NEW CONSTRAINT — Managed Keys cover only 8 of the 12 networks.** **X (Twitter), Google Business
Profile, Vimeo and Reddit are BYOK-ONLY**: Outstand ships no managed OAuth app for them, so the TENANT
must register their own developer application before connecting. That is not a settings change, it is a
developer-portal application — far past what an SMB will do. Treat those four as **not available at
launch** rather than as a connect button that strands people, and size the product on the eight that work:
LinkedIn, Instagram, Facebook, Threads, Bluesky, YouTube, Pinterest, TikTok. Two more notes from the same
page: **Bluesky uses an app password, not OAuth**, and **TikTok Direct Post requires passing TikTok's own
Content Posting API audit** — a third-party review on the critical path for that one network.

**✅ Instagram corroborated.** The docs say "Business and Creator accounts", and list "connected business
or creator account (not personal accounts)" as a general prerequisite — matching what the vendor told the
author on 2026-11-06 (§6.2f). Two independent sources now agree, so the onboarding copy can state it
plainly.

### 6.2h ⚠️ THE PUBLIC PAGE NOW CONTRADICTS THE GRANT IN BOTH DIRECTIONS (2026-11-06)

§6.2e warned the marketing page was not the terms. Read today it disagrees with the vendor's email twice:

| | Public pricing page (2026-11-06) | What the vendor granted |
|---|---|---|
| Reselling | listed as a **Business ($129/mo)** inclusion; **not** listed under Pay as you go | permitted on this key at **$19** |
| Connected accounts | Pay as you go: **"No cap"**; Business: 1,000 slots to start | **100 accounts** |

Both differences are survivable and neither is new in kind — but together they make §6.2b's ask concrete
and raise its priority: **the email must name the plan.** "Approved for 100 accounts for resale" is
ambiguous against a page that sells reselling one tier up; "approved for reselling on Pay as you go, 100
accounts" is not. That is one sentence from them, and it is the difference between a grant that can be
produced on demand and one that reads as a misunderstanding. Ask in the thread that already exists.

### 6.2c The account ladder, answered (2026-11-05) — ⚠️ SUPERSEDED BY §6.2d, kept as the record of a
### cliff that turned out not to exist

**$19/mo up to 100 accounts; $129/mo ("Business") at 101 and above.** A hard step, not an overage — the
101st account costs $110/mo, the 102nd through however-far-Business-reaches cost nothing.

**The step is small and self-absorbing.** At $69/tenant it takes **two tenants** to pay for the crossing
($110 ÷ $69 = 1.6), and the tenant that triggers it is net −$41 for one month. That is a dip, not a wall.

**What decides when the dip arrives is PROFILES PER TENANT, and that is a product lever we control:**

| Profiles/tenant | $19 covers | Peak publishing cost, at the crossing | At 2× that many tenants |
|---|---|---|---|
| 1 (IG only) | **100 tenants** | 1.85% of revenue | 0.93% |
| 2 | 50 tenants | 3.67% | 1.87% |
| 3 | 33 tenants | 5.50% | 2.83% |
| 4 | 25 tenants | **7.19%** | 3.74% |

Letting every tenant connect four profiles brings the cliff forward **four times sooner** and makes it
**four times more painful** at the moment it lands. Publishing never threatens the business — worst case
7.2%, improving immediately after — but the difference between 1 and 4 profiles is the difference between
a rounding error and a line somebody has to explain.

**✅ BUILT 2026-11-05 (the number; enforcement lands with the connect flow).**
`stripe-link` `domain/account_quota.py` resolves it, `plan_connected_accounts` reads it off the plan
row's generic `limits` map (a Pricing-screen edit, no deploy — a cost dial that needs a deploy is one
nobody turns), the billing webhook denormalizes it onto the tenant, and it appears on the plan cards so a
buyer sees the number before meeting it. **Default 3: one per supported channel** (`../attention`
`domain/channels.py`), which puts the vendor cliff at ~33 tenants as a chosen number rather than an
accident. `may_connect()` is the gate the connect flow will call — asked BEFORE the OAuth round trip,
because a tenant who authorises Instagram and is then refused has given a third party access for nothing.

**One asymmetry worth knowing**, pinned by a test: on cancellation `sites` drops to the FREE FLOOR (a
storefront survives a lapse) while `connected_accounts` drops to ZERO (vendor capacity does not). Getting
that backwards either takes a lapsed tenant's shop offline or keeps billing us for someone who stopped
paying.

**So connected profiles should be a PLAN ALLOWANCE, not an unlimited.** This is the same shape as the
Site cap (`SITE_AS_BUSINESS_IDENTITY.md` §P5, shipped 2026-11-05) and should reuse its machinery rather
than inventing a second one: a `connected_accounts` entry in the plan row's generic `limits` map,
denormalized onto the tenant by the billing webhook, resolved by a pure function, enforced at connect
time with the number shown BEFORE it bites. §P5 already proved every part of that path.

It also gives the tier ladder something to sell: *"1 profile on the lower rung, 3 on the top"* is a real
difference a buyer understands, and it keeps our own cost curve where we chose to put it.

**Still open:** does Business cap accounts too, and does it raise the 3,000-post base? One more email,
same reasoning as §6.2a — the answer changes nothing above but it decides whether there is a THIRD cliff
waiting, and that is worth knowing before the spike prices anything.

### 6.2a ⚠️ RESALE NEEDS THEIR WRITTEN PERMISSION — the gate nobody priced (author, 2026-11-03)

Two findings from the author reading Outstand's actual terms, and both narrow §6.2's claim rather than
confirming it:

1. **Resale is permitted only with their WRITTEN PERMISSION** under the $19 plan. The author has requested
   it; **it is not granted.** Reselling an aggregator's publishing to tenants is exactly what this plan
   does, so without that letter there is no Outstand path at all — not a worse one, none.
2. **The $19 plan grants DEVELOPER ACCESS only.** So the arithmetic above is probably priced off the wrong
   tier: "first ~50 tenants inside the $19 base" assumed a production allowance. Until the permission reply
   names the tier resale actually runs on, treat **every figure in §6.2 as a developer-tier quote**, and
   the "<1% of a $69 tier" conclusion as unsupported.

**This changes the ORDER of §11.** The spike was going to validate pricing, embedding rights and failure
behaviour. Paying for a week of testing a vendor who may not permit resale spends money to learn something
the permission reply answers for free. **Get the written permission first; spike second.**

**What it costs if they refuse.** The §6.1 adapter contract is unaffected — that is what it is insurance
for, and the reason it was built before any vendor was chosen. What is affected is the LAUNCH PATH, and
there are only three options left, all worse:

| If Outstand refuses | Consequence |
|---|---|
| Ayrshare | The same questions over again, including its own resale clause. Unverified in exactly the way Outstand was. |
| Own Meta/TikTok/YouTube apps | §6.2's whole premise is that app review is weeks-to-months and the author "is not positioned to do now". Refusal does not change that. |
| Ship A4 only | Export the calendar, tenant posts by hand. Already built and already working — this is the honest floor, not a failure state. |

That last row is worth saying plainly: **A5 is the only phase with a third-party veto on it, and A4 already
delivers a usable product without it.** A tenant with a dated plan and a CSV is not blocked on anyone's
written permission.

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
| **A1 — Context** | ✅ **DEPLOYED dev + prod** (`jb-attention-stack-prod`, 2026-11-03; verified 2026-11-05). Dev carries real rows; prod is deployed and empty |
| **A2 — Attribution** | `?src=` slugs, click ingestion, checkout attribution, per-post/per-pillar GMV *(early — see §8)* |
| **A3 — Campaign engine** | ✅ **SHIPPED dev 2026-11-02** — intensity-aware plan, batch-written queue |
| **A4 — Calendar UI** | ✅ **dev 2026-11-02** — dated table, skip/restore, move, CSV + clipboard export. **Drag deferred** |
| **A5 — Publishing** | 🟡 **UNBLOCKED 2026-11-05** — resale permission granted (§6.2b). Remaining gate is §11's unrun paid spike — adapter + reconnection + 15-min sweep |
| **A6 — BYOK migration** | ⛔ **BLOCKED on Meta/TikTok/YouTube app review** (§6.2: weeks-to-months) and on A5 |
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

### Finished copy — generation runs in `stripe-link` (author decision 2026-11-02)

`operation: "generate_copy"` on `stripe-link`'s existing `POST /ai/generate`, the third operation folded
onto that route. **Not in `../sam/attention`**, and the reason is the comment already written above
`_enrich_offer`: that function owns the provider adapter, the BYOK configuration and the usage counter, so
generating anywhere else means a second service re-reaching all three — including, once BYOK generation is
wired, decrypt on every tenant's provider key. It also costs no route budget, against a guard at 225/240.

The division of labour holds §2 and §3 intact. **Attention decides what a post is about** — pillar, goal,
instruction, anchor, hooks, native format; that is §3's "five-pillar prompt templates" and it stays there.
`domain/attention_copy.py` only composes those given fields into a prompt, and a test asserts it names no
pillar: add a pillar in Attention and that module does not change.

**The brief arrives via a browser, so it is input, not instruction.** The prompt is assembled field by
named field, every field whitespace-collapsed and length-capped, so a crafted brief cannot append an
instruction of unbounded length or introduce a field the module does not name. The schema carries **no
`maxItems`** — Bedrock rejects it and the failure is silent — so lengths are clamped in Python instead.
`for_page=True`: a social post is published copy, so §A.7's floor applies as it does to a landing page.

**The ledger rule is `enrich`'s**: debit first, refund anything that did not produce copy — a provider
failure, an empty answer, a carousel that came back without slides. Copy is generated **per angle, on
request**, because writing five posts a tenant wants one of would spend five generations on four they
discard, and the cost is stated before the click.

## 10b. A3 + A4 as built (2026-11-02)

**A3 — the campaign engine.** `domain/campaign.py`, two tables, deterministic and free. Three dimensions
advance at different rates so a month does not fall into a pattern: **pillar per post** (the §4 arc),
**channel per post** (so no platform gets the same pillar twice running), **anchor per lap** (so thirty
posts use thirty of the offer's own anchors, not one restated). A tenant who asks why there is a Mistakes
post on the 14th gets an answer.

Post ids are **derived** from the campaign, and the campaign id from offer+mode+day, so pressing the
button twice **re-plans rather than doubling the calendar** — verified against the real tables. A random
id would turn one dropped response into two campaigns' worth of posts in the queue.

Posts carry their whole brief, **copied at plan time**. The context is keyed on the model's content, so a
post that read through to it would rewrite itself when the offer was re-analyzed. `predates_the_offer`
reports that instead, and treats an unknown key as **not** stale — the opposite of the context cache's
rule, because there the cost of being wrong is invisible staleness and here it is nagging a tenant to
rebuild a plan that was fine.

**A4 — the calendar.** A dated table in the offer modal with skip/restore, ±1 day / ±1 week, clipboard and
**CSV download**. §10's "delivers value with zero publishing APIs", which is the point while A5 is gated.
`published` is deliberately **not settable** from a browser: that is A5's word, written by the sweep that
actually published something, and letting a client claim it would make the calendar lie about what went
out. **Drag-and-drop is deferred** — a lot of frontend for reordering something that can be re-planned.

Two bugs found here, one by a test and one by the real tables:

- **`channels: ["facebook"]` planned for all three platforms.** `known or CHANNELS` made the default
  truthy, so the unknown-channel guard never fired. A tenant who picked one platform would have got a
  month of posts on two they never chose.
- **Every number read back from DynamoDB is a `Decimal`,** and `json.dumps(default=str)` stringified it —
  so *create* answered `due_at` as a number while *the calendar* answered the same field as a string. One
  field, two types, depending on the route. Now encoded as a number.

⚠️ **Pre-existing gap, found while building A1's generation and not introduced by it:** nothing in the
generation path decrypts `ai_provider_config.api_key_ref`. The page, enrichment and copy operations all pass no
`api_key`, so a BYOK tenant admitted by `can_use_ai_builder` reaches `_byok_loop` with an empty key.
Everything today runs on the platform's own Bedrock access. The fix is one resolver all three call; it was
deliberately not papered over with a fourth private decrypt.

**Prod needs one write** that is not code: `environments.{dev,prod}.attention_api_base` in the prod
`app_config` document. Until then the prod dashboard shows no panel, which is the gate working.

## 11. Verify before A5 hardens

**Step 0 — ✅ DONE 2026-11-05: permission granted, $19 tier, 100 connected accounts (§6.2b).**
Originally: get the resale permission IN WRITING, and the tier it applies to. Outstand
permits resale only by written permission and the $19 plan is developer access only (§6.2a). A refusal ends
the Outstand path, so this is the cheapest question and it must be asked first — the spike below cannot
validate pricing for a tier the author is not allowed to resell on.

**VENDORS SETTLED 2026-11-05 (author).** Both, and no further evaluation: **Outstand** for publishing
(§6.2b permission granted) and **Higgsfield** for video (`HIGGSFIELD_INTEGRATION.md` §0). Ayrshare is no
longer a live alternative; §6.2a's fallback table stands only as the record of what refusal would have
cost. The spike below is now a VERIFICATION of a chosen vendor, not a selection between candidates.

Then run a **paid one-week spike**: one real IG account, publish a carousel and a video, then
**deliberately revoke the token mid-queue** and read the error. That single test validates pricing,
embedding rights, and — most importantly — the failure behavior the whole scheduling design depends on.
Vendor claims in §6.2 are unverified marketing until this passes.

### 11a. The spike checklist — what one paid week must answer

Ordered by what blocks the most work if the answer is bad. Each is cheap only while the account is
already open and paid for; every one of them becomes a second week if it is missed.

| # | Question | Why it blocks something |
|---|---|---|
| 1 | **Revoke a token mid-queue — what does the API return?** | §6.4 makes reconnection a first-class state rather than an error path. That design needs the actual status code and body, not a guess. |
| 2 | **Does `publish()` return `{external_post_id, live_url}` as §6.1 assumes?** | The adapter contract is the insurance. If the vendor returns neither, the contract changes shape before anything is built on it. |
| 3 | **Per-post METRICS: does the API return views / engagement / reach for a post we published?** | ⭐ **The one that upgrades a "Later" into a differentiator.** §8 already measures clicks→sales; platform metrics add views→clicks, which lets §10's performance-weighted pillar selection rank on real reach instead of conversion alone. Record granularity (per post? per profile?), latency (minutes? next day?), and whether it is a push or a poll. A **no** does not break anything — it means the view half needs per-platform analytics APIs, which lands in A6/BYOK and should be priced there, not assumed here. |
| 4 | **Is a post schedulable at the vendor, or must we hold the queue?** | §7 reuses the 15-min sweep rather than scheduling per post. If the vendor schedules natively the sweep gets simpler; if not, §7 is already right. |
| 5 | **Does one connected account count once, or once per platform?** | §6.2c's whole cost model is accounts-per-tenant. "100 accounts" means something different if IG+Reels is two. |
| 6 | **What does the 101st account actually do** — hard refuse, auto-upgrade, or silent overage? | §6.2c assumes a hard step at $129. An auto-upgrade that bills without asking is a different risk. |
| 7 | **Media limits**: max video length/size, accepted codecs, carousel count. | Decides what `HIGGSFIELD_INTEGRATION.md` may generate. Generating a clip the publisher refuses is the worst ordering available. |

**Record the answers in §6.2 and strike "not independently verified" from the claims that pass.** The
figures there have already moved once by 30× (§6.2b); the point of a paid week is to stop guessing.
