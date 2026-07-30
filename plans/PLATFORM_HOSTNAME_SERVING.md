# Platform-hostname Site serving (`*.jbay.uk`) — navigable free/test stores + environment parity

**Status:** design, not built. **Author-greenlit 2026-07-30** (direction chosen over a bespoke "test store").

## Why

Clean-slug Site navigation — what storefront cards, the header home link, breadcrumbs, and the reserved
post-purchase funnel slugs (`/upsell` `/downsell` `/thank-you`) and context views (`/sale` `/flash-sale`) all
rely on — exists in **exactly one place today: a live custom domain in prod** (served by the Cloudflare Worker
→ `custom_domains_resolve.py`). Consequences:

- **No navigable store in test.** The test host (`test.juniorbay.com/{published|preview}/{code}`,
  `handlers/test_page_serve.py`) serves pages *by short_code, one at a time* — it has no Site/slug routing, so a
  storefront can't navigate there.
- **Storefront card links die off the live domain.** They're built as `home_url + slug` against the Site's
  custom domain; in dev (or before the domain is live) that domain doesn't resolve → `NXDOMAIN` when clicked
  (the `mart.automizepro.com` bug, 2026-07-30).
- **The free platform hostname is reserved but not wired.** Every Site already gets `{label}.jbay.uk`
  (`_ensure_platform_hostname`, reserved in `SubdomainRegistry`), but nothing serves `*.jbay.uk`.

**Wiring `*.jbay.uk` to serve Sites** gives a navigable store on the free platform address in **both
environments** — building the test↔live parity we want — that is always `noindex` (reputation isolation), and
makes "go live" simply mean **connecting a custom domain** (the indexed, branded upgrade). It also unlocks
**free-tier stores** as a product surface.

## Guiding principles

1. **Reuse, don't rewrite.** The custom-domain resolver, route table, `attach_funnel_slugs`,
   `attach_context_view_slugs`, `funnel_role`/`strategy`, re-publish-on-verify, and the SEO toggle are already
   **host-agnostic**. The platform host is a *new host type that plugs into the same machinery*. The
   custom-domain path stays byte-for-byte the same; the **existing ~1218 tests are the tripwire** that proves it.
2. **The platform host is never indexed.** `page_robots_directive` keeps the reputation-isolation floor: only a
   verified custom domain on an eligible Site is indexable. Platform host = **navigable + `noindex`**.
3. **One artifact, many hosts.** Prefer host-relative internal links so a single published artifact serves
   correctly on the platform host, the custom domain, and previews — which also *fixes* the dead-link bug.

## What we reuse (verified current state)

- **Resolver** (`handlers/custom_domains_resolve.py`): `index_repo.find_by_id(normalize_domain(host))` → the
  denormalized route table → slug → artifact, already including funnel + context-view slugs. **Serving a
  platform host = the same resolver keyed on a different host** — write a domain-index record for
  `{label}.jbay.uk` and it just works.
- **`SubdomainRegistry`** (`repositories/documents.py`): `owner_of(label) → site_id`, so a platform host maps to
  its Site (a fallback lookup if we ever need it beyond the index record).
- **Zone + cert:** we own the `jbay.uk` zone (`domains.jbay.uk`, `go.jbay.uk` already live on it). Cloudflare
  **Universal SSL covers one-level `*.jbay.uk`** — so `{label}.jbay.uk` needs **no per-tenant certificate**
  (unlike custom domains via Cloudflare-for-SaaS). This is the big infra win.
- **Worker:** `deploy/cloudflare-custom-domain-worker.js` + `setup-cloudflare-custom-domain-worker.sh` — the
  reverse-proxy-via-resolve-API pattern already exists to extend to `*.jbay.uk`.

## The work (phased)

### P1 — Serve Sites on the platform host (the core)

1. **Index record per platform host.** At publish (and on Site save), write a domain-index record keyed by
   `{label}.jbay.uk` carrying the **same route table** as a custom domain (`domain_index_record` /
   `route_table`, already funnel- and context-aware). The existing resolver then serves it **with no resolver
   code change**. (Distinguish it from a custom-domain record so indexing stays off — a flag like
   `host_kind: "platform"`, or infer from the hostname suffix.)
2. **Cloudflare: `*.jbay.uk` → Worker → resolve API → pages origin.** Add a wildcard route to the existing
   Worker (excluding the reserved hosts `domains.`/`go.`/`api.`/etc.), pointing at the same resolve endpoint.
   Universal SSL covers the wildcard.
3. **Decouple "navigable home host" from "indexable custom domain."** Today `home_url` (drives the storefront
   header + internal links) is set only for a *verified custom domain*, and that same signal gates indexing.
   Split them: set `home_url` = the **serving host** for platform hosts too (so chrome + navigation render),
   while `page_robots_directive` keeps platform hosts `noindex`. This lives next to the SEO-toggle code — a
   clean split, not a reversal; the SEO toggle already separated "chrome" from "indexing," so it fits the grain.
4. **Host-relative internal links.** `render_catalog_grid` cards, `render_site_header` brand link,
   `render_breadcrumb` → emit **relative** targets (`/slug`, `/`) so one artifact serves correctly on any host
   (and previews stop dead-linking). No change to which slugs resolve — the resolver still maps slug→artifact
   per host.
5. **Host-aware funnel redirects.** `handlers/post_checkout.py` (`_next_page_url`) currently hardcodes the
   custom domain for the reserved-slug redirects. Make it **preserve the buyer's origin host**: the landing
   page's checkout `success_url` (built client-side, which knows `window.location.origin`) carries the origin;
   the router redirects to *that* host + reserved slug. So a funnel entered on `{label}.jbay.uk` stays there,
   and one entered on the custom domain stays there — reusing all of `funnel_reserved_slug` mapping.

**P1 done:** a Site is fully navigable on `{label}.jbay.uk` in **both** environments — storefront, offer pages,
funnels, sale/flash views — all `noindex`. The dead-link/preview problem is gone.

### P2 — Environment parity / promote (test → live)

With both environments serving Sites identically, the promote story simplifies:
- Extend the existing **copy-page-to-environment** (`copyPageToEnvironment`, `handlers/pages` copy path) into a
  **Site-level copy**: the Site doc (route map, org, SEO settings) + all its pages + their offers/products,
  test → live, same IDs.
- The **custom domain is NOT copied** (live-specific). On live, the Site is immediately navigable on its
  platform host; **connecting + verifying a custom domain** (existing flow + re-publish-on-verify) upgrades it
  to the indexed, branded home. No bespoke "test store" concept needed.

### P3 — Polish / free-tier surface

- Free-tier **shareable store URL** on the platform host (a real store without a custom domain).
- Dashboard: show the platform-host store URL + a "Visit store" link; point the storefront **Live Preview** at
  the real, navigable platform-host URL instead of a dead custom domain.
- Optional: brand-as-headline for the storefront (pick a Profile brand; fall back to store name) — noted
  2026-07-30, independent of this plan.

## Risk / what stays locked

- **Custom-domain behavior is unchanged and test-fenced.** Platform-host work is additive with its own tests.
- **Reputation floor preserved** — the platform host is always `noindex`; only a verified custom domain on an
  eligible Site indexes.
- **The one careful area** is the `home_url` ↔ indexing decoupling (P1.3), because it sits near the SEO toggle.
  It's a clean split, and the existing SEO-toggle + robots tests guard the boundaries.

## Resolved implementation decisions (2026-07-30, build start)

- **One artifact per page + `noindex` via edge response header** (NOT per-host artifacts). A verified custom
  domain serves the page `index,follow` from the HTML; the platform-host resolver path adds
  `X-Robots-Tag: noindex, nofollow` so the same artifact is `noindex` there (more-restrictive wins). For a
  platform-only Site the artifact is *already* `noindex` (`on_custom_domain` false), so the header is
  belt-and-suspenders. Avoids doubling artifacts.
- **Relative internal Site links** (catalog cards, `sl-brand` header, breadcrumb, nav) so ONE artifact
  navigates correctly on the platform host AND the custom domain. Absolute stays only for `canonical`/`og:url`
  (→ the primary home) and the server-side funnel redirect (host-aware, Slice 3).
- **`home_url` = the Site's canonical origin** — custom domain if verified, else the platform host — used for
  `canonical`/`og:url` and to gate whether the storefront chrome renders. **Gated behind platform-serving-
  enabled** so existing pages don't sprout chrome until the feature is on (no silent change to shipped output).
- **Index-record-per-platform-host**: publish writes a domain-index record keyed by `{label}.<hosting-domain>`
  with the same `route_table`, tagged `host_kind: "platform"`, so the existing resolver serves it unchanged.
- **Build order = safest first.** Slice 1 (index record + resolver header) is additive and leaves the shipped
  custom-domain render byte-identical; the render changes (Slice 2) come next, fenced by the existing tests.

## Progress

- **Slice 1 — SHIPPED dev.** Platform domain-index record per Site + `host_kind: "platform"` → resolver
  `X-Robots-Tag: noindex` header. Test env flipped to `jbay.be`; dev Axel Mart Site migrated `.jbay.uk`→`.jbay.be`.
- **Slice 2 — BUILT (this pass), flag OFF.** (a) All internal Site links now render **host-relative**
  (`internal_href`): catalog cards, `sl-brand`, breadcrumb visible `<a>`, nav/footer menus, seller-profile
  catalog, thank-you home. Breadcrumb **JSON-LD `item` stays absolute** (Google wants absolute). This is
  behaviour-preserving on a custom domain (relative resolves to the same URL) and fixes the dead-link bug.
  (b) `home_url` decoupled: `render_page(home_url=…)` override; `publishing.site_serving_origin()` computes the
  Site's serving origin (verified custom domain → else platform host **gated by `PLATFORM_SERVING_ENABLED`**),
  and `canonical` + `home_url` are both derived from it so they always share an origin (breadcrumb depends on
  that). Flag defaults **off** → platform-only Sites stay chrome-less until the edge is wired (no silent change).
  **Deferred to ops:** wire `PLATFORM_SERVING_ENABLED` as a SAM parameter / Lambda env var so it can be flipped
  on per environment when the `*.jbay.*` Worker route goes live.
- **Slice 3 — BUILT (this pass), flag OFF.** Host-aware funnel redirects. (a) Every client-side
  `post-checkout/next` builder (funnel-island dismiss, checkout `success_url`, cart success, pp-carousel
  dismiss) now carries `origin=window.location.origin`. (b) `post_checkout._next_page_url` reads that origin and
  keeps the funnel on it — but only after `_redirect_base` validates it against the Site's known origins
  (verified custom domain + platform host when serving is on), so a forged `origin` can't open-redirect the
  buyer; otherwise it falls back to the custom domain, then the interim artifact. (c) `publishing.site_is_served`
  broadens the funnel/context **slug-attach + route-table** gates from "verified custom domain" to "served"
  (custom domain OR platform host when the flag is on), so `/upsell //downsell //thank-you //sale //flash-sale`
  resolve on the platform host too. Everything platform-side is behind `PLATFORM_SERVING_ENABLED` (off) → no
  change to shipped behaviour; the only always-on change is the harmless `origin` query param on funnel URLs.
  **P1 (the core) is now code-complete — only the Cloudflare ops + the flag flip remain to light it up.**

## SHIPPED — live on both environments (2026-07-30)

Platform-hostname serving is **fully live and validated on test AND prod**:
- **Test (`jbay.be`):** `axel-mart.jbay.be` serves `200` + `x-robots-tag: noindex, nofollow` + storefront chrome
  + relative internal links + self-canonical (fake `mart.automizepro.com` custom domain disconnected → true
  free-tier store).
- **Prod (`jbay.uk`):** `axel-mart.jbay.uk/vyhthv-whey-protein` serves `200` + edge `noindex`; canonical → its
  custom domain (by design — platform host is a noindex mirror).
- **Edge (both zones, one Cloudflare account):** `jbay.be` `*/*` → `jb-custom-domain-router-dev`; `jbay.uk` `*/*`
  → `jb-custom-domain-router-prod` (both Workers stamp `X-Robots-Tag` on `route.noindex`); wildcard
  `*.jbay.be` / `*.jbay.uk` A → `192.0.2.1` (Proxied). API token widened to all-zones-on-account.
- **`PLATFORM_SERVING_ENABLED=true`** on both stacks.
- **Bug fixed during prod validation:** `publish_page_document` synced the domain index only when a funnel/
  context slug changed, so a re-published page whose slugs were already attached never (re)wrote its platform-
  hostname record — `{label}.<hosting-domain>` stayed unresolvable. Now the domain index is refreshed on EVERY
  publish (idempotent); regression test added; validated live (delete record → re-publish → publish recreates it
  in ~6s). commit after 0d25854.

Remaining: **P2** (Site-level copy test→live) and **P3** (dashboard "Visit store" link + point the builder Live
Preview at the real platform-host URL).

## Ops runbook — lighting it up (Cloudflare + flag flip)

Everything in the app is code-complete behind `PLATFORM_SERVING_ENABLED` (off). The edge is the last mile.
The Worker + setup script already handle platform hosts (`deploy/cloudflare-custom-domain-worker.js` stamps
`X-Robots-Tag: noindex, nofollow` when the resolver flags `route.noindex`; the setup script binds a zone-wide
`*/*` route and is parameterized by `CLOUDFLARE_ZONE_ID`).

1. **Move the `jbay.be` zone** onto the Cloudflare account that holds `jbay.uk`. Confirm Universal SSL covers
   `*.jbay.be` (one label under the apex — free, no Advanced Certificate Manager). Delete/relocate any leftover
   stripe-cart subdomains on `jbay.be`, or add them to `RESERVED_HOSTS` in the Worker so they pass through.
2. **Deploy the Worker to both zones** (same script, once per zone id):
   - prod / `jbay.uk`: `CLOUDFLARE_ZONE_ID=<jbay.uk zone> STACK_NAME=jb-stripe-link-stack-prod ENVIRONMENT=prod ./deploy/setup-cloudflare-custom-domain-worker.sh`
   - test / `jbay.be`: `CLOUDFLARE_ZONE_ID=<jbay.be zone> STACK_NAME=jb-stripe-link-stack-dev ENVIRONMENT=dev ./deploy/setup-cloudflare-custom-domain-worker.sh`
   (The `jbay.uk` zone likely already has the custom-domain route; re-running just re-uploads the updated
   script and is idempotent on the route.)
3. **Flip the app switch** per environment and re-publish so chrome + platform index records regenerate:
   `PLATFORM_SERVING_ENABLED=true ./deploy/deploy.sh dev` (then prod). Re-put a Site's pages (bump `updated_at`)
   to trigger re-publish via the PagesTable stream.
4. **Smoke test:** `curl -sI https://axel-mart.jbay.be/` → 200 + `x-robots-tag: noindex, nofollow`; the storefront
   renders chrome with relative links; an offer page, `/upsell`, `/downsell`, `/thank-you`, `/sale` all resolve;
   a test purchase's funnel stays on `axel-mart.jbay.be` end to end.

**Rollback:** re-deploy with `PLATFORM_SERVING_ENABLED` unset (default off) — pages revert to chrome-less interim
identity on the next publish; the Worker route can stay (a platform host with the flag off simply has no attached
routes and 404s, which is the pre-feature state).

## Open decisions (resolve during scoping)

1. **Index-record-per-platform-host vs. registry lookup in the resolver.** Lean **index record** — reuses the
   resolver untouched, denormalized like custom domains, consistent mental model.
2. **Relative vs. host-aware-absolute internal links.** Lean **relative** for the artifact; **absolute only**
   for the server-side funnel redirect (which carries the origin host).
3. **Wildcard cert scope — RESOLVED 2026-07-30.** Prod platform host = `{label}.jbay.uk`; **test platform host =
   `{label}.jbay.be`** (author-owned, freed by sunsetting stripe-cart). Both are single-label under their apex,
   so Cloudflare **Universal SSL covers `*.jbay.uk` and `*.jbay.be` for free** — no Advanced Certificate
   Manager. `PLATFORM_HOSTING_DOMAIN` = `jbay.uk` in prod, `jbay.be` in the dev/test stack. **Setup:** move the
   `jbay.be` zone onto the Cloudflare account that holds `jbay.uk`; clean up / exclude any leftover stripe-cart
   subdomains on `jbay.be` so they don't collide with the `*.jbay.be` store Worker route.
4. **Worker topology.** One Worker with a `*.jbay.uk` route + reserved-host exclusions, vs. a sibling Worker.

## Ties

`plans/SITE_OBJECT.md` (Site = aggregate root, `platform_hostname`, route map); `plans/SALES_FUNNELS.md`
(reserved-slug funnel routing, reused host-agnostically); the SEO toggle (`indexing.seo_enabled`, chrome↔index
split); `handlers/custom_domains_resolve.py` + `runtime/publishing.py` (`domain_index_record`/`route_table`) +
`repositories/documents.py` (`SubdomainRegistry`); copy-page-to-environment (extended to Site-level in P2).
