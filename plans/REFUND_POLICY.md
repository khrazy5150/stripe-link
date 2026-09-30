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

1. **`domain/refund_policy.py`** — port the vocabulary tables, `normalize_policy`, `build_policy_definition`
   and `resolve_effective_refund_policy`, reading the nested map. Pure, no I/O, fully testable. Include the
   legacy coercion: products already carry policies written by the JS literal, and they must normalise.
2. **Tenant profile field + validator** — `refund_policies.{physical,digital,subscription}`.
3. **Settings UI** — three policies, one per class, each a window/condition/return-method picker with the
   generated `short_label` and `full_policy` shown read-only so the tenant SEES what their storefront
   promises. This is the screen whose absence caused the whole problem.
4. **Product override UI** — render the inputs the wizard's picker already implies. They exist as form state
   with no fields; that is why "Override for this product" does nothing today.
5. **Server-side resolution on write.** The policy must be resolved by a HANDLER, not by the browser. Today
   the dashboard decides what a product promises, which is how a literal ended up on live pages.
6. **Retire the JS literal and the UserPreferences slot.**

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
- **Interim honesty.** Until step 3 ships, the least-dishonest change is to stop stamping
  `source: "user_preference_default"` on a value no preference produced.
