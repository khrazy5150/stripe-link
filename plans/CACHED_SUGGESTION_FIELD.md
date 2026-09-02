# Cached suggestion field — fetch once per scope, filter locally

**Status:** SHIPPED 2026-09-02. `composables/useCachedSuggestions.js`, consumed by the product category
field; `/product-categories` gained `?limit=` so the whole scoped set can be fetched.

## 1. Why this exists

`plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md` line 90 already asked for it:

> "The full promoted set is small and slow-changing, so the client **may fetch it once and filter locally
> rather than hitting the API per keystroke**."

It was never implemented. Measured 2026-09-01: `searchCategories()` calls `/product-categories` on every
focus and on every 180 ms typing pause, with no cache in the util, the component, or `apiRequest`. Each
call is a Lambda invoke plus a **full DynamoDB scan** of contributed categories. Fast continuous typing
collapses to one request; typing with pauses — what people do while THINKING about a category — produces
several.

Note the word "may". A permissive requirement is one nothing enforces, which is why it fell out. This is
the second dropped requirement found today (the first: service-only offer naming, from 95da715). Both were
written down and neither had a test.

## 2. The principle

**Fetch once per scope, filter locally, refetch when the scope or the field reopens.**

- **Scope key.** The cache is keyed by whatever narrows the server result — for categories that is
  `product_type`. A single global cache would be wrong: switching type must not show the old type's list.
- **Refetch on FOCUS, not on keystroke.** This is what keeps it correct. A tenant's own newly-typed
  category must reappear next time they open the field; refetching per open gives fresh data at the only
  moment staleness is observable, and costs one request per field-open instead of one per pause.
- **Local filter while typing.** Same normalized substring match the server uses.
- **Server fallback.** If the local filter returns nothing and the query is longer than what the cached
  page covers, ask the server — the cache may be a capped page rather than the whole set.
- **Degrade to a plain text field on error.** Already the behaviour; keep it.

## 3. Shape

A composable, not a Vue component — the markup differs per field (the category field has a "your
category" tag, a free-text commit on blur, a selected state), but the FETCH/CACHE/FILTER logic is what
repeats.

    const { suggestions, loading, open, search } = useCachedSuggestions({
      fetch: (scope) => searchCategories("", scope),   // full set for a scope
      filter: (items, query) => items.filter(...),      // normalized substring
      scope: () => form.product_type,                   // cache key; changing it invalidates
    })

`open()` on focus (refetches if the scope changed or the cache is empty), `search(q)` on input (local,
no network).

## 4. Honest scoping — one consumer today

Surveyed the dashboard: **the product category field is currently the ONLY server-backed typeahead.**
Everything else filters already-loaded data or is a plain select. So this abstraction has exactly one
caller right now.

That argues for extracting it FROM the category field rather than designing it for imagined consumers:
keep it thin, let the second consumer reshape it. Plausible second consumers, none of which exist yet:
product tags, a brand picker fed by Business Profile, and anything the Form Builder adds.

**Do not build a generic search framework here.** The value is the caching principle applied consistently,
not a configurable engine.

## 5. Also worth fixing while in here

`ProductCategoriesRepository.list_all()` is a full table scan per request. The code says so deliberately
("the table is small and slow-changing… a scan is fine"), and that is true today. It is a documented
assumption that stops being true silently as the contributed tail grows — the same shape as the
unbounded list endpoints in `plans/OFFER_ITEM_VISIBILITY.md`. Caching on the client reduces how OFTEN it
runs, which buys time; it does not make the scan bounded. Revisit with a query-by-prefix or a cached
projection when the contributed table is measurably large.

## 6. Ties in

- `plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md` — the origin of the requirement.
- `plans/OFFER_ITEM_VISIBILITY.md` — same family: what filters where, and who holds the data.


## 7. What shipped, and the thing the plan missed (2026-09-02)

`useCachedSuggestions({ fetchAll, filter, scope })` — `open()` on focus, `search(q)` on input, local only.

**The plan's gap:** it assumed the endpoint could return "the full set for a scope". It could not —
`search_suggestions` caps at 20, a typeahead page, and there are 28 curated categories alone. Caching that
response and filtering locally would have been fast and silently wrong, missing ten categories. So the
endpoint learned `?limit=` (default 20 unchanged, capped at 500) and the client asks for the whole scope.
**Filtering client-side is only correct over a complete set** — that precondition is the whole design, and
it was not in the plan.

**Stale-while-revalidate**, beyond the plan: the cached list renders immediately on open while the refresh
is in flight, so the menu never blanks. A response for a scope the user has since left is discarded, and a
scope change drops the previous list rather than showing it while loading — a digital product must not be
offered a physical product's categories, even for a frame. Both are tested with a deliberately slow fetch.

**Parity is enforced, not asserted in prose:** `filterCategories` mirrors `search_suggestions`' matching
(normalized substring against key OR normalized label), and a test runs the JS filter and a real server
query over the same terms — empty, whitespace, uppercase, multi-word — requiring identical keys.

**Still true:** `ProductCategoriesRepository.list_all()` remains a full table scan per request. Caching
reduces how OFTEN it runs, not its cost. Revisit with a query-by-prefix or cached projection when the
contributed table is measurably large (2 rows in dev, 0 in prod today).
