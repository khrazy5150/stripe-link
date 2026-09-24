# The silo model — what a deployment IS, and which events belong to it

Status: **PROPOSED (2026-09-23). Not built.** The model is the author's and is settled; the guard it
implies is not written.

## Read this first: two words mean opposite things

This is not pedantry. It derailed an entire working session and it has already produced bugs, because the
codebase and the author use **the same two words for opposite axes**:

| the author says | the code says | values |
|---|---|---|
| **mode** | `ENVIRONMENT` | sandbox (`dev`), production (`prod`), one day `staging` |
| **environment** | `stripe_mode`, `mode` | `test`, `live` |

So "four webhooks — two per mode, each with a live and a test environment" means **silos × Stripe modes**,
not what a reader of `stripe_webhook.py` would assume. This document uses **silo** for the deployment axis
and **Stripe mode** for test/live, and avoids the bare words entirely. Do the same.

## The root cause: the silo is not a modeled concept

Author, 2026-09-23, and it is the sentence this whole document exists to record:

> *The code is still using legacy terminology because it ignores the silo itself. It asks `mode=live|test`
> — the Stripe axis — and that is the gap that was never fixed when the silo concept was introduced. The
> code adopted the legacy logic and we have been patching it.*

stripe-cart had ONE server with two Stripe modes, so "which deployment" and "which Stripe mode" were the
same question. stripe-link has several deployments, and the decoupling split those axes **in the data**
(`stripe_mode` became a record attribute) — but it never made the **silo** a modeled thing. There is no
silo identity on a record, no silo on an event, and `ENVIRONMENT` appears nowhere in the webhook handler.

The silo boundary today is implicit: *whatever tables this Lambda's environment variables happen to point
at.* That works, and it is unverifiable — nothing can ask "does this belong here?", because nothing says
where anything came from. Every bug in this area has been a patch around that absence.

## The model

**A silo is a complete, independent SaaS.** Not a staging copy, not a scratch environment — the whole
product, deployed separately, with its own tables, its own tenants and its own money.

The only thing that distinguishes one silo from another is **who uses it**:

| silo | audience |
|---|---|
| sandbox | developers |
| staging | a small number of real tenants, ahead of general release |
| production | everyone |

Everything else is identical by design. A tenant dropped into sandbox would find a working business.

## Consequence: every silo processes LIVE money

This follows from the model and is **not negotiable**, though it contradicts the usual "non-production must
never touch real money" instinct:

- **Sandbox must, or it verifies nothing.** Code is promoted sandbox → production. If sandbox cannot
  process a live transaction, the one path that matters most is the one path never exercised before
  release.
- **Staging must, because its tenants are real.** Real tenants running real businesses ahead of a general
  release are taking real payments. A staging silo that refused live money would be a demo, not an
  early-access tier.

An earlier draft of this analysis proposed exactly the wrong guard — *"a sandbox or staging silo must
refuse `livemode: true`"* — imported from the conventional model. It is recorded here because it is the
mistake a reader is most likely to repeat.

## The correct safety property: silo membership

The question is never *"is this event live?"* — every silo handles live events. It is:

> **Does this event belong to THIS silo?**

A tenant belongs to exactly one silo. An event names a connected account. So: is that account a tenant
here? If not, the event is somebody else's and must not be touched.

This property is silo-agnostic. It works for two silos or five, permits live money in all of them, and
never asks which one is "production."

## The hole that exists today

`handlers/stripe_webhook.py:221`:

```python
tenant_id = str((tenant_document or {}).get("tenant_id") or "").strip() or _metadata_tenant_id(stripe_event)
```

`find_by_connect_account_id(account_id, mode)` **is** the membership check. Then the `or` throws it away:
when the account is not a tenant here, the code reads `tenant_id` out of the **event's own metadata** —
which our checkout stamps on every session (`payload["metadata[tenant_id]"]`).

**So the boundary is checked and then bypassed.** A production tenant's live payment arriving at a sandbox
endpoint — a misconfigured URL, a copied webhook, a tenant pasting the wrong address — finds no matching
account, falls through to metadata, finds a perfectly good tenant id, and is processed: a real order in
sandbox's tables, a real receipt to a real customer, real money in sandbox's ledger.

Invisible today **only because sandbox has no endpoint.** It is a latent defect that activates the moment
this plan's first step is taken.

**This is also the unclosed half of an older bug.** `[[project_webhook_mode_guard]]` — *"dev+prod webhooks
BOTH processed test events; per-table dedup can't catch cross-env"* — has the same root cause: nothing
establishes that an event belongs to this silo. It was patched with a `livemode`-vs-`ENVIRONMENT` guard,
which worked only by accident of the old conflation, and P3 of `plans/STRIPE_MODE_DECOUPLING.md` removed
that guard when the conflation went away. The symptom was treated; the hole was not.

## The proposal — CORRECTED 2026-09-23

An earlier draft of this section proposed: *"if an event names a connected account and that account is not
a tenant of this silo, do not process it."* **That does not work, and the reason is the modeling gap
above.**

**A tenant can be a tenant of several silos at once.** The same connected account is registered in dev AND
prod — `acct_1TA08M21lLbLd4Y5` is in both `jb-stripe-keys-v2-dev` and `-prod` (verified 2026-09-23). Both
silos legitimately answer "yes, mine." Membership is **necessary but not sufficient**; it cannot
discriminate, because the account is not what distinguishes silos.

This is the same wall the 2026-09-20 investigation hit: *"With no discriminator, both once processed
everything and produced duplicate orders."* The fix at the time — route-by-livemode with a single
registered endpoint — stopped the duplicates by **starving dev of traffic entirely**, which is why
`jb-orders-dev` has never held a row and `jb-ledger-prod` holds test money.

### What the discriminator has to be

The event must carry **which silo created the thing it is about**, because nothing else can distinguish
two silos that both know the account. We control that for anything we originate:

- **Stamp the silo at session creation.** `build_checkout_payload` already writes
  `metadata[tenant_id]`; it adds `metadata[silo]`. Subscriptions already copy session metadata onto
  `subscription_data[metadata]`, so renewals inherit it.
- **The webhook processes an event whose stamped silo is its own, and ignores the rest** — acknowledging
  to Stripe so it stops retrying, logging loudly, persisting nothing.
- Membership stays as a second check, per ACCOUNT not per (account, Stripe-mode), for the reason in the
  section below.

### The residual case, which needs a decision

**An event we did not originate carries no stamp.** A tenant creating a test invoice in Stripe's own
dashboard — exactly what happened on 2026-09-23 — produces `invoice.paid` with no `metadata[silo]`,
because no silo created it. Options, none obviously right:

1. **The production silo claims unstamped events.** Simple; wrong the moment a staging tenant does it.
2. **Every silo ignores unstamped events.** Safe, and silently drops legitimate Stripe-dashboard activity
   — which is how yesterday's subscription renewals arrived.
3. **Route by which silo the tenant "belongs to"**, requiring a home-silo on the tenant record — the
   modeling this document says is missing, done properly.

(3) is the honest answer and the largest. Decide before S1 ships, because the guard's behaviour for
unstamped events IS the design.

- Acknowledge to Stripe (2xx) so it stops retrying — the event is not ours and never will be.
- Log loudly, with the account id and the silo. A silo receiving another's traffic is a misconfiguration
  someone needs to hear about, not a condition to swallow.
- Persist nothing — no order, no ledger entry, no notification, no email.
- Keep the metadata fallback **only** for events that carry no `account` at all (platform-account events).

### Resolved (author, 2026-09-23): can a tenant exist before their `stripe_keys` row?

**Yes — and it does not matter.** A tenant can use the product with no Stripe at all: non-transactional
pages, lead capture, a link hub. They are a full tenant of the software. But **they cannot produce a
Stripe event**, because a Stripe transaction requires a connected account, and a connected account is
exactly what writes the row.

So "an event names an account we do not know" has no legitimate new-tenant explanation. The guard can be
strict: **reject, not retry.** No grace path.

The one ordering race — `account.updated` firing during onboarding, before the OAuth callback writes the
row — is **already handled**: `stripe_webhook.py:335` gates that branch on `tenant_document`, so an
unknown account is ignored rather than acted on.

### But membership is a property of the ACCOUNT, not the (account, Stripe-mode) pair

`find_by_connect_account_id(account_id, mode)` filters on **both** the account id and the mode
(`documents.py:624`), and the OAuth callback writes **one row per connected mode**
(`stripe_connect.py:255`). A tenant who connects in only one Stripe mode therefore has no row in the
other.

**This matters for live-first onboarding**, which is already planned: a merchant connects LIVE and may
never connect test. If they then create a test invoice in Stripe's own dashboard — exactly what happened
on 2026-09-23 — the event arrives with `livemode: false`, the lookup asks for a `mode=test` row that does
not exist, and a **strict membership guard would reject a real tenant's event as foreign.**

Not firing today: the only connected account in dev or prod has rows for both modes (verified
2026-09-23). It becomes live the first time a tenant connects one mode only.

**So the guard must ask membership per ACCOUNT, in any mode**, and use the event's mode only to choose
which keys to work with. Two different questions that the current signature conflates:

- *is this account a tenant of this silo?* — account only
- *which credentials do I use for this event?* — account **and** mode

## Webhook topology, and why one endpoint per silo

The Stripe axis stays **data, not routing** — a single endpoint per silo serves both test and live,
deriving the mode from `livemode`. The alternative (an endpoint per Stripe mode) costs double:

| | one endpoint per silo | one per silo × Stripe mode |
|---|---|---|
| sandbox + production | **2** | 4 |
| + staging | **3** | 6 |

Each new silo is then one registration, one signing secret, one thing to monitor. Signing secrets are
already keyed by `(kind, mode)`, so per-mode separation already exists where it does real work —
signature verification — without multiplying URLs.

**Note what one endpoint per silo does NOT change:** the endpoint never chooses the table. The stack does,
through its environment variables. Routing by URL would give a different address to the same code writing
the same tables — which is why the membership guard, not the topology, is what provides isolation.

## Today's topology, for the record

**One endpoint total**, on production, serving both Stripe modes. Sandbox receives no Stripe traffic at
all — 0 invocations in 24 hours against production's ~77 (measured 2026-09-23). A consequence worth
stating: **the entire webhook path can only be exercised in production.** Every verification during the
2026-09-23 session ran against production data because there was no alternative.

## Phases

- **S1 — the membership guard.** Precondition for everything else. Small, and it closes a latent defect
  that exists regardless of whether another silo is ever added.
- **S2 — a sandbox webhook**, pointed at a Stripe account owned by the platform team. Closes the
  can-only-test-in-production gap.
- **S3 — a staging silo**, if and when the early-access tier is wanted. A stack, its tables, its hostname,
  its endpoint. `plans/STRIPE_MODE_DECOUPLING.md` already anticipated this: *"A future
  `staging.juniorbay.com` is the isolation tier, not a shared-DB."*

## Relationship to other plans

- `plans/STRIPE_MODE_DECOUPLING.md` owns the **Stripe** axis and its P7 owns the isolation debt on it.
  This document owns the **silo** axis. The two are orthogonal, which is the entire point of that plan and
  the reason the vocabulary collision above is so costly.
- `plans/COPY_TO_ENVIRONMENT.md` is about the Stripe axis despite its name — another casualty of the
  collision.
