# Developer Mode — hide the raw JSON panels behind a per-user preference

Status: PLANNED, not built. Agreed 2026-08-30.
Related: plans/TODO.md → Security (allowlist rewrite; stored-but-unread credentials).

---

## Problem

The dashboard renders 13 raw `<pre>{{ JSON.stringify(...) }}</pre>` dumps across 10
components. They are genuinely useful for development and support, but they are always on
for every tenant, which:

- makes the product read as an internal admin tool rather than a finished app;
- leaks internal ids into screenshots, screen-shares, tutorials and support tickets.

## What this is NOT

**Developer Mode is not a security boundary, and must never be described as one.**

Every panel renders an object the browser already holds, fetched by the tenant's own
authenticated API calls. Anyone can open DevTools → Network and read the identical JSON,
or `curl` the endpoint with their own session. Hiding the panel changes what is *shown*,
not what is *disclosed*.

The schema itself cannot be kept secret: shipping a JSON API to a browser SPA discloses
it. That is inherent to the architecture and no UI gate claws it back.

Confidentiality of the *contents* is a separate, already-solved problem — see the
redaction fix in 175bce7 (Connect OAuth token ciphertext no longer reaches the browser).
Anything sensitive must be removed from the response, never merely hidden in the client.

### Rejected: a support-issued unlock key

Considered: tenant contacts support → support issues a key expiring in ~5 minutes → tenant
enters it in the module they are troubleshooting → the panel unlocks.

Rejected because:

- **It buys no confidentiality.** DevTools shows the same payload with no key at all.
- **It costs a week or more** — issuance, expiry, storage, a redemption endpoint, an audit
  trail, support-side tooling, and documentation.
- **It raises support load rather than lowering it.** Support must mint a key before the
  tenant can gather the very thing support asked for, at the moment the tenant is already
  stuck and frustrated.

The Phase 2 diagnostics bundle serves the same goal — get support a good payload — without
any of that machinery.

---

## Decision: a per-user preference, not tenant config and not localStorage

Three options were considered:

| Where | Verdict |
|---|---|
| `Configuration.vue` | **No.** Configuration governs the whole tenant/app. A debug view is a property of the *person looking at the screen*, not of the business. One user enabling it would flip it for every colleague. |
| `localStorage` only | **No.** Zero server work, but per-device: a user who works across two browsers toggles it twice, and it silently resets when site data is cleared. |
| **`UserPreferences` document** | **Yes.** A per-user store already exists and is the natural home. |

`/preferences` is keyed by `(tenant_id, user_id)`, already backs `theme`,
`default_stripe_mode`, `dashboard_home` and `sidebar_collapsed`, and is already reachable
from the avatar dropdown → Preferences. Adding `developer_mode` is extending what is
there rather than inventing a parallel mechanism.

`?debug=1` is kept as a **non-persistent** one-shot override, so support can say "add
`?debug=1` to the URL" without walking a tenant through changing a saved setting.

---

## Phase 1 — the panel and the preference

### 1. Schema

`schemas/UserPreferences.schema.json` is `"additionalProperties": false`, so the field must
be declared or `validate_user_preferences` will reject the save:

```json
"developer_mode": { "type": "boolean", "default": false }
```

No migration and no backfill: absent reads as `false` via the default.

### 2. Composable

```js
// dashboard/src/composables/useDeveloperMode.js
// Persistent per-user preference, plus a one-shot ?debug=1 that support can talk a tenant
// through without changing their saved settings.
export function useDeveloperMode() {
  const oneShot = new URLSearchParams(location.search).has("debug");
  return computed(() => oneShot || Boolean(preferencesStore.developer_mode));
}
```

### 3. Shared component

`dashboard/src/components/shared/JsonPanel.vue` — renders nothing unless enabled.

```vue
<JsonPanel :value="selectedProduct" label="Product document" />
```

Consolidating is most of the value even before the gate: 13 hand-rolled blocks are 13
independent decisions about what gets dumped, with nobody comparing them. One component
means one place to change the rule.

### 4. Preferences UI

A checkbox in `Preferences.vue` beside the existing four, worded honestly:

> **Developer Mode** — show the raw JSON behind each screen. Useful for troubleshooting
> with support. This changes what the dashboard displays, not what your browser can access.

### 5. Call sites (13, as of 2026-08-30 — verify line numbers before editing)

| File | Line(s) |
|---|---|
| `Coupons.vue` | 203 |
| `Customers.vue` | 84 |
| `Invoices.vue` | 164 |
| `LandingPages.vue` | 527, 1192, 1287 |
| `Notifications.vue` | 76 |
| `Offers.vue` | 408, 433 |
| `Orders.vue` | 94 |
| `Products.vue` | 152 |
| `Services.vue` | 358 |
| `StripeKeys.vue` | 300 |

**Decide each site individually — this is not a blanket find-and-replace.**
`LandingPages.vue:1192` uses a distinct `builder-json` class and may be an intentional
authoring aid rather than debug chrome; if so it stays visible, or moves behind its own
control. Check the others for similar intent before gating them.

---

## Phase 2 — the diagnostics bundle

The raw document is a mediocre support artifact: it omits the context that resolves most
tickets (environment, build, when, which entity) and includes fields nobody needs.

Add a **Copy diagnostics** action producing something purpose-built:

```json
{ "captured_at": 1788080000,
  "environment": "prod",
  "app_version": "…",
  "tenant_id": "…",
  "entity": { "type": "offer", "id": "offer_…" },
  "document": { "…scrubbed…" } }
```

Scrubbing **must** reuse the backend's `SENSITIVE_FIELDS` (`src/stripe_link/security.py`)
rather than restating the list client-side. A second hand-maintained copy is exactly how
the Connect token refs went unredacted for months — the list drifted from the schema
silently. Export it to the client from one source, or generate it at build time.

This is strictly better for support than a raw dump *and* safe to paste into a ticket or a
public forum thread.

---

## Sequencing and cost

- **Phase 1** ≈ an afternoon. Delivers the polish and the screenshot fix on its own.
- **Phase 2** ≈ a day. This is the part that reduces support load.

Independent: Phase 1 alone is a complete improvement and can ship without Phase 2.

## Open questions

1. Should platform staff get Developer Mode on by default? There is no staff role today,
   so this needs a role concept first — out of scope.
2. Does anything outside the dashboard render these documents (preview, published pages)?
   Assumed no; confirm before closing Phase 1.
