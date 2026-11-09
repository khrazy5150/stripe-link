# Google OAuth verification — Calendar (prod)

Everything needed to submit `Junior Bay - Calendar Prod` for verification, and the state it was in when
this was written (2026-11-08).

## Why this exists at all

Google Calendar connect had **never worked in production**. `template.yaml` points every environment at
`jb/google-oauth/${Environment}` and only the dev secret existed, so prod asked Secrets Manager for a
secret that was not there; boto3's `ResourceNotFoundException` is not a `GoogleCalendarError`, was caught
nowhere, and became an unhandled 500. `CALENDAR_REDIRECT_URI` was empty on the prod stack as well. The
feature failed on first contact and nothing — no log, no test, no deploy — said so.

## The two projects, and why they are separate

| | Project | Publishing status | Purpose |
|---|---|---|---|
| dev | `Junior Bay - Calendar Sandbox` (`181659905302`) | Testing, forever | the author's own testing; never submitted |
| prod | `Junior Bay - Calendar Prod` (`460733766550`) | Testing → to be published | what tenants authorise |

Separate because **verification is per consent screen, which is per project**, and adding scopes to a
verified app triggers re-verification. Bundling would have put the urgent Calendar submission behind a
speculative Google Business Profile one.

## Configuration as submitted

- **Authorized redirect URI:** `https://prod.juniorbay.com/calendar/callback` — verified against API
  Gateway: that host maps to REST API `jloezsxw05`, stage `prod`, and the route answers.
- **Authorized JavaScript origin:** `https://app.juniorbay.com`. Unused — this is a server-side code
  exchange — but harmless, and it registers `juniorbay.com` as an authorized domain.
- **Homepage / privacy / terms:** `https://juniorbay.com`, `/legal/privacy`, `/legal/terms`. All 200. The
  legal pages are rendered by `LegalFunction` and reach the marketing domain through a CloudFront
  behaviour (`PathPattern: /legal/*` → `HomepageLegalApiOrigin`), so they ship with `deploy.sh`, **not**
  `deploy-homepage.sh`.
- **Scopes:** exactly `DEFAULT_SCOPES` from `src/stripe_link/google_calendar.py` — scope strings and
  user-facing labels both confirmed against the prod console 2026-11-08, matching `REQUIRED_SCOPE_LABELS`
  in `handlers/calendar.py` exactly (those labels are what the partial-grant refusal shows a merchant).
  **All three are NON-SENSITIVE.** The sensitive and restricted tables are empty.

## Scope justifications — the text reviewers read

Keep these tied to the calls the code actually makes. Every claim below is checkable in
`src/stripe_link/calendar_sync.py` and `src/handlers/calendar.py`.

### `https://www.googleapis.com/auth/calendar.app.created`

> Junior Bay is a booking platform for small businesses. When a merchant connects their Google account we
> create one secondary calendar in it, named "Junior Bay Bookings", and every appointment a customer books
> becomes an event on that calendar. When the customer reschedules we update that event; when they cancel
> we delete it. This scope can only reach a calendar this application itself created, so the merchant's
> existing calendars and events are outside our access entirely — we cannot read, change or delete any
> event we did not create. We do not read event contents from anywhere.

API methods used: `calendars.insert`, `calendars.get`, `events.insert`, `events.update`, `events.delete`.

`calendars.get` is how we detect that a merchant has deleted the bookings calendar themselves, so we can
create a replacement instead of failing their next booking.

### `https://www.googleapis.com/auth/calendar.freebusy`

> When a customer is choosing an appointment time, we query free/busy across the merchant's own calendars
> and the bookings calendar, so the platform does not offer a slot the merchant is already committed for,
> and two customers cannot take the same slot. This returns only whether a period is busy — not event
> titles, descriptions, attendees or locations.

API method used: `freebusy.query`.

### `https://www.googleapis.com/auth/calendar.calendarlist.readonly`

> We read the list of the merchant's calendars to know which ones count toward that availability check,
> and to show them which Google account is connected. We read the list only — never the contents of any
> calendar in it.

API method used: `calendarList.list`.

**Not optional, and must not be described as optional.** With bookings in a calendar of their own, a
free/busy query against that calendar alone would see only our own appointments and none of the merchant's
real commitments — the opposite of the point. The list is how we learn which calendars to include. We
include only calendars whose `accessRole` is `owner` or `writer`, so a read-only subscription such as
"Holidays in United States" cannot mark whole days busy and close the business by accident.

### Why these three (narrowed twice, 2026-11-08)

The original pair was `calendar.events` + `calendar.readonly`. `calendar.readonly` — *"See and download any
calendar you can access using your Google Calendar"* — asks a merchant for far more than a booking tool
needs. That became `calendar.events.owned` + `calendarlist.readonly` + `freebusy`, and then this.

Checked against the API reference rather than assumed:

| Method | Scopes Google accepts | Chosen |
|---|---|---|
| `calendars.insert` | `calendar`, `calendar.app.created`, `calendar.calendars` | `calendar.app.created` |
| `events.insert/update/delete` | `calendar`, `calendar.events`, `calendar.app.created`, `calendar.events.owned` | `calendar.app.created` |
| `freebusy.query` | `calendar.readonly`, `calendar`, `calendar.events.freebusy`, `calendar.freebusy` | `calendar.freebusy` |
| `calendarList.list` | `calendar.readonly`, `calendar`, `calendar.calendarlist`, `calendar.calendarlist.readonly` | `calendar.calendarlist.readonly` |

**`calendar.events.owned` is dropped.** It reaches every calendar the merchant owns, and our defence was a
promise — *we only touch events we created*. With bookings in a calendar the app itself created, that is a
property of the API instead: `calendar.app.created` has no path to a calendar it did not create. The claim
a reviewer has to accept on trust is gone, which is the single strongest thing this submission can say.

**`freebusy.query` does NOT accept `calendar.events`** — that was the obvious guess and it is wrong, which
is why it was looked up. Each scope maps onto one job, so "minimum necessary" is self-evident from the
list rather than a claim to be taken on trust.

Changing scopes forces every connected tenant to re-consent. Done while prod had zero connections and dev
had one test user.

### What the merchant gives up, and is told

Bookings no longer land in a calendar they pick — there is no picker, because nothing we request can write
to a calendar they already had. The costs, and what covers each:

| Cost | Covered by |
|---|---|
| A newly added calendar is sometimes switched off per device, so bookings show on the web but not on a phone | Said on the connect confirmation page, plus a persistent **"Show bookings on your phone"** disclosure in Calendar Sync |
| `PATCH /calendar/connections/{id}` with a `calendar_id` can no longer redirect bookings | Refused with `calendar_not_selectable` and an explanation, rather than stored and silently ignored |

In exchange the merchant gets separate colouring, separate notifications, sharing with staff, and
one-action removal of every booking — and an app that cannot see the rest of their calendar.

## There is no sensitive-scope review (confirmed 2026-11-08)

The console classifies all three scopes as **non-sensitive**, which was open question #3 and is the
largest single consequence of moving to `calendar.app.created`. Google ties the Verification Center
submission to sensitive or restricted scopes; with neither table populated there is no scope review, and
therefore **no demo video** — it is named in Google's documentation only as additional evidence for
sensitive or restricted scope verification.

What remains is **brand verification**, which applies because the app is External, will be Published, and
shows a name and logo on the consent screen. That is a branding check, not a scope review:

- Branding page complete: app name, logo, developer contact, links
- home page publicly reachable and plainly about the app — `https://juniorbay.com`
- privacy policy **on the same domain as the home page** — `https://juniorbay.com/legal/privacy` ✓
- authorized domains verified in **Google Search Console**
- scopes declared under *Add or remove scopes* ✓
- **Verify branding** → **Publish branding**. Results are valid for 7 days.

The only item that still wants attention is the one already in Loose ends: the support contact is on
`juniorbay.net`, a different domain from the authorized `juniorbay.com`.

## Order of operations

1. Deploy dev → prod, so the privacy policy and terms describing the new scopes are live **before**
   anything is reviewed or any merchant sees the consent screen.
2. Reconnect the test tenant. The scope change forces re-consent, and that first connect is what creates
   the bookings calendar.
3. Branding complete → **Verify branding** → **Publish branding**, then **Publish app** on the Audience
   page. Publishing ends the Testing-mode 7-day refresh token expiry.

Testing-mode refresh tokens still expire after 7 days until the app is published, so step 3 is what makes
a connection last.

## What the privacy policy had to say, and now does

`domain/legal.py` generates the platform policy. It named only Stripe and said merely "information from
third-party services you choose to connect" — the most common reason sensitive-scope verification is
refused. It now carries a **Google User Data** section: what is accessed and why, what is not done
(no advertising, no sale, no transfer, no AI/ML training, no human access), what is stored (an encrypted
token and the id of the calendar we create, not a copy of the calendar) and until when, both ways to revoke, and
the **Limited Use** statement naming the Google API Services User Data Policy.

## What is stored (answered 2026-11-08)

Asked directly: does Junior Bay keep Google event IDs, or only tokens and the calendar id? **Both.**
`calendar_sync.py` persists an `external_calendar_events` entry on each appointment —
`{provider, connection_id, calendar_id, event_id}` — where `event_id` is the identifier Google assigned
to the event we created. It is what `update_event` and `delete_event` are called with when a booking is
rescheduled or cancelled (`calendar_sync.py:106-116`).

So the stored set is: an encrypted refresh token, the id of the bookings calendar we created
(`bookings_calendar_id`), and one Google event id per booking. **No event contents** — no titles,
descriptions, attendees or locations — and no copy of the calendar.

The privacy policy's storage paragraph originally named only the token and the calendar id. It was
accurate about contents and silent about the event ids, which is the kind of omission a reviewer is
entitled to pick up. Corrected.

**The event ids are a second, independent reason the "only our own events" claim holds.** Even setting
the scope aside, we can only address an event whose id we stored when we created it. With
`calendar.app.created` the scope already makes it impossible to reach anything else, so the two arguments
are belt and braces rather than one load-bearing promise.

## Loose ends

- Support contact is `support@juniorbay.net`, a different domain from the authorized `juniorbay.com`.
  Not a blocker; a reviewer comparing the two may pause.
- The legal text was drafted against what the code does. It is accurate to the implementation; it has not
  been reviewed by a lawyer.
