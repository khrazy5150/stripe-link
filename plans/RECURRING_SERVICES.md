# Recurring services

Raised 2026-09-20: *"services don't offer a recurring pricing model; they are all one-time. I can think of
recurring services such as landscaping or cleaning that could be best billed as recurring."*

Status: **design only, nothing built.** The author asked for this planned in full rather than piecemeal.

---

## 1. Why it is one-time today

Deliberate, and written down three times in plans/SERVICES_IN_OFFERS.md: `pricing_model` is *"`one_time`
now; `recurring`/`customer_chooses` later"*, `checkout.mode` keeps `subscription` *"reserved for recurring
services (later)"*, and Phase 4 lists *"recurring (subscription) services"* alongside packages and PWYW.

So this is a deferral, not an oversight. What has changed since is that **product** recurring shipped
(2026-09-15), so the billing half now exists and has been exercised.

## 2. A live hazard, independent of whether this is ever built  ✅ CLOSED 2026-09-20

`resolve_service_offer_item` never applies `recurring_terms(price)` — the product resolver does — and
`validate_service` **accepts** a recurring service price. Proven 2026-09-20:

```
service price says:   pricing_model=recurring, monthly
resolved line says:   recurring = None
Stripe session mode:  payment
-> the customer is charged ONCE
```

The only thing preventing a silent mis-charge is a dropdown offering one option. That is the shape this
codebase keeps reproducing — two things that must agree with nothing forcing them to — and it is the same
failure the product recurring bug had on 2026-09-15.

**Closed by refusing.** `validate_service` rejects any `pricing_model` but `one_time` (both `prices[]` and
the legacy `price`), `resolve_service_offer_item` refuses one as defence in depth, and a test binds the
form's offered models to what the validator accepts. Honouring it instead would have shipped half a feature.

This changes nothing about §4–§7: when recurring services ARE built, the narrowing is one constant to widen,
and the tests around it say exactly what has to become true first.

## 3. What already exists (checked, not remembered)

More than the older notes suggest. `BOOKING_AS_PRIMITIVE.md` is marked "no code yet"; that is stale.

| | State |
|---|---|
| `Appointment` | Real. **`services[]` is already the canonical shape** — the multi-service model that plan argued for, greenfield, no scalar `service_id`. |
| Lifecycle | `reserved → booked → paid → checked_in → completed`, plus `canceled` / `no_show`. |
| Slot locking | `reserve_route` + a slot-locks repository. |
| Self-service | `manage_view` / `manage_cancel` / `manage_schedule` / `manage_reschedule`, behind a manage token. |
| Google Calendar | Real API client: create / update / delete events, and `free_busy` for busy intervals. |
| Fan-out at purchase | `checkout.session.completed` builds appointments from the `service_lines` metadata the checkout payload carries. |
| Billing | Product recurring shipped: `pricing_model`, `recurring{interval, interval_count}`, trials, subscription mode chosen from any recurring line. |

**The gap is narrower than "build booking".** Booking exists and works for one appointment. What does not
exist is anything that produces appointments *over time*, and the calendar client creates **discrete events
only** — no `RRULE`, no `recurringEventId`.

## 4. The insight that should shape this: these are TWO products

"Recurring service" sounds like one feature. It is two, with different customers, different mechanics, and
different failure modes. Building one and calling it done would strand the other.

### 4a. A standing appointment — "every Tuesday at 9am"

Landscaping, cleaning, a regular dog walk. The customer buys a **slot in perpetuity**. The time is the
product; changing it is an event worth confirming.

- Each cycle must produce an appointment at the same weekday/time.
- The calendar wants a recurring event, or N discrete ones we keep in step.
- Cancelling *one visit* ("we're away next week") is ordinary and must not cancel the subscription.
- A failed payment has to decide: hold the slot, or release it to someone else?

### 4b. A plan drawn down on — "four cuts a month"

A salon package, a coaching retainer, a massage plan. The customer buys **entitlement**, then books each
visit when it suits them.

- Each cycle grants N bookable credits; nothing is scheduled automatically.
- Unused credits at cycle end: expire, or roll over? (Expire is simpler and is what most such plans do;
  rollover turns this into a ledger.)
- This is much closer to what the booking machinery already does — the customer self-books through the
  existing manage/schedule route.

**Recommendation: build 4b first.** It reuses the existing booking flow almost unchanged, it has no calendar
recurrence problem, and "buy a plan, book when you like" covers salons, coaching, therapy and personal
training. 4a is the harder shape and deserves to follow, informed by real 4b usage.

## 5. The decisions 4a forces, which are the reason it is hard

Each needs an answer before any of 4a is written.

1. **Who creates the Nth appointment, and when?** On `invoice.paid` (automatic, but Stripe's retry timing
   then decides when a customer's visit appears), or a rolling horizon regenerated by the existing 15-minute
   sweep (predictable, but appointments exist before they are paid for)?
2. **One calendar event with an `RRULE`, or N discrete events?** Recurrence is cheaper and drifts badly the
   first time one occurrence moves. Discrete events are what the client already writes.
3. **Cancel semantics.** Three distinct actions — cancel this visit, cancel the subscription, cancel the
   subscription *and* all future visits — and today's `manage_cancel` knows only one.
4. **Payment failure.** Hold the slot (revenue protected, calendar blocked for a non-payer) or release it?
5. **Fulfiller continuity.** The same person every week, or whoever is free? A standing appointment usually
   means the same person, which the current per-appointment assignment does not express.
6. **Proration and mid-cycle changes.** Stripe handles the money; nothing decides what happens to the visits.

## 6. What 4b actually needs

Much shorter, which is the argument for doing it first.

1. **§2's hazard closed** — the resolver honours `recurring` on a service line.
2. `SERVICE_PRICING_MODELS` gains `recurring`; the wizard's price step exposes interval + count, reusing the
   `PricingCard` block products already use.
3. `validate_service` validates a recurring service price with the **same** `validate_recurring_price` the
   product path uses — one implementation, not a parallel one.
4. An **entitlement** record: how many bookings this subscription grants per cycle, and how many are left.
   This is the only genuinely new document.
5. `checkout.session.completed` grants credits instead of creating an appointment; the existing
   `manage_schedule` route spends one.
6. The webhook's `invoice.paid` path refreshes the cycle's credits.

Deliberately **not** in 4b: rollover, proration, standing slots, calendar recurrence.

## 7. Order

1. **Close §2** — the mis-charge hazard. Small, and independent of everything else here.
2. **4b**, end to end, including a real purchase and a real booking against it.
3. **Decide §5** with 4b in production, where the questions have evidence behind them.
4. **4a**, and revisit `BOOKING_AS_PRIMITIVE.md` at the same time — a standing appointment is exactly the
   case that plan's "Booking covers services[] line items" model was drawn for.

Not in scope: customer-chooses (PWYW) services and multi-price packages, both still Phase 4 of
plans/SERVICES_IN_OFFERS.md. Packages overlap 4b and should be reconsidered once entitlement exists.
