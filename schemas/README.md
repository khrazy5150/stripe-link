# stripe-link schemas

These JSON Schemas define the durable contracts used by APIs, renderers, migration tools, and future LLM workflows.

The first domain slice covers Product, Price, Offer, and Coupon because those contracts determine how `stripe-link` avoids duplicate Stripe products:

- one canonical Stripe Product
- multiple Stripe Prices on that product
- local Offer documents that select price context, presentation context, checkout behavior, and eligibility
- selectable offer items for pages where the customer chooses among multiple prices on the same product
- Stripe-first Coupon documents that are persisted only after the Stripe Coupon and Promotion Code exist

Important separation:

- `Price.quantity` describes the bundle or package represented by the Stripe Price, such as 3 items or sessions.
- `Offer.items[].quantity` describes how many of that selected Stripe Price to add to checkout.
- `Offer.items[].selectable_prices` describes the customer-facing selector for one product in one offer.
- `Offer.items[].display_discount_pct` and `selectable_prices[].display_discount_pct` are display overrides only. Stripe pricing still comes from the selected immutable Price.
- `Offer.status` is the lifecycle source of truth. Do not add a parallel boolean `active`.
- `Offer.context` describes funnel placement only: standard, sale, flash sale, upsell, downsell, or order bump. Subscription is intentionally a price/checkout model, not an offer context.
- `Offer.discount` is always present. Use `{ "mode": "none" }` when there is no discount, `{ "mode": "coupon_code" }` to attach a Stripe-first Coupon, and `{ "mode": "auto" }` only when the API will create/apply the corresponding Stripe discount behavior.
- `Coupon` uses the immediate model: the API creates Stripe objects first, then writes the local document with `sync.status = "synced"`. Failed Stripe creation should return an error and leave no usable coupon document behind.
- `order_bump` offers should normally reference distinct add-on products and a `trigger_offer_id`. The schema permits product references, but API validation should reject self-referential bumps unless a deliberate exception is documented.

Template/page-section schemas should be implemented later as a vertical slice with one complete page experience before expanding the component catalog.

`Page.schema.json` is intentionally minimal for now. It stores page identity, route, offer reference, theme tokens, and semantic sections. The section catalog should grow only through vertical slices that include schema, renderer, dashboard controls, and tests together.

Future A/B testing should be modeled as its own document type rather than embedded directly in Page. The expected shape is an experiment document with `experiment_id`, `tenant_id`, `status`, weighted variant page references, `winner_page_id`, and `experiment_url`.

`UserProfile.schema.json` is separate from `UserPreferences.schema.json`. Profiles store account identity, dashboard display name, avatar image metadata, Cognito-facing auth metadata, and subscription state. Preferences remain UI behavior only, such as theme and default dashboard view. Password changes are actions against the auth provider and must not be persisted in profile JSON.

Refund policy inheritance is intentionally copy-on-write:

- `UserPreferences.authoring_defaults.refund_policies` stores per-user defaults for creating documents.
- `Product.refund_policy` stores the product-level policy copied from preferences or explicitly overridden.
- `Offer.refund_policy` may inherit from product policy or override it for a checkout context.
- `Page.refund_policy` stores the customer-facing snapshot resolved from the offer/product chain so published pages remain stable.

Notifications are operational documents. `Notification.schema.json` stores tenant/user-facing alerts such as paid invoices, while `RefundRequest.schema.json` stores the refund workflow records shown on the Notifications screen. Both can live in the same `jb-notifications-*` DynamoDB table because their document types use separate sort-key prefixes.

`ShippingConfig.schema.json` stores tenant-level shipping setup: provider metadata, encrypted credential references, origin/return addresses, parcel defaults, rating options, and label options. Product documents still decide whether an item requires shipping; offers/pages can later resolve shipping choices against this tenant shipping configuration.

`Customer.schema.json` is an operational customer record, not a report. It stores contact details, optional Stripe customer linkage, addresses, denormalized purchase summary fields for fast list/detail views, product affinity, and recent transaction references. Reports should aggregate from customers, orders, invoices, and refunds instead of replacing the customer document.

Service booking is modeled as several related documents in the shared `jb-services-*` table:

- `Service.schema.json` defines the bookable unit, its duration, price, Stripe product/price link, booking rules, and allowed fulfillers.
- `Fulfiller.schema.json` defines staff/delegates, compensation, tips ownership, and personal weekly hours.
- `TenantAvailability.schema.json` defines tenant-wide booking defaults such as timezone, slot interval, lead time, buffers, and weekly hours.
- `AvailabilityException.schema.json` defines tenant or fulfiller-specific blocks/openings.
- `Appointment.schema.json` stores the booking instance, customer, assigned fulfiller, payment status, and check-in/completion lifecycle fields.

This keeps service catalog setup separate from appointment operations while still letting a checkout page sell a service through the same Product/Price primitives as physical or digital products.

`Invoice.schema.json` stores local invoice state around Stripe invoices. Stripe remains the payment/invoice delivery primitive, while the local document stores customer snapshots, line items, presentation metadata, due/resend/share state, Stripe IDs/URLs, and source links back to services, appointments, orders, products, or custom dashboard-created work.

`app-config.json` stores platform-level environment configuration in `jb-app-config-*`. It is a singleton document keyed as `config_key=app_config` and `environment=global`, with environment-specific values under `environments.dev` and `environments.prod`. Values such as `api_base_url` are shared system configuration that the dashboard can display or consume while tenant-owned settings continue to live in `TenantConfig.schema.json`.

`global-billing-config.json` is the S3-backed platform billing document. It owns platform fee tiers and payment processing schedules used by `/prices/calculate`, allowing fee changes without redeploying Lambda code.

`Site.schema.json` is a collection document that groups one or more Pages under a shared root domain, enabling subfolder-based URL routing for SEO domain authority consolidation. A Site is the layer between a tenant and their pages when the tenant owns a custom domain and wants each page to inherit that domain's authority rather than being served from an isolated subdomain or short URL.

Important separation between Site and Page:

- `Site` owns the domain, the slug-to-page routing map, the Cloudflare Worker integration config, and site-level SEO defaults. It does not own page content, offer references, or section definitions — those remain entirely on the Page document.
- `Page` owns its own content, offer, theme, and sections exactly as before. A page is unaware of which Site (if any) it belongs to. This preserves the existing page architecture with zero breaking changes.
- A Page may exist without a Site (served via the short URL at `go.jbay.be/{short_id}` as today) or be referenced by exactly one Site entry. A Page must not be referenced by more than one Site to avoid routing ambiguity.
- `Site.pages` is a slug-keyed map where each key is the tenant-defined path segment such as `/plumbing` or `/hvac`. The root page uses `/`. Slugs must be unique within a Site, so the schema models them as object keys instead of array entries.
- `Site.domain.verified` is set by the platform after DNS or Worker validation completes. Unverified sites must not be served on the custom domain.
- `Site.integration.mode` defines how the custom domain routes traffic to Junior Bay pages. Six modes are supported covering the current spectrum of tenant technical profiles. More server-specific modes can be added later as implementation needs become concrete. Only the config block matching the active mode should be present on the document.
- `worker` — Cloudflare Worker reverse proxy deployed to the tenant's own Cloudflare zone. Intercepts only the configured path prefixes and proxies them to Junior Bay. All other traffic passes through to the tenant's existing site unchanged. Requires tenant DNS to be managed through Cloudflare. Best SEO outcome — true subfolder routing with full domain authority inheritance.
- `cloudflare_saas` — Junior Bay's own Cloudflare for SaaS zone handles SSL provisioning and routing. Tenant adds a single CNAME record at any DNS provider pointing to the Junior Bay proxy hostname. Cloudflare provisions SSL automatically per custom domain via the API. Best fit for tenants with no existing website. No server access or Cloudflare account required from the tenant.
- `cloudflare_partial` — Tenant adds a CNAME record for a specific subdomain (e.g. `pages.clientdomain.com`) to Junior Bay's Cloudflare infrastructure at their existing DNS provider. Root domain DNS zone remains untouched. Cloudflare handles SSL and routing for that subdomain stream only. Note: this routes a subdomain rather than a true subfolder so domain authority inheritance is partial, not full.
- `dns` — Tenant points their entire root domain DNS to the Junior Bay CloudFront distribution. Existing website is fully replaced. Most disruptive mode — recommended only for tenants with no existing site or who are actively migrating away from their current platform.
- `nginx` — Tenant's own web server proxies specific path prefixes to Junior Bay. Junior Bay generates copyable Nginx `location` or Apache `ProxyPass` snippets so tenants can hand the instructions to their IT team with minimal friction. Other server-specific snippets can be modeled as additional server types or modes when needed.
- `wordpress` — Junior Bay WordPress plugin registers custom rewrite rules for each Site slug, intercepts matching requests, fetches Junior Bay page HTML server-side via `wp_remote_get`, and renders it at the client's WordPress URL. Fetched HTML is cached in WordPress transients at a configurable TTL (default 300 seconds) to eliminate per-request latency. No DNS changes, no server config, no Cloudflare account required. The plugin derives fetch URLs from the parent Site document's `site_id` and must call `flush_rewrite_rules` when page slugs are added or removed to avoid stale 404s.
- `Site.integration.worker_config` is only present when `mode` is `worker`. It stores the Cloudflare zone ID, deployed Worker script ID, intercepted path prefixes, and last deploy timestamp.
- `Site.integration.cloudflare_saas_config` is only present when `mode` is `cloudflare_saas`. It stores the proxy hostname, Cloudflare Custom Hostname ID, and SSL provisioning status.
- `Site.integration.cloudflare_partial_config` is only present when `mode` is `cloudflare_partial`. It stores the subdomain prefix, CNAME target, and CloudFront distribution ID.
- `Site.integration.dns_config` is only present when `mode` is `dns`. It stores the CNAME target and CloudFront distribution ID.
- `Site.integration.nginx_config` is only present when `mode` is `nginx`. It stores the Junior Bay origin URL, proxy path prefixes, and an optional server type hint used to generate the Nginx `location` or Apache `ProxyPass` snippet shown in the dashboard.
- `Site.integration.wordpress_config` is only present when `mode` is `wordpress`. It stores cache TTL, installed plugin version, and last rewrite flush timestamp. It intentionally does not duplicate `site_id`; the plugin uses the parent Site document's `site_id`.
- `Site.seo_defaults` provides fallback meta title suffix, default OG image, and structured data hints applied to all pages in the site when the page itself does not override them. This is the correct place to store `LocalBusiness` or `Organization` schema hints that apply site-wide.
- `Site.status` is the lifecycle source of truth. Valid values are `draft`, `active`, and `archived`. Do not add a parallel boolean `active`.
- Sites are environment-aware. Tenants should be able to build and test a Site in `test`, then use a later Copy to Live workflow to create or update the `live` Site separately.
- Disabled or archived Sites and disabled page routes must return 404. This is required for billing enforcement and for removing routes without redirect leakage.
- Sites live in the `jb-sites-*` DynamoDB table with `PK: TENANT#{tenant_id}` and `SK: SITE#{site_id}`.
- Runtime routing should use a CloudFront KeyValueStore or equivalent edge-readable route manifest, not live DynamoDB reads at the edge. The deployed route map should resolve the incoming hostname and environment to a Site, then match the request path to the correct `page_id` within that Site's slug-keyed page map. Standalone pages without a Site continue to resolve by short URL lookup as today.
- `Site.routing` may be empty for unpublished drafts. Once any publication field is set, `kvs_key`, `published_revision`, and `published_at` must be stored together.
