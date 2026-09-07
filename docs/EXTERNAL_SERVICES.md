# External services stripe-link depends on

These are **separate repositories/deployments**. Nothing in this repo builds or deploys them, and the
only trace of them here is a hardcoded API base URL — which makes them easy to miss. Check here before
concluding a media capability "doesn't exist".

---

## Image / video processing — `../sam/image-processing`

**Repo:** `sam/image-processing` (sibling of this one)
**API base:** `IMAGE_UPLOAD_API_BASE` env on `UploadFunction` (`template.yaml`), currently
`https://dph4d1c6p8.execute-api.us-west-2.amazonaws.com/v3`
**CDN:** `images.juniorbay.com` (console-managed distribution — see `plans/LOCALIZED_IMAGE_URLS.md`)
**Proxied by:** `src/handlers/upload.py` — a thin pass-through. stripe-link stores NO media itself.

### What it does

| Endpoint | Purpose |
|---|---|
| `POST /upload` | Mint a **presigned PUT** (or multipart above `SINGLE_PUT_MAX`, default 9 MB) for one file. Takes `mediaType` (`photo` \| `video`), `fileName`, `mime`, `sizeBytes`. Returns `{id, upload:{putUrl}, expectedUrls}`. |
| `POST /upload/multiple` | Batch image upload. **The only endpoint stripe-link proxies today** (`create_upload`). |
| `GET /upload/status/{id}` | Processing status. Already proxied (`get_upload_status`). |
| `POST /upload/from-url`, `POST /reprocess/{id}`, `GET /resize/{id}/{dims}`, `DELETE /delete/{id}` | Not proxied. |

### VIDEO IS ALREADY SUPPORTED — do not rebuild it

Verified 2026-08-30 after nearly building a parallel video pipeline in this stack:

1. `POST /upload` with `mediaType: "video"` → `src/lib/plan.js` routes to the `videos/` prefix with
   `PRIMARY_VIDEO_EXT` (mp4) and maps `mp4`/`mov` content types.
2. Client PUTs the bytes straight to `putUrl` (S3), never through stripe-link.
3. The processor's non-image branch (`src/imageProcessorApp.js:170`) copies the original to the
   CDN-backed target bucket and writes `status: "complete"` with `urls.original`.
4. `GET /upload/status/{id}` then reports complete with the public CDN URL.

### Size limits live in that stack, not here

`MaxUploadBytes` (photo, default 100MB) and `MaxVideoUploadBytes` (video, default 500MB) are CloudFormation
**parameters** on `image-processing-stack`. The per-upload ceiling is baked into the presigned POST's
`content-length-range`, so S3 enforces it, and it is returned as `maxBytes` in the presign response.

**Never hardcode an upload limit in this repo.** `uploadVideo` reads `maxBytes` off the presign response,
so raising the ceiling for course video is a stack parameter update — no dashboard build, no release.

**No transcode.** The original is served as-is (`PRESERVE_SOURCE_FOR`). Practical consequence: prefer
`video/mp4`; a large `.mov` from a phone will play inconsistently and is bad for page speed. If
transcoding is ever wanted, it belongs in that repo, not this one.

### NEVER plain `sam build` that stack from a Mac

Learned the hard way on 2026-09-06, by taking the whole image service down.

`sharp` resolves a platform-specific binary at install time. `sam build` on macOS packages
`@img/sharp-darwin-x64`, which cannot load on Lambda — **every** function in that stack shares `CodeUri:
src/`, so all ten start throwing `Could not load the "sharp" module using the linux-x64 runtime` on their
next invocation. Uploads, processing and resizing all stop.

Nothing in the normal loop catches it. `sam build` exits 0. The unit tests pass — they deliberately never
load sharp, because a platform-specific binary will not load on a dev machine at all. The only evidence
lives inside the package.

```bash
cd ../image-processing
sam build --use-container --parallel   # resolve deps in the RUNTIME image, not the laptop
npm run verify:build                   # fails if any package lacks sharp-linux-x64
sam deploy --no-confirm-changeset
```

`npm run verify:build` exits non-zero and names the offending functions, so it can gate a deploy. Run it
between build and deploy every time — the failure is invisible until production traffic hits it.

### Rule of thumb

Media storage/processing lives in `image-processing`. This repo proxies and stores URLs. Before adding a
bucket, a distribution or a MediaConvert pipeline here, check whether that service already does it.

---

## Other sibling projects (context, not dependencies)

`sam/stripe-cart` is the legacy behavioural reference (see `CLAUDE.md`). `sam/ai-video-generator` and
`sam/social-media-downloader` are unrelated to tenant media upload.
