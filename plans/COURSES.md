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
5. **Build vs buy remains open for Phase 1 only.** Mux / Cloudflare Stream / api.video collapse Phase 1 to
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

## Related

- [TODO.md](TODO.md) — "revisit image-processing: utility micro-service vs. a real media service"
- [EXTERNAL_SERVICES.md](../docs/EXTERNAL_SERVICES.md) — the media service contract; records that
  transcoding belongs in `image-processing`, not here
- [PLATFORM_PLANS.md](../docs/PLATFORM_PLANS.md) — the plan tiers this must be priced against
