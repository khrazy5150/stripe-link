# Font service on published pages

**Status:** planned, not built. Raised 2026-09-03 while checking whether `fonts.juniorbay.com` carries
Inter for the Quote element's opening quotation mark. It does not — but the check turned up something
larger, which is what this plan is actually about.

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
