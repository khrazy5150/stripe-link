# Video transcode and adaptive delivery

Status: **proposed** (design only — no code yet). Direction from the author 2026-11-15, with a pipeline
diagram this document follows exactly:

```
Upload (MP4 / MOV / WebM …) → S3 (private original) → AWS Elemental MediaConvert (1080p / 720p / 480p)
  → S3 + CloudFront (HLS) → Junior Bay Video Player (automatic quality selection)
```

That is the standard AWS VOD pipeline and it is the right shape. What follows is what it costs, where each
piece lives, and the three things that are not obvious from the diagram.

## 1. It spans two repositories, and most of it is not this one

`CLAUDE.md` is explicit: **stripe-link does not store or process media.** Upload is proxied to
`../image-processing`, which already presigns video (`mediaType: "video"`), stores originals and fronts
them with a CDN. So:

| Piece | Repo |
|---|---|
| S3 private original, MediaConvert job, HLS output, CloudFront | **`../image-processing`** |
| Job status / "is this recording ready" | `../image-processing`, read through the existing poll |
| The player, quality selection, the broadcast seek rules | **stripe-link** (`runtime/html.py`) |
| Refusing to schedule a session whose recording is not ready | stripe-link (Events screen) |

**Deploy footgun, carried over from `docs/EXTERNAL_SERVICES.md`:** never plain `sam build` that stack from
a Mac. It ships a macOS `sharp` binary and breaks *every image upload* — empty urls and "Image not found",
with no error. Use `--use-container`.

## 2. What the diagram does not show

**HLS does not play in Chrome, Firefox or Edge without a library.** Safari and iOS play `.m3u8` natively;
nothing else does. "Junior Bay Video Player with automatic quality selection" therefore means `<video>`
plus **hls.js**, and that is a new client dependency on *published tenant pages*, which today carry no
external JS at all. Load it only on a page that actually has a player, and keep `<video src="…mp4">` as
the fallback when `Hls.isSupported()` is false — a webinar that fails to start is a missed event.

**MediaConvert is asynchronous, and slow relative to a session.** A job runs roughly 0.5–2× realtime, so a
90-minute recording can take 30–90 minutes to package. A tenant who uploads an hour before their webinar
may have nothing to play. This is the operational consequence worth designing for, not the transcode
itself: the Events screen must show a recording's state, and scheduling a sitting whose recording is not
`ready` should be refused or loudly warned. The sibling stack already polls job status for images
(`getStatus.js`, `pollVideoUrl`), so the pattern exists.

**Transcode is cheap and one-off; DELIVERY is the cost that scales.** Rough figures, worth checking against
current pricing before committing:

| | Rough cost |
|---|---|
| MediaConvert, 3 renditions of a 90-min recording | ~270 output-minutes ≈ **$2–4, once per recording** |
| CloudFront egress, 90 min at ~1.5 Mbps (720p) | ≈ **1 GB per attendee** |
| …100 attendees | ≈ 100 GB ≈ **$8–9 per sitting** |

So the transcode bill is noise and the **egress bill is the business model**. A tenant running a weekly
auto-webinar to 500 people is ~$45/session in bandwidth alone. That belongs in the pricing conversation
before this ships, not after — see [[project_pricing_model_pivot]].

## 3. Locked decisions

- **Accept what the diagram accepts, normalise to one thing.** MP4, MOV and WebM in; HLS (H.264/AAC) out.
  Accepting MOV becomes *safe* only once there is a transcode — today it is accepted by one picker and
  refused by the uploader, which is why that mismatch was just fixed rather than widened.
- **The original is private and never served.** Only MediaConvert reads it. Today's pipeline serves the
  original bytes as-is, which is exactly the fragility this removes.
- **The ladder is 1080p / 720p / 480p**, per the diagram. 360p is worth adding only if attendance data
  shows it is needed; every rendition is transcode cost and storage on every recording.
- **Playback stays a broadcast.** The seek rules already shipped (`AUTO_WEBINAR.md`) do not change: the
  island seats the player at the live edge and snaps back on a forward seek. Adaptive bitrate changes the
  *quality* a viewer gets, never their position.

## 4. Phases

1. **T1 — transcode in the sibling stack.** MediaConvert job template, triggered on a video landing in
   the source bucket; HLS output to the delivery bucket; job state readable through the existing status
   path. Nothing in stripe-link changes.
2. **T2 — the player.** hls.js, loaded only on a page with a player, with the MP4 fallback. The existing
   broadcast seek rules sit on top unchanged.
3. **T3 — readiness.** Recording state on the Events screen; refuse or warn when scheduling a sitting
   whose recording is not ready.
4. **T4 — the old originals.** Everything uploaded before T1 is a bare MP4/WebM with no HLS. Decide
   whether to backfill or to let `video_url` mean "pre-transcode original" indefinitely. Leaving both
   shapes live forever is the thing that will rot.

## 5. Open questions

- **Who pays the egress?** See §2. This is the one that should be answered before T1, because it may
  change the ladder, the default rendition, or whether auto-webinars are a paid-tier feature at all.
- **Signed playback URLs?** A paid webinar's recording sitting on a public CloudFront path is downloadable
  by anyone who reads the manifest. CloudFront signed cookies are the usual answer and are not free to
  build.
- **Does the tip-jar/landing `video` element share this pipeline?** It should, eventually — the same
  format fragility applies to any tenant video. Out of scope here, but the T1 trigger should not assume
  the only caller is a webinar.
