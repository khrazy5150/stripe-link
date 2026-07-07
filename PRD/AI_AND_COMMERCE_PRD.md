# stripe-link-v2 — AI Generation & Commerce PRD

**Status:** approved for execution · **Companion:** `plans/AI_AND_COMMERCE_ARCHITECTURE.md` (design rationale)

This PRD is the execution spec. The architecture doc explains *why*; this doc defines *what ships,
in what order, and how we know it's done.*

---

## Product summary

stripe-link-v2 is an AI-assisted commerce and landing-page platform for existing SaaS tenants on
AWS, built in Python. A tenant generates a **draft** page from manual details (later: a product
URL), reviews it in the existing builder, and publishes **only by deliberate action**. AI never
emits HTML and never auto-publishes.

---

## Objectives

- Replace theme-driven page creation with a **composition/preset system** that becomes the AI
  output vocabulary.
- Add a **real media pipeline** so generated pages can attach tenant-owned assets.
- Ship a **safe AI MVP** that produces draft pages, not published pages.
- Preserve **environment isolation** so AI actions in test use dev resources and AI actions in
  live use prod resources — reusing the existing `mode` mechanism (see Environment model).
- Lay the **commerce foundation** (line-item order model, reserved tax fields) so no cart or tax
  migration is forced later.

---

## Out of scope

- **Image generation** (all phases in this PRD). Generated product imagery misrepresents real
  products; when added later it is scoped to ambient/decorative imagery only, never the product
  hero, via a decoupled platform image service.
- Cart, tax, inventory, i18n, MCP, page-view analytics, services booking, and Sites (later phases /
  deferred).
- Auto-publish (never).

---

## Principles

- AI must emit **JSON that conforms to existing schemas; it never emits HTML.**
- **One renderer, many compositions.**
- **Deterministic code decides before the model decides**, via a versioned resolver chain with the
  precedence `explicit request > tenant brand/preferences > platform defaults > AI judgment`.
  Where the model should have a say, it is handed a shortlist, not an open choice.
- **Human review is always required before publish.**
- **All platform *infrastructure* is AWS-native** (compute, storage, queues, orchestration, secrets,
  observability) with Python back-end services. **Tenant-connected AI providers are external by
  design** (BYO OpenAI/Anthropic keys); the platform-owned trial path uses **Amazon Bedrock** so the
  one credential the platform owns stays AWS-native (IAM, no stored third-party key).

---

## Environment model (applies to every phase)

The platform already isolates environments with a per-document **`mode`** field (`"test"` / `"live"`)
that routes each write to dev vs prod resources:

- `SimpleKeyRepository.table_for_mode("live") → prod_table`, else `dev_table`
  (`src/stripe_link/repositories/documents.py`).
- Checkout/base URLs derive the same way — `"live" if environment == "prod" else "test"`
  (`src/stripe_link/runtime/publishing.py`).

**AI work reuses this primitive. It does not introduce a parallel mechanism.**

- Every AI-created record — `generation_job`, and the resulting Product / Offer / Page — **carries
  the triggering `mode`** and writes through the existing repositories.
- **The `mode` is captured at trigger time and threaded through the entire async pipeline** into the
  worker and every write. A background worker must never default `mode` or drop it. This is the
  single largest isolation risk and is an explicit requirement, not an implementation detail.
- Test-triggered AI work uses dev tables, dev keys, dev resources; live-triggered AI work uses prod
  tables, prod keys, prod resources.
- Prod may support A/B testing and custom domains; dev may not. AI must be environment-aware when
  deciding which capabilities and wizard/questionnaire paths are even available.

---

## Phases

### Phase 1 — Composition / preset system

**Goal.** Refactor the builder so every current and future page is composed from sections, variants,
style tokens, and presets rather than template styles.

**Scope.**
- Collapse `TEMPLATE_STYLES` into one token-driven renderer.
- Define a section catalog with variants.
- Define a bounded token system with curated palettes, fonts, spacing, and radius (constrained, to
  avoid open-ended visual chaos).
- Create a preset library such as Clean Product, VSL, Founder-led, Social-proof heavy.
- Ensure the builder can edit composition, section order, and per-section variants.
- Make the AI output surface use the same vocabulary.

**Functional requirements.**
- Drag-reorder sections; toggle sections on/off; per-section layout variants.
- Deterministic presets reusable by AI and manual flows.
- Preserve current pages during migration; render existing tenant pages without visual regressions
  beyond accepted token changes.

**Acceptance criteria.**
- A page can be created, edited, and rendered with the new composition model.
- Existing pages continue to render after migration.
- `TEMPLATE_STYLES` is no longer the source of truth for page appearance.
- A preset can be applied and then customized in the builder.
- AI and manual flows both reference the same section catalog and token system.

> **May ship any time from Phase 1 on (independent hygiene):** actual-fee true-up — reconcile the
> estimated `stripe_fee`/`net_payout` to the **actual** value from the charge's balance transaction
> (`platform_fee` is already exact). It is not coupled to the commerce work in Phase 5 and improves
> accounting accuracy on money flowing today.

### Phase 2 — Media / asset pipeline

**Goal.** Replace proxy-based uploads with first-class tenant media stored in MediaBucket.

**Scope.**
- Implement real uploads to MediaBucket.
- Store and serve tenant-owned asset URLs for page rendering.
- Structure the asset priority chain: **provided → scraped → stock → placeholder**. (Only the
  `provided` and `placeholder` tiers are active before Phase 4; `scraped` and `stock` light up with
  URL ingestion and stock selection in Phase 4.)
- Prepare the pipeline for later AI attachment of media.

**Functional requirements.**
- Uploads create durable tenant-owned media records.
- The builder can select uploaded assets.
- AI generation can reference stored media URLs.
- Asset retrieval works in dev and prod using the correct environment resources.

**Acceptance criteria.**
- A tenant can upload an image and use it on a page.
- Uploaded media survives page refresh and page publish.
- The media pipeline is usable by the builder before AI generation launches.

### Phase 3 — AI generation MVP

**Goal.** Let tenants generate **draft** pages from manual input using connected AI providers, with
safe validation and repair. The MVP proves one thing: the model reliably emits good page JSON.

**Scope.**
- Support **BYO AI keys** first.
- Support two BYO providers at launch: **OpenAI and Anthropic**. Architect for N providers later.
- Provide a **metered platform-key trial via Amazon Bedrock** (AWS-native; no stored third-party
  key) so every tenant can test the wow moment immediately.
  - Free-tier note: Bedrock has **no durable free token allotment** — model inference is pay-per-use
    from token one (new-account promotional credits expire and are not a plan input). The trial is
    therefore kept cheap by construction: a low-cost model (e.g., Claude Haiku or Amazon Nova) and a
    small per-tenant quota.
- Add provider adapters with a normalized structured-output interface.
- Add resolvers and a versioned generation policy. Resolvers apply the precedence chain
  `explicit > tenant preferences > platform defaults > AI judgment`.
- Add manual-input generation. (URL ingestion is Phase 4 only.)
- Generate Product and Offer **deterministically** from the brief (platform owns ids, Stripe sync,
  fees; AI assists copy only).
- Validate and repair AI output against the page schema, with bounded retries.
- Save output as a **draft** in the existing builder screen.
- **Images in the MVP come from `provided` (tenant upload via Phase 2) → `placeholder` only.** Stock
  and scraped imagery arrive in Phase 4.

**AI behavior.**
- AI may choose section order and section selection.
- AI must use the tenant's environment context and operate only within the triggering `mode`
  (test→dev, live→prod); it must never assume production when triggered from test.
- **Environment-awareness rule (in scope):** AI must *know* that A/B testing and custom domains
  exist in prod and not in dev, and must not offer capabilities the current environment lacks.

**Tenant optimization intent.**
- Transactional offers optimize for conversions; lead-gen offers optimize for brand fidelity.
- The offer type informs page-generation strategy.

**Functional requirements.**
- AI generation runs as an **async job**; the tenant can poll generation status.
- AI generates **draft content only**; the tenant reviews in the existing builder before publishing.
- The platform-key (Bedrock) trial is rate-limited and quota-limited.
- **BYO-key generation is also bounded** (max concurrent / max per day per tenant) so a runaway job
  cannot spawn endlessly on the tenant's own key.
- The system stores the generation-policy version with each result.
- The system supports provider verification when a tenant connects a key.
- The system supports validate/repair retries with bounded attempts.
- The system isolates dev and prod resources based on the triggering environment (carries `mode`
  through the async pipeline per the Environment model).

**Acceptance criteria.**
- A tenant can generate a draft from manual input using OpenAI, Anthropic, or the Bedrock trial.
- A tenant in test never writes to prod resources through AI; a tenant in live only uses prod
  resources for AI-triggered actions.
- The generated draft opens in the existing builder screen and remains unpublished until the tenant
  chooses to publish.

### Phase 3.5 — AI proactive offers (fast-follow)

**Goal.** Layer proactive, environment-gated offers onto the AI flow **after** the MVP is proven, so
they never gate or widen the core generation surface.

**Scope.**
- If A/B testing is available in prod and not specified, AI may ask whether the tenant wants an A/B
  version.
- If custom domains are available in prod and not specified, AI may ask whether the tenant wants a
  custom domain; if the tenant agrees, AI follows the **same questionnaire flow as the manual
  custom-domain wizard** (reuse, do not duplicate).

**Dependencies.** Phase 3; the A/B engine; the manual custom-domain wizard flow.

**Acceptance criteria.**
- The system can ask the tenant whether to create an A/B version in prod.
- The system can ask the tenant whether to set up a custom domain in prod, reusing the manual
  wizard's questionnaire.
- These offers are absent in dev and never block draft generation.

### Phase 4 — AI expansion

**Goal.** Extend the AI system with URL ingestion, stock asset selection, critic passes, and more
providers.

**Scope.**
- SSRF-locked URL ingestion; scraped-content extraction from public sources only.
- Stock-image fallback selection (activates the `stock` tier of the Phase 2 chain).
- Critic pass to improve weak drafts.
- More providers beyond OpenAI and Anthropic.

**Functional requirements.**
- URL ingestion blocks private, metadata, and otherwise unsafe IP ranges.
- Scraped content is treated as **data, not instructions** (prompt-injection defense).
- Asset attachment follows the priority chain established in Phase 2.
- Critic pass is optional and measurable.

### Phase 5 — Commerce foundations

**Goal.** Prepare the order and offer models for listicles, carts, and tax without a migration later,
and establish an **append-only transaction ledger** as the canonical financial record (P&L,
reconciliation, tax reporting).

**Scope.**
- Promote `offer_type` to a validated field.
- Move the order model to a **line-item shape**; preserve single-product compatibility.
- Add line-level attribution (`product_id`, `page_id`, slide/source, `offer_id`, `ab_variant`).
- Reserve per-line `tax_amount` and order-level tax totals (default 0).
- Add actual-fee true-up so Stripe fee reporting matches balance transactions (if not already shipped
  as the Phase 1 hygiene item).
- Add `unit_cost` to the Product model (COGS capture) so profit is real, not aspirational.
- Build the **transaction ledger** per **[`plans/TRANSACTION_LEDGER_STRIPE_LINK.md`](../plans/TRANSACTION_LEDGER_STRIPE_LINK.md)**:
  an immutable `LedgerEntry` (sale/refund/dispute/shipping/cost) with additive signed amounts, made
  the source of truth from which order payment aggregates and refund history are **derived**
  (consolidating today's `RefundsTable` / `WebhookEventsTable` roles rather than adding a parallel
  table). Direct-charge Connect economics kept explicit (tenant P&L vs platform application-fee
  revenue); daily rollups for fast dashboards. Sequenced **on top of** the line-item model and the
  fee true-up.

**Functional requirements.**
- Existing single-product orders continue to render and reconcile.
- Each order line carries attribution data.
- Tax data is representable even when tax collection is off.
- Fee reconciliation uses actual Stripe values, not estimates, when available.
- Every financial event (sale, refund, dispute, shipping/cost) appends an immutable, idempotent
  ledger entry; order aggregates are derived from the ledger, not authored independently.
- Reports (gross, net, fees, COGS, shipping, **profit**, tax-by-jurisdiction) come from the ledger /
  rollups via date-range queries — never a full-partition scan.

**Acceptance criteria.**
- A legacy single-product order still works after the model change.
- A line-item order can be stored and retrieved without loss of attribution.
- Fee reporting can reconcile to balance-transaction actuals.
- Replaying the ledger reproduces the order payment aggregates (ledger is authoritative; aggregates
  are a rebuildable cache).
- The same financial event recorded twice yields exactly one ledger entry (idempotency).

### Phase 6 — Listicle + buy-now

**Goal.** Add a `product_carousel` section with per-slide CTA and buy-now using the existing
checkout.

**Scope.**
- Listicle as a **section, not a theme**.
- Per-slide dynamic CTA.
- Reuse existing single-offer checkout for buy-now.
- No cart primitive yet.

**Dependencies.** Phase 1 composition system; Phase 5 `offer_type` validation.

### Phase 7 — Cart

**Goal.** Introduce a server-side cart with multi-line checkout and abandoned-cart recovery.

**Scope.**
- Server-side cart document keyed to visitor/session.
- Multi-line checkout based on the Phase 5 order model.
- Baked-in shipping (per-item shipping priced into the discounted price; no cart-time shipping math).
- Abandoned-cart recovery using the email system.

### Phase 8 — Tax

**Goal.** Enable tax collection per tenant, **default off and registration-gated** (collected tax is
trust money that must be remitted).

**Scope.**
- Per-tenant toggle.
- Stripe `automatic_tax` on the connected account (direct-charge model → runs on the tenant's
  registrations, billed to the tenant).
- Sales-by-state ledger view (from our own order ledger, no external data).
- Collected-tax-by-jurisdiction reporting.

### Phase 9+ — Deferred

MCP server · inventory · i18n · page-view analytics · services booking · Sites.

---

## AWS implementation guidance

- AWS for compute, storage, queues, orchestration, secrets, and observability.
- KMS for tenant secrets (BYO AI keys encrypted like `stripe_keys`).
- AWS-native job orchestration (Step Functions or a worker Lambda) for async generation.
- Environment-separated resources for dev and prod, selected via the `mode` primitive.
- Python worker services for provider adapters, resolvers, validation, and content generation.
- Bedrock (IAM-scoped) for the platform trial path; outbound calls to OpenAI/Anthropic for BYO keys.

---

## Success metrics

**Phase 1** — % of pages migrated to the new composition system; page types supported by the section
catalog; builder edit-completion rate after preset application; reduction in template-related
rendering code.

**Phase 2** — upload success rate; median asset-attach latency; % of pages using first-class
MediaBucket assets.

**Phase 3** — draft-generation completion rate; time to first draft; validate/repair success rate;
draft-to-publish conversion rate; % of tenants who connect a key vs. use the Bedrock trial;
**AI-triggered environment-isolation violations, target zero.**

**Phase 3.5** — A/B-offer acceptance rate; custom-domain-offer acceptance rate.

**Phase 4** — URL-ingestion success rate; SSRF-block rejection rate; critic-pass adoption rate;
provider-diversity usage.

**Phase 5** — % of orders on the new line-item model; fee-reconciliation accuracy; backward-
compatibility pass rate for legacy orders.

**Phase 6** — listicle conversion rate; buy-now click-through rate.

**Phase 7** — cart-creation rate; cart-abandonment recovery rate; multi-line checkout completion
rate.

**Phase 8** — tax-enablement rate among registered tenants; tax-reporting completeness.

---

> Not legal or tax advice. Marketplace-facilitator posture and nexus thresholds must be confirmed
> with a tax professional; the platform does not perform DIY nexus monitoring.
