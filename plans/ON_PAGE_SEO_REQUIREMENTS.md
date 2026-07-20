# On-Page SEO Requirements — Junior Bay Page Generator

**Scope:** server-rendered public pages emitted by the landing page builder (product/offer pages, lead-gen pages, funnel steps).
**Audience:** page renderer, `Product.schema.json`, `Page.schema.json`, `Site.schema.json`, admin product modal.
**Status:** proposed spec. Requirement IDs are stable; use them in tickets.

---

## 0. Terminology (resolve before implementation)

Two different things are currently both called "brand." Fix this in the schema now.

| Concept | Proposed field | Example | Rendered as |
|---|---|---|---|
| Storefront / tenant name | `tenant.brand_label` | Axel Mart | `.sl-brand-label`, title suffix, `Organization` schema |
| Manufacturer of the goods | `product.brand` | Apple | `Product.brand.name` in JSON-LD, title body |

Every requirement below uses `tenant.brand_label` and `product.brand` explicitly. Never let the renderer fall back from one to the other.

---

## 1. Priority Summary

| ID | Requirement | Priority | Blocking? |
|---|---|---|---|
| SEO-01 | Self-referencing canonical URL | **P0** | Yes — duplicate content at scale |
| SEO-02 | Robots meta + funnel-step `noindex` | **P0** | Yes — upsell pages must not index |
| SEO-03 | Transactional title formula | **P0** | No |
| SEO-04 | Meta description enrichment | **P0** | No |
| SEO-05 | Single `h1` enforcement in renderer | **P0** | No |
| SEO-06 | `product.brand` / `mpn` / `gtin` fields | **P0** | Yes — blocks merchant listings |
| SEO-07 | Complete Product JSON-LD | **P0** | Yes |
| SEO-08 | Minimum unique content gate | **P0** | Yes — thin/doorway risk |
| SEO-09 | Open Graph + Twitter Card | P1 | No |
| SEO-10 | `preconnect` / `preload` for LCP image | P1 | No |
| SEO-11 | BreadcrumbList + on-page breadcrumbs | P1 | No |
| SEO-12 | Organization + WebSite schema | P1 | No |
| SEO-13 | Internal linking (related products, store root) | P1 | No |
| SEO-14 | XML sitemap + robots.txt per Site | P1 | Yes for discovery |
| SEO-15 | IndexNow submission on publish | P1 | No |
| SEO-16 | Webmaster verification tokens | P1 | No |
| SEO-17 | Hide auto-generated SKU in admin modal | P1 | No |
| SEO-18 | Defer head script; a11y label fixes | P2 | No |
| SEO-19 | AggregateRating / Review support | P2 | No |
| SEO-20 | `hreflang` support in Site object | P2 | No |
| SEO-21 | Environment/domain leakage guard | P2 | Yes for staging safety |
| SEO-22 | Seller attribution via tenant-anchored `@id` | **P0** | Yes — see TENANT_PROFILE_REQUIREMENTS.md |

---

## Implementation status

**Phase 1 — SHIPPED (renderer + product schema + admin, no Site object).** Everything buildable without the
Site object / custom-domain routing / tenant profile:

- **SEO-03** title formula: `Buy {condition} {product.name} | {brand_label}` (lead-gen omits "Buy"), 60-char
  degradation ladder, dedupe guard, condition words (`new` omitted, `damaged`→"For Parts"). `brand_label` =
  `offer.presentation.brand`; product name carries the manufacturer. Title no longer re-title-cased (SEO-18
  case consistency — "MacBook" preserved across title/h1/JSON-LD).
- **SEO-04** meta description enrichment: thin (<100) descriptions wrapped `Shop {condition} {name}. {desc}.
  {N-day returns} {CTA}`; deterministic CTA rotation by product_id; idempotent; 155 cap at word boundary.
- **SEO-06** `product.brand`/`mpn`/`gtin` (documents.py, maxLength + GTIN mod-10 check digit).
- **SEO-07** complete Product JSON-LD: `brand`(Brand)/`mpn`/`gtin`, `offers.seller` (OnlineStore stub),
  `hasMerchantReturnPolicy` (from the refund policy on the page), `offers.url`; **price now a decimal string**.
- **SEO-09** Open Graph + Twitter Card; **SEO-10** preconnect/dns-prefetch/preload for the LCP image.
- **SEO-17** admin: SKU collapsed behind a disclosure; "Product identifiers" group (brand/mpn/gtin) with a
  non-blocking GTIN check-digit warning.
- **SEO-18** (partial): price-radio `aria-label`, countdown `aria-live="off"`, case consistency. *Deferred:*
  moving the head script to an external deferred bundle (larger perf refactor).
- **SEO-01/22 (interim):** canonical, `og:url`, `offers.url`, and the seller `@id` are emitted from the page's
  **published-artifact URL** (query/fragment stripped), threaded via `render_page(canonical_url=…)` from the
  publish pipeline and the preview render. The clean root-domain path is the Phase-2 refinement.

**Deferred to Phase 2 (need the Site object / custom-domain routing / tenant profile — see
TENANT_PROFILE_REQUIREMENTS.md):** SEO-02 robots/noindex for funnel/env, SEO-05 outline is already enforced
by the existing heading validator, SEO-08 content gate, SEO-11 breadcrumbs, SEO-12 Organization/WebSite,
SEO-13 internal linking/category pages, SEO-14 sitemap/robots.txt, SEO-15 IndexNow, SEO-16 verification
tokens, SEO-19 reviews, SEO-20 hreflang, SEO-21 domain-leakage guard. The seller `@id` becomes a real
root-domain anchor then.

---

## 2. Head & Metadata

### SEO-01 — Canonical URL (P0)

Every public page emits exactly one self-referencing canonical on the clean path, with all query parameters stripped.

```html
<link rel="canonical" href="https://axelmart.com/products/apple-macbook-pro-13-3-inch-retina-display">
```

**Why this is P0 for Junior Bay specifically:** the page already accepts `?checkout=success`, `?checkout=cancel`, `?booking=success`, `?booking=cancel`, `?funnel_page=`, `?funnel_step=`, `?session_id=`, `?outcome=`, and `?step_id=`. Each is a crawlable duplicate the moment it appears in a link, a referrer log, or an analytics share. Without a canonical, Google chooses which one to index — and it frequently chooses the parameterized one.

**Acceptance criteria**
- Canonical is absolute, HTTPS, includes the Site's configured root domain (never the CloudFront or `dev.` origin).
- Canonical is generated from `Site` routing, not `window.location`.
- Trailing-slash policy is applied consistently and matches what the server actually serves (no canonical → 301 → different canonical chains).

---

### SEO-02 — Robots meta and indexing control (P0)

Add an indexing directive to `Page.schema.json`:

```json
"indexing": {
  "type": "string",
  "enum": ["index", "noindex"],
  "default": "index"
}
```

Renderer rules:

| Page condition | Directive |
|---|---|
| Canonical product/offer page | `index,follow,max-image-preview:large,max-snippet:-1` |
| Funnel step (`funnel_step` present) | `noindex,follow` |
| Upsell / downsell page | `noindex,follow` |
| Thank-you / post-checkout page | `noindex,follow` |
| Page failing the SEO-08 content gate | `noindex,follow` |
| Non-production environment | `noindex,nofollow` |

```html
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
```

`max-image-preview:large` is what allows the product image into the SERP thumbnail. Without it you get a thumbnail or nothing.

---

### SEO-03 — Transactional title formula (P0)

**Approved base formula (purchase intent):**

```
Buy {condition} {product.name} | {tenant.brand_label}
```

**Applies only when** `product.intent === "payment"`. Lead-gen products (`intent === "lead"`) must not receive a "Buy" prefix — it misrepresents the page and depresses CTR from users who bounce immediately, which is itself a negative signal.

**Lead-gen formula:**

```
{product.name} | {tenant.brand_label}
```

#### Condition-word handling — two decisions to confirm

| `condition` | Emitted word | Rationale |
|---|---|---|
| `used` | `Used` | Strong query match — "used macbook pro" is a real head term |
| `refurbished` | `Refurbished` | Same, high commercial intent |
| `new` | *(omit by default)* | "New" is the assumed default; omitting frees ~4 chars for the product name. Expose as `site.seo.include_new_in_title` if you disagree. |
| `damaged` | `For Parts` | "Buy Damaged X" reads as a warning and suppresses clicks. "For Parts or Repair" matches how buyers actually search on eBay/Swappa. |

#### Length degradation ladder

Google truncates around **60 characters / ~580px**. The example title is 63 characters and will be cut. Build the full string, then degrade in this order until it fits 60:

1. Full: `Buy Used Apple MacBook Pro 13.3-Inch Retina Display | Axel Mart` (63)
2. Drop the tenant suffix: `Buy Used Apple MacBook Pro 13.3-Inch Retina Display` (50) ✅
3. If still over: truncate `product.name` at the last word boundary that fits, then re-append the suffix if room remains.

Never truncate mid-word and never emit a trailing ellipsis — Google adds its own.

#### Reference implementation

```js
const CONDITION_WORD = {
  new: null,            // configurable via site.seo.include_new_in_title
  used: 'Used',
  refurbished: 'Refurbished',
  damaged: 'For Parts',
};

const TITLE_MAX = 60;

function buildTitle(product, tenant, site) {
  const isTransactional = product.intent === 'payment';
  const conditionWord = isTransactional
    ? (product.condition === 'new' && !site?.seo?.include_new_in_title
        ? null
        : CONDITION_WORD[product.condition])
    : null;

  const parts = [];
  if (isTransactional) parts.push('Buy');
  if (conditionWord) parts.push(conditionWord);
  parts.push(product.name);

  const core = dedupePrefix(parts.join(' '));       // see below
  const suffix = ` | ${tenant.brand_label}`;

  if ((core + suffix).length <= TITLE_MAX) return core + suffix;
  if (core.length <= TITLE_MAX) return core;
  return truncateAtWord(core, TITLE_MAX);
}

// Guard: tenants who already named the product "Buy X" or "Used X"
function dedupePrefix(title) {
  return title
    .replace(/^Buy\s+(Buy\s+)+/i, 'Buy ')
    .replace(/\b(Used|Refurbished|New)\s+\1\b/i, '$1');
}

function truncateAtWord(str, max) {
  if (str.length <= max) return str;
  const cut = str.slice(0, max);
  return cut.slice(0, cut.lastIndexOf(' ')).trim();
}
```

**Character escaping:** if a tenant uses an inch mark (`13.3"`), emit `&quot;` in any attribute context and prefer the prime character `&#8243;` (″) in `<title>`. Raw `"` inside `<title>` is valid but breaks if the same string is reused in `og:title` content attributes.

**Uniqueness guard:** titles must be unique per Site. If two products in the same Site produce identical titles, append the differentiating price-label or a short SKU suffix.

---

### SEO-04 — Meta description enrichment (P0)

**Approved rule:** when `product.description.length < 100`, wrap it.

```
Shop {condition} {product.name}. {product.description}. Get yours today!
```

Producing:

```html
<meta name="description" content="Shop used Apple MacBook Pro 13.3-Inch Retina Display. Intel Core i5 2.3GHz, 8GB RAM, 128GB SSD, Silver (MPXQ2LL/A) - Mid 2017. Get yours today!">
```

**Constraints to add on top of the base rule:**

1. **Hard cap at 155 characters**, truncated at a word boundary. Over that, Google rewrites the description itself and your formula is wasted.
2. **Idempotency guard** — do not prefix "Shop" if the description already starts with Shop/Buy/Get/Order (case-insensitive). Tenants will paste marketing copy that already opens that way.
3. **Punctuation normalization** — do not emit `..` when the description already ends in a period.
4. **CTA rotation.** `Get yours today!` appearing verbatim on every page across every tenant is a near-duplicate boilerplate footprint. Make it a small rotating set keyed deterministically off `product_id` so it's stable per page but varied across the corpus:
   `Get yours today!` / `Order now.` / `Ships fast — order today.` / `In stock now.`
   Also expose `site.seo.description_cta` so a tenant can override globally.
5. **Free-shipping / return signal.** If the offer has free shipping or a return window, append it before the CTA — it measurably lifts CTR: `Free shipping. 30-day returns.`

Meta description is **not a ranking factor**. It is a click-through-rate factor, and CTR feeds back into rankings indirectly. Frame it that way when documenting it for tenants so expectations are correct.

```js
const DESC_MIN = 100;
const DESC_MAX = 155;
const CTAS = ['Get yours today!', 'Order now.', 'Ships fast — order today.', 'In stock now.'];

function buildDescription(product, offer, site) {
  let desc = (product.description || '').trim();

  if (desc.length >= DESC_MIN) return truncateAtWord(desc, DESC_MAX);

  const alreadyHasCta = /^(shop|buy|get|order)\b/i.test(desc);
  const cond = product.condition && product.condition !== 'new' ? `${product.condition} ` : '';
  const head = alreadyHasCta ? '' : `Shop ${cond}${product.name}. `;

  const body = desc.replace(/[.\s]+$/, '');
  const signals = [];
  if (offer?.shipping?.free) signals.push('Free shipping.');
  if (offer?.refund_policy?.window_days) signals.push(`${offer.refund_policy.window_days}-day returns.`);

  const cta = site?.seo?.description_cta || CTAS[hashToIndex(product.product_id, CTAS.length)];

  return truncateAtWord(`${head}${body}. ${signals.join(' ')} ${cta}`.replace(/\s+/g, ' ').trim(), DESC_MAX);
}
```

---

### SEO-05 — Heading hierarchy (P0)

**Current state:** `.sl-headline h1` and `.sl-hero h1` are both heading-bearing section types. A page composing both emits two `h1` elements. `.sl-brand-label` is already a `<p>` and is correct as-is.

**Rule:** the renderer, not the CSS, enforces the outline.

- The **first** heading-bearing section on the page renders `h1`.
- Every **subsequent** heading-bearing section renders `h2`.
- The `h1` must be the product/offer name — never the tenant brand label.
- `.sl-content-block h2`, `.sl-faq summary h3`, `.sl-section-heading` stay as-is; no level skipping (`h1` → `h3`).
- The `h1` should be substantially similar to the `<title>` minus the "Buy" prefix and tenant suffix.

CSS should be updated to `.sl-headline :is(h1,h2)` / `.sl-hero :is(h1,h2)` so both levels inherit the same visual treatment and the renderer is free to demote.

**Severity note:** Google states multiple `h1`s are not a penalty and it parses the HTML5 outline. Bing and Yahoo weight the `h1` more literally, and a duplicated `h1` obscures the primary topic. Treat this as outline hygiene with a real Bing benefit — not as a Google ranking bug.

**Validation:** add a build-time assertion. Any page emitting `document.querySelectorAll('h1').length !== 1` fails CI.

---

### SEO-09 — Open Graph and Twitter Card (P1)

Not a ranking factor. It determines whether a shared link renders as a rich preview or a bare URL, and shares are how these pages acquire the external links that *are* a ranking factor.

```html
<meta property="og:type" content="product">
<meta property="og:site_name" content="Axel Mart">
<meta property="og:title" content="Buy Used Apple MacBook Pro 13.3-Inch Retina Display">
<meta property="og:description" content="...">
<meta property="og:image" content="https://images.juniorbay.com/products/0UCvYpmAgT2/large.webp">
<meta property="og:image:width" content="1920">
<meta property="og:image:height" content="1920">
<meta property="og:image:alt" content="Apple MacBook Pro 13.3-Inch Retina Display in Silver">
<meta property="og:url" content="{canonical}">
<meta property="product:price:amount" content="353.97">
<meta property="product:price:currency" content="USD">
<meta name="twitter:card" content="summary_large_image">
```

`og:image` must be absolute, ≥1200px on the long edge, and publicly fetchable without auth. Prefer a 1.91:1 crop variant if the media pipeline can generate one — square images get letterboxed by most scrapers.

---

### SEO-10 — LCP resource hints (P1)

The LCP element is a cross-origin image on `images.juniorbay.com`. Every page currently pays a full DNS + TCP + TLS handshake before the hero can begin downloading.

```html
<link rel="preconnect" href="https://images.juniorbay.com" crossorigin>
<link rel="dns-prefetch" href="https://images.juniorbay.com">
<link rel="preload" as="image"
      href="https://images.juniorbay.com/products/0UCvYpmAgT2/medium.webp"
      imagesrcset="https://images.juniorbay.com/products/0UCvYpmAgT2/small.webp 640w,
                   https://images.juniorbay.com/products/0UCvYpmAgT2/medium.webp 1080w,
                   https://images.juniorbay.com/products/0UCvYpmAgT2/large.webp 1920w"
      imagesizes="(min-width: 52rem) 52rem, 100vw"
      fetchpriority="high">
```

Add the same `preconnect` for `fonts.juniorbay.com` on any page that loads a custom font.

---

### SEO-16 — Webmaster verification (P1)

Add to `Site.schema.json`:

```json
"seo": {
  "google_site_verification": { "type": "string" },
  "bing_site_verification":   { "type": "string" },
  "indexnow_key":             { "type": "string" },
  "include_new_in_title":     { "type": "boolean", "default": false },
  "description_cta":          { "type": "string" }
}
```

Emitted only when present. Bing Webmaster Tools verification is separate from Google's and is the only way to submit sitemaps to Bing/Yahoo.

---

### SEO-21 — Environment and domain leakage (P2, but ship the guard early)

The current output hardcodes `dev.juniorbay.com` in the checkout CTA, the `data-checkout-api-base-url`, and all three legal footer links. If a staging page is ever indexed you have a duplicate-content problem plus outbound links to a non-production host.

**Requirements**
- All emitted absolute URLs derive from a single `Site.root_domain` + environment config.
- Non-production environments emit `noindex,nofollow` **and** an `X-Robots-Tag: noindex` response header.
- Non-production environments serve `robots.txt` with `Disallow: /`.
- CI asserts that no production build output contains `dev.`, `staging.`, or a raw CloudFront hostname.

---

## 3. Structured Data

### SEO-06 — New product fields (P0)

Add to `Product.schema.json`:

```json
"brand": {
  "type": "string",
  "maxLength": 70,
  "description": "Manufacturer or product brand (Apple, Sony). Distinct from the storefront name."
},
"mpn": {
  "type": "string",
  "maxLength": 70,
  "description": "Manufacturer Part Number (MPXQ2LL/A)."
},
"gtin": {
  "type": "string",
  "pattern": "^(\\d{8}|\\d{12}|\\d{13}|\\d{14})$",
  "description": "Global Trade Item Number — UPC (12), EAN (13), ISBN (13), ITF-14 (14), or GTIN-8."
}
```

All three optional. All three surface in the admin product modal as optional text inputs (see §5).

**GTIN check-digit validation.** Do not accept an arbitrary 12–14 digit string — an invalid GTIN is worse than no GTIN, because Google will reject the whole merchant listing rather than ignore the field.

```js
function isValidGtin(raw) {
  const s = String(raw || '').replace(/\D/g, '');
  if (![8, 12, 13, 14].includes(s.length)) return false;
  const digits = s.split('').map(Number);
  const check = digits.pop();
  let sum = 0;
  // weights alternate 3,1 from the rightmost body digit
  for (let i = digits.length - 1, w = 3; i >= 0; i--, w = w === 3 ? 1 : 3) {
    sum += digits[i] * w;
  }
  return ((10 - (sum % 10)) % 10) === check;
}
```

Validate on save; show an inline warning rather than hard-blocking (some tenants have legitimate internal codes they'll try to paste here — warn and let them proceed with the field empty).

**Coverage guidance for tenants (UI helper text):** Google's product identifier requirement is satisfied by `gtin`, **or** by `brand` + `mpn` together. Used and refurbished goods frequently have no GTIN — for those, `brand` + `mpn` is the path. `MPXQ2LL/A` in the MacBook example is exactly an MPN and should be captured as one rather than buried in prose.

---

### SEO-07 — Complete Product JSON-LD (P0)

Current output is missing `brand`, `mpn`, `gtin`, `offers.url`, `offers.priceValidUntil`, `offers.seller`, `shippingDetails`, and `hasMerchantReturnPolicy`. As written it will not qualify for product rich results or merchant listings.

**Target template:**

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
  "gtin": "0190198611086",
  "brand": { "@type": "Brand", "name": "Apple" },
  "category": "Electronics",
  "offers": {
    "@type": "Offer",
    "url": "https://axelmart.com/products/apple-macbook-pro-13-3-inch-retina-display",
    "price": "353.97",
    "priceCurrency": "USD",
    "priceValidUntil": "2026-12-31",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/UsedCondition",
    "seller": { "@type": "Organization", "name": "Axel Mart" },
    "shippingDetails": {
      "@type": "OfferShippingDetails",
      "shippingRate": {
        "@type": "MonetaryAmount",
        "value": "0.00",
        "currency": "USD"
      },
      "shippingDestination": {
        "@type": "DefinedRegion",
        "addressCountry": "US"
      },
      "deliveryTime": {
        "@type": "ShippingDeliveryTime",
        "handlingTime": { "@type": "QuantitativeValue", "minValue": 1, "maxValue": 2, "unitCode": "DAY" },
        "transitTime":  { "@type": "QuantitativeValue", "minValue": 2, "maxValue": 5, "unitCode": "DAY" }
      }
    },
    "hasMerchantReturnPolicy": {
      "@type": "MerchantReturnPolicy",
      "applicableCountry": "US",
      "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
      "merchantReturnDays": 30,
      "returnMethod": "https://schema.org/ReturnByMail",
      "returnFees": "https://schema.org/FreeReturn"
    }
  }
}
```

**Field mapping**

| JSON-LD path | Source |
|---|---|
| `name` | `product.name` |
| `description` | `product.description` (raw, not the enriched meta description) |
| `image[]` | media pipeline, largest two variants, absolute URLs |
| `sku` | auto-generated SKU |
| `mpn` / `gtin` | new fields (§SEO-06), omit key entirely if empty |
| `brand.name` | `product.brand`, omit if empty |
| `offers.url` | canonical (§SEO-01) |
| `offers.price` | default price, **decimal string, no currency symbol, no thousands separator** |
| `offers.priceValidUntil` | offer expiry, or +1 year from publish |
| `availability` | inventory state — do not hardcode `InStock` |
| `itemCondition` | `product.condition` → `New`/`Used`/`Refurbished`/`Damaged` `Condition` |
| `seller.name` | `tenant.brand_label` |
| `shippingDetails` | shipping provider config (Shippo/EasyPost/ShipStation/EasyShip) |
| `hasMerchantReturnPolicy` | the refund policy **already rendered on the page** — currently invisible to crawlers |

**Rules**
- Omit keys entirely when the value is empty. Never emit `""`, `null`, or `"N/A"` — an empty required-ish field invalidates the whole item.
- `price` must exactly match the price visible on the page after any countdown expiry logic runs. The current `expireDiscounts()` mutates the displayed price client-side while the JSON-LD keeps the sale price. Google fetches the rendered DOM; that mismatch is a structured-data violation.
- `availability` must reflect real inventory. Hardcoded `InStock` on a sold-out item is a merchant-listing suspension risk.

---

### SEO-11 — BreadcrumbList (P1)

Requires the Site object's subfolder routing. Emit both visible breadcrumbs (crawlable internal links) and the matching JSON-LD.

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://axelmart.com/" },
    { "@type": "ListItem", "position": 2, "name": "Electronics", "item": "https://axelmart.com/electronics" },
    { "@type": "ListItem", "position": 3, "name": "Apple MacBook Pro 13.3-Inch Retina Display" }
  ]
}
```

The final item has no `item` URL by design (it's the current page).

---

### SEO-12 — Organization and WebSite (P1)

Emitted once per Site, on every page. This is what tells search engines the tenant is a real merchant entity rather than an anonymous page farm.

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://axelmart.com/#organization",
  "name": "Axel Mart",
  "url": "https://axelmart.com/",
  "logo": "https://images.juniorbay.com/tenants/axelmart/logo.webp",
  "sameAs": ["https://www.facebook.com/...", "https://www.instagram.com/..."]
}
```

Add `site.social_profiles[]` to `Site.schema.json` to populate `sameAs`. **`sameAs` entries must be ownership-verified before emission** — see TENANT_PROFILE_REQUIREMENTS.md §4.

**Anchor the `@id` to the tenant's own root domain**, never to `juniorbay.com`. See SEO-22.

---

### SEO-22 — Seller attribution (P0)

Every `Offer` carries a seller reference stub identifying which tenant is responsible for the listing.

```json
"seller": {
  "@type": "OnlineStore",
  "@id": "https://axelmart.com/#organization",
  "name": "Axel Mart",
  "url": "https://axelmart.com/"
}
```

**Rules**

- Type is `OnlineStore` (a schema.org subtype of `Organization`), not bare `Organization`.
- The stub carries `@type`, `@id`, `name`, `url` only. The full node is served once per page by the `Organization` block (SEO-12) and in full detail on the tenant profile page.
- **`@id` is anchored to the tenant's own canonical root domain** — `https://{site.root_domain}/#organization`. It must resolve to a page that actually serves the matching `Organization` node.
- `@id` falls back to `https://juniorbay.com/sellers/{tenant_id}` **only** when the tenant has no custom domain. Tenants in that state share the platform's reputation; see TENANT_PROFILE_REQUIREMENTS.md §2 for the consequences and the required mitigations.
- `price` is a **decimal string**, not a number: `"353.97"`.
- No JSON comments. The emitted document must parse as strict JSON.

**Do not treat this as a reputation firewall.** Structured data is self-asserted and unverified; it does not partition spam liability. See TENANT_PROFILE_REQUIREMENTS.md §2.

---

### SEO-19 — Reviews and ratings (P2)

The stylesheet already ships `.sl-testimonial`, `.sl-rating`, `.sl-rating-stars`, and `.sl-rating-meta` — nothing renders them. Wire up a testimonial/review section type and emit `aggregateRating` + `review` from **verified order data only**.

Do not let tenants hand-type an `aggregateRating`. Self-serve platforms that allow this get their entire domain's rich results disabled, and on a shared platform the blast radius could extend across tenants.

---

## 4. Content, Linking, and Crawl Infrastructure

### SEO-08 — Minimum unique content gate (P0)

This is the highest-risk item in the document and the one most likely to be dismissed as "not technical."

The reference page carries roughly **40 words** of unique indexable text. The `h1` and the meta description are the same string. Every other word — trust badges, refund copy, legal footer, section ordering — is template boilerplate identical across every tenant and every product.

At a few hundred pages this is thin content. At scale it is the **doorway page / thin affiliate** pattern that Google's helpful-content and product-review systems are specifically tuned to demote, and demotion can apply site-wide rather than page-by-page.

**Requirements**
1. Compute a `unique_word_count` at publish: total body text minus template boilerplate, minus content identical to any other page in the Site.
2. **Under 150 unique words → the page publishes with `noindex,follow`** and the admin shows a non-blocking "not eligible for search indexing" banner with a checklist of what to add.
3. Prompt tenants for structured, high-value content the template already has CSS for and does not render:
   - **Specifications table** (processor, RAM, storage, year, color, screen size) — this is the content that wins long-tail queries like *"macbook pro 2017 8gb 128gb used"*.
   - **FAQ section** — `.sl-faq` CSS exists, nothing renders it. Wire the section type and emit `FAQPage` JSON-LD.
   - **Condition detail** — for used goods, cosmetic grade, battery cycle count, and what's included in the box. High-conversion and highly unique.
4. Vary trust badges and refund boilerplate per tenant, or move them to a template region that is clearly ancillary.

**Also fix:** both `<img alt>` values are a verbatim copy of the `h1`. Vary the alt for the gallery image or mark it decorative (`alt=""`) if it duplicates the hero.

---

### SEO-13 — Internal linking (P1)

The reference page's only outbound links are three legal footer links. It is an orphan — it can be indexed via sitemap but will accrue no internal link equity.

**Requirements**
- Breadcrumb links (§SEO-11) to store root and category.
- A related-products rail. `.sl-carousel-*` CSS already exists; render 3–6 same-category products with real `<a href>` elements, not JS-only navigation.
- A footer link to the store root and to a category index.
- Category index pages generated from `product.category` — this is the single biggest structural win the Site object enables, since it creates the crawl hierarchy that makes subfolder domain-authority consolidation actually work.

---

### SEO-14 — Sitemap and robots.txt (P1)

Generated per Site, served from the Site's root domain.

```
https://axelmart.com/sitemap.xml
https://axelmart.com/robots.txt
```

**Sitemap**
- Includes only canonical, indexable URLs. Exclude every funnel step, upsell, thank-you page, and any page failing the SEO-08 gate.
- `<lastmod>` reflects real content modification, not a rebuild timestamp — a sitemap where every URL's `lastmod` updates on every deploy is ignored.
- Split at 50,000 URLs / 50MB with a sitemap index.
- Emit an image sitemap extension so product images on `images.juniorbay.com` are discoverable despite the cross-origin host.

**robots.txt**
```
User-agent: *
Disallow: /checkout
Disallow: /*?funnel_step=
Disallow: /*?session_id=
Allow: /

Sitemap: https://axelmart.com/sitemap.xml
```

Use `Disallow` only for crawl-budget control; rely on `noindex` (SEO-02) for actual index exclusion. A `Disallow`d page can still be indexed URL-only if it's linked externally, and a `Disallow`d page's `noindex` is never read.

---

### SEO-15 — IndexNow (P1)

Bing, Yahoo, Yandex, Naver, and Seznam accept IndexNow. It reduces time-to-index for a newly published page from weeks to minutes and it is the single highest-leverage Bing/Yahoo action available.

**Implementation**
- Generate an `indexnow_key` per Site; host it at `https://{root_domain}/{key}.txt`.
- On publish/update/unpublish, POST the changed URL(s) to `https://api.indexnow.org/indexnow`.
- Cloudflare has a native IndexNow integration that fits the existing edge stack — evaluate it before building the submitter.
- Batch endpoint accepts up to 10,000 URLs; debounce bulk imports rather than firing per-product.

Google does not support IndexNow. For Google, rely on sitemap `lastmod` plus the internal linking from SEO-13.

---

## 5. Admin UI — Product Modal

### SEO-17 — Hide the auto-generated SKU (P1)

The SKU is derived from product name + ID and is stable after creation. Exposing an editable input invites tenants to break it, and a changed SKU cascades into structured data, order records, and any downstream feed.

**Change:** collapse it behind a disclosure — `Advanced ▸ Stock keeping unit` — showing the generated value read-only with an "Edit" affordance for the minority who genuinely have their own SKU scheme. Keep the existing helper text.

### New fields

Add three optional inputs to the product modal, grouped under a **Product identifiers** heading placed between the SKU/Condition row and the Tags row:

| Label | Field | Placeholder | Helper text |
|---|---|---|---|
| Product Brand | `product.brand` | `Apple` | The manufacturer of this product — not your store name. Helps your listings appear in shopping results. |
| MPN | `product.mpn` | `MPXQ2LL/A` | Manufacturer Part Number, usually printed on the product or its box. |
| GTIN | `product.gtin` | `012345678905` | UPC, EAN, or ISBN barcode number. Leave blank if this item has none. |

Group-level helper text:

> Optional, but strongly recommended. Search engines match your products to shopping results using either a GTIN, or a Brand and MPN together. Used and refurbished items often have no GTIN — Brand plus MPN works just as well.

Validate GTIN with the check-digit routine in §SEO-06; show an inline warning on failure, do not block save.

---

## 6. Reference `<head>` Output

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <title>Buy Used Apple MacBook Pro 13.3-Inch Retina Display</title>
  <meta name="description" content="Shop used Apple MacBook Pro 13.3-Inch Retina Display. Intel Core i5 2.3GHz, 8GB RAM, 128GB SSD, Silver (MPXQ2LL/A). Free shipping. 30-day returns. Order now.">

  <link rel="canonical" href="https://axelmart.com/products/apple-macbook-pro-13-3-inch-retina-display">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">

  <link rel="preconnect" href="https://images.juniorbay.com" crossorigin>
  <link rel="dns-prefetch" href="https://images.juniorbay.com">
  <link rel="preload" as="image"
        href="https://images.juniorbay.com/products/0UCvYpmAgT2/medium.webp"
        imagesrcset="https://images.juniorbay.com/products/0UCvYpmAgT2/small.webp 640w,
                     https://images.juniorbay.com/products/0UCvYpmAgT2/medium.webp 1080w,
                     https://images.juniorbay.com/products/0UCvYpmAgT2/large.webp 1920w"
        imagesizes="(min-width: 52rem) 52rem, 100vw"
        fetchpriority="high">

  <meta property="og:type" content="product">
  <meta property="og:site_name" content="Axel Mart">
  <meta property="og:title" content="Buy Used Apple MacBook Pro 13.3-Inch Retina Display">
  <meta property="og:description" content="...">
  <meta property="og:image" content="https://images.juniorbay.com/products/0UCvYpmAgT2/large.webp">
  <meta property="og:image:alt" content="Apple MacBook Pro 13.3-Inch Retina Display in Silver">
  <meta property="og:url" content="https://axelmart.com/products/apple-macbook-pro-13-3-inch-retina-display">
  <meta property="product:price:amount" content="353.97">
  <meta property="product:price:currency" content="USD">
  <meta name="twitter:card" content="summary_large_image">

  <link rel="icon" href="https://images.juniorbay.com/icon/favicon.png">
  <link rel="apple-touch-icon" href="https://images.juniorbay.com/icon/favicon.png">

  <meta name="google-site-verification" content="{site.seo.google_site_verification}">
  <meta name="msvalidate.01" content="{site.seo.bing_site_verification}">

  <script type="application/ld+json">{ /* Product — §SEO-07 */ }</script>
  <script type="application/ld+json">{ /* BreadcrumbList — §SEO-11 */ }</script>
  <script type="application/ld+json">{ /* Organization — §SEO-12 */ }</script>

  <style>/* critical CSS — keep inline, this is already correct */</style>
  <script defer src="/assets/page.js"></script>
</head>
```

Note the `<title>` here drops the tenant suffix because the full string exceeded 60 characters — that is the SEO-03 degradation ladder working as specified.

---

## 7. Miscellaneous (SEO-18, P2)

- **Defer the head script.** ~200 lines of JS currently parse-block in `<head>` despite being wrapped in `DOMContentLoaded`. Move to an external deferred bundle; it also lets you cache it across pages instead of re-sending it per page.
- **Label the price radios.** `<input type="radio">` inside `.sl-price-option` has no associated `<label>` and no `aria-label`. Wrap the copy in a `<label for>` or add `aria-labelledby`.
- **`aria-live` on the countdown.** The timer mutates text every second with no announcement policy; `aria-live="off"` is the correct value here to prevent screen readers reading every tick.
- **Case consistency.** The reference page emits "Macbook" in `<title>` and "MacBook" in the `h1` and JSON-LD. Derive all three from the same normalized `product.name` string.
- **`hreflang` (SEO-20).** Not needed today. Reserve `site.locales[]` in `Site.schema.json` now so it isn't a migration later.

---

## 8. Acceptance Checklist

Run per generated page before marking any of the above done.

- [ ] Exactly one `h1`, and it is the product name
- [ ] Heading levels descend without skipping
- [ ] Self-referencing canonical, absolute, production domain, no query string
- [ ] `<title>` ≤ 60 chars, unique within the Site
- [ ] `<meta description>` 100–155 chars, no duplicated CTA across the Site's corpus
- [ ] Product JSON-LD passes Google Rich Results Test with zero errors
- [ ] Product JSON-LD passes Schema Markup Validator with zero warnings on required fields
- [ ] JSON-LD `price` matches the rendered price after countdown expiry logic
- [ ] `brand` + `mpn`, or a check-digit-valid `gtin`, is present
- [ ] `hasMerchantReturnPolicy` matches the rendered refund policy
- [ ] `offers.seller.@id` resolves to a live page serving the matching `Organization` node
- [ ] `offers.seller.@id` is anchored to the tenant's root domain, not `juniorbay.com` (unless no custom domain)
- [ ] `offers.price` is a decimal string, not a number
- [ ] Emitted JSON-LD parses as strict JSON (no comments, no trailing commas)
- [ ] BreadcrumbList present and matches visible breadcrumbs
- [ ] ≥150 unique words, or page is `noindex`
- [ ] At least 3 internal links beyond the legal footer
- [ ] No `dev.`, `staging.`, or raw CloudFront hostname in output
- [ ] Funnel steps and post-checkout pages emit `noindex,follow`
- [ ] URL present in `sitemap.xml`; submitted via IndexNow
- [ ] LCP < 2.5s on mobile 4G (PageSpeed Insights, field or lab)
- [ ] `preconnect` present for every cross-origin asset host
