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

## DECIDED (author, 2026-09-23)

| question | decision |
|---|---|
| Stripe platform accounts | **ONE, shared by all silos.** Not one per silo. |
| silo roster | **sandbox + production now**; staging designed-for, not deployed |
| tenant ↔ silo | **a tenant MAY exist in several silos at once** |
| the silo anchor | **the Stripe Customer**, buyer-scoped, deduped by email |
| a Customer for every buyer | **yes** — accepted cost, see below |
| erase the data | **not yet.** Plan first. |

Source of the anchor idea: `plans/PRELIMINARY_SILO_ARCHITECTURE.md`.

### The principle behind the one-platform decision

Author, 2026-09-23:

> *The idea is to present a seamless tenant experience, NOT to create a perfect silo environment. If I'm
> running my business on staging and testing new features, I don't want to lose the ability to grant
> refunds when I switch to production. That's the sole purpose of the single Junior Bay platform account.
> We don't want tenant friction when switching between silos.*

This draws a line that is easy to blur, and everything below depends on it:

- **Initiating an action is NEVER silo-gated.** A refund, a cancellation, a subscription change — the
  tenant has ONE Stripe relationship, and any silo they are standing in may act on it. Do not build a
  guard that refuses because "that charge was created in another silo."
- **Recording an event lands in the silo that owns the data.** Only one silo holds the order; that is
  where the refund gets recorded. Other silos see the event and correctly do nothing.

The silo boundary is for OUR data. It is not a boundary in the tenant's business.

## How each event resolves — and how much is already built

| event class | resolves by | status |
|---|---|---|
| `checkout.session.completed` | `metadata[silo]`, which we stamp because we create the session | **to build** |
| `invoice.*` (automatic renewals) | the **Customer anchor** — subscriptions always have one; metadata is unavailable because Stripe created it | **to build** (traversal helper already exists) |
| `charge.refunded`, `charge.dispute.created` | **"do I hold the order?"** — `find_by_payment_intent` on this silo's own table | **already correct** |
| `account.updated` | not silo-specific — the connected account is the tenant's, globally. Every silo that knows the tenant should process it | **already correct** (gated on `tenant_document`) |

Two of the four need nothing. `reconcile_charge_refunded` already resolves the order by payment intent and
returns `order_not_found` when it does not hold it — which is exactly the discriminator, arrived at for
ordinary reasons. `invoice_subscription_metadata` already traverses invoice → subscription metadata,
written 2026-09-23 with the comment *"a renewal invoice we did not create carries none of its own"* — the
anchor strategy, already in production.

**So the work is smaller than the diagnosis suggests.** What is missing is the silo stamp and the Customer
mapping, not a new routing engine.

### The cost we are choosing to pay

Every checkout must create a Stripe Customer, because the anchor cannot work on sessions that have none —
and today **4 of 5 production checkout-session orders have no `stripe_customer_id`** (`customer_creation:
always` is only set when the offer has a post-purchase upsell). The merchant's Stripe dashboard gains a
Customer per buyer.

`stripe_coupons.find_or_create_customer(email)` — built 2026-09-23 for targeted coupons — already does
create-or-reuse deduped by email. Pointing checkout at it keeps a repeat guest buyer as ONE Customer
rather than one per purchase, which is what makes this cost tolerable.

## Evidence — three organic transactions, 2026-09-23

Recorded after S0+S1 were deployed to both silos. The author declined to backfill the older records, so
the pre-stamp objects remain as a **control group** on the same Stripe account: unstamped rows sitting
beside stamped ones, which is stronger evidence than a backfilled set where nothing distinguishes what was
organic.

### The stamp works

| object | `metadata.silo` |
|---|---|
| new subscription session | `sandbox` |
| new subscription `sub_1UJ5D8…` | `sandbox` |
| one-time session | `sandbox` |
| downsell PaymentIntent `pi_3UJ5AH…` | `sandbox` |
| the two pre-S1 subscriptions | **absent** — control group intact, nothing retroactive |

The new subscription carrying the stamp is the one that matters: its renewal inherits it through
`subscription_details.metadata`, which `invoice_subscription_metadata` already reads. The old
subscriptions renew unstamped on the same day, which is the comparison.

### ONE PURCHASE, SPLIT ACROSS TWO SILOS

The clearest statement of the problem this document exists for. A single customer's single purchase:

```
jb-orders-prod   order_cs_test_a1gXWA…               $24.20   the checkout session
jb-orders-dev    order_cs_test_a1gXWA…_upsell_1      $18.34   its downsell
```

**Same order id. Different silos.** The session's order landed in **production** because only production
receives Stripe webhooks. The downsell landed in **sandbox** because the sandbox-published page called
sandbox's `/upsell/charge` **directly** — an API call, not a webhook, routed by the page's own baked
backend URL.

So the two halves of one order are in different databases, and **neither silo can render that order
completely**. Production shows a $24.20 purchase with no downsell; sandbox shows an $18.34 downsell
attached to an order it does not have.

This was invisible before the stamp because nothing distinguished the two. It is the concrete case S3's
resolver has to answer, and it shows the resolver cannot be webhook-only: **an event is not the only way
data enters a silo.** A direct API call from a published page is the other, and it routes by whatever
backend that page was published against.

### Stripe does NOT propagate session metadata to the PaymentIntent

Confirmed on our own data rather than quoted: the two session-driven PaymentIntents came back with **no
`silo`**, while their sessions carry it. The preliminary document warned of exactly this —
*"metadata set on one payment object doesn't automatically propagate to related objects"* — and it is now
observed here.

**Harmless today.** Refunds and disputes resolve by "do I hold the order?" (`find_by_payment_intent`), not
by PaymentIntent metadata. **Worth closing anyway:** `payment_intent_data[metadata][silo]` on the session,
one line, would make charge and dispute events self-describing instead of dependent on a lookup — useful
precisely when the order is in the OTHER silo, as the split order above shows it can be. Not built.

## Phases

Ordered so that each phase is verifiable on its own and nothing is deployed that depends on a later one.

- **S0 — name the silo. BUILT 2026-09-23.** `stripe_link/silo.py` (`SANDBOX`/`PRODUCTION`/`KNOWN_SILOS`,
  `normalize_silo`, `current_silo`) plus a `SiloForEnvironment` mapping in the template feeding a `SILO`
  environment variable. `dev` is a DEPLOYMENT; `sandbox` is a silo. **`normalize_silo` has no default on
  purpose** — both directions of guess are wrong (calling production "sandbox" makes a silo foreign to
  itself; calling sandbox "production" pollutes real data), so an unknown value is unknown and callers
  omit rather than invent. Adding `staging` is an entry in two places, never a new endpoint.
- **S1 — stamp what we create. BUILT 2026-09-23.** `metadata[silo]` on every Checkout Session (so the
  cart path gets it too, sharing `build_checkout_payload`), on `subscription_data[metadata]` so renewals
  inherit it, and on the one-click upsell's PaymentIntent — the one Stripe object we create directly
  rather than through a session. **Gap, deliberately left:** a session's own PaymentIntent is NOT stamped,
  because Stripe does not propagate session metadata to it (observed 2026-09-23, see Evidence).
  **Write-only**: a test asserts that nothing in `src/` reads
  `metadata[silo]` yet, so shipping the stamp ahead of the resolver is provably safe. That test is
  deleted, not edited, when S3 begins.
- **S2 — a Customer for every buyer.** Point checkout at `find_or_create_customer(email)` so every session
  names a Customer. Record `(tenant_id, silo, stripe_customer_id)` in a mapping table as it happens.
  Still nothing routes on it.
- **S3 — resolve, then enforce.** The webhook resolves a silo per event: stamp first, Customer anchor
  second, "do I hold the order?" third. **Log disagreements for a period before acting on them** — a
  stamp that says production against an anchor that says sandbox is an invariant violation and worth
  seeing before it becomes a refusal.
- **S4 — refuse.** Once the logs are quiet, an event resolving to another silo is acknowledged to Stripe,
  logged, and not persisted.
- **S5 — a sandbox webhook.** Only safe after S4. Closes the gap where the whole webhook path can only be
  exercised in production.
- **S6 — a staging silo**, if the early-access tier is wanted. A stack, its tables, its hostname, its
  endpoint. `plans/STRIPE_MODE_DECOUPLING.md` anticipated it: *"A future `staging.juniorbay.com` is the
  isolation tier, not a shared-DB."*

### Migration

**No wipe yet** (author, 2026-09-23). Recorded so the option is not lost: there are no real tenants, every
production order is test, and a clean slate would remove the need to backfill `metadata[silo]` and the
Customer mapping onto existing records. If the wipe happens it should be a STEP of this plan — after S0/S1
are written and before S3 reads anything — not a separate act.

Without a wipe, S3 needs a rule for records that predate the stamp. The same rule as everywhere else in
this codebase: **unstamped means test/sandbox**, never production.

## Relationship to other plans

- `plans/STRIPE_MODE_DECOUPLING.md` owns the **Stripe** axis and its P7 owns the isolation debt on it.
  This document owns the **silo** axis. The two are orthogonal, which is the entire point of that plan and
  the reason the vocabulary collision above is so costly.
- `plans/COPY_TO_ENVIRONMENT.md` is about the Stripe axis despite its name — another casualty of the
  collision.
