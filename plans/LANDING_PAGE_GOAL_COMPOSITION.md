# Landing Page Goal Composition (offer_type × goal)

## Why

The builder is heading toward supporting many page kinds (e-commerce, services, appointments, lead capture,
call, redirect) and many *non-visible* concerns (SEO structured data, LLMs.txt, accessibility, layout
stability). Showing every capability to every tenant is overwhelming, and most of it is irrelevant to any
one page: a page fed by paid ads wants speed and no SEO weight; a page chasing Google rankings wants the
opposite. So composition needs a **second axis beyond `offer_type`: the tenant's goal / traffic source.**

Benefits: it forces the tenant to think through intent, lets us optimize the page for that intent, and gives
a future **Build with AI** a precise brief (see below). This extends [[PAGE_COMPOSER]] — same composer,
one more input.

## The two axes

- **offer_type** (WHAT the page sells): single / bundle / listicle / service / appointment / lead / call /
  redirect. Already drives the base section allow-list.
- **goal** (WHY / where the traffic comes from): the optimization profile. Starter set (to refine):
  - **paid_ads** — fast & minimal; ad pixels on; SEO scaffolding off; smallest LCP.
  - **search_seo** — structured data, FAQ, content depth, LLMs.txt; semantic headings.
  - **social** — social proof + shareable OG/Twitter cards; lighter SEO.
  - **email_list** — warm audience; minimal friction, direct offer.
  - **minimal** — just the offer.

The **intersection picks the starting page.** The tenant can still override any section afterward (the
compact `composition.overrides` map from Phase 2 is unchanged).

## Composition model: base + packs (not a full matrix)

A full `offer_type × goal` matrix would be O(types×goals) hand-maintained entries. Instead the goal toggles
**capability packs** — named bundles of sections — on top of the offer_type base:

- `offer_types[type].sections` — the base visible sections (today's allow-list).
- `packs` — named bundles, each carrying a **channel** (see below): e.g. `discoverability`
  (structured_data, faq, llms_txt), `social_proof` (testimonials, ratings, marquee), `urgency` (countdown),
  `video` (vsl).
- `goals[goal].packs` — which packs are on by default for that goal (paid_ads → none; search_seo →
  discoverability; social → social_proof).

Default visibility = base sections ∪ sections from the goal's enabled packs. Tenant overrides still win.
Adding a new goal = one row; a new pack = one entry; renderers never change. This stays data-only in
`composition_rules.json` (the single source both Python and Vue already read).

## Three buckets — only one is a menu

1. **Quality baseline — automatic, never a toggle.** Accessibility (landmarks, alt text, focus order), a valid
   heading outline / semantic HTML (see plans/SEMANTIC_HTML.md), and layout stability (reserved image
   dimensions, no CLS) are renderer responsibilities, surfaced only as *warnings*, never as opt-ins.
2. **Core content — the offer.** Hero, price card, CTA; morphs by offer_type.
3. **Opt-in capabilities — the only real menu.** Packs + individual add-ons, defaulted by the goal.

## Elements have a *channel*

Each section declares where it renders: `body` (visible), `head` (meta / JSON-LD), or `sidecar`
(`/llms.txt`, sitemap). "Structured data" and "LLMs.txt" then become ordinary composed sections governed by
the same rules — they just don't paint pixels, and the builder tucks them into a collapsed **Discoverability**
drawer. Critically, **SEO/LLM output is derived, not hand-entered**: Product/Offer/FAQ/AggregateRating
JSON-LD and `/llms.txt` are generated from the offer + already-composed sections. "SEO" is a mode the goal
flips on, not a form. For service/local businesses this includes **LocalBusiness/Service + AggregateRating**
derived from a canonical Business Profile (NAP + GBP + reviews) — see plans/BUSINESS_PROFILE_AND_GBP.md.

## Wizard change

Extend the existing 3-step create wizard (Choose Offer → Preset → Review) with a **Goal** step:

1. **Choose Offer** → implies `offer_type`.
2. **Goal** (new) → "Where will this page's traffic come from?" with the goal options + a one-line note on
   what each optimizes. Presets the composition + packs.
3. **Preset** (visual theme) — unchanged.
4. **Review** — shows offer_type + goal + the resulting section list before opening the builder.

The builder then opens pre-composed and lean; packs/add-ons and the Advanced/Discoverability drawer are
available but out of the way.

## Data model

- Page stores `goal` (string) alongside `offer_id` and `theme`.
- `composition.overrides` (Phase 2) unchanged — still the tenant's deviations.
- Composer inputs become `(offer_type, goal, overrides)`; `compose_page` unions base + goal packs, then
  applies overrides. Missing `goal` → a safe default (e.g. `minimal` or `paid_ads`) so old pages still compose.

## Build with AI hook

`offer_type + goal + offer data` is exactly the brief an AI page-builder needs:

- The **composer produces the scaffold** (which sections, which channels) — the AI never invents structure,
  it fills a known shape, so output is always schema-valid (ties to [[project_ai_commerce_direction]]).
- The **goal constrains the AI**: a paid_ads brief won't get a 1,500-word SEO article; a search_seo brief
  gets FAQ + structured data. The profile is the guardrail that keeps AI output on-intent and un-bloated.
- SEO/LLM fields are derived, so the AI writes *copy and section choices*, not JSON-LD by hand.

## Phasing

1. Add `goal` to the create wizard + persist on the page; composer accepts it (single default pack mapping).
2. Introduce `packs` + `goals` in `composition_rules.json`; `compose_page` unions base + packs.
3. Add the `channel` concept; move structured_data / llms_txt to derived `head`/`sidecar` sections + the
   Discoverability drawer.
4. Quality-baseline warnings (a11y/CLS) as a page-health checklist.
5. Feed the composed scaffold to Build with AI.

## Status — Phase 3a shipped (head channel + structured data)

`channel` is now enforced: `body` sections render into `<main>`, `head` into `<head>`. **structured_data** is
the first head section — governed, in no offer_type base, granted only by the `discoverability` pack. So
`search_seo` finally composes differently from `paid_ads`, and the pack `sections` half is live.

The JSON-LD is **derived, never entered**: `Product` + `AggregateOffer` from `landing_page_offer_prices()`
(the same filter the price cards paint, because Google requires markup to match visible content), and
`FAQPage` from the composed faq section through the same title-casing `render_faq` applies.

**Never emitted** (both pinned by tests): `AggregateRating` — the rating element is a hand-typed number with
no verifiable source, so marking it up would be fabricated review data (Google policy + the FTC rule on
deceptive ratings); and `LocalBusiness`/`Service`, which needs the Business Profile's NAP.

Also landed: the builder gained a **Page Goal selector** (goal was create-only, so Phase 3 could never have
reached an existing page — changing it re-composes governed sections but never re-seeds content, which stays
the tenant's), `seo_title`'s channel was corrected from `head` to `body` (it renders a visible `<p>`), and
`SUPPORTED_PAGE_SECTION_TYPES` now derives from the element catalog instead of duplicating it.

**Discoverability drawer — shipped.** Non-visible (`head`/`sidecar`) sections get their own collapsed drawer
in the builder instead of sitting in Page Sections next to visible toggles. It shows *what will be emitted*
(mirroring `render_structured_data`'s conditions) and surfaces **structured-data health warnings** returned
by `/pages/render` — thin markup (no image, no description, no category, unset condition, no SKU) is flagged
as a nudge, never a publish gate. Product richness landed too: single `Offer` at the displayed price (not an
AggregateOffer range), numeric price, product name (not the offer headline), 1920px image, humanized
category, `sku` (auto-generated, stable) and `itemCondition` (stated, never assumed) — verified passing
Google's Rich Results Test.

**Phase 3 remainder:** the sidecar channel + `llms_txt` (blocked, see below).

**Phase 4 — quality-baseline warnings — STARTED (heading outline shipped).** The `warnings.page_health`
channel is live: `/pages/render` returns it and the builder shows it in an always-visible "Page health"
banner. The first check is the **heading-outline validator** (`heading_outline_warnings`, plans/SEMANTIC_HTML.md
Slice 2): one `<h1>`, no empty/skipped levels, `<head>` ignored. Still open in this phase: **accessibility**
(images missing `alt`, missing landmarks) and **layout stability** (images without reserved dimensions / CLS)
— both plug into the same `page_health` channel. The prior text below is retained for the fuller picture.

**Phase 4 (original note) — NOT built.** The plan's "three buckets" (line 45) call for a quality
baseline surfaced as *warnings, never toggles*: accessibility (landmarks, alt text, focus order), a valid
heading outline / semantic HTML (plans/SEMANTIC_HTML.md — one H1, ordered H2/H3, publish-time outline
validator), and layout stability (reserved image dimensions, no CLS). The structured-data warnings shipped in
Phase 3a are the *first* member of this checklist; the a11y / heading-outline / CLS checks are still open.
This is the clearest unblocked next step in this plan, and it overlaps with plans/SEMANTIC_HTML.md's
publish-time outline validator.

**Phase 5 — Build with AI — NOT built** (its own plan, [[AI_AND_COMMERCE_ARCHITECTURE]]). The scaffold this
phase produces is the brief AI fills.

**Blocked on plans/BUSINESS_PROFILE_AND_GBP.md:** `LocalBusiness` / `Service` + `AggregateRating` JSON-LD.
Phase 3a deliberately omits both — AggregateRating because the rating element is a hand-typed number with no
verifiable source, LocalBusiness because it needs a canonical NAP. Business Profile P1 unblocks both.

### llms.txt is blocked on something owning a domain root (found 2026-07-17)

The plan lists `sidecar` as a per-section channel writing `/llms.txt`. That does not work yet, and the reason
is worth recording rather than rediscovering:

**llms.txt is a domain-root convention** (llmstxt.org) — `https://example.com/llms.txt`, like `robots.txt`.
Nothing requests it anywhere else. But pages publish to `{pages_domain}/{page_id}/index.html`, so a per-page
sidecar lands at `/{page_id}/llms.txt`, a path no client will ever ask for. The real root — `/llms.txt` on
the shared pages distribution — serves every tenant's pages, so no one tenant can own it.

The entity that *would* own a root is **`Site`** (`schemas/Site.schema.json`: `domain.hostname`, a slug-keyed
`pages` map, `seo_defaults`) — but it is **schema-only**; nothing in `src/` references `site_id` and the Sites
screen is disabled. The other candidate is a **custom domain**, which `handlers/custom_domains.py` already
maps to a single page (`target_page_id`, `target_type: "landing_page"`) — a domain whose root *is* one landing
page makes `/llms.txt` correct. There are currently no live custom domains to build against.

So `llms_txt` waits on whichever lands first (Site, or custom domains in real use). Until then it would emit a
correct file at a URL nothing reads. The mechanical work it needs is unchanged and small: `artifact_targets`
gains a second artifact per page, and `publish_page_document` — which today writes one `html` body with
`text/html` to every target — needs per-target body + content-type.

## Status — Phases 1 + 2 shipped

`goal` is a first-class page field, the wizard asks for it, and the composer takes it as a second input.

- **Rules** (`composition_rules.json`): `goals` (label + note + packs) and `packs`. Goals are data — adding
  one is a row, and it surfaces in the wizard, the composer, the validator, and the JSON schema for free.
- **A pack has two halves**, because the two kinds of section behave differently:
  - `seeds` — content-bearing body elements (faq, testimonials, rating, client_marquee). These render
    nothing until a tenant fills them in, so a flag can't summon them: the create wizard **seeds empty
    scaffolds into builder state**, and they are tenant-owned from that moment. Changing goal later never
    deletes copy someone wrote. They go into builder state, *not* the draft document — an empty FAQ is not a
    valid page section (`items` need answers), and `builderSections()` drops still-empty elements on save.
  - `sections` — governed sections the goal turns on, unioned over the offer_type base. This is the right
    home for **derived** `head`/`sidecar` output (structured_data, llms_txt) that needs no tenant input.
    **Empty today**: the mechanism is wired and tested-inert so Phase 3 slots in with no renderer change.
- **Union-only, so no migration.** A page with no `goal` composes exactly as it did before goals existed.
  Tests pin this: no goal can remove a base section, and `recommended_section_keys(type, goal)` is currently
  identical for every goal. Verified on dev — the same page rendered with no goal, `search_seo`, and
  `minimal` produced byte-identical HTML (same SHA).
- **One enum, one source.** `SUPPORTED_PAGE_GOALS` is read from the rules file, so the goals a page may
  store cannot drift from the goals the composer understands. Python and Vue were checked to return
  identical packs/seeds for every goal plus the `""`/unknown cases.
- Also fixed in passing: `Page.schema.json` never declared `composition` despite `additionalProperties:
  false`, so it had been rejecting documents the builder actually writes.

**Known and intentional:** `paid_ads`, `email_list`, and `minimal` are section-identical right now — they
enable no packs. Their real divergence (SEO scaffolding off, ad pixels, LCP budget) arrives with Phase 3.
The five names ship now so the vocabulary is stable for Build with AI.

## Open decisions

- ~~Final **goal list** and names~~ — shipped the starter five: paid_ads, search_seo, social, email_list,
  minimal.
- ~~Exact **pack contents**~~ — `discoverability` seeds faq; `social_proof` seeds testimonials + rating +
  client_marquee. `urgency`/`video` deferred: countdown is driven by its own builder toggle rather than an
  element, and there is no vsl element yet.
- ~~Whether **VSL/minimal** are goals or style choices~~ — minimal is a goal; video stays a pack for when a
  vsl element exists.
- ~~Default `goal` for pages created before this exists~~ — none. Absent `goal` is a first-class state
  meaning "base only", which is precisely the old behaviour; nothing is backfilled.
- Still open: whether a goal should ever be able to **remove** a base section (a `hides` list). **Raised and
  deliberately deferred (2026-07-16)** — union-only stands for now; revisit once Phase 3 gives goals real
  teeth. The consequence is worth stating plainly: **a goal can only add.** `trust_badges`, `refund_policy`
  and `brand_label` come from the offer_type base, so *no* goal can strip them — `minimal` renders the same
  chrome as `search_seo`. The goal notes were reworded to promise addition, not subtraction, so the wizard
  stops implying otherwise. Two candidate fixes when we return: a `hides` list on goals (small composer
  change, still backward compatible since a no-goal page has no hides), or trimming the offer_type base to a
  lean core and adding chrome back via packs (purer, but it changes defaults for existing no-goal pages and
  needs a migration or a legacy base).

## Not configurable at runtime (known)

Goals are **data, but not self-service**. `composition_rules.json` ships *with the code*: Python reads it off
disk in the Lambda bundle (`CodeUri: src/`) and Vue **inlines it at build time** (`import rules from
"../../../src/stripe_link/composition_rules.json"`). There is no config table and no admin UI, so changing a
goal means editing the file and running both `deploy.sh` and `deploy-dashboard.sh`. Making it truly
tenant-configurable is a separate project: the rules would have to move to a store both renderers read at
runtime, which means the Vue side fetches them instead of inlining — losing the compile-time guarantee that
the two composers read the identical bytes. That guarantee is the reason preview and published can't drift,
so it should not be traded away casually.
