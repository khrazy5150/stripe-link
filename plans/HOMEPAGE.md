# HOMEPAGE.md — the public juniorbay.com marketing site

The public, SEO-facing homepage at **`https://juniorbay.com`** (apex) — a **sales page for the Junior Bay platform**
(this repo). Its only job: get a visitor to **start a free trial** or **sign in**; everything about "how much / which
plan" lives *inside* the app. Design/copy details are discussed separately; this doc locks the architecture.

## Decisions (locked)

### Where it lives — THIS repo, isolated deploy
Hosted in the `stripe-link` repo, **not** a separate project. It's an extension of the product (its content *is* the
product), and it reuses infra we already own: the `juniorbay.com` Route 53 zone, the ACM cert `1a72b7c6` (whose SANs
include the **apex** `juniorbay.com`, not just `*.juniorbay.com`), the `/legal/*` pages, and `app_config.legal`.
Deploy stays **isolated** — its own bucket + CloudFront distribution + deploy script — so editing marketing copy can
never touch the dashboard or backend.

### Tech — PLAIN static HTML/CSS/JS (no framework, no build)
It's an SEO-critical marketing page, so the content must be **real static HTML** (crawlable, fast first paint, top
Core Web Vitals) — never a client-rendered SPA. **No dynamic content**, so no framework and **no build step**: just
`index.html` + `css/` + `js/` + `images/` synced to S3. (Pricing is deliberately not shown here — see below — which
is what keeps the page fully static; live plan data lives in the Vue dashboard.)

### Folders (after the pending cleanup — see Prerequisite)
- `homepage/` — this static site.
- `dashboard/` — the Vue dashboard (renamed from `dashboard-vue`).

### Serving / deploy
- New `template.yaml` resources (mirroring the dashboard pattern): `HomepageBucket`, `HomepageOriginAccessControl`,
  `HomepageDistribution`, `HomepageBucketPolicy`, and a Route 53 **apex** alias `juniorbay.com` → the distribution.
  Gated on a param (prod only; sandbox/staging need no marketing front).
- Cert: reuse the existing us-east-1 `*.juniorbay.com`/apex wildcard `1a72b7c6` (already covers the apex).
- `deploy/deploy-homepage.sh`: `aws s3 sync homepage/ s3://<bucket>/ --delete` + CloudFront invalidation. **No `npm`,
  no build** (contrast `deploy-dashboard.sh`, which builds Vite first).

### CTAs & routing
- **"Start your free 14-day trial — no credit card"** → `https://app.juniorbay.com` (registration).
- **"Sign In"** → `https://app.juniorbay.com` (login).
- These are single, stable URLs — fine to hardcode in a marketing page (the prod dashboard host).
- **Sandbox / future staging are NOT linked from the homepage** — they're reached directly.

### Pricing — hint, don't show
No pricing table (prices/fees will change; and trial-first converts better with a no-card trial). But **do** signal
affordability so "no price" doesn't read as "expensive." Approved copy:
> **Start your free 14-day trial** — no credit card. *It costs less than your coffee habit.*

Rule for future edits: **keep the money hint vague — no hard numbers, no fixed counts** ("four coffees" pins ~$9 and
breaks on a price change). Vague-but-cheap survives repricing. Full pricing is revealed **inside the app** (the
dashboard reads the live `PlatformPlansTable`).

### Footer / legal / identity
- Footer links **Terms / Privacy / Refund** → the existing **`/legal/*`** pages (config-driven via `app_config.legal`).
- Company name/address/email come from the same `app_config.legal` (one source — see `docs/APP_CONFIG.md`).

### SEO baseline
Real static HTML with: unique `<title>` + meta description, Open Graph + Twitter tags, `Organization` JSON-LD,
`sitemap.xml`, `robots.txt` (index,follow — this is the ONE juniorbay.com surface that SHOULD be indexed), a real
`<h1>`, descriptive `alt`, and a fast, image-optimized hero. Favicon from the asset CDN (`public_asset_base_url`).

## Done already
- **Front-end cleanup (2026-08-24):** retired the legacy plain-JS `dashboard/` folder and `git mv dashboard-vue →
  dashboard` (dropping the `-vue` suffix; the new marketing folder will be `homepage/`). Updated the one functional
  reference (`deploy/deploy-dashboard.sh`), the npm package name, the `/dashboard/` `.gitignore` line, and the doc
  mentions. Build verified.
- The old `frontpage/dot-com` classifieds app was relocated to `frontpage/dot-net` (for a future `juniorbay.net`);
  the retired travel test was discarded. The homepage is built here, not in the frontpage project.

## To discuss (the actual homepage — details)
- Sections/layout (hero, value props, proof/social proof, how-it-works, FAQ, footer) and the copy.
- Visual design / brand (colors, type, hero imagery).
- Analytics (which tool), a contact/about page, and whether a lightweight build (minify/bundle) is worth it later.
