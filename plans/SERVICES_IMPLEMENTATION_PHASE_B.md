# Services Phase B — Booking Runtime

**Status:** design, not yet built · **Parent:** `plans/SERVICES_IMPLEMENTATION.md` (Phase B section) ·
**Behavioral reference:** stripe-cart `src/services.py` · **Depends on:** Phase A (admin + lifecycle,
shipped) and the minimal ledger (`sale_entry`, shipped).

## Goal

Turn the configured catalog into a working booking system: a customer picks a service, sees **real
open slots**, reserves one, **pays (or books free)**, and can self-serve **cancel/reschedule** — while
the tenant's calendar fills and every paid booking lands in the ledger. Calendar sync, SMS, and payable
invoices are **Phase C**.

## What Phase A already gives us

- All five documents (Service, Fulfiller, TenantAvailability, AvailabilityException, Appointment) with
  CRUD, and the **appointment lifecycle** state machine (`assign/check-in/complete/cancel/no-show`).
- The admin screens to configure services, fulfillers, hours, and exceptions.
- The ledger `sale_entry` builder (paid bookings write into it, exactly like product sales).

## What's missing (this phase)

The **slot engine**, the **public booking flow** (resolve → reserve → checkout/confirm → manage), the
**storefront booking surface**, and the **paid-booking webhook branch**.

## Principles

- Pure domain for the scheduling math (no I/O); thin handlers load documents and call it.
- **Public** endpoints live in a separate resolve-style handler (mirroring `experiments_resolve` /
  `custom_domains_resolve` / `routes_resolve`), never the admin `services` handler. Tenant is derived
  from the service/appointment, not an admin session.
- **Server owns money and slots:** price is computed server-side (never trust the client); the slot is
  secured with an atomic conditional write (never trust an availability read).
- **Direct-charge Connect** for paid bookings — reuse `checkout.py`'s `checkout_credentials` +
  `build_checkout_payload(apply_application_fee=…)`; **free/lead-gen** bookings skip Stripe.
- `mode` (test/live) threads through every booking write.

---

## B.1 Slot-availability engine (the keystone)

New pure module **`domain/scheduling.py`** — port the legacy `_local_day_slots`:

```
available_slots(service, tenant_availability, fulfillers, exceptions,
                appointments, *, now_epoch, range_start, range_end) -> list[slot]
```

Algorithm (all in the tenant **timezone** via stdlib `zoneinfo`, DST-aware):
1. **Effective weekly hours** = tenant default (`TenantAvailability.weekly_hours`), overridden by the
   assigned/eligible **fulfiller's** personal hours when a fulfiller is in scope.
2. Walk each day in `[range_start, range_end]`, emit candidate starts stepped by
   `slot_interval_minutes`, each lasting the service `duration_minutes`.
3. **Drop** a slot if it: starts within `lead_time_minutes` of `now`; overlaps an
   `AvailabilityException` of type `block` (respecting `fulfiller_scope`); or overlaps an existing
   **appointment** (respecting `buffer_before_minutes`/`buffer_after_minutes` and duration). A
   `reserved` appointment blocks **only until its `hold_expires_at`** (expired holds don't block).
4. Return `[{start, end, fulfiller_id?}]`.

**Endpoint (public):** `GET /services/{service_id}/availability?from&to&fulfiller_id` — the handler
loads the service, tenant availability, in-scope fulfillers, exceptions, and existing appointments,
then calls `available_slots`. Heavy unit coverage: DST boundaries, lead/buffers, exception scopes,
overlap edges, fulfiller override, multi-fulfiller union, expired holds.

---

## B.2 Public booking flow

New public handler **`handlers/booking.py`** (resolve-style):

- **`GET /services/resolve?service_id=`** — public service view for the widget: service +
  `presentation` + the resolved single price + open slots. Billing-paywall gated like other public
  surfaces.
- **`POST /services/appointments/reserve`** — create a `reserved` Appointment holding the slot with a
  TTL (`hold_expires_at`, e.g. now + 10 min), a server-generated **`customer_manage_token`**, and the
  **server-computed price**. Double-booking is prevented by an **atomic slot-lock** (below), not by the
  advisory availability read. Returns the appointment + manage token.
- **`POST /services/appointments/checkout`** — for the reserved appointment:
  - **Paid** service → a Stripe **Checkout Session on the connected account** (reuse
    `checkout_credentials` + `build_checkout_payload`, `apply_application_fee=True`), with
    `metadata.appointment_id` + `metadata.tenant_id`; returns the URL.
  - **Free/lead-gen** service ($0) → confirm immediately: `status: booked`, drop `hold_expires_at`,
    emit the booked notification.
- **Webhook branch** — extend `stripe_webhook` `checkout.session.completed`: when the session carries
  `appointment_id`, mark the appointment `paid`/`booked`, **remove `hold_expires_at`**, append a
  ledger **`sale_entry`** (keyed `le_sale_{payment_intent}`, referencing `appointment_id`), and emit
  the booked notification. Idempotent via the webhook-events table.
- **Customer self-serve:** `GET /services/appointments/manage?appointment_id&manage_token` (token-
  authorized view), `POST …/manage/cancel`, `POST …/manage/reschedule` (release the old slot, reserve
  a new one under the same token; free move within the same service for v1).

### Slot-lock (double-booking prevention)
Reserve does a **conditional write**: a deterministic lock item keyed by
`(tenant_id, fulfiller_id, slot_start)` written with `attribute_not_exists` — if it already exists, the
slot is taken → 409, re-fetch availability. The lock carries the same `hold_expires_at` TTL so an
abandoned hold frees the slot automatically (DynamoDB TTL). Confirmation on payment makes the booking
permanent; expiry/cancel deletes the lock.

---

## B.3 Storefront booking surface

**v1: a hosted booking page per service** — `GET /book/{service}` rendered server-side (same hosting
path as published pages/checkout). It shows the service + a **slot picker** (calendar/time list from
`/availability`), collects customer name/email/phone, then calls **reserve → checkout/confirm**. Small
client script drives slot selection and the reserve/checkout calls; the page never sees or sets price.

**Follow-up (not v1):** a composable **booking section** for the page builder so a landing page can
embed booking inline — aligned with the Phase 1 composition system.

---

## B.4 Payments & the ledger

- Reuse the product-checkout Connect path; the only new wiring is `metadata.appointment_id` and the
  webhook branch.
- On paid confirmation, the **same `sale_entry`** used for products records the booking (gross =
  service price; `stripe_fee`/`platform_fee` from the session/fees; `order_id` set to the
  `appointment_id` for the money-timeline). Free bookings write no ledger entry.
- **Compensation snapshot:** on book/assign, snapshot the fulfiller's *effective* comp (service
  `allowed_fulfillers` override → fulfiller default) onto the appointment's `rule_snapshot`, so later
  payout/comp reporting uses what was true at booking, not current config.

## B.5 Notifications (first real emitters)

Appointment **booked** and **canceled** write unread `Notification` docs (the bell already counts
them) — the concrete first emitters beyond checkout, per `docs/NOTIFICATION_EMITTERS.md`.

---

## Data model changes

- **Appointment:** add `hold_expires_at` (epoch; reserve TTL, removed on confirm) and `customer_manage_token`
  (or a hashed `manage_token_ref` + raw token in the link). `rule_snapshot`, `price`, `payment_status`,
  and lifecycle timestamps already exist.
- **New lock item** (in `ServicesTable`): `document_type: "slot_lock"`, keyed deterministically by
  `(tenant_id, fulfiller_id, slot_start)`, with `hold_expires_at`.
- **Enable DynamoDB TTL** on `ServicesTable` using `hold_expires_at` — only reserved holds and locks
  carry it, so only abandoned holds auto-delete (booked appointments have it removed on confirm).

## Infrastructure (`template.yaml`)

- New public routes: `GET /services/{service_id}/availability`, `GET /services/resolve`,
  `POST /services/appointments/reserve`, `POST /services/appointments/checkout`,
  `GET /services/appointments/manage`, `POST /services/appointments/manage/{action}`, and the
  storefront `GET /book/{service}`.
- A `BookingFunction` (public handler) with CRUD on `ServicesTable` + read of tenant Stripe keys +
  create Checkout Session; extend the **webhook** function (already has ledger + services access) to
  branch on `appointment_id`.
- Enable **TTL** on `ServicesTable` (`hold_expires_at`).

## Security

- **Double-booking:** conditional-write slot-lock (the availability read is advisory only).
- **Money:** price computed server-side from the service; client-supplied amounts ignored.
- **Manage token:** opaque, single-purpose, expiring; authorizes only that appointment.
- **Holds:** TTL auto-release; expired holds never block new bookings.
- Public endpoints billing-gated + rate-limited; `mode` isolation on every write.

## Testing

- **Slot engine** (exhaustive, pure): DST, lead, buffers, exception scopes, overlap edges, fulfiller
  override, multi-fulfiller, expired holds.
- **Reserve:** slot-lock rejects the second concurrent reserve (409); hold TTL frees the slot.
- **Checkout:** paid → session with `appointment_id`; free → immediate booked; webhook → paid/booked +
  ledger `sale_entry` + notification, idempotent on replay.
- **Manage:** token auth; cancel releases the slot; reschedule moves it atomically.
- **Comp snapshot:** override vs fulfiller default resolved and frozen.

## Build order

1. **Slot engine** + `/availability` (keystone; unlocks everything).
2. **Reserve** + slot-lock + hold TTL.
3. **Checkout** (paid Connect + free) + webhook branch + ledger `sale_entry` + booked notification.
4. **Storefront booking page** (`/book/{service}`).
5. **Manage** (cancel/reschedule) + comp snapshot.

## Dependencies & deferrals

- **Depends on:** Phase A (lifecycle, admin), the ledger (`sale_entry`), `checkout.py` Connect helpers,
  the webhook, notifications, `mode`.
- **Phase C (next):** two-way calendar sync, SMS reminders, payable invoices.
- **Deferred:** deposits/partial payment, group/multi-attendee, recurring appointments, waitlists, and
  the booking page-builder section.
