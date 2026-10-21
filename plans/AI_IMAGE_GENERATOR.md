# AI Image Generator — plan

**Status:** proposed, not built. Written 2026-10-20.
**Audience:** whoever builds this, and whoever asks in six months why it is not its own repo.

A tenant types a prompt, picks how many images they want (1–4), and gets images stored on the CDN with
permanent URLs — usable as-is in the page builder, or as the starting point for an edit.

---

## Two findings that reshape the request

### 1. DALL·E no longer exists

`dall-e-2` and `dall-e-3` were **removed from the OpenAI API on 2026-05-12**. The replacements are the
GPT Image family: `gpt-image-1`, `gpt-image-1-mini`, `gpt-image-1.5`, `gpt-image-2`. Anything written
against DALL·E today is written against an endpoint that returns 404.

Useful consequence: `n` accepts **1–10** in a single request, so "1–4 images" is one call, not four.

Published per-image pricing at 1024×1024 (`gpt-image-1`): **$0.011 low / $0.042 medium / $0.167 high**;
`-mini` is $0.005–$0.036. Four medium images is **~$0.17 a click**, four high is **~$0.67**. That number
drives every other decision in this document.

### 2. We already own the storage half — do not build a bucket

`../sam/image-processing` has the S3 buckets, the `images.juniorbay.com` CDN, the variant pipeline
(thumb/small/medium/large/full × avif/webp/jpg) and, decisively, **`POST /upload/from-url`** —
`{url, basePrefix?, baseKey?, fileName?}` — which fetches a remote URL, stores it, and queues
processing. An image generator's output is a URL. The two halves already fit.

So the "save them to an S3 bucket that's always accessible via URL" requirement is **already met by an
endpoint we do not currently proxy**. Building a second bucket would give us a second CDN, a second
lifecycle policy and a second place for a tenant's media to live. `docs/EXTERNAL_SERVICES.md` exists
because this has nearly happened before, with video.

---

## DECIDED 2026-10-20: its own repo, `../sam/ai-image-generator`

Asked for as a separate service; I argued for building it in `stripe-link` and was wrong. The author's
three reasons, which are better than my objection:

**1. The transform budget is a scarce shared resource, and it is for core commerce.** Measured the day
this was decided: **902,362 / 1,000,000 bytes, 219 Api events, and the guard trips at 240** — about 21
routes left for the Site object, collections, business profile, reviews elements, ads, GBP and ViralSpy.
This stack has already failed a deploy on that ceiling once (`plans/TRANSFORM_BUDGET.md`). Spending 3-4
of the remaining routes on a nice-to-have is a trade the core features would lose.

**2. Portability.** An image generator coupled to nothing but a UUID is reusable by whatever gets built
next. One built inside `stripe-link` is a stripe-link feature forever.

**3. A UUID owner id is the whole decoupling** — and it answers the objection I raised. My case for
keeping it here was that a separate service would have to re-implement auth, plans and metering. It does
not, because **those are policy and they stay here.** `stripe-link` decides whether this user may
generate; the service only generates. It never learns what a tenant, a plan or an allowance is.

### The split that makes that true

| | owns |
|---|---|
| **stripe-link** | who may generate, how many they have left, the builder UI, inserting the returned URL into a `photo` element |
| **ai-image-generator** | prompt → images → durable URLs, foldered by `owner_id` |
| **image-processing** | the bytes, the CDN, the variants |

The contract is deliberately thin: `{owner_id, prompt, count, size, quality}` in, `{job_id}` back, CDN
URLs on poll. **No Cognito** — the caller is a service, so service-to-service auth (shared secret in
Secrets Manager, or SigV4) rather than an end-user identity. **No tenant table, no plan table, no Stripe
anything.** If a second app ever calls it, it calls it the same way with a different UUID.

Storage still delegates to `image-processing` rather than minting a bucket: that service is already the
media layer for the family, and duplicating the CDN and variant pipeline would give a tenant's media two
homes. The chain `app → ai-image-generator → image-processing` is two generic services doing their own
jobs.

### What this costs

Its own repo, stack, deploy script and CI; service-to-service auth; a second place to look when an image
is missing. Accepted deliberately in exchange for the three reasons above — and for keeping
`stripe-link`'s remaining routes available to the things that earn money.

## Flow

```
stripe-link (policy)                 ai-image-generator (capability)
─────────────────────                ───────────────────────────────
tenant clicks Generate
  gate: plan + allowance        →    POST /generate  {owner_id, prompt, count, size, quality}
  (refuse BEFORE spending)             → write job {owner_id, status: queued}
                                       → self-invoke (Event)  ← no gateway waiting
                                  ←    202 {job_id}
  poll                          →    GET /jobs?owner_id=&job_id=   (one route, not a path param:
                                       the stack folds reads onto one)
                                  ←    {status, images:[{url, variants}]}
  insert URL into a photo element

                                     worker
                                       → provider, n = count → N images
                                       → image-processing POST /upload/from-url
                                           {basePrefix: "ai/<owner_id>"}
                                       → poll /upload/status/{id}
                                       → job.result = [{cdn_url, variants, model, cost_cents}]
```

`basePrefix: "ai/<owner_id>"` is the foldering: a UUID per owner, no other structure, so the service
never needs to know what an owner IS.

The async shape is not optional. Image generation runs 10–30s and API Gateway hangs up at 29 — the same
wall that produced "Failed to fetch" on delete-test-data and, before that, on page generation. The
pattern to copy is `ai_generate.py`: request path queues, worker runs where no gateway waits, dashboard
polls the job row.

---

## Decisions already made by existing architecture

- **The job row is the result**, and the pattern is worth copying wholesale from `ai_generate.py`:
  request path queues, worker runs on an async self-invoke where no gateway waits, caller polls, a reaper
  fails jobs Lambda dropped. Its own table in its own stack, so none of the shared-table hazards apply —
  but note the one that bit us on 2026-10-19 anyway: if a jobs table is ever shared, a reaper must claim
  only its own `document_type` or it applies one job kind's compensation to another.
- **Storage is delegated.** stripe-link stores no media. The handler proxies, as `upload.py` already does.
- **Platform-paid, and the gates already exist.** `ai_generate.py` runs three, and the image path wants
  all three for the same reasons:

  1. **plan entitlement** — is this tier allowed to generate at all;
  2. **per-tenant allowance** — `consume_if_available`, whose check and increment are ONE conditional
     write (two round trips produced four generations from an allowance of three, under a comment saying
     it could not happen);
  3. **platform budget** — `within_platform_budget`, identity-independent, and the comment says exactly
     why it exists: *"the only control that sees abuse per-tenant caps cannot: serial trial signups, each
     one perfectly within its own allowance."* A free image allowance is a way to spend AWS money, and
     this is the control that bounds it.

  All three live in `stripe-link`, which is consistent with the split: policy here, capability there.
  The service never sees a plan.

- **Allowances are config, not code.** `_configured_allowances()` reads them from a CONFIG row so the
  Admin Site can change them without a deploy, and `docs/PLATFORM_PLANS.md` already carries
  `ai_generations: 20` per plan. Images want an `ai_images` beside it — the same shape, the same table,
  the same editing path. Tuning "5 free" to "3 free" after launch is a config edit.

- **BYOK stays possible, later.** The key can travel with the request for a tenant who wants to spend
  their own money at a higher volume. It is just not the default, and not P1.

## Decisions that need making

1. ~~Platform-paid at all?~~ **DECIDED 2026-10-20: platform-paid on Bedrock, metered by tier.**
   BYOK was the original P1 and is wrong for this feature. An OpenAI API key is **not** covered by a
   ChatGPT subscription — the key needs its own prepaid credit balance. So "bring your own key" means a
   tenant must open an OpenAI account, attach a card, pre-buy credits, mint a key and paste it, before
   generating one image for their storefront. That is double friction on a nice-to-have, and almost
   nobody completes it.

   Platform-paid on Bedrock instead, with an allowance per tier: a few images free, more at $19. This
   also gives the paid plan its **second** reason to exist alongside the lower transaction fee, which
   matters because the plan had exactly one.

2. ~~Which Bedrock model?~~ **SUPERSEDED 2026-10-20: no Bedrock model exists to choose.** Amazon
   retired BOTH of its image models with no successor — Nova Canvas on 2026-09-30 and Titan Image
   Generator on 2026-06-30 — and invoking Titan returns `ResourceNotFoundException` "this model version
   has reached the end of its life". That removed the only first-party option, and every remaining
   Bedrock image model is third-party, which carries the subscription failure below. **Shipped on OpenAI
   direct** (`gpt-image-2.5-flare`), which removes that failure mode rather than managing it.

   The real rates, now confirmed rather than estimated, per image at 1024×1024, ×1.5 for a non-square:

   | quality | per image | landscape hero (1536×1024) |
   |---|---|---|
   | low | $0.011 | $0.017 |
   | medium | $0.042 | **$0.063** |
   | high | $0.167 | $0.250 |

   A landscape hero at medium is **$0.063**, against ~$0.105 for a page generation — close enough that
   images and pages belong on the same pricing ladder, and cheap enough that a 3-image trial costs 19
   cents. Quality is deliberately NOT exposed in the Junior Bay UI: it is a cost dial, not a creative
   one, and hiding it keeps one credit worth a predictable amount of money.

   The superseded analysis follows, kept because the reasoning about spread still applies if the
   provider ever changes again.

   ~~**Which Bedrock model — OPEN, and the one number that must be confirmed.**~~ Nova Canvas, the obvious
   default, **reached end of life 2026-09-30**. Titan Image Generator lists ~**$0.01**/image at 1024×1024
   standard; SDXL runs **$0.036–$0.08** depending on quality and step count. That 8× spread decides how
   generous "free" can be:

   | per image | 5 free images | 100 images on the $19 tier |
   |---|---|---|
   | $0.01 | $0.05 / tenant / month | $1.00 against $19 |
   | $0.08 | $0.40 / tenant / month | $8.00 against $19 |

   Confirm the live rate and the current model in the console before setting allowances. Published
   example prices are examples, and one model in this space has already been retired this quarter.

   **Leaning Titan**, and not only on price: it is a FIRST-PARTY Amazon model, so the third-party
   subscription failure mode below does not apply to it at all. See "Bedrock model access is not a given".
3. **Retention.** Generated images accumulate on a CDN we pay for and never expire today. A lifecycle
   rule belongs in `image-processing`, not here.
4. ~~Bedrock as the platform-paid path.~~ **DECIDED: yes.** `PLATFORM_PAID = (BEDROCK,)` is already
   wired, the relationship exists, and it avoids a second vendor whose keys the tenant would have to
   fund themselves. What remains open is only WHICH Bedrock model (see 2).

## Bedrock model access is not a given, and cannot be checked by asking

AWS's own warning on third-party models: the first invocation starts a subscription in the background;
calls **may succeed temporarily** during setup (up to 15 minutes); if a prerequisite is missing the
subscription fails and subsequent calls return `AccessDeniedException`; after permissions are granted it
can take another 2 minutes. *"Verify all prerequisites before invoking models in production."*

This repo has already paid for half that lesson. From `domain/ai_provider.is_verified`, measured
2026-09-27: `list-foundation-models` lists models the account cannot call, and
`get-foundation-model-availability` returned four green flags — agreement, entitlement, authorization,
region, all AVAILABLE — for models that then returned `AccessDenied`. **A catalogue check proves
nothing; only a generation does.** Hence `verified_at` is set by a real invocation.

The warning adds what we had not hit: a single success is not proof either, if it happened inside the
subscription window.

### What follows for this service

1. **Prefer a FIRST-PARTY Amazon model.** The warning is specifically about *third-party* models. Titan
   Image Generator is Amazon's own, so there is no third-party subscription dance to fail — and it is
   also the cheaper option (~$0.01 vs SDXL's $0.036–$0.08). Price and operational risk point the same
   way, which is rare enough to take. Choosing Stability or another vendor means owning this whole
   section; choosing Titan mostly deletes it.

2. **Subscribe at DEPLOY time, never on a tenant's click.** A provisioning smoke generation as part of
   the deploy, so the 15-minute window is spent by us on a Tuesday rather than by the first tenant who
   tries the feature. The same call sets `verified_at`.

3. **One success is not verification.** Because calls can succeed mid-subscription and fail after, the
   smoke generation must be repeated after the window — or a periodic health generation must run — before
   the feature is advertised. "It worked once" is exactly the evidence this failure mode produces.

4. **`AccessDeniedException` is a PLATFORM state, not a tenant error.** It means we are misconfigured.
   The tenant must not see "generation failed"; an operator must see "model not subscribed". It belongs
   in the admin site's view, not in a toast.

5. **Do NOT consume the tenant's allowance on an AccessDenied.** The allowance is taken *before* the call
   — it has to be, since the check and the increment must be one write — so a platform failure after it
   spends an image the tenant never got. The generation path already solves this: the reaper calls
   `_release` to give a slot back when a job dies, *"because the refund is the point."* The image path
   needs the same release on any platform-side failure, and that includes this one.

## Safety

Lower stakes than page generation — an image makes no commercial promise — but not zero, and different:

- **The output lands on our domain.** A generated image sits on `images.juniorbay.com` under our
  certificate. The provider moderates its own output; we inherit whatever passes.
- **Prompt logging.** Store the prompt on the job: it is the only evidence of what a tenant asked for,
  and the admin site's abuse queue will want it. It is also personal data — give it the same TTL as the
  job row.
- **Likeness and marks.** "A photo of <celebrity> holding my product" is a request the provider may well
  fulfil. This is the same takedown story as `plans/CREATOR_LINK_POLICY.md`, and the admin site's
  per-tenant view should show generated images alongside pages.
- **Spend as an abuse vector.** A platform-paid allowance is a way to spend our money. The allowance
  check must happen *before* the provider call, and `purchase_throttles`-style rate limiting applies.

## Phases

**P0 — the repo, and model access proven. SHIPPED dev + prod 2026-10-20.** Stack, deploy script, service-to-service auth, one health
route — plus the provisioning smoke generation that subscribes the model and sets `verified_at`, and a
second one after the subscription window to prove the first was not a mid-setup false positive. Small,
and it is the part that makes every later phase cheap. Doing it here means the 15-minute window is spent
on a Tuesday by us rather than by the first tenant who clicks Generate.

**P0.5 — the console. SHIPPED dev + prod 2026-10-20, unplanned.** A browser UI on the service itself
at `studio.juniorbay.com`, signed in with the SHARED Junior Bay Cognito pool. Not in the original plan
because the original plan assumed only a server would ever call this. It earns its place: it makes the
service usable and demonstrable before any Junior Bay integration exists, and it forced two things P1
needed anyway — a per-person spend ceiling, and the discovery that a uniform 7-day job TTL would have
quietly emptied anybody's library a week after they built it.

**P1 — platform-paid, metered, in the builder. The BACKEND is done; the picker is not.**
Shipped and proven on dev 2026-10-20: the three gates, the `ai_images` allowance beside
`ai_generations`, the server-side quality ceiling, the separate `images#` counter, the permanent
ledger row and the release-on-failure. A live run clamped a request for `high` down to `low` because
the account was on trial, spent `images#trial`, put a 1536×1024 hero on the CDN and recorded
`operation=image_generation, status=succeeded, quality=low, cost=16500` micros.

**What remains is the Hero picker, and it is the whole feature.** Everything above is unreachable by a
human until it exists — no tenant can press anything.

**P2 — Library + reuse. MOSTLY ABSORBED.** The library READ was always done (`GET /jobs`), and DELETE
shipped on 2026-10-20 as part of P1 rather than here, because a takedown had to exist before tenant
imagery could reach a public page, not after. What is left of P2 is "re-run a prompt" — a button
inside the picker P1 has yet to build, so there is nothing to start here independently.

**The one thing blocking an honest Delete button**: `image-processing` deletes the S3 objects but does
not invalidate the CDN, and variants carry `max-age=31536000`. The fix is written and committed in that
repo, NOT deployed — it needs `npm install @aws-sdk/client-cloudfront` and a deploy of the stack that
serves every image on the platform. Until then a delete removes the bytes but an edge keeps serving any
variant somebody had already loaded, which is exactly the set worth removing.

**P3 — BYOK as an escape hatch.** For a tenant who wants volume beyond their tier and will pay OpenAI
directly. Optional, and only worth building if anyone asks.

**P4 — Edit.** "modify them" from the original request: the GPT Image models support edits with a mask.
Deliberately last — it doubles the surface and P1 has to be proven first.

## The Junior Bay integration — DECIDED 2026-10-20

**First surface: the Landing Page Hero.** The hero inherits the offer's product images today, which is
reasonable and rarely striking. The price cards already carry the product shot, so the hero is free to
do a hero's job — convey a feeling — and that is exactly the image a tenant does not have. A fourth
button beside Upload Image / Upload Video / YouTube·Vimeo opens a modal holding a prompt box and this
tenant's existing AI images with the prompts that made them; picking one overrides the AUTO media.

**Reuse the quota rail that already exists. Do not build a second one.** `domain/ai_quota.py` already
encodes the exact entitlement rule this feature needs — `allowance_for()` returns a source of
`trial` / `plan` / `free` / `byok` / `exempt`, the trial counter is a LIFETIME one (`TRIAL_PERIOD`)
*because a 14-day trial straddles two calendar months and a monthly key hands the allowance out twice*,
and `DEFAULT_FREE_ALLOWANCE = 0` already means "paid or in trial, nobody else". `consume_if_available`
is one conditional write. `ai_generation_events` already has `started` / `succeeded` / `failed` /
`released`, which is reserve-then-settle: a failed generation gives the credit back.

**The numbers, DECIDED and already written to both config tables 2026-10-20** (before any code reads
them, so the code's fallback can never silently apply):

| | pages | images |
|---|---|---|
| trial (lifetime) | 3 | **7** |
| free / expired trial | 0 | **0** |
| Premium $19 (per month) | 20 | **30** |

**Quality is `low` everywhere today, and that is a server-side CEILING** (`ai_trial_image_quality` on
the CONFIG row, `ai_image_quality` on the plan row) — not a hidden control, because the parameter
travels in the request body and hiding a control limits nothing. Low is 15× cheaper than high and the
same pixel dimensions, so a trial hero is softer, never smaller. Higher resolutions become the reason to
buy a $29 tier that does not exist yet; until it does, P1 ships with no quality selector at all.

Dev deliberately differs on the trial row only — 25 and 25 — so the gate can be exercised without
burning a real allowance. At `low` everywhere, 30 images is $0.49/month against the $2.10 pages already
cost: $2.60 of $19, about 14% at the model layer.

### The AI Page Builder as a second caller — DECIDED 2026-10-20

The builder should be able to ask for a hero image while it writes a page, which means the capability
has to be declared in the element contracts `for_prompt()` renders. Six rules, and the first is the one
everything else follows from.

1. **The model emits INTENT, never I/O.** It writes `hero.image_request: {prompt, style}` into the page
   JSON and the job's worker fulfils it afterwards. It does not call a tool and wait. This is the same
   principle that already governs this generator — *emit schema-valid JSON, not HTML* — and the
   alternative is worse in three ways at once: a 10–30s image call inside a generation that is already
   slow, a second failure mode inside the one that produces the page, and a model holding a connection
   open while it spends money.

2. **The contract IS the budget.** The image affordance is rendered into the prompt only when the tenant
   can afford one. A model that was never told a capability exists cannot reach for it — which is far
   more reliable than describing it and adding "you may not", and it is the §A.7 lesson about bad
   examples inverted: what you put in front of the model is what it will do.

   **Build that view WITHOUT mutating the cache.** `contract()` hands out the live cached rules, and on
   2026-10-20 a `.pop()` on exactly that object consumed every `why` on the first call of a warm Lambda,
   silently teaching every later generation less. A per-tenant contract must be a copy.

3. **At most ONE image per page generation, for now.** A page becomes $0.105 + $0.0165. Unbounded, a
   single generation could order four.

4. **A failed image must never fail the page.** The hero falls back to the offer's product images, which
   is what it does today and is a perfectly good page. An image is an improvement on a working result,
   and failing the whole generation to protect a nice-to-have would be the worst possible trade.

5. **One style vocabulary, two consumers.** The presets the Hero picker offers are the fragments the AI
   appends — read from the same config, so a style the tenant can pick is a style the AI can request and
   the two cannot drift.

6. **Scene and mood, not product photography.** The contract must say so in its `do_not_use_when`, for
   the reason `ai_floor.py` already encodes: a photorealistic image of a product nobody photographed,
   on a page where someone is about to pay, is the visual form of an assertion we were not given. The
   real product is on the price card. The hero is for the feeling.

Images requested this way land in the same tenant library as hand-made ones, so they appear in the Hero
picker afterwards and can be reused, replaced or removed like any other.

### Making space for higher resolutions — binding, even though every tier is `low` today

The $29 tier is not being built now. These five rules exist so that building it is a config edit plus a
tier row, and never a rewrite of this feature. Each costs nothing today.

1. **The ceiling is DATA and already is.** `ai_trial_image_quality` on the CONFIG row,
   `ai_image_quality` on the plan row. Raising a tier to `medium` is an Admin Site edit on the next
   cache TTL, with no deploy — the same path `entitlements` and `fee_tier` take. Nothing may hardcode
   `"low"`.

2. **ONE resolver, two readers.** `image_quality_ceiling()` is what the generator clamps with AND what
   the config endpoint reports. `ai_config.py` already carries the warning this follows: *"The screen
   must read the SAME counter the generator will spend from, period included"* — showing a tenant one
   ceiling while the generator enforces another is that bug with a different noun.

3. **The UI renders a server-supplied list, never a hardcoded one.** The config response carries
   `qualities: [{value, label, credits}]`, built like `_catalogue()` builds the model list. It has ONE
   entry today, and a one-entry list renders no control at all — which is why P1 has no quality
   selector without P1 containing a decision to have no quality selector. When the $29 tier makes the
   list three long, the control appears with no change to the modal.

4. **Record the quality on the ledger event.** `ai_generation_events` never expires and answers "what
   did it cost?", so cost history must stay truthful across a tier change. It also means a weighted
   charge can arrive later without a migration: `consume_if_available` already takes `by=`, so a `high`
   image costing 4 credits needs no new column and no backfill — today everything is `by=1` because
   everything is the same price.

5. **Extend `entitlement_for`, do not clone it.** It takes an operation and returns the right counter,
   period and allowance for pages or images. A parallel `image_entitlement_for` would be two places to
   remember the lifetime-trial rule, and the comment on the original says exactly what that costs:
   a caller *"reaching for `period_key()` out of habit would hand a trial tenant a fresh three every
   calendar month."*

**One prerequisite this surfaces.** A subscriber's allowance is read from `tenant.ai_generations`,
denormalized onto the profile by the billing webhook so the generation path never reads the plans
table. `ai_images` and `ai_image_quality` must be denormalized the same way, in the same webhook — or
the image path acquires a plans-table read on the hot path that the page path deliberately does not
have.

**A separate `ai_images` allowance, not a shared pool.** `ai_generation_events` says the counter is
*"deliberately counted in GENERATIONS ... so that ad copy, SEO metadata and product descriptions can
share this ledger without reshaping it"*, so sharing was available and was rejected on product grounds:
Premium should read as "20 page generations + N hero images", and a tenant experimenting with images
must never discover they can no longer generate a page. The cost of separating is **zero** — the usage
counter's sort key is a plain string, so it is `images#<period>` and `images#trial` beside the existing
`<period>`, in the same table, through the same atomic write. One new admin-editable field per plan row,
the same shape as `ai_generations`.

**The library is keyed by `tenant_id`.** The images belong to the business whose landing page they are
for, not to whoever happened to be signed in. Today `caller_tenant()` falls back to the Cognito `sub`
and the code records that they are equal for all 6 current users — so `studio.juniorbay.com`, which
keys on `sub`, shows the same library today. That equality is *"a property of the data, not a guarantee
of the schema"*: if a tenant ever carries a `custom:tenant_id` that differs, the business library and
the personal console diverge, and the console needs a business switcher at that point. Keying on the
tenant is the choice that survives that; keying on the person would not.

**Zero new API routes.** The stack is at 219 Api events against a guard that trips at 240. The image
call folds onto `POST /ai/generate` with an operation key, and polling reuses `GET /ai/jobs/{job_id}`.
`OPERATION_IMAGE_GENERATION` joins `OPERATION_PAGE_GENERATION` in the ledger.

**Landscape by default.** `1536×1024`, because that is the hero's shape; square is what a product shot
wants and the hero is explicitly not that.

**What drops in unchanged.** The microservice stores through the same `image-processing` pipeline as a
manual upload, so the result arrives already shaped like `custom_1600x1200_….webp` with the full variant
set. The hero media array should take it natively — no new media type, no renderer special-casing — and
`image_dims` should ride along for CLS, the same as any other image.

**Refusals already carry blame.** A prompt the safety system rejects comes back as `blame: "tenant"`
with the provider's own sentence, so the modal can say "try describing it differently" instead of
"something went wrong" — and must NOT consume the credit, which is what `STATUS_RELEASED` is for.

## Explicitly not in scope

A new S3 bucket. A new CDN. A transcode or variant pipeline. A second media lifecycle. All four exist in
`image-processing`; see `docs/EXTERNAL_SERVICES.md` before reopening any of them.
