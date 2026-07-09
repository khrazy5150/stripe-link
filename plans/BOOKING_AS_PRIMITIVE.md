# Booking as a First-Class Primitive

Status: **proposed** (design only — no code yet). All decisions below are author-approved.

> **Greenfield note.** Services-in-offers shipped the same day this flaw was found. There is **no legacy
> data or frozen client** to preserve — so there is **no back-compat layer**. The appointment entity is
> reshaped directly; any stray test appointments are wiped or trivially backfilled once.

## 1. The flaw we're fixing

Today an `appointment` is **1:1 with a service** (`appointment.service_id` is singular). That coupling
makes two real situations impossible:

1. **One visit, several services** — a customer wants **tax preparation *and* notary** in the *same*
   booking (one slot, one visit). Today the tenant must book each service separately.
2. **A service that needs no booking at all** — e.g. a repair shop **tops off fluids with every oil
   change**: a sellable, *taxable* service with no appointment. It may be an order-bump or standalone.

The fix: **an appointment is a scheduled visit covering `services[]`** — one or more service line items —
and a Service declares whether it even needs a booking.

## 2. Locked decisions

- **`services[]` is the one canonical field.** `appointment.services[]`, required, `minItems: 1`. **No**
  scalar `service_id`/`service_name`, **no** mirror, **no** read adapter. A single service is just a
  one-element `services[]`.
- **The Offer coordinates the "how."** The Offer is the single source of truth for a landing page *and*
  for how its services are delivered: no booking, one combined visit, or many separate visits.
- **A combined (multi-service) booking is single-fulfiller for v1.** One visit covering multiple services
  implies a single-owner/freelancer op, so it uses **one fulfiller (or unassigned)**. Different delegates
  under the *same* visit (multi-resource scheduling) is a **deferred phase** — §9.
- **`no_booking` is a Service, not a Product — because of TAX.** A non-bookable service is fiscally a
  *service*; tax treatment differs. It stays in the service catalog with a `fulfillment_mode`.
- **The entity stays `appointment` / `appointment_id`.** Not renamed to "Booking" — "booking" already
  means the *verb/flow* here (`booking.py`, `booking_page`, `booking_flow`); a `Booking` entity would
  collide. "Booking" in this doc is an informal label for "an appointment that now covers many services."

## 3. The primitives

### Service (evolved)
A **priced unit of work**. Adds **`fulfillment_mode`**:
- `scheduled` — needs a time slot (today's behavior). Has `duration_minutes`, fulfiller/calendar routing,
  check-in/completion rules.
- `no_booking` — pay-only, no scheduling. Fulfilled immediately/async. Still routes to a fulfiller for
  **payout/commission** and is **taxed as a service**. `duration_minutes` not required.

### Appointment (evolved)
A **scheduled visit** covering `services[]`:
```
Appointment {
  appointment_id, tenant_id,
  services: [ { service_id, price_id, fulfiller_id?, rule_snapshot?, duration_minutes } ],  // ≥1, required
  starts_at, ends_at, timezone,          // one window for the whole visit
  fulfiller_id,                          // v1: one fulfiller for the visit
  duration_minutes,                      // = sum of the service lines' durations (v1)
  status, payment_status, awaiting_schedule,
  customer, order_id, offer_id, invoice_id, page_id, source, ...
}
```
No scalar `service_id`. Readers use `services[]` (`services[0]` for the representative line). If an
explicit anchor is ever needed, add a `primary_index` (int into `services[]`, can't dangle) — **not** a
duplicate id.

### Offer (evolved)
Coordinates delivery of its scheduled services:
- **`service_booking_mode`**: `single_visit` (all scheduled services → one appointment) |
  `separate_visits` (each scheduled service → its own appointment). Default `single_visit`.
- `no_booking` services in the offer are simply **fulfilled** (order line + payout), never booked.
- `service_booking_mode` is **shorthand that expands into per-item booking groups** via one resolver
  `booking_groups_for(offer)`. **Future:** explicit per-item `booking_group` for *mixed* offers — an
  item's explicit group wins, else falls back to the mode-derived default. One source of truth, never two
  contradictory knobs. See §9.

## 4. Scenario mapping

| Scenario | Model |
|---|---|
| Tax prep + notary, **same visit** | Offer `single_visit` → **one appointment**, two service lines, duration 60+15=75, one slot. |
| Massage + facial, **separate visits** | Offer `separate_visits` → **two appointments**, scheduled independently. |
| Fluid top-off **with** oil change | Oil change (`scheduled`) → one appointment; fluid top-off (`no_booking`, order-bump) → fulfilled, no appointment. |
| Standalone no-booking service | Offer of only `no_booking` services → **no appointment**, just an order (taxed as a service). |
| Single service | One appointment, one service line — the degenerate case, not a special path. |

## 5. Data model (schemas)

- **`Service.schema`** — add `fulfillment_mode` (`scheduled` | `no_booking`, default `scheduled`);
  `duration_minutes` optional when `no_booking`.
- **`Appointment.schema`** — replace singular `service_id` with **`services[]`** (`minItems: 1`; each line
  `service_id`, `price_id`, optional `fulfiller_id`, `rule_snapshot`, `duration_minutes`).
  `duration_minutes`/`price` become the visit-level rollup. Entity name/`document_type`/`appointment_id`
  /paths unchanged. **No mirror, no back-compat fields.**
- **`Offer.schema`** — add `service_booking_mode` (`single_visit` | `separate_visits`); reserve per-item
  `booking_group` for the future; relax the (added-today) "one service item" cap to allow N.
- **Migration:** none. Greenfield — any existing test appointments are wiped or a one-time script wraps
  the old `service_id` into `services[]`, run once and discarded.

## 6. Flows

- **Checkout** (`POST /checkout`, sync) — metadata carries **all** scheduled service lines + `no_booking`
  lines + the offer's `service_booking_mode`, so the webhook can fan out.
- **Webhook** (`POST /webhook/stripe`, event) — `persist_service_purchase` creates **1..N appointments**
  per mode (`single_visit` → one appointment, all lines, duration = sum; `separate_visits` → one per
  scheduled line), each `awaiting_schedule`; `no_booking` lines → order fulfillment + payout snapshot,
  **no appointment**. `invoice.paid` fans `payment_status` out to `source.appointment_ids[]`. Idempotent,
  order-independent.
- **Scheduling** (`POST /services/appointments/manage/schedule`, sync) — the customer schedules each
  appointment (one slot for a combined visit, N for separate). Combined availability needs one
  **contiguous slot of the summed duration** for the **single fulfiller**; comp still tracked per line.
  Re-validates availability + slot lock. Response is an **array** of appointments.
- **book-then-pay** — appointment(s) created `booked`+`unpaid`; **one invoice per purchase** with one line
  per service (`source.appointment_ids[]`), via `invoice_from_order` (generalizing
  `invoice_from_appointment`). `invoice.paid` fans out.
- **Direct booking page** (`GET /book/{service}`) — a single service produces a one-line appointment.

## 7. API model / architecture

Both synchronous and event-driven — the split follows a principle, not a preference:

| Operation | Model | Why |
|---|---|---|
| Create 1..N appointments on purchase; `no_booking` fulfillment + payout snapshot | **event** | Downstream of payment; Stripe is the source of truth. |
| Schedule appointment(s); availability/catalog reads; invoice-from-order *create* | **sync** | Customer is blocking; needs immediate answer + consistency (slot lock). |
| `invoice.paid` → mark appointments paid | **event** | External timing. |

**Invariants the PRD must state:**
1. **Idempotency everywhere** — event handlers keyed on `session/invoice id + line/appointment index`;
   sync mutations keyed on slot-lock / schedule.
2. **No webhook ordering assumption** — at-least-once, possibly out of order; handlers order-independent.
3. **Fan-out stays inline in the webhook Lambda** for v1 (generalizes `persist_service_purchase`). An
   internal event bus (EventBridge/SNS) is a documented future scaling option, **not** v1.

## 8. Endpoint surface

**Changed (design + contract carefully):**
- `POST /checkout` — emit all scheduled lines + `no_booking` lines + `service_booking_mode` in metadata.
- `POST /webhook/stripe` (+preview) — fan out 1..N appointments; `no_booking` fulfillment; paid fan-out.
- `POST /services/appointments/manage/schedule` — schedule 1..N; array response; summed-duration availability.
- `POST /offers/resolve`, `PUT /offers` — `service_booking_mode`; allow >1 service item.
- `POST /invoices/from-appointment` → generalize to **from-order** — one invoice/purchase, `appointment_ids[]`.
- `POST /services/appointments/reserve`, `.../checkout` — emit/charge `services[]` (sum).
- `POST /services/appointments/manage/{cancel,reschedule}`, `GET .../manage` — multi-line / multi-appointment.
- `GET /services/{service_id}/availability` — combined (summed-duration) variant.
- `GET/PUT /services`, `.../{service_id}` — `fulfillment_mode`.
- `GET/PUT /services/appointments`, `.../{id}`, `.../{id}/{action}` — `services[]` shape; whole-visit actions (single fulfiller v1).

**Unchanged (out of scope for v1 — state explicitly):**
- `GET /book/{service}` (direct page), `POST /pages/{page_id}/post-checkout/next` (upsell chaining).
- `GET/PUT /invoices`, `/invoices/{id}`, `/invoices/{id}/send` — mechanics unchanged; new invoice
  *behavior* (paid fan-out) lives in the webhook.
- `/services/fulfillers/*`, `/services/availability/defaults|exceptions/*`.

**Nuances:** "Create appointment" has three entry points — `reserve` (sync, book-then-pay), the **webhook**
(event, pay-then-book — the only fan-out path), and admin `PUT`. All adopt `services[]`; only the webhook
+ offer path fans out to 1..N. **`no_booking` services touch only checkout + webhook** — they never
create an appointment, so no schedule/manage route changes for them.

## 9. Compensation, payout & tax

- **Per-line comp:** each service line carries its own `rule_snapshot`, so payout reporting is correct
  even when one fulfiller performs several services in a visit.
- **`no_booking` fulfiller assignment:** resolve like a scheduled service — use the service's
  `default_fulfiller_id` if set (freeze `rule_snapshot` at purchase/webhook time); if none, leave
  **unassigned = tenant/business revenue, no individual commission** (a legitimate terminal state, not an
  error). Note the asymmetry: for a *scheduled* appointment "unassigned" means "pick someone before
  scheduling"; for a `no_booking` line it is **final** (no later assignment step). Solo tenants get 100%
  with no phantom split for free. *(Future: the Offer may attribute a `no_booking` line to a scheduled
  line's fulfiller.)*
- **Tax:** `no_booking` services stay **services** for fiscal treatment; ties into the tax/fee accounting
  in `AI_AND_COMMERCE_ARCHITECTURE.md`. Per-service tax categorization is its own follow-up (§10).

## 10. Deferred phases (documented so they don't fall through)

- **Multi-fulfiller single visit (multi-resource scheduling).** Different delegates in the *same* visit →
  find a slot where *all* required fulfillers are free (and sequence them); duration stops being a sum and
  becomes "max across concurrent tracks + sequential portions," and availability becomes an *intersection*
  of fulfillers' free windows (needs per-line start-offsets / a track model). v1 restricts a combined
  appointment to one fulfiller. Distinct, non-trivial phase.
- **Per-item `booking_group` on offers.** Mixed offers (some services share a visit, others separate),
  beyond the offer-wide `single_visit`/`separate_visits` switch — the general form of §3's resolver.
- **Optional combined-duration override/buffer (single fulfiller).** For shared setup/intake, an
  *offer-level* adjustment; service `duration_minutes` stays pristine. Only if tenants ask.
- **Bill-on-completion / installment invoicing.** Per-appointment invoices billed as each visit completes
  — a distinct billing model opted into per tenant, vs the default one-invoice-per-purchase.
- **Service tax categories.** Per-service tax classification + reporting, paired with the commerce tax/fee work.

## 11. Resolved design decisions

- **Combined visit duration** → **sum** of line durations (single fulfiller ⇒ sequential ⇒ exact). Optional
  offer-level buffer is the only single-fulfiller escape hatch (§10); true parallelism belongs to the
  multi-fulfiller phase.
- **book-then-pay invoicing** → **one invoice per purchase**, itemized, `source.appointment_ids[]`;
  bill-on-completion is a deferred opt-in mode. Assumption: **one purchase = one payment posture** (so
  pay-then-book vs book-then-pay is an **offer-level** timing, like `service_booking_mode`).
- **`no_booking` fulfiller** → service default → else unassigned (tenant revenue). Not force-assigned.

## 12. Phasing

1. **Appointment model** — `services[]` (required); `Service.fulfillment_mode`; single fulfiller. Direct
   booking + existing flows adopt the new shape.
2. **Offer coordination** — `service_booking_mode`; checkout metadata carries all lines; webhook creates
   1..N appointments; `no_booking` fulfilled without an appointment.
3. **Scheduling UX** — schedule 1..N appointments; summed-duration availability; `invoice_from_order` for
   book-then-pay.
4. **Deferred (§10)** — multi-fulfiller single visit, per-item booking groups, duration buffer,
   bill-on-completion, service tax categories.

## 13. Relationship to existing plans

- Builds on `SERVICES_IN_OFFERS.md` (services first-class in offers; the Offer is the source of truth);
  this doc decouples the *booking* from the *service*.
- Compensation/calendar routing from `MULTI_CALENDAR_ARCHITECTURE.md` applies per service line.
- Tax categorization pairs with `AI_AND_COMMERCE_ARCHITECTURE.md`'s tax/fee accounting.
