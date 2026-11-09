# Bookings get their own calendar (app-created)

Planned 2026-11-08. Not built. Supersedes the `calendar.events.owned` arrangement shipped the same day,
and should land **before** the verification submission — otherwise Data Access, the justifications and the
demo video are all redone.

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

## Open questions — test before building

1. **Can `calendarList.list` see the app-created calendar under these scopes?** If not, the stored id is
   not merely wise but mandatory, and a merchant who deletes the calendar can only be recovered through
   the 404 path.
2. **Does `calendar.app.created` permit `calendars.delete` / `calendars.update`?** Relevant only if we
   ever rename or remove it; not needed for the first cut.
3. **Sensitive or non-sensitive?** The console reports the classification once the scopes are saved. If
   `freebusy` or `calendarlist.readonly` land as non-sensitive, the review narrows further.

## The escape hatch, if the UX proves wrong

Granular consent makes this reversible per merchant rather than per product: default to the app-created
calendar on two narrow scopes, and offer *"put bookings in my main calendar instead"* as an opt-in that
**incrementally** requests `calendar.events.owned` only for merchants who ask. Two code paths, so not
worth building now — but the decision is not one-way, which is why it can be taken quickly.
