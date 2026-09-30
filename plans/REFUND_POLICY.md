# Refund Policy — port the primitive, change where it lives

**Status: planned, nothing built · Written 2026-09-30 · Supersedes the hollow wiring described in
`plans/TODO.md` 🚨 URGENT.**

## Why this exists

Every product in stripe-link carries a refund policy **nobody set**. `dashboard/src/stores/products.js:550`
returns a hardcoded constant at product-creation time — 30 days for physical, non-refundable for digital —
stores it on `Product.refund_policy`, and `html.py:4933` renders it on the public page. The record even
stamps `source: "user_preference_default"` while nothing anywhere reads
`UserPreferences.authoring_defaults.refund_policies`.

The author's words on discovering it: *"The reason I didn't notice it before is because the pages show a
refund policy that I assumed was the tenant default policy."* That is the failure — it looks configured.

This is not only cosmetic. A refund window on a public storefront is an **offer to the buyer**; the field
floor uses it to LICENSE the AI's `guarantee` claims (a numeric class, §A.7); and
`ai_provision.chosen_badges` labels the money-back trust badge from its `short_label`.

## What stripe-cart already got right

`../stripe-cart/src/refund_policy.py` (291 lines) is a real domain module and is the behavioural spec:

- **Vocabulary as DATA, not free text.** `REFUND_WINDOW_OPTIONS` (7), `CONDITION_OPTIONS` (4),
  `RETURN_METHOD_OPTIONS` (3). These are policy language — a tenant typing "about a month" is not a policy.
- **Three product classes**, including `subscription`, which stripe-link's thinking has been missing. Its
  windows are measured in HOURS (`72_hour_renewal`, 96, 120) because a subscription refund is about the
  renewal charge, not a parcel.
- **`resolve_effective_refund_policy(...)`** — one function, returning `mode` (`default` | `override`),
  `source`, `product_class`, and the resolved fields. This is what makes `source` earned rather than
  decorative.
- **Legacy coercion** (`_window_from_legacy`, `_condition_from_legacy`, `_return_method_from_legacy`) so old
  records normalise instead of breaking.

**PORT the module.** The vocabulary and the resolver are the valuable part, and the hour-based subscription
windows are precisely the sort of thing stripe-link would get wrong by inventing.

## What to change: the storage shape

stripe-cart flattens three sibling fields onto the tenant profile —
`refund_policy_physical` / `_digital` / `_subscription`. stripe-link is JSON-first and should not.

**Decision (author, 2026-09-30): port the module, change the storage shape.**

| | stripe-cart | stripe-link |
| --- | --- | --- |
| Authority | tenant profile, 3 flat fields | tenant profile, ONE nested map |
| Shape | `refund_policy_physical: {...}` | `refund_policies: {physical, digital, subscription}` |
| Override | `product_metadata.refund_policy_override` + `_mode` | `Product.refund_policy` (exists) |
| Resolution | `product_override → tenant_default` | same — two levels, not three |

**`UserPreferences.authoring_defaults.refund_policies` is retired.** It was the wrong home: a refund policy
is a property of the BUSINESS, not of the person authoring. stripe-cart puts it on the tenant and that is
right. Nothing reads the UserPreferences copy today, so there is no migration — only a schema removal.

**"Tenant default" and "user preference default" collapse into one option.** The wizard's three-way picker
becomes two: *Use my default* / *Override for this product*. The third was fiction; for a solo tenant the
first two were the same thing anyway.

## Phases

1. **`domain/refund_policy.py`** — ✅ **SHIPPED 2026-09-30** (41 tests). Port the ALGORITHMS —
   `normalize`, `build`, `resolve`, two-level resolution — reading the nested map. Pure, no I/O.

   **NOT the vocabulary.** This plan originally said to port stripe-cart's tables and discovery overruled it:
   stripe-link's own enums are better and already hold live data. stripe-cart has `30/60/90_day_returns` and
   `72/96/120_hour_renewal`; stripe-link has `7_days`/`14_days`/`custom`, digital-aware conditions
   (`defective_only`, `not_downloaded`), a semantic `return_method` (`digital_revoke_access`) rather than
   stripe-cart's label-printing one, and `keep_it_below`, which stripe-cart has no concept of. The repo's own
   decision priority settles it — existing stripe-link architecture outranks stripe-cart behaviour — and a
   test now asserts the module's three tables equal the schema's three enums, so they cannot drift.

   The legacy text-sniffing coercion (`_window_from_legacy` reading "within 30 days" out of prose) was also
   NOT ported: all 32 live dev products store well-formed values in stripe-link's vocabulary, so it would be
   80 lines of migration code for data that does not exist.
2. **Tenant-level field + validator** — ✅ **SHIPPED 2026-09-30** (23 tests).
   `legal_defaults.refund_policies.{physical,digital,subscription}` on **TenantConfig**, not TenantProfile.

   **Why the change of document.** TenantProfile is written only by registration, auth and Stripe webhooks,
   and it holds `billing_status`, `tier_id`, `billing_exempt` and `stripe_subscription_id`. Reaching a refund
   setting there means giving the dashboard a PUT over that document — which would hand every tenant their
   own billing tier. TenantConfig is already the tenant-editable settings document, already served at
   `/config` with GET and PUT, already validated, and already holds `legal_defaults`, so the refund URL now
   sits beside the policy it links to. Same intent as the plan (ONE tenant-level home, not per-user, not
   `UserPreferences`), without inventing an endpoint or an exposure.

   The validator is strict about the three enums rather than falling back: a typo'd window that silently
   defaulted would be the same fault as the literal — a commercial term the tenant did not choose. A custom
   window with no prose is refused, because a custom policy IS its prose.
3. **Settings UI** — ✅ **SHIPPED 2026-09-30**. A "Refund Policy" card on Configuration, one block per
   class, each with a window/condition/return-method picker and the generated sentence shown read-only so the
   tenant SEES what their storefront promises. This is the screen whose absence caused the whole problem.

   Three things it does deliberately:

   - **A per-class "Set my own" toggle.** Off means the platform's default applies and the preview says so in
     those words — *"The platform's default — nobody chose this."* The distinction between a chosen default
     and a fallback is the entire point, so the UI states it rather than hiding it behind an identical-looking
     pre-filled form.
   - **The sentence comes from the server.** `/config?refund_options=1` returns the vocabulary AND a generated
     preview for all 126 class/window/condition combinations. A JavaScript copy of the sentence template is
     *precisely* how the literal in `stores/products.js` came to be published, so the browser is not allowed
     to compose one. The 20KB payload is opt-in per request so no other caller of `/config` pays for it.
   - **The class labels name the mapping.** "Digital goods & services" makes it visible that services resolve
     under `digital`; a tenant selling services would otherwise hunt for a block that does not exist.
4. **Product override UI** — ✅ **SHIPPED 2026-09-30**. The picker's three options became two: the old
   "Use user preference default" and "Use tenant default" named the same thing, and the preference they
   referred to was never read by anything. Choosing "Override for this product" now reveals the three
   structured pickers (and a wording box for a custom window), with the server-generated sentence previewed
   below. Switching to override seeds from what the product already promises rather than from blanks — a
   tenant narrowing a window should see the current one first.

   A legacy product whose policy is stamped `user_preference_default` shows as **"use my default"**, not as
   an override. Showing it as an override would freeze the literal: that product would keep promising 30 days
   whatever the tenant later set.
5. **Server-side resolution on write.** The policy must be resolved by a HANDLER, not by the browser. Today
   the dashboard decides what a product promises, which is how a literal ended up on live pages.

   ✅ **SHIPPED 2026-09-30.** `domain/refund_policy.apply_to_product` is the rule — pure, no I/O — and both
   write paths apply it:

   - `handlers/products.resolve_refund_policy` reads TenantConfig and calls it before validation.
   - `handlers/ai_generate` calls it for AI-created products. **This was a real hole:**
     `ai_provision.product_document` set no policy at all, so an AI-generated product saved with none — its
     page showed no refund section and `chosen_badges` had no guarantee to read. A second write path quietly
     disagreeing with the first is how the original literal survived so long.

   **Anything the client sends that is not a deliberate override is DISCARDED.** That is the property that
   actually fixes the bug: an old cached dashboard bundle still posting the literal gets the tenant's real
   default written instead. Fixing the browser is not enough, because a browser is not a place you can
   enforce anything.

   An unreadable TenantConfig falls back to the platform default rather than to no policy — an unreadable
   settings table must not decide what a storefront promises, and must not block a save or fail a generation
   either.
6. **Retire the JS literal and the UserPreferences slot.** ✅ **SHIPPED 2026-09-30.**

   `stores/products.js` no longer contains a policy: `refundPolicy(form)` returns the override intent or
   `null`, and the field is omitted entirely when there is no override. The product form's defaults no longer
   carry `"30_days"`, `"30-day money-back"` or the sentence.

   `UserPreferences.authoring_defaults.refund_policies` is gone from the schema, the validator and the
   fixture. **Both user-preferences tables were verified EMPTY — zero rows in dev AND prod.** So the
   provenance stamped on 29 live products pointed at a table that has never held a single record. That is the
   strongest form of the original finding: not merely "nothing read it", but "there was never anything there
   to read". `authoring_defaults.return_address` and `refund_request_handling` stay — they belong to the
   REQUEST flow, per Open below.

## What this does NOT change

`refund_requests` and the Refunds screen were built assuming this existed (author: *"putting the cart before
the horse"*). They consume a policy rather than defining one, so they should need little: verify
`refund_policy_return_note` and the request flow read the resolved policy rather than the raw product field.

## Order, and why this plan goes first

The author's sequence, 2026-09-30 — this plan, then `plans/SHIPPING_CHARGES.md`:

    1. refund policy primitive -> tenant defaults -> product override
       -> server-side resolution -> storefront/refund/AI consumers
    2. shipping primitive -> offer shipping mode -> shipping calculation
       -> order shipping_amount (+ eventually shipping_cost)
       -> fee/tax/refund/ledger -> Stripe Checkout shipping_options

Refunds lead because the damage is already live: pages are promising a window right now, and every day of
delay is more orders carrying a term nobody chose. Shipping is a missing capability, which is a smaller
category of wrong than a false statement already published.

The phase order WITHIN each plan matters for the same reason in both: the resolution step (5 here, the fee
and invariant rules there) comes before the consumers, because a rule settled after its consumers are built
has to be retrofitted through all of them.

## The principle both plans exist to serve

> *"Customer-facing commercial promises should never be implicit."* — the author, 2026-09-30

Two bugs, one shape. The refund policy was implicit because a default was hardcoded; shipping was implicit
because "free" was assumed. Both become explicit domain data that downstream systems consume, and where
there is no answer the page says **nothing** — silence is recoverable, a false promise is a dispute.

## Open

- **`refund_return_address` and `refund_request_handling`** (`manual_review | auto_reply`) exist on
  stripe-cart's tenant profile and have no stripe-link equivalent. They belong to the REQUEST flow rather
  than the policy, so they are noted here and scoped with the Refunds screen, not with this.
- **Interim honesty.** ✅ Done in step 1: `platform_default` is now a source value, and it means what it
  says — nobody chose, this is the fallback. Added to `Product.schema.json` along with `tip_jar_default`,
  which `handlers/tip_jar_provision.py` was already writing without it being a valid enum value.
- **`custom` has nowhere to put a number.** `refund_window: "custom"` means the tenant's prose governs, and
  the schema has no days field, so `window_days()` returns None and no deadline can be computed. Nothing
  breaks today — `handlers/refunds.py` never computes one, the merchant decides — but a future automatic
  deadline needs a `custom_days` field. `build()` refuses a custom window with no prose in the meantime.

### What step 1 found in live data

- **Every published physical-product page prints the same paragraph twice.** The literal appends the
  return-note text to `full_policy`, and `runtime/html.py` ALSO renders
  `refund_policy_return_note(policy)` as its own paragraph — so the page says it once as "does not" and once
  as "doesn't". Verified on `jb-pages-dev/test/page_3VmYubKR3AM`. The note belongs to the renderer; the
  policy sentence belongs to the module. Fixed by omission.
- **A physical product sold BOTH one-time and daily-recurring.** stripe-cart's rule (any recurring price
  makes the product a subscription) would have narrowed that product's published promise from 30 days of
  delivery to 72 hours of renewal — for the one-time buyers too. Split into `product_class` (the product as
  a whole; subscription only when it is the ONLY way to buy) and `purchase_class(product, price)` for the
  order and refund paths, where the buyer's actual choice is known.
- **The legacy copy generator was wrong for subscriptions.** `_window_days` turned 72 hours into 3 days and
  the single sentence template said "of delivery", producing *"within 3 days of delivery"* for a renewal
  window — wrong unit and wrong event. The basis now follows the class: delivery / purchase / renewal.
- **Verified across all 32 live dev products:** the only change to rendered text is the duplicated paragraph
  disappearing. 16 digital identical, 1 tip jar identical, 3 carry no policy and still carry none.
