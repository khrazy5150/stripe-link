# Site Migration Guide

**Companion to:** `plans/SITE_OBJECT.md`, `schemas/Site.schema.json` (v2).
**Strategy (consensus):** **incremental** — the Site is built *alongside* existing data. Nothing breaks on day
one; existing pages keep serving via `page_id`. A default Site is auto-created per tenant and existing pages are
attached to it. No big-bang cutover.

---

## 1. The shape change

```
BEFORE                                   AFTER
------                                   -----
Tenant                                   Tenant   (billing/users/Stripe only)
  └── Page (carries domain, SEO,           └── Site   (hostname, Organization, SEO, nav, indexing)
            analytics, legal, routing)           └── Page (content/layout/offer-ref/page_type)

+ identity spread across:                + identity consolidated into:
    tenant_profile.brand{}                   Site.organization
    tenant_profile.business_name
    user_profile.business{}
    (unbuilt Site.seo_defaults)

+ custom domains in:                     + custom domain in:
    tenant_config.custom_domains[]           Site.hosting.custom_domain + Site.integration
```

---

## 2. Field moves

| From | To | Notes |
|---|---|---|
| `user_profile.business.name` | `Site.organization.name` | The storefront/brand label |
| `user_profile.business.phone` | `Site.organization.telephone` | Normalize to E.164 |
| `user_profile.business.address{street,locality,region,postal_code,country}` | `Site.organization.address{…}` | Same shape |
| `user_profile.business.brands[]` | *stays a product concern* | These are the brands the tenant **carries** (→ `hasOfferCatalog` later), not the Organization's own name — do not map into `organization.name` |
| `tenant_profile.business_name` | `Site.organization.legal_name` (or `name` if no user_profile value) | Reconcile duplicates on backfill |
| `tenant_profile.brand.display_name` | `Site.organization.name` (preferred source) | |
| `tenant_profile.brand.logo_url` | `Site.organization.logo.url` + `Site.branding` | |
| `tenant_profile.brand.primary_color` | `Site.branding.colors.primary` | |
| `offer.presentation.brand` (interim brand_label) | continues to work; **falls back to** `Site.organization.name` when a Site exists | The offer pick still wins; Site is the new default source |
| `tenant_config.custom_domains.domains[]` | `Site.hosting.custom_domain` + `Site.integration` (cloudflare_saas) + `Site.hosting.verification` | The one-subdomain→one-page entry becomes the Site's custom domain |
| `page.analytics{google_tag_id,pixel_id}` | `Site.analytics` (page may still override) | |
| `page.seo.title` / `.description` | **stays on Page** (per-page override) | Site provides `seo.title_suffix` + Organization brand |
| page's implicit "landing" role | `Site.pages[slug].page_type` | Default `landing` |

**During transition, the old fields stay readable.** Backfill copies (does not delete) so a rollback is safe.
A later cleanup pass removes the duplicated identity once the Site is the confirmed source.

---

## 3. Migration steps (executed within Phase 2.1)

1. **Stand up the Site infrastructure** (schema, `SitesTable`, `validate_site`, `sites_repository`,
   `handlers/sites.py`) with zero behavior change to page rendering/serving.
2. **Auto-create a default Site per tenant** (idempotent). For each tenant:
   - `platform_hostname` = a slugified, tenant-chosen name on the platform hosting domain (prompt in the UI;
     fall back to a slug of the tenant/business name; reserve permanently).
   - `hosting.type = "platform"`, `custom_domain = null` (→ `indexing.eligibility = "blocked"`).
   - `organization` backfilled from `tenant_profile.brand` / `tenant_profile.business_name` /
     `user_profile.business` per the table above.
   - `pages`: attach every existing page owned by the tenant, keyed by a slug derived from `page.route.slug`
     (collision → suffix), `page_type = "landing"`, `enabled = page.status == "published"`.
3. **Absorb existing custom domains.** For each `tenant_config.custom_domains.domains[]` entry whose
   `target_page_id` belongs to the tenant's default Site, set `Site.hosting.custom_domain` +
   `Site.integration = cloudflare_saas` + `verification` from the existing Cloudflare state. (One custom domain
   per Site initially — matches today's one-domain reality.)
4. **Idempotency + safety:** re-running the backfill must not create duplicate Sites or reattach pages. A page
   already assigned to a Site is skipped. Nothing is deleted from `tenant_profile` / `user_profile` /
   `tenant_config` in this phase.

---

## 4. Backward compatibility

- **Pages without a Site still serve** exactly as today (`{page_id}/index.html`, interim canonical). The
  renderer prefers Site identity when a Site is resolvable, else falls back to the Phase-1 interim behavior.
- **The default Site starts `platform`/`blocked`** → every page renders `noindex` (correct: nothing is on a
  custom domain yet). This is *stricter* than today's `env==prod` rule and is the intended reputation posture;
  it means existing prod pages become `noindex` until their Site connects a custom domain + Connect verifies.
  **This is a deliberate, communicated change** — flag it in the phase's release notes and confirm before
  shipping 2.3 (the gate) to prod.
- **No page_id or offer_id changes.** Pages, offers, and products are untouched; only a new parent is added.

---

## 5. What is explicitly NOT migrated

- Products / offers / prices — the tenant catalog is unchanged; Sites don't own it.
- Page content/sections/theme — stays on Page.
- Billing / users / Stripe / permissions — stays on Tenant.
- The `routes` short-URL system — orthogonal; unchanged.
