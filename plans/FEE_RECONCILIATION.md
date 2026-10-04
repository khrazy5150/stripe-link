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
- old enough to have settled (**180s** — see the measurement below);
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

## Phase 2 — built, measured, deleted (2026-10-04)

The plan called for an accelerator: correct the fee the instant Stripe says the charge succeeded, rather
than waiting for the sweep. It was built on `payment_intent.succeeded` rather than the `charge.updated`
this was scoped as — already subscribed on the Connect endpoint in both modes, so no Stripe configuration
to add and get wrong, and firing for both sale paths. It looked ideal.

**It never once succeeded.** The event arrives about a second after the charge; the balance transaction is
not readable for 76–101s. Four invocations over four hours, every one logging

    [fees] ..._upsell_1 still unsettled at payment_intent.succeeded; leaving it to the sweep

and each having spent a Stripe API call to learn nothing. That is the same race, and the same waste, as
the three synchronous attempts inside the upsell handler deleted an hour earlier. Keeping it because it
had a phase number would have been sunk cost.

**There is no Stripe event at the right moment.** `charge.updated` is no better — it fires on metadata
edits and other noise, not on settlement. The sweep is the whole answer, and that is not a gap in the
design; it is what the measurement forces. A tenant-visible consequence: a fee is right within 3–8
minutes, never within seconds, and nothing in the product depends on the difference.

Two pieces of the attempt were kept, because both are right regardless:

- **`reconcile_order`**, the single-order primitive the sweep calls. Phase 2 is why it was extracted from
  the sweep's loop, and the separation of "which order" from "what correcting means" is worth having.
- **`metadata[order_id]` on the upsell's PaymentIntent** — free, and it makes a charge traceable back to
  an order in the Stripe dashboard for refunds, disputes and support.

> **The live Connect endpoint is currently `disabled`.** Irrelevant to this now, but it was true while
> Phase 2 existed and would have made it inert in prod regardless.

### What the measurement changed

Two real upsell charges were polled until their balance transaction became readable:

    upsell_1   READABLE after 101s   stripe_fee=94
    upsell_2   READABLE after  92s   stripe_fee=122

Both landed on the same ten-second tick, so the true delay sits between roughly **82s and 101s**. That one
number closed every open timing question in this work, and it is worth stating what it cost to get: three
separate attempts at a synchronous true-up, each built on a different guess about why the previous one
failed. None of them could have worked. The thing being raced was ninety seconds away the whole time.

Consequences, all applied:

- **Phase 2 does not fire for upsells**, and cannot. `payment_intent.succeeded` arrives about a second
  after the charge. It is kept because it costs nothing and would start working if Stripe's timing
  changed; it is no longer described as the thing that closes the window.
- **The session lookup was removed** (above).
- **The gate dropped 300s → 180s**, and the schedule **15 min → 5 min**. The cadence, not the gate, was
  the real latency: a quarter-hour pass left an order wrong for up to fourteen minutes to correct
  something ready in under two. Now ~3–8 minutes.
- **The upsell's synchronous attempts were deleted.** All three of them — the follow-up GET, the
  `expand[]` on the create, and both together with the guard fixed — were two Stripe calls spent to learn
  nothing, on the one path where the buyer is waiting. What remains is `true_up_fees(fees, {})`, which
  NAMES the estimate; that mark is what the sweep selects on, so it is the handoff rather than an attempt.
  The `checkout.session.completed` true-up is **kept**: unlike the upsell's, it demonstrably works, on 7
  of the last 8 main orders.
- **The sweep now logs settle ages** (`fee settle: order=… age=…s readable|NOT YET readable`). Read the
  caveat on `_settle_evidence` first: the data is censored by our own gate, so it proves "settled by N"
  and never "settled at N". It can justify loosening the gate and cannot, alone, justify tightening it —
  which is why the UNSETTLED case is logged too, since an order unreadable at N seconds is the only
  direct evidence of a floor the sweep ever produces. To tighten to 120 honestly, drop the gate below the
  suspected delay for a while and read those lines; each costs a single Stripe call.
### The experiment, and why 120s was NOT taken (2026-10-04)

Ran at a 60s gate and a 1-minute cadence to catch the floor. Both upsell charges came back readable on
their **first** probe:

    fee settle: order=…_upsell_1 age=84s readable drift=+22c
    fee settle: order=…_upsell_2 age=76s readable drift=+31c

Not a single `NOT YET readable` line. So the experiment produced **two more ceilings and no floor** — the
one thing it was run to get. Across all four charges ever measured (76s, 84s, 92s, 101s) every one was
settled by the first look, and nothing has ever been observed *unsettled* at any age.

**The data weakly supports 120s and the change is still not worth making,** because the gate is not what
holds the window open. With a 5-minute cadence the correction lands anywhere in `[gate, gate+300]`:

    gate 180, cadence 5m   ->  3-8 minutes     (today)
    gate 120, cadence 5m   ->  2-7 minutes     (saves 60s on a multi-minute window)
    gate  90, cadence 1m   ->  ~1.5-2 minutes  (what the experiment actually ran at)

The experiment corrected both upsells **within 90 seconds of the charge** — a 5x improvement, and all of
it came from the cadence. Tightening the gate alone is the option that sounds like progress and buys
almost nothing, on four test-mode samples of one card type with no floor evidence behind it.

So 180/5m stands. If the window ever needs to be short, the lever is the cadence, and the cost is a
full table scan every minute — which is trivial today and is what the `fees_source` GSI in **Open** is
for when it stops being.

- **120s remains available**, via `FEE_SETTLE_MIN_AGE_SECONDS`, with no deploy of this plan's code. These were two test-mode charges; 180 is the
  measurement plus room for a slower day. Asking early costs a wasted Stripe call and the next pass is
  only five minutes behind, so the conservative direction is the cheap one.

> **The live Connect endpoint is currently `disabled`.** Phase 2 is inert there until it is enabled, as is
> every other webhook including the `checkout.session.completed` true-up. Not something Phase 2 introduced.

## Open

- **A tenant-facing signal.** A report can now distinguish estimated from settled fees, but nothing
  surfaces it. Worth a quiet marker on an order row rather than a notice — per
  `feedback_notices_only_when_actionable`, there is nothing the tenant can do about it.
- **Orders that never settle.** After 7 days the sweep stops asking. Nothing currently reports the ones
  it gave up on.
- **The scan.** A full table scan every 15 minutes is fine at current volume and will not be forever. A
  GSI on `fees_source` is the obvious answer when it stops being fine.
