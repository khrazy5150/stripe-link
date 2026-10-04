# Fee reconciliation — making a recorded Stripe fee the real one

## The problem

Every sale records an **estimated** Stripe fee when it is written: the configured rate (2.9% + 30¢),
computed locally. Most are corrected seconds later by the webhook, which reads the charge's balance
transaction and replaces the estimate with Stripe's own number.

Upsells are not. An upsell is a PaymentIntent we create ourselves, so no `checkout.session.completed`
fires and no webhook follows it. The handler has to ask for itself — and the balance transaction is not
attached yet at that moment. Proven rather than assumed, on a real funnel (2026-10-04):

    [fees] upsell ..._upsell_1 kept its estimate; stripe returned []
    [fees] upsell ..._upsell_2 kept its estimate; stripe returned []

**Empty, not partial** — and empty again on an immediate retry. Stripe backdates `balance_transaction.created`
to the charge second but attaches it asynchronously, so nothing asked inside the buyer's request can fix
this. Two earlier attempts proved it the hard way:

1. A follow-up GET after the create. Returned nothing.
2. `expand[]=latest_charge.balance_transaction` on the create itself, with the GET as a retry. Also
   nothing — and a bug of its own, since the first version guarded on `if not actual`, and a partial
   `{"net": ...}` is truthy, so the retry was never even reached.

## Why it matters — measured, not argued

The same funnel paid with a Canadian Visa. Stripe adds **1.5% for a foreign-issued card**:

| order | amount | recorded | actual | drift |
|---|---|---|---|---|
| main | 18564 | 847 | 847 | **+0** — the webhook trued it up |
| upsell_1 | 900 | 57 | 70 | **+13** |
| upsell_2 | 1786 | 82 | 109 | **+27** |

Forty cents on twenty-seven dollars, one-directional, **understating the tenant's cost**. Every earlier
run matched to the cent because the cards were US-issued and the estimate is exactly right for those —
which is precisely why this went unnoticed for so long. An estimate is a plausible number, and plausible
is indistinguishable from true until something makes it say which it is.

That something is `fees_source`, which now stamps **both** outcomes (`estimate` / `balance_transaction`).
It used to appear on success alone, so an estimate was marked by the *absence* of a field —
indistinguishable from an order written before the field existed, and from one where nobody tried.

## Phase 1 — the sweep ✅ SHIPPED 2026-10-04

`handlers/fee_reconciliation.py`, on a 15-minute schedule. The authoritative reconciliation pass, and the
one that needs no Stripe configuration.

**It shares the webhook's Lambda rather than owning one.** The first attempt added a function and the
deploy failed: `Transform AWS::Serverless-2016-10-31 returned fragment exceeding 1000000 bytes` — this
stack is at CloudFormation's SAM-transform limit, and a new function no longer fits. Sharing turned out to
be the better home anyway: the sweep does exactly what the webhook does to every other sale, for the one
sale path no webhook follows, and that function already holds every permission it needs (Orders, Ledger,
StripeKeys, KMS, the platform secret). `stripe_webhook.handler` dispatches on `source == "aws.events"`,
**before** reading `httpMethod` — an EventBridge event has none, so a handler that checks HTTP first
answers the schedule 405 and the sweep silently never runs.

> **The stack is full.** This is the first thing that did not fit, and it will not be the last. Splitting
> the stack is now a real piece of work on the horizon, not a tidy-up.

For each order that says it is an estimate: ask Stripe for the charge's balance transaction, and if it has
settled, correct **the order and its ledger entry together**. Correcting one without the other leaves the
two disagreeing, which is worse than correcting neither — every report a tenant reads is built from the
ledger.

**The selection rule** (`domain/fee_reconciliation.due`) is four conditions, each with a reason:

- it must SAY it is an estimate — an order with no `fees_source` predates the marker, and correcting one
  would rewrite history nobody asked anyone to touch;
- it must name a charge — without `payment_intent_id` there is nothing to look up, which was true of
  every upsell ever written until 2026-10-04;
- old enough to have settled (5 min — anything younger is caught by the next pass, and asking early only
  wastes a Stripe call);
- young enough to be worth retrying (7 days — still estimated after a week is a thing to look at, not to
  retry forever).

**That first condition is also the data boundary.** Orders written before `fees_source` existed are never
selected. Not a cutoff anyone has to maintain — just the honest consequence of only correcting what
announced itself as uncorrected.

**Other properties worth keeping:**

- The ledger row is *restated in place*. The entry id is deterministic (`le_sale_<pi>`), so appending the
  rebuilt row overwrites rather than double-counting — the same property the webhook relies on to be
  replay-safe. Its original `source` and `occurred_at` are read back off the stored row, so an upsell row
  does not turn into a `webhook` one dated to the moment it was corrected.
- Every failure is **per order**. One revoked key, one unsettled charge, one Stripe outage must not stop
  the pass; the next one picks up whatever this one left, because `fees_source` still says `estimate`.
- Credentials resolve **once per tenant** — a Secrets Manager read plus a KMS decrypt per order is waste.
- An unsettled charge is deliberately left marked `estimate`. That is what makes the next pass retry it.

## Phase 2 — `charge.updated` (not built)

Subscribe the platform webhook to `charge.updated` and true up the mapped order immediately, to narrow
the window from ~15 minutes to seconds. Needs a new event subscription, which is why it is second.

**The sweep stays underneath it, permanently.** An event that never arrives leaves no trace; a sweep that
finds nothing costs one scan. The webhook is an accelerator, not a replacement.

## Open

- **A tenant-facing signal.** A report can now distinguish estimated from settled fees, but nothing
  surfaces it. Worth a quiet marker on an order row rather than a notice — per
  `feedback_notices_only_when_actionable`, there is nothing the tenant can do about it.
- **Orders that never settle.** After 7 days the sweep stops asking. Nothing currently reports the ones
  it gave up on.
- **The scan.** A full table scan every 15 minutes is fine at current volume and will not be forever. A
  GSI on `fees_source` is the obvious answer when it stops being fine.
