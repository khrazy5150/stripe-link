# Stripe Cart JSON-First Refactoring Plan

## Purpose

Recreate Stripe Cart as `stripe-link`, a JSON-first checkout and commerce-page platform where presentation, logic, and data are separate contracts instead of tightly coupled HTML, JavaScript, Lambda code, and DynamoDB shapes.

The target result is an app where an LLM, dashboard, API client, or mobile app can create and modify checkout experiences by manipulating validated JSON documents. The same page definition should render on the web, power native mobile screens, enforce feature tiers, and update previews in real time without hard page refreshes.

## North Star

Stripe Link should treat JSON as the source of truth for checkout experiences.

- Data lives in normalized commerce records: tenants, products, prices, offers, pages, orders, subscriptions, domains, media, legal policies, shipping rules, and analytics.
- Logic lives in versioned services: validation, pricing, eligibility, tier policy, checkout creation, fulfillment, publishing, routing, and event handling.
- Presentation lives in renderer packages that consume JSON: web renderer, dashboard editor renderer, server renderer, email renderer, and future mobile renderers.
- Feature availability is resolved from tier policy JSON, not scattered conditionals.
- Live editing is driven by observable JSON state wrapped in a `Proxy` object that emits structured patches on property changes.

## Existing Stripe Cart Surfaces To Recreate

Use the original `stripe-cart` project as the behavioral baseline.

- Infrastructure: `template.yaml`, `short-url-edge.yaml`, `deploy/`, `seeding/`, SAM deployment scripts, CloudFront, S3, Lambda, API Gateway, DynamoDB, KMS, Secrets Manager.
- Core API modules: `src/api_products.py`, `src/api_offers.py`, `src/api_pages.py`, `src/create_checkout.py`, `src/upsell_processor.py`, `src/orders.py`, `src/invoices.py`, `src/shipping_api.py`, `src/legal_pages.py`, `src/custom_domains.py`, `src/billing.py`.
- Tenant and platform modules: `src/tenant_config.py`, `src/platform_config.py`, `src/config_api.py`, `src/admin_keys.py`, `src/connect_oauth.py`, `src/stripe_platform_secrets.py`, `src/fee_handling.py`.
- Rendering modules: `src/lambda_page_generator.py`, `src/node_render/index.js`, `layers/node_renderer/nodejs/renderer.js`, `templates/`, `dist/dashboard/js/lp-core.js`, `dist/dashboard/js/template-schemas.js`, `dist/dashboard/js/components/`.
- Routing and publishing: `src/lambda_edge_router.py`, short URL generation, CloudFront Function/KVS routing, S3 page publishing, preview buckets, custom domains.
- Admin dashboard: `dist/dashboard/`, `dist/admin/`, products, offers, landing pages, services, orders, customers, invoices, themes, media, auth, profile, preferences, platform admin, Stripe onboarding.
- Supporting features: Stripe Connect, platform billing paywall, fee handling, shipping, services and appointments, refund policies, video upload/transcode, download delivery, page tracking, transaction ledger, test data deletion, product reconciliation, webhooks, migrations.

## Target Architecture

Build `stripe-link` around a small set of explicit packages and contracts.

```text
stripe-link/
  schemas/                  Versioned JSON schemas and examples
  packages/
    core/                   Shared domain types, validators, patch utilities
    runtime-web/            Browser renderer and interactive checkout runtime
    runtime-server/         Server-side renderer and publishing runtime
    runtime-mobile/         Mobile-friendly render contract adapters
    editor/                 Dashboard state, proxy store, form generation
    tier-policy/            Feature gates, usage limits, entitlement resolver
  src/
    api/                    Lambda handlers grouped by resource
    services/               Business logic, no API Gateway assumptions
    repositories/           DynamoDB access and migrations
    integrations/           Stripe, AWS, Cloudflare, email, shipping
  dist/
    dashboard/              Built dashboard assets
    storefront/             Built web runtime assets
  plans/
```

## Resource Isolation And Naming

`stripe-link` must not share mutable AWS resources with the existing `stripe-cart` application. All newly created resources should use a `jb-` prefix wherever AWS naming rules allow it.

1. Use `jb-` as the table prefix for every new DynamoDB table: `jb-stripe-keys-dev`, `jb-products-dev`, `jb-offers-dev`, `jb-pages-dev`, `jb-orders-dev`, `jb-checkout-sessions-dev`, and the matching `prod` tables.
2. Use globally unique S3 bucket names with the same boundary, account ID, and environment: `jb-pages-dev-{account_id}`, `jb-pages-preview-dev-{account_id}`, `jb-media-dev-{account_id}`, `jb-templates-dev-{account_id}`.
3. Use isolated stack names: `jb-stripe-link-stack-dev`, `jb-stripe-link-stack-prod`, and a separate edge/routing stack if CloudFront Function, KVS, or Lambda@Edge resources remain split by region.
4. Use isolated Lambda/function names where explicit names are set: `jb-pages-api-dev`, `jb-create-checkout-dev`, `jb-page-render-dev`, `jb-short-url-router-dev`.
5. Use isolated CloudFront KeyValueStore, CloudFront Function, custom domain routing records, and app config keys so short URL routing cannot collide with `stripe-cart`.
6. Keep migration tools explicit: read from legacy `stripe-cart` resources only when a migration command names them, and write only to `jb-` resources.
7. Scope IAM policies to the new `jb-` resources first; grant legacy read permissions only to migration functions or scripts.
8. Add deployment checks that fail if a `stripe-link` write target does not start with `jb-`.

## Canonical JSON Contracts

Create schemas before rebuilding behavior. Every API and renderer should depend on these contracts.

1. Define `schema_version` and migration rules for every document.
2. Create `TenantProfile.schema.json` for tenant identity, brand, billing state, Stripe Connect state, domains, support contacts, legal defaults, and feature tier.
3. Create `Product.schema.json` for Stripe-synced product data plus local metadata, images, shipping metadata, service metadata, tags, search fields, and sync state.
4. Create `Price.schema.json` for one-time prices, recurring prices, trial settings, fee handling, gross/net amounts, currency, interval, default flags, Stripe IDs, and active state.
5. Create `Offer.schema.json` for product bundles, selected price IDs, quantities, discounts, upsells, order bumps, eligibility rules, checkout behavior, and fulfillment metadata.
6. Create `Page.schema.json` for page identity, SEO, route, selected offer, template, sections, content blocks, media references, theme tokens, behavior flags, analytics IDs, legal links, publish state, and preview state.
7. Create `Section.schema.json` and `Block.schema.json` for reusable presentation primitives: hero, media carousel, product selector, CTA, trust badges, benefits, FAQ, testimonials, guarantee, timer, comparison table, order summary, checkout form mount, legal footer.
8. Create `Theme.schema.json` for design tokens: colors, typography, spacing, radius, shadows, layout density, dark mode support, and component-level overrides.
9. Create `Checkout.schema.json` for line items, customer data requirements, shipping/tax behavior, payment methods, success/cancel URLs, upsell routing, and Stripe session options.
10. Create `TierPolicy.schema.json` for plan tiers, feature flags, max pages, max products, custom domains, templates, media/video, analytics, services, subscriptions, A/B testing, white label, and publish limits.
11. Create `RuntimeEvent.schema.json` for editor changes, checkout events, page views, conversion events, Stripe webhook events, publish events, and audit events.
12. Add schema examples for a minimal single-product page, a bundle page, an upsell flow, a SaaS paywall, a service booking page, and a mobile-native page definition.
13. Add JSON Schema validation tests using a single validator in CI and Lambda runtime.

## Data Model Steps

1. Inventory every DynamoDB table in `stripe-cart`: app config, Stripe keys, platform config, checkout sessions, orders, customers, invoices, notifications, refunds, services, fulfillers, appointments, tenant profiles, products, offers, landing pages, transactions, legal pages, custom domains.
2. Decide which tables remain separate and which become single-table entities. Keep high-volume operational records such as orders/events separate unless access patterns prove otherwise.
3. Add `schema_version`, `document_type`, `tenant_id`, `mode`, `created_at`, `updated_at`, `updated_by`, and `revision` to mutable JSON documents.
4. Store the full canonical JSON document for pages/offers/themes while maintaining denormalized indexes for list/search views.
5. Keep Stripe as source of truth for product/price primitives, but persist a normalized local cache plus local extension metadata.
6. Represent page drafts, previews, and published versions as separate revisions. Never overwrite published JSON without a revision record.
7. Create a `document-events-{env}` table or stream target for JSON patches, publish actions, audit history, and collaboration hooks.
8. Create migrations from current `stripe-cart` shapes into canonical JSON documents.
9. Add idempotent seed scripts for tier policies, base themes, starter templates, legal defaults, and platform config.

## Service Layer Steps

1. Extract business logic from Lambda handlers into services with explicit inputs and outputs.
2. Build a validation service that validates JSON documents, applies defaults, upgrades schema versions, and returns field-level errors.
3. Build a tier policy resolver that receives tenant, action, document, and environment, then returns allowed/denied plus limits and explanations.
4. Build product sync services for Stripe product and price webhooks, scheduled reconciliation, and manual sync.
5. Build offer services for bundle pricing, selected price resolution, discounts, upsell chains, order bumps, and product eligibility.
6. Build checkout services for Stripe Checkout Session creation, connected account handling, application fees, fee handling, shipping, tax, subscriptions, and success/cancel routing.
7. Build page services for draft save, preview render, publish, copy-to-live, copy-to-test, route assignment, custom domain assignment, and invalidation.
8. Build order services for webhook ingestion, line-item normalization, fulfillment, invoices, refunds, downloads, and transaction ledger entries.
9. Build legal policy services for tenant defaults, page overrides, refund policy selection, terms/privacy/contact page generation, and checkout links.
10. Build media services for image/video upload, transcode, metadata, signed URLs, and render-safe media references.

## API Steps

1. Start with REST endpoints equivalent to the current API Gateway surface, but make request and response bodies canonical JSON.
2. Add `/schemas` endpoints so the dashboard, LLM tools, and mobile clients can discover the current schema versions and feature capabilities.
3. Add `/tenants/{tenant_id}/tier-policy/effective` to expose resolved feature availability.
4. Add `/documents/validate` for LLM-created page, offer, theme, and checkout JSON validation before saving.
5. Add page endpoints: create draft, get draft, patch draft, validate draft, preview draft, publish draft, list revisions, restore revision.
6. Add offer endpoints: create, update, patch, validate, archive, list by tenant, resolve checkout-ready offer.
7. Add product endpoints: list, sync, update local metadata, attach media, query by product type/category/tags.
8. Add checkout endpoints that accept `page_id`, `offer_id`, or explicit checkout JSON and produce Stripe sessions consistently.
9. Add event endpoints for page views, editor changes, conversion events, and client-side runtime telemetry.
10. Preserve CORS, auth, environment/mode selection, and billing gates from the original app.

## Renderer Steps

1. Define a renderer interface: `render(document, context) -> output`, where output can be DOM nodes, HTML string, React Native config, or email HTML.
2. Build `runtime-web` to render canonical page JSON into browser DOM without depending on dashboard globals.
3. Build `runtime-server` to render the same JSON to static HTML for S3/CloudFront publishing.
4. Build a mobile adapter that maps page sections and checkout actions to native-safe primitives, even if the first implementation only emits a normalized mobile view model.
5. Replace template-specific hand wiring with component schemas and renderer components keyed by section/block type.
6. Move theme handling to token application: CSS variables on web, style objects on mobile.
7. Ensure checkout actions are declarative JSON actions: `create_checkout_session`, `open_url`, `apply_upsell`, `select_price`, `track_event`.
8. Add graceful unknown-component behavior gated by schema validation: fail validation for publish, show editor warnings for draft.
9. Snapshot-test representative documents against server HTML output and browser DOM output.

## Dashboard And Editor Steps

1. Build the editor around the canonical page JSON document, not template-specific DOM fields.
2. Generate forms from schema metadata where practical, with custom editors only for high-value controls such as media, products, checkout actions, and theme tokens.
3. Replace `template-schemas.js` with versioned component schemas that are shared by dashboard, API validation, and LLM tooling.
4. Add an editor state store that holds one proxied JSON document per active draft.
5. Add patch history, undo, redo, dirty state, autosave state, validation state, and publish readiness as first-class editor state.
6. Add tier-aware UI filtering so unavailable sections, templates, and settings are hidden or disabled based on effective tier policy.
7. Keep the preview mounted and update it from JSON patches rather than reloading the whole page.
8. Add field-level validation messages returned from the same validator used by the API.
9. Add LLM import flow: paste or generate JSON, validate it, show required fixes, save as draft, then preview.

## Real-Time Proxy Object Model

Implement live updates with an observable JSON store that wraps draft documents in `Proxy`.

1. Create `createObservableDocument(rawDocument, options)` in `packages/core`.
2. The function returns `{ state, subscribe, getSnapshot, applyPatch, replace, destroy }`.
3. Wrap nested objects and arrays recursively with `Proxy` so changes like `state.sections[0].headline.text = "New"` are observed.
4. Implement `set`, `deleteProperty`, and array mutation traps.
5. Emit RFC 6902-style JSON Patch operations: `add`, `replace`, `remove`, plus metadata `{ path, oldValue, newValue, timestamp, source }`.
6. Batch synchronous changes into microtasks to avoid excessive preview renders.
7. Add path-level subscriptions so the preview can re-render only affected sections.
8. Add loop protection so applying remote patches does not re-emit duplicate local changes.
9. Add immutable snapshots for validation, autosave, undo, redo, and API submission.
10. Add debounced autosave that sends patches or full documents depending on revision state.
11. Add conflict detection with `revision` and `updated_at`; for now use last-write-wins only for drafts, never for published revisions.
12. Add tests for nested object edits, array insert/remove/reorder, delete operations, patch replay, undo/redo, and serialization.

Example shape:

```js
const doc = createObservableDocument(pageJson, { source: "editor" });

doc.subscribe((patches) => {
  previewRuntime.applyPatches(patches);
  autosaveQueue.enqueue(patches);
  validationQueue.enqueue(doc.getSnapshot());
});

doc.state.sections[0].blocks[1].content.headline = "Updated offer";
```

## Feature Tiers

1. Define tier policy JSON as platform-owned config, not code constants.
2. Resolve tier policy on every document mutation, publish action, checkout action, and dashboard capability fetch.
3. Model feature flags as structured paths: `pages.custom_domains`, `pages.max_published`, `checkout.upsells`, `media.video`, `analytics.advanced`, `branding.white_label`.
4. Model usage limits separately from booleans: counts, bandwidth, video minutes, domains, active pages, products, collaborators.
5. Add `requires_feature` and `requires_limit` metadata to schema fields and components.
6. Make schema-driven addition/subtraction possible by changing tier policy and component registry JSON.
7. Add API enforcement first, then dashboard affordances second.
8. Add tests proving unavailable features cannot be saved, previewed as publishable, published, or used at checkout.

## LLM Creation Workflow

1. Publish a concise prompt contract that tells LLMs to produce only valid JSON matching the current schemas.
2. Provide example documents for each checkout pattern and tier.
3. Add an API endpoint or local tool that returns schema, effective tier, available products/offers, and allowed components.
4. Validate generated JSON before persistence.
5. Return actionable validation errors with JSON Pointer paths.
6. Auto-fill safe defaults for omitted optional presentation fields.
7. For unsafe or unavailable features, return tier-aware corrections rather than silently dropping fields.
8. Add a `source: "llm"` audit marker and preserve original prompt metadata when available.

## Publishing And Routing Steps

1. Render published page revisions from canonical JSON, not dashboard form fields.
2. Store published JSON and rendered HTML together so debugging can compare input and output.
3. Keep preview publishing uncached or no-cache; keep production publishing cache-aware with invalidation.
4. Preserve short URL behavior, but make route records JSON documents that point to tenant, page revision, mode, domain, and target URL.
5. Preserve CloudFront Function/KVS routing where it is already working.
6. Add custom domain route documents for tenant-owned domains.
7. Add publish pipeline states: validating, rendering, uploading, routing, invalidating, published, failed.
8. Add rollback to previous published revision.

## Mobile App Compatibility

1. Keep page JSON free of browser-only assumptions.
2. Represent layout in semantic sections and design tokens rather than CSS strings.
3. Keep actions declarative so mobile can invoke native checkout, web checkout, or external URLs.
4. Provide a `mobile_view_model` adapter that strips unsupported web-only blocks and returns warnings.
5. Add schema fields for responsive/media variants without requiring separate mobile pages.
6. Test the same JSON document through web and mobile adapters.

## Migration Steps From Stripe Cart

1. Copy infrastructure patterns into `stripe-link`, but rename stacks, buckets, functions, tables, and domains carefully.
2. Port shared utilities first: CORS/JSON response helpers, environment resolution, KMS utilities, Stripe key lookup, platform secret lookup, fee handling, config loader.
3. Port schemas and validators before porting API write paths.
4. Port product sync and reconciliation.
5. Port offers and checkout session creation.
6. Port page draft, preview, publish, and short URL routing.
7. Port dashboard authentication, tenant config, Stripe onboarding, and platform billing gates.
8. Port order, invoice, refund, transaction ledger, download, shipping, service, appointment, legal page, media, video, and custom domain modules.
9. Replace copied dashboard landing-page editor code with the JSON-first editor store and schema-driven controls.
10. Migrate current sample pages into canonical JSON fixtures.
11. Build compatibility adapters only where needed to read legacy records during transition.
12. Remove compatibility adapters after data migration is complete and verified.

## Testing Steps

1. Add schema validation tests for every fixture and representative invalid document.
2. Add unit tests for tier policy resolution.
3. Add unit tests for proxy patch generation and patch replay.
4. Add service tests for product sync, offer resolution, checkout creation, publish pipeline, and route resolution.
5. Add renderer snapshot tests for web/server output.
6. Add API integration tests using local SAM events or mocked AWS repositories.
7. Add Stripe webhook fixture tests.
8. Add migration tests from current `stripe-cart` records to canonical JSON.
9. Add browser tests for dashboard edit, live preview update, autosave, validation, publish, and checkout launch.
10. Add mobile adapter tests that prove web-only components fail gracefully.

## Deployment Steps

1. Create `template.yaml` for `stripe-link` with dev/prod environments and `jb-` naming defaults.
2. Add `jb-` DynamoDB tables, API Gateway, Lambda functions, globally unique `jb-` S3 buckets, CloudFront distributions, KMS permissions, Secrets Manager permissions, and route resources.
3. Keep edge/global resources separated where AWS requires `us-east-1`.
4. Add deploy scripts for core stack, edge/routing stack, dashboard build, seed config, pull/push config, and teardown.
5. Add environment-specific app config seeding.
6. Add CI checks for schema validation, unit tests, build, package, and deployment template validation.
7. Add operational runbooks for Stripe webhook setup, Connect onboarding, custom domains, short URLs, rollbacks, and CloudFront invalidation.

## Suggested Implementation Order

1. Bootstrap repository structure, package manager, formatter, test runner, SAM template skeleton, and local dev scripts.
2. Create canonical schemas, fixtures, and validator package.
3. Implement observable JSON proxy store and patch tests.
4. Implement tier policy package and seed policy fixtures.
5. Implement repositories and service layer for products, offers, pages, tenants, and checkout.
6. Implement web/server renderers for a minimal page with product, offer, CTA, and checkout action.
7. Implement dashboard editor for canonical JSON with live preview and autosave.
8. Implement Stripe checkout path end to end.
9. Implement publish path to S3/CloudFront and short URL routing.
10. Port remaining Stripe Cart features in priority order: orders, billing gates, Connect, custom domains, legal pages, shipping, services, media/video, analytics, refunds, invoices, transaction ledger.
11. Add migration scripts and migrate known fixtures.
12. Harden tests, deployment, monitoring, and rollback.

## Definition Of Done

The refactor is complete when:

- A checkout page can be created from valid JSON without hand-authored HTML.
- The same JSON can render in dashboard preview, published web page, server-side HTML, and mobile view model.
- Feature tiers can add or remove page capabilities by changing tier policy/schema metadata.
- The dashboard preview updates instantly when proxied JSON changes, without a hard refresh.
- Published pages are revisioned and rollbackable.
- Stripe checkout, upsells, orders, billing gates, Connect, domains, legal links, shipping, and fulfillment work at parity with Stripe Cart.
- Tests cover schema validation, proxy updates, tier enforcement, checkout, rendering, publishing, and migration.
