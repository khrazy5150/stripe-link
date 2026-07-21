# Site Examples

Concrete `Site` documents for the common shapes, per `schemas/Site.schema.json` (v2) and `plans/SITE_OBJECT.md`.
Timestamps and ids are illustrative.

---

## 1. Free-tier, platform-only (the default every Site starts as)

Served on the reserved platform subdomain, **not indexed** (no custom domain yet → `indexing.eligibility:
blocked`). Fully functional for preview and sharing.

```json
{
  "schema_version": "2026-07-20",
  "document_type": "site",
  "site_id": "site_UpQW786zXMd1",
  "tenant_id": "586173f0-40a1-7053-d421-453cf1de68d0",
  "environment": "live",
  "name": "Axel Mart",
  "status": "active",
  "hosting": { "type": "platform", "platform_hostname": "axel-mart.jbay.uk", "custom_domain": null },
  "organization": {
    "name": "Axel Mart",
    "entity_type": "OnlineStore",
    "description": "Certified pre-owned electronics and refurbished tech.",
    "email": "support@axelmart.com"
  },
  "indexing": { "eligibility": "blocked", "reasons": ["no_custom_domain"] },
  "pages": {
    "/": { "page_id": "page_5oNCbI0r5PU", "page_type": "landing", "label": "MacBook Pro", "enabled": true }
  },
  "created_at": 1784600000,
  "updated_at": 1784600000
}
```

Rendered head on the platform host: `<meta name="robots" content="noindex,nofollow">`, canonical =
`https://axel-mart.jbay.uk/`.

---

## 2. E-commerce store, custom domain, indexed

Custom domain verified + Stripe Connect verified → `eligibility: eligible`. Organization is the single identity
every Product `seller` and the `WebSite`/`Organization` JSON-LD reference.

```json
{
  "schema_version": "2026-07-20",
  "document_type": "site",
  "site_id": "site_UpQW786zXMd1",
  "tenant_id": "586173f0-40a1-7053-d421-453cf1de68d0",
  "environment": "live",
  "name": "Axel Mart",
  "status": "active",
  "hosting": {
    "type": "custom",
    "platform_hostname": "axel-mart.jbay.uk",
    "custom_domain": "axelmart.com",
    "verification": { "verified": true, "verified_at": 1784600500, "method": "cloudflare_saas" }
  },
  "organization": {
    "name": "Axel Mart",
    "legal_name": "Axel Mart LLC",
    "entity_type": "OnlineStore",
    "description": "Certified pre-owned electronics and refurbished tech hardware.",
    "logo": { "url": "https://images.juniorbay.com/tenants/axelmart/logo.webp", "width": 600, "height": 600 },
    "telephone": "+18015550100",
    "email": "support@axelmart.com",
    "address": { "street": "75 S 100 E", "locality": "St. George", "region": "UT", "postal_code": "84770", "country": "US" },
    "same_as": [
      { "url": "https://www.facebook.com/axelmartreal", "verified": true, "method": "reciprocal_link" },
      { "url": "https://www.instagram.com/axelmartreal", "verified": true, "method": "oauth" }
    ],
    "currencies": ["USD"]
  },
  "branding": { "favicon_url": "https://images.juniorbay.com/tenants/axelmart/favicon.png", "colors": { "primary": "#0ea5e9" } },
  "navigation": { "primary": ["/", "/products", "/about", "/contact"], "footer": ["/privacy", "/terms", "/returns"] },
  "seo": { "title_suffix": " | Axel Mart", "google_site_verification": "abc123", "indexnow_key": "d41d8cd9…" },
  "indexing": { "eligibility": "eligible", "reasons": [], "evaluated_at": 1784600600 },
  "analytics": { "google_tag_id": "GT-XXXX", "pixel_id": null },
  "integration": {
    "mode": "cloudflare_saas",
    "cloudflare_saas_config": { "proxy_hostname": "customers.jbay.uk", "custom_hostname_id": "cf_host_123", "ssl_status": "active" }
  },
  "pages": {
    "/": { "page_id": "page_home01", "page_type": "homepage", "label": "Home", "enabled": true },
    "/products": { "page_id": "page_coll01", "page_type": "collection", "label": "All Products", "enabled": true },
    "/products/apple-macbook-pro-13-3-inch": { "page_id": "page_5oNCbI0r5PU", "page_type": "landing", "label": "MacBook Pro", "enabled": true },
    "/about": { "page_id": "page_about1", "page_type": "about", "label": "About", "enabled": true },
    "/contact": { "page_id": "page_contact1", "page_type": "contact", "label": "Contact", "enabled": true },
    "/privacy": { "page_id": "page_priv1", "page_type": "legal", "label": "Privacy", "enabled": true },
    "/terms": { "page_id": "page_terms1", "page_type": "legal", "label": "Terms", "enabled": true },
    "/returns": { "page_id": "page_ret1", "page_type": "legal", "label": "Returns", "enabled": true }
  },
  "routing": { "kvs_key": "site:live:axelmart.com", "published_revision": 4, "published_at": 1784600600 },
  "revision": 4,
  "created_at": 1784600000,
  "updated_at": 1784600600
}
```

Product pages emit `seller.@id = https://axelmart.com/#organization`; canonical =
`https://axelmart.com/products/apple-macbook-pro-13-3-inch`; robots = `index,follow,…`. The `/checkout` and any
`thank_you` pages would carry `page_type` that forces `noindex,follow` even here.

---

## 3. Local service business (LocalBusiness family, multi-page)

`entity_type` selects a specific LocalBusiness subtype; `area_served` + `address` feed LocalBusiness JSON-LD
(the payoff of `plans/LOCAL_SEO_SIGNALS.md`, now sourced from one place).

```json
{
  "schema_version": "2026-07-20",
  "document_type": "site",
  "site_id": "site_element01",
  "tenant_id": "tenant_element",
  "environment": "live",
  "name": "Element Home Services",
  "status": "active",
  "hosting": { "type": "custom", "platform_hostname": "element.jbay.uk", "custom_domain": "elementhomeservices.com", "verification": { "verified": true, "verified_at": 1784600500, "method": "cloudflare_saas" } },
  "organization": {
    "name": "Element Home Services",
    "legal_name": "Element Plumbing, Heating-Air & Electrical LLC",
    "entity_type": "HomeAndConstructionBusiness",
    "telephone": "+14355550100",
    "email": "hello@elementhomeservices.com",
    "address": { "street": "123 Main St", "locality": "St. George", "region": "UT", "postal_code": "84770", "country": "US" },
    "area_served": ["St. George", "Washington County", "Hurricane", "Ivins", "Santa Clara"]
  },
  "navigation": { "primary": ["/", "/plumbing", "/hvac", "/electrical", "/contact"], "footer": ["/privacy", "/terms"] },
  "indexing": { "eligibility": "eligible", "reasons": [] },
  "pages": {
    "/": { "page_id": "page_ehome", "page_type": "homepage", "enabled": true },
    "/plumbing": { "page_id": "page_plumb", "page_type": "landing", "label": "Plumbing", "enabled": true },
    "/hvac": { "page_id": "page_hvac", "page_type": "landing", "label": "HVAC", "enabled": true },
    "/electrical": { "page_id": "page_elec", "page_type": "landing", "label": "Electrical", "enabled": true },
    "/contact": { "page_id": "page_econt", "page_type": "contact", "enabled": true },
    "/privacy": { "page_id": "page_epriv", "page_type": "legal", "enabled": true },
    "/terms": { "page_id": "page_eterms", "page_type": "legal", "enabled": true }
  },
  "created_at": 1784600000,
  "updated_at": 1784600600
}
```

---

## 4. Lead-generation funnel (mixed indexability)

The public landing page is indexable; the thank-you/step pages are `noindex` by `page_type` even though the
Site is eligible.

```json
{
  "site_id": "site_leadgen1",
  "hosting": { "type": "custom", "platform_hostname": "acme-leads.jbay.uk", "custom_domain": "getacme.com", "verification": { "verified": true } },
  "organization": { "name": "Acme", "entity_type": "Organization", "email": "hi@getacme.com" },
  "indexing": { "eligibility": "eligible" },
  "pages": {
    "/": { "page_id": "page_lg_land", "page_type": "landing", "enabled": true },
    "/thank-you": { "page_id": "page_lg_ty", "page_type": "thank_you", "enabled": true }
  },
  "schema_version": "2026-07-20", "document_type": "site", "tenant_id": "tenant_acme",
  "environment": "live", "name": "Acme Leads", "status": "active",
  "created_at": 1784600000, "updated_at": 1784600000
}
```

---

## 5. Multi-site tenant (one billing account, several public sites)

One Tenant, several independent Sites — each its own hostname, Organization, indexing state, and sitemap. They
must **not** cross-link (TP-10): no "our other stores" module between them.

```
Tenant: Acme Inc  (billing/users/Stripe)
  ├── Site site_main       → axelmart.com            (OnlineStore, eligible)
  ├── Site site_clearance  → clearance.jbay.uk   (platform-only, blocked)
  └── Site site_wholesale  → acmewholesale.com        (OnlineStore, eligible)
```

Each is a separate `Site` document sharing `tenant_id`, with distinct `hosting`, `organization`, `pages`, and
`indexing`. Adding a fourth site is a new document — no new architecture.
