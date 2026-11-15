# Auto-webinars

Status: **approved 2026-11-15** (author: *"make sure that auto-webinar is the first type of webinar you
create"*). This supersedes [WEBINAR.md §10](WEBINAR.md), which recorded auto-webinars as *not approved*.
§10's own recommendation was **auto before live**, so the direction is unchanged; only the approval is new.

An **auto-webinar** is a pre-recorded video that *starts at a scheduled time*. The registration page, the
event, the occurrences, the reminders and the confirmation email are all identical to a live webinar. The
only thing that changes is what happens when the session starts: instead of handing the visitor a Zoom
link, the page plays the recording, positioned to where the broadcast has got to.

## 1. The finding that reshapes this — and a bug in shipped code

**The event page decides its state at PUBLISH time, not at view time.** `render_checkout_cta` calls
`event_live_occurrence(scheduled_event, now=int(time.time()))` while rendering, and a published page is a
static artifact in S3 (`page_publish` is a DynamoDB **stream** handler; no sweep republishes on a
schedule). The code says so itself: *"Asked at PUBLISH … A page is a cached artifact, so the server still
checks."*

That reasoning is sound for **registration** — the server re-checks, so a stale page cannot create a
registration the server would refuse. It does not hold for the other two states:

* A page published before the session shows the **registration form during the session and after it**.
* `render_event_live` and `render_event_closed` therefore only ever appear if the page happens to be
  published inside the live window, or re-saved by the tenant at the right moment.

So the LIVE window — the feature WEBINAR.md §0 calls *"the whole point of having both"* states — does not
work on a published page today. It looks correct in the builder because `/pages/render` previews render on
demand, with a real clock.

**Auto-webinar cannot be built on top of that**, because playback position is a function of the current
time and nothing else. Fixing it is therefore not a tax on this feature; it is the feature's foundation,
and it repairs the live webinar on the way past.

## 2. Locked decisions

- **Session state moves to the CLIENT.** `starts_at` and the duration are baked into the page as data
  attributes; a small island computes UPCOMING / LIVE / ENDED from `Date.now()` and swaps which block is
  shown. This is exactly what `countdown_timer` in `deadline` mode already does — counting to a fixed
  moment on a static page is a solved problem here, and the same mechanism answers both questions.
  The server keeps refusing registrations on its own clock; nothing about that changes.
- **Auto is a DELIVERY MODE on the event, not a new offer type and not a new page type.** `delivery:
  "auto" | "live"`. The registration page, the leads, the reminders and the emails are all unchanged —
  which is the entire argument for doing auto first. A new `lead_event` sibling would have duplicated a
  page shape to change one block.
- **`delivery` defaults to `auto`** (author, 2026-11-15). A tenant creating a webinar gets an auto-webinar
  unless they choose otherwise.
- **Video is uploaded through `../sam/image-processing`, never a pipeline in this repo.** `POST /upload`
  with `mediaType: "video"` already exists and is the documented path
  ([EXTERNAL_SERVICES.md](../docs/EXTERNAL_SERVICES.md)). Two consequences carried over from that doc:
  there is **no transcode**, so prefer `video/mp4`; and the size ceiling is a CloudFormation parameter in
  *that* stack, so **never hardcode an upload limit here**.
- **Playback is a BROADCAST, not a library.** Position is `now - starts_at`, clamped. The viewer may pause
  and may seek *back*, but may not seek past the live edge: an auto-webinar that can be scrubbed to the
  pitch at the end is just a video page, and the scheduled start is the only reason any of the urgency on
  the registration page is honest.
- **Replay after the session is out of scope**, and stays the open question WEBINAR.md §11 already records.
  ENDED behaves exactly as it does today.

## 3. What already exists — verified 2026-11-15, do not rebuild

| Piece | Where | State |
|---|---|---|
| Event, occurrences, `starts_at`, `duration_minutes`, `ends_at` | `domain/events.py` | shipped |
| `session_state` → UPCOMING / LIVE / ENDED / CANCELLED | `domain/events.py` | shipped |
| Counting to a fixed moment on a static page | `countdown_timer` `mode: deadline` | shipped |
| A video player element | `video` element, `render_video` | shipped |
| Video upload, presigned, with its own size ceiling | sibling `image-processing` | shipped |
| Registration, refusal, reminders, confirmation email | webinars P1–P3 | shipped |

The pure logic to add is small: *where in the recording are we*. Everything around it exists.

## 4. Phases

1. **P1 — the clock moves to the client.** Bake `starts_at`/`ends_at` onto the event CTA block; an island
   picks UPCOMING / LIVE / ENDED at view time and reveals the matching block. Fixes the live webinar.
   `delivery` on the event, defaulting to `auto`. Pure helpers + tests first.
2. **P2 — the player.** When `delivery: "auto"` and the state is LIVE, render the recording instead of the
   join link, positioned at the elapsed offset and barred from seeking past it.
3. **P3 — the tenant side.** Video upload on the Events screen, through the sibling stack's presign; a
   delivery picker that starts on Auto.
4. **P4 — attendance.** How far each registrant actually watched. Deliberately last: it is the part that
   needs a write path per viewer, and it is worth nothing until P1–P3 prove tenants run these at all.

## 5. Open questions

- **Does an auto-webinar need a "starting soon" holding slate** in the last minute or two, or is the
  countdown enough? The reference implementations all show one; it may just be a state of the player.
- **What happens to someone who arrives 80 minutes into a 90-minute session?** Letting them in two minutes
  before the pitch is worse than telling them the truth. A join cut-off (no entry after N% elapsed) is
  probably right, and is one comparison once the client clock exists.
