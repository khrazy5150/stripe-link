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

### `https://www.googleapis.com/auth/calendar.events`

> Junior Bay is a booking platform for small businesses. When a customer books an appointment, we create
> a calendar event on the calendar the merchant selected when they connected their Google account. When
> the customer reschedules, we update that event; when they cancel, we delete it. We only ever create,
> update, or delete events that this application itself created. We do not read the contents of events
> created by anyone else.

API methods used: `events.insert`, `events.update`, `events.delete`.

### `https://www.googleapis.com/auth/calendar.readonly`

> Two uses, both narrow. First, at the moment the merchant connects their account we read the list of
> their calendars once, so they can choose which calendar bookings are written to. Second, when a
> customer is choosing an appointment time we query free/busy for that one calendar, so the platform does
> not offer a slot the merchant is already busy for. The free/busy query returns only whether a period is
> busy — we do not read event titles, descriptions, attendees or locations.

API methods used: `calendarList.list`, `freebusy.query`.

**Narrowing opportunity, untested.** `calendar.readonly` grants more than the above: it permits reading
every event on every calendar. `calendar.calendarlist.readonly` would cover `calendarList.list` alone.
Whether `freebusy.query` is authorised by `calendar.events` is **not verified** — test it in the sandbox
before narrowing. Changing scopes forces every connected tenant to re-consent, so the cheapest moment is
now, while prod has zero connections and dev has one test user.

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
