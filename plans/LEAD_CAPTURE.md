# Lead Capture

Status: **proposed** (design only — no code yet). Author-approved direction; specifics of the Terms-of-Service
clause (§6.4) are deliberately deferred.

> **Greenfield note.** There is **no lead-capture backend today** — `product.lead_capture.action` has never
> had a receiving endpoint, and no lead is stored anywhere. So there is no legacy data or migration; we build
> the primitive clean. This supersedes the "EmailCollector" line item in
> `LANDING_PAGE_CTA_AND_COMPOSITION.md` (phase 2), which was tabled pending this design.

## 1. What we're building

A lead is captured when a visitor submits the **inline form CTA** on a published landing page (the `email`
CTA type — and later `open_form`). We need to: receive it on a **public** endpoint, store it as a
first-class document, let the tenant **see and export** their leads, and — with explicit consent —
**subscribe the email to the tenant's and/or Junior Bay's mailing list**.

Goal of the Junior Bay subscription: **promote the tenant's business to customers who might be interested in
their offers** — the platform markets *on the tenant's behalf* to an audience that opted in.

## 2. Locked decisions

- **Dedicated `LeadsTable`, one per environment (`lead-capture-{dev,prod}`).** This matches the house
  **table-per-entity** convention (`ProductsTable`, `OffersTable`, `PagesTable`, `ServicesTable`, …); leads
  are their own entity with high write volume, PII, and a distinct retention lifecycle, so an isolated table
  is the *right* fit (not a single shared table). It is wired the same way: a `leads_repository()` over
  `DynamoDocumentRepository`, reading `LEADS_TABLE` from env.
- **Leads are anchored to the offer/page, not an invented "campaign."** Every lead carries `offer_id` and
  `page_id`. We do **not** introduce a `campaign` entity (the source doc's campaign concept is dropped);
  offer/page is our real dimension. Campaign-style grouping, if ever wanted, is a later GSI over `offer_id`.
- **Ingest is PUBLIC and unauthenticated by design.** It comes from an anonymous visitor. Tenant + offer are
  resolved **server-side from the payload's IDs**, never from a client-supplied partition key. The endpoint
  is protected by **abuse controls** (§8), not auth. Read/list/export paths are **authenticated** and
  tenant-scoped, reusing the same dashboard auth as every other authenticated handler.
- **Duplicates are recorded, not blocked.** The same person legitimately submits on different offers or
  resubmits later. We never return a hard 409 for a "duplicate person." We *do* enforce **request-level
  idempotency** (a client idempotency key → the same lead on retry). This resolves the source doc's
  email-vs-phone-dedupe ambiguity: there is no blocking dedupe to disagree.
- **No sharding, no rollup tables, minimal GSIs on day one.** Per-tenant lead volume from landing pages is
  far below a single DynamoDB partition's limits. We ship the simple key convention and add shards / GSIs /
  aggregate counters **only if metrics justify it** (§10). The source doc's 16-shard + monthly-bucket +
  GSI1/2/3 + daily/monthly rollup design is kept as a documented *scaling target*, not the starting point.
- **Consent is dual, granular, and opt-in** — tenant list and Junior Bay list are two independent explicit
  opt-ins, each with its own stored proof (§6). Never bundled, never pre-ticked, never automatic.
- **Reuse what exists.** A captured lead **emits a notification** (the bell — fulfilling the deferred
  `NOTIFICATION_EMITTERS` plan) and can trigger a **mailer** autoresponder / double-opt-in confirmation.

## 3. The primitive: `lead_submission`

A single stored document per form submission:

```jsonc
{
  "schema_version": "2026-05-29",
  "document_type": "lead_submission",
  "tenant_id": "tenant_demo",
  "lead_id": "lead_...",
  "offer_id": "offer_...",          // where it came from — the offer is the contract
  "page_id": "page_...",
  "fields": {                        // validated against the product's lead_capture.fields[]
    "email": "jane@example.com",
    "name": "Jane Doe",
    "phone": "+1..."                 // only what the form declared
  },
  "email_normalized": "jane@example.com",   // lowercase/trimmed — for lookup/erase, not for blocking
  "phone_normalized": "+1...",
  "consent": { /* §6 */ },
  "status": "new",                   // new | contacted | qualified | archived  (tenant-managed)
  "provenance": { "ip": "...", "user_agent": "...", "referer": "...", "submitted_at": 0 },
  "idempotency_key": "...",          // request-level dedupe
  "created_at": 0,
  "updated_at": 0
}
```

`fields` is **not** an opaque blob: it is validated against the offer's primary product `lead_capture.fields[]`
(name/type/required), so we only accept declared fields and enforce required ones. `status` is a small
tenant-managed enum for the dashboard pipeline.

## 4. Data model (LeadsTable keys)

Consistent with `DynamoDocumentRepository` (tenant-scoped partition, sortable id):

- **PK** `TENANT#<tenant_id>`
- **SK** `LEAD#<created_at_iso>#<lead_id>` — time-ordered, so "recent leads" is a single reverse `Query` on
  one partition. No scatter-gather.
- **Idempotency**: a conditional write keyed on `idempotency_key` (a marker item or a condition expression)
  makes retried submits return the existing lead.
- **GSIs (day one, minimal):** at most one, `GSI-offer` (`PK: TENANT#<tenant>#OFFER#<offer_id>`), *only if*
  the dashboard needs per-offer lists; otherwise defer entirely and filter client-side. Status/campaign/
  email GSIs are **deferred** (§10).

## 5. Ingest flow (`POST /leads`)

1. Parse payload: `tenant_id`, `offer_id`, `page_id`, `fields`, `consent`, `idempotency_key`, honeypot field.
2. **Abuse gate** (§8): honeypot empty, size caps, rate-limit by IP+tenant, timing check.
3. Resolve the offer server-side; load its primary product `lead_capture` → the field schema.
4. **Validate** `fields` against `lead_capture.fields[]` (required present, declared-only, basic type checks);
   normalize email/phone.
5. **Idempotent write**: if `idempotency_key` already seen → return the existing lead (200). Else write the
   `lead_submission`.
6. **Record** (not block) a `duplicate_of` hint if the same normalized email/phone already exists for this
   offer — informational only.
7. Fire side effects: **notification** (bell) to the tenant; if `consent.platform_marketing.granted`, kick
   the **double-opt-in** confirmation email for Junior Bay; optional tenant autoresponder.
8. Respond `201` with a minimal body (no echo of stored PII beyond what's needed).

## 6. Consent & GDPR

Subscribing a lead to a mailing list is a **separate processing purpose** from receiving the inquiry, and the
tenant list vs the **Junior Bay** list are **two independent controllers**. GDPR (Art. 7, Recital 32; the
Planet49 ruling banning pre-ticked boxes) requires **specific, granular, affirmative opt-in** per purpose.

### 6.1 Form
Up to two **independent, unticked** opt-ins, each with its own visible disclosure copy:
- "Join **{tenant}**'s mailing list."
- "Join **Junior Bay**'s mailing list." (platform marketing on the tenant's behalf)

Neither is a precondition for submitting the inquiry. Default to opt-in globally (EU/UK require it;
US CAN-SPAM needs truthful disclosure + working unsubscribe regardless).

### 6.2 Stored proof
Each opt-in is its **own consent record** — the record *is* the legal evidence:

```jsonc
"consent": {
  "tenant_marketing":   { "granted": true,  "text": "<exact copy shown>", "timestamp": 0, "ip": "...", "method": "web_form", "source_offer_id": "offer_..." },
  "platform_marketing": { "granted": false, "text": "<exact copy shown>", "timestamp": 0, "ip": "...", "method": "web_form", "double_opt_in_confirmed": false }
}
```

### 6.3 Rules
- **Double opt-in for the Junior Bay list** (confirmation email; `double_opt_in_confirmed` flips on click) —
  it's platform marketing to someone else's audience, so provable consent + spam-trap protection matter most.
- **Independently revocable** — separate unsubscribe per list; withdrawing one never affects the other.
- Withdrawal + erasure honored via the email lookup (§9).

### 6.4 Terms of Service — **NOTE FOR LATER (do not build yet)**
The **ToS page must disclose the Junior Bay subscription**: that Junior Bay may, with the visitor's explicit
opt-in, email them to **promote the tenant's business/offers**, that Junior Bay is a separate controller for
that purpose, and that they can unsubscribe independently. The tenant agreement should likewise permit
platform marketing to leads generated on tenant pages. **Specifics deferred** — this note exists so it isn't
lost. Ties into the existing legal/ToS surface (`domain/legal.py`, LegalPagesTable).

## 7. Endpoint surface

Public (unauthenticated, abuse-gated):
- `POST /leads` — ingest.
- `GET /leads/confirm?token=…` — double-opt-in confirmation for the Junior Bay list.
- `GET /leads/unsubscribe?token=…&list=tenant|platform` — per-list unsubscribe.

Authenticated (tenant-scoped, same auth as other dashboard handlers):
- `GET /leads?offer_id=&status=&since=` — list (recent-first).
- `GET /leads/{lead_id}` — detail.
- `PATCH /leads/{lead_id}` — update `status` (pipeline).
- `GET /leads/export.csv` — export.
- `DELETE /leads/by-email?email=…` — GDPR erase (§9).

## 8. Security & abuse (public path)

- **Honeypot** hidden field + minimum time-to-submit (bot timing).
- **Rate limiting** by IP + tenant (and per offer); payload size caps; field-count caps.
- Tenant/offer resolved **only** from the payload IDs against real documents — **never** accept a
  client-supplied partition key or arbitrary attributes.
- Optional pluggable challenge (hCaptcha/Turnstile) behind a per-tenant flag if abuse appears — not day one.
- IAM scoped to the `LeadsTable` (+ its GSI) only.

## 9. Retention, PII & erasure

- **Erase-by-email**: `email_normalized` enables GDPR right-to-be-forgotten across a tenant's leads.
- **Retention policy** (resolves the source doc's open question): configurable per tenant; default **retain
  until deleted**; optional DynamoDB **TTL** for auto-expiry when a tenant sets a window. PII minimization —
  store only declared fields.
- Consent withdrawal removes the address from the relevant list but keeps the **consent-history record** as
  proof (or tombstones it), per accountability requirements.

## 10. Deferred — the source doc's scaling design (documented so it's not lost)

Add **only when metrics justify** — trigger signals: sustained write throttling on the tenant partition,
p99 ingest latency climbing, or a single tenant's monthly lead volume approaching partition limits.
- **Sharded partitions** `TENANT#<tenant>#SHARD#<0-15>#YYYYMM` with deterministic shard from
  normalized email/phone/uuid, monthly buckets to cap partition growth.
- **GSI2 (campaign/offer + timestamp)**, **GSI3 (status + timestamp)** for large-volume filtered views.
- **Daily/monthly aggregate counters** (`TENANTSTATS#…`) updated atomically on ingest, for dashboards.
- **`LOOKUP#EMAIL#…` / `LOOKUP#PHONE#…`** items if we ever move to transactional cross-partition lookup.

Until then, recent-first `Query` on one tenant partition + optional single offer GSI is sufficient and far
simpler.

## 11. Resolved open questions (from the source doc)

1. *Email vs phone dedupe disagreement* → moot; we don't block duplicates.
2. *Duplicate returns existing ID or conflict?* → **request-level idempotency** returns the same lead (200);
   genuine resubmissions are stored additively, never 409.
3. *Monthly rollups sync or async?* → **no rollups day one**; deferred to §10.
4. *Exact GSI schema?* → day one: none required (or one offer GSI); rest deferred (§10).
5. *Which auth provider?* → **existing dashboard auth** for read paths; ingest is public.
6. *Retention policy?* → §9 — per-tenant, default retain-until-deleted, optional TTL, erase-by-email.

## 12. Phasing

1. **Capture core — ✅ SHIPPED (2026-07-10).** `lead_submission` doc + `leads_repository` + `LeadsTable`
   (`jb-lead-capture-{env}`, TTL on `retention_expires_at`) + `validate_lead_submission`; public
   `POST /leads` with validation against `lead_capture.fields[]` + honeypot + payload caps + request
   idempotency + duplicates-recorded-not-blocked; notification emit (`type: "lead"`, route `leads`). The
   `email` landing-page CTA renders a real inline form (fields from the product's `lead_capture.fields[]`,
   honeypot, dual opt-ins) posting to `/leads`. Auth read/list/filter + `PATCH` status. Tests in
   `tests/test_lead_capture.py` + `tests/test_cta_render.py`.
2. **Consent + Junior Bay list — PARTIAL.** ✅ The form captures the two independent opt-ins and stores the
   **consent proof records** (§6.2) on every lead. ⏸ **Deferred:** double-opt-in confirmation email,
   per-list unsubscribe endpoints, and *actually adding the address to a list* — because **there is no
   mailing-list / campaign system in stripe-link yet** to subscribe them to (the mailer is transactional
   only). Building the confirm/unsubscribe lifecycle before that system exists would manage state with no
   downstream effect. Revisit when a marketing-list primitive is built; the legally-important consent proof
   is already captured.
3. **Dashboard Leads screen — ✅ SHIPPED (2026-07-10).** `components/Leads.vue` + `stores/leads.js` + menu
   entry (Orders → Leads): list, status filter, per-lead status pipeline, detail modal (fields / consent /
   source), CSV export. Erase-by-email endpoint deferred with the rest of §9's lifecycle.
4. **Scale (only if metrics demand).** Shards / GSIs / aggregate stats per §10.
- **Parallel, later:** ToS clause (§6.4).

## 13. Relationship to existing plans

- Unblocks phase 2 of `LANDING_PAGE_CTA_AND_COMPOSITION.md` (the EmailCollector CTA renders this form).
- Uses the deferred **notification emitter** from `docs/NOTIFICATION_EMITTERS.md` and the existing mailer.
- ToS/consent surface ties into `domain/legal.py` + LegalPagesTable.
- The `open_form` lead action (a hosted multi-field form) is a natural extension of the same primitive.
