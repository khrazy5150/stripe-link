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
- Still open: whether a goal should ever be able to **remove** a base section (a `hides` list). The plan is
  union-only on purpose, but it means lean goals can't actually strip trust badges / refund policy. Revisit
  once Phase 3 gives goals real teeth.
