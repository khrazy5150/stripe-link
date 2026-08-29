# DIGITAL_MARKETPLACE.md — starter inventory + the provisioning engine

Status: **design draft, not built** (author direction 2026-08-28). HIGH priority.
Companion plan: `plans/ATTENTION_PRIMITIVE.md` (the traffic half of the same flywheel).

## 1. Thesis — solve the empty catalog

A free storefront is not enough of a hook; Stan, Beacons and Linktree all give you one. The two cold-start
problems that actually stop a new creator are **"I have nothing to sell"** and **"nobody visits my store."**
This plan solves the first.

A tenant buys a low-priced, ready-to-sell digital asset and Junior Bay **provisions an entire business around
it in one click** — licensed product, priced offer, landing page, funnel — then they sell it at their own
price. It feeds the free-forever model directly: we don't need the marketplace margin, we need the **GMV it
creates** (`plans/TODO.md` Pricing pivot — digital sales carry the 7% free-tier / 2% premium fee).

```
[ Marketplace ] ──► [ Provisioning Engine ] ──► [ Tenant storefront ] ──► GMV ──► platform fee
  starter inventory     license+product+           their brand, their
                        offer+page (1 click)        price, their buyers
```

## 2. Locked decisions

### 2.1 ⭐ FIRST-PARTY CONTENT ONLY in v1 (author decision 2026-08-28)
Junior Bay **creates/commissions and owns** the catalog. No third-party PLR suppliers at launch.

*Why this is the keystone decision:* the original proposal had suppliers submitting assets with a
`SourceContractSha256` "chain of custody." **A hash proves a contract wasn't altered — it does NOT prove the
supplier ever held the rights.** Anyone can grab a copyrighted asset off the internet and label it PLR. With a
"Verified by Junior Bay" badge on it, our verification becomes the thing a claimant points at. First-party
authorship removes that entire class of risk and, with it, supplier warranties, indemnification, DMCA
takedown cascades, and license revocation across live tenant stores.

**Deferred (needs its own design if ever revisited):** third-party supply, supplier Connect payouts,
revocation propagation, and the audit apparatus that would make third-party "verified" defensible.

### 2.2 Terminology: never say "PLR" to a customer
"PLR/MRR" carries a get-rich-quick smell that fights the brand ("makers and small brands", the creator selling
her own baking kits). Customer-facing language is **"starter inventory"**, **"done-for-you products"**, or
**"ready-to-sell templates."** The rights schema below stays — it's the substance — but the label doesn't.

### 2.3 The durable primitive is the PROVISIONING ENGINE, not the catalog
"One click → license + product + offer + landing page" is valuable **independent of where the asset comes
from.** Build it as a primitive with a pluggable supply source, so it later powers third-party supply,
tenant-to-tenant wholesale, template packs, or partner catalogs with no rework. The marketplace is
**supply source #1**, not the architecture.

### 2.4 Quality over volume
A handful of genuinely good assets beats a thousand junk ones. The entire differentiator against the existing
PLR market is that ours is **not** junk. Curation is the product.

## 3. The rights contract

Every catalog item carries an explicit **boolean** rights map. Vague marketing terms ("Commercial Rights",
"MRR", "Resell Rights") are prohibited — ambiguity is what makes the existing market unusable.

| Key | v1 default | Meaning |
|---|---|---|
| `commercial_use` | `true` | Tenant may monetize the finished derivative |
| `modify_content` | `true` | May edit, expand, extract, recombine |
| `rebrand_allowed` | `true` | May apply their own brand, logo, domain |
| `sell_finished_product` | `true` | May sell the modified deliverable |
| `sell_raw_unchanged` | `false` | May **not** flip the asset as-is |
| `giveaway_as_lead_magnet` | `true` | May distribute free to capture leads |
| `transfer_plr_rights` | `false` | Downstream buyers get end-user rights only |
| `transfer_mrr_rights` | `false` | Downstream buyers cannot resell rights |

- The map is **snapshotted immutably onto the license at purchase** — later catalog edits never retroactively
  change what a tenant already bought.
- `sell_raw_unchanged: false` is also the (partial) answer to **catalog saturation**: 500 tenants selling the
  identical file compete with each other. Mitigations to consider later: limited seats per asset, per-niche
  exclusivity as a premium lever, or AI-assisted differentiation at provisioning time.
- The tenant-facing badge states plainly what they may do. Because the content is first-party, this is a
  statement of fact, not a claim about a third party.

## 4. Architecture — adapted to THIS repo

> The source proposal assumed single-table DynamoDB (`PK: MARKETPLACE / SK: ITEM#…`) and TypeScript. This repo
> is **Python 3.12** with **36 tables, table-per-entity**, `stripe_link/repositories/*` + `handlers/*`
> patterns. Port the *spirit*, not the shapes. (CLAUDE.md: follow stripe-link's architecture; reuse first.)

### 4.1 Tables (new, per-env `jb-{name}-{env}`)
| Table | Key | Holds |
|---|---|---|
| `marketplace-catalog` | PK `item_id` | catalog item: title, category, price, rights map, asset ref, active |
| `marketplace-licenses` | PK `tenant_id`, SK `license_id` | issued license + **immutable rights snapshot** |

- Licenses are tenant-scoped, mirroring every other tenant entity (`TENANT#…` conventions in
  `repositories/documents.py`). A **GSI on `license_id`** serves public verification lookups.
- The catalog is **platform-global** (not tenant-scoped) — the same shape as `PlatformPlansTable`
  (`repositories/platform_plans.py`), which is the closest existing analogue. **Reuse that pattern.**
- Assets live in a private **marketplace vault** S3 bucket; tenant copies go to the tenant's own prefix.

### 4.2 ⚠️ No cross-table transaction — provisioning must be idempotent, not atomic
The source doc used `TransactWriteItems` to write license + product + offer in one shot. **DynamoDB
transactions do not span the multiple tables this repo uses.** Provisioning is therefore a **resumable
state machine**, not a transaction:

1. Record a `provisioning` license row first (the anchor + idempotency key).
2. Copy the S3 asset into the tenant prefix.
3. Write the Product (reuse `products` repo/validators — do **not** invent a parallel product type).
4. Write the Offer (reuse `offers`), priced at a sane default the tenant can change.
5. Generate the draft landing page via the existing page/composition pipeline.
6. Flip the license to `active`.

Each step is idempotent and keyed off the license id, so a retry resumes rather than duplicating. A sweep can
finish any license stuck in `provisioning` (reuse the existing `rate(15 minutes)` sweep pattern — three
already exist: reminders, cart recovery, review invites).

### 4.3 Reuse, don't fork
The provisioned Product/Offer/Page **are ordinary tenant entities** — same schemas, same validators, same
builder screens. A marketplace-provisioned product must be indistinguishable from a hand-made one afterwards,
apart from `source_license_id` provenance. Anything else doubles the surface area forever.

## 5. Money flow

**Junior Bay is the seller.** The tenant buys from the platform, so this rides the **platform-billing rail
that already exists** for Premium subscriptions (platform Stripe account, `platform_subscription.py` /
`platform-billing` webhook) — *not* Connect, and not the tenant's own account.

- No supplier payouts in v1 (first-party content ⇒ no third-party split).
- The marketplace price is deliberately low; **the money is downstream** — the tenant's sales carry the
  standard transaction fee, which is the whole point.
- Purchases must be idempotent against webhook replay (follow the existing webhook ordering/dedup guards).

## 6. Verification endpoint

`GET /marketplace/license/{license_id}` → status, rights snapshot, issued-at, item ref. Backed by the license
GSI. Public and cheap; gives the tenant something to point at if a *downstream buyer* ever questions their
right to sell. (With first-party content this is a convenience, not a legal shield — the legal answer is that
we authored it.)

## 7. Open questions / to decide before build

1. **Catalog seed** — how many assets, which niches, produced how? (This is a content-operations question, and
   it gates launch more than the code does.)
2. **Pricing** — flat (e.g. $7) or per-item? Free items for trial tenants as an acquisition hook?
3. **Saturation policy** — unlimited seats, limited seats, or niche exclusivity as a premium lever?
4. **Entitlement** — is marketplace access free-tier or premium-gated? (Recommendation: **free tier** — it
   creates the GMV the free model monetizes; gating it would starve the flywheel.)

## 8. Phases

| Phase | Deliverable |
|---|---|
| **M1 — Catalog** | catalog table + repo + rights-map validation + admin seeding (hand-edited table, per `PlatformPlansTable` precedent); browse/detail screens |
| **M2 — Purchase + license** | platform-billing purchase, license issuance with immutable snapshot, idempotent webhook handling |
| **M3 — Provisioning engine** | the resumable state machine (§4.2): S3 copy → product → offer → draft page; stuck-license sweep |
| **M4 — Polish** | verification endpoint, provenance surfacing in the builder, tenant-facing rights badge |
| **Later** | saturation controls; third-party supply (needs §2.1's deferred design); AI-assisted differentiation at provisioning |
