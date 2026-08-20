# Serve-host scheme — implementation plan (early P5 slice)

> **SHIPPED PROD + DEV 2026-08-19.** All four `{stage}-{mode}.juniorbay.com` hosts live and serving; dashboard
> de-hardcoded + `app_config` deploy-populated; legacy `test.juniorbay.com` + `preview.juniorbay.com` deleted. The
> app(prod)+test-mode preview misroute is fixed. **Lesson (step 4):** to unset a CloudFormation param you cannot just
> drop it from samconfig (→ `UsePreviousValue`) — and SAM silently drops empty-string tokens too; the reliable fix
> was to remove the legacy param + its resources from the template entirely.

Concrete build plan for the `{stage}-{mode}.juniorbay.com` serve hosts + config-driven URLs decided in
`plans/STRIPE_MODE_DECOUPLING.md` ("Serve-host naming + config-driven URLs"). This is the **early, additive** slice
of P5: it fixes the app(prod)+test-mode preview misroute and de-hardcodes serve URLs **without** touching backend
data partitioning, artifact paths, or the onboarding model (those stay in full P5/P2).

## The bug this closes
`test.juniorbay.com` is a single, **dev-only** host (regional API Gateway domain → dev `RestApi` `jm3ppyxos4`,
reading the **dev** buckets), and the dashboard hardcodes `TEST_PAGES_HOST = "test.juniorbay.com"` for *all*
test-mode links in both dashboards. So **app (prod) + test mode** points at the dev viewer → can't find prod
test-mode artifacts (written to the prod buckets). Sandbox+test works only by coincidence (all-dev).

## Reuse BOTH existing mechanisms per-stage (no unification, no CloudFront Function)
There are two serving front-ends today; keep both, just give each stage its own host + make the host config-driven:
- **LIVE previews** → the per-stage CloudFront **preview distribution**, addressed by full path
  (`/preview/{tenant}/{page_id}/index.html`). Prod already branded `preview.juniorbay.com` (shipped 2026-08-19).
- **TEST previews** → the per-stage **`TestPageServeFunction`** Lambda (`src/handlers/test_page_serve.py`), a regional
  API Gateway custom domain, resolving `short_code` → artifact and serving `/preview` + `/published` + the
  `/sale`//`/flash-sale` view variants. The prod stack **already has this function** — it just has no custom domain.

Because test uses the Lambda viewer and live uses the dist, **no CloudFront host→prefix Function is needed** for this
slice. (That Function is only for a *later* option that unifies everything onto the dist and drops the short_code
viewer — explicitly out of scope here.)

## Host map
| Host | → target | Mechanism | Cert | Work |
|---|---|---|---|---|
| `prod-live.juniorbay.com` | prod preview dist (`ELXXGAY4VK8QM`) | CloudFront path | us-east-1 `*.juniorbay.com` (`1a72b7c6`) | add alias (keep `preview.juniorbay.com` as legacy alias) |
| `prod-test.juniorbay.com` | prod `RestApi` (`jloezsxw05`) TestPageServe | regional APIGW | us-west-2 `*.juniorbay.com` (`1c396c68`) | **NEW apigw custom domain — fixes the misroute** |
| `dev-live.juniorbay.com` | dev preview dist (`E5ZXQMSV1EQIQ`) | CloudFront path | us-east-1 `1a72b7c6` | add alias |
| `dev-test.juniorbay.com` | dev `RestApi` (`jm3ppyxos4`) TestPageServe | regional APIGW | us-west-2 `1c396c68` | add apigw custom domain (keep `test.juniorbay.com` legacy) |

Two cert stories by mechanism: **CloudFront** hosts use the us-east-1 wildcard (already in use for `preview.juniorbay.com`);
**API Gateway** regional hosts use the us-west-2 wildcard (already in use for `test.juniorbay.com`). Verify `1c396c68`
is `*.juniorbay.com` (it covers `test.juniorbay.com` today, so almost certainly a wildcard); if not, request a
us-west-2 `*.juniorbay.com` cert (Route 53 DNS-validated, quick).

## Steps (ordered, non-breaking; dev first, then prod; config flip LAST per channel)
1. **`prod-test` (the fix).** Add an API Gateway **regional** custom domain `prod-test.juniorbay.com` (cert
   `1c396c68`) + base-path mapping → the prod `RestApi`, + Route 53 A/AAAA alias to its regional target. Mirror how
   `test.juniorbay.com` is wired, but on the prod stack. Template: add gated resources (a `PreviewTestServeDomain*`
   param set, like the dashboard/preview pattern), values set only for prod.
2. **`dev-live` + `prod-live`.** Add a CloudFront alias on each stage's preview dist (`dev-live` on the dev dist,
   `prod-live` on the prod dist) + Route 53 alias. Generalize the shipped `PreviewCustomDomain*` params to carry the
   mode-specific name(s), or add a second param pair. Keep `preview.juniorbay.com` as an extra alias on the prod dist.
3. **`dev-test`.** Add `dev-test.juniorbay.com` as an apigw custom domain → dev `RestApi` (keep `test.juniorbay.com`
   mapped as a legacy alias/redirect until confident).
4. **Stack Outputs + deploy-time config population.** Emit each host as a Stack Output. Add a deploy step
   (`deploy/*.sh`, run post-`sam deploy`) that reads the outputs and writes
   `app_config.environments.{channel}.{test_pages_host, preview_host}` — **infra identities populated from stack
   outputs, never hand-typed** (the drift-free principle). This replaces the manual `pages_preview_base_url` edit.
5. **Dashboard de-hardcode.** Replace the `TEST_PAGES_HOST` constant (`LandingPages.vue`) with
   `getTestPagesHost(channel)` reading `app_config` (same shape as the existing `getPreviewPagesBaseUrl`). No URL
   *addressing* change: test stays short_code-based, live stays path-based — only the host becomes per-channel.
6. **Verify** all four combos serve HTTP 200 for a real artifact: sandbox×{test,live} and app×{test,live}; confirm
   **app+test now resolves against prod** (misroute closed).
7. **Delete the old records (goal 2) — LAST, after prod verification.** Once all four hosts serve and the dashboard
   reads them from `app_config` with **no code reference to the old names**, delete the Route 53 records (and their
   apigw base-path mapping / CloudFront alias) for **`test.juniorbay.com`** and **`preview.juniorbay.com`**. Per the
   operator's request these are **deleted, not kept as aliases**, to avoid later confusion. Caveat: they are the
   rollback fallback (below), so delete only after step 6 passes **in prod**.

## Hardcoded-URL inventory (goal 1) + de-hardcode scope
Audited 2026-08-19. Infra/serve hosts hardcoded in code today:

**In scope for this slice (serve hosts → `app_config`):**
- `dashboard/LandingPages.vue:2007` — `TEST_PAGES_HOST = "test.juniorbay.com"` → `getTestPagesHost(channel)` from
  `app_config`.
- `dashboard/api/client.js:98-105` — the pages/preview CloudFront **fallback defaults** (`dlxn0y…`, `drjfn283…`,
  `d1lcshy…`). The preview default (`d1lcshy…` = the **dev** dist) is exactly what misrouted prod. Once `app_config`
  is deploy-populated, **remove these guess-defaults** (or make them error/empty) so a missing config surfaces loudly
  instead of silently serving the wrong environment.

**Intentional bootstrap exception — STAYS hardcoded (agreed 2026-08-19):**
- `client.js:9-10` — `API_BASES = {dev: dev.juniorbay.com, prod: prod.juniorbay.com}`. The minimum needed to *fetch*
  `app_config`; everything downstream is table-driven. This is the one deliberate hardcode. "Remove all hardcoded
  URLs" means all **except** this bootstrap.

**Related hardcodes — same principle, separate fixes (flagged, NOT this slice):**
- `publishing.py:711` — checkout base `https://prod.juniorbay.com` → host-agnostic checkout URL
  (STRIPE_MODE_DECOUPLING subsystem #4 / P4).
- `platform_subscription.py:33` — billing return `https://app.juniorbay.com` → derive from request host / config.
- Asset/canonical hosts `images.juniorbay.com` (`html.py:38` + dashboard ×3) and `juniorbay.com` (`legal.py:25`) —
  asset CDN + company URL; config-drive in a low-priority follow-up if wanted (not routing-critical).

## Open items to confirm at build
- Confirm `1c396c68` (us-west-2) is a `*.juniorbay.com` wildcard; else request one (Route 53-validated).
- `noindex`: `prod-test` (and all preview/test serving) must stay `noindex`. The `TestPageServeFunction` already sets
  noindex headers; confirm the prod preview dist keeps it too (preview artifacts are never canonical).
- Keep the short_code viewer for test **previews and `/sale`//`/flash-sale` views** — do not try to path-serve those
  in this slice (they're variant artifacts the viewer resolves by code).

## Rollout / rollback
Land dev hosts first, verify on sandbox; then prod. The **`app_config` flip is the last step per channel**, after the
host actually serves — so previews never point at a not-yet-live host. Rollback (before step 7) = revert the
`app_config` host values; the dashboard falls back to the still-present `test.juniorbay.com` / `preview.juniorbay.com`.
**The old records must stay until prod is verified** — step 7 (deleting them) is the point of no easy rollback, so it
runs only after everything is green in prod.

## Relationship to the bigger plan
This is an additive down-payment on `STRIPE_MODE_DECOUPLING.md` P5. It does **not** move test-mode *data* onto prod
or retire dev's tenant-test role — it only makes the **serving hosts** correct and config-driven. A later option
(unify all previews onto the preview dist via a CloudFront host→prefix Function and drop the short_code viewer) can
simplify further, but is not required and is deferred.
