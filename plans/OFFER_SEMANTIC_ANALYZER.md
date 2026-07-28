# Offer Semantic Model + Analyzer

Status: **design locked v2 (author review incorporated 2026-07-28), not built.** The canonical understanding of
an offer — *what is this?* answered exactly once, for the whole platform. NOT an SEO utility. Deterministic core
now; AI enrichment is a later, clean upgrade over the same object. The `smart_offer_slug` shipped 2026-07-28
(handlers/offers.py) is the pilot consumer this absorbs.

> ## The analyzer emits MEANING only.
> It contains **no SEO, Google, channel, or formatting logic**. It understands offers. Downstream generators
> consume the understanding and own their own output. This is the heart of the architecture — the model is
> domain-agnostic; the consumers are domain-specific.

## Mission (domain-agnostic)

Every subsystem that acts on an offer first asks the same question — *what is this offer?* Today the slug, the
title, the JSON-LD, the breadcrumb, and the OG tags each answer it **independently** from the raw offer, so they
drift (the observed slug-vs-label divergence; mixed-category bundles reading awkwardly). Tomorrow the same
question is asked by AI content, a Merchant Center feed, Google/Meta/TikTok/Amazon listings, email campaigns,
recommendations, and analytics. The `OfferSemanticModel` answers it **once**.

```
ExpandedOffer
    │
    ▼
OfferSemanticAnalyzer.analyze()
    │
    ▼
OfferSemanticModel  ── canonical understanding ──►  ├── SEO (slug/title/desc/schema/breadcrumb/OG/canonical)
                                                    ├── Rendering (landing page)
                                                    ├── Commerce (funnel/pricing tooling, analytics)
                                                    ├── AI (content, sales scripts)
                                                    ├── Search / Recommendations / Related offers
                                                    ├── Merchant Feeds (Google Merchant Center)
                                                    └── Advertising (Google/Meta/TikTok/Amazon assets)
```

## What already exists (reuse, do not rebuild)

- **Normalizer** ≈ `expand_offer()` → the `ExpandedOffer` (follows `product_id` refs, snapshots products,
  resolves `single_unit_price` per item) + the opportunities adapter (`landing_presentation`,
  `derived_offer_type`) that flattens shape + brand resolution + `product_category`. This is the "resolve the
  messy details into a consistent view" layer. It exists; the Analyzer consumes it.
- **Generators** exist and today each re-derive meaning directly: `document_title()` (Buy-formula), the meta
  description builder, `render_structured_data` (Product/Organization JSON-LD), OG/Twitter tags, breadcrumb,
  `canonical_page_url`, brand resolution. This is a **consolidation** — insert the model, re-point generators
  one at a time — not a greenfield build.

## The model — FACTS vs INTERPRETATION (separated on purpose)

Facts are values the offer *has*. Interpretation is *opinion* — weights, rankings, confidence produced by an
algorithm that will change. Keeping them in separate blocks means improving the weighting/confidence model
never touches the facts, and consumers can choose to trust only facts or facts + interpretation.

### `facts` — stable, plain values
```
entities: {
  primary:   { type: product|service|bundle|listicle|membership|lead_generation, name },
  secondary: [ { type, name }, ... ]        # NMN + Resveratrol + Quercetin: all meaningful, all exposed
}
brand?: { name }
taxonomy: { hierarchy: [ "Health", "Supplements", "Protein", "Whey Protein" ] }   # recursive, variable depth
intent: {
  commercial:  transaction | lead_generation | informational,
  audience:    consumer | business | ... ,
  fulfillment: physical | digital | service | scheduled,
  acquisition: direct | ... ,
  urgency:     standard | ...
}
commerce: {
  pricing_model:  single | tiered | ... ,
  purchase_model: one_time | subscription | ... ,
  funnel: { landing: bool, order_bump: bool, upsells: N, downsells: N }
}
attributes: [ { name, value } ]              # flavor, size, quantity-pricing — FACTS, unweighted
```

### `interpretation` — opinions, isolated
```
interpretation: {
  key_concepts: [ { value, weight } ],       # the offer's important concepts (renamed from "identity_terms" —
                                             # domain-neutral so it feeds AI/ads, not just SEO)
  confidence: { "taxonomy.hierarchy": 0.6, "entities.primary": 1.0, ... },   # PER-FIELD, not one global score
  source: "deterministic" | "ai",
  version, generated_at
}
```

## Deterministic core (v1): populate the subset, shape the whole

The schema above declares the **full** shape. v1 populates only what's honestly derivable; the rest is present
but empty/low-confidence, and consumers must **degrade gracefully** on missing fields. This is the guardrail
against speculative over-build: ambition in the interface, minimal implementation.

| field | deterministic source (now) | AI / richer-schema (later) |
|---|---|---|
| `entities.primary` | `derived_offer_type` + resolved name | a natural "what this is" phrase |
| `entities.secondary` | the bundle's other landing products | de-noised, ranked |
| `brand` | `offer.presentation.brand` (already resolved) | — |
| `taxonomy.hierarchy` | shallow: humanized `product_category` (± a category→parents map) | deep, multi-level tree |
| `intent.commercial` | `product_intent` | — |
| `intent.fulfillment` | `product_type` / product `fulfillment` | — |
| `intent.audience` / `acquisition` / `urgency` | — (empty in v1) | AI or tenant input |
| `commerce.*` | ALL derivable — pricing_model (tiers), purchase_model (recurring), funnel counts (contexts/opportunities) | — |
| `attributes` | quantity-pricing, subscription (from prices) | flavor/size extracted from names |
| `interpretation.key_concepts` | tokens from names + category + brand, coarse weights | tuned weights, associative terms ("smoothies") |
| `interpretation.confidence` | coarse (1.0 facts / lower heuristics) | per-field calibrated |

`commerce` is fully deterministic and useful far beyond SEO (analytics, funnel tooling) — expect it to grow
fastest. `intent` is deliberately broad now (mostly empty) so email/ads/marketplace generators have a home to
read from later without a schema change.

## Consumers (generators)

Each reads the model, owns its formatting:
- **SlugGenerator(semantic)** — PILOT. `entities.primary` + top `key_concepts` (+ `secondary` when it wants) +
  a bundle/collection descriptor; short; then `unique_offer_slug` for the `-N` net. Absorbs `smart_offer_slug`.
  Single source for BOTH slug and the offer **label** so they can't diverge (the observed bug).
- **TitleGenerator** — Buy-formula over `entities.primary.name` + primary concept (re-point `document_title`).
- **SchemaGenerator** — `taxonomy` → schema.org `category` + specific `@type`; `entities` → multi-product feeds.
- **BreadcrumbGenerator** — `taxonomy.hierarchy` renders almost directly (the hierarchy IS the breadcrumb).
- **MetaDescription / OpenGraph / Canonical** — re-pointed.
- **Future (non-SEO):** AI content, Merchant feed, Google/Meta/TikTok/Amazon assets, email, recommendations.

## Caching / regeneration
Compute-on-read alongside `expand_offer` (the model is a pure function of the ExpandedOffer), and OPTIONALLY
cache `offer.semantic_model` at save (like the ExpandedOffer denormalization) if the AI tier makes recompute
costly. Invalidate on any offer/product/brand change. The dashboard reads the same model (server-authoritative)
so previews match published output — the slug JS-mirror pattern, generalized.

## Phasing (low-regression)
- **P1 — Analyzer core + SlugGenerator (pilot).** Deterministic `analyze()` populating the derivable subset +
  `SlugGenerator`; retire `smart_offer_slug` into it; unify the offer LABEL with the slug off
  `entities.primary`. Fixes the mixed-bundle slug + the label divergence. Tiny blast radius. JS mirror updated.
- **P2 — Title + MetaDescription** re-pointed (coherent label/slug/title/description).
- **P3 — Schema / Breadcrumb / OpenGraph / Canonical** re-pointed, with **golden-output regression tests
  written FIRST** so live SEO markup can't silently regress.
- **P4 — AI enrichment tier** (LLM fills `interpretation` + nuanced facts; validated against the schema;
  deterministic fallback always), then new consumers: Merchant feed, ads assets, AI content.

## Guardrails
- The model is **meaning only** — never formatting, URLs, routes, indexing, or channel logic.
- **Facts vs interpretation** stay separated; opinions (weights/confidence) never leak into facts.
- Consumers **degrade gracefully** on missing / low-confidence fields (v1 leaves many empty).
- Re-pointing a shipped SEO generator is only safe behind a golden-output test of its current markup.
- The model is **versioned**; AI output is validated against the schema; deterministic is always the fallback.

## Relationship to other plans
- **AI_AND_COMMERCE_ARCHITECTURE.md** — AI page/content generation consumes the model (closes the loop).
- **ON_PAGE_SEO_REQUIREMENTS.md** — the shipped title/desc/schema/OG/canonical generators become consumers.
- **OFFER_MODEL_REDESIGN.md** — `purchase_opportunities` + the adapter are the Normalizer's input.
- **SITE_OBJECT.md** — slug/canonical routing + indexing (the model feeds keywords, not routes).
- **BUSINESS_PROFILE_AND_GBP.md / REVIEWS.md / LOCAL_SEO_SIGNALS.md** — taxonomy→`@type`, local signals, review
  markup are downstream consumers. **Future advertising/marketplace** (Merchant/Ads/Amazon/TikTok) too.
