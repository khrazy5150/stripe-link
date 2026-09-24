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

## The proposal

**If an event names a connected account and that account is not a tenant of this silo, do not process it.**

- Acknowledge to Stripe (2xx) so it stops retrying — the event is not ours and never will be.
- Log loudly, with the account id and the silo. A silo receiving another's traffic is a misconfiguration
  someone needs to hear about, not a condition to swallow.
- Persist nothing — no order, no ledger entry, no notification, no email.
- Keep the metadata fallback **only** for events that carry no `account` at all (platform-account events).

Open question for implementation: whether a brand-new tenant can produce an event before their
`stripe_keys` row exists. If so the guard needs a grace path, and the answer decides whether "not found"
means *reject* or *retry*.

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
