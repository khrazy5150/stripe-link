# Roundup pages

**Status:** PLANNED, not built. Design agreed with the author 2026-10-27.

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

**P1 — `presentation.layout`.** Add the field (default `grid`, so nothing existing moves), implement
`listicle` rendering, port `masonry`. Shippable alone: it improves Collections with or without Roundups.

**P2 — the reverse cascade.** §5. Independently valuable — every Collection embed is stale today, not
just counted ones. **Must land before P3**, or the counted title is a lie.

**P3 — the `roundup` action.** The enum entry, the composition, the wizard card, the two required text
fields.

**P4 — the title engine.** `{count}` / `{year}`, plural rule, propagation to all four surfaces, the
pattern picker.

---

## 9. Open questions

1. **Layout on the Collection or on the embed?** `presentation.heading` sets the precedent for the
   Collection, and that is this plan's assumption. The cost: one Collection cannot be a grid on one page
   and a listicle on another without being duplicated. Cheap for `all`/`category`, slightly redundant for
   `manual`. Revisit if a real tenant wants both.

2. **Where does per-entry pitch copy live?** A Collection's members are page references with nowhere to
   put a paragraph. Either extend the member shape, or author the entries on the embedding **section**
   with an `offer_id` binding. This plan leans to the section — the pitch is page-specific framing, and
   the same Collection on two pages may want different angles — but it is unresolved, and it decides
   whether a Roundup has any original content or merely re-prints the offer pages' own descriptions.

3. ~~**Does the listicle CTA go to the offer page or straight to checkout?**~~ **DECIDED 2026-10-27 —
   both links go to the offer page.** The entry heading is a link and the button is a button, as on the
   reference, and both land on the offer landing page, which then transacts. Straight-to-checkout was
   considered and rejected: it costs the internal links §6 depends on, the page carrying `Product` markup,
   and any buyer context before the payment form. The author's assessment was that skipping the offer page
   could work under about $25 and not above it — and a Roundup is a browsing page, where the reader has
   not yet chosen anything.

4. **How many entries before the page stops being good?** The reference has 88 and is the worse for it.
   `numbered_list` already has a `NUMBERED_LIST_MAX`. Decide whether a Roundup gets a cap, a warning, or
   nothing.
