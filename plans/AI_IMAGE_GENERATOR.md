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

## DECISION REQUIRED: where this lives

The request says "separate microservice". Three options, with the trade honestly stated.

### A. In `stripe-link`, delegating storage to `image-processing` — RECOMMENDED

Generation is one outbound API call. Everything *around* it already exists here:

| need | already built |
|---|---|
| async job + polling + reaper | `JobsTable` (renamed from AiJobsTable 2026-10-19 precisely so it is not AI-specific) |
| provider config, BYOK | `domain/ai_provider.py` — `openai` is already a BYOK provider |
| usage metering, allowances | `AiUsageRepository.consume_if_available` |
| plan gating | tier/entitlement plumbing |
| auth | the Cognito authorizer |
| storage + CDN | `image-processing` `/upload/from-url` |

Cost: two API routes and one worker mode on an existing function. Transform headroom is ~98KB, so this
fits comfortably.

### B. A third repo

Honest case for it: image COGS is a different risk profile from page generation, and a blast radius of
its own is worth something on a service that spends money per click.

Honest case against: it would own neither the storage (that is `image-processing`) nor the rails
(metering, plans, auth, jobs — all here). It would have to re-implement auth and metering, or call back
into `stripe-link` for both. That is a service defined by what it delegates.

### C. In `image-processing`

It owns storage and already fetches remote URLs. But it has no concept of a tenant, a plan, an
allowance, or a Cognito identity, and `sharp` makes that stack hazardous to deploy (see
`docs/EXTERNAL_SERVICES.md` — a Mac `sam build` took the whole image service down once).

**Recommendation: A.** The thing being added is small; what makes it feel like a service is the
machinery around it, and that machinery is already written.

---

## Flow

```
POST /ai/images            {prompt, count: 1..4, size, quality}
  → validate + check allowance (refuse BEFORE spending money)
  → write job {document_type: "image_generation_job", status: queued}
  → self-invoke (InvocationType: Event)   ← no gateway waiting
  → 202 {job_id}

worker
  → provider call (n = count) → N image URLs or b64
  → for each: POST image-processing /upload/from-url {basePrefix: "ai/<tenant_id>"}
  → poll /upload/status/{id} until complete
  → job.result = [{cdn_url, variants, prompt, model, cost_cents}]

GET /ai/images?job_id=...  → poll, same shape as /ai/jobs
GET /ai/images/library     → the tenant's past generations
```

The async shape is not optional. Image generation runs 10–30s and API Gateway hangs up at 29 — the same
wall that produced "Failed to fetch" on delete-test-data and, before that, on page generation. The
pattern to copy is `ai_generate.py`: request path queues, worker runs where no gateway waits, dashboard
polls the job row.

---

## Decisions already made by existing architecture

- **The job row is the result.** `JobsTable`, `document_type: "image_generation_job"` — distinct, so the
  generation reaper does not claim it and refund an AI allowance it never spent (the hazard found
  2026-10-19 when that table became shared).
- **Storage is delegated.** stripe-link stores no media. The handler proxies, as `upload.py` already does.
- **BYOK is the default for cost.** `openai` is already a BYOK provider; a tenant's own key makes the
  COGS theirs. Platform-paid generation is a plan entitlement with an allowance, metered through
  `AiUsageRepository` — the same rail page generation uses.

## Decisions that need making

1. **Platform-paid at all?** At ~$0.17 per four-image click, a generous free allowance is a real bill.
   Options: BYOK-only at launch (zero COGS, zero abuse exposure); small metered allowance on the paid
   plan; or paid add-on credits. BYOK-only is the cheapest way to ship and learn.
2. **Which model tier is the default.** `-mini` at $0.005/image makes a free allowance plausible;
   `gpt-image-2` does not. This is the same shape as the page-gen finding that *the cheap model is the
   dangerous one* — except for images "dangerous" means ugly, not libellous, so the trade differs.
3. **Retention.** Generated images accumulate on a CDN we pay for and never expire today. A lifecycle
   rule belongs in `image-processing`, not here.
4. **Bedrock as the platform-paid path.** Bedrock offers image models and we already hold that
   relationship, with `PLATFORM_PAID = (BEDROCK,)` wired. Worth comparing before adding a second
   platform-paid vendor.

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

**P1 — BYOK, one model, no platform spend.** Routes, job, worker, `/upload/from-url` delegation, a
builder picker that inserts a CDN URL into a `photo` element. Zero COGS, so it can ship without the
pricing decision being made.

**P2 — Library + reuse.** `GET /ai/images/library`, re-run a prompt, delete. Needs the retention
decision.

**P3 — Platform-paid.** Allowance, metering, plan gate, Bedrock-vs-OpenAI comparison. Needs decisions
1, 2 and 4.

**P4 — Edit.** "modify them" from the original request: the GPT Image models support edits with a mask.
Deliberately last — it doubles the surface and P1 has to be proven first.

## Explicitly not in scope

A new S3 bucket. A new CDN. A transcode or variant pipeline. A second media lifecycle. All four exist in
`image-processing`; see `docs/EXTERNAL_SERVICES.md` before reopening any of them.
