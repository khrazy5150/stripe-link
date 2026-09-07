# Image cropper

**Status:** P1–P3 **SHIPPED** 2026-09-06 (not yet deployed). P4 in progress — Page Ribbon done, other
surfaces pending. P5 not started.

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

## The core idea: the surface declares what it allows, the cropper obeys

This is what makes one component serve every caller. A crop UI where the tenant picks any rectangle solves
nothing on its own — the hero still gets a square photo from someone who cropped square. A cropper that
picks its own ratio is worse still: the tenant frames a shot and the page silently discards it.

| Surface | Allowance |
|---|---|
| Author bio photo, marquee logo, product | `1` — locked, the layout demands a square |
| Hero media | `1.7778` — locked |
| **Page ribbon** | `["original", 1, 1.3333, 1.7778]` — renders `height:auto`, so the tenant chooses |
| **Before / After pair** | one ratio, **both sides locked to it** — that is what makes them align |

## The rect is data, not a baked file

**Store the crop rectangle. Do not only bake the output.**

If the rect is persisted, crops are non-destructive: a tenant reopens the modal and adjusts, exactly as
they expect from every tool that has ever offered a crop. If only the derivative is kept, every adjustment
is a re-upload and the framing decision is unrecoverable.

It also buys a genuinely useful intermediate step: with the rect in hand, **CSS applies the crop with no
backend change at all**. Not `object-position` — that can only pan, so it cannot express a zoom. The image
is scaled by `1/w` and `1/h` inside a clipped box and offset by `-x/w`, `-y/h`, which puts exactly the
chosen region in view and leaves `responsive_img`'s srcset, lazy loading and intrinsic dimensions intact.
Baking a derivative through `/resize` is then a delivery optimisation for LCP, not a correctness
requirement.

**Any rule that sizes an image inside a cropped box corrupts that geometry.** The ribbon's own mobile rule
(`.sl-page-ribbon .sl-ribbon-media img`, specificity 0,2,1) outranked the crop rule (0,1,1) and clamped the
scaled image, so the crop was wrong on phones while desktop was right only because the two desktop rules
tie and the crop rule happened to sit later in the file. Every croppable container's image rules carry
`:not(.sl-cropped)`.

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

One `ImageCropper.vue`, used by every image button. Props: the source URL, the surface's `ratios`
allowance (number, list, or null), and an existing `crop` to reopen with. Emits the normalized rect plus
the `ar` it was framed at. Drag to move, slider to zoom; the shape picker appears only when there is a
choice to make, since a one-option picker invites the tenant to look for a choice that does not exist.

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

**P1 — cache key. ✅ SHIPPED.** Hash the full transform into `destKey`. Ships alone, fixes a latent bug, unblocks
everything else.

**P2 — crop on `/resize`. ✅ SHIPPED.** `crop` parameter, normalized→pixel conversion, `extract()` after `rotate()`,
clamping. Backward compatible, deploys independently.

**P3 — `ImageCropper.vue` + rect storage. ✅ SHIPPED.** The bulk of the work. Ratio-locked, non-destructive, owns its
own file input. Applied via `object-position`; no derivative baked yet.

**P4 — roll out per surface. ✅ DONE for every surface that should crop.** Page Ribbon, Author Bio and
Content Block are wired. The remaining image surfaces were examined and deliberately excluded — "roll out
to everything" turned out to be wrong:

| Surface | Why not |
|---|---|
| **Client marquee logo** | `object-fit: contain` is deliberate — a logo must show in full. Forcing it into a crop box fights the one thing that rule exists to guarantee |
| **Quote photo** | Two presentations. The *fancy* one positions the photo absolutely at `height: calc(100% + 11.2rem)` to overlap the card; a crop box would break that overlap |
| **Testimonial avatar** | Emitted as a bare `<img>` carrying `order: -1` in the mobile rule. Wrapping it changes flex ordering — a layout change that needs visual checking, not a mechanical edit |
| **Hero media** | Stored as newline-joined URL **strings**, so there is no object to hang a crop on. Wants a URL-keyed sidecar mirroring `image_dims` (`renditionBase()` keying, already proven) — a data-model step, not a wiring one |

The ratio table lists ONLY wired surfaces, and a test renders each one to prove it actually crops. An
entry with no wiring is a lie the cropper cannot detect: the tenant gets a shape picker, frames a photo,
and the page ignores it. Author bio, ribbon, hero, products, marquee. Each declares its ratio. Do
them one at a time; each is a small diff once P3 exists.

**P5 — bake derivatives. ✅ SHIPPED** — but for correctness, not LCP. Asset images (product, service,
landing hero) also feed `og:image` and Product JSON-LD, which are URLs in meta tags no stylesheet can
reach, so a CSS crop would keep sending the uncropped photo to Facebook and Google. `POST /upload/crop`
proxies the resize endpoint; the crop always reads the ORIGINAL by asset id, so a re-crop never compounds
the last one.

**The two mechanisms are not interchangeable**, and the ratio table is grouped by mechanism so a surface
cannot be wired one way and rendered the other:

| | Placement | Asset |
|---|---|---|
| Examples | ribbon, author bio, content block | product, service hero, landing hero |
| Crop applied | CSS clip at render time | baked into a derivative |
| Stored URL | the original | already cropped |
| Renderer | emits `.sl-cropped` | emits nothing |
| Reaches `og:image` | **no** | yes |

Wiring one as the other fails silently in both directions: an asset image clipped again on top of a baked
crop, or a placement crop stored and never applied.

Landing-page hero AUTO slides need nothing — they come from the offer's products, so cropping a product
once means every surface inherits it.

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
4. ~~**Zoom beyond 100%.**~~ **Decided:** capped at native resolution. A small upload therefore has little
   crop range, and the cropper says so rather than offering a slider that does nothing.
5. **Does an unlocked surface want true drag-handle freeform?** Shipped as presets plus "original", which
   covers the ribbon without building resize handles. Revisit only if a surface appears that genuinely
   needs an arbitrary rectangle.

## Related

- [EXTERNAL_SERVICES.md](../docs/EXTERNAL_SERVICES.md) — the service contract and its rule of thumb
- [LOCALIZED_IMAGE_URLS.md](LOCALIZED_IMAGE_URLS.md) — the other planned change to the same CDN path
- [BEFORE_AFTER](TODO.md) — the element that raised this, and which deliberately does **not** depend on it
