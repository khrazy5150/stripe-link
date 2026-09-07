# Image cropper

**Status:** planned, not built. Raised 2026-09-06.

## What this is

A shared crop / zoom / reposition UI behind **every** image button in the dashboard, so a tenant controls
what part of their photo survives instead of accepting whatever `object-fit` decides for them.

It is **one stack extended and one Vue component** — not a new service. `image-processing-stack` already
owns everything the server side needs; the bulk of the work is front-end.

## Scope, precisely

| Piece | Where | Infrastructure impact |
|---|---|---|
| Crop params + `sharp.extract()` | `image-processing` → `OnDemandResizeFunction` | **None.** One existing function's code |
| Crop modal | `stripe-link` → `dashboard/` | **None.** Static Vite bundle, no backend |
| Storing the rect | `stripe-link` → image metadata sidecar | None |
| `/resize` proxy (only if baking) | `stripe-link` → `handlers/upload.py` | None |

No new bucket, table, distribution, IAM role, or stack. `OnDemandResizeFunction` already has sharp, read on
the source bucket, **write** on the target bucket, the metadata table, the CDN base and immutable cache
headers, at 2048 MB / 30 s. Cropping adds query parameters and one call in a chain that already runs.

## Three modes, because surfaces differ (revised 2026-09-06)

The first cut locked every surface to one ratio. That was wrong for half of them: the page ribbon renders
`height: auto` and has never had a fixed shape, so locking it to 4/3 imposed a constraint the design never
had and silently discarded framing the tenant chose. `image_ratios.json` now takes three forms:

| Entry | Meaning | Example |
|---|---|---|
| a **number** | Locked. The layout demands one shape | `author_bio: 1` — a circular avatar is not negotiable |
| a **list** | The tenant picks | `page_ribbon: ["original", 1, 1.3333, 1.7778]` |
| **null** | The surface accepts any shape | `content_block: null` |

`"original"` means the source image's own ratio: a reframe that zooms and pans without changing shape.

Because a preset or freeform crop's shape cannot be recovered from the rect alone — it is fractions of the
SOURCE, so 0.5 x 0.5 is any shape until you know the source's dimensions — **the cropper records the ratio
it framed at** as `ar` on the crop. Depending on the `image_dims` sidecar instead would make the page wrong
whenever it happened to be missing.

## The core idea: the element declares the ratio, the cropper enforces it

This is what makes one component serve every caller. A crop UI that lets the tenant pick any rectangle
solves nothing on its own — the hero still gets a square photo from someone who cropped square.

Instead each call site declares what it needs:

| Surface | Ratio |
|---|---|
| Author bio photo, marquee logo | `1:1` |
| Hero media, page ribbon | `16:9` |
| Product / offer images | `1:1` |
| **Before / After pair** | one ratio, **both sides locked to it** |

The cropper locks the crop box to that ratio and the tenant moves and zooms within it. The output is then
correct by construction rather than by hope, and the before/after alignment problem stops being a problem
anyone can create.

## The rect is data, not a baked file

**Store the crop rectangle. Do not only bake the output.**

If the rect is persisted, crops are non-destructive: a tenant reopens the modal and adjusts, exactly as
they expect from every tool that has ever offered a crop. If only the derivative is kept, every adjustment
is a re-upload and the framing decision is unrecoverable.

It also buys a genuinely useful intermediate step: with the rect in hand, **CSS can apply the crop with no
backend change at all** — `object-fit` plus `object-position` against the declared `aspect-ratio`. Baking a
derivative through `/resize` then becomes a delivery optimisation for LCP, not a correctness requirement.

### Coordinates must be normalized

Store the rect as fractions of the source (`0.0`–`1.0`), never pixels:

```json
"crop": { "x": 0.12, "y": 0.05, "w": 0.66, "h": 0.44 }
```

Pixel coordinates are bound to one specific rendition of the source. The processor already produces
`thumb`/`small`/`medium`/`large`/`full` derivatives and `/resize` mints more on demand, so a pixel rect is
correct against exactly one of them and silently wrong against the rest. Normalized survives every
rendition, and survives the source being reprocessed. The server multiplies up against real metadata at
the moment it crops.

This lives beside the existing `image_dims` sidecar, which already records `{base: [w, h]}` — the same
shape of per-image metadata, for the same reason.

## Server changes (`image-processing`)

### 1. Fix the cache key FIRST

```js
const destKey = `${baseKey}custom_${width}x${height}.${format}`;
```

The key contains only the output dimensions — not `fit`, and today not a crop. Two different crops at the
same output size would write to the same object, and the CDN would then serve whichever landed last, with
`max-age=31536000, immutable` ensuring it stays wrong for a year.

Hash the full transform (fit + crop rect + format) into the key. **This must ship before any crop
parameter exists**, not alongside it — the collision is silent and the cache headers make it durable.

### 2. Order in the sharp chain is load-bearing

```js
sharp(srcBuf, { failOn: "none" })
  .rotate()                                   // EXIF auto-orientation
  .extract({ left, top, width, height })      // NEW — must come after rotate
  .resize({ width, height, fit, ... })
```

`.rotate()` applies EXIF orientation. The rect the browser computed was measured against the *displayed*
image, which is the post-rotation one. Extract before rotate and portrait phone photos crop the wrong
region — while every landscape desktop test image passes. This is the single most likely way to ship a bug
that survives testing.

### 3. Clamp, do not trust

`sharp.extract()` throws when the rect exceeds the image bounds, and browser rounding will eventually
produce a rect one pixel over. Clamp server-side against real metadata, and reject a degenerate (zero-area)
rect with a 400 rather than a 500.

### 4. Backward compatibility

`/resize` without crop parameters must behave exactly as it does today. That is what lets the service
deploy independently and ahead of the dashboard, with nothing to coordinate.

## Client changes (`stripe-link`)

### The shared component

One `ImageCropper.vue`, used by every image button. Props: the source URL, the required `ratio`, and an
existing `crop` to reopen with. Emits the normalized rect. Interaction is drag to move, slider or wheel to
zoom — the shape of the reference UI.

Its job is the rect. It does not upload, does not know about elements, and does not decide where the value
is stored.

### It should own the file input, which fixes a live bug

```js
function setElementImageInput(id, el) { blurbImageInputs.value[id] = el; }
```

Refs are keyed by `element.id` alone — as are `blurbImageUploading[element.id]` and
`blurbImageErrors[element.id]`. Any element with **two** images collides: the second input overwrites the
first's ref, the spinner shows on both slots, and an error on one displays on both. Nothing hits this today
because no element has two images; Before/After would be the first.

Fixing it inside the shared component is better than keying by `${id}:${field}` in place, because it makes
the collision structurally impossible rather than fixed once.

Note that `handleElementImagePicked(element, event, field = "image_url")` is **already** generalized by
field name, with a comment saying exactly why. The groundwork is there.

### Preview is free

The builder preview is an `<iframe :srcdoc="previewHtml">` fed by the server renderer — there is no Vue
re-implementation of sections. Apply the crop through `object-position` in the rendered CSS and the preview
shows it with no extra work.

## Do we need to proxy `/resize`?

Not for v1. The dashboard reaches image-processing only through `handlers/upload.py`
(`apiRequest("/upload/multiple")` → `call_image_service`), and bytes go straight to S3 on a presigned POST.
The service is never called from the browser.

That matters, because `OnDemandResizeFunction`'s `ALLOWED_ORIGINS` is:

```
http://127.0.0.1:5500, http://localhost:5500, https://images.juniorbay.net,
https://images.juniorbay.com, https://juniorbay.com, https://www.juniorbay.com
```

**Neither `app.juniorbay.com` nor `sandbox.juniorbay.com` is in that list.** A direct call from the
dashboard would be blocked by CORS. So if baking is ever wanted, proxy it through `upload.py` —
`call_image_service` is already a generic helper and this is the established pattern ("this repo proxies
and stores URLs") — rather than widening CORS on a public endpoint.

## Phases

**P1 — cache key.** Hash the full transform into `destKey`. Ships alone, fixes a latent bug, unblocks
everything else.

**P2 — crop on `/resize`.** `crop` parameter, normalized→pixel conversion, `extract()` after `rotate()`,
clamping. Backward compatible, deploys independently.

**P3 — `ImageCropper.vue` + rect storage.** The bulk of the work. Ratio-locked, non-destructive, owns its
own file input. Applied via `object-position`; no derivative baked yet.

**P4 — roll out per surface.** Author bio, ribbon, hero, products, marquee. Each declares its ratio. Do
them one at a time; each is a small diff once P3 exists.

**P5 — bake derivatives** where LCP justifies it, proxied through `upload.py`.

P1 and P2 are in `image-processing`; P3 onward are here. Service first, always — it stays backward
compatible, so there is no window where the two must land together.

## Open questions

1. **Where exactly does the rect live?** Beside `image_dims` on the document, or on the image record in the
   processor's own metadata table? Document-side keeps it with the usage (the same photo could be cropped
   differently in two places, which argues strongly for document-side).
2. **Existing images.** Absent rect must mean current behaviour. No migration; crops appear as tenants
   re-open images.
3. **Does the cropper replace or supplement upload?** Crop-on-upload (forced, like the reference UI) versus
   crop-later (optional, via an edit affordance). Forced is simpler to reason about and gets every image
   framed; optional is less friction. I lean forced-on-upload with re-edit available afterwards.
4. **Zoom beyond 100%.** Allowing upscale produces soft images. Cap zoom at native resolution unless there
   is a reason not to.

## Related

- [EXTERNAL_SERVICES.md](../docs/EXTERNAL_SERVICES.md) — the service contract and its rule of thumb
- [LOCALIZED_IMAGE_URLS.md](LOCALIZED_IMAGE_URLS.md) — the other planned change to the same CDN path
- [BEFORE_AFTER](TODO.md) — the element that raised this, and which deliberately does **not** depend on it
