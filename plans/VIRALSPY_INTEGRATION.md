# ViralSpy integration — a metered gateway in front of someone else's API

Status: **design, nothing built.** Written 2026-10-16 from the author's sketch:

```
[ User Action in SaaS ] → [ SaaS Backend Gateway ] → [ ViralSpy REST API ]
                            1. check token balance
                            2. debit tokens
                            3. add Authorization: Bearer <MASTER_KEY>
```

The sketch is right. This document is about the four things it leaves out, each of which is where this
kind of integration actually goes wrong: **the debit is a distributed transaction**, **the master key is
the platform's money**, **a token is not a unit until someone decides what it buys**, and **the cheapest
call is the one not made**.

---

## 0. What is NOT known yet

Two searches found no product called "ViralSpy", so **every vendor-specific number below is a placeholder
and must be confirmed before anything is built**. The architecture does not depend on them; the economics
entirely do.

| Unknown | Why it changes the design |
|---|---|
| **Upstream pricing unit** — per call? per result? per credit, with endpoints costing different amounts? | Decides whether "1 action = 1 token" is honest or quietly loss-making. See §3. |
| **Upstream rate limits**, and whether they are per-key | A shared master key means one tenant's burst is every tenant's outage. See §4. |
| **Whether the ToS permits resale / multi-tenant use** | If it forbids sublicensing, the master-key model is not available and this becomes BYO-key. **Check this first — it can invalidate the whole design.** |
| **Response freshness / whether results are cacheable** | The single biggest cost lever. See §5. |
| **Whether responses carry personal data** | Decides whether this is a GDPR processing activity with a retention policy. See §8. |

---

## 1. Where it lives: its own service

A **sibling repo and stack**, like `admin-site`, `fonts-api` and `image-processing` — not routes in
`stripe-link`. Three reasons, and the first two are hard limits rather than preferences:

1. **`stripe-link` is at CloudFormation's 1MB transform limit.** A single new API route failed a prod
   deploy on 2026-10-05.
2. **It is at ~441 of 500 CloudFormation resources** (`domain/ai_quota.py` records this). A gateway needs a
   table, a function, routes and an alarm; that is a meaningful bite out of 59.
3. **Different failure mode.** This calls a third party that will be slow and will go down. That belongs
   behind its own concurrency limit and its own alarms, not sharing a deploy with checkout.

It shares what the admin site already shares, the same way: the **Cognito pool** by parameter, and the
**tenant profile table** by a scoped IAM read. Being signed in is not being entitled — entitlement is read
per call, exactly as `platform_status` and `entitlements` already are.

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

## 3. A token is not a unit until someone decides what it buys

The sketch says "debit tokens for action". That only works if every action costs the same, and it almost
certainly does not — a trend search and a full creator history are not the same call upstream.

**So: a per-action cost table, held as DATA.** `action → tokens`, on a config row, editable from the Admin
Site without a deploy. This repo has already learned this one the hard way, twice:

> the fee rates come from the deployed S3 config, NOT from `DEFAULT_GLOBAL_BILLING_CONFIG` — change both

and `ai_quota.py`'s leading comment: *"NOTHING here is the pricing… Hardcoding them in Python would repeat
the fee-table mistake exactly: code saying one thing while the deployed table says another, and the table
winning."* Hardcoding `TOKENS_PER_CALL = 1` would be the third time.

**The margin check that must happen before launch:** tokens per action × tokens included per plan ×
upstream cost per call, against the subscription price. `ai_quota.py` records the AI version of this sum —
at ~$0.105 a generation, a flat 50 gives away 27% of a $19 subscription at the model layer alone. The same
arithmetic decides the allowance ladder here, and it cannot be done until §0's pricing unit is known.

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

## 5. The cheapest call is the one not made

If upstream charges per call and queries repeat — and for trend data they repeat heavily, because everyone
asks about the same hashtags in the same week — **a shared cache is the largest cost lever available**, far
larger than any allowance tuning.

A short-TTL cache keyed on the normalized query, shared across tenants. Two things to settle first:

- **Is a cached hit still debited?** Recommendation: **yes.** The tenant is buying the answer, not our
  upstream invoice, and a free-when-cached rule makes a tenant's bill depend on strangers' activity —
  unexplainable on a dashboard. It also means the cache is pure margin, which is what pays for the tool.
- **How stale is too stale?** "Viral" has a short half-life. A day-old trend list may be worthless; an
  hour-old one is probably fine. This is a product decision, and it should be a config value, not a
  constant.

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

- **Phase 0 — confirm §0 before writing code.** Especially the ToS question: if multi-tenant resale is not
  permitted, the master-key model is dead and this becomes BYO-key, which is a different product.
- **Phase 1 — the gateway, one action.** Its own stack; Secrets-Manager key; `consume_if_available`-style
  atomic debit; ledger rows; refund-on-failure; the three gates; suspension check. One upstream endpoint,
  end to end, so the economics are measured rather than modelled.
- **Phase 2 — the surface.** Dashboard screen, balance, per-action costs, pre-click price.
- **Phase 3 — the cache**, once Phase 1's ledger shows the real repeat rate. Building it earlier means
  guessing at the hit rate; the ledger measures it.
- **Phase 4 — top-ups**, only if wanted. Buying tokens means Stripe, a purchased-balance ledger separate
  from the monthly allowance, expiry rules and refunds. It is a bigger piece of work than Phases 1–3
  together and should not be assumed into the first version.

---

## 8. Open decisions

- **Where does the balance live?** Its own table in the new stack (recommended — it is this service's
  state), with plan allowances read from the tenant profile, the same cross-stack read the admin site
  does. The alternative, folding it into the AI counter table, couples two unrelated products.
- **Monthly allowance, purchased tokens, or both?** Both means two balances with different expiry rules
  and a spend order to define. Phase 1 should assume allowance only.
- **Does a free-tier tenant get any?** The platform is free-forever with limited features; this is exactly
  the kind of feature that is "limited". Zero is a defensible default and costs nothing to raise.
- **Retention of upstream responses.** If they contain personal data, caching them is a processing
  activity with a retention policy, not just an optimisation. Settle with §0's answer.
- **Attribution and ToS display.** Some data providers require attribution or forbid re-display. Unknown
  until the vendor is identified.
