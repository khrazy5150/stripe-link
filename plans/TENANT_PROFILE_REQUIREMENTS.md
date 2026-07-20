# Tenant Profile & Reputation Isolation Requirements

**Scope:** tenant identity modeling, seller profile pages, and the operational controls that actually limit cross-tenant reputation damage.
**Companion document:** `ON_PAGE_SEO_REQUIREMENTS.md` (§SEO-12, §SEO-22).
**Status:** proposed spec.

---

## 1. Goals — stated and actual

| Stated goal | Achievable with schema? |
|---|---|
| Tell search engines which tenant is responsible for a listing | **Yes** — this is exactly what `Offer.seller` + `@id` is for |
| Help engines disambiguate tenants as distinct commercial entities | **Yes** — entity anchoring works |
| Improve tenant-level rich results and knowledge-panel eligibility | **Partially** — requires corroboration beyond self-assertion |
| **Prevent one bad-actor tenant from getting the platform domain penalized** | **No.** See §2. |

The first three justify building this. The fourth does not, and designing around it will produce false confidence.

---

## 2. Why structured data is not a reputation firewall

**Read this section before the schema sections.** It changes what the schema is for.

### 2.1 Structured data is self-asserted

Nothing in the JSON-LD pipeline is verified. A tenant selling prohibited goods can emit a perfectly-formed `seller` node. Search engines know this, which is why structured data is treated as a *hint for understanding content*, not as evidence in spam adjudication. Markup that contradicts the rendered page is a violation in itself; markup that merely labels ownership carries no evidentiary weight.

### 2.2 Reputation attaches to hostnames and registrable domains

Google's spam systems operate on the eTLD+1 boundary and, secondarily, the hostname. Schema `@id` values are not a partitioning mechanism at any layer of that stack. Bing and Yandex behave the same way.

### 2.3 Google's site reputation abuse policy explicitly closes the subdomain escape hatch

Two things from Google's own documentation and FAQs that bear directly on this architecture:

- Moving content to a subdirectory or subdomain within the same site's domain name does not resolve the underlying issue and may be viewed as an attempt to circumvent the spam policy, which may lead to broader actions against the site in Search.
- Creating new subdomains, subdirectories, or sites with the intention of continuing to violate policies is itself listed under circumvention.

Enforcement has moved from manual-action-only (March 2024) toward algorithmic evaluation, including section-level independence scoring that assesses subfolders and subdomains independently against the parent domain's topical authority profile.

The mitigating observation: enforcement to date has generally applied to the offending sections rather than sitewide. That is a description of observed practice, not a guarantee, and the policy language explicitly reserves broader action.

### 2.4 The proposed `@id` inverts the intended protection

The originally-proposed anchor was:

```
https://juniorbay.com/sellers/586173f0-40a1-7053-d421-453cf1de68d0
```

This places **every tenant's identity node on the platform domain** and links it from every tenant product page. Where tenant pages live on custom domains, this constructs a hub-and-spoke graph in which `juniorbay.com` aggregates third-party commercial content it does not editorially control — a close structural match for the pattern the site reputation abuse policy targets.

**Requirement TP-01:** the tenant `Organization` `@id` is anchored to the tenant's own canonical root domain.

```
https://axelmart.com/#organization
```

`https://juniorbay.com/sellers/{tenant_id}` is permitted **only** as a fallback for tenants with no custom domain, and those tenants are subject to the additional controls in §5.

**Requirement TP-02:** do not publish a crawlable `juniorbay.com/sellers` directory index. A single page linking out to every tenant is the artifact most likely to bind their collective reputation to the platform domain. If an internal directory is needed for support or admin, put it behind auth.

---

## 3. Product-page seller attribution

Corrected version of the product-page markup. Changes from the draft are annotated below the block.

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Apple MacBook Pro 13.3-Inch Retina Display",
  "description": "Intel Core i5 2.3GHz, 8GB RAM, 128GB SSD, Silver (MPXQ2LL/A) - Mid 2017",
  "image": [
    "https://images.juniorbay.com/products/0UCvYpmAgT2/large.webp",
    "https://images.juniorbay.com/products/0UCvYpmAgT2/full.webp"
  ],
  "sku": "APPLE-MACBO-9G0HD34JQJ5",
  "mpn": "MPXQ2LL/A",
  "brand": { "@type": "Brand", "name": "Apple" },
  "offers": {
    "@type": "Offer",
    "url": "https://axelmart.com/products/apple-macbook-pro-13-3-inch-retina-display",
    "price": "353.97",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/UsedCondition",
    "seller": {
      "@type": "OnlineStore",
      "@id": "https://axelmart.com/#organization",
      "name": "Axel Mart",
      "url": "https://axelmart.com/"
    }
  }
}
```

**Changes from the draft**

| # | Change | Reason |
|---|---|---|
| 1 | `@id` moved to the tenant's root domain | §2.4 — the platform-domain anchor inverts the isolation goal |
| 2 | `"price": 353.97` → `"price": "353.97"` | Float serialization round-trips badly; string matches Google's reference examples |
| 3 | `Organization` → `OnlineStore` | More specific, accurate schema.org subtype; better entity classification |
| 4 | Added `seller.url` | An `@id` alone gives crawlers no navigable path to the entity |
| 5 | Removed `/* comments */` | Invalid JSON — will fail parsers if it survives into a template |
| 6 | Added `mpn`, `brand`, `offers.url` | Per `ON_PAGE_SEO_REQUIREMENTS.md` §SEO-06, §SEO-07 |

**Requirement TP-03:** the `@id` must resolve. A crawler following `https://axelmart.com/#organization` must land on a page that emits a matching `Organization`/`OnlineStore` node with the same `@id`. A dangling `@id` is worse than no `@id` — it asserts an entity that doesn't exist.

---

## 4. The tenant profile page

### 4.1 Placement

**Requirement TP-04:** the tenant profile page is served from the tenant's own root domain.

| Tenant configuration | Profile URL | `@id` |
|---|---|---|
| Custom domain (`dns`, `cloudflare_saas`, `cloudflare_partial`, `worker`) | `https://axelmart.com/about` | `https://axelmart.com/#organization` |
| WordPress integration | `https://axelmart.com/about` | `https://axelmart.com/#organization` |
| No custom domain (short-URL / platform-hosted only) | `https://juniorbay.com/sellers/{tenant_id}` | same URL | 

The fragment identifier (`#organization`) is deliberate: it lets the entity `@id` be stable even if the profile page later moves from `/about` to `/store` or `/seller`.

### 4.2 Page type

**Requirement TP-05:** use `CollectionPage` (or `WebPage`) with an `OnlineStore` `mainEntity`.

`ProfilePage` is valid schema.org and won't hurt, but Google's documented `ProfilePage` support targets creator and author profiles feeding perspectives/discussion features — it will not produce a merchant rich result. If the profile page also lists the tenant's products, `CollectionPage` is the more accurate type and pairs naturally with an `ItemList` of listings.

### 4.3 Corrected profile markup

```json
{
  "@context": "https://schema.org",
  "@type": "CollectionPage",
  "url": "https://axelmart.com/about",
  "dateCreated": "2024-03-11",
  "dateModified": "2026-07-19",
  "mainEntity": {
    "@type": "OnlineStore",
    "@id": "https://axelmart.com/#organization",
    "name": "Axel Mart",
    "url": "https://axelmart.com/",
    "description": "Premium refurbished electronics and certified pre-owned tech hardware.",
    "logo": {
      "@type": "ImageObject",
      "url": "https://images.juniorbay.com/tenants/axelmart-logo.png",
      "width": 600,
      "height": 600
    },
    "email": "support@axelmart.com",
    "telephone": "+1-801-555-0100",
    "address": {
      "@type": "PostalAddress",
      "addressLocality": "Salt Lake City",
      "addressRegion": "UT",
      "addressCountry": "US"
    },
    "hasOfferCatalog": {
      "@type": "OfferCatalog",
      "name": "Axel Mart product catalog",
      "itemListElement": [
        { "@type": "OfferCatalog", "name": "Apple" },
        { "@type": "OfferCatalog", "name": "Dell" }
      ]
    },
    "sameAs": [
      "https://www.facebook.com/axelmartreal",
      "https://www.instagram.com/axelmartreal"
    ]
  }
}
```

### 4.4 Field-by-field notes on the draft

**`brand` → replaced with `hasOfferCatalog`.**
Schema.org defines `Organization.brand` as the brand(s) *maintained or owned* by the organization. Axel Mart resells Apple and Dell; it does not own them. Asserting brand ownership is a false identity claim — the same category of signal that gets structured data ignored or penalized, and a plausible trademark complaint vector from the brand owners themselves. `hasOfferCatalog` expresses "these are the brands I carry" accurately.

**`founder` → optional, opt-in, never auto-populated.**
This is a named real person, i.e. PII. Requirements:
- Off by default. Tenant must explicitly opt in with a clear explanation that the name will be publicly visible and indexed.
- **Never** populate from Stripe Connect KYC data. That information was collected under an identity-verification consent basis and repurposing it for public SEO markup is a consent violation regardless of jurisdiction.
- Free-text field the tenant fills in themselves, or nothing.

**`sameAs` → requires ownership verification.**
Unverified `sameAs` is an impersonation vector: a bad-actor tenant can assert identity with any brand's real social profiles, or point at malicious destinations, using your domain's markup to do it. Requirements:
- Verify ownership before emission. Acceptable methods, in descending order of strength: OAuth connection to the platform; a verification token the tenant posts in the profile bio; a reciprocal link from the profile back to the tenant's root domain.
- Whitelist the destination hosts (major social platforms, Crunchbase, BBB, Wikidata). Reject arbitrary URLs.
- Any rendered outbound link to a `sameAs` target carries `rel="nofollow ugc noopener"`. Cap at 6 entries.

**`logo` → use `ImageObject`, not a bare URL string.**
Bare string works, but `ImageObject` with explicit dimensions is required for some logo rich results and prevents ambiguity. Minimum 112×112px; square or near-square.

**`address` / `telephone` / `email` → strongly recommended, and the highest-value trust fields on this page.**
Verifiable contact details are the single strongest corroboration signal for a commercial entity, and their absence is a well-known low-trust marker for e-commerce. This matters more for real-world trust and conversion than any of the identity plumbing above. Make them required for index eligibility (§5).

---

## 5. What actually limits cross-tenant reputation damage

Ordered by effectiveness. Everything below the first item is mitigation, not isolation.

### TP-06 — Separate registrable domain per tenant (P0)

The only boundary search engines genuinely recognize. Tenants on their own eTLD+1 are reputationally independent; tenants on `*.juniorbay.com` or `juniorbay.com/*` are not, per §2.3.

**Product implication:** custom domain setup should be strongly encouraged during onboarding, not deferred as an advanced setting. Consider making it a prerequisite for index eligibility.

### TP-07 — Separate Search Console property per tenant domain (P0)

Verified to the tenant, not to the platform. Manual actions and security notices then land in the tenant's account. This also creates a paper trail that the platform is not the publisher of record.

Emit `site.seo.google_site_verification` / `bing_site_verification` per Site (already specced as `ON_PAGE_SEO_REQUIREMENTS.md` §SEO-16).

### TP-08 — Gate index eligibility on Stripe Connect verification (P0)

**The highest-leverage control available, and the platform already has the infrastructure.**

Stripe Connect onboarding performs real KYC/KYB. Bind indexing to it:

| Connect account state | Page indexing |
|---|---|
| Not started / incomplete | `noindex,nofollow` |
| Pending verification | `noindex,follow` |
| `charges_enabled: true`, no restrictions | `index,follow` |
| Restricted / rejected / disabled | `noindex,nofollow` + delist from sitemap + IndexNow removal |

This converts an unbounded reputation problem into a bounded onboarding gate, and gives a defensible answer to "what first-party oversight do you exercise?" — which is the question the site reputation abuse policy actually asks.

Add to `Site.schema.json`:

```json
"indexing_eligibility": {
  "type": "string",
  "enum": ["blocked", "pending", "eligible", "revoked"],
  "default": "blocked"
}
```

Recompute on every Connect webhook. Revocation must trigger sitemap removal and an IndexNow submission within minutes, not on the next scheduled rebuild.

### TP-09 — Prohibited items policy and enforcement (P0)

Unglamorous and load-bearing. Minimum viable version:

- A published prohibited-items list in the tenant terms.
- Automated screening of `product.name`, `description`, `category`, and `tags` against a keyword/classifier list at publish time. High-confidence matches block publication; medium-confidence flag for review.
- A reporting endpoint and a documented takedown SLA.
- On takedown: `noindex` immediately, `410 Gone` after a grace period (not `404` — `410` de-indexes materially faster), and an IndexNow submission.

Retain an audit log of moderation decisions per listing. If a manual action ever arrives, that log is the reconsideration request.

### TP-10 — Link hygiene (P1)

- Every tenant-controlled outbound link (`sameAs`, tenant-authored content links, social icons) carries `rel="nofollow ugc noopener"`.
- No PageRank flows from platform-owned pages to tenant storefronts, and none between tenants.
- No public cross-tenant "related stores" or "other sellers" modules. Related-products rails (`ON_PAGE_SEO_REQUIREMENTS.md` §SEO-13) stay **within a single tenant's Site**.

### TP-11 — Separate the platform's own content (P1)

`juniorbay.com` marketing, docs, blog, and legal pages must not share a hostname with tenant-generated storefronts. If any tenant is ever hosted on `juniorbay.com/*`, the platform's own editorial content is sharing a domain with unmoderated third-party commercial pages — which is the fact pattern in §2.3.

Preferred: tenant fallback hosting on a distinct registrable domain (e.g. `juniorbaystores.com`) that carries no platform marketing content and whose reputation the business can afford to lose.

---

## 6. Schema additions

`Site.schema.json`:

```json
"organization": {
  "type": "object",
  "properties": {
    "legal_name":  { "type": "string" },
    "description": { "type": "string", "maxLength": 500 },
    "logo_url":    { "type": "string", "format": "uri" },
    "email":       { "type": "string", "format": "email" },
    "telephone":   { "type": "string" },
    "address": {
      "type": "object",
      "properties": {
        "locality":    { "type": "string" },
        "region":      { "type": "string" },
        "country":     { "type": "string", "minLength": 2, "maxLength": 2 }
      }
    },
    "founder_name": {
      "type": "string",
      "description": "Optional, opt-in, tenant-entered. Never populated from KYC data."
    },
    "carried_brands": {
      "type": "array",
      "items": { "type": "string" },
      "maxItems": 20,
      "description": "Brands the tenant resells. Emitted as hasOfferCatalog, NOT as Organization.brand."
    },
    "same_as": {
      "type": "array",
      "maxItems": 6,
      "items": {
        "type": "object",
        "properties": {
          "url":      { "type": "string", "format": "uri" },
          "verified": { "type": "boolean", "default": false },
          "method":   { "type": "string", "enum": ["oauth", "bio_token", "reciprocal_link"] }
        }
      },
      "description": "Only entries with verified=true are emitted into sameAs."
    }
  }
},
"indexing_eligibility": {
  "type": "string",
  "enum": ["blocked", "pending", "eligible", "revoked"],
  "default": "blocked"
}
```

---

## 7. Out of scope — flag for counsel

Marketplace liability for illicit tenant listings is a legal question, not an SEO one, and none of the controls above address it:

- Platform liability posture (Section 230 in the US; the EU Digital Services Act if there are EU tenants or buyers, which carries notice-and-action and trader-traceability obligations).
- Stripe's own prohibited-business rules and platform-liability terms under Connect — these may impose obligations stricter than anything here, and violating them is an existential risk to the payment rails.
- Trademark exposure from tenants asserting brand associations (the `Organization.brand` issue in §4.4 has a legal dimension as well as a technical one).

**This document is engineering guidance, not legal advice.** Get counsel on the above before scaling tenant onboarding.

---

## 8. Acceptance checklist

- [ ] `offers.seller.@id` anchored to the tenant's root domain
- [ ] `@id` resolves to a live page emitting a matching `OnlineStore` node
- [ ] `seller` stub is `@type` / `@id` / `name` / `url` only
- [ ] `price` emitted as a decimal string
- [ ] Profile page served from the tenant's own domain
- [ ] `Organization.brand` is **not** used for resold brands; `hasOfferCatalog` used instead
- [ ] `founder` absent unless explicitly opted in; never sourced from KYC data
- [ ] Every `sameAs` entry ownership-verified; host whitelisted; ≤6 entries
- [ ] All tenant-controlled outbound links carry `rel="nofollow ugc noopener"`
- [ ] No public `/sellers` directory index
- [ ] Indexing gated on Stripe Connect verification state
- [ ] Connect revocation triggers `noindex` + sitemap removal + IndexNow within minutes
- [ ] Prohibited-items screening runs at publish time with an audit log
- [ ] Takedown path emits `410`, not `404`
- [ ] Platform marketing content does not share a hostname with tenant storefronts
- [ ] Emitted JSON-LD parses as strict JSON
