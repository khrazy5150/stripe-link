# Multi-Calendar Architecture

Status: **proposed** (design only — no code yet). Author-approved decisions baked in:
dedicated table, **service-default + fulfiller-override** routing, provider-agnostic.

---

## 1. Why

Today a tenant can connect exactly **one** calendar. A tenant is often an umbrella over
several related businesses, each with its **own calendar and its own manager**. The owner
(tenant) delegates: bookings for *this* page go to *that* business's calendar, run by *that*
manager. We want:

1. A tenant to connect **many** calendars.
2. **Provider-agnostic** connections — Google today; **Outlook 365 / Exchange (Microsoft
   Graph)** later — with no churn to the booking engine when a provider is added.
3. Routing: **which calendar a booking touches** is chosen per service/page, with a
   per-fulfiller override (a delegated manager's own calendar wins for their appointments).
4. **Delegation must actually delegate (hard requirement).** When a tenant delegates a service
   to a staff person, that person's booking event is written **automatically to their own
   connected calendar** — no manual step. The delegate must have a *supported* calendar
   connected (Google today) for this to work; §5.1 defines the precondition and the fallback.
5. **The delegate is notified (hard requirement).** On each booking assigned to a delegate, an
   **email** is sent to that delegate with the service + appointment details (SMS later, reusing
   the C.2 channel). See §5.2.
6. No hardcoded `connection_id` (the current `"google"` constant is the thing to kill).

---

## 2. Current state (what we're changing)

- **Storage:** `jb-calendar-connections-{env}` table via `calendar_connections_repository()`
  (`DynamoDocumentRepository`, PK `TENANT#{id}` / SK `CALENDAR_CONNECTION#{connection_id}`,
  GSI1 for `find_by_id`). Already the right home — we just stop pinning the id.
- **Hardcoded id:** `CONNECTION_ID = "google"` in `stripe_link/calendar_sync.py`, used by
  `handlers/calendar.py` (connect/callback/status/disconnect) and by `resolve_tenant_calendar`
  / `sync_appointment_event` / `tenant_busy_intervals`. One connection per tenant, full stop.
- **Google-specific sync:** `calendar_sync.py` → `google_calendar.GoogleCalendarClient`
  (`create_event`/`update_event`/`delete_event`/`free_busy`/`calendar_list`) + pure
  `domain/calendar.py` (`google_event_body`, `busy_intervals`). No provider seam.
- **Appointment link:** `appointment.external_calendar_events[]` already an array of
  `{provider, calendar_id, event_id}` — matched in sync by `provider == "google"`.
- **Availability wiring:** `handlers/booking.py` `availability_route` calls
  `tenant_busy_intervals(...)` once and passes a single `external_busy` list into
  `domain/scheduling.available_slots(...)`, which applies it to **every** candidate fulfiller
  (`scheduling.py` ~L176). **Bug for multi-staff tenants:** one shared calendar's busy time
  blocks all fulfillers. The routing work below fixes this.

---

## 3. Target data model

### 3.1 `CalendarConnection` (schema changes)

Keep the dedicated table; make the document self-describing and multi-capable.

| Field | Change | Notes |
|---|---|---|
| `connection_id` | **generated** `cal_<uuid12>` | de-hardcode; unique per connection |
| `provider` | enum → `["google","microsoft","exchange"]` | Google now; others later |
| `display_name` | **new**, required | tenant-facing label, e.g. "Downtown Salon — Jane" |
| `is_default` | **new**, boolean | exactly one default per tenant (tenant-wide fallback) |
| `account_email` | keep | the connected account |
| `calendar_id` | keep | a specific calendar *within* the account (default `primary`) |
| `owner_fulfiller_id` | **new**, optional | if this connection *is* a fulfiller's own calendar |
| `refresh_token_ref` / `token_ref` | keep (KMS) | per-provider token material, KMS-encrypted |
| `provider_meta` | **new**, optional object | provider-specific (e.g. Graph tenant id) |
| `status` | keep | `connected` / `revoked` / `error` |

- **Legacy back-compat:** `"google"` is a perfectly valid `connection_id` string. We do **not**
  rewrite existing docs' ids. A one-line backfill sets `is_default=true` + a `display_name`
  ("Primary calendar") on each existing connection; new connections get generated ids.
- **Uniqueness of default:** enforced in the handler (setting a new default clears the old);
  no schema constraint needed.

### 3.2 Routing fields (service default + fulfiller override)

- **`Service.calendar_connection_id`** (optional): the calendar this service's bookings write
  to and check busy against. Absent → tenant **default** connection.
- **`Fulfiller.calendar_connection_id`** (optional): that staff member's own calendar. When an
  appointment is assigned to this fulfiller, this **overrides** the service calendar for both
  the event write and that fulfiller's busy check.

> v1 keeps each of these to a **single** connection. Multi-source *busy aggregation* (a service
> that writes to one calendar but blocks against several — e.g. manager + shared room) is a
> Phase 4 refinement: promote to `busy_connection_ids[]` without breaking the single-id field.

### 3.3 `Appointment.external_calendar_events[]` (schema change)

Add **`connection_id`** to each entry: `{provider, connection_id, calendar_id, event_id}`.
Sync matches by `connection_id` (not `provider`), so multiple same-provider calendars are
unambiguous. Still an array → an appointment can hold events in more than one calendar.

Also add **`delegation_calendar`** (optional): `"written"` when the event landed on the assigned
delegate's own calendar, `"unavailable"` when the delegate had no usable calendar and routing fell
back (§5.1). Drives the delegate email's calendar-added-or-not line and surfaces delegation health
in the admin.

---

## 4. Provider abstraction (the Outlook/Exchange seam)

Introduce a thin interface so booking code never names a provider:

```
class CalendarClient(Protocol):
    calendar_id: str
    def create_event(self, body) -> dict
    def update_event(self, event_id, body) -> dict
    def delete_event(self, event_id) -> bool
    def free_busy(self, time_min, time_max) -> list[{start,end}]   # normalized
```

- `stripe_link/calendar_providers/__init__.py` → `client_for_connection(connection, *, secret_cipher, opener) -> CalendarClient | None`
  (a factory keyed on `connection["provider"]`).
- Google: wrap existing `GoogleCalendarClient` + `google_event_body` + `busy_intervals` behind
  the interface (event-body/free-busy shaping moves into the Google provider module).
- Microsoft (Phase 3): `MicrosoftCalendarClient` over Graph (`/me/events`,
  `/me/calendar/getSchedule`), OAuth via Microsoft identity platform; platform app creds in
  Secrets Manager (`jb/microsoft-oauth/{env}`), per-tenant refresh token KMS-encrypted — same
  shape as Google. Outlook 365 and Exchange Online are both Graph, so one client covers both.
- `calendar_sync.py` becomes provider-agnostic: resolve a **connection** (by id), build a
  client via the factory, and run the same upsert/delete/free-busy logic. `free_busy` returns
  an already-normalized `[{start,end}]` so the slot engine is unchanged.

---

## 5. Routing resolution (pure, testable)

New `domain/calendar_routing.py`:

- **Write target for an appointment** `resolve_write_connection(appointment, service, fulfiller, connections) -> connection|None`:
  1. assigned fulfiller's `calendar_connection_id`, else
  2. service's `calendar_connection_id`, else
  3. tenant **default** connection, else
  4. `None` (no sync).
- **Busy sources for availability** `resolve_busy_sources(service, fulfillers_in_scope, connections) -> {fulfiller_id|None: [connection]}`:
  - the **service/default** connection → keyed `None` (global: blocks the whole service), and
  - each in-scope fulfiller's own connection → keyed by `fulfiller_id` (blocks only them).

`available_slots(...)` gains an `external_busy_by_fulfiller: {fid|None: [intervals]}` (replacing
the flat `external_busy`; `None` = applies to all). This is the fix for the "one calendar blocks
everyone" bug and is what makes per-fulfiller delegation correct.

### 5.1 Delegation: automatic write to the delegate's calendar (hard requirement)

When a service is delegated to a staff person (the appointment's `assigned_fulfiller_id` resolves
to a fulfiller with a `calendar_connection_id`), the booking event **must be written
automatically to that fulfiller's own connected calendar** — the fulfiller override in
`resolve_write_connection` (step 1) is what guarantees this, on every booking path (free confirm,
paid webhook, reschedule → move the event; cancel → delete it).

- **Precondition — the delegate needs a *supported, connected* calendar.** A fulfiller can only
  be "fully delegated to" if they have a `calendar_connection_id` pointing at a `connected`
  connection whose `provider` is supported (Google today). The dashboard enforces this at
  **setup time**: assigning a fulfiller as a service's delegate surfaces a clear warning (and a
  "connect calendar" prompt) if that fulfiller has no connected supported calendar, so the tenant
  sets it up before real bookings arrive. Each fulfiller connects via the same OAuth flow; the
  resulting connection is stamped with `owner_fulfiller_id`.
- **Runtime fallback (never drop a booking).** If, at booking time, the assigned fulfiller has no
  usable connection (never connected, revoked, or an error state), routing falls back to the
  service calendar, then the tenant default (§5 steps 2–3). The booking still succeeds; the
  appointment records that the delegate write was skipped (`delegation_calendar: "unavailable"`)
  and the delegate email (§5.2) says the event **could not** be added to their calendar and asks
  them to connect it. Calendar sync is best-effort by design — a missing delegate calendar must
  degrade, not fail the booking.
- **Correct busy-checking follows automatically.** Because a delegated fulfiller's own calendar
  is keyed by their `fulfiller_id` in `resolve_busy_sources`, their external commitments block
  only *their* slots — so a customer can only book a delegate when that delegate is actually free.

### 5.2 Delegate notification (hard requirement)

On every booking assigned to a delegate, email that delegate the service + appointment details.

- **Channel:** email now (SES `mailer.py`), SMS later (reuse the C.2 sender + opt-out; gated on
  the fulfiller having a phone + consent). Content built by a pure
  `domain/notifications_content.py::delegate_booking_email(appointment, service, fulfiller)` —
  service name, date/time + timezone, customer name, location/notes, and a manage link;
  plus a line stating whether the event was added to their calendar (ties to the §5.1 fallback).
- **Recipient:** `Fulfiller.email` (required field). Sent best-effort from the same place the
  booked notification is emitted today — `handlers/booking.py` free-confirm and
  `stripe_webhook.persist_appointment_paid` (paid) — and on reschedule/cancel (update/cancelled
  variants), so the delegate always knows the current state. A delivery failure never blocks the
  booking (same pattern as receipts).
- **Idempotency:** keyed off the appointment + state transition so webhook redelivery / retries
  don't double-send (mirrors the existing webhook idempotency).
- **Distinct from the tenant's bell notification.** The existing in-app "New booking" notification
  is tenant-facing; this is a separate, delegate-facing email to the assigned staff person.

---

## 6. API / handler changes

- **`handlers/calendar.py`**
  - `POST /calendar/connect` → still starts OAuth, now provider-parameterized (`?provider=google`).
  - `GET /calendar/callback` → creates a **new** connection with a generated id + `display_name`
    (first connection auto-`is_default`).
  - `GET /calendar/connections` → **list** (replaces single `/calendar/connection` status).
  - `PATCH /calendar/connections/{id}` → set `display_name`, `calendar_id` (within-account
    picker via `calendar_list()`), or `is_default`.
  - `DELETE /calendar/connections/{id}` → disconnect one; block/relink if it's referenced by a
    service/fulfiller (warn, reassign, or clear the reference).
- **`handlers/services.py`** — accept/persist `Service.calendar_connection_id`.
- **Fulfiller admin** — accept/persist `Fulfiller.calendar_connection_id`; return whether the
  fulfiller has a connected supported calendar so the dashboard can warn on delegation (§5.1).
- **`handlers/booking.py`** — `availability_route` computes per-fulfiller busy via the routing
  helper; `_sync_calendar` / webhook `persist_appointment_paid` resolve the **write connection**
  per appointment (fulfiller override → service → default) instead of the single tenant calendar,
  and **emit the delegate email** (§5.2) on confirm/paid/reschedule/cancel, best-effort.

---

## 7. Dashboard

- **Calendar settings** → a **list** of connected calendars: connect (provider picker), label,
  choose which calendar within the account, mark default, disconnect individually; shows each
  connection's status + owning fulfiller.
- **Service editor** → "Calendar" picker (default / specific connection).
- **Fulfiller editor** → "Uses their own calendar" — connect/pick a calendar for this staff
  person (stamps `owner_fulfiller_id`); shows connected/not-connected status.
- **Service delegation** → when a fulfiller is set as a service's delegate/default and has **no**
  connected supported calendar, show an inline warning + "connect calendar" prompt (§5.1).

---

## 8. Migration & backward compatibility

1. **Zero-downtime read:** new code resolves connections by id and lists them; the existing
   `"google"` doc is read as-is.
2. **Backfill** (one-shot, idempotent): for each existing connection, set `is_default=true`
   (first/only one) + a `display_name`. No id rewrite.
3. **Behavior preserved through Phase 1:** with no service/fulfiller routing set yet, everything
   resolves to the default connection — identical to today.
4. `external_calendar_events[]` entries without `connection_id` are treated as belonging to the
   default connection (or matched by `provider`) until re-synced.

---

## 9. Security

- Per-connection refresh tokens **KMS-encrypted** (`KmsSecretCipher`, existing `calendar`
  mode/field pattern), redacted on read. Platform provider app creds in **Secrets Manager**
  (`jb/google-oauth/{env}`, later `jb/microsoft-oauth/{env}`) — never in the connection doc.
- `mode`/tenant isolation on every write; `DELETE` guarded so one tenant can't touch another's
  connection; least-privilege IAM (calendar functions get only their secret paths + KMS).

---

## 10. Testing

- Pure: `calendar_routing` resolution (fulfiller override > service > default > none); busy-source
  mapping; `available_slots` with `external_busy_by_fulfiller` (per-fulfiller vs global).
- **Delegation (hard req):** an appointment assigned to a fulfiller-with-calendar writes to
  **their** connection (not the service/tenant one); a delegate with no/revoked calendar falls
  back per §5.1, still books, and stamps `delegation_calendar: "unavailable"`.
- **Delegate email (hard req):** `delegate_booking_email` content includes service/time/customer
  + the calendar-added-or-not line; sent to `Fulfiller.email` on confirm/paid; idempotent under
  webhook redelivery; not sent when no fulfiller is assigned.
- Provider factory: selects Google; unknown provider → `None` (no crash). Google client behind
  the interface unchanged (reuse existing calendar tests).
- Handlers: connect creates generated-id connection + auto-default; list/patch/delete; set-default
  clears prior default; disconnect referenced connection is guarded.
- Migration backfill idempotency.

---

## 11. Phasing

- **Phase 1 — Foundation (Google, no routing yet).** De-hardcode `connection_id`; provider
  factory (Google only); connection list / set-default / per-connection disconnect; schema +
  migration backfill; dashboard connection list. Behavior preserved (all → default).
- **Phase 2 — Routing + delegation (service default + fulfiller override).** `Service`/`Fulfiller`
  calendar fields; `calendar_routing`; per-fulfiller busy in `available_slots` (**fixes the
  all-fulfiller busy bug**); **automatic write to the delegate's calendar** with the §5.1
  precondition/fallback; **delegate email notification** (§5.2, SES now); write-target resolution
  in booking + webhook; dashboard pickers + the "connect calendar" delegation warning. *(These are
  the two hard requirements — they land together in this phase.)*
- **Phase 3 — Microsoft Graph provider (Outlook 365 / Exchange).** `MicrosoftCalendarClient`,
  OAuth + `jb/microsoft-oauth/{env}` secret, provider selection in connect flow.
- **Phase 4 — Refinements.** Busy aggregation (`busy_connection_ids[]`); external-change push
  notifications/webhooks; richer within-account calendar management.

---

## 12. Open questions (resolve before/within each phase)

- **Delete semantics** when a connection is referenced by a service/fulfiller: block, reassign
  to default, or clear the reference + warn? (Lean: warn + clear reference, keep bookings.)
- **Unassigned-pool busy:** should the service/default calendar's busy block only unassigned
  fulfillers, or the whole service? (v1: whole service — simplest and matches "one shared
  business calendar." Revisit with aggregation.)
- **Within-account multiple calendars:** treat "same account, different `calendar_id`" as two
  connections (simplest) vs. one connection with a calendar list. (Lean: two connections.)
- **Microsoft consent/verification** lead time mirrors Google's (app registration + admin
  consent for delegated calendar scopes) — start early when Phase 3 approaches.
