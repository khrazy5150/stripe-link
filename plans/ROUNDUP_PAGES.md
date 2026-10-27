# Roundup pages

**Status:** **COMPLETE — P1–P4 SHIPPED** 2026-10-27, creation flow included. Design agreed with the author 2026-10-27.

A Roundup is a **non-transacting listing page**: an ordered set of the tenant's own landing pages, each
rendered as an entry with an image, a short pitch and a link through to that page, under a headline that
counts itself. It is the page shape every affiliate site on the internet already uses, pointed at the
tenant's own catalogue instead of someone else's.

---

## 1. The goal, and the two flaws we are fixing

The reference the author brought is `consumerbags.com/coolest-gifts`. Read it before building anything:
88+ numbered entries, each with a name, a sales headline, sometimes an image, a rating or review count, a
discount badge, a paragraph of promotional copy, and a CTA.

Two things about it are worth copying and two are not.

**Worth copying.** The format converts, and the headline formula — `{count} {plural noun} {hook}` — is a
proven pattern that most small merchants do not know. Handing it over, with the number kept true
automatically, is the actual product value here. It is copywriting a tenant cannot write, given for free.

**The flaw we fix.** Its title says *"29 Insanely Cool Gifts"* and it lists over sixty. The title was
written once; the author kept adding products. A hand-typed number is wrong the moment the list changes,
and nothing tells anyone.

**What we do NOT copy.** It is an affiliate advertorial: every button goes to `go.consumerbags.com/click/…`
and out to third-party merchants, it carries unsourced medical claims (*"Sleeping pills can increase your
risk of death by 4.6X"*), manufactured discount urgency, and an Advertiser Disclosure for a reason. A
Roundup lists **the tenant's own offers only**. Affiliate links are out of scope — see §7.

**Name.** Called "Roundup", not "Advertorial". An advertorial is paid advertising dressed as editorial;
it is the thing that *triggers* FTC disclosure duties, and it misdescribes a tenant listing their own
products. The word in the UI shapes what tenants write.

---

## 2. The decision: reuse three things, invent nothing

The whole feature is three small additions to machinery that already exists and is already proven.

### 2a. Non-transacting: `product_intent = "lead_gen"` + a new action

`composition_key()` (`domain/composition.py:268`) returns `"lead_gen"` when the offer says so, then maps
`lead_capture_action` through `LEAD_COMPOSITIONS` (`composition.py:253`). Add one entry:

```python
LEAD_CAPTURE_ACTIONS  (documents.py:808)   += "roundup"
LEAD_COMPOSITIONS     (composition.py:253) += "roundup": "roundup"
```

**This is the established mechanism, not a workaround.** `plans/SOCIAL_MEDIA_PAGES.md` §2a records that
an earlier attempt to express "this page sells nothing" through `offer_type` *could never be reached*,
because `offer_type` is derived and no offer shape can say it. And two existing actions — `external_url`
and `social_redirect` — already capture no lead at all, so the enum is in practice *"what does this
non-transacting page do"*.

A Roundup is **not** in `NEVER_INDEXED_COMPOSITIONS` (`composition.py:353`). Unlike `lead_bridge`, being
found in search is its entire purpose.

### 2b. Input: a Collection, not a new member list

A Collection is already *"an ordered, curated group of a Site's landing pages"* with `rule` of `manual`
(ordered `members[]`), `all`, or `category` (`documents.py:2614`). `_collection_grid_items()`
(`runtime/publishing.py:383`) resolves members against the Site route map and **drops anything not
published on the Site**.

That gives us, free and already tested: ordering, reuse of one Collection across pages, and — the part
that matters for §4 — a member list that can only contain pages which genuinely resolve and are
navigable. A Roundup **embeds a Collection**; it does not hold its own list of pages.

### 2c. Layout: one new field on `presentation`

`Collection.presentation` exists and currently holds exactly one key:

```
presentation: {'heading': 'string'}
```

Add `layout`, defaulting to `grid` so every existing Collection is unchanged:

| `layout` | Shape | For |
|---|---|---|
| `grid` | uniform cards (today's `render_catalog_grid`) | default; unchanged |
| `masonry` | CSS multi-column, variable heights | **browsing** an unordered catalogue |
| `listicle` | single column, ordered, numbered | **Roundup**; mobile-first |

---

## 3. The three layouts, and why masonry is not the Roundup one

### `listicle` — what a Roundup renders

One entry per row, numbered, image left or above, heading, pitch, CTA. The closest existing renderers are
`render_catalog_grid` (`html.py:~7860`, which already emits real anchors — see §6) for the data binding,
and `render_numbered_list` (`html.py:7466`) for the ordered semantics. Neither does both:
`numbered_list` is authored plain-text lines with no product binding; `catalog_grid` is cards with no
per-entry prose.

Mobile is the reason this is the Roundup default: a single scrolling column is the format, and a grid
collapses to one column on a phone anyway but keeps card proportions that waste the fold.

### `masonry` — ported from the old front page

Source: `/Users/morpheus/Documents/Development/junior bay/frontpage/dot-net/index.html`. It is **pure CSS
multi-column**, no JS library:

```css
.masonry      { column-count: 5; column-gap: 14px; }
.image-tile   { break-inside: avoid; }
/* 5 → 4 (≤1180px) → 3 (≤900px) → 2 (≤650px) → 1 (≤420px) */
```

It also carries a `.image-tile.no-image` variant for products without a photo — keep it.

**Why masonry must not be the Roundup layout.** `column-count` lays items out in **column order, not
reading order**. With 10 items in 5 columns the top row reads 1, 3, 5, 7, 9 — item 2 sits *below* item 1,
not beside it. For an unordered gallery that is invisible; for a ranked list with a counted headline it
destroys the sequence the tenant curated.

Note the DOM order stays correct, so crawlers and screen readers get the right sequence. It is only the
visual order that misleads — the markup is right and the layout lies, which is the opposite of the usual
accessibility bug and easy to miss in review.

**Three changes when porting:**

1. Guard the tile hover `transform: scale(1.02)` behind `prefers-reduced-motion`.
2. Drop `aria-live="polite"` from the section. It was correct when JS injected results into it; in a
   pre-rendered artifact it makes a screen reader announce a static list as though it were changing.
3. Keep emitting `width`/`height` from the `image_dims` sidecar. Variable-height columns are where
   layout shift hurts most, and that work has already shipped.

---

## 4. The title engine

Opt-in per page. A checkbox — *"Count the items in this list"* — plus a noun the tenant supplies.

```
{count} {plural_noun} {rest of title}

 →  "29 household products you absolutely have to have today"
 →  "13 gift ideas for your mom"
 →  "25 insane gadgets you'll love in 2027"
```

Five rules, each of which is a bug if missed:

1. **Count what is RENDERED, not what is authored.** Take the length of `_collection_grid_items()`'s
   output — the same list the layout draws, after unpublished members are dropped. Counting
   `collection.members` would print "29" above 26 entries.

2. **Plural at 1.** "1 gift ideas for your mom" is fatal to the format. The tenant types the plural (they
   will anyway), and at a count of 1 the number is **omitted entirely**: *"Gift ideas for your mom"*.
   Do not attempt automatic singularisation.

3. **Add a `{year}` token.** *"…you'll love in 2027"* is hand-typed text that goes stale exactly the way
   the count does — and worse, because "best X 2027" read in 2028 signals an abandoned page. If we
   auto-maintain one number we should auto-maintain both. Costs nothing alongside the count.

4. **The count propagates to all four places**: `<title>`, the H1, `og:title`, and the
   `ItemList`/`CollectionPage` `name` in `collection_json_ld()` (`html.py:5396`). A count that updates in
   three of four makes the page contradict itself.

5. **Never in the slug.** `/coolest-gifts`, permanently. A slug carrying the count changes URL on every
   republish, breaking inbound links and discarding whatever ranking the page earned.

**Headline patterns, not pre-filled claims.** Offer the *structures* — `{count} {noun} {audience} swear
by`, `{count} {noun} under ${price}`, `{count} {noun} you'll love in {year}` — and let the tenant write
the hook. Shipping "you absolutely have to have" as a default puts our words in their mouth, and the
claims are where their liability starts.

---

## 5. The prerequisite: a reverse cascade on Collection write

**Without this the feature reproduces the exact bug it exists to fix.**

Today the cascade runs one way only. `cascade_publish_collection_drafts()`
(`runtime/publishing.py:696`) runs *when the embedding page publishes* and publishes that page's draft
members. Nothing runs the other way: `handlers/collections.py` has no publish path at all. Adding a
product to a Collection in February leaves the already-published artifact — and its "29" — untouched.

Artifacts are pre-rendered and served from the CDN, so the count cannot be computed at request time. It
is a publish-time value, and something has to trigger the republish.

**What to build:** on a Collection write, find the published pages whose sections embed that
`collection_id` and re-publish them. Three things to get right:

- **Termination.** `cascade_publish_collection_drafts` publishes draft members; a member publish must not
  re-trigger the collection cascade and bounce. The existing function already reasons about this — follow
  its argument.
- **Fan-out.** One Collection may be embedded by several pages. The write must not load-mutate-put a
  shared document per page; see `[[feedback_shared_document_read_modify_write]]`, which was learned on
  this exact subsystem.
- **Failure is per-page.** A page that fails to republish must not block the Collection write.

---

## 6. SEO: what is already right, and the one floor to enforce

Already correct and **not to be rebuilt**:

- **Crawlable links.** `render_catalog_grid` emits `<a class="sl-catalog-card" href="…">` with
  host-relative URLs — ordinary anchors, not JS click handlers. The listicle layout must do the same.
- **Structured data split.** `collection_json_ld()` emits `ItemList`/`CollectionPage` whose entries are
  `ListItem` with url + name, **deliberately not** nested `Product`+`Offer`. Its own comment explains
  why: the full Product markup belongs on the product's page, and restating prices in two places creates
  two claims that can disagree. Keep that.
- **Only real pages appear.** `_collection_grid_items` already guarantees it.

**The floor.** The thin-content demotion (`publishing.py:1520`, `THIN_CONTENT_MIN_WORDS`) publishes any
page under 150 words of unique body text as `noindex`. Measured on a real custom domain during
`plans/OFFERLESS_PAGES_IN_BUILDER.md`:

```
storefront, as the wizard makes it   words= 11  → noindex,follow
storefront + builder content         words=168  → index,follow
```

A Roundup that is only a rendered list **publishes noindex and never ranks**. This is the one place the
author's "ideally no design" goal has to bend, and the distinction that resolves it is *design* versus
*words*:

- **No layout decisions.** The tenant picks pages; the page builds itself. This is the real goal and it
  is fully preserved.

  To be exact about what "no design" means here, because it is the point of the whole feature: a tenant
  must never be asked *"image above the heading or beside it? button before the paragraph or after?"*
  Every entry has one fixed arrangement, chosen once, by us. That is precisely the flaw in other page
  builders — unlimited choice with no direction, which produces either paralysis or a bad page, and
  usually both. The tenant's only decisions are **which pages, in what order, under what headline**.
- **Two required text fields.** An introduction, and a short "how these were chosen". Without them the
  page is a reassembly of content Google already has from the offer pages, with nothing of its own.

Per-entry pitch copy: see §9, open question 2.

---

## 7. Explicitly out of scope

- **Affiliate links.** A Roundup lists the tenant's own offers. Third-party links change the data model,
  make `Product` markup impermissible, and bring FTC disclosure duties onto the platform hosting them.
  Revisit as its own plan, with the disclosure requirement designed in rather than added after.
- **A new per-entry rating field.** See below — the existing `rating` element already covers this and
  already has a settled policy. Do not invent a second one on the Roundup section.
- **Free-text discount badges.** Derive from an actual compare-at price or omit. Unlike a star badge there
  is no existing element for this, so adding one would be a new decision rather than a settled one.

### Star ratings: already solved, available, not volunteered

An earlier draft of this plan ruled star ratings out. That was wrong, and the correction is worth
recording because it is the kind of thing a later reader will re-litigate.

The `rating` element already exists — `composition_rules.json`, labelled *"Star-rating badge"*, slot
`proof` — and `render_structured_data` (`html.py:~5358`) already draws the exact line this plan was
reaching for, in its own words:

> *No AggregateRating. The `rating` element is a number a tenant typed, with no verifiable source.
> Emitting it as review markup would be fabricated structured data — against Google's structured-data
> policies and squarely within the FTC's rule on deceptive ratings. It stays visible-only text until a
> real review source exists.*

So the platform's position is already set and is the right one: **the badge renders, the markup does
not.** A tenant who adds it is making a claim in their own name on their own page, which is theirs to
make. The `reviews` element is the other half — real buyer reviews, which *do* earn `AggregateRating`.

For Roundup specifically: `rating` is **available but never volunteered**. It does not appear in the
default template, the wizard does not suggest it, and no copy hints at it. The reference page covers
every entry in invented scores; the difference between a tool that permits that and a tool that proposes
it is the whole of our exposure, and it costs nothing to stay on the right side of it.

---

## 8. Phases

**P1 — `presentation.layout`. SHIPPED 2026-10-27.** The field exists on `Collection.presentation` beside
`heading`, validated against `COLLECTION_LAYOUTS` (`documents.py`), propagated onto the section at publish
by `resolve_category_grids` with the section winning over the Collection, and rendered by
`render_catalog_grid`, which now branches on it. Masonry is ported from the old dot-net front page as pure
CSS multi-column with the four original breakpoints, its square crop dropped so heights can vary, and the
hover lift behind `prefers-reduced-motion`. The listicle is a real `<ol>` with a CSS counter.

19 tests in `tests/test_collection_layouts.py`. The one they exist for is **crawlability**: all three
layouts must emit one `<a href>` per item, because these cards are the internal links the catalog
hierarchy is built on, and a layout that rendered beautiful unlinked tiles would look finished while
quietly costing the Site its linking. Unknown and absent layouts both fall back to `grid`, so every
Collection written before this renders exactly as it did.

**P2 — the reverse cascade. SHIPPED 2026-10-27.** Writing or deleting a Collection now re-renders the
PUBLISHED pages that embed it: `pages_embedding_collection` finds them, and each is re-put so the publish
stream fires. Drafts are skipped — no artifact to go stale, and they resolve the collection fresh when
they do publish. Best-effort per page, after the Collection's own write, so a failed re-render never
costs the tenant their edit. 13 tests in `tests/test_collection_reverse_cascade.py`, asserting on the
page WRITE rather than a patched helper, because the write is what fires the stream.

Two things building it taught:

- **The finder lives in `handlers/collections.py`, not `runtime/publishing.py` where it belongs.**
  Importing the publish module made the function statically reach three further tables and a bucket it
  never touches, and the grant tests correctly demanded all of them. Likewise the page re-put is written
  out rather than imported from `handlers.sites`, which would have dragged in Stripe keys, user profiles
  and six more tables for three lines. Both are deliberate; both are commented at the site.
- **`rule: all` and `category` collections have a SECOND staleness this does not fix.** Their membership
  changes when *pages* change, not when the Collection does — publishing a new offer page silently
  changes what an `all` collection contains, and nothing re-renders its readers. P2 closes the
  Collection-write direction only. **This matters for P4**: a counted headline on an `all`-rule Roundup
  would still drift. Either restrict the count to `manual` collections, or add the page-publish
  direction too. Unresolved — see open question 5.

**P3 — the `roundup` action. SHIPPED 2026-10-27.** `roundup` joins `LEAD_CAPTURE_ACTIONS`, maps to the
`lead_roundup` composition, gets rules in `composition_rules.json` (which the dashboard imports, so
builder and renderer cannot drift), a wizard card, a glyph and form copy. 13 tests in
`tests/test_roundup_composition.py`.

Two traps found building it, both of which would have shipped looking correct:

- **The composition's NAME decides whether the page transacts.** `render_coupon` computes
  `transacts = not composition_key(offer).startswith("lead_")`, so a composition called `roundup` would
  have been handed a checkout href on a page that sells nothing. It is named `lead_roundup`, and a test
  now asserts that every lead action maps to a name starting `lead_`.
- **`THIN_BY_DESIGN` is derived from `LEAD_COMPOSITIONS.values()`**, so joining that map silently
  exempted the Roundup from the thin-content WARNING — while the demotion in `publishing.py` happened
  anyway. Silently unranked with the one explanation switched off. `lead_roundup` is now subtracted from
  that set explicitly, which is the only lead shape that is.

`rating` is in neither `sections` nor `excludes`, which is how "available but never volunteered" from §7
is expressed in the rules file. Also fixed in passing: the `teal` tone the Register-for-an-event card has
referenced since it shipped had no CSS rule, so that icon rendered untinted beside its siblings.

**P4 — the title engine. BACKEND SHIPPED 2026-10-27.** `expand_title_tokens` resolves `{count}` and
`{year}`; `roundup_item_count` counts the RESOLVED items of `manual` collections only;
`expand_roundup_titles` runs at publish, straight after `resolve_category_grids`, and rewrites both
`seo.title` and the hero's `headline`/`subheadline` in place. Those two fields are all four surfaces:
`seo.title` feeds the `<title>`, `og:title` and the `CollectionPage` name, and the hero headline IS the
h1. 20 tests in `tests/test_roundup_title_engine.py`.

Expanded at publish rather than at render because artifacts are pre-rendered and served from the CDN —
there is no request-time hook, and publish is the moment the resolved item list is known.

Degradation is deliberate: an unknown count (no manual collection on the page) drops the number rather
than publishing a literal `{count}` to a live page, which would be worse than any wrong number. One item
drops it too — "1 gift ideas for your mom" is fatal to the format, and no automatic singularisation is
attempted because the tenant typed the plural and English does not let us un-type it.

The five headline patterns live in `composition_rules.json` as `roundup_headlines`, which the dashboard
already imports. They are structures — `{count} {things} for {audience}` — never finished claims, and a
test asserts none of them ships an adjective on the tenant's behalf.

**P4b — per-entry copy and the builder controls. SHIPPED 2026-10-27.**

- **Per-entry pitch copy**, open question 2's resolution, is wired. Items now carry `page_id` in all
  three resolve modes, and the listicle renders `section.entry_copy[page_id]`, falling back to the
  offer's subheadline and then the product description — the same ladder `hero_copy` climbs, so an
  entry reads the way its own page's hero does. Grid and masonry are untouched: a card is a glance, a
  row is a read. Keyed by PAGE, not offer, because two pages can serve one offer and the pitch
  belongs to the page.
- **Builder controls**: headline patterns as one-click chips under the Hero Headline (roundup pages
  only, read from the shared rules file so the builder cannot offer a pattern the publisher would not
  expand), a layout select on the grid section defaulting to "use the collection's setting", and a
  per-entry copy box for each member of a `manual` collection.

Carrying `page_id` on only the Collection path broke `test_migration_is_behavior_preserving`, which
compares an inline grid against the same grid migrated to a Collection. That test was right: a field
present in one mode and not the other makes a migration that changes nothing look like one that
changes something. All three modes now emit the same item shape.

**P4c — the creation flow. SHIPPED 2026-10-27.** `catalog_grid` is `ui: "internal"` and arrives with
the page; offer-less pages get theirs from the storefront wizard, and a Roundup has an offer, so it
took the ordinary landing-page path and arrived with no grid, no Collection and no way to add either.
The page the whole shape is made of never existed, while every piece behind it worked.

`seedRoundupCollection()` now mints a `manual` Collection with `layout: listicle` before the builder
opens, exactly as the storefront flow mints its own, and returns false on failure so the builder never
opens onto a grid that cannot resolve. `builderSectionCandidates` emits the grid for a roundup; both
shapes share one `catalogGridSection()` emitter, and `layout` and `entry_copy` round-trip through
`offerlessState` so neither is write-only. `SHAPE_SEEDS` seeds a `content_block` for the same reason
the link-in-bio page needed its seeds: a bare list is under 150 words and publishes `noindex`.

**A drift found on the way, unrelated to Roundup and older:** the builder's `LEAD_COMPOSITIONS` mirror
was missing `register_event` from the day it shipped, so it fell through to the `lead_capture`
default — the builder composed every webinar page as a squeeze page while the renderer composed it
as `lead_event`. The comment above the map claimed a test pinned it; the test only checked that the
LOOKUP was written. Both maps are now compared member by member.

---

## 9. Open questions

1. **Layout on the Collection or on the embed?** `presentation.heading` sets the precedent for the
   Collection, and that is this plan's assumption. The cost: one Collection cannot be a grid on one page
   and a listicle on another without being duplicated. Cheap for `all`/`category`, slightly redundant for
   `manual`. Revisit if a real tenant wants both.

2. **Where does per-entry pitch copy live?** STILL OPEN; it blocks P3.

   The input model is settled and needed no change: a `manual` Collection's `members` are **page_ids**,
   and `_collection_grid_items` resolves each to `(slug, offer_id)`. So a Roundup is built from the
   tenant's existing LANDING PAGES, and an offer already written up on a page can be pulled into any
   number of Roundups without being recreated. That is the author's intent and it is what the code
   already does.

   What is unsettled is the paragraph. Members are bare page references with nowhere to put one. The
   recommendation is **optional copy authored on the embedding section**, bound by `page_id`, falling
   back to the offer's own description when absent:

   - *On the section, not the Collection*, because one Collection may be embedded by two Roundups that
     frame the same product differently ("for your mom" / "for coworkers"), and a Collection is
     documented as pure, reusable, URL-unaware data.
   - *Optional, with a fallback*, because "very little design" is the goal: a tenant who writes nothing
     still gets a working page, and the 150-word floor is carried by the intro and the selection
     rationale rather than by per-entry prose.

3. ~~**Does the listicle CTA go to the offer page or straight to checkout?**~~ **DECIDED 2026-10-27 —
   both links go to the offer page.** The entry heading is a link and the button is a button, as on the
   reference, and both land on the offer landing page, which then transacts. Straight-to-checkout was
   considered and rejected: it costs the internal links §6 depends on, the page carrying `Product` markup,
   and any buyer context before the payment form. The author's assessment was that skipping the offer page
   could work under about $25 and not above it — and a Roundup is a browsing page, where the reader has
   not yet chosen anything.

4. ~~**Does the count work on `all`/`category` collections?**~~ **DECIDED 2026-10-27 — `manual` only.**
   `{count}` is offered on `manual` collections, where the tenant's own edit is the only thing that
   changes the list and P2 already re-renders every reader of it. On `all` and `category` the checkbox is
   not offered: their membership moves when a *page* publishes, a direction that is not wired, so a count
   there could drift silently — the precise failure this feature exists to prevent.

   Counting those is a future enhancement, and it is gated on the publish-and-refresh lifecycle being
   able to GUARANTEE consistency rather than usually achieving it. A number that is right most of the
   time is worse than no number, because it is trusted.

5. **How many entries before the page stops being good?** The reference has 88 and is the worse for it.
   `numbered_list` already has a `NUMBERED_LIST_MAX`. Decide whether a Roundup gets a cap, a warning, or
   nothing.
