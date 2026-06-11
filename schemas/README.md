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
