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
  poll                          →    GET /jobs/{job_id}
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

2. **Which Bedrock model — OPEN, and the one number that must be confirmed.** Nova Canvas, the obvious
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

**P0 — the repo, and model access proven.** Stack, deploy script, service-to-service auth, one health
route — plus the provisioning smoke generation that subscribes the model and sets `verified_at`, and a
second one after the subscription window to prove the first was not a mid-setup false positive. Small,
and it is the part that makes every later phase cheap. Doing it here means the 15-minute window is spent
on a Tuesday by us rather than by the first tenant who clicks Generate.

**P1 — Bedrock, platform-paid, metered.** Generate + job + poll, `/upload/from-url` delegation, and in
`stripe-link`: the three gates, an `ai_images` allowance beside `ai_generations`, and a builder picker
that inserts the returned CDN URL into a `photo` element. Gated on confirming the model and its live
per-image rate.

**P2 — Library + reuse.** `GET /ai/images/library`, re-run a prompt, delete. Needs the retention
decision.

**P3 — BYOK as an escape hatch.** For a tenant who wants volume beyond their tier and will pay OpenAI
directly. Optional, and only worth building if anyone asks.

**P4 — Edit.** "modify them" from the original request: the GPT Image models support edits with a mask.
Deliberately last — it doubles the surface and P1 has to be proven first.

## Explicitly not in scope

A new S3 bucket. A new CDN. A transcode or variant pipeline. A second media lifecycle. All four exist in
`image-processing`; see `docs/EXTERNAL_SERVICES.md` before reopening any of them.
