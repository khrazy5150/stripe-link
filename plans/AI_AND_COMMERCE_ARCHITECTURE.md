# AI Generation & Commerce Architecture Plan

**Status:** design locked · Parts B/C/D substantially SHIPPED under other entries · Part A not built
· **Scope:** stripe-link (JSON-first platform)

This plan captures the decisions from the AI + theme + cart + tax design discussions. It is
the reference to build against.

**"Nothing here is coded yet" was true when this was written and is not true now** (audited
2026-09-27). Parts B, C and most of Phase 0 shipped under the Page Composer, Goal Composition and
Listicle/Cart entries without anyone crediting them here, which is why this plan read as untouched:
the section catalog (`composition_rules.json`, 36 elements), the token system
(`UNIVERSAL_BUNDLE_THEME_PRESETS` + `fonts.py`), the collapse to one renderer (`TEMPLATE_STYLES` is
down to a single `universal_bundle`), and the server-side cart are all live. **Part A — the AI itself
— is genuinely unbuilt**: there is no `generate_structured`, no provider module, no AI code of any
kind. §D.2's "reserve tax fields now" also never happened, and orders turn out to have no schema at
all to reserve them in.

§A.1 (who pays) and §A.7 (the field floor) were revised 2026-09-27 against measurement, not argument.

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

### A.1 Who provides the model — REVISED 2026-09-27 (was: BYO-key only)
- Per-tenant **AI provider config**: `{ provider: bedrock|openai|anthropic|gemini|deepseek, model,
  api_key_ref }`. For a BYO key: stored **KMS-encrypted** (reuse `KmsSecretCipher`), redacted on read,
  with a `POST /ai/connect` + verify call (mirror `stripe_keys.py`). For `bedrock` there is no key at
  all — an IAM role — so that whole surface is absent rather than empty.
- **Two paths, one setting** (author, 2026-09-27):
  - `provider: byok` — the tenant's key, **the tenant's bill**. Available on every plan, including
    free. This is what keeps page generation — the *acquisition* feature — inside the free tier, where
    a tenant can actually see the payoff of the JSON-first architecture.
  - `provider: bedrock` — **the platform's bill**, gated on plan. The tenant never sees a key field.
- **REVISED 2026-09-27 (same day): platform-paid is the DEFAULT; BYOK is tabled, kept, demoted.**
  The original §A.1 reasoning -- "cost is the tenant's" -- assumed bringing a key was roughly free for
  them. It is not, and the friction is not the price:
  - A consumer subscription does **not** cover API use. Claude Pro/Max and ChatGPT both cover the chat
    surfaces only, and **no third-party app can consume a consumer subscription** — not us, not anyone,
    because the vendors expose no mechanism. (Claude Code authenticating with Pro/Max is first-party
    and specially arranged.) So the appealing version of BYOK — "use the subscription you already pay
    for" — cannot be built by anybody. That constraint is permanent and is not a gap in what we built.
  - API access needs **prepaid credits that expire one year from purchase and never refund**. A tenant
    must therefore create a vendor account, discover their subscription does not count, commit
    non-refundable money, and only then paste a key — four steps before their first page. A tenant who
    buys $5 and generates three pages has paid $1.67 each.
  - And the cost being avoided is tiny. A measured generation is **$0.0187**: fifty a month is **$0.94
    per premium tenant** (under 5% of a $19 plan) and five for a free tenant is **9 cents**. BYOK was
    solving a cost problem that barely exists.
  - **Bedrock also bills in ARREARS through AWS** — no prepayment, no expiry, no float — which is a
    more durable advantage over the Anthropic-direct path than the entitlement hassle is a
    disadvantage. The parked WIF option draws on the same expiring credits.

  So `bedrock` is the default provider and the primary card on the settings screen; BYOK stays behind
  a disclosure for the tenant who wants headroom or their own vendor relationship, with the credit
  terms stated before the button. **Allowances: free 5, premium 50.** The free tier moved from zero
  because platform-paid removes the setup that made a free allowance pointless — and page generation
  is the acquisition feature, so a free tenant who cannot run it never sees what would convert them.

  **Model: `sonnet-4.6`, entitled and working.** The entitlement impasse only affects models this
  account did not already have (Sonnet 5, the GPT families); Sonnet 4.6 measured best for this task
  regardless. The author is pursuing the impasse separately; nothing here waits on it.

- **BOTH SHIPPED 2026-09-27** (slice 1). BYOK reaches each vendor's own API over raw urllib, so
  `src/requirements.txt` stays empty — no SDK is worth ~20MB in every package for one POST. The two
  differ in kind, not decoration: OpenAI's `response_format: json_schema, strict: true` *guarantees*
  conformance (and demands every nested object close `additionalProperties` and list every property in
  `required`, applied recursively or the request is rejected outright); Anthropic offers one forced
  tool whose `input_schema` IS the contract. Both normalize to one return, so nothing above
  `generate_structured` can tell which answered. A BYO key is KMS-encrypted with the same
  service-scoped context as the Stripe secrets, **proven by a real generation BEFORE it is stored** —
  a key that does not work never becomes a saved configuration the tenant discovers is broken later —
  and a failure to encrypt never falls through to storing it in clear. BYOK model names come from the
  VENDOR, not our Bedrock registry (their account, their entitlements), but from a closed list rather
  than a passthrough: a typo would otherwise surface as a confusing vendor error and a wrong id as a
  surprise charge on their bill.
- **DEFERRED 2026-09-27 — a third provider: Anthropic Workload Identity Federation.** Parked with the
  research done, because it is worth reaching for later and expensive to re-derive.

  *What it is.* A Lambda calls `sts:GetWebIdentityToken` for an AWS-signed OIDC JWT asserting its IAM
  role, exchanges it at `https://api.anthropic.com/v1/oauth/token`, and receives a short-lived
  `sk-ant-oat01-…` token (600s default) used as `authorization: Bearer`. AWS IAM becomes the trust
  anchor. It needs `boto3` + `urllib` only, so `requirements.txt` stays empty, and it would slot in as
  a third `provider` value — platform-paid, no key — which `pays_platform()` already accounts for:
  adding it is one entry in `PLATFORM_PAID` and the quota, the billing label and the free-tier logic
  all keep working.

  *Why it is attractive.* No long-lived secret exists to store, rotate or leak — strictly better than
  a platform API key in Secrets Manager. And it **bypasses Bedrock entitlement entirely**, which is
  the thing currently blocking every model this account did not already have.

  *Setup it would need.* Outbound web identity federation is an account-level flag, **off** on
  `150544707159` (checked). Then `sts:GetWebIdentityToken` on the function role, and an issuer + rule
  in the Claude console — scoped to the exact role ARN, because a `subject_prefix` ending in `/*` lets
  any principal who can assume any role in the account mint tokens on our bill.

  *Why deferred (author, 2026-09-27).* It is a platform credential: one identity, one bill, serving
  every tenant. It does not and cannot serve BYOK, since a tenant has no workload in our AWS account
  to federate. BYOK carries the feature for now; this is the platform-paid path when one is wanted.

- **The multi-tenant tolerance of ONE shared AI credential** (measured 2026-09-27, applies to WIF and
  to any platform key). Rate limits are not the constraint; the **spend cap** is, and the risk is
  blast radius rather than capacity.

  Against the real slice-2 generation (2,239 in / 800 out on Sonnet 4.6, $0.0187):

  | Tier | Monthly cap | Generations | Premium tenants @ 50/mo | Binding rate limit |
  | --- | --- | --- | --- | --- |
  | Start | $500 | ~26,700 | ~530 | OTPM, ~500 generations/min |
  | Build | $1,000 | ~53,400 | ~1,070 | ~1,250/min |
  | Scale | $200,000 | ~10.7M | ~214,000 | ~2,500/min |

  Throughput is a non-issue — and **cached input tokens do not count toward ITPM**, so the identical
  system prompt raises effective headroom as well as lowering cost. A new organization also starts in
  an **Evaluation** tier *below* Start, so the first weeks are tighter than the table.

  **The hazard:** reaching the cap pauses ALL usage until 00:00 UTC on the 1st — HTTP 429,
  `error_code: enforced_spend_limit_reached`, **no `retry-after`**, retries fail. One shared credential
  is one shared outage: a single runaway tenant takes generation down for everyone, for up to a month.
  Anthropic offers workspace-level spend and rate limits but **nothing per-tenant** — the API has no
  concept of our tenants — so §A.6's per-tenant quota is not defence in depth, it is the only thing
  between one tenant and everyone else's outage.

  Mitigations to apply if a platform path ships: keep BYOK first-class so heavy tenants pay their own
  way and cannot hurt anyone else; set our own spend limit BELOW the tier cap (that yields a softer
  400 before the hard 429); separate workspaces for sandbox and production so a dev mistake cannot
  exhaust production's budget. **Open question not yet checked:** passing an end-user identifier per
  request for abuse attribution, which matters if one tenant's content triggers a policy review.

- **KNOWN GAP, not yet fixed** (found 2026-09-27): `ai_byok.py` maps every 429 to `throttled`, which
  the handler renders as "busy right now, try again in a moment". For a spend-cap 429 that is wrong —
  the honest answer is "the monthly budget is exhausted until the 1st", and the two are
  distinguishable by `error_code: enforced_spend_limit_reached` plus the absent `retry-after`. Harmless
  while only BYOK ships (it is then the tenant's own cap, and the message still points them at their
  provider), and it must be fixed before any platform-paid path.

- **Inference runs on GLOBAL profiles** (decided 2026-09-27). Regional (`us.`) costs exactly 10% more
  for identical output — measured across all 15 models, no exceptions — and a page-composition prompt
  carries tenant product copy, never customer PII, so nothing here needs to stay in one geography. The
  regional id is kept per model against a future tenant or region that needs US-only routing.
- The original note said a platform-key fallback was "optional and later". It arrives **first**,
  because Bedrock removes the key exchange entirely and boto3 already ships in the Lambda runtime
  (`src/requirements.txt` stays empty). `provider` is in the config from day one so BYOK is a second
  backend, never a retrofit.
- **The consequence to hold onto:** Bedrock reverses who pays, so a bundled allowance must be
  *countable* ("N generations/month included"), never implied-unlimited — one heavy tenant otherwise
  costs more than their subscription. No usage metering exists anywhere in the repo today, so this is
  net-new, and it is the same counter as §A.6's abuse cap: build it once. §A.7 carries the measured
  per-generation cost the allowance should be set from.
- **Verify by invoking, not by looking up.** `list-foundation-models` cheerfully lists models an
  account cannot call (§A.7), so `/ai/connect` — and the Bedrock equivalent — must make a real
  minimal call. A catalogue lookup proves nothing.

### A.2 Provider adapter layer
- One normalized interface: `generate_structured(prompt, json_schema, provider, model) ->
  validated object`, backed by a small per-provider raw-HTTP client (like `stripe_client.py`).
- Maps to each vendor's structured-output mechanism (Bedrock `converse` +
  `outputConfig.textFormat.structure.jsonSchema` — a first-class feature, not tool-use, and the one
  verified working in §A.7; OpenAI `response_format: json_schema`; Anthropic tool-use; Gemini
  `responseSchema`; DeepSeek OpenAI-compatible JSON mode).
- **Bedrock model ids are inference profiles**, not bare model ids: `us.anthropic.claude-sonnet-4-6`,
  not `anthropic.claude-sonnet-4-6`. `us-west-2` offers no In-Region inference for the current
  generation, so a bare id fails. The id belongs in the versioned `generation_policy` (§A.5) with the
  cost table beside it — both are config, because neither is derivable from an API (§A.7).

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

The chain has a floor: some fields are **never** the AI's to write, however the precedence resolves.
That list is §A.7, and the resolvers are where it is enforced — not a review step afterwards.

### A.5 Versioned generation policy
Treat the **system prompt + blueprints + resolvers + presets** as a versioned `generation_policy`
(like `schema_version`) → improve quality, roll back, and **A/B-test generation policies** on the
A/B engine already built.

### A.6 Security
SSRF-locked URL ingestion · no HTML/JS injection (structured data) · prompt-injection defense
(scraped content is data) · per-tenant rate limits / max generations · the §A.7 field floor.

The rate limit is not only an abuse control. Under the Bedrock path the platform pays for inference,
so a runaway generation loop spends **our** money — which is why the cap ships in the first commit
rather than as a later hardening pass.

### A.7 The field floor — what the AI may NEVER write (DECIDED 2026-09-27, from measurement)

**The original guardrail named the wrong risk.** It said the AI enriches *meaning*, never
*verifiable / markup-eligible facts* — brand, gtin, price, rating — which was aimed at fabricated
structured data. That rule is right and insufficient. Measured against four Bedrock models on a real
brief (see "What the probe found" below), the models did **not** fabricate reviews when told not to.
What they fabricated instead was **commercial terms and regulated claims** — and on a landing page an
invented term is a representation the tenant never agreed to make.

**The rule:** these fields are resolver-owned. The generation schema handed to the model does not
contain them, so the model cannot emit them and there is nothing to review, strip or repair.

| Never AI-writable | Why | Where it comes from instead |
| --- | --- | --- |
| `refund_policy` (page + section) | a refund window is a contract term | the tenant's own policy document |
| `legal` / `legal_footer` | ditto, plus jurisdiction | tenant config |
| `post_checkout` | promises about what happens after payment | the funnel the tenant built |
| cancellation / renewal terms *in prose* | the measured failure: two of four models volunteered "no lock-in, no fees" unprompted | the Price/subscription record, rendered by code |
| shipping promises, delivery windows | `ShippingConfig` knows; the model does not | resolver from shipping config |
| guarantee length, trial length | same class as refund policy | Price / tenant policy |
| dosage, usage instructions, efficacy or health claims | a supplement or a supplement-like product turns this into a regulated claim | tenant-supplied copy only, never generated |
| price, currency, brand, gtin/mpn, ratings, review counts | the original rule, retained | platform-owned records |

**FAQ needs this most, and is the least obvious.** Every invented term in the probe landed in a FAQ
answer, because "Can I cancel anytime?" *invites* a policy statement. So FAQ is not a free-text
section: questions may be generated, but any answer touching the table above is either resolved from
the record or the question is not asked. A generated FAQ that quietly writes policy is the single
highest-risk output of this entire feature.

**The inverted cost finding.** The cheapest model was the *most* dangerous. Haiku 4.5 — 4x cheaper
than Sonnet 4.6 — turned a given "5g per serving, 60 gummies per tub" into **"5g per gummy"** and
**"one gummy daily"** (invented dosing), added a taste claim that was never in the brief, and asserted
"you'll notice improved strength and muscle endurance" (an efficacy claim). Sonnet 4.6 and Opus 4.6
instead hedged correctly — *"check the label for the exact gummy count per serving"*. So
**"use the cheap model for page-gen to save COGS" is closed**: on this task, spend is not the axis
that matters, and the floor above is what makes a cheap model safe to use at all.

#### What the probe found (2026-09-27, `us-west-2`, real calls, ~$0.02 total)

Four entitled models, one brief, Bedrock's native structured-output contract
(`outputConfig.textFormat.structure.jsonSchema`), against the repo's **real** section types and field
names — `headline`/`subheadline`/`bragging_points`/`testimonials`/`faq` as `runtime/html.py` consumes
them.

| Model | in | out | latency | schema-valid | rendered | ~$/gen |
| --- | --- | --- | --- | --- | --- | --- |
| `claude-sonnet-4-6` | 1552 | 714 | 19.4s | yes | yes, 4.8KB | 0.015 |
| `claude-opus-4-6` | 1552 | 661 | 13.2s | yes | yes, 4.7KB | 0.024 |
| `claude-sonnet-4-5` | 1551 | 484 | 9.7s | yes | yes, 3.0KB | 0.012 |
| `claude-haiku-4-5` | 1551 | 499 | 13.4s | yes | yes, 3.2KB | 0.004 |
| `openai.gpt-oss-120b` | 381 | 1047 | 6.5s | **no** | — | 0.0004 |

Confirmed by this:
- **The central bet holds.** All four Claude models emitted schema-valid JSON that rendered through
  the real renderer **on the first attempt — zero repair rounds.** "The schema is the AI's API" is not
  a hope; it is measured, against production section shapes rather than a toy.
- **`Page.schema.json` is NOT a sufficient contract.** Its `sections[]` is `additionalProperties: true`
  with only `id` and `type` required, so `{"id":"x","type":"anything"}` validates and renders nothing.
  The generation schema must be built from the **section catalog** (`composition_rules.json`, 36
  elements) plus the renderer's field names — a *derived, stricter* schema than the validation one,
  with a test locking the two equivalent (the `semantic_schema.py` pattern).
- **Strict structured output rejects `minItems` > 1.** Cardinality belongs in the prompt, not the schema.
- **`us-west-2` has no In-Region inference** for these models; the model id must be a `us.`- or
  `global.`-prefixed inference profile. Bare `anthropic.claude-sonnet-4-6` fails.
- **Entitlement is orthogonal to EVERY readable flag** — the strongest form of "verify by invoking".
  Three layers were measured lying in sequence on 2026-09-27: `list-foundation-models` lists models
  the account cannot call; `get-foundation-model-availability` then reports all four flags green
  (agreement / entitlement / authorization / region `AVAILABLE`) for those same models; and finally
  `create_foundation_model_agreement` succeeds, flips the flag to `AVAILABLE` in 20 seconds, and still
  does not grant access. The control: **deleting `sonnet-4.5`'s agreement left it invoking perfectly**
  (`NOT_AVAILABLE` + works) while newly-agreed models sat at `AVAILABLE` + denied. Agreements are not
  the gate. Whatever is appears to need AWS approval — the error advises contacting AWS Sales, and
  `put_use_case_for_model_access` is a separate reviewed submission. **Consequence for the adapter:
  there is no readable field that means "this model will answer."** `/ai/connect` must make a real
  generation, and a model's availability must be re-proven rather than cached from a status call.
- **Invoking IS the enablement mechanism now**, which makes that rule load-bearing rather than merely
  prudent. The console's Model access page has been retired, and says so: serverless models "are now
  automatically enabled across all AWS commercial regions when first invoked", and for Marketplace-served
  models "a user with AWS Marketplace permissions must invoke the model once to enable it account-wide
  for all users." So `create_foundation_model_agreement` is the OLD path — which is exactly why it
  granted nothing — and a verify-by-invoking connect flow is not just how we CHECK access, it is how
  access gets turned on. One consequence worth designing for: the first call against a new model may be
  slower or one-time-fallible in a way later calls are not, so connect must not treat a single failure
  as permanent.
- **The one entitled OpenAI model does not honour the contract.** `gpt-oss-120b` wrapped the object in
  an array and then emitted malformed JSON at char 2467 with `stopReason: end_turn`. Provider-agnosticism
  is therefore **unproven** until a frontier OpenAI model is enabled and measured.
- **Rates are not machine-readable.** All 1052 `us-west-2` Bedrock price records from the AWS Pricing
  API carry **zero** current-generation models (Anthropic stops at Claude 3; the only OpenAI rows are
  `gpt-oss`). The published pricing page lists the models but shows no per-token rates. So the cost
  table is hand-maintained **config, never a code constant** — same trap as the stale
  `global_billing_config.json` fee table.
- **Prompt caching is the real COGS lever.** Input was ~1550 tokens, almost entirely a system prompt
  byte-identical across all four runs; with a full section catalog and blueprint library that prefix
  grows a lot. Sonnet 4.6 supports caching at a 1024-token minimum with a 1-hour TTL, so the prompt
  should be built as a stable cacheable prefix plus a small variable suffix **from the first commit**.

Budget **2–3x** the table above for a real full page (more sections, product details, theme
resolution, the occasional repair round): ~$0.046/generation on Sonnet 4.6. At that rate a bundled
**50 generations/month lands near 12% of a $19 subscription** — comfortable; 200/month reaches 49%,
which is where it stops being.

---

### A.8 Three gates, and what each one costs — DECIDED 2026-09-29

Access, entitlement and consumption are **three separate decisions**, and collapsing them into one number is
what forces a quota redesign every time pricing changes.

```
can this tenant use AI Builder at all?     -> CAPABILITY
how many generations are they entitled to? -> QUOTA (trial: lifetime · paid: monthly · BYOK: safety ceiling)
will we spend another Bedrock dollar now?  -> PLATFORM BUDGET
```

#### Gate 1 — capability

Add `ai_builder` to `CAPABILITIES`. Leave it OUT of `FREE_TIER_CAPABILITIES`, which is
`{landing_pages, sites, collections}` — booking is premium and must not be added here.

| Tenant state | AI Builder |
| --- | :-: |
| Free | ❌ |
| Live 14-day trial | ✅ (already gets the full set from `entitlements.py`) |
| Premium / Pro | ✅ |
| **Free + verified BYOK** | ✅ — their key, their bill; withholding it prevents someone spending their own money |

```
can_use_ai_builder(tenant) = has_capability(tenant, "ai_builder") or has_verified_byok(tenant)
```

"Verified" means `ai_provider.is_verified()` — `verified_at` set by a **real generation**, not a catalogue
lookup. Measured 2026-09-27: `get-foundation-model-availability` reported four green flags for models that
still returned AccessDenied, so only an invocation proves anything.

**This gate is ADVISORY until the authorizer lands.** `tenant_id_from_event` reads the tenant from the request
body, query string or headers, and nothing verifies the caller (plans/API_AUTHENTICATION.md, Phase 2 open). A
free tenant can send a trial tenant's id and the server cannot tell. Until then the only identity-independent
protection is gate 3, which is a reason to build gate 3 properly rather than a reason to delay gate 1.

#### Gate 2 — quota

| Source | Allowance | Counter |
| --- | --- | --- |
| Trial | **3 generations, LIFETIME** | period `"trial"` |
| Premium / Pro | 50 / calendar month | period `YYYY-MM` |
| BYOK | `BYOK_CEILING` safety ceiling | never consumes trial or platform allowance |
| `exempt` | UNLIMITED | test accounts; must survive this change |

**3, not 2, and called "3 AI generations" — never "2 pages."** One generation to discover, one to refine, one
to experience the value; two ends the demo at "still not quite." And the counter counts generations, which is
already the decided unit (§6 of AI_PAGE_BRIEF: a disliked generation still counts).

**One Build-with-AI click = one generation**, however many model calls it makes internally.

**Lifetime, because the calendar counter does not do what the name suggests.** `period_key()` is the calendar
month, so a trial starting 25 September spans September and October and hands out the allowance twice. The fix
is the period key `"trial"`: it never resets because there is no next trial period.

**One table, not two.** The semantics are the point, not the table — a row keyed `"trial"` reads as trial in
the data, reuses the single atomic increment path, and costs no new infrastructure. A second table is not free:
the stack is at **441 of 500 CloudFormation resources** on dev, and a table plus its IAM eats into that.

**The fallback inverts.** `FALLBACK_PLAN = "basic"` deliberately grants 5 on an unreadable plan, because zero
"is a lie to a tenant whose profile read merely blipped" and the exposure was nine cents. Under capability
gating that reasoning breaks: an unreadable plan must not silently grant AI, and must not wrongly deny a
paying customer either. It needs a **third state** — a retryable "we could not check your plan" — rather than
either a grant or a denial. And `PLATFORM_PAID_ALLOWANCE["basic"]` should be **deleted**, not set to 0: an
unreachable allowance that still looks authoritative is what a later reader mistakes for policy.

**Enforce on the write, not the read.** `ai_generate.py:140-150` reads `used`, decides, then consumes and
discards the returned total — so two concurrent requests both pass at `used=2, allowance=3` and produce four
generations. The comment above it claims the opposite. `AiUsageRepository.consume()` already returns the new
total precisely so the caller can enforce on it; the fix is consume → enforce on what came back → `release()`
if over. Consume-before-generate and the compensating release on provider failure already exist and are right.

#### Gate 3 — platform budget

Identity-independent, which is what makes it the real protection while gate 1 is advisory. A monthly Junior Bay
AI spend ceiling plus an emergency global disable, checked before invocation and **skipped for BYOK**, since
the platform is not paying for those. Per-tenant caps protect tenants from each other; only this protects the
platform from aggregate abuse — including serial trial signups, which no per-tenant cap can see.

Pair it with a short rate limit and one concurrent generation per tenant. The async job model already makes the
concurrency half nearly free: refuse to queue a second job while one is running.

---

### A.9 Cost accounting — what is real-time, and what cannot be (DECIDED 2026-09-29)

Requested by the author: record AWS spend in near-real time, surfaced in the Admin Site, with the ability to
spot big spenders per tenant. The honest design has **three tiers**, because they differ in both latency and
truthfulness, and presenting them as one number would be the fee-table mistake again.

| Tier | What | Latency | Per tenant? | Truth |
| --- | --- | --- | :-: | --- |
| 1 | **AI inference** | real time | ✅ exact | we are in the call path |
| 2 | Attributable infrastructure (requests, stored bytes, egress) | near real time | ⚠️ allocated | a model, not a measurement |
| 3 | **AWS Cost Explorer / CUR** | up to ~24h | ❌ account only | the actual bill |

**Tier 1 is the one that matters and the only one that is exact.** Bedrock's `converse` returns
`usage.inputTokens` / `outputTokens`, and `ai_models.estimate_cost()` already turns those into USD *with a
confidence attached*. Record it on the **same `ai_usage` row** as a second atomic `ADD` after the call — tokens
and cost accumulate alongside `used`, so the "big spender" question is answered by a row that already exists.
No new table.

**Store money as integer `cost_micros`, never a float.** DynamoDB `ADD` on floats accumulates rounding error,
and Decimal-from-DynamoDB is already a known footgun in this repo.

**Tier 2 is an allocation model and must be labelled as one.** One Lambda serves every tenant; AWS has no
tenant dimension. Counting attributable events and multiplying by unit rates produces an estimate, and calling
it "cost" invites exactly the confusion the estimate/actual split exists to prevent.

**Tier 3 cannot be real-time and cannot be per tenant.** Cost Explorer lags up to a day and CUR delivers a few
times daily. Its job is **reconciliation**, not display — the same estimate-then-true-up discipline this repo
already runs for Stripe fees against balance transactions. Show tier 1 as the live number, reconcile against
tier 3 monthly, and show the drift rather than hiding it.

**Two traps this design has to carry:**

- **The rate table is hand-maintained.** All 1052 `us-west-2` Bedrock price records carry zero current-
  generation models, so `ai_models.json` holds `rate_in`/`rate_out`/`rate_confidence` by hand. Costs therefore
  drift silently when AWS reprices. Needs a `rates_verified_at` stamp displayed next to any cost figure — the
  `global_billing_config.json` lesson, which is that deployed config outranks code and stale config outranks
  both.
- **The TTL deletes the history.** `consume()` sets `expires_at = at + 90 days` so spent periods expire rather
  than accumulate. That is right for a quota counter and wrong for cost trends: a year-over-year view would
  find nothing. Either extend the TTL on rows carrying cost, or roll up to a durable monthly summary **before**
  expiry. Decide before the first row expires, because after that the data is simply gone.

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

- Schema is the AI contract; AI emits JSON, never HTML. The *generation* schema is derived from the
  section catalog and is stricter than `Page.schema.json`, which alone would validate unrenderable
  sections (§A.7).
- One renderer + composable sections + bounded tokens + presets (no multi-theme code).
- **The §A.7 field floor:** policy, legal, commercial terms and regulated claims are resolver-owned
  and absent from the generation schema. Not reviewed out afterwards — never offered.
- BYO AI keys first, **plus a platform-paid Bedrock path** (revised 2026-09-27 — see §A.1): `provider`
  is a per-tenant setting, Bedrock gated on plan. Bedrock inverts who pays, so the per-tenant
  generation cap is load-bearing, not hygiene, and ships in the first commit.
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

---

## Shared with the Offer Semantic Model (P4)

The **provider adapter** (A.2), **BYO keys** (A.1), and **versioned generation policy** (A.5) defined here are
**not AI-page-gen-only** — they are the platform's single AI stack. The `OfferSemanticModel`'s **AI enrichment
tier** ([`OFFER_SEMANTIC_P4.md`](OFFER_SEMANTIC_P4.md)) is another `generate_structured` consumer, and that
plan's **ad-copy** and **AI-content** generators *are* the "AI content" surface of Part A — now reading the
canonical model instead of an ad-hoc brief. **Build the adapter once; both consume it.** The semantic model also
supplies the brand/category/concept context Part A.3 needs, so the two plans meet at Phase 1: the adapter lands
here, the enrichment tier and its consumers land in P4 on top of it. Guardrail carried across: the AI enriches
**meaning, never verifiable/markup-eligible facts** (brand/gtin/price/rating) — the same rule that keeps
fabricated structured data off the page.
