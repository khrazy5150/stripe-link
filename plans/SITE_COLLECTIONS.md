# Site / Page / Collection — the store data model

**Status:** design, not built. **Author + Claude, agreed 2026-07-31** through discussion. Supersedes the
interim "auto-attach on publish" idea (membership-implies-serving replaces it). Extends `plans/SITE_OBJECT.md`.

## Why

Almost every storefront bug we hit came from **two parallel relationships that could disagree**:

- `Site → pages` (the route map / "attach") — where a page is served.
- `catalog_grid → pages` (curation) — which pages a storefront lists.

"In the grid but not on the Site" (dead cards), "attached but not in the grid," "attached but no offer link
recorded until re-publish," three competing slugs (page slug vs Site slug vs grid slug) — all of it is the seam
between those two relationships. Collapsing them into **one** hierarchy, with **one owner per concern**, deletes
the whole class of bugs by construction.

The deeper problem is that today's three entities (Site, Landing Page, "Storefront") partially overlap. The fix
is to separate three **orthogonal** concerns:

| Concern | Question it answers | Owner |
| --- | --- | --- |
| Identity / routing | "Where does this content live?" | **Site** |
| Conversion | "What content converts this visitor?" | **Page** |
| Merchandising | "How are pages grouped for browsing?" | **Collection** |

## Retire the word "Storefront"

"Storefront" is the whole store — which is already the **Site**. Reusing it for "a grid of products" made the
word do two jobs and caused half the confusion. The grouping entity is a **Collection** (the term everyone reads
correctly; cf. Shopify/Squarespace/Webflow). A Site contains *many* collections; it is not itself one.

## The model

Four entities, each owning exactly one concern:

| Entity | Owns | Does NOT own |
| --- | --- | --- |
| **Site** | hostname, **routing table**, navigation, theme, **chrome defaults**, publication | content |
| **Page** | id, content, offer, SEO, layout, **per-page chrome** | its URL (no slug) |
| **Collection** | id, name, presentation, **ordered page references** | its URL, *whether* it is routed, the pages themselves |
| **Navigation** | ordered links, each → Page \| Collection \| External | — |

```
Site
 ├── Routing table   path → RouteTarget
 ├── Navigation      ordered links → RouteTarget
 ├── Theme
 ├── Chrome defaults
 ├── Pages           content/offer/SEO/layout (id only)
 └── Collections     ordered page references + presentation (URL-unaware)

RouteTarget (open abstraction)  =  Page | Collection | Redirect | External | …(Blog, Search, API later)
```

### Rules (locked)

1. **The Site owns the entire routing table.** A path maps to a **`RouteTarget`** — an open abstraction whose
   kinds are `Page | Collection | Redirect | External` today, and `Blog | Search | API | …` later with zero
   router changes. The router's whole job shrinks to "resolve path → RouteTarget, hand off." **Pages and
   Collections have no slug of their own** — the router owns paths. One source of truth kills the competing-slugs
   problem, and it unlocks (later) aliases, redirects, localized paths, and moving a page without touching the
   page object. `Redirect` folds the existing `www→apex` 301 into the model instead of special-casing it in the
   resolver. *Phasing:* v1 = exactly one canonical path per target; the superpowers are allowed by the model but
   not built day one.

2. **Published ⇒ has a Site.** A draft may be Site-less; a **published page with no Site is impossible** (a URL
   needs a hostname). This single invariant deletes the "published but No Site" state that caused the dead-link
   and attach-friction bugs.

3. **A page belongs to exactly one Site.** (A URL has exactly one hostname.)

4. **Collections are playlists of pages** — ordered **references**, never ownership (Spotify: one song, many
   playlists; here, one page, many collections). Many-to-many. Removing a page from a collection never deletes or
   un-serves the page.

5. **Collections group *pages*, not products** — the deliberate divergence from Shopify (where collections group
   products and PDPs are auto-generated). Here the **landing page is the first-class conversion asset**, so a
   collection curates landing pages. Implication for UX: "add a product to a collection" means "add its *landing
   page*," and every merchandised product has a page.

6. **Collections are pure data; routability is a routing concern, never a collection property.** A collection is
   always just `{ id, name, presentation, members }` — it never knows whether it's reachable. Two independent
   things can happen to it, and neither lives on the entity:
   - **Embed** — a Page renders it via a `section: { type: collection, collection_id }`. Always available; a
     collection is a reusable block droppable into any page (the homepage's Featured/New/Popular sections).
   - **Route** — the Site's routing table *may* point a path at it (`/sale → Collection`). Whether it has a URL
     is entirely "is there a route to me?", owned by the Site alongside every other URL fact. No `routable?` flag.

   This keeps the ownership rules pure (a collection genuinely does not own its URL) and still gives the two real
   jobs: **browse pages** ("Supplements", "Sale" → a route points at them: indexed hubs, subfolder authority) and
   **building blocks** ("Homepage Featured", "You May Also Like" → embedded, no route). The thin-content
   protection is simply *"we didn't add a route"* — force-routing every collection would mint near-duplicate
   `/homepage-featured` junk the SEO stack (noindex floors, thin-content gate) exists to avoid. The **smart
   default lives in the builder, not the model**: creating a "category" collection offers to also mint a route;
   an inline homepage block just doesn't.

7. **The homepage is just the page the route `/` points at.** Nothing special about it except its route. It
   **composes** sections — hero + several collection-embeds (Featured/New/Popular) + testimonials + footer. So a
   collection is a reusable building block, embeddable as a section *and* (optionally) routable on its own path.

8. **Navigation is independent of collections.** Nav is an explicit ordered list whose entries each point at a
   Page, a Collection, or an external URL. Creating a collection does NOT add it to nav.

### Chrome / header composition (per page)

Chrome (the store header, breadcrumb, nav, footer) is a **Site concern applied at serve time**, controlled
**per page** with a Site-level default. This is what resolves the "double header" and the standalone-ad-page in
one dimension — the same question: *does this route wrap the page in Site chrome?*

The header is unified (not two competing brand marks):

- **Every served page:** the centered **`● Brand`** mark (the "dotted branded name" style) is the one permanent
  header, clickable to the store root. This **retires** the old plain top-left site header — one brand mark, not
  two, and the page's former standalone brand overlay becomes this Site chrome.
- **Store / SEO pages:** a **breadcrumb line directly below** the brand mark.
- **Ad / bare pages:** brand mark only — **no breadcrumb**, no nav, no footer.

Set per page (e.g. `page.chrome = "store" | "bare"`), defaulting from the Site. So an ad landing page can always
opt down to bare while keeping the branded look.

## Relationship to existing work

- **`plans/SITE_OBJECT.md`** — the Site aggregate root, `platform_hostname`, route map. This doc promotes the
  route map into the authoritative **routing table** and adds **Collection** as the missing first-class entity.
- **Platform-hostname serving (shipped)** — already made the Site route map the authority for canonical + serving
  and added per-host chrome. So "page has no slug" is an **incremental cleanup + an invariant to enforce**, not a
  rewrite: `page.route.slug` is already vestigial (a default suggestion + the legacy standalone-artifact URL).
- **`plans/PAGE_COMPOSER.md` / `plans/CONVERSION_CONTEXT.md`** — the section-composition + registry machinery the
  homepage-composes-collections and chrome-per-page rules ride on. A collection-embed is a composed section; a
  routed collection renders via a default collection template (itself a one-section composed page).
- **Supersedes** the interim "auto-attach on publish": you don't attach on publish; **membership in a collection
  (or a standalone route) *is* serving**, and publish simply requires a Site (Rule 2).

## Migration (from today's model)

Today: `Site.pages` is a slug-keyed route map carrying `{page_id, page_type, enabled, label, category,
offer_id}`; a "storefront" is a **page** with `brand_hero` + `catalog_grid` sections; each page also carries
`route.slug`. Target: routing table + first-class Collections + composed homepage + slug-less pages.

Incremental, back-compat at each step (the platform-hostname tests are the tripwire):

1. **Routing table (rename/promote).** Treat `Site.pages` AS the routing table, each entry a
   `path → RouteTarget`. Add the `RouteTarget` shape (`{kind:"page", page_id}` default) so entries can later
   point at `kind:"collection"|"redirect"|"external"`. No behavior change.
2. **Extract Collections.** For each existing `catalog_grid` (scope="all" / category / curated), mint a
   **Collection** entity (ordered page references + presentation) and replace the in-page grid with a
   **collection-embed** section referencing it. The storefront page becomes a normal composed page. Auto-fill and
   category grids become collection *rules* (all-pages / by-category) vs explicit references.
3. **De-slug pages.** Stop reading `page.route.slug` for the canonical/served URL (already true for served
   pages); keep it only as the default when minting a route. Later drop it from the Page schema.
4. **Enforce published ⇒ Site.** On publish, require a Site + a route; pair with the auto-default Site
   (`SITE_OBJECT.md`) so this never dead-ends a tenant. Migrate existing "No Site" published pages onto their
   tenant's default Site with a route derived from their old slug.
5. **Chrome per page.** Add `page.chrome` (default from Site); render the unified centered-brand header +
   optional breadcrumb; retire the plain top-left header.
   - **Partially shipped 2026-08-03 (double-header dedup):** when a page composes its own centered `● Brand` mark
     (`brand_label`), that mark is now the single brand *and* carries the crawlable store-root link (SEO-13), and
     the store header drops its brand (nav-only). A page with no brand mark still keeps the header brand
     (non-regressive). Still to do here: `page.chrome` opt-down to bare, and ordering the breadcrumb *below* the
     brand mark. See `render_brand_label` / `render_site_header` in `src/stripe_link/runtime/html.py`.

## Builder UX shifts

- **Collections screen** (new): create/name a collection, pick + order its member pages (playlist), set
  presentation. Optionally **give it a route** (adds a routing-table entry → this collection) — the collection
  itself stays URL-unaware; this just writes a route on the Site.
- **Page editor**: sets content/offer/SEO/layout + **its route** (path in the Site) + **chrome** (store/bare).
  No more "storefront" page kind; a "storefront homepage" is just a page composing collection-embeds.
- **Homepage builder**: compose sections, including "embed a Collection" blocks (Featured/New/Popular).
- **Navigation editor**: explicit links → Page | Collection | External.
- "Add product to store" = add its landing page to a collection (or give the page a route) — one action,
  membership implies serving.

## Phased build order (proposed)

- **P1 — Routing table + Collection entity (additive).** `RouteTarget` shape on route entries (default
  `kind:"page"`); a Collection document (pure data, no slug/routable); the collection-embed section reads
  references; the router resolves `path → RouteTarget`. Migrate existing grids to Collections behind the scenes.
  No slug/chrome changes yet. This alone removes the two-relationships seam.
- **P2 — Published ⇒ Site + auto-default Site.** Enforce the invariant; migrate No-Site published pages.
- **P3 — Chrome per page.** Unified header + per-page store/bare; retire the top-left header.
- **P4 — De-slug pages** + routing superpowers (aliases/redirects/localized) as demand appears.

## Open questions / deferred

- Collection *rules* (all-pages, by-category, manual) — keep all three, or unify manual+rule?
- Where per-section presentation overrides live when a collection is embedded vs routed.
- Route-collision handling in the routing table when many collections reference the same page (page has ONE
  canonical route; collections just link to it — so no collision, but confirm the builder surfaces the page's
  route clearly).
- Naming: `Collection` (chosen) vs Catalog/Shelf/Showcase.

## Ties

`plans/SITE_OBJECT.md`, `plans/PAGE_COMPOSER.md`, `plans/CONVERSION_CONTEXT.md`, `plans/PLATFORM_HOSTNAME_SERVING.md`,
`plans/SITE_MIGRATION.md`; `schemas/Site.schema.json` (route map → routing table of `path → RouteTarget`),
`schemas/Page.schema.json` (drop slug, add chrome), a new `schemas/Collection.schema.json` (pure data — no slug,
no routable).
