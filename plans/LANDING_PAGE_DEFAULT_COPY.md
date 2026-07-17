# Landing Page Default Copy — proper titles, headlines, brand, description by default

## Why

Out of the box the software produces **useless customer-facing copy** that a tenant is forced to fix. One
internal label leaks into four public fields that each want something different. A tenant who touches nothing
should still ship a solid page; today they ship a broken one.

Worked example (real, from dev):

- Offer name is auto-generated as `<product name> + "Single Offer"|"Bundle"` — e.g. **"NAD Supplement Single
  Offer"** (`Offers.vue:1477/1486`). That suffix is an *internal disambiguation label* so a tenant can tell
  two offers apart in the Offers list. It is not copy.
- The landing page then reuses that one string as, all at once:
  - the **brand label** (site-name chip) → "NAD SUPPLEMENT SINGLE OFFER"
  - the **hero `<h1>`** (should be the benefit thesis) → "NAD Supplement Single Offer"
  - the **`<title>`** (should target search intent) → "NAD Supplement Single Offer Landing Page"
  - the **`<meta description>`** → "NAD Supplement Single Offer"

So the brand, the page's single H1, the SEO title, and the description are all the same internal label —
incongruent, keyword-poor, and repetitive. This is the legacy-inherited rule: *offer name = product name +
offer type, and everything on the page derives from the offer name.*

## The goal

The software fills in **proper, distinct defaults** for each field, derived from the product (and, later, the
Business Profile), so an untouched page is already good. The tenant edits to improve, not to repair.

## The four fields are different things (the convention to nail down)

The core work is a **naming convention** that separates concerns. Each field has a distinct job:

| Field | Channel | Job | Bad default today | Shape of a good default |
|---|---|---|---|---|
| **Brand** (`brand_label`) | body chip / `head` `<title>` suffix | Who is selling (business/brand name) | "NAD Supplement Single Offer" | The tenant's business name, or the product's brand ("Fulimiks"), never the offer label |
| **Headline** (hero `<h1>`) | body | The benefit *thesis* (why buy) | product name verbatim | Benefit-led, derived from product benefit/description ("Support Healthy Aging with NAD+ 1500mg") |
| **`<title>`** | head | Search intent / keywords | "… Single Offer Landing Page" | `<Product> — <key benefit/spec> \| <Brand>` (keyword-first, distinct from H1) |
| **`<meta description>`** | head | The SERP snippet, ~150 chars | "Single Offer" | A real sentence from the product description, trimmed to length |

This mirrors the split already established in plans/SEMANTIC_HTML.md (**`<title>` ≠ `<h1>`**: the title targets
keywords, the H1 is the benefit thesis) and plans/SOCIALITE_PARITY.md (brand/SEO-title `head` vs hero-headline
`<h1>` body). This phase makes those *defaults* good, not just the structure correct.

## Set at the offer, from the start

The offer is the contract the page derives from ([[project_conversion_context]]), so the proper copy should
originate **at offer creation**, not be patched at render time:

- The offer keeps an **internal name** (the disambiguation label — "NAD Supplement Single Offer" is fine
  *there*, in the Offers list) **separate from customer-facing copy**. Two different fields.
- The offer gains derived-but-editable defaults for headline / title / description / brand (or they live on
  `offer.presentation`, which already holds `headline`/`cta_label`). Generated once from the product on
  offer create; the tenant can override.
- The landing page consumes those fields instead of re-deriving from the internal offer name. The
  `render_seo_title` / brand / hero defaults stop falling back to `<offer name> + "Landing Page"`.

This also front-loads quality for **Build with AI** — the AI improves already-solid copy rather than starting
from "Single Offer".

## Scope of the fix

- **Offers builder**: stop overloading `offer.name`. Introduce (or populate) distinct headline / seo_title /
  description / brand fields with product-derived defaults; keep the internal disambiguation name for the list.
- **Renderer**: `<title>`, `<meta description>`, `brand_label`, and the hero headline read the proper fields
  and only fall back to the internal name as a last resort (or better, to a product-derived value).
- **Migration**: existing offers/pages still store the internal name in the copy fields — decide whether to
  backfill derived defaults or leave existing pages as-is (tenants can regenerate).

## Open decisions (nail down when we build this)

- The exact **title template** — `<Product> — <benefit> | <Brand>`? Derived from which product fields
  (name, `product_category`, a spec, description first clause)? Templated vs. AI-written vs. both.
- The **headline** derivation — benefit-led rephrasing needs either a template ("<Benefit verb> with
  <Product>") or AI; a naive template can read awkwardly.
- **Brand source** — tenant business name (needs plans/BUSINESS_PROFILE_AND_GBP.md), product brand field
  (doesn't exist yet), or tenant profile display name.
- Whether defaults are **generated once and stored** (editable, stable) or **derived live** (always fresh but
  overwrite-on-edit friction). Leaning stored-once, like the SKU generator.
- **Migration** of existing offers/pages.

## Ties

- plans/SEMANTIC_HTML.md — the `<title>` ≠ `<h1>` split; this phase supplies the *default content* for that
  structure.
- plans/LANDING_PAGE_GOAL_COMPOSITION.md — the "SEO is derived, not hand-entered" principle; a future phase
  there points here.
- plans/BUSINESS_PROFILE_AND_GBP.md — the canonical brand/business name a good `brand` default needs.
- [[project_ai_commerce_direction]] — solid defaults are the baseline the AI improves on.

## Status

Not built. Recorded 2026-07-17 as a future phase (a tenant-visible quality gap: default titles/headlines/
brand/description are the offer's internal label, not real copy).
