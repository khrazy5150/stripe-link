# Google Merchant Primitive

**Status** — Design draft, not built. Direction set by the author on November 25, 2026. Revised November 27, 2026 after a review against the codebase (§13). Next gate: Phase 0, Junior Bay's own Merchant Center advanced account, Merchant API developer registration, and test accounts.

**Dashboard** — Attention → Google Shopping (new menu entry, key `googleMerchant`)

**Provider** — Google Merchant Center through the Merchant API (v1). The Content API for Shopping reached its sunset on August 18, 2026 and is not an option. [Content API sunset](https://developers.google.com/shopping-content/guides/sunset) · [Merchant API](https://developers.google.com/merchant/api)

Junior Bay lists a tenant's physical products on Google: free listings on Search, Shopping, Images, YouTube and Maps, and later the catalog behind Shopping and Performance Max campaigns. The tenant owns the Merchant Center account. Junior Bay builds the catalog from data the tenant already keeps in Products, Sites, Shipping and refund policies, keeps it in sync as that data changes, and translates Google's diagnostics into fixes inside the dashboard.

## 0. Decisions already made

| Decision | Detail |
| --- | --- |
| Standalone module | Google Merchant is its own primitive, like Shipping and Ads. It works with no Ads connection and no Ads entitlement. Ads may later read it, and it never reads Ads. |
| Free listings are free | The module is available on every plan, including `free`. Paid placement (Shopping and Performance Max) is an Ads feature and follows the Ads entitlements in `ADS_PRIMITIVE.md`. Listing needs a claimed website (§2.2). Today that means a custom domain, which the Free plan does not include, so open decision 8 settles whether Free tenants can actually list. |
| Tenant-owned accounts | Each tenant brings an existing Merchant Center account or Junior Bay creates one for them. Junior Bay never holds tenants' products in its own account. |
| Full Google surface | Every capability the Merchant API offers a merchant is reachable from the module. Presets cover the common case, and Advanced exposes the rest at the tenant's own risk (§5). |
| Products, not pages | The unit of listing is the Product. A page is only the landing link Google sends shoppers to. Landing-page goals do not control listing. |
| On by default after one opt-in | Connecting is a deliberate tenant action, since Google requires the merchant to accept its Terms of Service. After that, every eligible product is listed unless the tenant hides it. |
| Agency-ready ownership | Connections belong to the tenant and record `connected_by`. See the ownership rules in a future `AGENCY_MODE.md`. |

## 1. Product scope

### What the tenant sees

One menu entry, **Google Shopping**, with four tabs. The screen subtitle reads "Powered by Google Merchant Center" so tenants who know the product recognise it.

| Tab | Purpose |
| --- | --- |
| Overview | Connection and verification state, products live / pending / need a fix / hidden, the next action, and account-level issues. Before connection it is the onboarding checklist. |
| Products | Every product with its Google status per destination (free listings, Shopping ads), its issues, and Include / Hide controls. Filters by status. Bulk include and hide. |
| Issues | Account and product issues as Google renders them for third-party apps, with the fix action next to each (§4.3). |
| Settings | A preset picker and an Advanced section (§5). |

Every product row in the main **Products** screen also gets a small Google badge (Live, Pending, Needs a fix, Hidden, Not eligible) that links to this module. Fixes happen in the product editor, because the product is where the data lives.

### What gets listed

A product is **eligible** when all of the following are true. Ineligible products are never sent, and the Products tab shows the reason.

1. It is a physical product: not a service, booking, webinar, event, course or lead-capture product, and with no `digital_asset`. Digital goods are excluded in the first release (open decision 6).
2. `status` is `active`, not `archived`.
3. It is Live-mode data. Test-mode products only ever reach Merchant Center test accounts (§2.4).
4. It has a **listing page**: a published page on the Site the connection claims (§2.1), and that Site's `indexing.eligibility` is `eligible`, meaning a verified custom domain and a verified Stripe Connect account (`SITE_OBJECT.md` §2.3). A page on any other Site is Not eligible, because Google disapproves a landing page whose domain differs from the claimed website. Unless Phase 0 shows a platform hostname can be claimed (open decision 8), a tenant without a custom domain sees "Connect your domain to list on Google" as the first checklist step.
5. It has a price, a title, a description and at least one image.
6. It has a one-time price. Products sold only on a recurring price are Not eligible in the first release (open decision 10).
7. The tenant has not hidden it (`listing.excluded`).

A product that passes 1–4 but fails 5 shows **Needs a fix** with the missing field, rather than disappearing.

### Defaults

- Connecting lists every eligible product. A confirmation precedes the first sync: "We'll list 312 products on Google. 18 need a fix first."
- New products are listed automatically under the Recommended preset. The Manual approval preset holds them in **Ready to list** until the tenant approves them in a batch.
- A product hidden from Google stays hidden through edits, imports and preset changes.

## 2. Junior Bay architecture

| Owner | Responsibility |
| --- | --- |
| `stripe-link` dashboard | Render the Google Shopping view and the per-product badge. Use the existing authenticated Attention API client (`dashboard/src/api/attention.js`). |
| `../attention` | Host **Merchant Core** and the Google Merchant adapter, with their own records, queue, worker, schedules and alarms. Merchant Core is a peer of Advertising Core, not part of it. |
| `stripe-link` commerce | Own Products, Offers, Sites, Pages, Shipping configuration and refund policies. Write a **listing snapshot** per product when its listing page publishes, from the same code that renders the page's Product structured data (§3.3). No new API routes. |
| `../sam/image-processing` | Serve product images at stable public URLs that Google can crawl. No new media pipeline (`docs/EXTERNAL_SERVICES.md`). |
| Google Merchant Center | Own the merchant account, policy review, product processing, serving and reporting. |

This follows the boundary set in `ADS_PRIMITIVE.md` §2: Google calls and their workers stay out of the commerce runtime, commerce stays the source of truth, and Attention only ever holds derived listing state.

### 2.1 Account model

Junior Bay operates one Merchant Center **advanced account** per release as the service provider. Tenant accounts are standalone, merchant-owned accounts linked to it through the `accountManagement` service. Google recommends this structure for ecommerce platforms and channel partners, and it keeps one tenant's policy problem from affecting any other tenant. Junior Bay does **not** use `accountAggregation` sub-accounts for tenants. [Account relationships](https://developers.google.com/merchant/api/guides/accounts/relationships) · [Create accounts](https://developers.google.com/merchant/api/guides/accounts/sub-accounts) · [Advanced accounts](https://support.google.com/merchants/answer/188487)

| Path | Flow |
| --- | --- |
| **Create** (no existing account) | The tenant signs in with Google once (scope `https://www.googleapis.com/auth/content`). Junior Bay calls `accounts.createAndConfigure` with the tenant as admin user, `accountManagement` with Junior Bay as provider, and verification mail suppressed. The tenant accepts the Terms of Service with their own credentials in the same session. The link is established on creation. |
| **Link** (existing account) | The tenant signs in with Google and picks an account they administer. Junior Bay proposes the `accountManagement` service, and the tenant's session approves it. Junior Bay then inspects existing data sources and products (§2.5). |
| **Disconnect** | The tenant chooses whether Junior Bay deletes the products it submitted now, or leaves them to expire in 30 days. Junior Bay then removes its service link and deletes its stored tokens. The account stays the tenant's. |

**One claimed website per account.** A Merchant Center account claims one website, and every product's landing page must be on it. A tenant can run several Sites on different domains (up to 3 on Basic and 10 on Pro), so each connection is bound to one Site: by default the tenant's default Live Site from `GET_STARTED_WIZARD.md`. Products whose listing page sits on another Site are Not eligible with "This page is on a different website than your Google listing". Open decision 9 settles whether a tenant may connect a second account for a second Site.

After onboarding, Junior Bay operates the account server-to-server with its own service account through the provider link, so syncs and refreshes run while the tenant is signed out. The tenant's OAuth grant is kept only where Google requires merchant credentials (Terms of Service changes and re-approvals), encrypted with the same KMS pattern as the Ads grants. Phase 0 confirms exactly which operations need merchant credentials. [Service provider setup](https://developers.google.com/merchant/3p/quickstart)

### 2.2 Website verification and claim

Google requires a verified and claimed website before products can serve. Junior Bay serves the tenant's custom domain, so it can place Google's site-verification token itself (meta tag on the Site's home page, or a well-known file through the Cloudflare Worker) and then call `accounts.homepage.claim`. Tenants never touch DNS records or HTML for this. If another Merchant Center account already holds the claim, the tenant sees the conflict and can choose to take the claim over. Phase 0 confirms the verification method available to a service provider. It also confirms two things that decide open decision 8. First, can a merchant claim a platform hostname such as `{label}.jbay.uk`? Junior Bay controls that host, so it could place the token the same way. Second, does Google's shopping crawler accept landing pages served with `X-Robots-Tag: noindex`, which every platform-hostname page carries? [Homepage resource](https://developers.google.com/merchant/api/guides/compatibility/homepage)

### 2.3 One data source, owned by Junior Bay

Junior Bay creates one primary API data source per account and target (feed label, country and language), and only touches products in data sources it created. Products in API data sources can be inserted, updated and deleted. File-based data sources cannot be changed through the API, which is why imported or legacy feeds are left alone (§2.5). [Add and manage products](https://developers.google.com/merchant/api/guides/products/add-manage)

Junior Bay turns **autofeed** off on accounts it manages so Google does not crawl the Site and create duplicate products. **Automatic improvements** (Google correcting price, availability and images from the landing page) stay on in the Recommended preset because they rescue items from disapproval.

### 2.4 Test and Live

Keep the AWS release channel distinct from the dashboard's Test/Live data mode, exactly as Ads does.

- **Test mode** connects to Merchant Center **test accounts**, which are isolated from live serving. Junior Bay creates a standalone test account, converts it to an advanced test account, and creates tenant test accounts under it with `createAndConfigure`. Each Google account can create at most five test accounts, so Sandbox uses a small pool assigned per pilot tenant. [Test accounts](https://developers.google.com/merchant/api/guides/accounts/test-accounts)
- **Live mode** connects to the tenant's real account, and only from the production release.
- Developer registration (`registerGcp`) is a one-time step on Junior Bay's **production** advanced account. Test accounts cannot be registered. [Developer registration](https://developers.google.com/merchant/api/guides/quickstart/registration)
- Use separate Google Cloud projects and service accounts for dev and prod. Key every record and job by tenant and mode.

### 2.5 Bringing an existing account

A tenant who already lists products through Shopify, WooCommerce or a spreadsheet feed will have products Junior Bay did not create. Listing the same item twice causes duplicate-product issues. On link, Junior Bay compares the existing products' links and identifiers against the tenant's Junior Bay catalog and offers:

1. **Take over** (recommended when the store is moving to Junior Bay): Junior Bay lists the matched products and tells the tenant which old data source to remove in Merchant Center. Junior Bay does not delete data it did not create.
2. **Only what's new:** Junior Bay lists only products with no match.

## 3. Catalog sync

### 3.1 Product to Google mapping

Commerce writes a **listing snapshot** per product (§3.3): the Product, its canonical listing page and offer, the Site, the price the page shows, and the resolved shipping and refund policy. Merchant Core maps it to a `ProductInput`. Price, link and identity come only from commerce data, never from AI enrichment (`OFFER_SEMANTIC_P4.md` guardrails).

| Google attribute | Source | Notes |
| --- | --- | --- |
| `offerId` | `sku`, else `product_id`; variants get a deterministic suffix | Stable forever. Renaming a product never re-identifies it. |
| `title`, `description` | Product name and description; Advanced may override | The semantic model may suggest a title. The tenant's value wins. |
| `link` | Canonical URL of the listing page on the Site's canonical hostname | Locked (§5.3). |
| `imageLink`, `additionalImageLinks` | `images` through image-processing public URLs | |
| `price` | The price the listing page shows for this product: the one-time price the renderer selects for the page's Product structured data (`runtime/html.py`) | Locked (§5.3). Products carry a `prices` array and can be recurring. Recurring-only products are excluded (open decision 10). |
| `salePrice`, `salePriceEffectiveDate` | Only when the listing page itself shows the discounted price and dates | Coupons that need a code are never a sale price. Use Promotions instead (§6). |
| `availability`, `availabilityDate` | New per-product listing field, default `in_stock` | Junior Bay has no inventory counts yet. `out_of_stock`, `preorder` and `backorder` are tenant-set. |
| `condition` | `condition` | Already constrained to `new`, `refurbished`, `used`, `damaged`. `damaged` is never sent; the product shows Needs a fix. |
| `brand`, `gtin`, `mpn`, `identifierExists` | Product identifier fields (`ProductIdentifiersField.vue`, validated in `domain/documents.py`) | `identifierExists=false` only when the tenant marks the item custom or handmade. Never inferred. |
| `googleProductCategory`, `productTypes` | `product_category`, `product_type`, semantic `taxonomy` | |
| `itemGroupId`, `size`, `color` | `variants` | One Google item per size/colour combination, grouped. Variants are labels only, with no per-variant SKU, price, image or stock. Every combination therefore shares the product's price and images, which Google may flag for apparel colours. This is a known limitation until variants gain their own images. |
| `shippingWeight`, dimensions | `fulfillment.weight_lb`, `fulfillment.dimensions` | |
| Shipping and returns | Account-level settings (§3.2), plus a per-item shipping label and return-policy label where the item differs from the account default | A product's own refund policy overrides the tenant default, and shipping can differ per Site. Phase 0 confirms the label attributes. |
| `customLabel0`–`4` | Advanced only | For tenants who will later segment Shopping campaigns. |

**Bundles:** a bundle offer emits nothing of its own. Each real product in it is listed under its own canonical page, as the multi-entity rule in `OFFER_SEMANTIC_P4.md` P4.2b already requires.

**Canonical listing page:** a product can appear on several pages. The tenant picks one as its listing page in the product editor. The default is the most recently published single-product page on an eligible Site. A product with no candidate is Not eligible with "Publish a page for this product."

### 3.2 Account settings from tenant data

| Merchant Center setting | Junior Bay source |
| --- | --- |
| Business info (name, address, customer service) | `organization` of the claimed Site only. Tenant-profile identity fields are retired (`SITE_AS_BUSINESS_IDENTITY.md`). |
| Shipping settings | `ShippingConfig` zones and `rate_options`, resolved for the claimed Site through the `ShippingConfig.sites` override map, translated into services and rate tables, with handling and transit times |
| Online return policies | `TenantConfig` `refund_policies.physical` (window, condition, return method, return shipping, restocking fee) as the account default. Each distinct product-level override becomes a labelled policy. An unset `physical` class resolves to nothing, so the checklist asks the tenant to set a returns policy before the first sync. |
| Programs (free listings, Shopping ads) | Free listings enabled on connect. Shopping ads enabled only when the tenant later links Google Ads. |

When a source changes, Merchant Core resends the account setting, not every product.

### 3.3 Change pipeline

Only the Pages table has a DynamoDB stream today, and stripe-link has little route budget left (231 route events) or template headroom. So the snapshot is produced where pages publish, instead of being served over a new API:

1. When a listing page publishes, `page_publish` writes one listing snapshot per product to a new stripe-link `ListingSnapshots` table (keyed by tenant, mode and product). It does this from the same function that renders the page's Product structured data. The feed and the page's markup then come from one computation, which is what the listing page standard (§4.4) requires.
2. Writes that change a listing without republishing the page (product, price, offer, shipping configuration, refund policy) trigger a republish of the affected listing pages. Prices and policies already appear in the page's markup, so the page should republish for these changes anyway. A custom-domain verification already republishes the Site's pages (`sites.py` `_republish_site_pages`). A Stripe Connect eligibility change, recomputed in `account.updated`, must do the same; confirm this in Phase 2.
3. Attention consumes the snapshot table's stream cross-stack. This is the same direction as its existing scoped reads of stripe-link tables, and adds one table and stream to stripe-link with no routes. An SQS queue in Attention coalesces per tenant, mode and product within a short window (target 60 seconds), so a burst of edits produces one update.
4. The worker maps the snapshot and compares a hash of the mapped `ProductInput` with the last one sent. Unchanged items are skipped.
5. Changed items are inserted (an insert with the same identity replaces the item) through batched requests. Products that became archived, hidden or ineligible are deleted from Junior Bay's data source.
6. Outcomes are recorded per product, with Google's request ID and redacted diagnostics. Retries use bounded backoff and a dead-letter queue, with alarms on the existing Attention alert topic. That topic is named for Ads today (`jb-attention-ads-alerts-<env>`), so rename it to a service-wide name when Merchant adds its alarms.

A **bulk import** (`PRODUCT_BULK_IMPORT.md`, to be written) republishes the affected listing pages as one batch, and Merchant Core syncs the resulting snapshots in batched requests instead of one request per product.

### 3.4 Refresh sweep

Products sent through the API expire 30 days after their last refresh. A daily scheduled sweep resends every listed product that has not been sent in seven days, so a product the tenant never edits is still refreshed at least four times before it would expire. [Expiration date](https://support.google.com/merchants/answer/6324499)

### 3.5 Lifecycle mapping

| Junior Bay state | Google action |
| --- | --- |
| Temporarily unavailable | Keep listed with `availability: out_of_stock` |
| Back in stock | Update to `in_stock` |
| `status: archived` (discontinued) | Delete from Merchant Center. The Junior Bay product and its order history remain. Unarchiving lists it again. |
| Hidden from Google | Delete from Merchant Center. Stays hidden until the tenant includes it. |
| Listing page unpublished or Site loses eligibility | Delete. The product shows Not eligible with the reason. |
| Product deleted in Junior Bay | Delete. |

## 4. Status, issues and notifications

### 4.1 Push notifications

Merchant Core subscribes to `PRODUCT_STATUS_CHANGE` notifications for all accounts managed by Junior Bay's advanced account, plus account-service change notifications so a tenant revoking the link in Merchant Center is noticed immediately. The callback is a public HTTPS route in the Attention stack (`/merchant/google/notifications`), decoded and verified before any write. [Notifications](https://developers.google.com/merchant/api/guides/notifications/overview) · [Product status changes](https://developers.google.com/merchant/api/guides/notifications/product-status-changes)

### 4.2 Reconciliation

Notifications can be missed. A scheduled job reads aggregate product statuses per account and reconciles them against stored listing state, with drift alarms like the Ads worker's.

### 4.3 Issues in the tenant's language

Google's issue resolution service returns account and product issues already written for display in third-party apps, with the available actions and the reasons an action is unavailable. The Issues tab renders that content rather than inventing explanations. Where the fix is Junior Bay data (a missing GTIN, a shipping gap, a price mismatch), the issue links straight to the field in the product editor or settings. In-app actions that need Google's allowlist (`triggeraction`) are requested in Phase 0 and fall back to Google's external link until granted. [Issue resolution](https://developers.google.com/merchant/api/reference/rpc/google.shopping.merchant.issueresolution.v1)

### 4.4 Junior Bay checks before Google

Many disapprovals are predictable. Merchant Core runs the same checks before sending so the tenant sees "Needs a fix" in seconds instead of days: missing identifiers, invalid GTIN (already validated), no returns policy, a recurring-only price, a listing page on a Site other than the claimed one, image too small, missing shipping for a target country, price on the page not matching the feed, and title or description length. These checks become part of Junior Bay's own product and listing-page standards, not just the Google module's.

**Listing page standard.** Any page serving as a listing page must show the same price Google receives, a working buy action, shipping and return information, and Product structured data whose price, availability and identifiers match the feed. The page composer enforces this for listing pages automatically, regardless of the page's goal.

## 5. Settings: presets and Advanced

### 5.1 Presets

| Preset | Behaviour |
| --- | --- |
| **Recommended** (default) | Auto-list every eligible product, account shipping and returns from Junior Bay, automatic improvements on, free listings on, US / English. |
| **Manual approval** | As Recommended, but new and newly eligible products wait in Ready to list for the tenant's approval. |
| **Custom** | Shown automatically once any Advanced setting differs from a preset. |

### 5.2 Advanced (at the tenant's own risk)

Advanced sits behind a disclosure: "These settings change what Google receives. Junior Bay can't guarantee approval of overridden values." Every overridden value shows an **Overridden** badge and a **Reset to Junior Bay value** action, and the Overview counts products with overrides.

| Area | Advanced controls |
| --- | --- |
| Targeting | Additional countries and languages (each a feed label and data source), with per-country shipping and returns. |
| Product attributes | Per-product overrides for title, description, Google product category, product types, highlights, details, custom labels 0–4, age group, gender, material, pattern, size system and type, energy label, bundles and multipacks, excluded destinations, and any other attribute the Merchant API accepts, validated before saving. |
| Automation | Automatic improvements by type (price, availability, images, shipping), autofeed (off by default, with a duplicate warning if turned on), auto-list new products. |
| Programs | Free listings and Shopping ads participation, and any other program Google offers the account. |
| Business | Business identity attributes, only as the tenant declares them. Business info overrides. |
| Users | View and manage the users on the tenant's Merchant Center account. |
| Raw view | Read-only view of the exact `ProductInput` last sent and the processed product Google returned, for knowledgeable tenants and support. |

### 5.3 Locked fields

`link` and `price` cannot be overridden. They must match the listing page or Google disapproves the item, so they are always derived. A tenant who wants a different price changes the product or the listing page. The Advanced screen explains why they are locked.

## 6. Full feature coverage

"Every feature Google offers" is delivered in stages. Each row is a separate, flag-gated capability inside the module, available on every plan unless open decision 2 decides otherwise.

| Capability | Merchant API area | Junior Bay source or use | Phase |
| --- | --- | --- | --- |
| Account creation, linking, users, business info and identity | Accounts | Site organization, tenant profile | 1 |
| Homepage verification and claim | Accounts (`homepage`) | Site canonical hostname | 1 |
| Shipping settings, return policies | Accounts, return policies | `ShippingConfig`, `TenantConfig` | 1 |
| Terms of Service state | Accounts | Re-acceptance prompts on the Overview | 1 |
| Product sync | Products, data sources | §3 | 2 |
| Status notifications and issue resolution | Notifications, issue resolution | §4 | 3 |
| Promotions | Promotions | Coupons (`Coupon.schema.json`), mapped where the terms fit Google's promotion rules. Funnel sale pages (`/sale`, `/flash-sale`) become `salePrice` with `salePriceEffectiveDate` ending at `sale.ends_at`, but only on the canonical listing page, never the sale variant. | 5 |
| Product review feed (Shopping stars) | Reviews | First-party reviews (`REVIEWS.md` Phase 3, 50+ reviews) | 5 |
| Local inventory and store pickup | Inventories (local) | Requires a linked Google Business Profile (`BUSINESS_PROFILE_AND_GBP.md`) and inventory counts | 6 |
| Regional pricing and availability | Inventories (regional) | Advanced targeting | 6 |
| Conversion sources | Conversion sources | Junior Bay checkout outcomes | 6 |
| Performance, best sellers, price competitiveness | Reports | Overview metrics and product insights | 6 |
| AI titles, descriptions and images | Product Studio (`v1alpha`) | Suggestions only, editable, never auto-applied to locked fields | 6 |
| Order tracking signals | Order tracking | `Shipment.schema.json` delivery data | 6 |
| Shopping and Performance Max campaigns | Accounts (campaign management link) + Google Ads | `ADS_PRIMITIVE.md` | 7 |

Phase 0 confirms the current version and availability of each area. Alpha and allowlisted areas ship behind a flag only once access is granted.

## 7. Records

| Record | Key fields |
| --- | --- |
| `MerchantConnection` | tenant, mode, Google account ID, ownership path (created / linked), provider link state, Terms of Service state, homepage URI and claim state, data source IDs per target, programs, encrypted merchant grant reference, `connected_by`, last verified at |
| `MerchantSettings` | tenant, mode, preset, auto-list setting, targets (feed label, country, language), automation toggles, schema version |
| `ProductListing` | tenant, mode, product ID, variant key, offer ID, listing page ID, included / hidden, eligibility and reason, last sent hash and time, Google status per destination and country, issue summary, overrides, expiration |
| `MerchantOperation` | idempotency key, operation, request ID, outcome (applied, rejected, retryable, unknown), redacted diagnostics |

Commerce gains per-product `availability` and `availability_date` on Product, the tenant's chosen `listing_page_id`, and the `ListingSnapshots` table with a stream (§3.3). `Product.schema.json` must also list `brand`, `gtin`, `mpn` and `identifier_exists`. They are validated in `domain/documents.py` and edited in `ProductIdentifiersField.vue`, but missing from the JSON schema.

## 8. Internal API

Authenticated routes under `/me/merchant`, mirroring `/me/ads`:

| Route | Purpose |
| --- | --- |
| `POST /me/merchant/connections` | Begin Google sign-in for create or link |
| `GET /merchant/google/callback` | OAuth callback (single-use state bound to tenant, user, release, mode; PKCE) |
| `GET /me/merchant/connection` | Connection, verification and checklist state |
| `DELETE /me/merchant/connection` | Disconnect, with the delete-now / let-expire choice |
| `GET /me/merchant/listings` | Product listing states, filterable |
| `PATCH /me/merchant/listings` | Include, hide, approve (bulk) and per-product overrides |
| `GET /me/merchant/issues` | Rendered account and product issues |
| `GET`/`PUT /me/merchant/settings` | Preset and Advanced settings |
| `POST /me/merchant/sync` | Tenant-initiated full resync (rate-limited) |
| `POST /merchant/google/notifications` | Google push notifications (public, verified) |

## 9. Entitlements

Add `entitlements.merchant` to every platform plan, including `free`, so the module can be disabled per plan later without code. Check it on the API and the worker. The wiring has three parts:

- Add `merchant` to stripe-link's `CAPABILITIES` (`domain/entitlements.py`). If it is really on Free, add it to `FREE_TIER_CAPABILITIES` too, which is code, not plan data.
- Add it to Attention's known capabilities (`attention/entitlement.py`).
- Route `/me/merchant/*` to its own check **before** Attention's `attention` beta check in `handlers/api.py`, as `/me/ads/*` does. Otherwise the module is silently limited to beta tenants. A tenant who loses the entitlement keeps their account and listings, and Junior Bay stops syncing after a notice; products then expire on Google's 30-day schedule unless the tenant reconnects or removes them.

## 10. Phases

| Phase | Scope and exit criteria |
| --- | --- |
| **0. Access and policy** | Create Junior Bay's production Merchant Center account and request advanced account setup. Enable the Merchant API in separate dev and prod Cloud projects. Complete `registerGcp` on the production account. Create the test advanced account and the test account pool. Confirm with Google: merchant-credential operations, the site-verification method for a provider, `accountManagement` creation for platforms, notification setup, the `triggeraction` allowlist, and quotas. Record results in `GOOGLE_MERCHANT_PHASE_0.md`. |
| **1. Connection and onboarding** (Test mode) | Create and link flows, Terms of Service, business info, homepage claim, data source creation, autofeed off, shipping and returns settings. Disconnect and reconnect. Exit: a pilot tenant connects a test account, claims a test domain, and disconnects cleanly. |
| **2. Catalog sync** | Listing snapshot contract, mapping, pre-checks, change pipeline, refresh sweep, lifecycle deletes, existing-account duplicate handling. Exit: a 1,000-product test catalog syncs, edits propagate in under five minutes, and archiving deletes. |
| **3. Status and issues** | Notifications, reconciliation, issue rendering, product badges. Exit: a forced disapproval appears in the dashboard with its fix link. |
| **4. Dashboard** | Overview, Products, Issues, Settings with presets and Advanced, overrides and locked fields. Exit: a new tenant reaches Live from the checklist without leaving Junior Bay except for Google sign-in. |
| **5. Live beta** | Production release, Live mode, a small pilot. Add Promotions and the review feed. Exit: pilot products approved and serving in free listings, with no duplicate or mismatch disapprovals. |
| **6. Extensions** | Local and regional inventory, conversion sources, reports, Product Studio suggestions, order tracking. |
| **7. Ads hand-off** | Ads proposes the campaign management link from Google Ads and Merchant Core approves it. Shopping and Performance Max become campaign types in `ADS_PRIMITIVE.md`, offered only when the account has approved products. |

## 11. Related plan changes

- `OFFER_SEMANTIC_P4.md` P4.2b says "hosted scheduled file first; Content API later". Replace it with a pointer to this plan: the Content API is gone, and the API data source replaces the scheduled file.
- `REVIEWS.md` Phase 3 (product review feed) becomes a Phase 5 capability here.
- `ADS_PRIMITIVE.md` §1's Shopping paragraph points here for the Merchant connection.
- `dashboard/src/config/menu.js` adds `googleMerchant` to the `attention` group.
- Write `PRODUCT_BULK_IMPORT.md` (Products-owned, every plan) before Phase 2, since large catalogs reach Merchant through it.
- `GET_STARTED_WIZARD.md` creates the default Live Site that a connection claims by default (§2.1).
- Add the missing identifier fields to `Product.schema.json` (§7).

## 12. Open decisions (recommendation first)

1. **Menu label.** Recommend **Google Shopping**, with "Powered by Google Merchant Center" on the screen. Alternative: "Google Merchant Center".
2. **Plan gating inside the module.** Recommend nothing gated: listing, sync and issues on every plan. Revisit Reports and Product Studio only if they carry a real cost.
3. **Refresh cadence.** Recommend a seven-day resend inside a daily sweep. Shorter costs quota for no benefit.
4. **Listing-page default.** Recommend the most recently published single-product page on an eligible Site, with the tenant able to change it.
5. **Availability without inventory.** Recommend a manual per-product availability field now, replaced by inventory counts when `INVENTORY_COST_BASIS.md` or a stock plan ships.
6. **Digital products.** Recommend excluded from the first release. Revisit once Google's eligibility for the specific digital categories Junior Bay tenants sell is confirmed.
7. **Countries beyond the US.** Recommend US only for the beta, with additional targets in Advanced after Live beta.
8. **Free tenants and the custom-domain requirement.** Listing needs a claimed website, and custom domains are not a Free capability. Recommend deciding after Phase 0: if Google lets a merchant claim a platform hostname, Free tenants list from their `{label}.jbay.uk` Site. If not, either let the Free plan add one custom domain for Merchant, or state plainly that listing starts at Basic. Without one of these, the module is a checklist Free tenants can never finish.
9. **Tenants with several Sites.** Recommend one Merchant connection per tenant, bound to the default Live Site, for the first release. Allow a second connection per additional Site later, since each Merchant account can claim only one website.
10. **Recurring products.** Recommend excluding recurring-only products from the first release. Map them to Google's subscription cost attribute after Phase 0 confirms category eligibility.

## 13. Review against the codebase (November 27, 2026)

The Google API facts were not re-checked in this review. Phase 0 still confirms them. The review checked the plan's claims about Junior Bay's own code and made six corrections:

1. Free tenants cannot get a custom domain, so the "every plan" promise needs open decision 8.
2. A Merchant account claims one website, so a connection binds to one Site (§2.1, open decision 9).
3. The catalog change event and the snapshot request had no mechanism. They became a publish-time snapshot table with a stream (§3.3).
4. Returns and shipping can differ per product and per Site, so they need item labels (§3.1, §3.2).
5. Recurring prices and label-only variants are now explicit (§1, §3.1, open decision 10).
6. Entitlement wiring needs three changes and a route placed before Attention's beta check (§9).

Confirmed as written: product `sku`, `condition`, `status`, `digital_asset`, category and type fields, size and colour variants, weight and dimensions, GTIN validation, Site indexing eligibility, and the refund vocabulary (window, return shipping, restocking fee).
