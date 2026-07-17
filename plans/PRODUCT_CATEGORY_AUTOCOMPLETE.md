# Product Category Autocomplete (organically-grown, shared taxonomy)

## Why

A fixed dropdown doesn't scale and forces anything unrecognised into "Other" — bad for SEO (the value
becomes schema.org `category`) and a hard ceiling for AI-generated products, which shouldn't be boxed into a
hand-maintained list. Replace the dropdown with an **autocomplete over a shared, growing taxonomy**: the
tenant types, sees matching existing categories, and if none fit, their own text is used. The list grows
organically instead of us inventing categories up front.

## The core tension: a shared list feeds PUBLIC data

The shared suggestion list is cross-tenant, and `category` is emitted into JSON-LD on every tenant's public
pages. So raw "add on submit" is a pollution/abuse vector — one tenant's typo (`Diietary Supplment`), junk,
or abuse string would be suggested to everyone and could surface in others' SEO markup. **The tenant's own
value and the shared list are therefore two different things:**

- **Private, instant:** whatever the tenant types is stored on *their* product immediately. Never gated,
  never blocked. Their page renders that string.
- **Shared, gated:** a value only becomes a *suggestion for other tenants* once it clears a bar.

## Promotion model: usage threshold, auto-promote (decided)

A typed category becomes a shared suggestion once **N distinct tenants** have used it (start N = 3). No admin
work; typos and junk never reach the threshold because nobody else independently types the same mistake; AI
near-duplicates stay private until genuinely popular. Curated seeds (today's 25) are promoted from day one.

Distinct-tenant counting is free and correct via a DynamoDB **string set**: each category item holds a set of
tenant_ids, and `ADD` is atomic and idempotent (re-adding a member is a no-op), so a tenant using a category
twice counts once. (Scale note: a category used by thousands of tenants would grow the set toward the 400KB
item limit; shard the counter if that ever bites. Fine at current scale.)

## Categories are scoped by product type

The choices differ by what the product *is*: a service should be offered "Plumbing" / "Consulting", not
"Apparel"; a supplement shouldn't see "Software as a Service". So every category declares which of the three
product types (`physical` / `digital` / `service`) it applies to, and the autocomplete only suggests
categories valid for the product being edited. A tenant-contributed category records the type(s) of the
products that used it, so it surfaces under the right type for others. "Other" is valid for all three.

## Admin: adding curated categories (plumbing, dental, jewelry, …)

Curated categories live in code — `_CURATED` in `src/stripe_link/domain/categories.py` — because they change
rarely and should be trustworthy (they're promoted to every tenant immediately). To add one, an admin appends
a `(label, types)` row and deploys the backend:

```python
("Plumbing", ("service",)),
("Dental", ("service",)),
("Jewelry and Accessories", ("physical",)),
```

- The **key is derived** as `normalize_category(label)`, so you never hand-write it and it can't drift from
  the label. A test asserts every curated label round-trips to its own key.
- `types` is any subset of `("physical", "digital", "service")`; use all three for a truly generic one.
- **Never change or remove an existing label's words in a way that changes its normalized key** — products
  store the key, so that would orphan them. Adding rows is always safe.
- Only `./deploy/deploy.sh <env>` is needed (backend); the autocomplete reads the list through the API.

Everything else — the long tail — arrives on its own via the usage threshold, so the curated list only needs
the common, trustworthy categories; admins don't have to enumerate the world.

## Data model

New shared (non-tenant-scoped) table, table-per-entity like `platform-config`:
`jb-product-categories-{env}`.

One item per **normalized key**:

- `category_key` (PK) — normalized: lowercased, accent-folded, non-alphanumerics -> single `_`
  (`"Dietary Supplement"` -> `dietary_supplement`). This is what dedups "Supplements"/"supplements".
- `label` — display string, first writer wins (later: most-common casing).
- `tenant_ids` — string set; its size is the distinct-tenant count.
- `status` — `seed` | `promoted` | `pending`. Promoted = seed OR `len(tenant_ids) >= N`.
- `created_at`, `updated_at`.

Seeded once from the current curated 25 (all `status: seed`).

## Storage shape on the product (compat)

Today `product.product_category` stores a **key** (`dietary_supplement`); the 15 existing products use keys,
and `humanize_category()` renders them. Going free-text, **store the normalized key** on the product too (not
the free label) — so existing products need no migration and the join to the category table is by key. The
label lives in the table, and the renderer already humanizes a key when it can't find a label. Free-text a
tenant types becomes `normalize(text)` as the stored key, with the raw text as the label if the key is new.

## Endpoints

- `GET /product-categories?q=<prefix>` — search. Returns promoted categories (seeds + threshold-cleared)
  matching the query, plus the requesting tenant's own private ones. The full promoted set is small and
  slow-changing, so the client may fetch it once and filter locally rather than hitting the API per keystroke.
- Recording usage is **not a separate call** — it happens server-side when a product is saved (the product
  handler upserts the category item and ADDs the tenant_id). Keeps the write path single and authoritative;
  the client can't inflate counts directly.

## Normalization (the other thing that's hard to change later)

One `normalize_category(text)` function, shared: lowercase, NFD accent-fold, collapse non-alphanumerics to
`_`, trim. Same helper the SKU generator already models. Without it the list fragments into
"Supplement"/"Supplements"/"supplements".

## Phasing

1. Table + seed the 25 + `normalize_category` + repository.
2. `GET /product-categories` search endpoint.
3. Product-save hook records tenant usage; promotion is derived.
4. Autocomplete component replaces the dropdown (falls back to the tenant's typed value).
5. (Later) admin view of pending/promoted; most-common-casing label; counter sharding if scale demands.

## Ties in

Feeds [[project_ai_commerce_direction]]: AI creates products and categorises them without a dropdown ceiling
or dumping into "Other"; its categories stay private until independently popular, so AI can't unilaterally
pollute the shared taxonomy. Related: the `sku` generator's normalize/accent-fold logic (same shape).
