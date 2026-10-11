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

## Part 4 — The cross-silo lost sale, and a latent false positive

### The bug, before prod takes its first order

`domain/orphan_charges.py` and the third pass of the sweep in `handlers/fee_reconciliation.py`
**do not consult the silo stamp at all.** The module docstring names a silo mismatch as one of the causes
it reports, and then never reads one.

Today this is harmless because production has no sales. **The day production takes its first order, the
sandbox silo's sweep will list that live charge, find no ledger entry in its own tables, and notify the
operator that a sale was lost.** It was not. It landed correctly, in the other silo.

The sweep runs **every 5 minutes** (`template.yaml`, `FeeReconciliationSweep` — five rather than fifteen
because every charge measured was readable within 76–101s), inside `StripeWebhookFunction`. So this is
not a once-a-day annoyance; it is a false alarm every five minutes, starting at the first real sale, on
the notification channel that is supposed to mean *money went missing*. That is how an alert that matters
gets trained into noise before its first true positive.

### The fix

Resolve the charge's silo and skip foreign ones. The resolver exists — `domain/silo_routing.py` has
`stamp_from_event()` and `normalize_silo()`, and already reads the stamp from the several places this
preview API version keeps it.

Three cases, and the third is the interesting one:

| the charge | sandbox's sweep | production's sweep |
|---|---|---|
| stamped `sandbox` | **mine** — report if unheld | skip (foreign) |
| stamped `production` | skip (foreign) | **mine** — report if unheld |
| **unstamped** | **claim it** | **skip** |

The third row follows the documented read rule already implemented in `resolve_event_silo` — *unstamped
means sandbox, never production* — and it happens to point the ambiguity at the silo where a false alarm
is cheap. Keep that direction deliberately, and say why in the code, because it looks arbitrary and is
not: **subscription-mode charges are permanently unstamped** (Part 2), so this row is not a legacy
migration case that ages out. It is permanent traffic.

### The upside the author asked for

> We absolutely want to prevent the 'lost sale' issue. Now that you have fixed it, it would be nice to
> take advantage of it across silos.

Because Stripe is shared, each silo *can* see the other's charges — which means a charge stamped
`production` that production's tables do not hold is a **genuinely detectable lost sale, visible from
elsewhere.** Worth having. But route it correctly:

- **A silo reports orphans for its own stamp**, to the tenant's notifications, as now.
- **Unstamped-and-unheld escalates to the operator, not the tenant** — an unstamped live charge is
  precisely the orphan hit on 2026-10-07, and no tenant can act on it.
- **A silo does not notify about another silo's gap.** A notification that is usually somebody else's
  problem gets ignored, and then it is ignored on the day it is real. If cross-silo visibility is wanted
  later, it belongs in an operator-only report, not in a tenant's bell.

---

## What this plan deliberately does not do

- **No staging silo.** Part 1 replaces it. Reasons above, and the author's own discovery is the evidence.
- **No cross-silo reads of our own tables.** The 2026-08-02 decision stands: Axis 1 only. Everything here
  goes through Stripe, which is shared by nature, or through the tenant profile, which is not per-silo.
- **No demotion of the ledger.** Part 3 completes it; it does not replace it.
- **No new API route.** The stack is at 993,953 of 1,000,000 transform bytes
  (`plans/TRANSFORM_BUDGET.md`); roughly one route fits. Nothing here needs one — the sweep is an
  existing schedule, the metadata is an existing call, the flag is an existing profile field.

## Phasing

**P0 — the silo-aware sweep.** Small, self-contained, and **it must land before production takes its
first order.** A false "a sale was lost" every five minutes is worse than no sweep.

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
