# List virtualization — the decision before the code

**Status:** NOT built. Blocked on a UX decision, not on effort. Prerequisites are done.

## What is already in place

- All four list screens filter through `composables/indexedList.js` (2026-09-02), so this lands ONCE.
- `ListCard` clamps title and description, so **rows are uniform height per list** — which is what makes
  fixed-height windowing possible instead of measuring virtualization with an offset map.
- Payload is already solved by the slim indexes. This is purely a RENDER-cost problem.

## The blocker

**No list has its own scroll container.** `.product-card-list` is a plain grid with no `overflow` and no
`max-height`, so the page scrolls, not the list. Every simple virtualization recipe assumes a scrolling
container with a `scrollTop`, and none exists here.

Two ways out, and the choice is a product decision:

### Option A — window-scroll virtualization (no UX change)

Listen to `window` scroll and resize, compute the list's offset from the document top, derive the visible
index range, render that slice, and reserve the space of the hidden rows.

- Keeps the page scrolling exactly as it does today. Nothing looks different.
- More code, and the failure modes are the unpleasant kind: jumpy scrolling, a scrollbar whose length
  changes as you scroll, content that shifts when the filter changes.
- Reserving space in a `display: grid` container with `gap` needs care — spacer elements inherit the gap,
  so the reserved height must account for it or the scroll position drifts over thousands of rows.

### Option B — give the list its own scroll container (simpler code, changes the UX)

`max-height: …; overflow-y: auto` on `.product-card-list`, then standard container virtualization.

- Much simpler and much harder to get wrong.
- But it introduces a **nested scrollbar**: the page scrolls, and the list scrolls inside it. That is a
  real UX change — it affects keyboard scrolling, mobile momentum, and how the toolbar/filters relate to
  the list. Not a decision to make silently on the author's behalf.

## Is it needed yet?

Measured at the current card pitch (~140px card + 16px gap = ~156px):

| Rows | DOM height | Card sub-elements |
|---|---|---|
| 100 | 15,600px | ~400 |
| 1,000 | 156,000px | ~4,000 |
| 5,000 | 780,000px | ~20,000 |

A browser handles a few hundred cards without complaint. It gets noticeable around a thousand and genuinely
slow in the thousands. Today's largest tenant has single digits, so **the trigger is list size, not a date**
— and unlike the payload cliff there is no hard failure, just degradation.

## Recommendation

**Option A**, when a real list passes roughly a thousand rows. It costs more code but changes nothing the
tenant can see, and a nested scrollbar is a permanent UX cost paid for a problem that is currently
hypothetical.

Do NOT build it blind. Scroll math is the kind of thing that looks right in code and is wrong in the
browser; it wants a real list of a few thousand rows to test against, which does not exist yet. When it
does, `indexedList.js` is where it goes, gated on a row-count threshold so smaller lists render normally
and the code path stays inert until it is needed.
