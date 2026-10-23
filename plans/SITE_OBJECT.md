# The Site Object — Architecture Decision Record & Plan of Action

**Status:** Approved design (consensus reached 2026-07-20). Not yet built.
**Supersedes:** the routing-only `schemas/Site.schema.json` (v1, unbuilt).
**Companions:** `schemas/Site.schema.json` (v2), `plans/SITE_MIGRATION.md`, `plans/SITE_EXAMPLES.md`,
`plans/ON_PAGE_SEO_REQUIREMENTS.md`, `plans/TENANT_PROFILE_REQUIREMENTS.md`.

---

**Status audited against the code 2026-10-23.** Every "SHIPPED"/"COMPLETE" claim below was re-checked
rather than trusted; what changed is recorded inline with the date. Corrections made in that pass: Phase 2.4
was describing a per-Site sitemap that in fact held one URL until 2026-10-22; Phase 2.6b listed a www↔apex
redirect as remaining when it had shipped; §2.3 omitted the two gates (Stripe mode, thin content) that were
added after it was written; and two of §6's open sub-questions were already answered. Placeholder hostnames
that never existed (`*.juniorbay-sites`) were replaced with the real `jbay.uk`/`jbay.be`.

## 1. Context & problem

The platform grew as "a landing-page builder." A **Page** ended up carrying responsibilities that were never
its job: the domain, routing, SEO defaults, canonical URLs, analytics, legal links, navigation, integrations.
At the same time the tenant's **public identity** got smeared across three documents — `tenant_profile`
(`business_name` + a `brand{}` block), `user_profile.business` (a NAP block added as an interim), and the
unbuilt Site's `seo_defaults`. On-page SEO Phase 1 shipped with *interim* canonical/seller URLs precisely
because there was no home for a tenant's canonical root domain or a single Organization identity.

Two different problems were being solved with duct tape:

1. **A modeling problem:** there is no object that represents "a website." Pages are isolated documents.
2. **An SEO/reputation problem:** search engines want to know *who publishes this page* and *on what domain*,
   and the answer must be the tenant — not the platform.

The Site object solves the modeling problem first. Getting that right happens to unlock most of the SEO work.

---

## 2. Decision

**Introduce `Site` as the public aggregate root.** In DDD terms, everything that exists *publicly* lives under
a Site. The Tenant becomes an internal account object.

```
Tenant   — owns        billing, users, roles, permissions, Stripe account
  └── Site — routes    hostname(s), Organization, branding, navigation, SEO,
      │                 analytics, integrations, sitemap, robots, indexing
      ├── Page — renders   sections, layout, an Offer reference, page role
      └── Page — renders   ...
Offer    — supplies    products, pricing, CTA, conversion logic  (tenant catalog, referenced by pages)
```

Four crisp responsibilities:

| Object | Owns | Is |
|---|---|---|
| **Tenant** | billing, users, roles, permissions, Stripe/Connect | *internal* account |
| **Site** | hostname(s), Organization identity, branding, navigation, SEO, analytics, integrations, sitemap, robots, indexing eligibility | *the public website* |
| **Page** | sections, layout, overrides, an Offer reference, a page **role** | *a destination* |
| **Offer** | products, pricing, CTA, conversion logic | *the commerce contract* |

**The Site owns the hostname — not the Tenant.** A Tenant may own several Sites (Main Store, Clearance,
Wholesale, Repair Center) under one billing account. The public entity graph (Organization, seller, canonical)
is anchored to the **Site**, which is anchored to a **hostname**, which is ideally the tenant's own domain.

### 2.1 Organization is the single source of truth (the biggest win)

The Site carries **one explicit `organization` object**. Every entity claim on every page derives from it:

- `Organization` / `OnlineStore` / `LocalBusiness` JSON-LD
- `Offer.seller` attribution (with `@id` → the Site's canonical origin `#organization`)
- Breadcrumb publisher, `WebSite` node, ContactPage, About page
- The `<title>` suffix / brand label, the footer identity, NAP everywhere

One place to edit, one entity for search engines to consolidate. This retires the `tenant_profile.brand` /
`user_profile.business` / `seo_defaults.structured_data` fragmentation (see `SITE_MIGRATION.md`).

Only **verifiable** fields are emitted. We never fabricate a `foundingDate`, a rating, or a claim the tenant
didn't state — same rule as Product JSON-LD.

### 2.2 The hosting model: platform hostname + custom domain, both retained

Every Site has a **permanent, tenant-chosen platform hostname** (`axel-mart.jbay.uk`, `.jbay.be` in sandbox) and an
optional **custom domain** (`axelmart.com`). The platform hostname never disappears or gets recycled — it
backs previews, rollbacks, migration, disaster recovery, and support. The **canonical** hostname is the custom
domain once connected; until then it is the platform hostname.

```
hosting: { type: "platform", platform_hostname: "axel-mart.…", custom_domain: null }
              ↓  connect + verify
hosting: { type: "custom",  platform_hostname: "axel-mart.…", custom_domain: "axelmart.com" }
```

Because the Site owns the hostname, connecting a custom domain updates **one field** and every canonical, every
`og:url`, every Organization `@id`, every Product `seller`, every sitemap URL switches automatically.

### 2.3 Indexing & reputation model (consensus: strict)

**Reputation attaches to the registrable domain (eTLD+1), not to JSON-LD.** Putting unmoderated third-party
commercial content on the platform's own domain at scale is the "site reputation abuse" fact pattern that
`TENANT_PROFILE_REQUIREMENTS.md` §2 flags as existential. Therefore:

- **Everything on platform infrastructure is `noindex,nofollow`** — the S3/CloudFront artifact URL *and* the
  `*.jbay.uk` / `*.jbay.be` platform subdomain. The platform host is a functional preview/starter host, never
  indexed.
- **A Site becomes index-eligible only when BOTH hold:** (a) it has its **own custom domain** (its own eTLD+1),
  verified; and (b) the tenant's **Stripe Connect account is verified** (`charges_enabled`, not merely OAuth-
  connected). This is TP-06 + TP-08: a real domain boundary *and* a KYC'd business relationship.
- **Free tenant hosting never shares a registrable domain with platform marketing** (`juniorbay.com`). If free
  sites need discoverability later, they get a dedicated hosting domain with no platform content (TP-11).

`Site.indexing.eligibility ∈ {blocked, pending, eligible, revoked}` is recomputed on domain verification and on
Stripe `account.updated` webhooks. Only `eligible` + a published page on a verified custom domain renders
`index,follow`.

**Two further gates were added after this section was written, and both outrank eligibility** (the full
decision lives in `page_robots_directive` + the thin-content step in `publish_page`):

- **Stripe mode.** Only a **live-mode** page is ever indexable; a test-mode page is test data and stays
  `noindex` wherever it runs. This is the MODE, never the deployment — `environment` (dev/prod) names the
  stack, and one stack serves both modes (`plans/STRIPE_MODE_DECOUPLING.md`, `src/stripe_link/silo.py`).
  Corrected 2026-10-23: the directive had been gated on the prod STACK, which made a live store on sandbox
  inherently unindexable and left the whole crawl-file path untestable outside prod.
- **Thin content (SEO-08).** An otherwise-indexable page under 150 words of unique body text is demoted to
  `noindex,follow` so a doorway-thin page cannot drag the Site's ranking down. Measured on the rendered HTML,
  so only the publisher knows it — which is why the sitemap reads a denormalized flag rather than recomputing
  (Phase 2.4).

**Side effect that resolves a real risk:** because platform hosts are never indexed, the custom-domain switch
is a clean **first indexation**, not a domain migration (no 301 chains, no equity loss, no duplicate content).
"Canonical switches automatically, nothing else changes" is only true *because* nothing was indexed before.

### 2.4 Page types are metadata, not a renderer fork

Each page in a Site's route map declares a **role**: `landing`, `homepage`, `collection`, `about`, `contact`,
`faq`, `legal`, `checkout`, `thank_you` (with `blog`/`article`/`category` reserved for later). The role is
pure metadata — it drives:

- which **JSON-LD `@type`** the page emits (e.g. `AboutPage`, `ContactPage`, `CollectionPage`, `FAQPage`),
- **sitemap** inclusion + priority,
- the **robots** default (checkout/thank-you → `noindex,follow` even on an eligible Site),
- **navigation** eligibility (a legal page belongs in the footer, not the primary nav).

The composition/element rendering engine is unchanged. `page_type` never branches `render_page`.

### 2.5 Navigation belongs to the Site

The Site owns the **menu** — an ordered list of slugs for `primary` and `footer` nav — not the page content.
Menus reference pages by slug; the pages themselves stay Page documents with a `page_type`. This prevents the
"invent a second object that says which pages go in the header" problem.

### 2.6 What the Site does NOT own

- **Products and Offers** stay the tenant-level catalog. Pages reference Offers; the Site routes pages. A Site
  is not a product catalog.
- **Page content** (sections, hero, price cards) stays on the Page. The Site owns *which* pages exist and
  *where they route*, not what's on them.

---

## 3. Consequences

**Positive**
- A real "website" abstraction; landing pages stop being orphans.
- One Organization identity → consistent entity graph, correct seller attribution, no fragmentation.
- Hostname-owned-by-Site makes the interim→real canonical upgrade a data change.
- The strict indexing model aligns the architecture with how search engines model publishers and gives a
  defensible answer to "what first-party oversight do you exercise?" (Connect verification).
- Multiple Sites per Tenant, blogs, collections, multilingual, marketplaces all fit later without a new layer.

**Negative / risks**
- It is a **new aggregate over existing data** → a real migration (mitigated: incremental, auto-default Site;
  see §5 and `SITE_MIGRATION.md`).
- **Clean multi-page slug URLs still require edge routing that doesn't exist** (a CloudFront KeyValueStore /
  path-aware Worker). The Site redesign organizes the *data* for this but does not remove the infra lift; it is
  sequenced as its own slice (Phase 2.6), not bundled with the model.
- Gating indexing on real Connect verification requires **new plumbing** (an `account.updated` webhook +
  `charges_enabled`/verification state) that does not exist today.

---

## 4. Relationship to existing infrastructure (build-on vs build-new)

| Concern | Today | Under Site |
|---|---|---|
| Custom domain | `tenant_config.custom_domains[]` (one subdomain → one page), Cloudflare custom-hostname flow, `CustomDomainsTable` index, resolve API, Worker reverse-proxy | Migrates to `Site.hosting.custom_domain` + `Site.integration`; reuse the Cloudflare verification flow and the resolve/Worker pattern (generalized to be path-aware in 2.6) |
| Public identity | `tenant_profile.brand` + `user_profile.business` + interim JSON-LD | `Site.organization` (single source) |
| Canonical / seller | interim published-artifact URL (`render_page(canonical_url=…)`) | `Site.hosting.canonical_hostname` + slug |
| Robots | per-stack: `indexable = published && env==prod` | `Site.indexing.eligibility` + page_type + custom-domain-verified |
| Sitemap / robots.txt | not served | generated per Site (2.4/2.6) |
| Routing | `{page_id}/index.html` only; slug ignored | `Site.pages` slug map + edge manifest (2.6) |

The `routes` short-URL system and the per-target `indexable` render logic stay as they are and inform the edge
work.

---

## 5. Plan of action (phased roadmap)

Each phase is independently shippable and testable, follows the established build→dev→review→prod workflow, and
is additive (existing pages keep working throughout — incremental migration).

**Phase 2.1 — Site data model + Organization + default-Site migration (foundation).**
- `schemas/Site.schema.json` v2, `validate_site`, `SitesTable`, `sites_repository`, `src/handlers/sites.py`
  CRUD, a minimal `Sites.vue`, enable the nav item.
- Auto-create a **default Site per tenant** and attach existing pages by `page_id` (idempotent backfill; a page
  belongs to at most one Site). Existing pages keep serving via `page_id` unchanged.
- Consolidate identity into `Site.organization` (read from `user_profile.business` / `tenant_profile.brand` on
  backfill; those stay readable during transition). See `SITE_MIGRATION.md`.
- No routing/robots changes yet — pure data model + admin.

**Phase 2.2 — Renderer consumes the Site: real Organization / canonical / seller.**
- `render_page` receives the resolved Site identity (canonical hostname + Organization).
- Emit `Organization` + `WebSite` JSON-LD (SEO-12); Product `seller.@id` → `https://{canonical}/#organization`
  (SEO-22, real). Canonical / `og:url` / `offers.url` derive from `Site.hosting.canonical_hostname` + the
  page's slug (SEO-01, real for single-host Sites using today's routing).

**Phase 2.3 — Indexing eligibility gate (Stripe Connect + custom domain).**
- Stripe `account.updated` webhook + `charges_enabled`/verification state on the Connect record.
- `Site.indexing.eligibility` computed from custom-domain-verified + Connect-verified.
- Robots directive: `index,follow` only for a published page, on a verified custom domain, on an eligible Site,
  whose `page_type` is indexable; everything else `noindex` (SEO-02/21, TP-08).

**Phase 2.4 — Crawl infrastructure per Site. SHIPPED (dev+prod).**
- `sitemap.xml` + `robots.txt` generated per Site (canonical, indexable URLs only; page_type/robots-aware).
- IndexNow submission on publish (SEO-15). Webmaster verification tokens in `<head>` (SEO-16) — Google, Bing
  and Pinterest.
- **The multi-URL sitemap only became true on 2026-10-22** (`plans/OFFERLESS_PAGES_IN_BUILDER.md` P5). Until
  then this described the intent while the file held exactly ONE url, the homepage — so a Site with a
  storefront, category pages, an about page and a dozen products advertised one of them. Each publish now
  records `indexable`/`lastmod`/`images` on its own Site route entry and the sitemap is built from the route
  map; a page with no flag has not published since that shipped and is left out rather than guessed at.
  One entry per PAGE at its own address, so `/sale`, `/flash-sale` and the reserved funnel slugs are excluded
  as the same page_id. Two latent bugs were fixed in the same pass: the crawl files were written under the
  page CURRENTLY PUBLISHING while the resolver serves them from the Site's ROOT page, and IndexNow was always
  pinged with the root rather than the page that changed.
- First exercised end to end on a real custom domain 2026-10-23 (`shop.coderbay.net`, sandbox, live mode).

**Phase 2.5 — On-page structure. COMPLETE (dev+prod).** Breadcrumbs (SEO-11) + thin-content gate (SEO-08) +
visible nav / store-root internal linking (SEO-13, the part not needing collection pages) shipped. The rest of
SEO-13 — category/collection index pages + an image related-products rail — is **folded into Phase 2.5b**
(§below), which owns the collection/category renderer those need. Nothing from 2.5 remains open.
- **Thin-content gate (SEO-08) — SHIPPED (dev+prod).** `indexable_word_count`/`thin_content_warnings` in
  html.py: approximate unique body words (strip scripts/styles + chrome — breadcrumb, header, footer nav,
  legal footer, minicart). An otherwise-indexable page below the 150-word floor is demoted to noindex,follow
  at publish (measured once, re-render only the rare indexable+thin artifact); the builder page-health panel
  warns with a fix checklist. NOTE: some existing thin pages (e.g. the prod homepage ~80 words) flip to
  noindex on next publish until content is added — the intended protection.
- **Visible nav (SEO-13 partial) — SHIPPED (dev+prod).** Storefront header (Organization name → store root +
  primary menu) + footer nav, rendered from `Site.navigation.primary/footer` resolved against the verified
  custom domain; crawlable `<a>` links to page slugs (label from the Site entry or slug-derived). Same gate as
  breadcrumbs (verified domain, not post-checkout). `site_nav_items`/`render_site_header`/`render_footer_nav`.
- **Breadcrumbs (SEO-11) — SHIPPED (dev+prod).** Visible crawlable `<nav class="sl-breadcrumb">` trail +
  matching `BreadcrumbList` JSON-LD, rendered by html.py (`breadcrumb_trail`/`breadcrumb_json_ld`/
  `render_breadcrumb`). Gated: only on a page served at a non-root slug on the Site's verified custom domain
  (a resolvable Home); never on the homepage (it's the root), never on post-checkout page_types
  (funnel_step/thank_you/checkout — a Home link would leak the buyer out of the funnel). Trail is shallow
  (Home→current) until category pages exist; a category level slots in between then. JSON-LD rides the
  search_seo discoverability pack (like Product/FAQ); the visible trail renders regardless of goal. render_page
  gained a `page_type` param + `_RENDER_STATE` home_url/page_type holders.
**Phase 2.5b — Storefront homepage + collection/category pages. COMPLETE (dev+prod); substantially extended
2026-10-22 by `plans/OFFERLESS_PAGES_IN_BUILDER.md` (P1–P4).** The page types below shipped able to render but
not to be *authored*: editing one reopened the create wizard, which offered no prose field at all, so every
storefront, category and store-profile page measured 5–15 words and the thin-content gate demoted all of them
to `noindex`. They now open in the real builder, carry a goal, and emit `CollectionPage`/`ItemList` markup and
a page-specific meta description. Read that plan alongside this section.
- **Slice 1 (SHIPPED)** — the storefront homepage. Composition-respecting (no renderer fork): two ungoverned
  sections `brand_hero` (store name as single H1, no product) + `catalog_grid` (curated cards → each offer's
  landing slug, internal linking). Offer-less pages: `offer_id` optional when a `catalog_grid` is present
  (schema + publish + preview). Builder: a step-1 "Storefront homepage" branch that picks pages for the grid;
  `POST /sites/{id}/homepage` sets a page as the Site homepage (displacing the old one to its own slug).
  Follow-ups: storefront-page editing in the builder + a wizard live preview.
- **Slice 2 backend (SHIPPED dev+prod)** — auto-enumerated category index pages. Landing pages denormalize
  their `offer_id` + `product_category` onto the Site route-map entry at publish; a `catalog_grid` with a
  `category` resolves its cards by scanning the route map (`resolve_category_grids`). Breadcrumbs deepen to
  Home → Category → Product when the Site has a category page for the product's category. `POST /sites/{id}/pages`
  attaches a page at a slug with a page_type + optional category (generalizes the homepage endpoint).
  Builder (Slice 2e, SHIPPED): a step-1 "Category page" kind (pick a category from the tenant's product
  categories → offer-less catalog_grid) + a Sites "Attach a page" control (`POST /sites/{id}/pages`, detects a
  category page and attaches it as page_type=category, else landing — attaching landing pages is what
  denormalizes them so category grids find them).
- **Slice 3 (SHIPPED dev+prod)** — related-products rail. An addable `related_products` section renders a
  same-category internal-link rail: at publish it fills from the Site's other pages in this page's category
  (excluding self), reusing the catalog-grid card layout. Completes the SEO-13 internal-linking set.
- A purpose-built homepage/`OnlineStore` page (brand hero, nav, lists the Site's offers/products) — a real
  `page_type: homepage`, not a landing page repurposed at the `/` slug (today's interim). The schema already
  reserves `homepage`/`collection`/`category`/`about` page types; this builds the editor + renderer for them.
  Makes a Site feel like a website, not a single funnel page. Overlaps 2.7 (profile).
- **Folded in from 2.5 (rest of SEO-13):** category/collection **index pages** generated from
  `product.category`, and an **image related-products rail** (3–6 same-category products with real `<a href>`).
  Both need this phase's collection/category renderer + catalog enumeration (a way to list a Site's
  products/pages by category), which is exactly what this phase builds — hence the fold rather than a bolt-on
  in 2.5.
- **Deepens breadcrumbs (SEO-11):** once category pages exist, the shipped breadcrumb trail gains its middle
  level automatically (Home → Category → Product) — the trail builder already leaves the slot; only the
  category URL/name need supplying.

**Phase 2.6 — Clean multi-page slug routing (the edge-infra slice). SHIPPED (dev+prod), pulled ahead of 2.5.**
- Edge route manifest realized as a **denormalized `routes` table on the domain-index record** (slug→page_id),
  projected off `Site.pages` by `custom_domains.domain_index_record`. The resolver + Worker are path-aware:
  the Worker forwards the path on every request and caches by host+path; the resolver maps `(host, path)` →
  slug → page_id → artifact, serving the homepage at `/`, well-known crawl files as siblings, and returning
  404 for an unknown slug. A CloudFront KeyValueStore remains a future optimization (the record is the manifest
  for now); `artifact_paths` still keys by page_id, so no re-keying was needed.
- **Serves the WHOLE funnel on the one custom domain:** on publish of a funnel entry page, its upsell/downsell/
  thank-you pages auto-attach to `Site.pages` at derived slugs (`/thank-you`, `/upsell-1`) and the route table
  refreshes, so they route on the custom domain. The `post-checkout/next` redirect regenerates as
  `https://{custom_domain}/{slug}`; Stripe `cancel_url` and non-funnel `success_url` already derive from
  `window.location` client-side, so the buyer never switches domains mid-funnel. Funnel step pages carry the
  new `funnel_step` page_type (noindex,follow, alongside `thank_you`).
- **Known limitation:** a funnel step page published *before* the entry page attaches it keeps its interim
  platform canonical until re-published (it's noindex regardless, so no indexing impact). A dangling funnel
  reference (thank-you page_id with no published artifact) attaches a slug that 404s — a tenant data issue, not
  a routing bug; the buyer-after-purchase hop for such a funnel was already broken pre-2.6.

**Phase 2.6b — Apex / root domain support. COMPLETE (dev+prod 2026-10-23): A/AAAA apex proxying is on.**
- Serving infra already handled apex (resolver/Worker key by hostname); the real work was the DNS-instruction
  layer. `assert_valid_domain` no longer rejects apex. `custom_hostname_dns_records` emits an ALIAS/flattened
  CNAME → `domains.jbay.uk` by default (works on Cloudflare's CNAME-flattening, DNSimple, ANAME/ALIAS
  providers), or plain A/AAAA to static IPs when `CLOUDFLARE_APEX_IPV4/IPV6` are configured (apex proxying —
  works on every provider incl. Route 53; empty until procured, then a config flip). DCV delegation unchanged
  (on the `_acme-challenge` subdomain). Sites.vue shows provider-adaptive apex guidance.
- **www↔apex redirect — SHIPPED.** An apex connect provisions `www.<apex>` as its own custom hostname carrying
  a `redirect_to` on its domain-index record; `custom_domains_resolve` turns that into a 301 to the apex (the
  canonical). Best-effort: the apex serves whether or not www succeeds.
- **The last item is DONE** (2026-10-23). `deploy/deploy.sh` now sets `CloudflareApexIpv4`/`IPV6` per
  environment to its own zone's anycast pair — `104.21.71.205`/`172.67.149.43` (+ IPv6) for jbay.uk,
  `104.21.88.48`/`172.67.173.6` for jbay.be — so every apex tenant is handed plain A/AAAA records, the one
  record type every provider supports, Route 53 included. No code change was needed; the record builder and
  the dashboard's A/AAAA copy had been waiting for the addresses. Guarded by `tests/test_apex_domains.py`,
  which asserts on the deploy script, because that is where the value is decided.
  **They are SHARED anycast addresses, and two measurements changed how alarming that is.** Pinning a
  working custom hostname to its own zone's pair serves 200 — and pinning it to the OTHER zone's pair also
  serves 200 (`curl --resolve shop.coderbay.net:443:104.21.71.205`, 2026-10-23). Cloudflare's edge routes
  purely by SNI/Host to whichever zone registered the hostname, so a reassignment *within* Cloudflare's
  anycast space keeps serving. The failure that would actually break tenants is an address leaving
  Cloudflare's network entirely — rare, slow, and no longer silent: `plans/DOMAIN_HEALTH_SWEEP.md` shipped
  first precisely so it could not be.
  Dedicated IPs remain the eventual answer, on timing we control: `domain_provisioning.dns_records` records
  what each tenant was told, so that migration is a known list of names and a gradual overlap rather than a
  coordinated outage. **Sequence as planned: the sweep, then the shared IPs, then dedicated IPs when apex
  tenants justify the line item.** The first two are done.
- **The dead-end this phase set out to close is now CLOSED** (2026-10-23). The historical note below warned
  that `assert_valid_domain` "ACCEPTS an apex it can't route". The ALIAS path fixed that for providers with
  an apex feature — Cloudflare flattening, DNSimple, ANAME — and left it for the rest. **Route 53 was the
  one that mattered**: its ALIAS targets only AWS resources, so it cannot point an apex at
  `domains.jbay.uk`. Found while assessing `coderbay.net`, whose nameservers are `awsdns-*`. With the apex
  addresses published, that tenant is handed A records Route 53 can create, and `apexHint` already says so:
  *"Your root domain uses plain A/AAAA records below — these work on any provider, including Route 53."*
- **The tenant is NOT left guessing**, which this note first claimed and a check disproved. `Sites.vue`'s
  `apexHint` carries a Route 53 case verbatim: *"Route 53 can't point a root domain at an external host like
  ours. Use a subdomain (e.g. www) for now, or move DNS to a provider with ANAME/ALIAS support."* **Both residual gaps stopped mattering** when the apex
  addresses went live: the provider-specific copy is now only reached when apex addresses are UNset (a
  fresh environment), because `usingA` short-circuits ahead of it — so a stale `<select>` default no longer
  misleads anyone, and the server mints a hostname every provider can point at. The provider `<select>`
  surviving as dead-in-practice copy is the remaining tidy-up, not a dead end.

**(historical) Phase 2.6b was — Apex / root domain support (COMMITTED — REQUIRED, not optional).**
- The product is a website builder for SEO; tenants must be able to use `example.com`, not only a subdomain.
- Blocker: our routing uses a CNAME (`domain → domains.jbay.uk`), and DNS forbids a CNAME at the apex. Needs
  ALIAS/ANAME/CNAME-flattening handling (Route 53 ALIAS, Cloudflare flattening) with provider-specific
  instructions, and an apex↔`www` redirect (standard SaaS pattern). Also: tighten `assert_valid_domain`, which
  currently ACCEPTS an apex it can't route (latent dead-end — flag/reject apex clearly until 2.6b ships).
- Subdomain custom domains (the current bridge) stay as-is; apex is additive.

**Phase 2.7 — Tenant/seller profile page. SHIPPED (dev+prod).**
- `seller_profile` section: a `CollectionPage` whose `mainEntity` is the full `OnlineStore` node (the seller
  `@id` resolves here — TP-03/04/05), plus a visible identity block (description, contact, verified social
  links `rel="nofollow ugc noopener"`, category links). Offer-less page (`page_type: about`), created via a
  4th builder kind "Store profile". **Security fix:** `sameAs` now emits only ownership-VERIFIED entries
  (TP §4.4 impersonation gate), host-whitelisted, ≤6. `hasOfferCatalog` derived from the Site's category
  pages ("brands carried", not owned). `is_offerless_page` marker unifies the offer-optional gate.
- **Follow-up:** the `sameAs` verification mechanism (OAuth / bio-token / reciprocal-link) + the social-profile
  editor (paired — unverified socials never emit, so nothing renders until verification ships).

Ordering note: **2.1–2.4 deliver the bulk of the SEO value on single-host Sites without the edge lift.** 2.6
(clean multi-page paths + funnel-on-domain) was **pulled ahead of 2.5** and shipped, because 2.5's breadcrumbs /
visible nav need slugs that resolve on the custom domain — 2.6 made those links real. **2.5 (on-page structure)
is now COMPLETE.** Remaining committed work: 2.5b (storefront homepage + collection/category pages, now also
carrying the rest of SEO-13), 2.6b (apex domains, REQUIRED), 2.7 (seller profile page).

### Documented workflows & decisions (confirmed 2026-07-21)

- **Distinct domains per landing page = distinct Sites.** The Site model attaches ONE custom domain to a Site
  (which serves its pages). To give separate landing pages their own domains (e.g. separate micro-brands), make
  each its own **Site** (a Site can be a single page) and connect a domain to each. This is the supported
  pattern; the current bridge already handles it. The legacy page-scoped `/custom-domains` API still exists but
  was never surfaced in the dashboard and is superseded.
- **Homepage is interim.** Until 2.5b, the Site "homepage" is whichever landing page is designated at the `/`
  slug. A real homepage builder is committed (2.5b).
- **Apex domains are committed (2.6b), required** — not a maybe. Subdomain-only is a temporary limitation.

---

## 6. Domain topology (LOCKED 2026-07-20)

Three reputation zones, three distinct registrable domains (eTLD+1) — the mechanism that makes the isolation
real. The hosting domain is read from config, never hardcoded.

| Zone | Registrable domain | Role | Indexed? |
|---|---|---|---|
| **Platform** | `juniorbay.com` | Junior Bay platform: marketing/sales, `app.juniorbay.com` (dashboard), `api.`, `docs.`, checkout | first-party marketing yes; app/api/checkout `noindex` |
| **Tenant free hosting** | `jbay.uk` | `{name}.jbay.uk` named subdomains + short URLs (Cloudflare-fronted, → CloudFront origin) | **never — `noindex`** |
| **Tenant storefronts** | the tenant's own custom domain | the real public store | **the only indexed tier** (custom domain verified + Connect verified) |
| Classifieds (legacy) | `juniorbay.net` (or retired) | a separate product | separate |
| `automizepro.com` | — | defensive redirect → `juniorbay.com` | — |

Decision record: Junior Bay is the **platform** brand and owns `juniorbay.com` (the classifieds product moves to
`juniorbay.net` or is retired). Tenant free sites live on `jbay.uk` (a different eTLD+1 from `juniorbay.com`,
and `noindex` regardless). This satisfies TP-06/TP-11: platform content never shares a registrable domain with
tenant storefronts, and only a tenant's own domain ever carries indexed reputation.

### Remaining sub-questions (not blockers)

- **Whether to retire `jbay.be`** — STILL OPEN, but the cost rose on 2026-10-23: `jbay.be` is no longer only
  sandbox's free-hosting domain, it is also sandbox's **Cloudflare for SaaS zone** (fallback origin
  `domains.jbay.be`). Retiring it now would take sandbox custom domains with it.
- ~~The **environment model** for Sites (`test`/`live` in-schema vs the per-stack `dev`/`prod` reality)~~ —
  **RESOLVED.** There are THREE axes, not two, and they are named: `ENVIRONMENT` (dev/prod) is the deployment,
  `stripe_mode` (test/live) is Stripe's, and the **silo** (sandbox/production) is "which independent copy of
  Junior Bay is this" — see `src/stripe_link/silo.py`, which exists to stop the three being read for each
  other. The Site's own field was called `environment` while holding `live`/`test`; renamed to `stripe_mode`
  2026-10-23, which also collapsed a duplicate (the mode-scoped repository already stamped `stripe_mode`, so
  a Site stored the answer twice and a test existed to stop the two disagreeing).
- ~~Moving the dashboard from the raw CloudFront URL to `app.juniorbay.com`~~ — **DONE.** `app.juniorbay.com`
  is prod, `sandbox.juniorbay.com` is dev.
