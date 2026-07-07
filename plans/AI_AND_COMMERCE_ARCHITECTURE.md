# AI Generation & Commerce Architecture Plan

**Status:** design locked, not yet built · **Scope:** stripe-link (JSON-first platform)

This plan captures the decisions from the AI + theme + cart + tax design discussions. It is
the reference to build against. Nothing here is coded yet.

---

## Vision

A tenant clicks **"✨ Let AI build it for you"**, gives either a **product URL** or a few
**manual details**, and their **connected AI provider** (OpenAI / Anthropic / Gemini / DeepSeek)
produces a beautiful, on-brand landing page — with the tenant making *zero* required design
decisions. This is the strategic payoff of going JSON-first.

---

## Guiding principles

1. **The schema is the AI's API.** The model emits **JSON** (`Page`/`Product`/`Offer`) that
   conforms to the existing JSON Schemas — never HTML. The existing `runtime/html.py` renderer
   turns valid JSON into the page. This buys: safety (structured data can't inject markup/JS),
   consistency (same renderer/themes/checkout wiring as hand-built pages), provider-agnosticism,
   and a real validate-and-repair loop.
2. **Structure and style are data, not code.** One renderer; every visual difference is
   expressed as data (which sections + which style tokens).
3. **Don't let the model guess what code can decide.** Push each decision to the lowest layer
   that can make it: *code decides* (enforced) → *a resolver decides* (rules) → *the AI decides*
   (genuinely creative). Constrain the plumbing; free the creativity.
4. **Reuse the existing patterns.** Per-tenant secrets via KMS (like `stripe_keys`), raw-HTTP
   provider clients (like `stripe_client`), provider abstraction (like shipping providers),
   draft→publish pipeline, document repos, webhook idempotency.
5. **Human-in-the-loop.** AI generates a **draft**; the tenant reviews/tweaks in the builder;
   publishing is always a deliberate step. Never auto-publish.

---

## Part A — AI landing-page generation

### A.1 Bring-your-own AI provider
- Per-tenant **AI provider config**: `{ provider: openai|anthropic|gemini|deepseek, model,
  api_key_ref }`, key stored **KMS-encrypted** (reuse `KmsSecretCipher`), redacted on read, with
  a `POST /ai/connect` + verify call (mirror `stripe_keys.py`).
- **Cost is the tenant's** (their key, their bill). *Decision:* BYO-key first; a platform-key
  "credits" fallback is optional and later.

### A.2 Provider adapter layer
- One normalized interface: `generate_structured(prompt, json_schema, provider, model) ->
  validated object`, backed by a small per-provider raw-HTTP client (like `stripe_client.py`).
- Maps to each vendor's structured-output mechanism (OpenAI `response_format: json_schema`,
  Anthropic tool-use, Gemini `responseSchema`, DeepSeek OpenAI-compatible JSON mode).

### A.3 Generation pipeline (async job)
Runs as a **job**, not a request (seconds–minutes; multi-step). Orchestrate with **Step Functions**
(or a single worker Lambda for the MVP) + a `generation_job` document (`status/progress/
result_page_id`) the dashboard polls.

1. **Ingest → normalized "product brief"** `{name, benefits[], features[], price, audience, tone,
   images[]}`. Two adapters:
   - *URL*: fetch + extract (og:image / product images / price / key text). **SSRF-locked**
     (public http(s) only; block private/metadata IP ranges; cap redirects/size/timeout).
     Treat scraped content as **untrusted data, not instructions** (prompt-injection defense).
   - *Manual*: a short form → the brief.
2. **Create Product + Offer deterministically** from the brief (platform owns
   `product_id`/`price_id`/`offer_id`, Stripe sync, fees; AI assists copy only) — avoids the AI
   inventing dangling references.
3. **Generate the Page JSON** with the schema as the output contract, offer/product ids injected,
   brand context from `TenantProfile`, few-shot examples of good pages, and a chosen **blueprint**.
4. **Validate → repair loop** against `validate_page_document`; re-prompt with errors (bounded).
5. **Attach assets.** Image priority: provided → scraped (→ MediaBucket) → generated (image model)
   → stock (Unsplash/Pexels by category) → placeholder. Image-gen is its own pluggable concern
   (not all providers do images; likely defaults to a platform service).
6. **Resolve a preset/theme** (see Part B).
7. **Save as DRAFT** → open in the builder → tenant reviews → publishes.
8. *(Optional)* **Critic pass**: draft → self-critique ("strengthen weak headlines") → refine.
   Cheap with structured output; measurable via A/B.

### A.4 Resolvers — the decision brain (shared by AI *and* manual flows)
Deterministic, **versioned, testable** module with an explicit **precedence chain**:
`explicit request > tenant brand/preferences > platform default rules > AI judgment`.
Examples: `resolve_preset`, `resolve_palette`, `resolve_sections`, `resolve_listicle_price`,
`resolve_upsell` (off for listicles). Where the AI *should* have a say, hand it a **shortlist**
(e.g., 2–3 presets that fit the category) rather than an open choice — rules narrow the space,
the AI picks within it.

### A.5 Versioned generation policy
Treat the **system prompt + blueprints + resolvers + presets** as a versioned `generation_policy`
(like `schema_version`) → improve quality, roll back, and **A/B-test generation policies** on the
A/B engine already built.

### A.6 Security
SSRF-locked URL ingestion · no HTML/JS injection (structured data) · prompt-injection defense
(scraped content is data) · per-tenant rate limits / max generations.

---

## Part B — Composition system (the "one theme" refactor)

"Theme" conflated three jobs; split them:

1. **Composition** — which sections, in what order (`sections[]`, already data / drag-reorder).
2. **Style tokens** — font, palette, spacing, radius (applied to one renderer).
3. **Presets (a.k.a. blueprints)** — named bundles of (default section list + token set + defaults):
   "Clean Product", "VSL", "Founder-led", "Social-proof heavy".

**One renderer + composable sections + bounded style tokens + a preset library.** Every element
(testimonials, ratings, VSL/video hero, face-in-hero, FAQ, …) is a **toggleable section**, not its
own theme. This is opinion-neutral (minimalism and maximalism both served), it's the ideal AI
input surface (AI can't produce non-rendering output), and A/B variants fall out for free.

**Refactor:** collapse the current `TEMPLATE_STYLES` (`simple`, `universal_bundle`) into one
token-driven renderer — a *simplification* that deletes code. The section render functions already
exist; this is mostly consolidation.

**Guardrails so it doesn't backfire:**
- **Constrain the token choices** — a curated set of coherent **palettes** + a small vetted
  **font set** (not open hex/any-font, which reopens the ClickFunnels chaos). Freedom in *what*
  (sections); rails on *how it looks*.
- **Per-section layout variants** as a small `variant` enum (pricing: stacked vs cards; hero:
  centered vs image-left) — variety without rigid templates.

Deliverable vocabulary the resolvers + AI both speak: **section catalog** (with variants),
**token system** (palettes + fonts), **preset library**.

---

## Part C — Listicle section + server-side cart

### C.1 Listicle is a *section*, not a theme
A `product_carousel` section iterating over several offers/products: swipeable, with a **per-slide
dynamic CTA** that morphs into that product's price. Improves on TikTok's version (which can't buy
on-page) with **Buy now** and **Add to cart** + a persistent **mini-cart** ("Checkout (3) · $34.97").

- **Promote `offer_type`** (single / bundle / listicle) to a **first-class validated field**
  (currently UI-only and stripped before validation). Prerequisite for listicle rules/rendering.
- **Price resolver (listicle slide):** single-unit prices (`quantity <= 1`), exclude
  `upsell/downsell/order_bump`, prefer discounted; tie-break `flash_sale > sale > standard`, then
  lowest `unit_amount`. One price → use it.
- **Upsell resolver:** listicle offers **ignore upsell funnels** (deterministic).

### C.2 Mixed fulfillment types are ALLOWED
*Decision (reversed from earlier):* do **not** force offers/carts to a single fulfillment type —
that would block the legitimate **physical + digital-bonus** combo. The **transactional vs
lead-gen** restriction stays (already enforced in `offers.py`). Buy-now is per-slide single-product
(works for any type); the cart handles mixed types via baked shipping + conditional address.

### C.3 Buy-now first (cheap), cart second (a real primitive)
- **Buy-now listicle uses the *existing* single-offer checkout** — a slide's button launches that
  product's Checkout Session. **No new primitives.** Ship this first.
- **Cart is its own deliberate project** (the moment you opt into "shop mode" vs "focused funnel"):
  - **Server-side cart document** (keyed to visitor/session) — unlocks **abandoned-cart recovery**
    (via the email system already built), attribution, cross-device. Not localStorage-only.
  - **Multi-line order model** — `line_items[]` instead of a single `product`. Ripples into things
    already built: **refunds ledger** (per-line), **receipts** (itemized), **digital downloads**
    (per-line links), **fees** (per-line rates). Keep a **single-product compat path** so existing
    orders still render.
  - **Line-level attribution** — each line keeps `{product_id, page_id, slide/source, offer_id,
    ab_variant}`, e.g. `product 1234xlt, page 33412, slide 4`. Keeps A/B + analytics meaningful in
    a multi-source cart.
  - **Baked-in shipping** — each item's individual shipping is priced into its discounted price, so
    the cart total is just the sum (no cart-time shipping math). Collect a shipping **address** only
    if the cart has a physical item; the real label is bought at fulfillment (margin =
    baked − combined-label cost). **Neutral on single buys, positive on carts.** Flat-rate model —
    tenant bears destination variance (fine for domestic/light DTC).
  - **Stripe constraints:** *carts are one-time-only* (subscriptions check out solo — a Checkout
    Session is payment-mode vs subscription-mode). Tax fields reserved (Part D).

---

## Part D — Accounting integrity (fees + tax)

**Principle:** tax and fees on the order are *the platform's books*, not "a Stripe concern."
Skipping them creates reconciliation drift.

### D.1 Fees — already present, but true them up
The order already stores `{stripe_fee, platform_fee, net_payout}`. But:
- **`platform_fee` is exact** (the `application_fee_amount` we set).
- **`stripe_fee` is currently an *estimate*** (computed from a schedule). The **actual** fee is on
  the charge's **balance transaction**. *Action:* reconcile `stripe_fee`/`net_payout` to the
  **actual** value (via a `charge`/`balance` webhook or a follow-up read) so books match Stripe.

### D.2 Tax fields — reserve now
Add **per-line `tax_amount`** + an **order-level tax total** (default `0`) to the multi-line order
model **from day one**, so enabling tax later is never a data migration.

### D.3 Tax collection — per-tenant, default OFF, registration-gated
- **Direct-charge Connect** model → set `automatic_tax: {enabled}` on the session created on the
  **tenant's connected account**; Stripe Tax uses **their** registrations and bills **their** account.
- A **per-tenant toggle**, default **off**, **gated on the tenant confirming registration** in the
  jurisdiction — a guardrail, because **collected tax is trust money that must be remitted**;
  collecting it prematurely is a *liability*, not revenue ("if you collect it, you owe it").
- **Basic vs Pro:** Stripe Tax *calculates/collects* (basic) vs also *files/remits* (pro/upgrade or
  partner). The tenant chooses; the platform can *recommend* from the ledger.

### D.4 Nexus monitoring — NOT the platform's job
- **No DIY threshold tracking.** There is no reliable, maintained, **free** public API of state
  economic-nexus thresholds; maintaining that table is a compliance liability out of scope.
- Use **Stripe Tax's free monitoring** on the connected account (monitoring is free; you pay only
  when it *calculates*). The **tenant** watches their own obligations (their dashboard) and decides
  when to register + flip collection on. ToS already puts tax responsibility on the tenant.
- The platform *may* offer an in-scope **"sales by state" view from its own order ledger**
  (informational, no external data) to inform the tenant's self-file-vs-Stripe-filing decision.
- **Ledgers/reports:** the order tax fields + Stripe Tax on the tenant account produce "how much
  tax collected, by jurisdiction" — so the toxic-asset (collected tax) is visible and remittable,
  not mistaken for revenue.

> Not legal/tax advice. A tax professional validates thresholds and — importantly — the platform's
> **marketplace-facilitator posture** (the one place the platform itself could be liable).

---

## Cross-cutting decisions (locked)

- Schema is the AI contract; AI emits JSON, never HTML.
- One renderer + composable sections + bounded tokens + presets (no multi-theme code).
- BYO AI keys first (platform-key credits optional/later).
- Resolvers are a first-class, versioned, testable module with a precedence chain.
- Generation policy (prompt + blueprints + resolvers + presets) is versioned and A/B-testable.
- Mixed fulfillment types allowed; transactional vs lead-gen stays enforced.
- Cart is server-side, multi-line, line-attributed, one-time-only, with baked-in shipping.
- Fees trued-up to actual; tax fields reserved; tax collection per-tenant, default-off,
  registration-gated; nexus monitoring outsourced to Stripe + tenant.

## Explicitly deferred (decisions, not omissions)

Inventory/stock · international / multi-currency · video upload/transcode · **MCP server**
(platform-as-agent-tool; keep logic decoupled from transport so it's a cheap adapter later) ·
platform-key AI credits · Stripe Tax *filing* automation.

---

## Phased build order

**Phase 0 — Foundations (cheap now, expensive to retrofit)**
- Promote `offer_type` to a validated field.
- Evolve order model → `line_items[]` (+ per-line `tax_amount`, line attribution) with a
  single-product compat path.
- Actual-fee reconciliation (balance-transaction true-up).
- **Composition refactor:** collapse `TEMPLATE_STYLES` → one token-driven renderer; define the
  **section catalog (+ variants)**, **token system (palettes + fonts)**, **preset library**.
- **Media/asset pipeline** (real uploads to MediaBucket; the AI needs this).

**Phase 1 — AI MVP**
- BYO AI keys + provider adapter (1–2 providers, e.g. OpenAI + Anthropic).
- Resolvers + blueprint library + versioned generation policy.
- Manual-input generation → validate/repair → **draft page** in the builder.

**Phase 2 — AI expansion**
- URL ingestion (SSRF-locked) · image strategy (generate/stock) · critic pass · more providers.

**Phase 3 — Listicle + buy-now**
- `product_carousel` section + per-slide dynamic CTA + buy-now on the existing checkout.

**Phase 4 — Cart primitive**
- Server-side cart doc · multi-line checkout · line attribution · baked shipping ·
  abandoned-cart recovery (reuse email).

**Phase 5 — Tax**
- Per-tenant registration-gated toggle → `automatic_tax` on the connected account ·
  "sales by state" ledger view · collected-tax-by-jurisdiction report.

**Phase 6+ — Deferred**
- MCP server · inventory · i18n.

---

## Prerequisites the AI feature leans on (pull forward)
- **Composition/preset system** (Part B) — the AI's output vocabulary.
- **Media/image pipeline** — the AI needs real asset storage + URLs.

These two are why the AI plan reorders the remaining migration backlog: build them as AI-enablers
before the AI MVP. The other remaining migration items (page-view analytics, services booking, the
Sites flow) are independent and can slot in anytime.
