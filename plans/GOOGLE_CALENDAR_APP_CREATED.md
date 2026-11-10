# Bookings get their own calendar (app-created)

Planned 2026-11-08. **BUILT and SHIPPED dev + PROD 2026-11-09** (commit `c21c0a3`). Supersedes the `calendar.events.owned`
arrangement shipped the same day, and lands **before** the verification submission — otherwise Data
Access, the justifications and the demo video are all redone.

Deployed and verified: the prod artifact was downloaded and grepped, and `DEFAULT_SCOPES` in it contains
exactly `calendar.app.created` + `calendar.calendarlist.readonly` + `calendar.freebusy` — every remaining
mention of `calendar.events.owned` is prose. Both legal pages are live on juniorbay.com carrying the new
text and the November 8, 2026 revision date. The prod changeset was audited before executing: 96 changes,
all `Modify`, **no replacements**, 80 Lambda `Code` updates plus derived re-evaluation of the API body,
event rules and one IAM role whose policy text was diffed and is byte-identical.

Still to do: reconnect the author's test tenant (re-consent is forced, and that connect is what creates
the calendar), stand up a bookable service, then brand verification. The prod console's Data Access
scopes were updated and verified against the code on 2026-11-08, and **no demo video or scope review is
needed** — see the verification plan.

## Why

Today bookings are written to the primary calendar of the connected Google account, which requires
`calendar.events.owned` — *"See, create, change, and delete events on Google calendars you own."* That is
the broadest thing we ask for, the line a cautious merchant balks at, and the one a reviewer scrutinises
hardest. Our defence is a promise: *we only touch events we created.*

If every booking lives in a calendar **the app itself created**, that promise becomes a property of the
API rather than a claim to be trusted. `calendar.app.created` cannot reach a calendar the app did not
create, so the merchant's existing events are unreachable by construction.

It also removes a decision the merchant should never have to make — which calendar, and what to call it.

## The scopes

| Scope | Why |
|---|---|
| `calendar.app.created` | create the bookings calendar, and create/update/delete the booking events on it |
| `calendar.freebusy` | availability across the merchant's **real** calendars, so we do not offer a slot they are busy for |
| `calendar.calendarlist.readonly` | **which** calendars count toward that availability check, and the account email we display |

Verified against the method reference, not assumed:

- `calendars.insert` accepts `calendar`, **`calendar.app.created`**, `calendar.calendars`
- `events.insert` accepts `calendar`, `calendar.events`, **`calendar.app.created`**, `calendar.events.owned`

**`calendar.events.owned` is dropped.** Nothing writes to a calendar we did not create.

**`calendarlist.readonly` is NOT optional**, and must not be described that way in the justification. With
bookings in their own calendar, a free/busy query against that calendar alone would see only our own
appointments and none of the merchant's real commitments — the opposite of the point. The list is how we
learn which calendars to include.

## What changes in the code

### 1. Find-or-create, keyed on the stored id

On connect, resolve the bookings calendar in this order:

1. `connection.bookings_calendar_id` — if present, use it
2. otherwise create one (`calendars.insert`, summary **"Junior Bay Bookings"**) and store the returned id

**Keyed on the id, never the name.** A merchant who renames it to "Appointments" would otherwise get a
second calendar created on the next connect, and then bookings split across two.

The summary is human-readable because it appears in their calendar list. `junior-bay-booking` is a slug
leaking into a user-facing surface.

### 2. Two 404s that must be told apart

Every 404 currently collapses into a generic `GoogleCalendarError` (`google_calendar._request`). This
design needs both distinguished, and neither is an error the merchant should see:

| Situation | Meaning | Response |
|---|---|---|
| 404 on the **calendar** | the merchant deleted it outside the software | create a fresh one, store the new id, continue. Nothing to clean up — it is already gone |
| 404 on an **event** | it is already absent | for a cancellation this is **success**; the goal was for it not to exist |

The second matters more than it looks: appointments booked before a calendar deletion hold `event_id`s in
a calendar that no longer exists. Cancelling one later must not report failure for having achieved exactly
what was asked.

### 3. Availability queries the right calendars

`GoogleCalendarClient.free_busy` queries `self.calendar_id`, which under this design becomes the bookings
calendar — the wrong one. It must query:

- the merchant's **real** calendars (from `calendarList.list`), so their own commitments block slots, and
- the **bookings** calendar, so two customers cannot take the same slot

`freebusy.query` accepts multiple ids in one call, so this is one request, not several.

### 4. Storage

`bookings_calendar_id` on the calendar connection document. `calendar_id` stays as it is for connections
made before this change (see migration).

### 5. Onboarding copy, and a help link

At the moment the calendar is created — not buried in settings — say:

> Bookings go to a new calendar called **Junior Bay Bookings**. If you do not see them on your phone,
> switch it on in the Google Calendar app.

Plus a persistent **"Show bookings on your phone"** link in the Calendar Sync panel, because the moment
someone needs it is weeks later, when a booking does not appear on a device and they conclude the
integration is broken.

**This is the one real cost of the design.** On mobile, a newly added calendar sometimes needs enabling
per device. Everything else about the split is neutral or better: the calendar renders alongside their
personal events on the web, and they gain separate colouring, separate notifications, sharing with staff,
and one-action removal of every booking.

## Migration

One connection exists in prod (the author's) and one test user in dev. The scope change forces re-consent
regardless, so:

- existing connections keep working until reconnected (they still hold `calendar.events.owned`)
- on reconnect under the new scopes, a bookings calendar is created and `bookings_calendar_id` stored
- appointments created before the change keep their old `event_id`s in the primary calendar; they remain
  cancellable while the old grant lasts, and the event-404 rule covers it afterwards

**This will never be cheaper.** The same argument applied to the last scope narrowing and was right.

## What building it turned up

Three things the plan did not anticipate, each a silent failure rather than an error:

1. **`busy_intervals` read ONE calendar key.** Querying four calendars in one `freebusy.query` and then
   reading a single key returns one calendar's busy windows and discards the rest — and the slot engine
   cannot tell that from "nothing is busy". It now takes a list.

2. **An existing event was addressed wherever the connection writes TODAY.** Moving the write target from
   `primary` to the bookings calendar redirects every update and delete of an event created before the
   move: the call reports success against a calendar the event was never in, and the real event sits in
   the merchant's calendar forever. `update_event`/`delete_event` now take the calendar the event lives
   in, which is what the stored `external_calendar_events.calendar_id` was always for.

3. **A legacy connection cannot create a calendar.** It holds `calendar.events.owned`, not
   `calendar.app.created`, so `calendars.insert` 403s — and `sync_appointment_event` swallows its own
   failures, so its bookings would simply stop reaching any calendar with nothing anywhere saying so.
   Creation is now gated on the connection's **stored** `scopes`, and absent scopes count as not granted.

Also: the slot picker is a public page, so the read path must never create a calendar — two customers
opening it at once with nothing stored yet would create two. Availability excludes calendars whose
`accessRole` is `reader`/`freeBusyReader`, because a subscribed "Holidays in United States" would
otherwise mark every public holiday fully busy and close the business by accident.

## Open questions — still to confirm against the live API

1. **Can `calendarList.list` see the app-created calendar under these scopes?** Not waited on: the
   bookings calendar is appended to the availability query explicitly rather than trusted to appear in
   the list, because finding out from a double booking is the wrong way to learn it.

**ANSWERED 2026-11-10 against the live account: app-created access survives a full revoke.** The app
was revoked at myaccount.google.com and reconnected. The connection row kept its id
(`cal_f47ce4fd77fd`), `updated_at` moved — so the token really was reminted — and
`bookings_calendar_id` came back unchanged, with no 404 or 403 in the logs. `calendars.get` therefore
succeeded on the FIRST try with a token from an entirely new grant.

So the "app created this" association belongs to the **OAuth client**, not to a grant. Revoking destroys
the credential and leaves the app's relationship to its own calendars intact. A merchant who revokes and
reconnects keeps their bookings calendar and its history.

The outcome worth having ruled out was a **403**: `resolve_bookings_calendar` treats only a 404 as "gone,
make another", so a 403 would have been swallowed by `sync_appointment_event`'s catch-all and bookings
would have stopped syncing with nothing said. It did not happen, and there is now no known path that
produces one.
2. ~~**Does `calendar.app.created` permit `calendars.delete`?**~~ **ANSWERED 2026-11-09: yes.** The
   method accepts `calendar`, `calendar.app.created` or `calendar.calendars`. We still do not call it,
   and should not start lightly -- see below.
3. ~~**Sensitive or non-sensitive?**~~ **ANSWERED 2026-11-08: all three are NON-SENSITIVE.** The prod
   console puts every one of them in the non-sensitive table and leaves sensitive and restricted empty.
   This is the largest consequence of the whole change and it was not anticipated: there is no
   sensitive-scope review and no demo video, only brand verification. The previous scope set
   (`calendar.events.owned`) was sensitive and would have required both.

## The escape hatch, if the UX proves wrong

Granular consent makes this reversible per merchant rather than per product: default to the app-created
calendar on two narrow scopes, and offer *"put bookings in my main calendar instead"* as an opt-in that
**incrementally** requests `calendar.events.owned` only for merchants who ask. Two code paths, so not
worth building now — but the decision is not one-way, which is why it can be taken quickly.

## Orphaned calendars after a revoke (seen 2026-11-09)

Revoking the app at Google and reconnecting produces a NEW connection document, which has no stored
`bookings_calendar_id` and therefore creates a second "Junior Bay Bookings" calendar. The previous one is
left behind, identically named, distinguishable only by its id.

This is correct behaviour, not a bug -- an ordinary reconnect reuses the stored id, which was verified
against a live account the same day. It happens only on a full revoke.

**We do not delete it, and should not start lightly.** `calendars.delete` would be permitted by the
scope, but deleting a merchant's calendar is destructive and irreversible, and one that looks orphaned
from our side may hold booking history they want. If this recurs often enough to matter, keep the
previous id on the connection and ASK -- "an older bookings calendar exists, remove it?" -- rather than
acting. A tidy-up that happens once is a UI job, not a code path that can delete the wrong thing at 3am.
