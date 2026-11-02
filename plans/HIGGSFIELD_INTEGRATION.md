# Higgsfield integration — metered video generation behind a platform key

Status: **VENDOR CLEARED 2026-11-01, NOT BUILT.** Renamed from `VIRALSPY_INTEGRATION.md`, which was
blocked because that vendor had no API and forbade multi-tenant use. **The architecture was written
vendor-agnostic and survives the swap**; what changed is that a vendor now exists whose terms contemplate
exactly this, and whose §11.5 imposes a design constraint the original sketch does not satisfy. Read §0
and §0b first.

The original sketch, from the author 2026-10-16:

```
[ User Action in SaaS ] → [ SaaS Backend Gateway ] → [ vendor REST API ]
                            1. check token balance
                            2. debit tokens
                            3. add Authorization: <MASTER_KEY>
```

The sketch is right about the shape. This document is about the five things it leaves out, each of which
is where this kind of integration actually goes wrong: **a pure pass-through is forbidden**, **the debit
is a distributed transaction**, **the master key is the platform's money**, **a token is not a unit until
someone decides what it buys**, and **capacity is a variable, not a constant**.

---

## 0. The vendor question, answered — and this time it passes

The predecessor died here. ViralSpy had no API, sold single-seat accounts and forbade resale, and no
amount of engineering makes a shared single-seat account a licensed multi-tenant one. Higgsfield is the
opposite on every count (checked 2026-11-01, Terms last updated 2026-10-23, effective on posting per
§19.6):

| Finding | Consequence |
|---|---|
| **A documented public API** (`docs.higgsfield.ai`), one key as ID + secret in `Authorization: Key ID:SECRET`, project-scoped and rotatable. | There is something to call. |
| **"Pay per generation, no subscriptions and no seats."** Video per second, images per image, balance-funded with auto top-up. | **Not per-tenant.** One platform balance, which is what makes a gateway possible — and what makes it our money (§4). |
| The licence covers *"your own purposes **or building applications for end users**"*, defines **End User** as anyone whose use of **your application** touches the Service. | Multi-tenant is contemplated, not tolerated. |
| **§11.5: no sublicensing, reselling, redistributing, or making Developer Access available "on a standalone basis"; no pass-through or service bureau without independent value added.** | **The binding constraint. See §0b — it invalidates the sketch above as written.** |
| *"Solely responsible for the acts, omissions and activities of your End Users"*, with an obligation to enforce the terms on them. | We need an AUP with teeth and a takedown path. Precedent exists: the creator-link policy, and the image generator's takedown-with-CDN-purge. |
| Training on the Service or its outputs is **prohibited**. | We do not train. No conflict, but it must reach tenants via the AUP above. |
| Outputs are the user's, commercially usable, no separate commercial licence to buy. | Tenants may use what they generate in ads and client work. |

### Still to confirm in writing before building

Secondary coverage disagrees about the **content licence** — one report of the July 2026 update claims a
broad perpetual licence over user inputs *and* outputs for training and promotion, while the Terms and help
centre describe something narrower and limited to operating the service. **We would be passing tenant
product photography and brand assets into this.** Get the current §11 and the content-licence clause
confirmed directly, in writing, before a line of code. That is the same discipline that killed the
predecessor honestly rather than expensively.

---

## 0b. §11.5 is a DESIGN constraint, not a legal footnote

**The sketch at the top of this document does not satisfy it.**

"Check balance → debit tokens → forward the call" is a billing wrapper around someone else's endpoint.
Metering is not independent value; charging per unit for relayed access is the definition of a service
bureau. A compliant vendor does not fix a non-compliant architecture, and a prompt box wired to
`POST /generate` with a token counter in front is exactly the thing §11.5 names.

**What passes is a different product, and it is the better one: generate from the OFFER, not from a prompt
box.**

The tenant has already built an offer — products, images, prices, a goal pack, brand colours, composition
rules, a funnel. "Make a fifteen-second ad for this offer" composes a prompt and an asset set out of
documents this platform holds and Higgsfield has never heard of. That is transformed input, and the tenant
could not obtain it by holding a Higgsfield key themselves.

The test to apply to every tool added later: **could the tenant get this by signing up to Higgsfield
directly?** If yes, it is relayed access and does not belong. If no — because it required their catalogue,
their brand, their funnel, their published page — it is an application.

**The strongest form of that answer is DISTRIBUTION, not prompt composition** (author, 2026-11-01).
Composing a prompt from the offer is transformed input, and it is an argument that has to be made. Being
the thing that schedules a Reel, posts it to three platforms on a calendar and then reports which post
produced a sale is not an argument at all — Higgsfield does none of it and cannot. **The video is an
ingredient; the product is the channel.** That is why generation lives inside
`plans/ATTENTION_PRIMITIVE.md` and is sold at no lower rung.

This is the same conclusion `plans/MCP_SERVER.md` reaches about tool design, from a different direction:
high-level intents that carry the platform's opinion, never a thin relay over someone else's primitive.
Both features fail the same way if built the lazy way, and the lazy way is also the weaker product.

**Consequences that follow from this, not from taste:**

- **No free-text prompt passthrough as the primary surface.** A prompt field may exist to *refine* a
  composed generation; it must not be the whole product.
- **Every generation is bound to an offer, product or page**, and the binding is stored. It is what the
  value-add argument rests on, and it is what makes the output useful in the builder afterwards.
- **The output lands in the platform**, on our CDN, in the tenant's asset library, reusable by the
  renderer — not handed back as a vendor URL and forgotten.

---

## 1. Where it lives: `../sam/ai-image-generator`, not a third repo

The predecessor said "its own sibling repo and stack". That was right then and is **superseded**: a
sibling that does exactly this job already exists. `plans/AI_IMAGE_GENERATOR.md` records
**DECIDED 2026-10-20: its own repo**, `../sam/ai-image-generator`, with a console at
`studio.juniorbay.com` signed in against the shared Cognito pool.

That service already holds every primitive this needs: metered generation against a platform key, a
server-side quality ceiling as config data, permanent CDN URLs, and takedown with CDN purge. Video
generation is **another generator in the same service**, not a new one beside it. Creating a third repo to
do metered media would be the duplicate-source fault this codebase keeps paying for, at the service level.

**NOT `../sam/ai-video-generator`.** That folder exists and is a trap: three files, no git history, a
template describing *"AI Video Generator Stack - Workout videos with music"*, its **own** Cognito pool
rather than the shared one, and Python 3.11 against the estate's 3.12. It is an abandoned scaffold for an
unrelated idea, and the name is close enough that anyone looking for "where does video generation live"
will find it first. Either delete it or leave it knowing this paragraph is the only thing pointing the
other way (noted 2026-11-01).

The two hard limits that forced it out of `stripe-link` still hold and still apply to the queue in §5:

1. **`stripe-link` is near CloudFormation's 1MB transform limit** — ~138KB of headroom after
   `plans/TRANSFORM_BUDGET.md`, and a single new route once failed a prod deploy.
2. **It is at ~441 of 500 CloudFormation resources.** A queue is SQS + worker + DLQ + alarm; that is a
   real bite out of 59.
3. **Different failure mode.** Third-party video generation is slow, bursty and will go down. That belongs
   behind its own concurrency limit and its own alarms, not sharing a deploy with checkout.

**What stays in `stripe-link`:** the quota rail. `domain/ai_quota.py` already has
`entitlement_for(..., operation=...)` parameterised by operation and `IMAGE_PREFIX = "images#"` producing
`images#2026-10` / `images#trial`. The image generator's plan is emphatic — *"Reuse the quota rail that
already exists. Do not build a second one."* Video extends it rather than forking it; see §3 for what the
unit is.

---

## 2. The debit is a distributed transaction, not a step

The sketch's steps 1 and 2 — *check balance*, then *debit* — **must be one write.**
`AiUsageRepository.consume_if_available` already exists for precisely this and its docstring records what
happens otherwise, in this codebase, in production:

> two requests at `used=2` of an allowance of 3 both passed the decision and both incremented, producing
> four generations from a three-generation allowance — under a comment asserting that could not happen.

So: **one conditional `ADD` that both checks and debits**, never a read followed by a write.

Then the harder half. A debit and an upstream call cannot both be atomic, so there are four outcomes and
three of them need a decision:

| | Debit | Upstream | What must happen |
|---|---|---|---|
| A | ok | 2xx | Nothing. The happy path. |
| B | ok | 5xx / timeout / network | **Refund.** The tenant paid for nothing. |
| C | ok | 4xx (bad query) | **Refund.** They still got nothing; we were not charged for work. |
| D | ok | 2xx, response lost in transit | Tenant retries → **debited twice for one answer.** |

**Decision: debit first, refund on anything that is not a 2xx.** Debiting first is the fail-closed
direction — it protects the master key, which is the thing that costs real money. The refund is a
compensating `ADD` carrying the **same request id**, so a retried refund cannot double-credit.

**D is the one that needs a request id from the client.** Every call carries a caller-supplied
`request_id`; the ledger row is written under it with a conditional put, so a retry of the same action
finds the existing row and returns the cached answer instead of debiting again. This is the same
`put_if_absent` idempotency primitive the Stripe webhook already uses, and for the same reason: *anything
that counts has to refuse the second copy at the database rather than trust the delivery.*

**Every call gets a ledger row** — tenant, action, tokens, request id, upstream status, latency, cost.
Not for billing alone: without it, "why is my balance 40 instead of 60" has no answer, and neither does
"what did this cost us last month".

---

## 3. A token is not a unit until someone decides what it buys — and video bills per SECOND

The sketch says "debit tokens for action". For video that is not one number: **Higgsfield prices video per
second and images per image**, model by model, with volume discounts applied automatically. A six-second
clip and a thirty-second clip are not the same purchase, and two models at the same duration are not
either.

So the counter's unit is **seconds of generated video**, not generations. `images#<period>` counts things;
`video#<period>` must count seconds, or a tenant allowed "20 videos" discovers that twenty thirty-second
clips cost five times what twenty six-second clips do — and the platform discovers it second.

**The cost table is DATA, not code.** `model + duration → tokens`, on a config row, editable from the Admin
Site without a deploy. This repo has learned it twice already:

> the fee rates come from the deployed S3 config, NOT from `DEFAULT_GLOBAL_BILLING_CONFIG` — change both

and `ai_quota.py`'s leading comment: *"NOTHING here is the pricing… Hardcoding them in Python would repeat
the fee-table mistake exactly: code saying one thing while the deployed table says another, and the table
winning."* Hardcoding `TOKENS_PER_SECOND = 1` would be the third time.

**The margin check before launch**, now computable because the vendor publishes a public per-model price:
tokens per second × seconds included per plan × upstream cost per second, against the subscription price.
`ai_quota.py` records the image version — at ~$0.105 a generation, a flat 50 gives away 27% of a $19
subscription at the model layer alone. **Video is an order of magnitude more expensive per unit than an
image.** Expect the honest included-allowance to be small, and say so on the pricing page rather than
discovering it in a month's invoice.

---

## 4. The master key is the platform's money

Under BYO-key a runaway loop embarrasses us. Under a master key **it bills us**, and that reverses who the
controls are protecting. Three gates, mirroring `ai_quota.py`, because the third is the only one that sees
the abuse that matters:

1. **Per-tenant allowance** — the commercial number ("1,000 tokens a month included"), which is also the
   per-tenant abuse cap. Same number, two jobs.
2. **Per-tenant rate/concurrency cap** — separate from the allowance. A tenant with 1,000 tokens can still
   spend them in four seconds and take the upstream rate limit down for everyone. The allowance is a
   month's worth; this is a second's worth.
3. **Platform monthly budget** — identity-independent, and the only control that catches serial trial
   signups each perfectly within their own allowance. Opt-in, `0` meaning no ceiling, so an unset budget
   never silently stops the whole platform.

Plus the obvious: **the master key lives in Secrets Manager**, passed by ARN exactly as
`StripePlatformSecretArn` is, never an environment variable, never reaching a browser. The gateway is its
only holder — which is the entire reason the gateway exists.

**A suspended tenant gets nothing**, by the same check `checkout` and `publish` use
([[ADMIN_SITE]] §1c). An abuse suspension that left the spy tool running would be a suspension in name.

---

## 5. Capacity is a VARIABLE, and a shared one

This replaces the predecessor's cache section, which was the biggest lever for *trend data* and is nearly
worthless here — see §5b.

**Concurrency is account-level and funding-tiered** (published 2026-11-01):

| Funds added in the trailing 28 days | Concurrent generations |
|---|---|
| new account | 2 |
| $25+ | 10 |
| $100+ | 20 |
| $1,000+ | 40 |
| enterprise | by agreement |

Two properties of that table matter more than the numbers.

**It is a rolling window, so capacity FALLS when usage dips.** A quiet month silently drops the platform
from 20 slots to 10, and a queue holding a hardcoded 20 will not notice — it will simply start failing in
a way that looks like the vendor being slow. That is this codebase's signature failure: a constant that
changed without telling anyone (`feedback_absence_reads_as_safety`, and the shipment lookup that asked for
a key which could not exist). **The worker must discover its capacity and back off on the retryable error,
never assert it.**

**Excess is not guaranteed to be queued.** The API terms permit concurrency, rate *and* quota limits and
allow requests beyond them to be queued **or rejected with a retryable error**. So the queue is ours to
build; theirs is not a promise.

### The queue

1. Tenant requests a generation; it is stored as a **job**, not a call.
2. A worker submits when a slot is free, recording the vendor request id.
3. Completion arrives by **webhook**, or by polling as a fallback.
4. The slot is released and the next job submitted.

**Per-tenant concurrency cap, separate from the allowance** — start at 2 active jobs per tenant. One
tenant must not be able to occupy every platform slot; that is the same rule the delivery-guarantee sweep
applies to a shared resource, and §4's second gate already states it.

**The completion webhook is a solved problem here.** `src/handlers/shipping_tracking.py` shipped
2026-11-01 doing precisely this shape for a carrier feed: a token in the URL compared constant-time,
**failing closed** when unconfigured, the vendor carrying **our own job id** in their metadata field so we
resolve by our identifier rather than theirs, idempotent on replay, and ordering guards so a late event
cannot undo a finished one. Lift that pattern; do not re-derive it. Note especially the metadata trick —
it is what avoids needing an index on a vendor id.

## 5b. The cache lever is mostly gone, and that changes the economics

For trend data the predecessor was right that a shared cache was the largest cost lever available, because
every tenant asks about the same hashtags in the same week. **Generated video is the opposite: the output
is bound to one tenant's offer and is useless to anyone else.** There is no shared hit rate to harvest.

What remains is narrower and still worth having:

- **Deduplicate an identical re-request from the same tenant** — same offer, same model, same duration,
  same inputs — within a short window. This catches the double-click and the impatient retry, which are
  the common cases, and it is the §2 `request_id` doing the work rather than a cache.
- **Never regenerate to re-render.** The output is a permanent CDN asset bound to the offer; a page that
  re-publishes must reuse it. Regenerating on publish would be a per-publish bill.

The consequence for pricing: **margin cannot be made on cache hits here.** It has to come from the
allowance being honest about what video costs, which makes §3's margin check load-bearing rather than
prudent.

---

## 6. What the tenant sees

- **Balance and what spent it.** A number with no itemisation produces support tickets; the ledger from §2
  is what makes it answerable.
- **The cost BEFORE the click**, on the action itself. "This search uses 5 tokens" prevents the entire
  class of complaint where someone discovers the price afterwards.
- **A refusal that says which gate stopped them**, and whether waiting fixes it. `ai_quota` already makes
  this distinction and explains it: a monthly ceiling must not say "try again shortly", because *"a retry
  message that is false trains people to retry forever."*

---

## 7. Phasing

- **Phase 0 — the written confirmation (§0).** Current §11 and the content-licence clause, from Higgsfield,
  in writing. Nothing below is worth building until that exists, and it is cheap to ask. The predecessor
  died at this step, which is the argument for doing it first rather than last.
- **Phase 1 — one generation, end to end, inside the image-generator service.** Platform key in Secrets
  Manager; `consume_if_available`-style atomic debit in seconds; ledger rows; refund-on-failure; the three
  gates; the suspension check; the job queue with discovered capacity; the completion webhook lifted from
  `shipping_tracking.py`. **One offer-bound generation**, not a prompt box (§0b), so the economics are
  measured rather than modelled.
- **Phase 2 — the surface.** The generation lands in the tenant's asset library with a permanent CDN URL
  and is selectable in the builder wherever a video already is. Balance, per-action cost, pre-click price.
- **Phase 3 — more compositions.** Additional offer-derived formats once Phase 1's ledger shows what people
  actually generate and what it costs. Each new one passes §0b's test before it ships.
- **Phase 4 — top-ups**, only if wanted. Buying seconds means Stripe, a purchased-balance ledger separate
  from the monthly allowance, expiry rules and refunds. Bigger than Phases 1–3 together; do not assume it
  into the first version.

---

## 8. Decided, and open

### DECIDED 2026-11-01 — video starts at the ATTENTION tier (~$69), with an allowance that EXPIRES

**There is no standalone video rung.** Generation is not sold on its own at any price: it exists only
inside `plans/ATTENTION_PRIMITIVE.md`, as an ingredient of a campaign product. An intermediate "$39
creative" rung was proposed and **rejected 2026-11-01** — see "Why no lower rung" below. Allowance per
plan, **not priced per generation**. No rollover, no purchased tokens in Phase 1.

That is not what makes it compliant — §0b is — but it removes the appearance of unit resale: the tenant
buys Junior Bay premium, not Higgsfield inventory counted out by us. It also inverts §4's cash-flow risk,
because subscription revenue arrives BEFORE the upstream cost is incurred, and it stabilises the funding
cadence §5's concurrency tier depends on.

**Why expiry rather than rollover: the two are not equally reversible.** Adding rollover later is a gift;
removing it later means clawing back balances tenants believe they own. Same reasoning as requiring a
return when no policy resolves — pick the direction that is one click to undo. And there is no usage data
yet, which is what Phase 1 is for.

**The accepted cost, stated rather than discovered:** a calendar month plus expiry produces a synchronised
month-end rush against a hard concurrency ceiling. **Absorb it in the queue (§5); do NOT change the period
model.** `ai_quota.period_key` chose calendar month deliberately — *"the number has to be one a tenant can
check against their own calendar without us explaining it"* — and a second period model in that module to
serve one feature is the split that drifts. Generation is async, so a deeper queue at month-end is slower
turnaround, not failure. Size for it and alarm on queue depth.

**Revisit when the ledger shows most tenants using well under half their allowance.** That is a churn
signal rather than breakage, and rollover is the right fix for it. If they cluster near the cap instead,
rollover adds liability and burst risk for people who do not need it.

**If rollover is ever added, two constraints.** Cap it at one month (maximum balance 2x) — uncapped banking
is the worst correlation available, a tenant redeeming a year at once hits cash and concurrency together,
possibly in a month when the rolling 28-day window has already dropped the tier. And **forfeit it on
downgrade or cancellation**: a balance that survives cancellation is a liability someone cashes out on the
way out, while a forfeitable one is a switching cost. Same feature, opposite effect on retention.

**Why no lower rung** (author, 2026-11-01). A rung selling generation *without distribution* is the
weakest §11.5 position available — "pay us monthly for generated assets" is the closest thing to a service
bureau that could be shipped, and it is the rung most likely to attract the tenant who signs up to farm
cheap generation. Under a platform key that farming is billed to US, so price is the cheapest filter and it
works before any of §4's gates fire. $69 also leaves COGS headroom for a vendor whose unit cost is an order
of magnitude above images.

**The consequence, accepted:** video earns no revenue until Attention ships. There is no "ship the
generator first and fund the rest" path, because the generator has no standalone home. See §7.

### Still open

- **What is the first composition?** A short ad from the landing offer is the obvious candidate — it uses
  products, images, price, goal pack and brand colours, which is the §0b argument at its strongest. Settle
  it before Phase 1, because it decides what the prompt composer reads.
- **Where does the balance live?** The image-generator service's own table (recommended — it is that
  service's state), with plan allowances read from the tenant profile by the same cross-stack read the
  admin site already does.
- **Shared or separate allowance from images?** `ai_quota` counts images at `images#<period>`. Video should
  be `video#<period>` — a **separate** counter, because the units differ (seconds vs images) and the costs
  differ by an order of magnitude. A shared pool would let a tenant spend their image allowance on four
  seconds of video.
- **Does a free-tier tenant get any?** The platform is free-forever with limited features and video is the
  most expensive thing on offer. **Zero is the defensible default** and costs nothing to raise.
- **AUP and enforcement.** The terms make us responsible for End Users and forbid training on outputs. The
  creator-link policy and the image generator's takedown-with-CDN-purge are the precedents; this needs the
  same, plus the training prohibition passed through to tenants.
- **What happens to a generation when a tenant leaves?** Outputs are theirs and commercially usable, so
  deletion is not automatic. Settle retention alongside the §0 content-licence answer.
- **Model choice: ours or theirs?** A catalogue of models at different prices is a pricing surface a tenant
  should probably not see. Recommendation: the platform picks, held as config data like the quality
  ceiling, so it can change without a deploy or a tenant-visible decision.
