# Builder section order — the form IS the page map

Status: PLANNED, not built. Designed 2026-08-30 with the author.
Related: `PAGE_COMPOSER.md` (§ Cardinality, composition), `LANDING_PAGE_GOAL_COMPOSITION.md`,
`SEMANTIC_HTML.md`, `FORM_BUILDER.md`, `SOCIAL_MEDIA_PAGES.md`.

---

## 1. The invariant this exists to create

> **The builder form reads top-to-bottom in the same order the page renders.**

stripe-cart had this and it is why its builder is legible: you never need a separate map, because the
form IS the map. stripe-link does not have it, and every attempt to bolt ordering on without it has
failed in a different way:

| Attempt | Why it failed |
|---|---|
| Section order list (`4f1fe07`) | Correct, complete, and **invisible** — the author looked for it twice and boxed the wrong control both times |
| Drag handles on form blocks (`e5428e3`) | A **ghost drag**: the page reordered, the dragged block did not move. Feedback appeared somewhere other than where the gesture happened |

Both shipped and both are wrong. This plan replaces them.

## 2. Three groups — NOT two

The author's first cut put favicon, theme preset and advanced colours in a "fixed" array beside the
hero, to keep a clean runway for the draggable ones. Right instinct, wrong bucket: those are not
sections at all. A favicon renders in a browser tab; a preset colours everything. Group them with the
hero and someone eventually asks why the theme preset cannot be dragged — and the honest answer is not
"it is pinned", it is "it is not a thing on the page".

| Group | Definition | Members |
|---|---|---|
| **Settings** | Not a page section. No position. | favicon, theme preset, advanced colour settings, SEO, analytics, sale & flash, post-checkout flow, page basics |
| **Fixed sections** | Renders at a position the tenant may not change | countdown (`lead`), hero media + H1 (`pinned_top`), footer (`pinned_bottom`) |
| **Draggable** | Tenant-ordered. Index 0 = first section after the hero. | everything else, INCLUDING the element cards (testimonials, FAQ, content blocks, rating, client logos, related products, product details) |

This maps exactly onto the `placement` bands already shipped in `composition_rules.json` (`6f2676d`).
No new vocabulary; Settings are simply the blocks with no element key, plus `channel: head`.

**Why the fixed ones are fixed:**
- **Hero / H1** — it is the LCP element (the renderer emits preload/priority hints for it) and one-H1-first
  is an invariant the semantic outline depends on.
- **Countdown** — real pages put it at the top or the bottom, never the middle. A free drag would only
  let a tenant build something wrong.
- **Footer** — legal links below the fold is the one universal convention.

## 3. Form restructure

Today the settings blocks sit *interleaved* with the section blocks, which is a large part of why the
order is impossible to see. Split the form:

```
[ PAGE CONTENT ]           <- one ordered sequence, page order, drag here
    countdown              (fixed, locked)
    hero media + headline  (fixed, locked)
    ...draggable sections and element cards, in order...
    footer                 (fixed, locked)

[ SETTINGS ]               <- everything with no position on the page
    page basics, SEO, theme, advanced colours, analytics, sale & flash, post-checkout
```

The element cards are ALREADY an ordered draggable list in the form — that half exists. The work is
folding the fixed-position section editors into that same list so there is one sequence, then moving the
settings blocks out from between them.

**Clear section boundaries** — the author's improvement on cart, and the reason cart's long pages became
a wall. Each entry in the content sequence is a card with a header carrying its drag handle and name, so
the sequence scans as discrete units rather than continuous form. Locked entries show the boundary and
the name but no handle.

## 4. The list is built per page type — it already is

`composition_rules.json` keys sections by `offer_type`, and Goal Composition adds `goals` + `packs`. So
"which sections exist" is already dynamic; what is missing is that nobody has built the lead-gen shapes.
Lead pages will want very different content from transaction pages, and the quiz/multi-step form
(`FORM_BUILDER.md` §4a) may want no hero at all.

**A page with no hero already works.** The bands are POSITIONS, not requirements — `pinned_top` simply
being empty for that composition is fine.

But it changes how the H1 rule must be phrased:

> **The first `pinned_top` section carries the H1 and is the LCP element.**

NOT "the hero does". Otherwise a heroless quiz page has no defined H1 owner and `SEMANTIC_HTML.md`'s
outline has nothing to anchor to.

### Open question — does `placement` need to vary per page type?

Today it is a global property of the element. Existence already varies by composition, which covers most
cases. But one could imagine the form being `pinned_top` on a quiz page, since it IS the page.

**Recommendation: keep placement global for now.** Add a per-composition override only when a real case
appears, rather than building the generality first — an override map is easy to add later and impossible
to remove once tenants depend on it.

## 4a. The BASELINE order — a researched default, not cart's

> **STATUS: SHIPPED.** `default_order` in `composition_rules.json`, read by `composition.baseline_order()`
> and `pageComposer.baselineOrder()`. Existing pages are untouched — their order is derived from saved
> `page.sections`, so a stored order always wins; the baseline only decides pages nobody has reordered.
> Per-goal overrides (`goals.<goal>.default_order`) are supported but none are defined: varying the order
> per goal without evidence would be guessing, and the calibration note below says so.


Tenants should not have to reorder anything to get a good page. Today the default is:

    hero -> trust_badges -> [all elements, in INSERTION order] -> price -> CTA -> refund -> footer

Two problems. **Trust badges sit a screen away from the CTA** — trust seals work by reducing friction at
the moment of commitment (Baymard's checkout-seal research is the usual citation), so they belong beside
the price/CTA cluster. And **there is no default order among elements at all**: a tenant who adds FAQ
before testimonials gets FAQ first, permanently. That is the biggest gap, because elements are what
tenants add most.

Proposed baseline (transaction, neutral traffic):

    countdown · brand_label · hero_media · hero
    product_details -> rating -> testimonials -> content_block -> client_marquee -> faq
    trust_badges -> offer_price_selector -> checkout_cta -> refund_policy
    related_products · legal_footer

The element run follows the visitor's actual questions: *what is it* -> *is it any good* -> *who says so*
-> *tell me more* -> *who else uses it* -> *but what about...*

**Deliberately NOT moving price/CTA above the fold.** Tempting, and right for warm traffic — but
`checkout_cta` is non-repeatable, so there is exactly ONE ask. A single ask belongs after the persuasion.
Moving it up without adding a second CTA at the bottom would be strictly worse. Revisit if a repeat CTA
is ever added.

### Calibration — what is actually established

Well supported: value proposition above the fold; trust signals adjacent to the action; risk reversal at
the moment of the ask; objections answered before the final ask. **Contested and A/B-dependent:** nearly
everything else, especially price placement, which swings on traffic temperature and price point. Treat
this baseline as a good default, not a law, which is exactly why every section stays draggable.

### Where the baseline lives: goal, not a new field

`page.goal` already exists with five values, and their own notes already encode traffic temperature:
`paid_ads` ("converts fast or bounces"), `email_list` ("a warm audience... straight to the offer"),
`social`, `search_seo`, `minimal`. Packs currently only ADD sections; they should also be able to ORDER
them.

Implementation: a `default_order` list per `offer_type`, with per-goal overrides, in
`composition_rules.json` — the same file both renderers already read. No new document field, no new
concept.

**Goal stays on the PAGE. Do NOT add it to the Offer.** The same offer legitimately has a cold-ads page
and a bio-link page, with different orders and identical product data. Storing goal on the offer makes
those two pages unable to differ, and creates two fields meaning the same thing that must agree — the
failure shape logged in `TODO.md` § silent agreement failures.

**When goal is unset, DERIVE rather than store.** The inputs are already on the offer the page
references: `product_intent` (lead_gen wants a wholly different sequence), price point (high-ticket earns
more proof before the ask), service vs product. A derived default costs nothing and cannot drift; a
stored copy can.

## 5. What this replaces — DONE

- **Removed** the drag handles on form blocks (`e5428e3`) — the ghost drag. Superseded when the blocks
  moved into the sequence (`04ad2e8`).
- **Retired** the separate Section order list (`4f1fe07`). The form is the map now, and a second view of
  the same thing only drifts.
- **KEPT: the Page Sections checkboxes.** Not redundant with the sequence, for two reasons. They are the
  only surface that shows sections which are currently OFF — the sequence renders only what is on, so
  without the roster a disabled section would be unreachable, the same dead end as an emptied
  trust-badges block. And a compact list of booleans is the right target for bulk and programmatic
  edits: AI page-generation can flip a set of sections declaratively instead of walking a spatial drag
  sequence item by item. Correct placement falls out of the three-group model — "which sections exist"
  is configuration and sits below the Settings divider; "what order they are in" is content and sits
  above it.
- **Keep** `placement` in `composition_rules.json` and `order_section_keys` / `orderSections` — the
  ordering model is right, only its surface is wrong.
- **Keep** deriving order from `page.sections` rather than storing a parallel array. No schema change.

## 6. Risks

- **It reshapes the screen the author uses most.** Ship to sandbox and let them live in it before prod.
- **Each fixed-position editor must become addressable by key** and render inside a `v-for` instead of a
  fixed spot in the template. That is the bulk of the work and the main regression risk — the blocks
  carry a lot of existing behaviour.
- **Settings need a home that is not a dumping ground.** A collapsed group or a second tab; decide when
  building, with the content sequence as the default view.


---

# Phase 2 — compact rows + modal editing

Status: PLANNED, not built. Agreed 2026-08-30, after Phase 1 shipped to sandbox.

## Why Phase 1 is not the end state

Phase 1 made the form read in page order, which was the goal. But the rows are EXPANDED editors, and that
has two costs:

1. **A long page is metres of form.** Ten sections is ten full editors — accurate, but not scannable. The
   map property is weakened by the same thing that gave cart's builder its wall-of-form problem.
2. **Tall cards cannot be dragged.** A testimonials section with 20 items is a ~2000px card. Dragging it
   means scrolling mid-gesture, which in practice means the drag does not work at all. This is the
   decisive argument: compact rows are not a tidiness preference, they are what makes reordering
   physically possible.

The Section order list retired in `b51078e` had the right FORM FACTOR — short rows — and the wrong
architecture: it was a second surface beside inline editors, so the two could disagree. Compact rows with
modal editing is that same form factor with the duplication removed.

## The model

    ⠿  Testimonials            3 quotes            Edit   Remove
    ⠿  Price cards             from the offer
    ⠿  FAQ                     2 questions         Edit   Remove
    🔒 Footer                  generated

- Each row: handle, name, a one-line summary of its contents, Edit, Remove.
- **Editing happens in a modal, and ONLY in a modal.** One surface. No inline/modal split — two places
  to edit the same thing is the drift shape this codebase keeps hitting.
- **Adding opens the same modal empty**, with an "Add Section" button. Cancel creates nothing.

## Commit semantics — ADD commits, EDIT is live

- **Adding** opens the modal on a DRAFT that does not exist in the document yet. "Add Section" commits
  it; Cancel discards it and nothing was created.
- **Editing** an existing section writes through live, exactly as the inline editors do today, so the
  preview keeps updating as the tenant types. Closing is just closing.

Deliberately not symmetrical. Live editing is what makes the preview useful, and a modal that batched
changes until "Save" would make the preview stale for as long as it is open — the thing tenants rely on
most while composing.

## Consequences worth stating

- **No more empty cards.** A section exists only once the tenant confirms it, which supersedes the
  builder.elements-sourced rows added in `6ce24e1` — that fix existed to make empty elements visible, and
  empty elements stop existing.
- **Applies to the fixed-position sections too** — Trust Badges, Refund Policy, Call to Action edit
  inline today. Leaving them inline while elements go modal would rebuild the mixed model this is meant
  to remove.
- **The summary line carries real weight.** "3 quotes" / "2 questions" / "from the offer" is what makes a
  collapsed row worth scanning; without it the map is a list of type names.
- **Cost: every edit is a click away.** Real, and accepted — at-a-glance editing is what makes the
  sequence unscannable and undraggable.

## Open

- ~~Do the pinned sections also move to modal editing?~~ **DECIDED 2026-08-30: yes, Countdown and Hero
  go modal too.** Not merely for consistency — they are the two with the MOST to configure. Countdown
  already has several independent settings (duration, start/end copy, start/end icons, per-state
  toggles), and Hero is due more: whether the H1 sits inside the hero image to save space, and where in
  the image it sits (centre, lower-left, upper-right…), which is adjacent to the positionable brand
  overlay in `SOCIALITE_PARITY.md`. Both are exactly the kind of multi-option editing a cramped inline
  card handles badly and a modal handles well.
- Automatic PLACEMENT by type ("an FAQ belongs near the bottom") only becomes meaningful once §4a's
  baseline order exists — that is what defines where a type belongs. Until then: new sections land at the
  end of the run, and the tenant drags.
