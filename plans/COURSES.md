# Junior Bay Courses

**Status:** design agreed 2026-09-07, not built. Supersedes the "video delivery service" framing.

## What this is

Not video hosting. **Knowledge as another thing a Junior Bay tenant can sell**, through the storefront,
checkout, customer records and analytics they already have.

The pitch is not "we have a video CDN". It is:

> **You already have a store. Now sell a course from it.**

That matters because it decides what gets built. Teachable, Kajabi and Thinkific sell a course platform to
someone who does not have one. Junior Bay's tenant already has a store, a payment processor, a customer
list, a domain and analytics — and does not want a second account for any of them. A maker selling
handmade goods adds *"How I Make These — $29"*. A photographer adds *"Learn Product Photography — $79"*.
The course is a new **product type**, not a new application.

```
                 JUNIOR BAY COMMERCE
                        │
       ┌────────────────┼────────────────┐
       ↓                ↓                ↓
   Physical         Digital           Course
   Product          Product           Product
       │                │                │
       └────────────────┼────────────────┘
                        ↓
                    Checkout
                        ↓
                   Entitlement
                        ↓
              ┌─────────┴─────────┐
              ↓                   ↓
          Download             Playback
```

Video also becomes just another media type on a pipeline that already exists:

| Media | Pipeline |
|---|---|
| Image | S3 → Lambda → sharp → CloudFront |
| **Video** | **S3 → Lambda → MediaConvert → CloudFront** |
| Digital product | S3 → entitlement → download |

## Entitlement is NOT the cookie

The single most important separation in this design, and the one easiest to get wrong.

```
                ┌── free
Customer ───────┤── purchased
                ├── subscription
                ├── enrolled
                └── drip-scheduled
                       ↓
                  ENTITLEMENT          ← commercial rules live here
                       ↓
            "User X may access resource Y"
                       ↓
             PLAYBACK AUTHORIZATION    ← delivery mechanism lives here
                       ↓
              short-lived signed access
```

A tenant may sell a $49 standalone course, a $19/month membership, individual lessons, a bundle, a
subscription covering fifty courses, a free preview, or a drip schedule. **The video system must know none
of that.** It receives one sentence — *user X is entitled to resource Y* — and turns it into temporary
playback authorization.

This is the same layering the platform already uses elsewhere: commerce primitives underneath,
presentation and context above. It is also what stops the media layer from having to change every time a
new pricing shape is invented.

The entitlement half is **already built**. `downloads.serve_handler` verifies a paid order owns a product
and issues short-lived access; a course lesson is the same question with a different answer format.

## ⚠️ The constraint that shapes the delivery design

**CloudFront signed cookies will not reliably work here, and this must be settled before anything is
built.**

A published page can be served from any of three origins:

- a tenant's **custom domain** (`academy.tenant-brand.com`)
- a **platform hostname** (`*.jbay.uk`, `*.jbay.be`)
- the platform host

If video is served from `media.juniorbay.net`, then a signed cookie set for that host is a **third-party
cookie** relative to the page. Safari blocks those outright and Chrome has been removing them. The
textbook AWS answer — "use signed cookies for HLS, because a manifest references hundreds of segments" —
assumes the player and the media share an origin. Here they usually will not.

Three viable alternatives, to be chosen deliberately:

1. **Signed manifest, signed segments.** A request-time Lambda (or CloudFront Function) rewrites the HLS
   manifest so every segment URL carries a short-lived signature. No cookies, works cross-origin. Costs a
   function invocation per manifest request, not per segment.
2. **Token in the path, validated at the edge.** A CloudFront Function checks a signed token embedded in
   the request path against the entitlement. Cheap, but the token is visible and shareable for its
   lifetime.
3. **Serve media under the page's own origin.** Same-origin, so cookies work — but it needs per-tenant
   CloudFront behaviour on custom domains, which is a significant edge-routing change.

**Recommendation: (1).** It is cross-origin by construction, keeps the bucket private behind Origin Access
Control, and the signature lifetime is ours to choose. Cost scales with manifest requests, which is far
below segment volume.

## The other decision to make now: a separate namespace

Video should not share the images distribution. Give it its own:

```
images.juniorbay.net     ← existing, public, immutable, long cache
media.juniorbay.net      ← new: video, authorized, range requests, different cache policy
   /media/{tenant_id}/videos/{video_id}/...
```

Video needs range requests, different MIME handling, different cache behaviour and — unlike images —
**authorization on every request**. Sharing a distribution means one cache policy and one security posture
serving two things with opposite requirements. Separating them costs nothing today and is painful to undo
later.

## Phases

Deliberately ordered so each phase is useful on its own. Notably the **video primitive comes before the
course product** — it is independently valuable, and building curriculum first would mean designing
against a delivery layer that does not exist yet.

### Phase 1 — Video infrastructure

```
VideoAsset · VideoEncoding · VideoVariant · VideoPlaybackAuthorization
```

Upload → MediaConvert → HLS ladder → CloudFront → protected playback. No curriculum, no course.

Includes what the current pipeline lacks for video: **duration**, **poster frames**, and an encoding
**status model** with a tenant-visible failure — MediaConvert jobs do fail on corrupt files and exotic
codecs, and today a video that cannot be processed has nowhere to report that.

Also settle **master retention**: keep the source for re-encoding (a future ladder change) or delete it
after success. Keeping is right, but it should be an explicit lifecycle rule rather than an accident.

### Phase 2 — Video as a content component

A page section or lesson can hold:

```json
{ "type": "video", "video_id": "…", "poster": "…", "duration": 382 }
```

The builder understands video. This is where the existing `video` element graduates from a public file or
YouTube link to a first-class, optionally-gated asset.

### Phase 3 — Course product

```
Course
 ├── Modules
 │    └── Lessons
 │         ├── Video
 │         ├── Text
 │         ├── Download
 │         └── Quiz
```

Now the commerce machinery does the interesting part: sales page, checkout, payment, enrolment — all
existing.

### Phase 4 — Learning state

```
Enrollment · LessonProgress · CourseProgress · Completion · LastPosition
```

**Resume playback is the highest-value item in this phase and possibly in the whole plan.** Not because it
is technically hard — it is not — but because it is what makes the product *feel* like a course platform
rather than a video page:

> **Continue watching**
> Module 3 — Lesson 4
> 17:42 / 31:08

The storage needed is trivial: `user_id, course_id, lesson_id, position_seconds, completed, updated_at`.
That single record buys more perceived quality than most of an LMS feature list.

## Unit economics — instrument from day one

Images cost **storage**. Video costs **delivery**. That is a different business, and the metric is not how
much tenants upload but **how many GB customers actually watch**.

Emit from the first phase:

```
video_uploaded · video_encoded · video_storage_gb
video_play_started · video_seconds_watched
video_gb_delivered · video_completion_rate
```

The number these produce is the one that matters:

> *"This tenant generated $1,200 in course revenue and consumed $37.40 of video delivery."*

Until that ratio is known, **video delivery must not be buried inside an unlimited $19/month plan**. The
pricing model (free-forever + transaction fees, `project_pricing_model_pivot`) charges on transactions,
which happens to align well: a course that sells generates fee revenue alongside its delivery cost. But
that alignment needs measuring, not assuming — a tenant with one popular free preview could deliver
serious bandwidth against zero revenue.

## Cost shape

Rough orders of magnitude; verify current AWS pricing before committing.

| | Driver | Notes |
|---|---|---|
| Encoding | per output-minute | 1 hour × 4 renditions = 240 output-minutes, one-time, low single-digit dollars |
| Storage | per GB/month | ~1 GB per HD hour across renditions; pennies |
| **Delivery** | **per GB served** | **The one that matters. Scales with watch time, not catalogue size** |

## Open questions

1. **Playback authorization mechanism** — signed manifest (recommended), edge token, or same-origin
   serving. Blocks Phase 1.
2. **The player is a new dependency.** Safari plays HLS natively; Chrome and Firefox need `hls.js`
   (~120 KB gzipped). Published pages currently ship **zero JS dependencies** — every interaction is
   hand-rolled inline script. That is a deliberate property, and this is the first thing to ask for it
   back. Worth pricing rather than assuming.
3. **Free preview** — a lesson marked free needs playback without entitlement, which is a different path
   through the same authorizer.
4. **Drip scheduling** — an entitlement-layer concern, not a video one. Recorded so it does not leak
   downward.
5. **MediaLive vs AWS IVS for Phase 5.** IVS is built for platforms letting their users stream and is
   likely the lighter fit; MediaLive + MediaPackage is broadcast-grade. Decide at the start of the live
   phase, not after — see the addendum.
6. **Who supplies the encoder?** MediaLive ingests RTMP, so the tenant needs OBS or similar. This is the
   biggest non-technical risk in the live phase.
7. **Build vs buy remains open for Phase 1 only.** Mux / Cloudflare Stream / api.video collapse Phase 1 to
   about a day, at a per-minute cost and with tenant media living elsewhere. Phases 2–4 are the same work
   either way. The case for building is that S3, SQS, Lambda and CloudFront are already in place, and
   "where tenant media lives" is a strategic property for a platform.

## What already exists

Worth stating plainly, because it is most of the hard part:

- **S3 source + target buckets**, and an S3 → SQS → Lambda pipeline that MediaConvert slots into exactly
  where `sharp` sits for images
- **CloudFront** in front of media
- **Entitlement** — `downloads.serve_handler` already verifies a paid order owns a product before issuing
  short-lived access
- **Checkout, orders, customers, tenants, published pages, custom domains**
- **A `video` page element** (shipped 2026-09-07) that already handles uploaded files and YouTube/Vimeo
  embeds, with per-element shape

The genuinely new infrastructure is **MediaConvert + protected HLS playback + a player**.

## Addendum — live streaming (agreed 2026-09-07)

Live is **Phases 5–6**. VOD and live are one **video commerce** primitive, not two features. The distinction is narrow and
entirely in the backend:

| | VOD | Live |
|---|---|---|
| Service | MediaConvert | MediaLive → MediaPackage |
| Shape | processes a file you already have | continuously processes an incoming feed |
| Billing | per output-minute, one-time | **per hour the channel is running** |
| Ops | serverless-ish, fire and forget | a provisioned, running broadcast channel |

```
                    JUNIOR BAY VIDEO
                          │
             ┌────────────┴────────────┐
            VOD                       LIVE
             │                         │
         Upload S3                 Live input
         SQS/Lambda                 MediaLive
        MediaConvert              MediaPackage
          HLS files                   HLS
             └────────────┬────────────┘
                      CloudFront
                      Entitlement
                       HLS Player
```

**The player does not care.** Both branches emit HLS, so one component serves both:

```
<JuniorBayVideo source="…" type="vod" />
<JuniorBayVideo source="…" type="live" />
```

The commerce layer does not care either. Every live product is the existing offer → payment → entitlement
chain with a different resource on the end: a live course, a paid event, weekly coaching, a members-only
Q&A. **That is the architectural win** — live adds a media backend, not a second commerce system.

### Authorization differs from VOD, and the entitlement layer does not

For VOD the recommendation is a signed manifest. Live does not carry that mechanism over: AWS's live
architecture uses **MediaPackage CDN authorization** — a CDN identifier header ensuring the MediaPackage
endpoint only serves through the authorized CloudFront distribution.

That is infrastructure trust, not customer entitlement. Junior Bay's layer still sits in front, unchanged:

```
Customer → Junior Bay → "does this customer own this event?" → YES
         → playback authorization → CloudFront → MediaPackage → stream
```

Which is the whole point of separating entitlement from the delivery mechanism: the mechanism changed and
the commercial layer did not have to.

### ⚠️ Never run a permanent channel per tenant

A MediaLive channel bills **for every hour it is running**, whether or not anyone is watching or streaming.
The lifecycle must be:

```
"Go Live" → provision/start → broadcast → "End Stream" → STOP
```

Three failure modes that follow, and the first is the expensive one:

1. **The forgotten channel.** A tenant clicks Go Live, the workshop ends, nobody clicks End Stream, and the
   channel bills all night. This needs **automatic stop on idle input** and a **hard maximum duration**,
   not a reminder email. Treat a running channel the way you would an unclosed transaction.
2. **Warm-up is not instant.** Starting a channel takes minutes, so "click Go Live and start talking" is
   not the experience without a *preparing your stream* state — and ideally pre-provisioning against a
   scheduled start time.
3. **Delivery spikes.** VOD watch time spreads out; a live audience arrives at once. Same GB, concentrated
   into an hour, which matters for both cost forecasting and the plan limits this must be priced against.

### The barrier is the encoder, not the infrastructure

MediaLive ingests RTMP/RTP. That means the tenant needs **OBS, Streamlabs or hardware** — and a maker
selling handmade goods almost certainly has none of it, nor wants to learn.

**This is the biggest product risk in the live phase, and it is not technical.** Options: accept it and
target tenants who already stream; ship a guided OBS setup; or use a service with browser-based ingest.

Which raises a genuine alternative worth evaluating before committing to MediaLive:

> **AWS IVS (Interactive Video Service)** is designed for exactly this shape — a platform letting *its
> users* stream — bundling ingest, transcoding and delivery as one managed service with far lighter
> operations than MediaLive + MediaPackage, which is broadcast-grade and correspondingly heavy. It is
> likely the better fit for "small tenants go live occasionally"; MediaLive is the better fit for
> scheduled, production-grade broadcast.
>
> Verify current IVS capabilities and pricing against this use case before choosing. The decision belongs
> at the start of the live phase, not after.

### When the stream drops

A tenant's connection dies mid-workshop with fifty paying customers watching. That needs a slate/holding
image, a reconnect window, and — the part that is not infrastructure — **a policy**. Refund? Reschedule?
Replay only? It is a commerce question, so it belongs in the entitlement layer alongside the other
commercial rules, not in the media pipeline.

### Live → VOD is where the branches reconverge

The most commercially interesting piece. MediaPackage can archive a live stream to S3, which is then
exactly the input the VOD branch already takes:

```
Live event → archive to S3 → MediaConvert → HLS → "Masterclass Replay"
```

A tenant runs *"Live Masterclass — Tuesday 7 PM — $29"*, and afterwards the same event becomes a permanent
digital product with no additional work. One recording sold twice, and the second sale needs no new
infrastructure at all — Phase 1 already built it.

MediaPackage also supports time-shifted viewing (pause, rewind, start-over) and DRM integration, so there
is room to grow past "broadcast this video".

### Sequencing

Live continues the phase numbering above rather than starting its own — the first two "stages" of a live
roadmap are simply Phases 1–4, already written:

| Phase | What | Why here |
|---|---|---|
| 1–2 | Video infrastructure + video as a component | Independently useful |
| 3–4 | Courses and learning state | The product the infrastructure was for |
| **5** | **Live events** — schedule, Go Live, MediaLive/IVS, paid audience | Needs an audience and a checkout to be worth anything |
| **6** | **Live → VOD** — the replay as a product | Nearly free once 1 and 5 exist |

The proposition at the end of it:

> **Upload a course. Sell it. Host the videos. Run a paid livestream. Sell the replay. All from one
> storefront.**

Which is a materially larger claim than "we host video".

## Related

- [TODO.md](TODO.md) — "revisit image-processing: utility micro-service vs. a real media service"
- [EXTERNAL_SERVICES.md](../docs/EXTERNAL_SERVICES.md) — the media service contract; records that
  transcoding belongs in `image-processing`, not here
- [PLATFORM_PLANS.md](../docs/PLATFORM_PLANS.md) — the plan tiers this must be priced against
