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

## Open decisions

- Final **goal list** and names (starter set above).
- Exact **pack contents** and which packs each goal enables.
- Whether **VSL/minimal** are goals or style choices layered on any goal (leaning: video is a *pack*, minimal
  is a *goal*).
- Default `goal` for pages created before this exists.
