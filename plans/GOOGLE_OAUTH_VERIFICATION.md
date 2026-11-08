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
- **Scopes:** exactly `DEFAULT_SCOPES` from `src/stripe_link/google_calendar.py`. Both sensitive; the
  restricted table is empty, so **no third-party security assessment is required**.

## Scope justifications — the text reviewers read

Keep these tied to the calls the code actually makes. Every claim below is checkable in
`src/stripe_link/calendar_sync.py` and `src/handlers/calendar.py`.

### `https://www.googleapis.com/auth/calendar.events.owned`

> Junior Bay is a booking platform for small businesses. When a customer books an appointment, we create
> a calendar event on the calendar the merchant selected when they connected their Google account. When
> the customer reschedules, we update that event; when they cancel, we delete it. We only ever create,
> update, or delete events that this application itself created, and only on a calendar the merchant
> owns — the application refuses to be pointed at a calendar that is merely shared with them. We do not
> read the contents of events created by anyone else.

API methods used: `events.insert`, `events.update`, `events.delete`.

**Why `.owned` and not `calendar.events`.** `calendar.events` reaches every calendar the merchant can
*see*, shared ones included; `.owned` reaches only calendars they own. The narrower scope is safe only
because `handlers/calendar.py` now refuses a `calendar_id` whose `accessRole` is not `owner` — otherwise
a merchant could select a shared calendar, be accepted, and 403 at the first real booking weeks later.

### `https://www.googleapis.com/auth/calendar.calendarlist.readonly`

> When a merchant first connects their Google account we read the list of their calendars once, so they
> can choose which calendar their bookings are written to. We do not read the contents of any calendar.

API method used: `calendarList.list`.

### `https://www.googleapis.com/auth/calendar.freebusy`

> When a customer is choosing an appointment time, we query free/busy for the one calendar the merchant
> selected, so the platform does not offer a slot the merchant is already busy for. This returns only
> whether a period is busy — not event titles, descriptions, attendees or locations.

API method used: `freebusy.query`.

### Why these three and not `calendar.readonly` (narrowed 2026-11-08)

The original pair was `calendar.events` + `calendar.readonly`, where `calendar.readonly` served both the
calendar list and the free/busy query. Its consent text — *"See and download any calendar you can access
using your Google Calendar"* — asks a merchant for far more than a booking tool needs, and invites the
reviewer's obvious question.

Checked against the API reference rather than assumed:

| Method | Scopes Google accepts | Chosen |
|---|---|---|
| `freebusy.query` | `calendar.readonly`, `calendar`, `calendar.events.freebusy`, `calendar.freebusy` | `calendar.freebusy` |
| `calendarList.list` | `calendar.readonly`, `calendar`, `calendar.calendarlist`, `calendar.calendarlist.readonly` | `calendar.calendarlist.readonly` |
| `events.insert/update/delete` | `calendar`, `calendar.events`, `calendar.events.owned` | `calendar.events.owned` |

**`calendar.app.created` was considered and not taken.** It is narrower still — the app creates its own
secondary calendar and can never touch the merchant's existing events — but it changes the product: no
"choose which of your calendars bookings go to", and new code to create and track that calendar. A
product decision, not a scope tweak. Worth revisiting on its merits.

**`freebusy.query` does NOT accept `calendar.events`** — that was the obvious guess and it is wrong, which
is why it was looked up. Each scope now maps one-to-one onto a single method, so "minimum necessary" is
self-evident from the list rather than a claim to be taken on trust.

Changing scopes forces every connected tenant to re-consent. Done while prod had zero connections and dev
had one test user.

## Order of operations

1. Branding complete → **Publish app** on the Audience page. This ends the Testing-mode 7-day refresh
   token expiry.
2. Submit from the Verification Center **after** the deploy that carries the privacy policy — otherwise
   the reviewer opens a policy with no mention of Google.
3. Expect a demo video request: record the consent flow and show where each scope is used.

## What the privacy policy had to say, and now does

`domain/legal.py` generates the platform policy. It named only Stripe and said merely "information from
third-party services you choose to connect" — the most common reason sensitive-scope verification is
refused. It now carries a **Google User Data** section: what is accessed and why, what is not done
(no advertising, no sale, no transfer, no AI/ML training, no human access), what is stored (an encrypted
token and the chosen calendar id, not a copy of the calendar) and until when, both ways to revoke, and
the **Limited Use** statement naming the Google API Services User Data Policy.

## Loose ends

- Support contact is `support@juniorbay.net`, a different domain from the authorized `juniorbay.com`.
  Not a blocker; a reviewer comparing the two may pause.
- The legal text was drafted against what the code does. It is accurate to the implementation; it has not
  been reviewed by a lawyer.
