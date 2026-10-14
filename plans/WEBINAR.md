# Webinars

Status: **proposed** (design only — no code yet). Author-approved direction from the 2026-10-14 discussion;
the v2 sketch in §10 is explicitly *not* approved and is recorded so the v1 shape does not foreclose it.

> **Mostly-built note.** Unlike most greenfield plans here, the majority of this already exists. Lead
> capture, the lead page shapes, the reminder sweep and the mailer are all shipped. The genuinely new work
> is a small one: an **Event** object, a **confirmation email**, and a **post-event state**. Read §3 before
> estimating anything — the temptation is to rebuild machinery that is already running.

## 0. What a webinar actually is (author, 2026-10-14)

> "A webinar is just a **free event** that's basically a sales pitch to get customers to buy something
> later. The point is to get people to **watch the presentation in its entirety**. The landing page's job is
> to **collect these leads and push them to the URL at the appropriate time**."

Two things follow, and both corrected this design after it was first written:

* **A webinar is not a sale, and its session is not a deadline on an offer.** The `event_date` element's
  `auto` source resolves a SALE expiry and stays that way; a registration page names `source: "event"`
  outright. Blending them would make one element mean different things on different pages.
* **The page has three jobs, not two.** Before the session it collects a lead; **during** it pushes the
  visitor at the join URL; after it says they missed it. The first model collapsed "has started" into
  "passed", so the page said "you missed it" at the exact moment the link mattered most. `session_state`
  (UPCOMING / LIVE / ENDED / CANCELLED) is separate from `registration_state` for this reason -- they
  disagree during the live window, which is the whole point of having both.

## 1. What we're building

A **webinar registration page**: a visitor arrives, sees what the session is and when, hands over their
details, and receives a confirmation with a join link and a calendar invite. Before the session they get
reminder emails. After it, the page stops taking registrations and says so.

v1 does **not** host the webinar. The tenant runs it on Zoom / WebinarJam / Google Meet and gives us the
join URL.

## 2. Locked decisions

- **A new OFFER TYPE `lead_event`, not a new page type.** The codebase already expresses "a lead page of a
  particular shape" as an offer type — `lead_capture`, `lead_bridge`, `lead_social`, `lead_call` all exist
  and differ mainly in composition. A webinar page is a fifth. This inherits the form, the leads table, the
  consent record and the CTA for free, and lets the composition differ where it genuinely does (date band,
  speaker bio, agenda, closed state). A new *page type* is the Site/Page axis and answers a different
  question.
- **The event is its OWN OBJECT, with occurrences.** Not fields hung off the offer. The normal case is a
  recurring session ("every Wednesday at 7pm EST", and a second time for Australia), and the field-bag
  version forces a new offer and a new page per week. Retrofitting occurrences later is a migration over
  live registrations; starting with them costs one extra level of nesting. It is also precisely the shape an
  auto-webinar schedule needs (§10), so the cheap decision now is the one that does not have to be undone.
- **v1 comms: a confirmation email carrying the join link and an `.ics`, plus email reminders.** No SMS in
  v1 (§8).
- **Registration closes when the occurrence starts.** A page that silently keeps collecting registrations
  for a session that already happened is the worst failure mode available here, and is what every reference
  implementation guards against.

## 3. What already exists — verified 2026-10-14, do not rebuild

| Piece | Where | State |
|---|---|---|
| Lead ingest, public + idempotent, with consent + provenance | `src/handlers/leads.py`, `LeadsTable` | shipped |
| Lead page shapes and their composition | `composition_rules.json` `offer_types` | shipped |
| Reminder scheduling, idempotent records, cancel/mark-sent | `src/stripe_link/domain/reminders.py` | shipped |
| A sweep that sends what is due | `src/handlers/reminders.py`, `rate(15 minutes)` | shipped |
| Transactional email | `src/stripe_link/mailer.py` | shipped |
| The date, in plain English, derived or explicit | `event_date` element | shipped 2026-10-14 |
| A countdown to a fixed moment | `countdown_timer` `mode: deadline` | shipped 2026-10-14 |

Two gaps behind the convenient summary:

- **Nothing emails a lead today.** `leads.py` stores the row and emits a dashboard notification; it has no
  mailer call. The confirmation email is new work, not a wiring job.
- **Reminders are appointment-shaped.** `plan_reminders` takes an appointment and writes `reminders[]` onto
  it; the `channel` parameter is already generic and defaults to `sms`. Registrations are a different
  carrier. Either generalise the record's owner or give registrations their own array of the same shape —
  the scheduling, idempotency and sweep logic should be reused either way.

## 4. Data model

```
Event                      (EventsTable, per environment)
  event_id, tenant_id
  title, description
  provider: zoom | webinarjam | meet | teams | other
  join_url                 the tenant's own link
  duration_minutes
  occurrences[]
    occurrence_id
    starts_at              epoch seconds
    timezone               IANA, the HOST's zone (see §7)
    capacity               optional — "Only 500 available"
    status                 scheduled | cancelled
```

A registration is a **lead**, not a new entity: `leads.py` already stores `fields`, consent, provenance and
an idempotency key. It gains `event_id` + `occurrence_id`. That keeps one list of people, one export, one
consent story, and one place where PII lives.

The offer references the event (`offer.event_id`), which is what makes `lead_event` a thin composition over
machinery that already works.

## 5. The page

Composition for `lead_event`, mirroring `lead_capture` and adding what a session page needs:

- `brand_label`, `hero_media`, `hero` — as today
- `event_date` — the occurrence, in plain English (already built, point its source at the occurrence)
- `countdown_timer` in `deadline` mode — optional, counting to the start (already built)
- `author_bio` — the host; webinars are sold on the speaker
- `info_cards` — "what you'll learn" (already built, and the numbered style is exactly this)
- `checkout_cta` — the registration form
- `legal_footer`

Excludes mirror `lead_capture`: no price selector, no product details, no refund policy.

**Occurrence choice.** When an event has more than one occurrence the form needs a picker ("Australia / USA"
in the reference). With one, it is hidden and the single occurrence is implied.

## 6. Registration flow

1. Visitor submits → existing public `POST /leads` path, with `event_id` + `occurrence_id` in the payload.
2. Server validates the occurrence is **in the future** and **not at capacity**, else returns a refusal the
   page can render (§9). The client must not be trusted for either.
3. Lead stored, as today.
4. **Confirmation email** sent: what, when (in the registrant's own words — see §7), the join link, and an
   `.ics` attachment. The `.ics` matters more than any reminder: it puts the session in their calendar,
   where their own device reminds them.
5. **Reminders planned** at 24h and 1h before `starts_at`, reusing `plan_reminders`' record shape so the
   existing sweep sends them.

## 7. Timezones

The `event_date` element already decided this for display: a session is announced in the **host's** zone,
because "7PM EST" is part of what is being announced and the references all label it that way.

The **confirmation email should carry both** — the host's zone (so it matches the page) and the registrant's
if we can infer it from the browser at submit time. This is the one place where converting is clearly right:
the email is addressed to one person, not to an audience.

`.ics` carries UTC with a timezone component, so the calendar does the conversion correctly regardless.

## 8. Why no SMS in v1

We have 10DLC and an SMS path, and SMS has the highest show-up rate of any reminder channel. It is still out
of v1 because the consent story is a legal one, not a technical one: the reference page's disclaimer
(autodialer, STOP handling, "not a condition of purchase") is TCPA language, and getting it wrong is a
per-message statutory exposure carried by the tenant *and* the platform. `build_consent` already records
consent properly, so this is a deliberate sequencing choice rather than a missing capability — add it once
someone has read the requirements, not because it was easy to turn on.

## 9. The post-event state

When `starts_at` has passed (or capacity is reached):

- the registration form is **replaced**, not merely disabled — a disabled form invites people to try
- the page says plainly that the session has happened, as the WebinarJam reference does
- if the event has a **later occurrence**, the page offers that one instead. This is the case that justifies
  occurrences living inside the event rather than each being its own page.

This state is computed at render from the occurrence, like every other derived thing here — not stored, so
it cannot go stale.

## 10. v2 — recorded, not approved

The author raised hosting webinars on AWS, including **auto-webinars** (pre-recorded, replayed on a
schedule). Recorded here so v1 does not block it:

- **Auto-webinar is the cheaper and more interesting half.** A pre-recorded video that "starts" at a
  scheduled time is close to the existing `video` element plus a gate and an attendance window. The
  occurrence model in §4 is already the schedule it needs. Most of this market runs auto-webinars.
- **Live hosting is a video platform, not a feature.** IVS/MediaLive, chat, attendance tracking, moderation,
  and a cost curve that scales with viewer-minutes rather than tenants. It is also the least differentiated
  thing in the stack — Zoom exists.
- Recommendation: ship v1, find out whether tenants run webinars at all, and if they do, build
  **auto-webinar before live**.

## 10a. Known constraint for P2: registrations are not queryable by session

Registrations are leads in `LeadsTable`, keyed `PK=TENANT#<tenant>` / `SK=LEAD_SUBMISSION#<lead_id>`. Each
carries `event_id` + `occurrence_id`, so they are **logically** segregated -- but there is **no index on
either**, so "everyone registered for Wednesday" means listing the tenant's whole lead set and filtering in
memory.

This is why `registered_count` is maintained on the occurrence rather than derived: counting would
otherwise read a tenant's entire lead history on every submission.

P2's reminder sweep will feel it. The fix when it is worth paying for is a GSI keyed
`OCCURRENCE#<occurrence_id>` on the leads table, which makes the registrant list a direct query and makes
the count derivable rather than maintained. Deliberately not built on speculation (author: "leads are not
customers and therefore shouldn't get top priority").

## 11. Open questions

- Does a registration need a **cancel / manage** link? The tip jar made the same call and chose link-based
  management with no buyer accounts ([[project_tip_jar]]); the same answer probably applies.
- Do we show **"Only 500 available"** honestly — i.e. decrement a real counter — or is it tenant-entered
  copy? Only the first is defensible, and it needs capacity to be enforced server-side (§6.2).
- **Replay for registrants only** appears in one reference. That is a gated asset, which the download
  machinery may already cover.

## 11a. P2 as built (2026-10-14)

Differs from §6 in two places worth recording:

* **The reminder sweep is driven by EVENTS, not leads.** §10a's missing index made the obvious design —
  scan registrations — mean reading every tenant's entire lead history every fifteen minutes. Inverting it
  reads the small table instead, and only a tenant with a session inside a ~25h horizon has their leads
  listed at all. The index in §10a is now a nice-to-have rather than a prerequisite.
* **What is due is DERIVED from `starts_at`, never planned and stored.** A stored schedule needs rewriting
  whenever a tenant moves a session and goes stale when a sweep is missed. Deriving means a sweep that
  fails sends LATE rather than not at all, and moving a session moves its reminders with no rewrite.

When several notices come due at once — a session created an hour before it runs, or a missed window —
only the **most imminent** is sent and the rest are recorded as `superseded`. "Starts tomorrow" about a
session starting in thirty minutes is not a duplicate, it is wrong.

A separate handler from `handlers/reminders.py`: that one is appointment SMS and returns early when no
10DLC origination number is configured, so folding email into it would have made these silently depend on
an SMS registration they have nothing to do with.

## 12. Phases

1. **P1 — Event + registration.** EventsTable, `lead_event` offer type and composition, occurrence picker,
   server-side future/capacity checks, post-event state.
2. **P2 — Comms.** Confirmation email with `.ics`; reminders retargeted from appointments to registrations.
3. **P3 — Operations.** Registrant list and export in the dashboard (likely falls out of the existing leads
   screen), cancellation, "notify me of the next one".

## 13. Budget note

A new table and a new route both consume CloudFormation transform budget. That was 6,047 bytes of headroom
before 2026-10-11 and is ~138,000 after the env-var work ([[project_transform_budget_done]]), so this fits —
but check `tests/envreach.py` before assuming, because the margin is shared with everything else in flight.
