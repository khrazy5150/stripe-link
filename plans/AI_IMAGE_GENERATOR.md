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
- **BYOK is the default for cost.** The key travels with the request, so the service holds no credential
  of its own and the COGS belongs to whoever owns the key. Platform-paid is a `stripe-link` decision:
  it gates on plan and allowance, then calls with the platform key. The service does not know which it is.

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

**P0 — the repo.** Stack, deploy script, service-to-service auth, one health route. Small, and it is the
part that makes every later phase cheap.

**P1 — BYOK, one model, no platform spend.** Generate + job + poll, `/upload/from-url` delegation, and in
`stripe-link` a builder picker that inserts the returned CDN URL into a `photo` element. Zero COGS, so it
ships without the pricing decision being made.

**P2 — Library + reuse.** `GET /ai/images/library`, re-run a prompt, delete. Needs the retention
decision.

**P3 — Platform-paid.** Allowance, metering, plan gate, Bedrock-vs-OpenAI comparison. Needs decisions
1, 2 and 4.

**P4 — Edit.** "modify them" from the original request: the GPT Image models support edits with a mask.
Deliberately last — it doubles the surface and P1 has to be proven first.

## Explicitly not in scope

A new S3 bucket. A new CDN. A transcode or variant pipeline. A second media lifecycle. All four exist in
`image-processing`; see `docs/EXTERNAL_SERVICES.md` before reopening any of them.
