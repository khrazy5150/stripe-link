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

### Brand / design system (provided 2026-08-24)
- **Colors:** background **`#0b5294`** (deep blue) · accent **`#ff8309`** (orange) · text **`#fffff1`** (cream/off-white)
  · **Free-trial button `#ffce47`** (gold) with **`#000000`** text on it.
- **Fonts — via `fonts.juniorbay.com`** (a Google-Fonts-style CSS service; **repeated `family=` params**, `|` fails):
  `<link rel="stylesheet" href="https://fonts.juniorbay.com/?family=Ubuntu%20Titling&family=Roboto&family=Montserrat">`.
  - **Wordmark** ("Junior Bay") → `'Ubuntu Titling'` — **note: the family name has a SPACE** (`Ubuntu Titling`); the
    hyphen form `Ubuntu-Titling` the service does NOT recognize. **Headlines** → `'Roboto'`. **Body** → `'Montserrat'`.
  - **⚠️ Build dependency:** the service's `@font-face src` points at `https://juniorbay.com/fonts/…woff2` — the apex,
    where the homepage lives. Ensure `/fonts/*.woff2` keeps resolving after cutover (bundle the fonts into the homepage
    bucket, or a CloudFront behavior). Add `preconnect` to `fonts.juniorbay.com` **and** `juniorbay.com`.
- **Wordmark treatment:** "**Junior**" in the text color (`#fffff1`) + "**Bay**" in the accent (`#ff8309`), set in
  `Ubuntu Titling`.
- **Logo / favicon:** `https://images.juniorbay.com/icon/favicon.png` (via `public_asset_base_url`).
- **Hero image:** the provided photo — a creator live-selling her own product (baking kits) to an audience; frames the
  positioning (turn your audience into a store). *Asset to place in `homepage/images/` at build.*

### SEO baseline
Real static HTML with: unique `<title>` + meta description, Open Graph + Twitter tags, `Organization` JSON-LD,
`sitemap.xml`, `robots.txt` (index,follow — this is the ONE juniorbay.com surface that SHOULD be indexed), a real
`<h1>`, descriptive `alt`, and a fast, image-optimized hero. Favicon from the asset CDN (`public_asset_base_url`).

## Done already
- **Page built — Track A copy + Track B scaffold (2026-08-24):** `homepage/` static site created —
  `index.html` (hero → 3 value props → **"A better link-in-bio" capability-orbit infographic** → 3-step
  how-it-works → **"Everything you need to start selling" checklist + CSS storefront mockup** → trust strip →
  final CTA → footer), `css/style.css` (brand kit applied), `robots.txt`, `sitemap.xml`, `images/` (README).
  Header has logo mark + in-page nav (Features / How it works). Two CSS-only product mockups (phone-store in
  the infographic, browser-store in the checklist) — no image assets, on-brand, re-themeable. Capability
  bubbles are **only real JB features** (no Courses/Webinars/Affiliate — Stan has them, we don't). **Approved copy:**
  hero H1 *"Turn your audience into a storefront."* + coffee-habit money hint; trust strip **replaces** a
  testimonials/"proof" block (pre-launch — no real customers to quote; add later). Wordmark uses `Ubuntu Titling`
  (space, weight 700), headlines `Roboto`, body `Montserrat`. **Still to do:** (1) bundle the hero photo at
  `homepage/images/hero.jpg`; (2) Track B infra — `deploy/deploy-homepage.sh` + `template.yaml`
  `HomepageBucket`/`Distribution`/apex Route 53; (3) wire `/legal/*` + `/fonts/*` to resolve on the apex.
- **Track B — deploy infra BUILT (2026-08-24, NOT yet deployed):** `template.yaml` gained `HomepageEnabled`
  + `HomepageCustomDomain{Name,CertificateArn,HostedZoneName}` params, `HasHomepage`/`HasHomepageApex`
  conditions, and resources `HomepageBucket` / `HomepageOriginAccessControl` / `HomepageDistribution`
  (S3 default origin + `/legal/*` → API custom origin) / `HomepageBucketPolicy` / `HomepageApexRecord` +
  `HomepageWwwRecord`, plus outputs. `deploy/deploy-homepage.sh` (sync + invalidate, no build) and
  `homepage/404.html` added. **Fonts bundled** into `homepage/fonts/{Ubuntu,Roboto,Montserrat}/…woff2` at the
  exact `/fonts/*` paths the font-service `@font-face` points to (verified they live in the old apex S3 bucket
  today). Cert **1a72b7c6 verified to include the bare apex SAN** (not just the wildcard). Template validates.
  **Cutover choreography (apex is a toggle — `HomepageCustomDomainName`):**
  1. *Phase 1* — deploy with `HomepageEnabled=true`, apex param empty → dist serves on `*.cloudfront.net`;
     upload via `deploy-homepage.sh` and verify site + `/legal/*` + `/fonts/*`. Zero impact on live apex.
  2. *Phase 2* — the old apex dist **E1VGTULTFA3BO3** (separate project; origin = `juniorbay.com` S3 bucket,
     us-west-2) still holds `juniorbay.com` + `www`. CloudFront forbids the same CNAME on two dists, so
     **free those aliases off E1VGTULTFA3BO3 first** (or `aws cloudfront associate-alias`), then set
     `HomepageCustomDomainName=juniorbay.com` + cert `1a72b7c6` + zone and redeploy → claims apex+www alias
     and Route 53 A-records. Old classifieds app moves to juniorbay.net separately.
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
