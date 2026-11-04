# SITE_AS_BUSINESS_IDENTITY.md — every message speaks for the Site it came from

Status: **planning, nothing built** (author direction 2026-11-03, from a real review-invite email).
Extends: `plans/BUSINESS_PROFILE_AND_GBP.md` (the 2026-07-23 course correction: Business Profile =
`Site.organization`). Reverses part of the 2026-09-23 sender consolidation in `domain/business_email.py`.

## 1. The bug, precisely

A review invite went out signed **"Poliaxis Nutrition"** when the offer belonged to a Site whose business is
**Quill**. Traced to four lines in `handlers/review_invites.py`:

```python
org = _tenant_organization(sites_repo, tenant_id)       # "First Site with an organization"
business_name = identity.get("business_name") or str(org.get("name") or "")
#                ↑ TenantProfile/UserProfile WINS over Site.organization
```

Two defects, not one:

1. **The precedence is inverted.** `tenant_email_identity()` reads the OWNER'S USER PROFILE and takes
   priority over the Site. The 2026-07-23 course correction says `Site.organization` IS the business
   identity; email never got the memo.
2. **`_tenant_organization` picks the FIRST Site with an organization.** Its own docstring admits
   "multi-Site precision is a future refinement". With several Sites it is arbitrary — and would still be
   wrong after fixing (1).

## 2. ⭐ This REVERSES a deliberate decision, and the reason for it must survive

`domain/business_email.py` was written 2026-09-23 to end exactly this class of bug. Its docstring:

> *"Before this existed each emitter resolved its own: the review invite read `Site.organization.name`, the
> receipt read `TenantProfile.business_name` (empty on every tenant that has ever existed), and most
> emitters asked for neither — so the same shop appeared as "Poliaxis Nutrition" on one message and as a
> bare "support@juniorbay.net" on the next."*

So the consolidation's goal — **ONE answer, so every message from a business looks like the same business**
— is correct and must be kept. What changes is the SCOPE of "one": per **Site**, not per tenant. A plan
that simply lets each emitter read a Site again, without a single resolver, re-creates the 2026-09 bug
with extra steps.

## 3. The four structural gaps

### 3.1 A Page does not know its Site

`Site.schema.json` has `pages`; `Page.schema.json` has **no `site_id`**. The link runs Site→pages only, so
finding a page's Site means scanning the tenant's Sites. That is precisely why `_tenant_organization`
cheats and takes the first one.

**Options:** (a) add `site_id` to the page document and backfill; (b) one cached reverse index
(`page_id → site_id`) built from `Site.pages`. (b) avoids a migration and keeps Site.pages the single
source of truth; (a) is faster at read time and survives a Site being edited mid-flight.

### 3.2 The emitters do not read the origin they already have

Orders DO carry `page_id` and `offer_id` (set from Stripe metadata, `stripe_webhook.py:1294`, `:3108`).
But **none** of `receipts.py`, `cart_recovery.py`, `reminders.py`, `invoices.py`, `purchase_manage.py` or
`notifications_content.py` reference `page_id` at all. So the chain exists in storage and is unused in
every send path. This is the bulk of the work, and it is per-emitter.

### 3.3 ⚠️ `Site.organization.email` IS NOT VERIFIED — this is the blocker

`business_email.py` gates the Reply-To behind a 6-digit code, a 5-minute TTL and an attempt limit, for a
stated reason: *"SES will not check whether the reply-to belongs to the tenant, so nothing else will."*

`Site.organization.email` is free text with **no verification path whatsoever**. Switching Reply-To to it
re-opens the hole that gate was built to close — a tenant could type any address, including one they do
not own, and the platform would mail on its behalf.

**This is the decision that gates the whole plan**, and there are only three honest answers:

| | |
|---|---|
| **Verify per Site** | Correct, and the most work. Each Site's address needs its own code flow. Friction: a tenant with 4 Sites verifies 4 times. |
| **Site name + tenant verified reply-to** | The *display* name comes from the Site (fixes the reported bug); the Reply-To stays the one verified address. Cheap, safe, and the NAP is still per-Site on the page. |
| **Use it unverified** | Rejected. It is the exact hole `business_email.py` exists to close. |

### 3.4 Not every email has a Site

Some sends have no page and therefore no Site: manually issued invoices, platform/billing notices, and
anything triggered from the dashboard rather than from a page. **Removing the tenant-level identity
outright would leave those with no name at all** — which is the "bare support@juniorbay.net" failure from
2026-09, rediscovered.

So the tenant-level fields cannot simply be deleted on day one. They can become the explicit **fallback
for site-less sends**, and be removed only if every send path is later proven to resolve a Site.

## 3a. ⭐ The transition is ~60% done — here is exactly where it stopped

The author's recollection is right, and the halves are cleanly separable. **The renderer already migrated.**
`html.resolved_brand_label` reads:

> *"The offer's explicit brand wins; otherwise the Site's Organization name (the single-source business
> identity); otherwise the platform brand."*

There is no user-profile `business_name` in that chain at all. So a **published page** is already
Site-based. Likewise the builder preview: on 2026-10-13 `renderedBrandLabel` was changed to read the mark
out of the preview frame, with a comment naming this very bug —

> *"Using it here promised 'Poliaxis Nutrition' on a page whose mark reads 'Quill' (author, 2026-10-13) — a
> placeholder that lies about what publishing will do."*

**Same two business names, same cause, caught in the preview and missed in email.** That is the strongest
argument for finishing the migration rather than patching emitters: the bug recurs wherever a surface was
not converted.

| Surface | State |
|---|---|
| Published page (`html.resolved_brand_label`) | ✅ Site.organization |
| Builder brand preview (`renderedBrandLabel`) | ✅ reads the rendered frame (2026-10-13) |
| Brand PICKER options (`stores/profile.js`, `Offers.vue`) | ❌ user profile `business.brands` — *"Manage your brands in Profile → Business"* |
| All transactional email | ❌ user profile (§1) |
| Profile → Business edit UI | ❌ still the edit surface for name/brands/NAP |

### The field delta

`Site.organization` already carries `name`, `legal_name`, `description`, `email`, `telephone`, `address`,
`founding_date`, `place_id`, `gbp_url`, `geo`, `opening_hours`. What lives on `user_profile.business` and
has **no home on the Site yet**:

| Field | Disposition |
|---|---|
| `brands[]` | **Add to `Site.organization`.** This is the author's ask: brands belong to the business that owns them, and an offer picks from its own Site's brands rather than a tenant-wide pool. |
| `sources{}` | Move with it — the per-field provenance (`stripe\|manual\|gbp\|derived`) is what stops a GBP/Stripe auto-seed clobbering a tenant's own value, and it is per-business. |
| `shipping_cutoff_hour` | **Not identity.** Operational, and arguably per-Site anyway (two shops can cut off at different times). Needs its own decision — it should not ride along silently. |
| `timezone` | Same. Operational, and already duplicated by `TenantAvailability`/booking. |

**The brand picker is the sharp edge.** Today an offer picks from a tenant-wide brand list. Once brands are
per-Site, the picker must be scoped to the Site the offer's page belongs to — which needs the SAME
page→Site resolution as §3.1. The two halves of this plan share one dependency, so they should ship in that
order rather than separately.

## 4. Proposed shape

**One resolver, Site-scoped, with a declared fallback.** Replace `tenant_email_identity(tenant_id)` with
`sending_identity(tenant_id, *, site_id="")` in `domain/business_email.py`:

```
site_id given        → Site.organization (name, NAP, gbp_url)
site resolvable      → from page_id → site_id (§3.1)
neither              → the tenant-level fallback, EXPLICITLY, with the reason recorded
```

Every emitter calls that one function. No emitter reads `Site.organization` or the user profile directly —
that rule is what preserves §2's guarantee while changing its scope.

## 5. Phasing

- **P1 — fix the reported bug.** Invert the precedence in `review_invites.py` so the Site wins, and resolve
  the Site from the invite's order `page_id` instead of "first Site". Smallest change that makes the
  reported email correct. **Does not touch Reply-To.**
- **P2 — the shared resolver.** Introduce `sending_identity(tenant_id, site_id=...)` and the page→Site
  lookup (§3.1). Move receipts, cart recovery, reminders, invoices and purchase-manage onto it one at a
  time, each with a test proving which Site's name it used.
- **P3 — per-Site Reply-To** *(only if §3.3 is decided that way)*. Per-Site email verification, reusing the
  existing code/TTL/attempt flow. Until then the Reply-To stays the tenant's verified address.
- **P3b — brands move to the Site.** Add `brands[]` + `sources{}` to `Site.organization`; scope the Offers
  brand picker to the offer's Site (depends on §3.1's page→Site resolution, same as P2). Decide separately
  where `shipping_cutoff_hour` and `timezone` live — they are operational, not identity, and must not
  migrate by accident.
- **P4 — remove the UserProfile Business section** *(only once P2 covers every send path, or the fallback
  is accepted as permanent)*. Removing it is a data migration, not a UI change: `business_name` /
  `business_email` are read by 16 modules, and `business.brands` backs a live picker.

## 6. Open decisions — author input needed

1. **§3.3 — the Reply-To question.** Verify per Site, or Site name + tenant verified Reply-To? This decides
   whether P3 exists at all. *Recommendation: the second, for P1–P2 — it fixes the reported bug this week
   without re-opening a security gate, and per-Site verification can follow if tenants ask for it.*
2. **§3.1 — `site_id` on the page, or a reverse index?** *Leaning: `site_id` on the page. The page already
   carries its own routing facts, and a Site edited between publish and send would otherwise change a
   message's identity retroactively.*
3. **Can the Business section actually be deleted (§3.4)?** Only if every send path resolves a Site.
   Invoices and platform notices look like permanent exceptions. *Leaning: keep the fields as a declared
   fallback, remove them from the UI, and stop tenants editing what no longer drives anything.*
4. **What about pre-multi-Site orders** with no `page_id` in metadata? They fall to the fallback; worth
   confirming that is acceptable rather than backfilling.
