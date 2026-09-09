# Font service on published pages

**Status:** SHIPPED. §3a/3b/3c, the catalogue audit, variable upgrades and Latin subsetting (2026-09-07/08);
§9's store-level preference and §10 font import — upload, convert, store, delete (2026-09-09). **The CORS
failure that shaped every decision in this plan is solved — read §12e before anything else here.** Still
open: subsetting for imported fonts, which has nowhere to live until `fontTools` has a home outside
`src/requirements.txt`. Raised 2026-09-03 while checking whether `fonts.juniorbay.com`
carries Inter for the Quote element's opening quotation mark. It does not — but the check turned up
something larger, which is what this plan is actually about.

Sections 1–11 are the ORIGINAL plan, kept as written. **§12 is what actually happened**, including four
findings that cost most of the build time and are worth reading before touching any of this again.

## 1. The finding

**Published landing pages load no webfonts at all.** `src/stripe_link/runtime/html.py` emits no
`@font-face` and no stylesheet link to the font service; its only `<link rel="preconnect">` is for the
hero image host. Meanwhile `font_stack()` happily produces:

    Montserrat,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif

`Montserrat` there only applies if the visitor happens to have it installed locally. On essentially every
visitor's device the page falls through to the system sans — a different typeface on macOS, Windows,
Android and Linux. So a page does not look the same on two devices, which is the actual defect.

The homepage does this correctly already (`homepage/index.html`):

    <link rel="preconnect" href="https://fonts.juniorbay.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.juniorbay.com/?family=Ubuntu%20Titling&family=Roboto&family=Montserrat">

Published pages simply never got the same treatment. Two surfaces of one product, one wired up and one
not — the house pattern again, in a place nobody looked because the fallback silently *works*.

### A second, quieter finding

**Nothing writes `theme.fonts`.** The renderer reads it (`font_stack`, `font_vars`), but no builder
control and none of the 16 theme presets set it. So the font feature is not merely unloaded — it is
unreachable: every page is `family: "system"` today. Wiring the service up without also giving fonts a
home in the presets and/or the builder would change nothing visible.

**Both halves are needed for this to mean anything.** That is the shape of the work below.

## 2. What the service can actually do

Probed directly, 2026-09-03:

| Request | Result |
|---|---|
| `?family=Roboto` | 200 — ONE face, weight 400 |
| `?family=Roboto:400,700` | 200 — TWO faces, Regular + Bold |
| `?family=Roboto:wght@400;700` | **400** — the Google `wght@` syntax is NOT supported |
| `?family=Roboto&family=Montserrat` | 200 — both, repeated params (`|` is not supported) |
| `?family=Inter` | **404** — `Font families not found: Inter` |

Weights available (probed with `:100,300,400,500,600,700,800,900`):

| Family | Weights |
|---|---|
| Roboto | 100, 300, 400, 500, 600, 700, 800, 900 |
| Montserrat | 100, 300, 400, 500, 600, 700, 800, 900 |
| Poppins | 100, 300, 400, 500, 600, 700, 800, 900 |
| Open Sans | 300, 400, 500, 600, 700, 800 |
| Ubuntu Titling | 700 only (a display wordmark face) |
| Inter | not present |

Faces are served from `https://juniorbay.com/fonts/<Family>/<Family>-<Weight>.woff2` with
`font-display: swap` already set by the service. `/fonts/*` is a CloudFront path with CORS configured
(`template.yaml`), which is why the homepage can use it cross-origin.

**Two traps to encode in code, not comments:**
1. Asking for a family WITHOUT weights silently yields regular only, so every heading at 700 becomes
   browser-synthesised faux-bold. The weight list is not optional.
2. The Google-style `wght@` syntax 400s. Anyone copying a Google Fonts URL will break the page.

## 3. Design

**One change reaches both surfaces.** The dashboard's live preview POSTs to `/pages/render`
(`handlers/page_render.py`), which calls the same `render_page()` that publishing does. So emitting the
link inside `render_page` gives the preview and the published artifact identical typography with nothing
to keep in sync — worth stating explicitly, because the preview/published pair is exactly where this
codebase has produced drift before.

### 3a. Emit the link

In the `<head>` builder, from the page's own theme:

    <link rel="preconnect" href="https://fonts.juniorbay.com" crossorigin>
    <link rel="preconnect" href="https://juniorbay.com" crossorigin>     <!-- the faces themselves -->
    <link rel="stylesheet" href="https://fonts.juniorbay.com/?family=<Heading>:<weights>&family=<Body>:<weights>">

- Emit **nothing** when both roles resolve to `system`. A page that wants system fonts must not pay for a
  render-blocking request — and that is every existing page, so this ships as a no-op until 3c lands.
- **De-duplicate**: heading and body are frequently the same family; ask once with the union of weights.
- **Two preconnects**, because the CSS and the `.woff2` files are on different hosts. Missing the second
  costs a whole handshake on the critical path.
- Host in one constant (`FONT_SERVICE_ORIGIN`), not inline — dev/prod may diverge later.

### 3b. Weights, decided rather than guessed

The renderer's own type scale is what dictates the list. Body copy is 400; headings are 700; a few
elements use 600 (the fancy quote's mark, the bragging-points value at 800). Request **400 and 700 for
every family**, plus **600 and 800 when the chosen family offers them**, and no more — each weight is a
separate `.woff2` download. Ubuntu Titling is the exception at 700-only; asking it for 400 must not 404
the whole stylesheet, so the weight list is intersected with a per-family capability map.

That map has to live somewhere. It should be **fetched from the service, not hardcoded here** — a second
copy of what families exist is precisely the drift this codebase keeps paying for. The service has no
listing endpoint today (`/families`, `/list` and `/index.json` all 403), so either:
- **(preferred)** add a listing endpoint to the font service, and cache it in `app-config`; or
- keep a short allow-list in `composition_rules.json` and a test that probes the live service and fails
  when the two disagree. Slower, but it cannot drift silently.

### 3c. Give fonts a way to be chosen

Without this, 3a and 3b are invisible. Smallest useful version:
- Add `fonts: {heading, body}` to the 16 theme presets, so picking a preset picks its typography. This is
  where most of the value is: presets already carry the page's whole visual identity except its type.
- Then, optionally, a font pair picker in Page Settings → Appearance, writing `page.theme.fonts`, which
  the renderer already reads. No schema change — the field has been there all along.

### 3d. Failure behaviour

`font-display: swap` is already set by the service, so text paints in the fallback immediately and swaps
when the face lands. If the service is down the page renders in the system stack — the status quo. The
stylesheet link is render-blocking for CSS but not for text; that is the accepted cost and the reason 3a
emits nothing for system-font pages.

## 4. Build order

1. **3a + 3b** — emit the link, weights included, behind "not system". No visible change yet: every page
   is `system` today, which makes this safe to ship alone and verify by diffing rendered HTML.
2. **3c preset fonts** — the first visible step, and where consistency across devices actually arrives.
3. **Builder picker** — optional, once presets prove the pipeline.
4. **Listing endpoint** — removes the hardcoded family/weight map.

## 5. Consequences worth accepting deliberately

- **A render-blocking request per page.** Mitigated by preconnects, by asking for a minimal weight set,
  and by skipping it entirely for system-font pages.
- **A third-party origin on the critical path.** It is our own origin, but a page that could previously
  not fail on fonts now can. `swap` keeps that to a flash of fallback text.
- **Inter still is not available.** The Quote element's opening mark keeps its system-sans stack until
  Inter is added to the service; that is a change in whichever repo owns `juniorbay.com/fonts/*`, not
  this one. See `QUOTE_MARK_FONT` in `runtime/html.py`.

## 6. The service is a hardcoded catalogue — and it advertises families it cannot serve

Traced 2026-09-03 after the Inter upload 404'd. `fonts-api` (`../fonts-api`) is a separate SAM app whose
families live in `src/font_definitions.py` as 221 literal entries across 30 families, each:

    "montserrat-thin": {
        "format": "woff2", "weight_range": "100", "style": "normal",
        "font_family_name": "Montserrat",      # what the CSS declares
        "folder_name": "Montserrat",           # where the file lives
        "file_name": "Montserrat-Thin.woff2",  # the object key
    }

`src/app.py` serves them from a single `URL = "https://juniorbay.com/fonts"`.

**The catalogue and the bucket have drifted, and the failure is silent.** The API advertises 30 families;
the serving bucket holds THREE:

| Family | `?family=` | file at `/fonts/...` |
|---|---|---|
| Montserrat | 200 | **200** |
| Roboto | 200 | **200** |
| Ubuntu Titling | 200 | **200** |
| Poppins | 200 | **404** |
| Open Sans | 200 | **404** |
| ...25 more | 200 | not present |

So `?family=Poppins` returns perfectly valid CSS, the page loads it without error, every `@font-face`
404s, and the text silently renders in the fallback. No console error a tenant would see, no failed
request a publisher would notice. **Picking one of those 27 families would look exactly like the bug this
whole plan exists to fix** — which makes an allow-list of *actually present* families a hard requirement
of step 3c, not a nicety.

### Where the Inter upload went

Into `s3://juniorbay.com/fonts/Inter/` — a legacy bucket. The live origin for `juniorbay.com` is
**`jb-homepage-prod-150544707159`** (distribution `E1RX3M3RT2BWUZ`), managed by THIS repo's
`template.yaml` and deployed by `deploy/deploy-homepage.sh`. That is why the files exist in S3 and still
404 at the CDN.

Also: the console upload set `Content-Type: application/x-www-form-urlencoded`. `deploy-homepage.sh`
already re-stamps `*.woff2` in the homepage bucket, so moving the files and running it fixes that too.

## 7. Does Inter's 18/24/28pt split limit us? No.

Those are Inter's **optical sizes** — the `opsz` axis flattened into three static families. 3 cuts x 9
weights x 2 styles = 54 files, which is exactly what was uploaded. Each cut is a COMPLETE family
(Thin -> Black, upright and italic).

It does not constrain us, because **the CSS family name is whatever `@font-face` declares** and the
catalogue already separates the three concerns. `Inter_28pt-SemiBold.woff2` can be published as
`font-family: 'Inter'; font-weight: 600` with no renaming at all:

    "inter-semibold": {
        "font_family_name": "Inter", "folder_name": "Inter",
        "file_name": "Inter_18pt-SemiBold.woff2", "weight_range": "600", "style": "normal",
    }

Optionally the split is an ASSET rather than an obstacle: register two families — `Inter` from the 18pt
cut for body and UI, `Inter Display` from the 28pt cut for headlines and the Quote's opening mark. Larger
optical sizes are drawn tighter for exactly that use. Worth doing only if the extra downloads are earned.

### The real constraint is charset weight, not the split

| File | Size |
|---|---|
| `Inter_18pt-Regular.woff2` | 116 KB |
| `Montserrat-Regular.woff2` | 103 KB |
| `Roboto-Regular.woff2` | 64 KB |
| `UbuntuTitling-Bold.woff2` | 17 KB |

These are full-charset (Latin + Greek + Cyrillic + Vietnamese) with no `unicode-range` subsetting — the
service emits one `@font-face` per file and no subsets. Inter at 400+700 is ~235 KB on a landing page
whose whole job is to convert. Google's own Latin subset of Inter is nearer 15 KB per weight.

**So the work Inter actually needs is subsetting, not renaming.** `../font-converter` is a sibling repo
that may already do this; check before building anything. Until then, keep the requested weight list
minimal (400 + 700) and treat any third weight as a real cost.

## 8. Revised build order

1. **Subset Inter to Latin** (or confirm `font-converter` does), then upload the chosen cut(s) to
   `jb-homepage-prod-150544707159/fonts/Inter/` and run `deploy/deploy-homepage.sh` to stamp content-types.
2. **Register Inter in `fonts-api`** `font_definitions.py` — weights 400/600/700 to start.
3. **Prune or flag the 27 phantom families** in the catalogue, or the allow-list in step 3c must exclude
   them. A family that returns CSS pointing at 404s is worse than one that is absent.
4. Then this repo's steps 3a/3b/3c as written above.

---

## 9. Tenant-wide font preference (added 2026-09-07)

A tenant with a strong typographic identity should not re-pick fonts on every page. Add a **font pairing
preference** to user preferences plus an explicit toggle:

> ☐ **Override font presets with these**

### The toggle is the important half

Without it, saving a preference would silently re-typeset every existing page the moment a tenant idly
picked a font they liked. The toggle makes it a decision rather than a side effect, and it is the same
reason presets *propose* fonts rather than owning them (§3).

### Resolution order

Four levels, most specific winning — the same shape already chosen for colour tokens in
`ADVANCED_COLOR_SETTINGS.md`, deliberately, so type and colour do not need two different mental models:

```
system fallback            always present, never fails
  ← preset fonts           the design the tenant picked
  ← tenant preference      only when the toggle is on
  ← page override          an explicit choice on THIS page
```

A page override still beats the tenant default. That matters: a tenant with a house style will still want
one landing page to look different, and they should not have to turn their own preference off to get it.

Storage is `user_preferences` (the table and repository already exist). It holds the pairing and the
toggle; it does not hold anything the renderer reads directly — resolution stays in one place.

## 10. Importing a tenant's own fonts (added 2026-09-07)

### `font-converter` already exists

A sibling service (`../sam/font-converter`, Node 20) already converts uploads with `ttf2woff2` and exposes
an upload endpoint. So this is largely **wiring an existing service in**, not building one — the same
situation as video upload, which turned out to be supported all along.

### ⚠️ The honest constraint: variable in, variable out

**A static TTF cannot be converted into a variable WOFF2.** WOFF2 is a compression container; it does not
add axes that were never in the outlines. `ttf2woff2` makes the file ~30–50% smaller and changes nothing
else.

This is not theoretical — it is exactly what bit us on 2026-09-03. A full Google Fonts TTF set was
converted and every result was static, because **Google ships almost all families as statics**. The
catalogue had been carrying `woff2-variations` entries for months on the assumption that conversion would
produce them; verifying with `fontTools` showed none were variable.

So the tenant-facing behaviour must be:

| Uploaded file | Result | What the tenant is told |
|---|---|---|
| Variable TTF (has `fvar` axes) | One variable WOFF2, full weight range | "One file covers every weight" |
| Static TTF | One static WOFF2 per weight | "Upload each weight you want to use" |

Saying nothing here is the cruelty: a tenant uploads Regular, sees it work, and cannot understand why bold
text is synthetically smeared instead of actually bold.

### Detection must be real, not a string sniff

`font-converter` currently decides with:

```js
fileString.includes('fvar') || fileString.includes('STAT') || filename.includes('variable')
```

That is a substring search over the file's bytes and a filename guess. It can false-positive on arbitrary
byte sequences, it cannot report which axes exist, and a correctly-named static passes it. Proper
detection reads the font's table directory for an `fvar` table and enumerates its axes — which is also
what tells the tenant *which* weight range they actually got.

### Licensing is a real question, not a footnote

A tenant uploading a font they own for **desktop** use does not necessarily hold **webfont** rights, and
the platform would be serving it publicly from its own CDN. Most commercial licences separate the two
explicitly.

At minimum this needs an upload-time affirmation that the tenant holds web-embedding rights, in the same
spirit as the comparison-table reasoning in `TODO.md`: the platform should not host a third-party legal
exposure it never asked about. Worth a lawyer's five minutes before the feature is public.

### Subsetting still applies

An imported font should get the same treatment as a catalogue one: subset to the needed unicode range,
`font-display: swap`, and a metrically-similar fallback stack. A tenant's own font is not exempt from
being the thing that shifts their layout.

## 11. Revised build order (supersedes §8's tail)

1. §8 steps 1–3 — Inter subset, register, prune the phantom families
2. §3a/3b/3c — link the service, then preset fonts
3. **§9 tenant preference + toggle** — small once the resolution order exists
4. **§10 font import** — wire `font-converter` in, with real `fvar` detection and the licence affirmation

Import comes last deliberately: it is the only step with a legal surface, and it is worth nothing until
the pipeline it feeds is proven.

---

## 12. What shipped, and what it cost (2026-09-07/08)

### 12a. Shipped

| | |
|---|---|
| §3a/3b | Pages emit the stylesheet link; weights requested as `Name:400,700` (the service's syntax, **not** Google's `:wght@`) |
| §3c | Per-page picker in Page Settings → Appearance, writing `page.theme.fonts.{role}` |
| §9 (half) | The four-level resolution order is live in `domain/fonts.py`. The tenant-preference **UI** is not built |
| Catalogue | Audited: 34 families, every catalogued file present, **zero** broken entries — §6's "advertises what it cannot serve" is resolved |
| Picker | 11 → **31** families offered |
| Variable | Source Code Pro and Source Sans 3 replaced their static pairs |
| Subsetting | Every pairing cut to Latin: **4,228 KB → 1,344 KB** weighted by preset usage |

Excluded from the picker deliberately, each recorded in `SERVABLE_FAMILIES`: **Themify** (an icon font — 0 of
62 Latin letters map, verified via its cmap; body text would render as glyph soup), **Futura** (a commercial
typeface — a licensing exposure, not a technical one), **Ubuntu Titling** (the Junior Bay wordmark; handing
the platform's own brand type to tenants is a branding decision).

### 12b. The trap that cost the most: `immutable` plus a late CORS fix

Chromium and Firefox refused every font with *"No 'Access-Control-Allow-Origin' header is present"* while
`curl` — **from the same machine, on the same network** — was served the header correctly every time, over
IPv4 and IPv6, coalesced or not, cold cache or warm.

Ruled out, all measured rather than reasoned about: browser cache, CloudFront cache-key/`Vary` poisoning, the
S3 bucket CORS config (there is none — the header comes from a `Managed-SimpleCORS` response-headers policy),
DNS across four resolvers, the TLS certificate, `content-type`, `content-encoding`, HTTP/2 connection
coalescing, HTTP/3, IPv4 vs IPv6, and the WOFF2 files themselves (structurally valid; Safari renders them,
and Safari is the only one of the three that does **not** enforce CORS on fonts).

**The lesson that generalises:** the font files are served `cache-control: public, max-age=31536000,
immutable`. The CORS policy was attached *after* those files had been cached. `immutable` tells a browser
never to revalidate — so a copy stored before the fix stays wrong **for a year**, and no amount of
server-side fixing reaches it. Only a **different URL** does. That is why the service now appends
`?v=FONT_URL_VERSION` to every file URL, and why subset fonts were uploaded under **new filenames** rather
than replacing the originals in place.

**Still unexplained**, and deliberately routed around rather than solved: see §12e.

### 12c. `fs=true` — embedding, and why it is a workaround

`?fs=true` returns the font bytes inside the stylesheet as `data:` URIs. One request, one host, no
cross-origin font fetch for anything to block. It is what made fonts work at all, and it is behind
`FONT_EMBED` in `runtime/html.py` so the referencing form is one edit away.

The cost is real: a `data:` URI cannot be skipped the way `unicode-range` lets a browser skip a file it does
not need, so the charset must be chosen up front. Subsetting is what makes that affordable — before it,
`natural-calm` shipped an **848 KB render-blocking stylesheet**.

### 12d. Measurements worth not repeating

- **Subsetting beats variability, by a lot.** Going variable saved ~1.3× (two files become one); subsetting
  to Latin saved a further ~4.6×. Most of the win is charset, not weight axes.
- **Only 2 of 15 static families have a variable version upstream** (Source Code Pro; Source Sans Pro only
  via its successor **Source Sans 3**, a rename). The other thirteen have no variable cut at all — but they
  subset just as well, so nothing is stuck.
- **Naive subsetting leaves half the win on the table.** Keeping every OpenType feature and all hinting gave
  Merriweather 433 → 200 KB; pruning to the features our CSS invokes (`kern liga clig calt ccmp locl mark
  mkmk rlig`) and dropping hinting gave **433 → 92.9 KB**, matching Google's own Latin cut.
- **Always re-check `fvar` after subsetting.** A careless subset silently flattens a variable font to static,
  which shows up only as faux-bold headings on a published page.
- **Raising webp/woff `effort` is not worth it** — measured at ~2% for 4× the encode time.
- **Inter is genuinely variable** (`fvar`, `wght 100–900` plus `opsz 14–32`). Its PostScript name reads
  `Inter-Regular`, which is the default instance and a red herring; the catalogue's `100 900` is honest.

### 12e. SOLVED (2026-09-09) — the CORS failure was a broken preflight

**Three things had to be true at once, which is why every single-layer check came back clean:**

| | |
|---|---|
| `/fonts/*` used `Managed-SimpleCORS` | its `AccessControlAllowMethods` is **`[]`** — it decorates responses but never answers a preflight |
| the bucket had no CORS configuration | so nothing else could answer one either; `OPTIONS` fell through to S3 and returned **404** |
| `Managed-CachingOptimized`, no origin-request policy | `Origin` was never forwarded, so S3 could not have evaluated a rule even if one existed |

The fix is all three: `Managed-CORS-With-Preflight` on the behaviour, a CORS rule on the bucket, and
`Managed-CORS-S3Origin` forwarding `Origin` and the `Access-Control-Request-*` headers. Verified by the
preflight going 404 -> 200 and referenced fonts then rendering in Chromium and Firefox.

`AllowedOrigins` is `*`, not a list. Pages are served from `*.jbay.be`, `*.jbay.uk` and arbitrary verified
custom domains; an explicit list breaks the first time a tenant adds one.

**Why it took a day: curl never sends a preflight.** Every check ran the request the browser was not
failing on. `GET` returned `200` with `access-control-allow-origin: *` from every origin, over IPv4 and
IPv6, on hits and misses, from the user's own machine — while the browser's `OPTIONS` was 404ing
unobserved. Cache, DNS, TLS, content-type, content-encoding, coalescing, HTTP/3 and the WOFF2 files were
all eliminated, correctly and uselessly, because none of them was ever the question.

**The diagnostic that would have found it in five minutes:**

```bash
curl -i -X OPTIONS "$FONT_URL" \
  -H 'Origin: https://your-page-origin' -H 'Access-Control-Request-Method: GET'
```

The lesson generalises past fonts: when a browser and curl disagree about CORS, **reproduce the browser's
request, not the one you can think of**. A tool that cannot preflight cannot observe a preflight failure,
so agreement between them proves nothing about the half curl does not send.

**What it unwound.** `fs=true` embedding existed only to dodge this. With referencing working, subset fonts
are better referenced: smaller HTML, and one download shared across pages instead of the same bytes inlined
into every one. `FONT_EMBED` in `runtime/html.py` is now `False` and governs both halves — the catalogue's
fonts and a tenant's imported ones — so they cannot disagree again. That disagreement is exactly what made
an imported font invisible in the live preview while presets showed fine.

### 12f. Recurring shape: two homes, no link

Four bugs this build, all the same shape — a value with two homes and nothing forcing them to agree:

1. `APP_CONFIG_TABLE` in template `Globals` vs the IAM grant on one function → config reads failed silently,
   and the platform favicon vanished from every published page.
2. `SERVABLE_FAMILIES` in Python vs the picker list in `LandingPages.vue`.
3. `resolve_families` accepting a bare family string vs `validate_font_settings` requiring `{family}` — the
   lenient half was exercised, the strict half runs first.
4. The rendition ladder in `imageProcessorApp.js` vs `template.yaml`'s `SizesJson` vs `IMAGE_RENDITION_WIDTHS`.

Each is now pinned by a test that **derives** one side rather than restating it — `test_app_config_grants.py`
walks the import graph, `test_font_picker_options.py` reads the `.vue`, `test_rendition_ladder.py` reads the
sibling repo's template. Prefer that over a second hand-maintained list.
