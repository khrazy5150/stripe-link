# Services Phase C — Calendar sync, SMS reminders & payable invoices

**Status:** design, not yet built · **Parent:** `plans/SERVICES_IMPLEMENTATION.md` (Phase C) ·
**Depends on:** Phase B (booking runtime, shipped to dev) and the ledger (`sale_entry`).

## Goal

Layer the three integrations that make bookings feel finished: the tenant's **calendar** stays in
sync both ways, customers get **SMS reminders**, and a tenant can send a **payable invoice** by email
or text without publishing a page. These sit on top of Phase B's booking lifecycle.

## ⚠️ External prerequisites (you must provision these — they gate testing/deploy)

Unlike A and B, Phase C can't be fully exercised on AWS alone:

1. **Google OAuth app (for C.1 calendar).** A Google Cloud project with an **OAuth 2.0 client**
   (client id + secret) and the **Calendar API** enabled, with our callback registered as an
   authorized redirect URI. The client secret goes in **Secrets Manager**. *Code is buildable without
   it; the OAuth round-trip can't be tested until it exists.*
2. **AWS End User Messaging 10DLC (for C.2 SMS).** A registered **brand + campaign** (US A2P 10DLC),
   an **origination phone number** in a **phone pool**, and a configuration set. **This has multi-day
   lead time and a cost** — start it early. *SMS code is buildable and unit-testable against a fake,
   but real delivery is blocked until the number is live.*

Because of these, the recommended order **front-loads the part that needs no external provisioning**
(payable invoices by email) and lets the Google app + 10DLC registration proceed in parallel.

## Principles

- **Adapter pattern** for calendars (provider-agnostic interface; Google first), same shape as the AI
  provider adapters; OAuth tokens **KMS-encrypted** like `stripe_keys`.
- **AWS-native** SMS via **AWS End User Messaging** (per the PRD infra principle).
- **Reuse:** the SES `mailer.py` (built), Stripe **Invoicing** (Stripe hosts the payable page), the
  webhook + its idempotency table, the ledger `sale_entry`, notifications, and `mode` isolation.
- Pure domain where possible (reminder scheduling math, invoice line-item build); thin handlers/adapters
  do I/O.

---

## C.1 Calendar — two-way, adapter-based, Google first

- **`CalendarConnection`** (new document/secret, per tenant and optionally per fulfiller): `provider`
  (`google` | …), `calendar_id`, OAuth token refs (**KMS-encrypted**), granted scopes, status. OAuth
  connect: `POST /calendar/connect` → provider consent → `GET /calendar/callback` stores tokens.
- **`CalendarProvider` interface** (raw-HTTP client like `stripe_client`): `create_event`,
  `update_event`, `delete_event`, `free_busy(range) → busy[]`. **Google Calendar** adapter first.
- **Push** (write): on book → `create_event`; reschedule → `update_event`; cancel → `delete_event`.
  Store `external_calendar_events[] = {provider, calendar_id, event_id}` on the appointment.
- **Read** (busy): the slot engine (`domain/scheduling.py`) gains an optional "external busy"
  input; the availability handler calls `free_busy` for the tenant's/assigned fulfiller's connected
  calendar and passes those intervals in, so the platform never double-books against events created
  outside it. Query at slot-computation time (cache briefly); no full mirror in v1.

## C.2 SMS reminders — AWS End User Messaging

- **Channel:** `pinpoint-sms-voice-v2` — platform-owned 10DLC number in a phone pool + configuration
  set. A thin `sms.py` sender (like `mailer.py`).
- **Scheduling:** on book, create **EventBridge Scheduler** one-shots per reminder (default lead times
  **24h + 1h**, tenant-configurable); delete/recreate them on cancel/reschedule. (Fallback: a 15-min
  sweep Lambda — simpler infra, coarser timing.)
- **Content/compliance:** E.164 validation at booking, **STOP/opt-out** handling, quiet-hours guard,
  and a `reminders[]` record on the appointment (`{lead_minutes, channel, sent_at}`) for
  idempotency/audit.

## C.3 Payable invoices via email / SMS (invoice-to-pay)

Turn the **passive** Invoice CRUD (`handlers/invoices.py`) into a **send-to-pay** flow. The `Invoice`
schema already anticipates it (`stripe_invoice_id`, `collection_method: send_invoice`,
`line_items[].type: "service"` + `service_id`/`appointment_id`, `customer.phone`).

- **Create from a service:** pick a service → prefill a `service` line item (price + `service_id`);
  ad-hoc items too. Ensure a Stripe **customer** on the connected account.
- **Finalize on Stripe (direct-charge Connect):** create + finalize a **Stripe Invoice** with
  `collection_method: send_invoice` and `application_fee_amount`; capture **`hosted_invoice_url`**.
- **Deliver:** send the hosted link by **email (SES `mailer.py`, default)** or **SMS (the C.2
  channel)**; record `delivery[] = {channel, to, sent_at}`.
- **Status sync (webhook):** `invoice.finalized`/`invoice.paid`/`invoice.payment_failed`/
  `invoice.voided` → update the Invoice doc, emit a notification, and append a `sale` **ledger entry**.
  If linked to an appointment, reflect its `payment_status`.
- **Dashboard:** Invoices screen gains **Create (from service / custom)**, **Send (email | SMS)**, a
  copyable pay link, and live status; Services/Appointments panels get a **"Send invoice"** action.

**Email delivery needs no external provisioning — it is fully buildable and testable now.** Only the
**SMS** delivery option depends on C.2's number.

---

## Data model changes

- **`CalendarConnection`** — new schema + validator + repo (secrets/KMS).
- **Appointment** — add `external_calendar_events[]` and `reminders[]`.
- **Invoice** — add `hosted_invoice_url`, `delivery[]`, optional top-level `service_id`/`appointment_id`.
- **Reminder policy** — small per-tenant config (lead times, quiet hours) on `TenantAvailability` or a
  services-settings doc.

## Infrastructure (`template.yaml`)

- New routes: `POST /calendar/connect`, `GET /calendar/callback`; invoice **finalize/send** routes;
  (SMS send is internal — EventBridge target, not a public route).
- Extend the **webhook** for `invoice.*` events (and, if used, calendar push webhooks).
- **AWS End User Messaging**: phone pool + configuration set + IAM; **EventBridge Scheduler** role;
  **Google OAuth client secret** in Secrets Manager; KMS grants for calendar tokens.

## Security

- Calendar OAuth tokens **KMS-encrypted**, redacted on read (reuse the `stripe_keys` pattern).
- SMS: 10DLC registration, STOP/opt-out, quiet hours, E.164 validation, per-tenant rate limits.
- Invoice/calendar public callbacks validated; `mode` isolation on every write; least-privilege IAM.

## Testing

- Calendar: Google adapter `create/update/delete/free_busy` against a fake; slot engine subtracts
  external busy; lifecycle push (book/reschedule/cancel) writes the right event ops.
- SMS: sender against a fake End User Messaging client; reminder scheduling (create on book, cancel on
  cancel); opt-out suppression; quiet-hours guard; idempotent send.
- Invoices: create-from-service prefill, finalize (application fee), deliver email/SMS, `invoice.paid`
  webhook → status + notification + `sale` ledger entry (idempotent).

## Build order (sequenced around the external blockers)

1. **C.3 email invoices — start here.** No external provisioning; reuses SES + Stripe Invoicing +
   webhook + ledger. Fully deliverable and testable now. *(Meanwhile: you register the Google OAuth
   app and kick off 10DLC — the long pole.)*
2. **C.1 calendar** — once the Google OAuth app exists: connection + adapter + push + free-busy.
3. **C.2 SMS** — once the 10DLC number is live: sender + scheduling + compliance.
4. **C.3 SMS delivery** — flip on the SMS channel for invoice sending (small add on top of C.2).

## Deferred (Phase C+ / later)

Non-Google calendar providers (Outlook/iCloud) beyond the adapter seam; deposits/partial invoices;
recurring reminders; per-fulfiller calendar as the default; abandoned-cart-style nudges.
