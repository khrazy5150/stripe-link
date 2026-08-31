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

## 5. What this replaces

- **Remove** the drag handles on form blocks (`e5428e3`) — they are the ghost drag.
- **Retire** the separate Section order list (`4f1fe07`) once the form itself is the map. Keep it until
  then; it is currently the only complete view.
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
