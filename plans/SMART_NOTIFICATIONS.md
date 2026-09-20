# Smart notifications: emailing the meaning, not the event

## The problem

A carrier tracking webhook fires on every scan. A single parcel produces a dozen events — accepted,
departed facility, arrived facility, departed facility again, on vehicle — and **eleven of them mean the
same thing to the person waiting for the box: "it's still coming."** Emailing each one turns a genuinely
useful notice into spam, and the buyer stops reading the one that matters.

The same shape exists outside shipping: Stripe sends `invoice.payment_succeeded` AND `invoice.paid` for one
payment, and `charge.dispute.created` matters enormously while most of its siblings do not.

## Why the dedupe we already have does not solve it

`handlers/stripe_webhook.py` already has two layers, and **neither one helps here**:

1. **Event-id idempotency** — `webhook_events_repository` keyed on `event_id`, checked before processing
   ("Stripe redelivers events; skip any we've already processed"). This suppresses *the same event
   arriving twice*.
2. **Effect-level claiming** — a conditional write marks `first_delivery` on the order so one-time side
   effects happen once even under concurrent delivery.

Twelve tracking scans are **twelve distinct events with twelve distinct ids**, each legitimately new. Event
dedupe passes them all through, correctly. The duplication is not in the delivery, it is in the *meaning*.

That is the whole insight: we need dedupe on **what the event means**, not on the event.

## Three questions, currently conflated

| Question | Answered by | Exists? |
|---|---|---|
| Has this exact event been processed? | event id | yes |
| Does this event MEAN anything a human cares about? | a policy layer | **no** |
| Have we already told them this particular thing? | state on the subject document | **no** |

Policy today is implicit and scattered — inline `if event_type == ...` branches in the webhook handler.
That works while the answer is "email on two event types". It does not survive a source that emits noise.

## The design

### 1. Milestones, not events

A pure mapping from a provider event to a **milestone** — the small set of things a human actually wants to
be told — or to nothing at all.

```
milestone_for(event) -> Milestone | None
```

For shipping, the whole set:

| Milestone | Carrier statuses | Why it earns an email |
|---|---|---|
| `shipped` | PRE_TRANSIT, first TRANSIT scan | "It's on its way", with the tracking link. The one everyone wants. |
| `out_for_delivery` | TRANSIT + out-for-delivery sub-status | Actionable: be home, move the car. Optional. |
| `delivered` | DELIVERED | Check the porch. Also cuts "where is it?" support. |
| `exception` | FAILURE, delivery exception | **The expensive silence.** Bad address, failed attempt. Never suppress. |
| `returned` | RETURNED | The parcel is coming back and the tenant must act. |

Everything else — every intermediate scan, UNKNOWN, a repeated status — maps to `None` and sends nothing.
Being noise is the default; earning an email is the exception.

### 2. Rules that make it "smart"

- **One email per milestone per subject.** `notified_milestones: ["shipped"]` on the shipment document.
  Not on the event — the point is that many events map to one milestone.
- **Never regress.** Milestones are ranked. A TRANSIT scan arriving after DELIVERED (webhooks arrive out of
  order) must not re-notify or walk the state backwards. Compare rank, not arrival time.
- **Exceptions always notify, even late.** They are the case where silence costs the most — a wrong address
  discovered by email beats one discovered by a refund request.
- **A hard cap per subject.** A safety valve: a carrier looping, or a provider replaying its history, must
  not be able to send fifty emails. If the cap is ever hit, that is a bug report, not a delivery.
- **Tenant preference, with a floor.** `shipped` and `exception` are always on; `out_for_delivery` and
  `delivered` are opt-in per tenant. A tenant cannot switch off the two that prevent support tickets.

### 3. Two audiences, different thresholds

`send_email` reaches the **buyer**; the `Notification` documents in `docs/NOTIFICATION_EMITTERS.md` drive
the **tenant's** in-app bell. The same event often deserves both at different thresholds — a tenant may
want every exception in the bell while the buyer gets plain language and nothing else. Keep the milestone
shared and the channel decision separate.

### 4. Plain language, not carrier jargon

A buyer must never see `PRE_TRANSIT`. The milestone is the interface; the content builder in
`domain/receipts.py` turns it into a sentence (see `plans/SHIPPING_PROVIDERS.md` P3 for the mail path this
reuses — pure builder, tenant branding, injectable send, never fails its trigger).

## Where it generalizes

Prove it on shipping, then the same layer answers questions already living as inline branches:

- `invoice.payment_succeeded` and `invoice.paid` are one payment — one milestone.
- `invoice.payment_failed` → a dunning milestone (today nothing tells the customer).
- `charge.dispute.created` → a tenant milestone with a deadline attached.

Do not build the general version first. A policy layer with one caller is a guess about the second.

## How we would know it is wrong

Count **emails sent per shipment**. The policy predicts 1–2 for a normal parcel. If the average drifts
above that, the mapping is leaking noise; if `shipped` is missing for parcels that plainly moved, it is
over-suppressing. Record milestone sends from the first one — like the estimate-vs-actual data in
`SHIPPING_PROVIDERS.md`, it cannot be backfilled.

## Decisions needed

1. **Is `delivered` on or off by default?** It is the highest-volume optional milestone and the one most
   likely to read as noise for a low-value item.
2. **Does `out_for_delivery` exist at all in v1?** It needs sub-status parsing that varies by carrier, for
   modest value.
3. **Who hears `exception` first — buyer, tenant, or both?** A bad address is the buyer's to fix and the
   tenant's to chase.
4. **Does the tenant get a bell item for every milestone, or only exceptions?** A busy shop shipping 40
   parcels a day would drown in `shipped` notifications.
