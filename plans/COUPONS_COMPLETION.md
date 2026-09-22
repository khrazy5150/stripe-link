# Coupons: make the module do what its schema already promises

**Status: planned, not built. Written 2026-09-22.**

## What is true today

The Coupons module records coupons faithfully and powers the Offers picker. What it never learned to do is
create the Stripe objects it claims to represent.

**Verified:**

- Nothing in `src/` ever calls `POST /v1/coupons` or `POST /v1/promotion_codes`. There is no Stripe write
  path for coupons anywhere in the repo.
- `buildCouponDocument` (dashboard/src/stores/coupons.js) synthesises the ids locally:
  `stripe_coupon_id: form.stripe_coupon_id || couponId` and
  `stripe_promo_code_id: ... || \`promo_${couponId}\``.
- `sync.status` is written by the CLIENT as the literal `"synced"`, and
  `validate_coupon_document` merely *requires* the document to say so.

**And the schema states the contract the code does not honour:**

```json
"sync": { "status": { "const": "synced",
  "description": "Coupons are persisted only after Stripe sync succeeds." } }
"stripe_coupon_id":     "Stripe Coupon object ID."
"stripe_promo_code_id": "Stripe Promotion Code object ID."
```

So the module was built to the shape of a Stripe-backed feature with the Stripe half left out. The only
redemption path that has ever worked is `allow_promotion_codes`, which relies on a code existing in Stripe
because someone created it there by hand.

**Why it matters now:** the coupon landing-page element (`plans/COUPON_ELEMENT.md`, shipped to `main`
2026-09-22, NOT deployed) pre-applies `discounts[0][promotion_code]`. Given a placeholder id, Stripe rejects
the session outright — so a coupon page would fail checkout rather than merely lose the discount. That
integration is blocked on this work.

**No migration needed:** `jb-coupons-dev` and `jb-coupons-prod` both hold **zero** records. Every coupon
ever created will be created under the finished design. This is the cheapest this will ever be.

## Design

### Persist only after Stripe succeeds

The schema's own rule, and the right one: a coupon document that exists while its Stripe objects do not is a
promise the platform cannot keep. Create in Stripe first, store the returned ids, then write the document.
A failed Stripe call returns the error and writes nothing.

Two objects per coupon, in order:

1. `POST /v1/coupons` — `percent_off` or `amount_off`+`currency`, `duration`, `duration_in_months`,
   `max_redemptions`, `redeem_by`
2. `POST /v1/promotion_codes` — `coupon`, `code`, `expires_at`, `max_redemptions`,
   `restrictions[first_time_transaction]`, `restrictions[minimum_amount]`+`minimum_amount_currency`

Both on the tenant's connected account. Reuse what checkout already uses:
`checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)` for the `(api_key, stripe_account)`
pair, and the request shape in `create_stripe_checkout_session` — including its hard-won `HTTPError` body
extraction, because Stripe always explains a 400 in the body and `str(exc)` throws that explanation away.

**Send an `Idempotency-Key`.** A retried save must not create a second coupon; the key is the `coupon_id`,
which the client already allocates before the request.

### Immutability is not our rule — it is Stripe's, and it matches the author's

A Stripe Coupon's `percent_off`, `amount_off` and `duration` **cannot be changed after creation**; only
`name` and `metadata` are mutable. A Promotion Code can change only `active` and `metadata`.

That coincides exactly with the standing decision that **a coupon is immutable until it expires — if a
tenant makes a discount promise, they keep it**. So the constraint needs no invention, only enforcement:

- Editing a coupon's VALUE, duration or code is refused after creation. The tenant deactivates it and makes
  another. `update_coupon` today accepts these edits and must stop.
- Editing the name, and disabling, remain allowed.
- **The editor must say this before the first save**, not after — the point at which it is still free.

### Disabling, and what a page already promising it should do

Disabling sets `active: false` on the Stripe promotion code AND `status: inactive` on our record, so the two
never disagree. Then, at checkout, two independent gates: our record says whether the tenant still intends
to offer it, Stripe says whether the code exists and is active.

**A published page cannot know.** Its section carries the code and expiry copied at publish; a coupon
disabled afterwards leaves a page still showing a live-looking ticket. Expiry is the only case the page
handles alone.

So when the page promised a discount and checkout cannot apply it, checkout **refuses with a clear message**
("this offer is no longer available") rather than silently charging full price. Overcharging someone who
came for a specific price is the worst of the available outcomes, and the buyer can still buy at full price
from the ordinary page. *(Decision taken 2026-09-22; the alternative — fall through to full price — was
rejected for exactly that reason.)*

Disabling should also **warn which published pages still show the coupon**, so the tenant sees the promise
they are about to break.

### Modes

The coupons table is mode-scoped, and Stripe test and live objects are separate. A test-mode coupon creates
test-mode Stripe objects; going live requires creating it again in live. Never reuse an id across modes —
the id is meaningless in the other one, and a cross-mode id is how "no such promotion code" reaches a buyer.

### Three fields Stripe cannot enforce

Recorded because silently dropping them would be worse than not offering them:

- **`max_redemptions_per_customer`** — Stripe has no per-customer cap on promotion codes. Either enforce it
  ourselves at checkout (we know the customer) or remove it from the editor. Do not keep collecting it and
  ignore it.
- **`applies_to_offer_ids`** — Stripe's `applies_to.products` takes STRIPE product ids, and our offers are
  not Stripe products. Decide whether this becomes a real Stripe restriction or stays an app-level filter.
- **Code collisions** — a promotion code must be unique per account. Stripe returns a 400; surface it as
  "that code is already in use" rather than a raw Stripe message.

## Phases

- **C1 — create in Stripe on save.** The server owns the Stripe call (not the browser, which must never hold
  a secret key): `POST /coupons` creates both objects, stores the real ids, persists only on success.
  Idempotency-Key. Real errors surfaced. `sync.status` becomes true for the first time.
- **C2 — lifecycle.** Disable deactivates the promotion code; value/code edits refused with the reason;
  editor states immutability up front.
- **C3 — unblock the element.** Checkout resolves the real id and pre-applies it; when it cannot, it refuses
  with the message above rather than charging full price. `plans/COUPON_ELEMENT.md` finishes here.
- **C4 — the three unenforceable fields.** Decide each: enforce, or remove from the editor.

## Risks

- **This is a money path.** A coupon that applies when it should not costs the tenant real margin; one that
  fails when it should work costs them a sale they already paid to advertise.
- **Partial creation.** The Coupon can succeed and the Promotion Code fail. Persist nothing in that case, and
  let the orphaned Stripe coupon be — it is inert without a code pointing at it, and deleting it on a failure
  path invites deleting the wrong one.
- **The element is committed but not deployed**, and its checkout path would fail a session today. Either
  C3 lands first, or the element's pre-apply is made fail-safe before anything ships.
