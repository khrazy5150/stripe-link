# Offer item visibility — cards and search

**Status:** phases 1-3 SHIPPED 2026-09-01. Phase 0 CONTRACT shipped 2026-09-02 (`GET /offers?limit=&cursor=`,
opaque cursor, 500 cap, unchanged when unused). Projection + client adoption deferred — see below.

## 1. The problem, as a tenant hits it

A tenant adds a Protein Shaker Bottle as an order bump, then goes looking for it later. It is not on the
offer card, and search does not match it. The only way to find it is to open every offer and read its
Purchase Flow diagram. With a dozen offers that is tedious; with a hundred it is impossible.

The same is true of `Whey Protein`, which is a plain landing item — so this is not only about bumps.

## 2. What was verified (not assumed)

Reading the real `Workout Bundle` document out of `jb-offers-dev`:

    items[]                 -> 3 products (LANDING ONLY)
    purchase_opportunities  -> stage=landing        x3   group=main_offer
                               stage=checkout       x1   group=order_bump      (Protein Shaker)
                               stage=post_purchase  x1   group=upsell          (NAD, a duplicate)

So `items[]` is a landing-only projection. Anything reading it to answer "what is in this offer" will
under-report by design. `purchase_opportunities` is the complete list, and it carries `stage` + a
`placement.group` that names the role.

Search coverage today, measured:

| Screen | Searches | Misses |
|---|---|---|
| Offers | `name`, `slug`, `offer_type`, `product_intent` | every item name, landing or funnel |
| Landing Pages | `name`, `page_id`, `offer_id`, `route.slug`, template, `status` | the offer's NAME, and every item name |
| Products | its own name/tag/category/keyword | — (it IS the entity) |
| Services | its own name/description/id | — (it IS the entity) |

**The pattern:** a list screen searches the fields of its own document and never the entities that
document REFERENCES. Products and Services are fine because they are the entity. Offers and Landing Pages
both point at other things, and neither can see through the pointer. Fixing only the offer card would
leave the identical hole one screen over.

## 3. Card display

Do NOT flatten every stage into one list. `Creatine Gummies, NAD Supplement, Whey Protein, Protein Shaker
Bottle` reads as four products on the landing page, which is wrong exactly when the tenant is trying to
work out what the offer is. Landing items are the offer's primary meaning; bumps and upsells are
conditional on a purchase that has not happened yet.

    Items: Creatine Gummies, NAD Supplement, Whey Protein · 1 bump

- Names for landing items (already shipped: names, 3-name cap, 90-char backstop, dedupe, title tooltip).
- A role-labelled COUNT for non-landing stages, from `placement.group` (`order_bump` -> "bump",
  `upsell`/`downsell` -> "upsell"/"downsell").
- Count **placements, not distinct products**. These words name funnel STEPS. An upsell reselling a
  product already on the landing page is still a real step, so the Workout Bundle reads `1 bump, 1 upsell`.
  (The first implementation deduped against the landing items and thereby hid a configured upsell
  entirely — corrected same day.) Roles read in funnel order regardless of document order.
- The hover title carries the full breakdown by role, so nothing is hidden, only collapsed.

## 4. Search

Extend `offerSearchText()` to include every item name across ALL stages plus the ids (an id is still a
legitimate thing to paste). Same for the Landing Pages filter: add the offer's name and its item names.

Then fix the placeholders, which currently promise less than they should deliver:
`Name, slug, type...` -> `Name, slug, product...`.

**Requires the catalog to be loaded client-side.** The Offers list now loads products + services on mount
(shipped with the card-names change; it also revived `offerImage`'s long-dead product-image fallback).
Landing Pages needs the same before its search can resolve names.

**Scaling limit, stated honestly:** this is client-side filtering over the full tenant list, which is how
every list screen here already works. It is fine at hundreds of offers and wrong at tens of thousands. The
day that matters, search moves server-side — that is a different plan, and nothing here blocks it.

## 5. Phases

1. **Card role counts** — SHIPPED. `Creatine Gummies, NAD Supplement, Whey Protein · 1 bump`.
2. **Offer search through items** — SHIPPED. Names + ids, every stage; placeholder now `Name, slug, product...`.
3. **Landing Pages parity** — SHIPPED. It already loaded the catalog via `ensureCatalogLoaded()`, so only the
   filter needed extending: it now matches the offer's name/slug and every item in it.

All three live in `dashboard/src/composables/offerItems.js` — ONE implementation with name resolution
injected, because both screens need identical rules over different stores. Covered by
`tests/test_offer_items_js.py` (run through node), which pins the two rules that were wrong in production:
items[] is landing-only, and funnel counts are placements rather than distinct products.

## 6. Deliberately out of scope

- Server-side search (see the scaling note).
- Showing funnel items in the offer card's IMAGE logic — the landing product is the right hero.
- Any change to `items[]` itself. It is a legitimate landing-only projection; the fix is to read
  `purchase_opportunities` when the question is "everything in this offer", not to redefine `items`.


## 7. Phase 0 — what shipped, and what deliberately did not (2026-09-02)

**Shipped: the contract.** `GET /offers?limit=&cursor=` returns `{offers, next_cursor}`, `next_cursor`
present only when more remain. `limit` caps at 500 (~1.5MB of ~2.9KB documents). Omit both and the response
is byte-identical to before, so no client changed. `list_page_for_tenant` is a NEW repository method;
`list_for_tenant` is untouched because 49 internal callers (publishing, sweeps, funnel resolution)
legitimately need the whole set.

The reason to do this pre-launch is that the API SHAPE is the expensive thing to change once a tenant
integration, the AI provider adapter, or a mobile client depends on the unbounded one. The implementation
behind it can change freely.

**Implementation note that matters:** DynamoDB applies `Limit` to items READ and stops at 1MB, so a query
can return fewer items than asked while more remain. `_query_page` keeps reading until it fills the page
or exhausts the partition. Treating a short page as end-of-list silently drops records — tested with a
table that always returns one row at a time.

**Deliberately NOT done:**

- **A card projection.** Measured against the real documents: `purchase_opportunities` is 50.6% of an offer,
  `items` 12.9%, `funnel` 8.8%. The card needs opportunities for item names and search needs the ids, so a
  projection saves ~25%, not the 10x first assumed. Pagination is what moves the cliff; projection is a trim.
- **Client adoption.** The dashboard still requests the full list, because filtering is client-side and
  paginating without moving search would make "shaker" search only the loaded pages — a correctness bug
  worse than the performance one, and the same invisible-product failure this plan exists to fix.

### The slim index — SHIPPED 2026-09-02

`GET /offers?view=index` returns the list projection: `offer_id, name, slug, offer_type, product_intent,
status, created_at, updated_at, item_ids, landing_ids` and `image_url` when set. Measured at **468 bytes
against 4,482 for the full document — 10%**, which moves the response cliff from roughly 2,000 offers to
roughly 13,000. Beyond that the same `limit`/`cursor` apply to the index too.

It carries **no product data, only ids**. The list screen already loads the product and service stores (it
needs them for item names and for deriving funnel roles from pricing contexts), so resolving a name
client-side is free — while embedding names here would copy catalog data into a second place that can go
stale, which is the failure mode this codebase keeps hitting. Ids reference; the catalog is the truth.

`landing_ids` is stored because landing membership is genuine OFFER data (which products are on the page,
in what order). Funnel roles are NOT stored, because they derive from each product's pricing contexts —
see §6 and `domain/funnels.funnel_context_items`.

`GET /offers/{offer_id}` already existed, so View and Edit fetch the one full document they need. That is
what lets the list screen stop loading full documents entirely.

### Dashboard adoption — SHIPPED 2026-09-02

`loadOffers()` fetches `?view=index`. View and Edit call `fullOffer()`, which fetches
`GET /offers/{offer_id}` for the one document they need — so the list never loads full documents at all.

Every card-facing helper reads BOTH shapes, because `purchaseFlow.offerEntries` normalizes all three
(purchase_opportunities, legacy items[]+funnel.*, index row) and `offerItems.js` now reads through it.
It previously had its OWN reader that knew two of the three, which meant an index row derived its funnel
roles correctly and silently lost its landing names — caught by the parity test, not by inspection.

`landing_tier_count` is projected so the card's single/bundle/selector RULE stays in the client
(`derivedOfferType`), reading the same facts from either shape via `landingShape()`. Projecting the fact
rather than the verdict keeps one implementation of the rule.

A saved offer stays in the list as a FULL document, deliberately: every consumer is shape-agnostic, so
mixing costs nothing, and converting it would need a JS mirror of the projection — a second implementation
to keep in step, which is the thing this design keeps avoiding.

`tests/test_index_row_parity.py` feeds the REAL server projection to the REAL client helpers through node
and requires identical card line, tooltip and roles — plus an absolute assertion on the text, since
equality alone would pass if both sides were broken.

**Still to do:** the PRODUCT index. Adopting it is what actually removes the
cliff for today's UI, and it is the prerequisite for mobile infinite scroll — which otherwise ships with
rows in offer-id order (there is no chronological index; the sort key is `OFFER#{mode}#{offer_id}`) and a
search covering only what has been scrolled.

**When catalogs get big, the preferred shape is a split payload:** load a slim search index for EVERY offer
(id, name, slug, item names — roughly 200 bytes each, so 1,000 offers is ~0.2MB) and paginate the rich
cards. Substring matching stays in the browser where it is free and correct. Server-side `FilterExpression`
is the alternative, but it is applied AFTER the read, so it saves no read capacity — only payload — and it
inherits the short-page trap above.

**Cost footnote, so nobody optimises the wrong thing:** a full 1,000-offer read costs about $0.000125
(PAY_PER_REQUEST, ~0.5 RCU per item). The reason to paginate is the 6MB response cliff, browser memory and
Lambda duration — not the database bill. `ProjectionExpression` reduces wire bytes but NOT read capacity,
which is charged on the full item size.
