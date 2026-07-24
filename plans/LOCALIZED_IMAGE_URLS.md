# Localized (Pretty) Image URLs — Hybrid Edge-Alias Design

**Status: Planned, not built.** Recorded 2026-07-23. Final item of `plans/LOCAL_SEO_SIGNALS.md`
(#5 localized filenames), re-scoped from "rename the stored file" to a **hybrid edge-alias** approach
after discussion. Opt-in, targeted at service/local businesses. Incremental image-pack SEO upside, not a
step-change — the phasing and opt-in framing keep the effort matched to the payoff.

---

## Goal

Serve landing-page images under a **human-readable, locally-anchored URL** —

```
https://images.juniorbay.com/photos/5kJ2mQ9xAbC/full/swedish-massage-luxe-spa-st-george-ut.webp
```

— while the underlying object keeps its opaque, canonical key. The descriptive last path segment is the
"filename" Google reads for Image SEO; the edge maps it back to the real object with **no lookup table**.

## Why

Google's Image SEO guidance lists the image URL/filename as a content signal alongside alt text, surrounding
text, and caption. It's the weakest of those four, BUT it's the one place the NAP + service keywords can live
in the image's own URL — which feeds **Google Images / Image Pack** ranking, a real discovery surface for
service businesses ("emergency plumber near me" frequently returns an image pack). We already ship the three
strong signals (localized alt, `<figcaption>` NAP, LocalBusiness JSON-LD); this completes the set.

## Why the earlier "rename the file" idea was rejected, and why this isn't

The naive version (bake a descriptive name into the stored object at upload) fails because **the anchor is
only known at render time, not upload time**: the same product image appears on a DTC page (no locality) and,
later, a local Site page ("…at Luxe Spa in St. George"). A filename fixed at upload is generic or wrong by the
time it matters. The hybrid **generates the alias at render time** — the slug is computed per page from
`_RENDER_ORG`, the object is untouched — so it's always correct for the page being served. This is the crux
of why the hybrid is the right shape.

---

## Current architecture (grounded)

- Images are produced by a **separate service**: `/Users/morpheus/Documents/Development/aws/sam/image-processing/`.
  It assigns a Base62 Snowflake `id` (`src/id.js`, ~11 chars, URL-safe, time-ordered) and writes variants to
  the `images.juniorbay.net` S3 bucket under key `photos/{id}/{size}.{fmt}` (`DEFAULT_BASE_PREFIX = "photos"`).
- **Size vocabulary is bounded and fixed** (`DEFAULT_SIZES`): `thumb, small, medium, large, full` (+ `original`).
  **Format vocabulary is bounded**: `avif, webp, jpg, png`. This is what makes a stateless edge rewrite safe.
- Served URL = `${CDN_BASE}/${destKey}` → `https://images.juniorbay.com/photos/{id}/{size}.{fmt}`.
- **The CloudFront distribution serving `images.juniorbay.com` is owned by us but is NOT defined in the
  image-processing `template.yaml`** (no `AWS::CloudFront::Distribution` / `::Function` resource there) — it
  was created out-of-band (console). **This is the one real prerequisite** (Phase 0): the alias rewrite has
  to be attached to that distribution. Confirmed live config (inspected 2026-07-23):
  - **Distribution `E16GIH1C3GYFQE`** = `d10mrfiih71pl6.cloudfront.net`, aliases `images.juniorbay.com` +
    `images.juniorbay.net`, origin = `images.juniorbay.net` S3 bucket. `PriceClass_100`, HTTP/2, `Compress: true`.
  - `photos/*` (all landing-page images) is served by the **default cache behavior** → the viewer-request
    function attaches there. No new path behavior needed.
  - **No FunctionAssociations / Lambda@Edge today** — clean slate.
  - Legacy-style config: default behavior uses `ForwardedValues` (not a cache policy), `MinTTL 0 /
    DefaultTTL 86400 / MaxTTL 31536000`, ResponseHeadersPolicy `5249ba1c-…` (CORS). A CloudFront Function
    coexists with the legacy config — **no cache-policy migration required**.
  - One existing behavior `landing-pages/video/*` → a separate videos origin; leave it untouched.
- `stripe-link` stores/render-emits image URLs in that canonical form and does not currently transform them.

---

## Design

### The pretty URL

```
canonical:  https://images.juniorbay.com/photos/{id}/{size}.{fmt}
pretty:     https://images.juniorbay.com/photos/{id}/{size}/{slug}.{fmt}
                                                  └ id kept in place ┘ └ decorative, stripped at edge
```

The `{id}` stays in its exact position, so the canonical key is recoverable by structure alone — no
slug→hash database. `{size}` moves from a filename stem to a directory segment; the descriptive `{slug}`
becomes the actual last segment, which is what Google weights as the filename.

### The edge rewrite (CloudFront Function, viewer-request)

Stateless, ~1 ms, no network. Pseudocode:

```js
// Bounded vocab — anything else falls through untouched (canonical URLs still work).
var SIZES = /^(thumb|small|medium|large|full|original)$/;
var EXT   = /\.(avif|webp|jpg|jpeg|png)$/i;

function handler(event) {
  var req = event.request;
  // /photos/{id}/{size}/{slug}.{ext}  ->  /photos/{id}/{size}.{ext}
  var m = req.uri.match(/^\/photos\/([^/]+)\/([^/]+)\/[^/]+(\.(?:avif|webp|jpg|jpeg|png))$/i);
  if (m && SIZES.test(m[2])) req.uri = "/photos/" + m[1] + "/" + m[2] + m[3];
  return req;
}
```

Both the pretty and canonical URLs resolve to the same object; old links keep working; nothing to migrate.

### `stripe-link` render change

A pure string transform applied only when the Site opts in:

```python
def localized_image_url(url: str, slug: str) -> str:
    # https://…/photos/{id}/{size}.{fmt}  ->  https://…/photos/{id}/{size}/{slug}.{fmt}
    # No-op if url isn't a canonical images.juniorbay.com/photos/{id}/{size}.{fmt} or slug is empty.
```

- Slug is derived at render from the same inputs as `local_business_caption` / `local_business_anchor`
  (business name + locality + product/service), then `slugify`'d (lowercase, hyphen, ASCII-fold, length cap).
- Applied where we emit `<img src>` for indexable imagery — primarily the hero (and optionally gallery).
  Price-card thumbnails etc. can stay canonical.

### Opt-in model

- One boolean on `organization`, e.g. `pretty_image_urls`, **defaulting on for local/service** businesses
  (`_org_is_local`) and off for DTC — mirrors the `review_destination` auto-default-by-business-type pattern.
- Dashboard: a single toggle in the Site editor's Local-business fieldset, recommended copy for service tenants.

---

## Caveats (design-acknowledged)

- **Dual-URL / duplicate image.** One object under two aliases is low-risk but not ideal for image
  canonicalization. Rule: one page → one alias. Only the rare DTC+local dual-use of the same image hits it;
  an image sitemap listing the chosen alias resolves it (Phase 2).
- **Cache: no fragmentation.** A **viewer-request** function runs *before* the cache lookup, so the URI is
  already rewritten to the canonical `{id}/{size}.{fmt}` when CloudFront computes the cache key. Pretty and
  canonical URLs therefore collapse onto **one** cache entry — an argument for viewer-request over
  origin-request timing. (An origin-request function would fragment the cache; don't use it here.)
- **Backfill.** Pretty URLs apply going forward on re-render; already-published pages keep canonical URLs
  until re-published. No migration — consistent with prior render-layer changes.
- **Vocab drift.** If the image service ever adds a new size name, the edge `SIZES` regex must learn it, or
  those pretty URLs 404. Keep the two lists in sync (and document the coupling in both repos).

---

## Phasing

- **Phase 0 — Edge infra (prerequisite).** Add a **viewer-request** CloudFront Function to the **default
  cache behavior** of distribution `E16GIH1C3GYFQE`. Decide first whether to **import that distribution into
  IaC** (image-processing stack) or apply the function via console + document it. Verify canonical URLs still
  resolve and pretty URLs rewrite. Low risk: no existing function to displace, and it coexists with the
  legacy `ForwardedValues` config (no cache-policy migration). Don't touch the `landing-pages/video/*` behavior.
- **Phase 1 — Render + opt-in.** `localized_image_url` + slug derivation in `stripe-link`, the
  `organization.pretty_image_urls` flag (validated, auto-default-by-type), the dashboard toggle, and apply to
  the hero image. Tests: transform correctness, no-op on non-canonical URLs, opt-out stays canonical.
- **Phase 2 — Polish.** Extend to gallery images if warranted; emit an image sitemap listing the canonical
  alias per image; optionally normalize the CloudFront cache key to fold aliases onto one entry.

## Open questions / prerequisites

1. **IaC the images distribution?** It's currently console-managed. Cleanest is to import it so the function
   is version-controlled; acceptable interim is console + a documented runbook. (Decision gates Phase 0.)
2. **Slug source of truth.** Business name + locality come from `_RENDER_ORG`; the product/service term from
   the offer/product. Confirm the term we want leading the slug (service name vs product name) per page type.
3. **Scope of application.** Hero-only (recommended start) vs hero + gallery.

## Ties

`plans/LOCAL_SEO_SIGNALS.md` (#5, this doc completes it), `[[project_local_seo_signals]]`,
`[[project_business_profile_gbp]]` (org identity / NAP), the image-processing service (key scheme + the
distribution the edge function lands on).

---

## Answered design questions (2026-07-23)

1. **Does the edge rewrite affect video?** No. Videos are served by the distribution's separate
   `landing-pages/video/*` behavior (its own origin, no function association); CloudFront only runs the
   function on the *matched* behavior, and ours attaches to the default (`photos/*`) behavior. The regex is
   photos-only besides. **Future option:** a parallel rewrite on the video behavior for `VideoObject` / video
   sitemap SEO — additive, out of scope here.
2. **Opt-in, not default?** Yes, by design. The edge function is a **no-op on canonical URLs** (only rewrites
   URLs already in pretty form), so deploying it changes nothing until a consumer opts in. The opt-in lives in
   the **render layer** (`organization.pretty_image_urls`, auto-default-on for `_org_is_local`) because the
   localization is page-contextual — the slug is built at render, nothing baked at upload. An image-service
   API `slug` param (for a context-independent product-name slug) is a possible later convenience, not required.
3. **Where does the opt-in belong?** Render layer (see #2), not the upload API.

---

## Appendix — Media API custom domain (`media.juniorbay.com`) — SEPARATE, DECOUPLED TASK

Not part of the localized-URL feature; recorded here because it came up together. Renames the **upload/status
API endpoint** (not the image CDN) from the raw `https://dph4d1c6p8.execute-api.us-west-2.amazonaws.com/v3`
to `https://media.juniorbay.com/v3`. Independent of the edge function; can execute in either order, anytime.

**Grounded facts:**
- The API is a **regional HTTP API** (`AWS::Serverless::HttpApi`, stage `v3`) in the image-processing stack.
- The stripe-link consumer is already indirected: `IMAGE_UPLOAD_API_BASE` env (stripe-link `template.yaml`,
  ~L761) overrides the hardcoded default in `src/handlers/upload.py:8`. Consumer switch = one-line env change,
  instantly reversible.
- **`juniorbay.com` DNS is on Route 53** (confirmed) → cert validation + the domain record can be fully
  automated in the SAM template; no manual DNS steps.

**Work (image-processing repo):**
1. ACM cert for `media.juniorbay.com` in **us-west-2** (HTTP APIs are regional-only — NOT us-east-1).
   DNS-validated via Route 53.
2. Custom domain + mapping via SAM's `Domain:` property on the `HttpApi` resource (creates
   `ApiGatewayV2::DomainName` + API mapping + Route 53 alias in one shot).
3. **Keep `/v3` as the base path** → `https://media.juniorbay.com/v3/...`, so the consumer change is a pure
   hostname swap and the version namespace is preserved. (Root-mapping to drop `/v3` is prettier but changes
   path shape and loses the version segment — not worth it.)

**Work (stripe-link repo):** set `IMAGE_UPLOAD_API_BASE` (template.yaml) and the `upload.py` default to
`https://media.juniorbay.com/v3`.

**Cutover (zero downtime, instant rollback):** custom domain is additive — the `execute-api` URL keeps
working. (1) Deploy the domain in image-processing, (2) verify `https://media.juniorbay.com/v3/upload/...`,
(3) flip the stripe-link env var + redeploy, (4) revert the env var if anything's off.

**Status: agreed to plan, execution timing TBD.** Note the two distinct hostnames stay meaningful:
`media.juniorbay.com` = the media *API*; `images.juniorbay.com` = asset *delivery* CDN.
