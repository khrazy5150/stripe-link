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

## 3b. ⭐⭐ Why this is a PRICING change, not a refactor (author, 2026-11-03)

The author's framing: **Site becomes the unit of "a business", and the number of Sites becomes the tier
axis** — Free 1, Basic 3, Pro 10. That reframes the whole plan. It is not cleanup; it is the thing that
makes a multi-business tier sellable.

**The commercial logic only closes if identity is per-Site.** "How many businesses can I run" has to equal
"how many Sites I pay for". While any part of business identity still lives on the tenant — the brand
list, the email sender — the axis is muddled: a tenant has one tenant-wide business identity regardless of
what they pay. Finish the migration and the answer becomes structural rather than enforced.

### The mechanism already exists

Plans carry numeric allowances today — `ai_generations` and `ai_images`, read from the plan record with
buyer-facing names in `_ALLOWANCE_LABELS` ("AI-written pages a month"). **A `sites` allowance is the same
shape**, needs no new machinery, and is editable from the Admin Site's Pricing screen without a deploy.

### But two gates must coexist, and they are different questions

`sites` is ALREADY a boolean capability, and it is in `FREE_TIER_CAPABILITIES` — "may this tenant use Sites
at all". The cap is a second, numeric question: "how many". Both are needed:

| Gate | Question | Where |
|---|---|---|
| `entitlements.sites` (exists) | may they use Sites at all? | free-tier floor — stays yes |
| `allowances.sites` (new) | how many may they have? | plan record, like `ai_generations` |

Conflating them would mean a downgrade removing Sites entirely rather than capping them.

### ⚠️ The hard question is DOWNGRADE, not upgrade

Creating the 4th Site on a 3-Site plan is easy to refuse. The real decision is what happens to Sites 4–10
when Pro → Basic, or when a subscription lapses to free. The free tier is **free-forever** and the pricing
pivot's stated rule is that an expired trial or cancelled subscription "sells on at the free-tier fee" —
pages keep serving, checkout keeps charging. Deleting a tenant's Sites would violate that outright.

Options, none free of cost:

| | |
|---|---|
| **Soft-lock extra Sites** ✅ **CHOSEN 2026-11-03** | Keep serving published pages; refuse edits and new publishes on Sites over the cap, **tenant picks which stay active**. Preserves free-forever; most work. |
| **Read-only over the cap** | Everything keeps serving, nothing over the cap can be edited. Simpler, blunter. |
| **Grandfather existing** | Cap applies to NEW Sites only. Zero disruption, but the tier never converts anyone who already has three. |

*Recommendation: soft-lock, with the tenant choosing which Sites stay active.* It is the only option that
keeps the free-forever promise while making the tier mean something.

### Two live facts that constrain the rollout

1. **No site-count gate exists anywhere** — verified: no `max_sites`, no counter, nothing. The cap is new
   machinery, not a changed constant. Note the free tier's "Unlimited landing pages" is **not** in
   conflict: it means unlimited pages *within* a Site (author, 2026-11-03), which stays true. The card
   needs a Sites line added, not that line corrected.
2. **The author's own dev tenant has 3 Sites** (`poliaxis-nutrition`, `poliaxis-nutrition-test`, `quill`,
   `quill-test` subdomains). So the "Poliaxis vs Quill" email is two of three real businesses on one
   tenant — this plan's motivating bug and its motivating revenue case are the same account.

## 3c. The cap counts LIVE-mode Sites (resolved 2026-11-03)

**Vocabulary first, because an earlier draft of this plan got it wrong.** *Sandbox* is the DEV DEPLOYMENT
(`sandbox.juniorbay.com`) — developer-only, no tenant ever touches it, and irrelevant to pricing.
*Production* (`app.juniorbay.com`) is where every tenant lives, and it carries BOTH Stripe modes: `test`
(off by default — where a tenant builds, then copies to live) and `live`. Keys carry `#mode=test` /
`#mode=live` to separate the data inside one deployment. "A sandbox Site" is not a thing. See
`plans/STRIPE_MODE_STORAGE.md` and the standing rule that `environment == prod` is abolished legacy for
`mode == live`.

**The keying, measured on dev.** `sites_repository` is `mode_scoped=True`, so a Site lives at
`SITE#<mode>#<site_id>`, and a Site copied to the other mode **keeps its `site_id`**:

```
SITE#live#site_rWLjyL57Pn5Gk5     1 live Site
SITE#test#site_rWLjyL57Pn5Gk5     the same Site, copied to test
SITE#test#site_3SxIqyfqnqrbmo     a test-only Site
```

So "how many Sites does this tenant have" has three possible answers (1 live, 2 test, 2 distinct ids) and
the cap must say which.

**Decision (author, 2026-11-03): the cap applies PER MODE.** Free = 1 Site in live **and** 1 in test;
Basic = 3 and 3; Pro = 10 and 10. Not "live only, test unlimited" — an earlier draft of this section said
that and it was wrong, because it let a free tenant build fifty businesses in test mode and flip them in
one at a time. Per-mode is also the simpler promise: *"your plan includes N sites"* means N in each mode.

The point of allowing test at all is the **round trip**: a free tenant enables test mode, copies their
live Site over, experiments, and copies back. The two modes holding *different* Sites is permitted — it is
just not the recommended way to work, because then nothing can be copied either direction without
displacing something.

### Why the copy does not fight the cap

`COPY_TO_ENVIRONMENT.md` D1 settles this: a copy is **same id (sync)**, not a fresh id. Confirmed in live
data — `SITE#live#site_rWLjyL57Pn5Gk5` and `SITE#test#site_rWLjyL57Pn5Gk5` are one Site in two partitions.

So copying a Site into the other mode is an **upsert of the same `site_id`**, and at a cap of 1 it is a
no-op against the counter:

| Situation | Copy live→test | |
|---|---|---|
| test is empty | creates `SITE#test#<same id>` | 0 → 1, allowed |
| test holds the SAME `site_id` | overwrites it | 1 → 1, allowed |
| test holds a DIFFERENT Site | would be 1 → 2 | **refused at cap** |

Only the third case trips, and the refusal is explainable in one sentence: *"Your plan includes one test
Site and it is currently <name>. Replace it, or upgrade."* **The counter must therefore count distinct
`site_id`s within the target mode, and the copy path must check the cap BEFORE writing** — otherwise the
upsert silently succeeds and the tenant is over.

**A Site is mode-scoped by design, not by accident** — worth recording so this is not re-litigated. The
schema says so itself:

> `stripe_mode` — *"The Stripe mode this Site belongs to. NOT the deployment: `environment` (dev/prod)
> names the stack, and one stack serves both modes. Called `environment` until 2026-10-23, which is how the
> two came to be read for each other. Sites are authored in test and copied to live by a later workflow."*

Mode runs to the edge too: the routing `kvs_key` pattern is `^site:(test|live):[a-z0-9.-]+$`, so the
CloudFront KeyValueStore holds the two separately. A "modeless Site" would mean reworking `stripe_mode`,
the `pages` map (whose page_ids are themselves mode-scoped), the hostname split and the edge keys — and
the cap does not need any of it. Counting the live partition gives the same answer far more cheaply.

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

- **P1 — fix the reported bug. SHIPPED 2026-11-03** (`handlers/review_invites.py`,
  `handlers/stripe_webhook.py`, `domain/review_invites.py`, `tests/test_invite_business_identity.py`).
  The invite now records the page the buyer converted on — read from `order.attribution.page_id`, which is
  where every order builder already put it, so no new order field — and the sweep resolves
  page → `page.site_id` → Site → `organization` per invite, cached by `(tenant, page)` rather than by
  tenant: two invites from two Sites in one sweep are signed differently. The precedence is inverted, so
  the Site's name beats `TenantProfile.business_name`, which is now only the fallback for an invite whose
  Site has no organization or whose page cannot be resolved. `ReviewInvitesFunction` gained `PAGES_TABLE`
  and a read grant on it. **Reply-To is untouched** — still the tenant's verified address, because that is
  the only one SES has been shown (P3). Legacy invites carrying no `page_id` keep the old first-Site scan.
  Not yet done here: `handlers/cart_recovery.py` has its own copy of the first-Site lookup, which P2
  replaces rather than this phase duplicating the fix into.
- **P2 — the shared resolver. SHIPPED 2026-11-03** (`stripe_link/sender_identity.py`,
  `tests/test_sending_identity.py`, `tests/test_sender_identity_wiring.py`).
  `sending_identity(tenant_id, *, site_id="", page_id="", mode="live")` returns
  `{business_name, reply_to, organization, source}`. Three rules, in order: a NAMED Site wins (`site_id`,
  or `page_id` through the page's `site_id` edge, falling back to the route-map scan); ONE unambiguous
  Site wins (nothing narrowed the message but the tenant has exactly one business — a Site with no
  organization is not a second candidate, because ambiguity is between businesses, not Sites); otherwise
  the TENANT answers and `source` records that it did. With two businesses and no context the resolver
  **declines to pick** — one wrong-but-consistent name beats a coin flip between two, which is what the
  two `_tenant_organization` copies were doing.

  It lives in its own module, not in `mailer.py`: `test_env_var_grants` propagates what a module reaches
  to every function importing it, and in the mailer it left fifteen send-only functions declared
  `SITES_TABLE`/`PAGES_TABLE` and granted read on both for a lookup they never perform.

  **Every tenant-authored sender is on it**: the order receipt and tip-renewal notice (from
  `order.attribution.page_id` + `stripe_mode`), the tracking email, purchase-manage's link email and
  cancellation (the link email lists several purchases, so it uses their page only when they agree on
  one), the abandoned-cart nudge (the cart now records its `page_id`; the published page already carried
  it), the review invite (P1), the invoice, the staff delegation notice, the lead-magnet download (name
  only — its verified-address gate is untouched), the appointment reminder SMS, and the webinar
  confirmation / reminder / cancellation. Each sweep caches by `(tenant, page)`, never by tenant: a
  per-tenant cache would sign every message in one pass with whichever Site resolved first, which is the
  reported bug one layer down.

  **Four of them were resolving their name from fields that are always empty** —
  `TenantProfile.business_name` / `support_email`, dead on every tenant in every environment since before
  they were written. The invoice, the delegation notice and the appointment reminder therefore named no
  business at all, and `purchase_manage._business_name` read the tenant profile for a USER-profile field,
  returned `""` every time, and made a buyer's own purchase page say "the seller". Two receiver-aware
  guards now watch both rules (`identity["business_name"]` is the point, `profile.get("business_name")`
  is the bug), each with a companion test proving it matches something.

  Still tenant-level by design: `send_email`'s own last-resort fallback for a caller that states no
  sender, and platform-authored mail, which has no Site. **Reply-To is untouched throughout** — see P3.
- **P3 — per-Site Reply-To. SHIPPED 2026-11-03** (`domain/business_email.py`, `handlers/sites.py`,
  `schemas/Site.schema.json`, `dashboard/src/components/Sites.vue`,
  `tests/test_site_email_verification.py`). Verification is Site-scoped, same 5-minute TTL and 5-attempt
  cap, and `email_identity` now prefers the Site's VERIFIED address with the tenant's verified one as the
  fallback — never the Site's unverified one.

  The load-bearing details, each one mistake away from a tenant receiving another business's replies:

  - **`verification_scope(tenant_id, site_id)` is the salt**, so a code mailed to prove one Site's mailbox
    confirms nothing about another. Without it, a tenant controlling one address verifies every Site they
    own and the gate reduces to "this tenant has an inbox somewhere". A bare tenant scope is deliberately
    the SAME string as before, so the tenant-level flow and its stored hashes are untouched — re-salting
    it would have silently unverified every tenant, including the fallback this phase depends on.
  - **`email_verified` is server-owned**, merged at the write boundary by
    `preserve_email_verification` exactly as `social_links.preserve_verification` handles sameAs. The
    Sites editor posts the whole `organization` back, so anything a client can send is something a client
    can assert, and this one decides what SES puts in a Reply-To.
  - **Re-pointing the address drops the proof** (and the pending code with it). The code proved "someone
    reads mail at THIS address" and that finding does not travel. So `organization.email` stays freely
    editable — it is the published contact address and belongs in the markup either way — and simply stops
    being usable as a Reply-To until the new one is proven.
  - **The confirm route is the only producer** of a verified state, the same arrangement
    `check_social_links` has.
  - The Sites editor shows the badge, and when unverified says what actually happens: *"replies to this
    site's emails go to your account email instead"*. A tenant who publishes a second business and never
    verifies its address would otherwise have nothing on the page tell them.

  `SitesFunction` gains the three grants the tenant-level flow already had (Debounce by secret path, SES,
  read on UserProfilesTable) plus two routes.
- **P3b — brands move to the Site. SHIPPED 2026-11-03** (`schemas/Site.schema.json`,
  `domain/documents.py`, `dashboard/src/stores/sites.js`, `Sites.vue`, `LandingPages.vue`, `Offers.vue`,
  `tests/test_site_brands.py`). `Site.organization` gains `brands[]` and `sources{}`; the Sites editor
  manages brands per business; `organizationFromBusiness` carries them into a derived default Site so a
  tenant's first Site keeps the list they already built.

  **Deviation from this plan's wording, deliberate.** It said *"scope the Offers brand picker to the
  offer's Site"*. The two surfaces that offer brands know different amounts, so they behave differently:

  - the **page builder** scopes STRICTLY to `selectedSite`. This is where it matters — the brand chosen
    there becomes the headline on a page belonging to exactly one business — and the builder already has a
    Site step, so there is nothing to guess.
  - the **Offers screen** cannot be scoped. An offer is authored before any page exists for it, so there
    is no page to resolve a Site through; resolving it would mean loading the whole pages list for a
    dropdown, and a brand-new offer would face an empty one either way. It offers the union and names the
    owner beside each brand *when the tenant has more than one Site*. Making ownership visible at the
    point of choice is what actually prevents the mistake scoping was for; hiding the ambiguity behind a
    filtered list that is sometimes wrong is not.

  Migration safety, in both: the tenant profile's list is a FALLBACK, used only where the Site declares no
  brands of its own, so nobody opens an empty dropdown before §P4 removes it. An offer already naming a
  brand no Site declares keeps it selectable, or saving the offer would silently reset its brand. The
  validator accepts exactly what `business.brands` accepted — uncapped, untrimmed — because a stricter
  rule would refuse a list the tenant could already save; the dashboard trims and de-duplicates on save.

  `sources{}` is a CARRIER with no writer yet, as this plan asked: `connect_sync.seed_business_identity`
  still stamps the tenant profile's copy, and pointing it at the Site is the GBP work.

  **`shipping_cutoff_hour` and `timezone` did NOT move** — asserted by a test, not just intended. They are
  operational rather than identity, `timezone` is already duplicated by `TenantAvailability`/booking, and
  both stay on the tenant profile until they get their own decision.
- **P4 — remove the UserProfile Business section** *(only once P2 covers every send path, or the fallback
  is accepted as permanent)*. Removing it is a data migration, not a UI change: `business_name` /
  `business_email` are read by 16 modules, and `business.brands` backs a live picker.

## 6. Open decisions — author input needed

1. ~~**§3.3 — the Reply-To question.**~~ **DECIDED 2026-11-03: verify an address PER SITE.** P3 is real
   scope, not optional. The author chose the fuller end state over my recommendation of Site-name-only —
   true per-business identity, at the cost of a verification per Site. Consequences: the existing
   code/TTL/attempt flow in `domain/business_email.py` must become Site-scoped rather than tenant-scoped;
   a Site with no verified address falls back to the tenant's verified one (never to an unverified Site
   address — that is the hole the gate exists to close); and onboarding a second Site now includes an
   email verification step, which the Sites editor must make obvious rather than letting a tenant publish
   and wonder why replies go elsewhere.
2. ~~**§3.1 — `site_id` on the page, or a reverse index?**~~ **DECIDED 2026-11-03: `site_id` on the page.**
   A direct read, and the page records the Site it belonged to at publish time — so editing a Site later
   cannot retroactively change which business an old order's email claims to be from. Costs an additive
   schema field and a backfill from `Site.pages`.
3. **Can the Business section actually be deleted (§3.4)?** Only if every send path resolves a Site.
   Invoices and platform notices look like permanent exceptions. *Leaning: keep the fields as a declared
   fallback, remove them from the UI, and stop tenants editing what no longer drives anything.*
4. **What about pre-multi-Site orders** with no `page_id` in metadata? They fall to the fallback; worth
   confirming that is acceptable rather than backfilling.
5. **§3b — the Site cap numbers and the downgrade rule.** Free 1 / Basic 3 / Pro 10 as stated? And what
   happens to Sites over the cap on downgrade — soft-lock, read-only, or grandfather? *Recommendation:
   soft-lock with tenant choice; it is the only option compatible with free-forever.*
6. ~~**§3b — does the cap apply to TEST-mode Sites?**~~ **RESOLVED 2026-11-03 — the cap is PER MODE**
   (Free 1 live + 1 test, Basic 3 + 3, Pro 10 + 10), and a cross-mode copy is a same-id upsert so it only
   trips the cap when the target mode holds a DIFFERENT Site. See §3c.
