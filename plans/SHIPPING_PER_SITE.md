# Shipping per Site

**Status:** S1–S3 SHIPPED 2026-11-04 (dev+prod pending deploy). S4–S5 not built. Written 2026-11-04, after `SITE_AS_BUSINESS_IDENTITY.md` P1–P4
made business identity per-Site. The author's ask: *"plan a migration to move the shipping to Sites."*

**Premise:** a Site is a business (`SITE_AS_BUSINESS_IDENTITY.md` §3b). Two businesses under one account
can ship from two warehouses, promise different delivery windows, and close their working day at different
times. Today none of that is possible: one tenant has exactly one shipping setup.

---

## 1. First, a correction to the premise

"Move the shipping to Sites" sounds like moving fields off the user profile, the way brands and the sender
identity moved. **It is not that.** Measured 2026-11-04:

**The ship-from address was never on the user profile.** It is already on the `ShippingConfig` document
(`ship_from_address`, `return_address`), keyed per tenant. `shipping._seller_contact` reads the profile's
`business` block and contributes exactly one thing to a label: **an email**, because Shippo refuses a
purchase with an empty `address_from.email` — `sender_address()` prefers the address's own email, then
`business.email`, then the signup email.

So the whole tenant-profile dependency of the shipping path is:

| Read | Where | What it decides |
|---|---|---|
| `business.email` | `shipping.sender_address` | the ship-from email, when the address carries none |
| `business.timezone` | `store_timezone` | whose 3pm the cutoff means |
| `business.address` | `suggest_timezone` | the timezone GUESS when none was chosen |
| `business.shipping_cutoff_hour` | `store_cutoff_hour` | when the working day ends |

`business.phone` and `business.address` are **written** by the Stripe Connect NAP seed
(`connect_sync.seed_business_identity`) and read by nothing in shipping.

**Therefore this work is two separable things**, and conflating them is the main risk:

- **(A) The working day** — `timezone` + `shipping_cutoff_hour` (+ the address the timezone is guessed
  from). Four reads, small, and the piece `SITE_AS_BUSINESS_IDENTITY.md` §P4 deferred to "its own plan".
- **(B) `ShippingConfig` itself** — making the tenant's carrier/warehouse setup per-Site. Ten readers,
  twenty-one template grants, a per-mode credential split already layered on it, and a primary key change.

(A) is a week's edge; (B) is the real plan. They can ship independently and (A) should go first.

---

## 2. What is a per-Site fact, and what is not

**The governing precedent is already in this codebase**, and it is exact. `domain/shipping_keys.py` faced
the same question for Stripe MODE and answered it:

> *"The provider stays shared and only the credential splits. A tenant's warehouse address, parcel
> defaults and label format are the same facts in both modes, and nobody uses Shippo for test and EasyPost
> for live. Making the whole document mode-scoped would force them to re-enter their address to flip a
> toggle, which is how a safety feature becomes the thing people route around."*

Apply the same test per Site — *is this plausibly a different fact for a second business?*

| Field | Per-Site? | Why |
|---|---|---|
| `ship_from_address` | **Yes** | The point of the whole plan. Two shops, two warehouses. |
| `return_address` | **Yes** | Follows the ship-from; a return goes back to the business that sent it. |
| `zones` | **Yes** | A delivery promise is part of a storefront's offer, and it is shown to the buyer. |
| `boxes` | **Probably** | A business packs what it sells. Shared is a defensible default. |
| `default_parcel` | Probably | Follows `boxes`. |
| `enabled` / `enabled_opt_out` | **Yes** | One business may ship and the other be digital-only. |
| `provider` + credentials | **No** | Nobody runs Shippo for one business and EasyPost for another. Already split per MODE; a second axis multiplies the slots for no benefit. |
| `label_options` | No | Printer and format are the account's equipment. |
| `rate_options` | No | A rate-selection policy ("cheapest", "fastest") is how the tenant works. |
| `enabled_services` | Borderline | Carrier services are provider-shaped; keep shared until a tenant asks. |
| `auto_fulfill_after_label_purchase` | No | A workflow preference. |

**So: an OVERRIDE model, not a per-Site document.** A Site states only what differs; everything else is
inherited from the tenant's config. This is the shipping-keys answer and it avoids its named failure mode —
a tenant who adds a second Site must not have to re-enter a warehouse address before they can quote a rate.

```
resolve(field, site) =  Site's shipping override, if it states this field
                     →  the tenant's ShippingConfig
```

Note `offer.shipping` is a THIRD, unrelated thing and must not be folded in: it is what the BUYER is
charged. `ShippingConfig` is the rate the tenant BUYS from a carrier. That separation already exists and
is documented on the Offer schema; keep it.

---

## 3. The four structural problems

### 3.1 `ShippingConfig` is keyed on `tenant_id` alone, and is not mode-scoped

`shipping_config_repository()` is a `SimpleKeyRepository(key_field="tenant_id")`. It takes no mode and has
no second key component. A per-Site override therefore has to go **inside the document** (a
`sites: {<site_id>: {...}}` map) or into a new document type keyed `TENANT#<t>` / `SITE#<site_id>`.

**Recommendation: a map inside the existing document.** The whole config is one small document read on
every checkout and every render; a second table is another read on a hot path, 21 more template grants, and
a second thing to keep in sync. A map keeps the primary key, the validator and every grant exactly as they
are.

**⚠️ But a map is a shared-document read-modify-write**, which this codebase has been bitten by
(`feedback_shared_document_read_modify_write`): load-mutate-put on a document many writers share loses
siblings under fan-out. Two Sites' shipping screens saved at once would lose one. **So the per-Site write
must be a targeted `update_item` on `sites.<site_id>`, never a put of the whole document** — the same shape
as `documents.set_site_id`.

### 3.2 A fulfilment-time read has to know WHICH Site

Today every reader passes `tenant_id`. Under this plan each needs a Site. Where each one gets it:

| Reader | Has | Resolution |
|---|---|---|
| `checkout.py` | `page_id` in the request | `page.site_id` (the P1 edge) |
| `page_render.py`, `page_publish.py` | the page | `page.site_id` |
| `orders.py`, `shipping.py` (label buy) | the order | `order.attribution.page_id` → `page.site_id` |
| `upsell.py` | the funnel page | `page.site_id` |
| `ai_generate.py` | the page being generated | `page.site_id` |

**Every one of them can already answer it**, because `SITE_AS_BUSINESS_IDENTITY.md` P1 put `site_id` on the
page and P2 built the `page_id → Site` walk. That is the dependency this plan inherits, and it is done.

An order with no `page_id` (pre-multi-Site) resolves to no Site and falls back to the tenant config —
which is exactly right and needs no special case.

### 3.3 The working day is read from a `business`-shaped dict

`store_timezone(business)` and `store_cutoff_hour(business)` take the profile's `business` block. They are
pure functions over a dict, so **the cheapest correct change is to pass the Site's `organization` instead**
— it already has `address`, and `timezone` / `shipping_cutoff_hour` would be added to it. No signature
change, no new module: `store_timezone(site_organization or tenant_business)`.

That makes (A) genuinely small: two fields on `Site.organization`, one resolution helper, and the four call
sites.

### 3.4 Nothing shows a tenant which Site a shipping setting belongs to

The Shipping screen is tenant-wide today. Per-Site it needs a Site selector and, more importantly, a clear
answer to *"this address is inherited — do you want to override it for this site?"* An override UI that
hides inheritance produces a tenant who thinks they changed one warehouse and changed none.

---

## 4. Phasing

- **S1 — the working day moves to the Site. SHIPPED 2026-11-04.** `Site.organization` gains `timezone` +
  `shipping_cutoff_hour` (both nullable: absent means inherit). `store_timezone.working_day()` resolves
  them **per field, Site before account** — a shop may keep the account's timezone and close earlier, and
  document-level resolution would make setting either field silently adopt the other's default.
  `attach_delivery_promise` resolves the selling business through `sender_identity.site_organization`.
  Closes the item `SITE_AS_BUSINESS_IDENTITY.md` §P4 deferred.

  The subtlety worth keeping: `suggest_timezone` never returns `""` — it answers UTC for an address it
  cannot place — so chaining the guess per source would let an EMPTY Site address swallow the account's
  real timezone. An explicit answer at either level wins first, then ONE guess is made. And midnight is a
  real cutoff: hour 0 is falsy, so a `||` anywhere in the chain reads it as unset and returns 3pm. Both
  have tests.
- **S2 — the label's sender is the selling business. SHIPPED 2026-11-04.** `sender_address` takes an
  `organization` and prefers its **verified** email, after the address's own and before the account's.
  Unverified is ignored for the same reason it is for a Reply-To: a carrier's "we could not deliver"
  notice going nowhere is worse than one going to the account owner.
- **S3 — `ShippingConfig.sites{}` overrides. SHIPPED 2026-11-04** (read path; nothing writes the map yet,
  so behaviour is identical today). `domain/shipping.config_for_site(config, site_id)` lays a Site's
  overrides over the account's, field by field, restricted to `SITE_OVERRIDABLE`
  (`ship_from_address`, `return_address`, `zones`). An empty value (`{}`, `[]`) means inherit, because
  that is what a half-filled form produces and shipping from nowhere is worse. The `sites` map is
  STRIPPED from the result so no reader can resolve twice and reach a different answer.

  **Where it resolves, and the correction to §3.2 above.** This section originally planned to thread a
  Site through all ten readers. It resolves at `config_for_mode`'s seam instead — the codebase's own
  answer to the identical problem for the carrier key: *"twelve places decrypt `provider.api_key_ref`...
  adding the mode to each would have been twelve chances to miss one."* `quote_rates` and `buy_label` each
  resolve the selling Site ONCE (`selling_site`) and use it for both the override and the sender email,
  because two reads could disagree and put one business's warehouse on another's label.

  The other eight readers are NOT threaded, deliberately: they are per-handler loaders with divergent
  failure semantics (one returns `True`, one a `dict(blank, reason=...)`) and they read `zones`/`enabled`
  — which is §S5's territory. Consolidating them is worth doing and is not this phase.
- **S4 — the write path and the screen.** Targeted `update_item` per Site (§3.1), plus the Site selector
  and an explicit inherited/overridden state.
- **S5 — per-Site enablement.** `enabled` / `enabled_opt_out` per Site, so one business can be
  digital-only. Deliberately last: it changes whether a buyer is offered shipping at all, and wants S3's
  resolution proven first.

No migration of existing data is required by S1–S3: an absent Site override means inherit, and every
tenant today has exactly the behaviour they have now. **S4 is the first step that writes**, and even then
the tenant-level config remains the default rather than being moved.

---

## 5. Open decisions — author input needed

1. **Are `boxes` and `default_parcel` per-Site or shared?** A business packs what it sells, which argues
   per-Site; but a tenant with one warehouse and two brands would then maintain two identical box lists.
   *Recommendation: shared in S3, add to the override map in S4 only if asked.*
2. **Should a Site be able to use a DIFFERENT carrier account?** §2 says no, on the shipping-keys
   precedent. Worth confirming, because the answer is hard to reverse: per-Site credentials multiply the
   key slots by the number of Sites and the KMS encryption context is deliberately not scoped
   (`SECRET_MODE = "shipping"`), so changing it would make stored keys undecryptable.
3. **What does a Site inherit at CREATION?** Nothing (pure inheritance, the override map starts empty), or
   a copy of the tenant's ship-from so the screen shows something concrete? *Recommendation: inherit, and
   label it as inherited — a copy silently freezes a value the tenant did not choose, which is the mistake
   `openEdit` already avoids for the creator-username fallback.*
4. **Does the cross-mode Site copy carry shipping overrides?** `COPY_TO_ENVIRONMENT.md` D1 makes a copy a
   same-id upsert, and `ShippingConfig` is not mode-scoped at all — so a Site's override would apply in
   both modes automatically. That is probably right (a warehouse does not move between test and live) but
   it should be a decision, not an accident.
