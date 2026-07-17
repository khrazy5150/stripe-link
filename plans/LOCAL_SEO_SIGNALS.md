# Local SEO Signals (service / local business landing pages)

## Why

Product pages optimize for product rich results (Phase 3a: Product/Offer JSON-LD). **Service and local
businesses need a different set of signals** — the whole page should say *who, where, and how to reach us*,
consistently, so Google can tie the page to a physical business entity and rank it locally. The current
alt-text work (Goal Composition Phase 4 slice 2) fills alt from the product/service name, which is fine for
DTC but **misses the local signal**: `alt="Swedish massage"` is weak; `alt="Licensed massage therapist
performing a Swedish massage at Luxe Spa in St. George, Utah"` carries the business + city that drives local
ranking.

Every signal here is **derived from the canonical NAP** (name / address / phone), so this plan is gated on
plans/BUSINESS_PROFILE_AND_GBP.md P1. Consistency is the point: the same NAP in the JSON-LD, the footer, the
image captions, and the alt text — inconsistent NAP dilutes the signal.

## What this adds (beyond Business Profile's JSON-LD)

Business Profile already owns the **LocalBusiness / Service + AggregateRating JSON-LD** derivation (head
channel, discoverability pack). This plan is the **body-side** local signals plus the richer schema shape:

### 1. Richer LocalBusiness JSON-LD (elaborates the Business Profile schema)

The full shape a local page wants — more than the base LocalBusiness:

- **Specific `@type`** by category — `MassageBusiness`, `Dentist`, `Plumber`, `HomeAndConstructionBusiness`,
  … derived from the service/product category, not a generic `LocalBusiness`. (Maps to the category taxonomy
  in plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md — a category → schema.org type table.)
- `image[]` — multiple, localized (entrance, room, etc.), the same assets used on the page.
- `@id` (stable business URI), `url`, `telephone`, `priceRange`.
- `address` (`PostalAddress`: street / locality / region / postal / country).
- `geo` (`GeoCoordinates`: lat/long) — from the profile's place coordinates.
- `openingHoursSpecification[]` — from the profile's hours.

All derived from the Business Profile; **never hand-entered on the page** (same principle as Product JSON-LD).

### 2. Localized alt text

For a page tied to a business, image alt should weave in the business name + locality **naturally, not
stuffed**: describe what a screen-reader user / crawler needs, *then* the local anchor. Template shape:

`<what the image shows> at <Business Name> in <City>, <Region>`

e.g. `alt="Licensed massage therapist performing a Swedish massage at Luxe Spa in St. George, Utah"`. The
renderer already fills alt from data (Phase 4 slice 2); this extends it to append the NAP anchor **when the
page has a linked business** and the alt isn't already localized. DTC/product pages keep the plain
product-name alt (no business = no local anchor).

### 3. `<figure>` + `<figcaption>` semantic bundling

Wrap key images in `<figure>` with a visible `<figcaption>` — crawlers weight text immediately surrounding an
image, and a caption can carry NAP the alt shouldn't overstuff:

```html
<figure>
  <img src="..." alt="The tranquil reception area inside Luxe Spa" width="800" height="533" loading="lazy">
  <figcaption>Welcome to Luxe Spa, located in suite 1E at 75 S 100 E in downtown St. George, UT.</figcaption>
</figure>
```

The element taxonomy already lists `figure` as a semantic wrapper (plans/SEMANTIC_HTML.md); this uses it for
hero / gallery images on business pages, with a derived caption. Product pages don't need captions.

### 4. Image dimensions (`width`/`height`)

Every `<img>` gets intrinsic `width`/`height` so the browser reserves space (no CLS) and the crawler gets
dimensions. This **overlaps Phase 4 slice 3 (CLS / reserved image dimensions)** — build it there; it's a
local-SEO win too. Renditions have known dimensions (IMAGE_RENDITION_WIDTHS), so this is derivable.

### 5. Localized image filenames (nice-to-have)

`swedish-massage-st-george.jpg` beats `IMG_4821.jpg` for image search. This touches the upload pipeline (the
processor names renditions by key today), so it's the lowest-priority item and may not be worth the churn —
noted for completeness.

## Consistency is the deliverable

The concrete win is **one NAP, everywhere it appears**: JSON-LD `address`/`geo`, the legal/contact footer,
figcaptions, and alt anchors all read from the same Business Profile. A future page-health check (Phase 4
family) could warn when a business page is missing NAP, or when NAP drifts between surfaces.

## Dependencies & phasing

- **Hard prerequisite:** plans/BUSINESS_PROFILE_AND_GBP.md P1 (canonical NAP + geo + hours). Nothing here
  works without it.
- Then: (a) richer LocalBusiness JSON-LD with the category→type table + geo + hours; (b) localized alt +
  figcaption on business pages; (c) width/height (shared with Phase 4 CLS slice).
- The category→schema.org-type mapping is a small data table reusing the product-category taxonomy.

## Open decisions (when we build this)

- The **category → schema.org `@type`** table (MassageBusiness, Dentist, Plumber, …) and its default when a
  category has no specific type (fall back to `LocalBusiness`).
- How aggressively to localize alt (every image, or just hero/gallery) without tipping into keyword stuffing.
- Which images get a `<figure>`/`<figcaption>` (hero + gallery vs all).
- `geo` source — manual lat/long on the profile, or geocode the address at profile save.
- Whether localized filenames are worth the upload-pipeline change.

## Ties

- plans/BUSINESS_PROFILE_AND_GBP.md — the NAP/geo/hours source and the base LocalBusiness JSON-LD. **Hard dep.**
- plans/SEMANTIC_HTML.md — `<figure>`/`<figcaption>` as declared semantic wrappers.
- plans/LANDING_PAGE_GOAL_COMPOSITION.md — Phase 4 alt-text (extends it for local) and the CLS/dimensions slice.
- plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md — the category list a category→schema-type table reuses.
- plans/LANDING_PAGE_DEFAULT_COPY.md — proper default copy; the local anchor is part of good default copy.

## Status

Not built. Recorded 2026-07-17 at user request — local pages should carry consistent NAP + local signals
(LocalBusiness schema, localized alt, figcaptions, image dimensions). Gated on Business Profile P1.
