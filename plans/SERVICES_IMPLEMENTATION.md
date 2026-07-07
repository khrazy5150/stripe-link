# Services & Appointments — Implementation Plan

**Status:** design, not yet built · **Behavioral reference:** stripe-cart `src/services.py` (1,543 lines)
· **Architectural spec:** stripe-link (JSON-first).

## Purpose (what this feature is)

A tenant sells **bookable services** (a massage, a consultation, a mobile detailing job) instead of —
or alongside — physical/digital products. The Services screen configures the whole booking operation:

- **Services** — the catalog of bookable services: duration, price, location mode, check-in/completion
  rules, and which fulfillers may perform each one.
- **Fulfillers** — the staff/providers who deliver appointments, each with compensation (flat/percent/
  hourly + tips) and personal weekly hours that override tenant defaults when assigned.
- **Tenant Availability** — the default bookable hours (weekly schedule) plus timezone, slot interval,
  lead time, and buffers.
- **Availability Exceptions** — one-off blocks (vacations/holidays), scoped to all fulfillers or one.
- **Appointments** — the booked calendar and each appointment's lifecycle: reserve → (pay) → booked →
  checked-in → completed / canceled / no-show.

A customer books from a public surface: pick a service → see open slots (computed from availability −
exceptions − existing bookings − external-calendar busy) → reserve → pay (or free) → get a confirmation
+ SMS reminder, with a self-serve link to cancel/reschedule.

## Current state

**Already migrated (backend CRUD only):** all five documents — `Service`, `Fulfiller`,
`TenantAvailability`, `AvailabilityException`, `Appointment` — with schemas, validators, and
`/services/*` routes. All five share one **`ServicesTable`** (single-table, `document_type`-prefixed
SKs). The dashboard has only the **catalog CRUD** built (`Services.vue` — name/desc/price/duration/
location/hero/active).

**Missing — everything else:**
- Handler has **no DELETE**, no appointment **lifecycle** actions, no **slot engine**, no **booking**
  (reserve/checkout), no **public resolve/manage**.
- Dashboard: Fulfillers, Tenant Availability, Exceptions, Appointments viewer, and the *extended*
  Service form (linked product, check-in/completion, allowed fulfillers) are all unbuilt.
- New asks: **two-way calendar sync** and **SMS reminders** (no legacy code — greenfield).

## Principles

- JSON-first documents + validators + document repositories + thin handlers; pure domain logic for the
  slot engine and lifecycle transitions (no I/O in the math).
- `mode` (test/live) threads through every write and every booking, like the rest of stripe-link.
- **Direct-charge Connect** for paid bookings — Checkout Session on the tenant's connected account with
  the platform application fee, exactly like product checkout. **Free/lead-gen** services book with no
  payment step.
- **Adapter pattern** for calendars (provider-agnostic interface; Google first) — same shape as the AI
  provider adapters; tokens KMS-encrypted like `stripe_keys`.
- **AWS-native** SMS via **AWS End User Messaging** (per the PRD infra principle).
- Reuse before create: the existing `ServicesTable` + repos, the weekly-hours widget (shared by
  fulfiller + tenant availability), the notification bell, the shared image uploader, checkout
  credentials, and the webhook idempotency table.

---

## Phase A — Admin dashboard screens (first deliverable)

Make the full management UI real over the existing CRUD backend, plus the small backend gaps the admin
screens need. Ships tenant-visible value with no runtime/payments risk.

### A.1 Backend gaps (small)
- **Add DELETE** to `document_route` (fulfillers, exceptions, and services) — legacy supported it; the
  current handler only does GET/POST/PUT. Delete is tenant-scoped, keyed by id.
- **Appointment lifecycle endpoints** — `POST /services/appointments/{id}/{action}` for
  `assign` / `check-in` / `complete` / `cancel` / `no-show`. Each is a **pure domain transition**
  (`transition_appointment(appt, action, ...)`) that validates the state machine
  (`reserved→booked→checked_in→completed`, plus `canceled`/`no_show`) and stamps
  `checked_in_at`/`completed_at`/`canceled_at`, then a thin handler persists it. (Booking/reserve is
  Phase B; these operate on appointments that already exist.)

### A.2 Screen structure
Restructure `Services.vue` into a **sectioned screen** matching the legacy layout: **Service Booking**
(create/list services), **Fulfillers**, **Tenant Availability**, **Availability Exceptions**,
**Appointments**. Each section is its own component + Pinia store; a shared **`WeeklyHours.vue`** widget
(7-day toggle + start/end) is reused by Fulfiller personal availability and Tenant Availability.

### A.3 Panels
- **Service form (extend the existing catalog form):** add **Linked Product / Linked Price**
  selectors (reuse products store; sets `linked_product`), **check-in/completion** labels + windows +
  `required` toggles (→ `booking_rules`), and an **Allowed Fulfillers** editor (add fulfiller + override
  type/amount + tips + enabled → `allowed_fulfillers[]`, with `default_fulfiller_id`). The schema
  already supports all of this — no schema change, just UI + document wiring (keep the merge-on-edit
  behavior so unrendered fields survive).
- **Fulfillers:** CRUD over `/services/fulfillers` — first/last/display name, email, phone, status,
  compensation (type + amount + tips), and **personal weekly hours** (`WeeklyHours`). Delete via A.1.
- **Tenant Availability:** GET/PUT `/services/availability/defaults` — timezone, slot interval, lead
  time, buffers, weekly hours; **Save Defaults**. (Schema has `buffer_before_minutes` and
  `buffer_after_minutes`; the legacy UI exposes "Buffer After" — expose both.)
- **Availability Exceptions:** CRUD over `/services/availability/exceptions` — start/end, type
  (block/open), reason, fulfiller scope (all/specific). List + delete.
- **Appointments viewer:** month/week calendar + selected-day list + a table, reading
  `/services/appointments`. Lifecycle actions (assign/check-in/complete/cancel) call A.1. Read-heavy in
  Phase A (no new bookings appear until Phase B), but fully wired.

### A.4 Acceptance
Every panel round-trips its document; the Service form persists linked product + booking rules +
allowed fulfillers without dropping fields; fulfiller/exception delete works; an existing appointment
can be advanced through its lifecycle from the calendar.

---

## Phase B — Booking runtime (slot engine, public booking, payments)

### B.1 Slot-availability engine (pure domain)
Port `_local_day_slots` into `domain/scheduling.py` — a pure function
`available_slots(service, tenant_availability, fulfillers, exceptions, appointments, now, range, tz)`
that generates candidate slots from the effective weekly hours (tenant default, overridden by the
assigned/eligible fulfiller), stepped by `slot_interval`, then removes: slots inside `lead_time`, slots
overlapping an **exception**, slots overlapping an existing **appointment** (respecting
`buffer_before/after` and service `duration`), computed in the tenant **timezone**. Deterministic and
unit-testable with no I/O. Exposed as `GET /services/{service_id}/availability?from&to&fulfiller_id`.

### B.2 Public booking flow
- `GET /services/resolve` — public service resolution for the booking widget (service + open slots +
  presentation), gated by the billing paywall like other public endpoints.
- `POST /services/appointments/reserve` — create a `reserved` appointment that **holds** the slot with a
  short TTL (`hold_expires_at`). Prevent double-booking with a **conditional write / slot lock** re-checking
  overlap atomically at reserve time (the engine read is advisory; the write is the source of truth).
- `POST /services/appointments/checkout` — **paid** service → Stripe **Checkout Session on the connected
  account** + application fee (reuse checkout credentials), `metadata.appointment_id`; returns the URL.
  **Free** service → confirm immediately (`status: booked`, `payment_status: unpaid`/n-a), skipping Stripe.
- **Webhook** (`checkout.session.completed` with an `appointment_id`) → mark `paid`/`booked` (idempotent
  via the existing webhook-events table), emit a notification, and (Phase C) create the calendar event +
  schedule the SMS reminder. Expired holds are swept back to available.
- **Customer self-serve:** `GET /services/appointments/manage` (opaque, expiring **manage token**),
  `POST …/manage/cancel`, `POST …/manage/reschedule`.

### B.3 Storefront surface
v1: a **hosted booking page per service** (same pattern as hosted checkout) — a `/book/{service}` route
rendered server-side. A composable **booking section** for the page builder (so a landing page can embed
booking) is a follow-up, aligned with the Phase 1 composition system.

### B.4 Notifications
Wire appointment emitters (booked / canceled / reminder) into the existing notification bell — this is
the concrete first emitter beyond checkout (see `docs/NOTIFICATION_EMITTERS.md`).

---

## Phase C — Calendar sync (two-way), SMS reminders & payable invoices

### C.1 Calendar — two-way, adapter-based, Google first
- **`CalendarConnection`** (new document/secret, per tenant and optionally per fulfiller): `provider`
  (`google` | …), `calendar_id`, OAuth token refs (**KMS-encrypted**, reuse `KmsSecretCipher`),
  granted scopes, status. OAuth connect flow: `POST /calendar/connect` → provider consent →
  callback stores tokens.
- **`CalendarProvider` adapter interface** (like the AI provider adapters; raw-HTTP client like
  `stripe_client`): `create_event`, `update_event`, `delete_event`, and `free_busy(range) → busy[]`.
  **Google Calendar** adapter first; others plug in later.
- **Push** (write): on book → `create_event`; on reschedule → `update_event`; on cancel → `delete_event`.
  Store the external ids on the appointment (`external_calendar_events[] = {provider, calendar_id,
  event_id}`).
- **Read** (busy): the slot engine (B.1) calls `free_busy` for the tenant's/assigned fulfiller's
  connected calendar and subtracts external busy intervals, so the platform never double-books against
  events created outside it. Freebusy is queried at slot-computation time (cache briefly); no full
  mirror needed for v1.

### C.2 SMS reminders — AWS End User Messaging
- **Channel:** AWS End User Messaging SMS (`pinpoint-sms-voice-v2`) — a platform-owned **10DLC** origination
  number in a phone pool + configuration set. (One-time A2P 10DLC registration is a prerequisite.)
- **Scheduling:** on book, create an **EventBridge Scheduler** one-shot per reminder (default lead times
  **24h + 1h**, tenant-configurable); delete/reschedule the schedule when the appointment is canceled or
  moved. (Alternative: a 15-min sweep Lambda querying upcoming appointments — simpler infra, coarser
  timing; Scheduler preferred.)
- **Content/compliance:** E.164 validation at booking, **STOP/opt-out** handling, quiet-hours guard, and
  a `reminders[]` record on the appointment (`{lead_minutes, channel, sent_at}`) for idempotency/audit.

### C.3 Payable invoices via email / SMS (invoice-to-pay)
Turn the existing **passive** Invoice document (today just CRUD in `handlers/invoices.py`) into a
**send-to-pay** flow, so a tenant (e.g., a tax preparer) can bill a customer for a service's preset
price — say $150 for tax prep before filing — **without publishing a landing page**. The `Invoice`
schema already anticipates this (`stripe_invoice_id`, `collection_method: send_invoice`,
`line_items[].type: "service"` + `service_id`/`appointment_id`, `customer.phone`), so this is mostly
behavior, not schema.

- **Create from a service:** pick a service → prefill a `service` line item (its price + `service_id`);
  ad-hoc/custom line items also supported. Ensure a Stripe **customer** on the connected account
  (port `_create_stripe_customer`).
- **Finalize on Stripe (direct-charge Connect):** create + finalize a **Stripe Invoice** on the
  tenant's connected account with `collection_method: send_invoice` and `application_fee_amount` (the
  platform fee — same model as checkout); capture the **`hosted_invoice_url`**. Stripe hosts the
  payable page, payment methods, PDF, and dunning — we do **not** rebuild a checkout page.
- **Deliver via our channels:** send the hosted link by **email (SES mailer, default)** or **SMS (the
  Phase C End User Messaging channel)**, with templates; record `delivery[] = {channel, to, sent_at}`.
  (Email-only could ship before Phase C since SES exists; **SMS delivery is why this belongs in C**.)
- **Status sync (webhook):** `invoice.finalized` / `invoice.paid` / `invoice.payment_failed` /
  `invoice.voided` → update the Invoice doc status, emit a notification, and append a `sale` **ledger
  entry** (per `plans/TRANSACTION_LEDGER_STRIPE_LINK.md`). If linked to an appointment, reflect its
  `payment_status`.
- **Dashboard:** the Invoices screen gains **Create (from service / custom)**, **Send (email | SMS)**, a
  copyable pay link, and live status; the Services/Appointments panels get a **"Send invoice"** action
  for a customer.

Reuses the SES mailer, the C.2 SMS channel (incl. opt-out/quiet-hours), webhook idempotency, and the
transaction ledger. Small schema additions only: `hosted_invoice_url`, `delivery[]`, and optional
top-level `service_id`/`appointment_id` provenance.

---

## Data model changes

- **No new table for the five core types** — they stay in `ServicesTable`.
- **Appointment** — add `hold_expires_at` (reserve TTL), `external_calendar_events[]`, `reminders[]`.
  (`manage_token_ref`, `payment_status`, lifecycle timestamps already exist.)
- **New `CalendarConnection`** schema + validator + repo (secrets/KMS).
- **TenantAvailability** — surface `buffer_before_minutes` (schema already has it).
- **Reminder policy** — small per-tenant config (lead times, quiet hours) on `TenantAvailability` or a
  services settings doc.
- **Invoice** (C.3) — add `hosted_invoice_url`, `delivery[]` (`{channel, to, sent_at}`), and optional
  top-level `service_id`/`appointment_id` provenance. No new table (existing invoices table); the rest
  of the schema (Stripe invoice id, `collection_method`, service line items) is already in place.

## Infrastructure (`template.yaml`)

- New functions/routes: appointment lifecycle, slot availability, public resolve/reserve/checkout/manage,
  calendar OAuth + sync, SMS send/opt-out, invoice finalize + send (C.3).
- Extend the **webhook** function to route appointment checkout sessions (branch on `appointment_id`
  metadata) **and Stripe `invoice.*` events** (finalized/paid/payment_failed/voided).
- **AWS End User Messaging**: phone pool + configuration set + IAM; **EventBridge Scheduler** role;
  Google OAuth client secret in **Secrets Manager**; KMS grants for calendar tokens.
- No changes to the five-type table topology.

## Security

- Calendar OAuth tokens **KMS-encrypted**, redacted on read (reuse the `stripe_keys`/AI-key pattern).
- **Manage token**: opaque, single-purpose, expiring; never exposes tenant/admin scope.
- **Double-booking**: conditional-write slot lock at reserve; the engine read is advisory only.
- **SMS**: 10DLC registration, STOP/opt-out, quiet hours, E.164 validation, per-tenant rate limits.
- PII minimization for customer phone/email; `mode` isolation on every booking write.

## Testing

- Pure-domain: slot engine (weekly hours × interval × lead × buffers × exceptions × existing appts × TZ
  edge cases incl. DST), lifecycle state machine (legal/illegal transitions), reserve overlap/hold TTL.
- Integration: paid booking (reserve → checkout → webhook → booked + calendar event + reminder
  scheduled), free booking (no Stripe), cancel/reschedule (calendar delete/update + reminder cancel),
  webhook idempotency, opt-out suppression.
- Adapters: Google create/update/delete/free_busy against a fake; SMS send against a fake End User
  Messaging client.
- Invoicing (C.3): create-from-service prefill, finalize on Stripe (application fee), deliver via
  email/SMS, and `invoice.paid` webhook → status update + notification + `sale` ledger entry (idempotent).

## Sequencing & dependencies

**A → B → C.** Phase A ships immediately (admin over existing CRUD + small backend gaps). Phase B adds
the runtime (slot engine is the keystone; payments reuse Connect checkout). Phase C layers the two
integrations. Calendar/SMS both depend on B's booking lifecycle existing first. Independent of the AI
phases; the booking **page section** (B.3 follow-up) aligns with the Phase 1 composition system.

## Open questions / deferred

- Per-fulfiller vs per-tenant calendar connection as the v1 default (plan supports both; recommend
  tenant-level first, fulfiller-level as the override).
- Reschedule re-payment policy (free move vs price delta) — recommend free move within the same service
  for v1.
- Group/multi-attendee bookings, recurring appointments, waitlists — deferred.
- Booking as a page-builder **section** (vs hosted page only) — follow-up with the composition system.
