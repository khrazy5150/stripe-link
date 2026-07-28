# Offer Semantic Model — P4: AI Enrichment + New Consumers

Status: **design, not built.** P1–P3 shipped to prod (deterministic core + slug/label/title/description/
breadcrumb, all coherent). P4 is the final phase of `OFFER_SEMANTIC_ANALYZER.md` — the point where the model
stops being SEO plumbing and becomes the shared **meaning layer for AI, advertising, and marketplaces**. That
is the payoff of the domain-agnostic design: one canonical *"what is this offer?"* now feeds channels far beyond
Google's crawler.

> **Tagged to [`AI_AND_COMMERCE_ARCHITECTURE.md`](AI_AND_COMMERCE_ARCHITECTURE.md).** The AI enrichment tier does
> **not** introduce its own AI stack — it is another consumer of the **provider adapter** (that plan's A.1/A.2)
> and the versioned **generation policy** (A.5). The ad-copy / AI-content consumers below *are* the "AI content"
> branch of that plan, now reading a real model instead of an ad-hoc brief.

---

## What P1–P3 already gave us (the input to P4)

`analyze_offer(offer, products_by_id) -> OfferSemanticModel`, split into **`facts`** (stable values) and
**`interpretation`** (opinions: `key_concepts` weights, per-field `confidence`, `source`, `version`). Today
`source` is always `"deterministic"` and several fields are intentionally empty (`intent.audience/urgency/
acquisition`, deep `taxonomy`, name-extracted `attributes`). Consumers already **degrade gracefully** on missing
fields. P4 fills those gaps with an LLM and adds consumers that need them.

---

## The dependency that reorders P4

The enrichment tier calls the LLM. That means it depends on the **provider adapter** — BYO per-tenant keys
(A.1), the normalized `generate_structured(prompt, json_schema, provider, model) -> validated object` (A.2), and
the versioned generation policy (A.5) — **none of which are built yet**. So P4 splits along one axis: *does this
piece need the LLM?*

| Track | Needs LLM? | Gated on | Buildable today? |
|---|---|---|---|
| Model schema + cache (P4.0) | no | — | **yes** |
| AI enrichment tier (P4.1) | **yes** | AI_AND_COMMERCE Phase 1 (provider adapter) | no |
| Ad-copy generator (P4.2a) | yes | P4.1 (best) or deterministic model | partial |
| Merchant feed (P4.2b) | **no** | `SITE_OBJECT.md` (verified domain, canonical, Organization) | when Site lands |
| AI content (P4.2c) | yes | AI_AND_COMMERCE Part A page-gen | no |

**Consequence:** build the provider adapter **once** (in AI_AND_COMMERCE Phase 1) and let both the page-generator
and the semantic enrichment consume it — never a second adapter. And note the **Merchant feed reads the
deterministic model**, so it can ship on the Site object alone, without any AI. Enrichment *improves* the feed;
it isn't required for it.

---

## P4.0 — Model schema + cache (foundation; no AI, no Site dependency)

Cheap, unblocks everything, ship first.

1. **Formalize `schemas/OfferSemanticModel.schema.json`.** P1 declared the shape in code; make it a real JSON
   Schema. This is the **contract the LLM's structured output is validated against** (A.2 needs a schema to
   validate) and the guarantee consumers rely on.
2. **`validate_semantic_model(model)`** mirroring `validate_page_document` — used on AI output and in tests.
3. **Cache field `offer.semantic_model`** denormalized at save (`{facts, interpretation}` with `source`,
   `version`, `generated_at`), recomputed deterministically on read when absent (the caching note in
   `OFFER_SEMANTIC_ANALYZER.md`). Invalidate on any offer/product/brand change. Deterministic recompute is
   fast, so the cache exists **only** to preserve the *AI* enrichment (expensive to recompute) — a purely
   deterministic model never needs the cache.

---

## P4.1 — AI enrichment tier (gated on the provider adapter)

`enrich(model, context, provider) -> OfferSemanticModel` — same schema in, same schema out, `source="ai"`.

### What the AI enriches — SOFT meaning only
- `interpretation.key_concepts` — tuned weights + **associative** terms the deterministic tokenizer can't reach
  ("smoothies", "post-workout", "gift for dad").
- `intent.audience / urgency / acquisition` — the deliberately-empty broad-intent fields.
- `taxonomy.hierarchy` — deepen the shallow single-level category into a real tree
  (`Health → Supplements → Protein → Whey Protein`).
- `attributes` — extract flavor/size/quantity from product names into structured `{name, value}` facts.

### What the AI must NEVER touch — HARD, verifiable, or markup-eligible facts
Brand name, `gtin`/`mpn`/`sku`, price, the entity **identity** that becomes `Product` markup, and anything
rating-related stay **deterministic / tenant-sourced.** This is the P3 lesson made a rule: fabricated verifiable
facts are a Google structured-data **and** FTC violation (the same reason we never emit a hand-typed
AggregateRating). **The AI enriches concepts, not claims.** Enforced structurally — `enrich()` may only write to
the soft fields above; it overlays interpretation + soft facts onto a deterministic base it cannot overwrite.

### Mechanism
- One `generate_structured(prompt, OfferSemanticModel.schema, provider, model)` call (A.2), **validate → bounded
  repair** loop (like page-gen A.3.4).
- **Graceful degradation is the default:** no provider connected, AI error, or low confidence → keep the
  deterministic model untouched. A tenant who never connects AI still gets the full P1–P3 experience.
- **Cost + caching:** runs at **save-time only** (async job or the on-demand button below), cached on
  `offer.semantic_model`; **never per render**. Cost is the tenant's (their key — A.1).
- **Versioned + A/B:** the enrichment prompt is part of the versioned `generation_policy` (A.5); enrichment
  policies A/B-test on the existing engine.
- **Security:** scraped/tenant text is untrusted **data, not instructions** (A.6 prompt-injection defense);
  per-tenant rate limits.

---

## P4.2 — Consumers

### P4.2a — Ad-copy / marketing-asset generator (AI; lowest-risk first consumer)
Google RSA / Meta / TikTok / Amazon ad **headlines, descriptions, keywords** as validated variants from the
enriched model (`subject_from_model` → headline seed, `key_concepts` → keywords, `intent.audience` → tone,
`attributes` → specifics). Ad copy is **generated, not verifiable markup**, so it is the safest place to debut
the AI tier. Reuses `generate_structured` against a per-channel asset schema (RSA ≤30-char headlines, etc.). A
**deterministic keyword export** (`key_concepts` → seed keywords, `taxonomy` → categories) works off today's
model with no AI — ship that as the floor, let P4.1 raise it.

### P4.2b — Merchant feed / Google Merchant Center (deterministic; gated on the Site object)
A product feed (hosted scheduled file first; Content API later) so offers appear in **Google Shopping / free
listings** — a concrete acquisition channel. Reads:
- **from the model:** title (`subject_from_model`), description, `google_product_category` (from `taxonomy`),
  `product_type` (from `key_concepts`/taxonomy);
- **from the product (never the AI):** `brand`, `gtin`, `mpn`, `sku` (already shipped in `ON_PAGE_SEO`
  Phase 1), price, availability, image;
- **from the Site:** canonical `link`, the Organization identity.

**Depends on `SITE_OBJECT.md`** (a feed needs stable indexable canonical URLs + a verified domain + Organization
— the same gate as indexable SEO markup). **Multi-entity rule (from P3):** a bundle/listicle emits **N feed
items, one per real product** — the abstract bundle is *not* a GMC product, exactly as `product_json_ld` names
real products, not "… Bundle."

### P4.2c — AI content (closes the loop with the page generator)
Product descriptions, benefit headlines, email / sales-script copy generated from the model — the point where
`AI_AND_COMMERCE_ARCHITECTURE.md` Part A stops passing an ad-hoc "brief" and reads the **canonical model**
instead. Folds into that plan's generation pipeline rather than standing alone.

---

## Guardrails (P4-specific, atop the model's existing ones)
- **AI enriches meaning, never verifiable/markup-eligible facts** (brand/gtin/price/rating/entity identity).
- **Deterministic is always the fallback** — the AI tier is strictly additive; removing it degrades to P1–P3.
- **AI output is schema-validated** against `OfferSemanticModel.schema.json`, with bounded repair, versioned,
  A/B-able.
- **Outbound assets (feed, ads) inherit the SEO posture:** publishing is deliberate; never fabricate; a bundle
  fans out to real products, not an invented one.

---

## Phasing (P4 internal; cross-plan gates called out)
1. **P4.0 — schema + `validate_semantic_model` + `offer.semantic_model` cache.** No deps. Ship now.
2. *(gate: AI_AND_COMMERCE Phase 1 — BYO keys + provider adapter + generation policy)*
3. **P4.1 — AI enrichment tier** (soft fields only; deterministic fallback; cached at save).
4. **P4.2a — Ad-copy generator** (first AI consumer; deterministic keyword export as the floor).
5. *(gate: `SITE_OBJECT.md`)* **P4.2b — Merchant feed.** AI-independent — may land **before** P4.1 if the Site
   object ships first.
6. **P4.2c — AI content** folded into the AI_AND_COMMERCE page-gen pipeline.

---

## Open decisions (recommendation first)
1. **Enrichment trigger — on-demand button vs auto-at-save.** *Recommend:* an **"✨ Enhance with AI"** button
   first — tenant-triggered, cost-visible, human-in-the-loop (A.5); auto-at-save later once trusted.
2. **Merchant feed transport — hosted file vs Content API.** *Recommend:* **hosted scheduled feed file** first
   (no per-tenant OAuth); Content API when per-tenant push is worth the auth cost.
3. **Do enriched soft facts write back to the Product?** (e.g., extracted flavor/size.) *Recommend:* **no** —
   the model stays *derived*; never mutate the catalog from an AI guess. Extraction lives on the model only.
4. **Bundle in the Merchant feed — one item or N?** *Recommend:* **N** (one per real product), consistent with
   P3's Product-markup rule.

---

## Relationship to other plans (the tags)
- **[`AI_AND_COMMERCE_ARCHITECTURE.md`](AI_AND_COMMERCE_ARCHITECTURE.md)** — **shared AI stack.** Enrichment
  reuses the provider adapter (A.2), BYO keys (A.1), generation policy (A.5), resolver precedence (A.4),
  security (A.6). P4.2a/c *are* that plan's "AI content" reading the model. Build the adapter once.
- **`SITE_OBJECT.md`** — the Merchant feed's gate (verified domain, canonical, Organization).
- **`ON_PAGE_SEO_REQUIREMENTS.md`** — the product identifiers (brand/gtin/mpn/sku) the feed consumes already
  shipped here.
- **`REVIEWS.md`** — review markup stays deterministic/verified; the AI tier is explicitly forbidden from
  fabricating ratings.
- **`OFFER_MODEL_REDESIGN.md`** — `purchase_opportunities` normalization is the model's input.
