# Money across silos — Stripe as the one shared book

**Status: NOT BUILT. Designed 2026-10-10** from the author's observation, after discovering that a live
sale taken through the sandbox silo is invisible in production:

> With this current architecture, a STAGING environment as I had envisioned it is impossible. What I
> think should have happened is allow the money to read from Stripe instead of reading it from our
> tables. This way the artifacts (offers, landing pages, booking, etc.) are stuck in their own silo, but
> the MONEY floats across silos per tenant.

That instinct is right, and this plan is what acting on it looks like. It is one design with four parts,
because the parts share a single premise: **Stripe is the only store both silos genuinely share.**

Everything else — offers, pages, products, bookings, carts — is per-silo by deliberate design
(`plans/SILO_MODEL.md`, and the 2026-08-02 decision in `plans/STRIPE_MODE_DECOUPLING.md`: *Axis 1 only,
no cross-silo data sharing*). The money is the one thing a tenant experiences as singular, and today it
is the one thing that gets cut in half by the silo boundary.

---

## Part 1 — Staging is a flag, not a deployment

### The requirement, separated from the mechanism

The author's goal was concrete: *launch without the AI builder, then let tenants try the AI builder on
their real data before it reaches everyone.* That decomposes into two claims that look like one:

| the goal | verdict |
|---|---|
| a tenant uses a feature that is not in production yet, **on their live data, losing nothing** | **achievable today; the machinery is already built** |
| ...in a **separate environment** | **this is what fights the architecture** |

A staging silo would start with empty tables. A tenant who built three pages and took six orders in
staging would find none of it in production the day the feature graduated — which is the *exact* failure
the author just hit with the live sandbox sale, reproduced on purpose and shipped as a feature. There is
no migration that fixes it, because the silo boundary is the thing that makes silos worth having.

### What already exists

`domain/entitlements.py` holds a per-tenant capability set, and **`ai_builder` is already a declared
capability**, with a comment in the source calling it *"Gate 1 of three"*:

```python
CAPABILITIES = {
    "landing_pages": ..., "booking": ..., "sites": ..., "collections": ...,
    "ab_testing": ..., "reviews": ..., "lead_capture": ..., "invoicing": ...,
    "custom_domains": ..., "ai_builder": ..., "bnpl": ...,
}
FREE_TIER_CAPABILITIES = frozenset({"landing_pages", "sites", "collections"})
```

`tenant_entitlement_set(tenant)` resolves what a tenant may do, already handling comped (`exempt`)
tenants and live trials. So the flow for the AI-builder example is: **ship the code to production dark,
turn the capability on for the beta tenants, leave it off for everyone else.** One silo, one dataset,
real live data, nothing stranded at graduation — the flag just goes default-on.

### The one concrete blocker

`domain/platform_subscription_sync.py:114` does a **wholesale overwrite**:

```python
updates["entitlements"] = plan_entitlements(plan)   # and line 100: updates["entitlements"] = []
```

A beta grant stored in that field is wiped by the next Stripe subscription webhook — silently, at an
unpredictable time, for a tenant mid-task. **A beta grant needs its own field** the plan sync cannot
reach:

```
tenant.beta = ["ai_builder"]      # operator-set, never written by billing
tenant_entitlement_set(...)  ->  plan ∪ free-tier ∪ beta
```

Union-only, so a tenant with no `beta` field behaves exactly as today. No migration.

### The honest cost

Production carries unfinished code behind flags. The failure mode is **a gate missed at one call site** —
the same class of defect as the Stripe-mode checks, which were got wrong twice during the mode retrofit
(once by a line-scoped grep that could not see a mode in a POST body).

The mitigation is the shape that already works here: `tests/test_table_grants.py` walks handlers
transitively and fails the build when a grant is missing. The same walk can enumerate the entry points
that touch a flagged capability and fail when one is ungated. **Write that guard before the first flag,
not after.**

### What is NOT being given up

Dev *is* staging — for the operator. What dev cannot do is carry live data, and the gap the author has
actually been feeling is not "no staging" but *"I cannot gain confidence without spending live money"* —
a different problem, addressed in `plans/CONFIDENCE_WITHOUT_LIVE_MONEY.md` and now largely built
(mode-parity tests, test-mode rehearsal, the reconciliation sweep, real-payload fixtures).

---

## Part 2 — Stripe knows four of the six components

The ledger's amounts are six additive, signed components (`domain/ledger.py:15`):

```python
AMOUNT_COMPONENTS = ("gross", "stripe_fee", "platform_fee", "tax", "cogs", "shipping_cost")
net    = gross + stripe_fee + platform_fee
profit = net + cogs + shipping_cost - tax        # cogs and shipping_cost are stored NEGATIVE
```

Of those six, **Stripe already knows four**: `gross` from the charge, `stripe_fee` and `platform_fee`
from the balance transaction, `tax` from the session's total details. Only `cogs` and `shipping_cost`
are ours and ours alone — and `plans/TRANSACTION_LEDGER_STRIPE_LINK.md` has recorded since 2026-07-23
that **neither is ever populated**, so `profit` is incomplete today regardless of which silo you ask.

This is why "read the money from Stripe" is a real design and not a slogan: a Stripe-derived view of a
tenant's money is **4/6 complete immediately**, across every silo, with no table to reconcile. Part 3 is
how it becomes 6/6.

### What is already stamped, measured not assumed

Measured against live Connect events on 2026-10-10:

| event | metadata keys | `silo` |
|---|---|---|
| `checkout.session.completed` | 14 | `sandbox` |
| `charge.refunded` | 1 | `sandbox` |
| `payment_intent.succeeded` | **0** | **absent** |

The session carries `offer_id, page_id, product_id, product_name, product_type, price_id, funnel_id,
order_bump_ids, coupon_code, tenant_id, silo, tenant_plan`. The charge carries exactly one key, because
`handlers/checkout.py:1525` sets only:

```python
payload.setdefault("payment_intent_data[metadata][silo]", silo)
```

**Two consequences worth writing down before anyone builds on this:**

1. `payment_intent_data` is **payment-mode only** — the comment two lines above says so. **Subscription
   renewals' charges carry no stamp at all.**
2. A charge stamped before that line shipped carries nothing either, which is what the 0-key
   `payment_intent.succeeded` above is.

So the stamp is *usually* on the charge and must never be *assumed* to be.

---

## Part 3 — COGS and shipping cost in Stripe metadata

Viable, and it is what turns the 4/6 above into 6/6. The two behave differently and the difference
drives the design:

**COGS is known at checkout.** It is a product field. It can be stamped in the same place `silo` already
is, and rides along at no cost:

```python
payload["payment_intent_data[metadata][cogs]"] = str(total_cogs_cents)   # negative, per the convention
```

**Shipping cost is not known at checkout.** It is known when the carrier label is bought, which is
*after* the charge. `summarize()` already says so in its own comment — *"`shipping_cost` has no source
until a carrier label is bought"*. So it needs a **metadata update on the PaymentIntent at label
purchase**: one idempotent API call, on a path that is already talking to a carrier and already writing a
shipment document.

### Constraints, all real, none fatal

- **Stripe metadata limits: 50 keys, 40 chars per key, 500 chars per value.** The session already uses
  ~14. **Per-line COGS across a multi-line cart must go on each line item's metadata, not the
  session's** — a listicle cart with a dozen lines would otherwise approach the key ceiling, and the
  failure would be a rejected checkout on the tenant's biggest order.
- **Metadata is not queryable.** You cannot ask Stripe to sum October's COGS. You list charges and sum
  locally. Fine at this volume; worth knowing before it is a reporting feature.
- **A later metadata write is not retroactive to the charge's balance transaction.** It is a side-car
  value we wrote, with Stripe's durability and none of Stripe's authority. That is the correct status for
  it — it is *our* number.

### The property that makes this correct rather than merely possible

Metadata is an **immutable snapshot at the moment of sale**. A tenant who corrects a product's cost next
month does not retroactively rewrite last month's margin. That is exactly the behaviour a ledger entry
has, and exactly the behaviour a P&L needs. Storing COGS only in the product record would give the
opposite and wrong behaviour.

### What this does NOT replace

`plans/TRANSACTION_LEDGER_STRIPE_LINK.md` stays canonical for the owning silo. This is not "delete the
ledger and read Stripe" — it is "**Stripe carries enough that any silo can reconstruct a tenant's money,
and the owning silo's ledger remains the fast, queryable, append-only copy.**" Two stores with one
source and a known direction of truth, rather than two stores that can disagree.

---

## Part 4 — The cross-silo lost sale — **BUILT 2026-10-10**

### It was not latent. It was firing, in both silos, every five minutes

The first draft of this plan predicted a false positive *"the day production takes its first order."*
Reading what the deployed sweep was actually logging, within the hour, found it already happening:

```
[ERROR] UNRECORDED STRIPE MONEY tenant=586173f0... mode=test
        {'count': 1, 'amount': 19792, 'charges': ['ch_3UOtmw21lLbLd4Y50K7lDokj']}
```

in **`jb-stripe-webhook-prod` AND `jb-stripe-webhook-dev`**, every five minutes, over a **$197.92**
charge that `jb-orders-dev` held as `order_in_1UOsq521lLbLd4Y50sXIDrlB`, `status: paid`,
`amount_total: 19792`. **Nothing was lost.** Three independent defects stacked, and only one of them was
the one this plan predicted.

### Defect 1 — a subscription charge can never be matched by PaymentIntent

The stored order has **no `payment_intent_id` field at all**. `order_record_from_invoice` keys on the
invoice (`order_{invoice_id}`), and the sweep's only lookup was `find_by_payment_intent`. So **every
subscription renewal that has ever been taken, and every one that ever will be, read as unrecorded
money.** Subscriptions shipped 2026-09-15; this was waiting from that day.

Fixed by matching the invoice *first* — an invoice charge also has a PaymentIntent, one we never store,
so asking the index about it returns nothing and looks exactly like a lost sale.

### Defect 2 — both silos list the same connected account

The two `stripe-keys` tables are per-environment (`jb-stripe-keys-v2-dev` / `-prod`), so each sweep
enumerates only its own tenants. **But they hold credentials for the same `acct_`,** because the tenant
connected Stripe in both silos. So production enumerated its copy of the tenant, listed the sandbox
silo's charges, and asked its own orders table about them.

Fixed by resolving ownership **with the same rule the webhook used when it chose where to write** —
`silo_routing.event_belongs_here`'s own logic: the stamp if there is one, else `LEGACY_SILO_FOR_MODE`.
Mirroring it is the whole point: *if the sweep and the writer disagree about ownership, the sweep reports
as missing precisely the charges the writer correctly declined.*

**The first draft of this plan got that rule wrong.** It said the fallback was *"unstamped means
sandbox, never production"* — that is the **read-side** default in `resolve_event_silo`. The **write
side**, which is what decides where an order actually lands, uses the legacy correspondence: unstamped
`test` → sandbox, unstamped **`live` → production**. Building the sweep on the read-side rule would have
made it disagree with the writer on every unstamped live charge.

### Defect 3 — the alarm was never wired

`handler` defaults `notifications_repo` to `None` for injection. `_notify_overdue` resolves it lazily
from `NOTIFICATIONS_TABLE`; **`_report_orphan_charges` did not.** So `_notify_orphans` took its
`if notifications_repo is None: return` on every scheduled run since it shipped, and both notification
tables held **zero** `orphan_charge_*` rows while the log had been screaming every five minutes.

**The detection built to end the silence was itself silent.** Same shape as `refundError` set and never
rendered, and as the fake that implemented a method the real repository lacked: the end of the path was
never exercised.

Note the ordering luck — had this been fixed first, turning the notifier on would have sent a *critical*
tenant-visible alert about correctly-recorded money every five minutes, in both silos.

### Where the stamp actually lives, verified

A subscription charge carries **no metadata of its own** — `payment_intent_data[metadata][silo]`
(`handlers/checkout.py:1525`) is **payment-mode only**, so the stamp never reaches a renewal's charge.
It does reach the subscription, and the invoice carries the subscription's metadata:

```
charge.metadata                                        {}
charge.invoice.parent.subscription_details.metadata    {... "silo": "sandbox" ...}
```

Reachable for free: **`expand[]=data.invoice` on the charges list** — the same one call, no extra round
trips.

### What shipped

- `silo_routing.stamp_from_object(obj)` extracted; `stamp_from_event` delegates to it. One
  implementation of *where is the stamp?*, because two readers would eventually disagree and the
  disagreement would be invisible until a charge went unclaimed.
- `orphan_charges`: `invoice_id_of`, `order_id_for_invoice`, `owning_silo`, `is_ours`; `orphans()` takes
  `order_for_id`, `this_silo`, `mode`.
- The sweep expands the invoice, passes its `SILO` (already deployed: `sandbox` / `production`), builds
  the notifications repository, and reports `notified` in the tally so *found money, told nobody* cannot
  hide again.
- The fact and the notification now carry `silo`, `orphan_reason` and `invoice_id`, so a wrong alarm can
  be **argued with** rather than merely believed.

**The filter fails open in every direction**: a deployment that cannot name its silo reports everything,
an unrecognised stamp is not trusted, and a charge nothing can attribute is still reported. A false alarm
costs a look at the Stripe dashboard; a suppressed one costs a sale nobody records. That asymmetry is the
only reason the filter is allowed to exist.

### The residual gap, stated

A **sandbox tenant's live subscription charge** is unstamped on the charge, and if its invoice is ever
unreachable the legacy rule attributes it to production. The expansion closes this in practice, and the
sweep now agrees with the writer in every case the writer can decide — which is the invariant that
matters. Routing cross-silo visibility into an operator-only report, rather than a tenant's bell, remains
future work: a notification that is usually somebody else's problem gets ignored, and then it is ignored
on the day it is real.

## What this plan deliberately does not do

- **No staging silo.** Part 1 replaces it. Reasons above, and the author's own discovery is the evidence.
- **No cross-silo reads of our own tables.** The 2026-08-02 decision stands: Axis 1 only. Everything here
  goes through Stripe, which is shared by nature, or through the tenant profile, which is not per-silo.
- **No demotion of the ledger.** Part 3 completes it; it does not replace it.
- **No new API route.** The stack is at 993,953 of 1,000,000 transform bytes
  (`plans/TRANSFORM_BUDGET.md`); roughly one route fits. Nothing here needs one — the sweep is an
  existing schedule, the metadata is an existing call, the flag is an existing profile field.

## Phasing

**P0 — the silo-aware sweep. DONE 2026-10-10.** Not the small change it looked like: three defects, two
of them unpredicted, one of which meant the alarm had never fired at all. It was not waiting for
production's first order — it was running.

**P1 — the beta-grant field.** `tenant.beta`, unioned in `tenant_entitlement_set`, plus the ungated-call-
site guard in the grant-test shape. This is what makes "staging" available at all, and it is a day.

**P2 — COGS at checkout.** One metadata key on the PaymentIntent, per-line keys on line items, and the
ledger entry populated from it. Completes five of the six components.

**P3 — shipping cost at label purchase.** The metadata update, on the path that already buys the label.
Completes the sixth, and `profit` becomes a real number for the first time.

**P4 — the Stripe-derived view, if still wanted.** With P2 and P3 done, any silo can reconstruct a
tenant's complete money from Stripe alone. Whether that becomes a screen, an operator tool, or just a
reconciliation check is a decision better made once the data is actually complete — and it may turn out
that P2/P3 were the whole value, and the view was never the point.

## Related

- `plans/SILO_MODEL.md` — the boundary this works within; S3 is the resolver Part 4 reuses
- `plans/STRIPE_MODE_DECOUPLING.md` — the 2026-08-02 "Axis 1 only" decision
- `plans/TRANSACTION_LEDGER_STRIPE_LINK.md` — the ledger Parts 2–3 complete rather than replace
- `plans/FEE_RECONCILIATION.md` — the sweep Part 4 fixes
- `plans/CONFIDENCE_WITHOUT_LIVE_MONEY.md` — the problem staging was really being asked to solve
- `plans/TRANSFORM_BUDGET.md` — why nothing here is a new route
