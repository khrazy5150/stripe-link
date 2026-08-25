# APP_CONFIG.md — platform config & URL-migration runbook

The backend and dashboard read centralized, config-driven values from a single **`app_config`** document in DynamoDB,
so URL migrations and platform-identity changes are a **config edit, not a code change**. This doc says exactly which
table, which field, and whether a redeploy is needed.

---

## The tables

| Table | Read by | Serves |
|---|---|---|
| `jb-app-config-dev`  | the **dev** backend + the **sandbox** dashboard | `sandbox.juniorbay.com` |
| `jb-app-config-prod` | the **prod** backend + the **app** dashboard    | `app.juniorbay.com` |

- **Region:** `us-west-2`
- **Primary key (both tables):** `config_key = "app_config"`, `environment = "global"` — one document per table.
- **Shape:**
  - `environments.{dev|prod}.{…}` — **per-channel** values (hosts, CDN bases). Each table holds its own channel's slice.
  - `legal.{…}` — **top-level, environment-agnostic** platform legal identity.
- **Edit BOTH tables** when a value applies to both environments (e.g. legal identity, an asset-CDN move).
- **When changes take effect:**
  - **Dashboard:** on the next page reload (it caches `app_config` in `localStorage` and re-fetches on load).
  - **Backend:** on the next Lambda **cold start** — the server-side reader (`src/stripe_link/platform_config.py`)
    caches per container with no TTL. Expect a few minutes, not instant.
  - **Published pages:** values baked in at publish time (the default favicon) need the page **re-published**.

---

## ⚠️ Two kinds of fields — read this first

Some fields are **written by the deploy** (from CloudFormation) and will be **overwritten** if you hand-edit them.

| Kind | Fields | How to change |
|---|---|---|
| **Hand-editable** (edit DynamoDB directly, no redeploy) | `environments.{env}.public_asset_base_url`, all of `legal.*` | Edit the item (see [How to edit](#how-to-edit)) |
| **Deploy-populated** — DO NOT hand-edit | `environments.{env}.test_pages_host`, `pages_preview_base_url`, `pages_base_url` | Change the stack, redeploy, then run `scripts/populate_serve_hosts.py` (see below) |
| **Template / samconfig env vars** (not in `app_config` at all) | `PUBLIC_CHECKOUT_BASE_URL`, `PLATFORM_BILLING_RETURN_URL`, the serve-host domains themselves | Change the samconfig param + `sam deploy` |

`scripts/populate_serve_hosts.py <dev|prod>` reads the deployed stack's parameters/outputs and writes the
deploy-populated fields — **run it after every `sam deploy`** so those fields stay correct.

---

## Migration recipes

### 1. Move the asset-image CDN (e.g. `images.juniorbay.com` → a new host)
**Hand-edit, both tables, `environments.{env}`:**
- `public_asset_base_url` = `https://<new-cdn-host>`

That single field drives: the default favicon on tenant pages (backend renderer), the dashboard favicons, and the
product-image URL normalization in the builder. No redeploy — backend picks it up on cold start; **re-publish** pages
to refresh baked favicons.

Notes:
- Existing product/offer image URLs already **stored** with the old host are *data*, not config — migrate those
  separately (a data backfill), they are not covered by this field.
- The image **upload bucket** host (`images.juniorbay.net`) is a different value set in dashboard upload code, not in
  `app_config` — out of scope for a CDN-delivery move.

### 2. Change company name / address / support email / website (legal pages + footers)
**Hand-edit, both tables, top-level `legal.{…}`:**

| Field | Example | Appears in |
|---|---|---|
| `company_name` | `Junior Bay Corporation` | Terms/Privacy/Refund body + footer, `GET /legal` list |
| `legal_address`, `legal_city`, `legal_state`, `legal_zip` | `30 N Gould St, Ste R` / `Cheyenne` / `WY` / `82801` | the address block at the bottom of each legal page |
| `legal_jurisdiction` | `Laramie County, WY` | Terms (governing law) |
| `legal_email` | `support@juniorbay.net` | every "contact us at …" link across the legal pages |
| `website` | `https://juniorbay.com` | Terms/Privacy intro + legal-page footer link |
| `legal_effective_date`, `legal_last_revised_date` | `March 24, 2026` | page headers |

These render **`/legal/terms`, `/legal/privacy`, `/legal/refund`** (which contain the company footer block). A tenant
landing page's legal footer shows **Terms / Privacy / Refund links** that point at those pages. No redeploy (backend
cold start). `src/stripe_link/domain/legal.py::LEGAL_CONFIG` is the built-in **fallback** if `legal.*` is ever absent —
`app_config.legal` wins.

### 3. Move a serve host, or the checkout / billing host (deploy-owned — NOT hand-edited)
| To change… | Change this | Then |
|---|---|---|
| `{stage}-test.juniorbay.com` (test viewer) | `TestServeDomainName` in `samconfig.toml` (+ Route 53/ACM in `template.yaml`) | `sam deploy --config-env <env>` → `python3 scripts/populate_serve_hosts.py <env>` |
| `{stage}-live.juniorbay.com` (live preview) | `PreviewLiveDomainName` in `samconfig.toml` | same as above |
| `pages_base_url` (published-pages CDN) | the `PagesDistribution` in `template.yaml` (rare) | `sam deploy` → run the populate script |
| checkout URL | `ApiCustomDomainName` (the env var `PUBLIC_CHECKOUT_BASE_URL = https://${ApiCustomDomainName}/checkout` derives from it) | `sam deploy` |
| billing-return URL | `DashboardCustomDomainName` (`PLATFORM_BILLING_RETURN_URL` derives from it) | `sam deploy` |

---

## Field reference — `environments.{env}`

| Field | Meaning | Source | Read by |
|---|---|---|---|
| `public_asset_base_url` | asset-delivery CDN base | **hand-editable** | backend favicon, dashboard favicon + image normalization |
| `test_pages_host` | `{stage}-test` viewer host | **deploy-populated** (`TestServeDomainName`) | dashboard preview links |
| `pages_preview_base_url` | `{stage}-live` preview host | **deploy-populated** (`PreviewLiveDomainName`) | dashboard preview links |
| `pages_base_url` | published-pages CDN | **deploy-populated** (`PagesDistributionDomainName` output) | dashboard published-artifact URLs |
| `api_base_url` | this channel's API base | reflects `ApiCustomDomainName` | dashboard bootstrap override (default is hardcoded in `client.js`) |
| `dashboard_url`, `label`, `feature_flags` | dashboard host / display label / flags | informational | dashboard |
| `favicon_url`, `checkout_base_url` | **legacy** — not read by current code (superseded by `public_asset_base_url` and the `PUBLIC_CHECKOUT_BASE_URL` env var) | — | — |

## Field reference — `legal.{…}`
`company_name`, `legal_address`, `legal_city`, `legal_state`, `legal_zip`, `legal_jurisdiction`, `legal_email`,
`website`, `legal_effective_date`, `legal_last_revised_date` — all **hand-editable**; see recipe 2.

---

## How to edit

Always **read-modify-write the whole item** (nested-map `update-item` expressions are error-prone — a bad path
silently writes to the wrong place). Example (change the asset CDN + a legal field on prod):

```python
import boto3
t = boto3.resource("dynamodb", region_name="us-west-2").Table("jb-app-config-prod")
item = t.get_item(Key={"config_key": "app_config", "environment": "global"})["Item"]
item["environments"]["prod"]["public_asset_base_url"] = "https://cdn.example.com"
item["legal"]["legal_email"] = "support@example.com"
t.put_item(Item=item)
```

Repeat for `jb-app-config-dev` (using `["environments"]["dev"]`). Verify via the public app-config API:

```bash
curl -s "https://prod.juniorbay.com/app-config/app_config?environment=global" | python3 -m json.tool
```

---

## Gotchas
- **Edit both `-dev` and `-prod` tables** — each backend/dashboard reads only its own.
- `legal` is **top-level** and env-agnostic; the URL/host fields live under **`environments.{env}`**.
- **Never hand-edit the deploy-populated fields** — the next deploy's populate step overwrites them.
- **Backend cache:** changes apply on the next Lambda cold start (no TTL on the reader). If you need it immediately,
  force new containers (e.g. a trivial `sam deploy`), or call `platform_config.reset_cache()` in a one-off.
- **The one thing NOT in config:** the dashboard bootstrap API base (`API_BASES` in `dashboard/src/api/client.js`)
  is intentionally hardcoded — it's how the app finds the config in the first place.
