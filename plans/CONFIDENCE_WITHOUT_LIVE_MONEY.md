# Confidence without spending live money

## The question

> "It was my understanding that if it works in test we could be certain it works in live. I cannot afford
> to keep spending money to test every live scenario just to confirm. How can we get past this?"

Asked 2026-10-08, after a day in which six defects were found by making real purchases.

## The premise was mostly right, and the evidence says so

Of the six defects found on 2026-10-07/08, **five would have failed identically in test**:

| defect | mode-dependent? |
|---|---|
| order write missing `PK` after the mode retrofit | no |
| refunds route read the action off `resource` | no |
| `PaymentIntentIndex` is `KEYS_ONLY`, returned a stub | no |
| `charge.refunds` absent from the payload | no |
| thank-you page not synthesized without upsells | no — a CONFIGURATION difference |
| **funnel URL carried no `mode`** | **yes** |

Test was not lying. Those paths had **never run at all**, in either mode — every table had just been
wiped and most of this was executing for the first time. "It works in test" had never been established
for them. The lesson is about coverage, not about environments.

## The one real asymmetry

```python
def resolve_stripe_mode(event, body=None, *, default: str = "test")
```

**54 call sites.** An omitted mode resolves to test, so a missing parameter *works* in test and *breaks*
in live. That is the single mechanism that makes test non-predictive, and it is the thing to attack.

The default is deliberately fail-safe — a forgetful caller must never mutate live data — so it should not
simply be removed. The fix is to make omission **visible** rather than silent.

## The four lines of defence

### 1. Replay real payloads — DONE 2026-10-08

`jb-webhook-events-{env}` already stores genuine Stripe payloads. `scripts/capture_webhook_fixtures.py`
lifts them into `tests/fixtures/stripe_events/`, scrubbed of identifying values but **structurally
untouched**: every key's presence and absence is Stripe's, not ours. `tests/test_real_payload_shapes.py`
asserts what the parsers extract from them.

Seven fixtures, covering `checkout.session.completed`, `charge.refunded`, `invoice.paid`,
`payment_intent.succeeded`, `payment_intent.payment_failed`, `customer.subscription.updated`,
`customer.updated`.

This is the highest-value item because every one of the four API-version defects was a hand-written
fixture encoding a belief that had expired. Re-run the capture script after any Stripe API version change.

**Scrubbing note:** the first pass left an account id embedded in a hosted-invoice URL — whole-string id
matching was not enough. Found by grepping the output for a known id, which is the check to repeat.

### 2. Mode-parity tests — DONE 2026-10-08

Run each scenario twice, `mode=test` and `mode=live`, and assert identical behaviour. Any divergence is
a bug by definition. This single harness would have caught the funnel defect, which is the only
genuinely mode-dependent one in the list above.

Cheaper variant worth doing first: a test that every outbound URL the page island builds carries an
explicit mode. `tests/test_post_checkout_carries_mode.py` does this for the funnel builders; generalise it.

### 3. Fakes must refuse what the real thing refuses — PARTLY DONE

The recurring cause. Three were fixed on 2026-10-08:

- a fake table that accepted an item with no key → now enforces the key schema
  (`tests/test_order_claim_keys.py`)
- a fake GSI that returned whole documents → now honours `KEYS_ONLY`
  (`tests/test_orders_find_by_payment_intent.py`)
- a gateway event with the action interpolated into `resource`, a shape API Gateway cannot produce
  (`tests/test_refunds.py`)

Others certainly remain. The rule: **a fake that cannot fail the way production fails is not a test, it
is a description of a world we invented.**

### 4. Exercise every scenario in test mode — AUTOMATED 2026-10-08, manual rehearsal still open

Stripe test mode is free and complete. Combined with (2), results transfer. The paths that have NEVER
run against live Stripe, as of 2026-10-08:

- upsell charge (off-session reuse)
- subscription renewal (test mode only so far)
- dispute (`charge.dispute.created`)
- cart checkout (multi-line)
- abandoned-cart recovery sweep
- invoice paid (test mode only so far)

## What only live can prove, and what it costs

Real fee amounts, Link/wallet payment methods, genuine card declines. Few, and cheap: a refunded live
test costs **44¢**, not $1.45 — only the fees are unrecoverable (Stripe keeps its 34¢; the platform fee
of 10¢ is ours to keep or return, see `plans/REPORTING.md` §6 and the `refund_application_fee` decision).

The expensive part of 2026-10-08 was time, not money.

## Related

### 5. Notice money we never recorded — DONE 2026-10-08

Detection rather than prevention: **nothing noticed that Stripe had taken money we never recorded.** Both
lost sales were found by the operator reading the Stripe dashboard a day later.

`domain/orphan_charges.py`, run as a third pass on the sweep that already executes every five minutes
(no new Lambda and no new route — the stack is at the transform limit). It reads the direction nothing
else does: Stripe's charges, not our orders, so it can find a sale we never heard of. A deleted endpoint,
a stale secret, a silo mismatch and a bug not yet written all surface as the same sentence.

Deliberate choices: a refunded charge still counts (the money moved twice, the books owe both); a failing
orders read reports nothing rather than claiming every sale vanished; notifications are keyed by charge
id so a repeating sweep does not repeat the alarm; and the pass never raises, because fee reconciliation
has real work to do.
