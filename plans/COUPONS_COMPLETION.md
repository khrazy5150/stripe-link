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

## Status

- **C1 — create in Stripe on save: DONE 2026-09-22.** `stripe_coupons.py` creates the Coupon then the
  Promotion Code on the tenant's connected account, with an `Idempotency-Key` per object derived from the
  `coupon_id` the client already allocates. The handler validates BEFORE calling Stripe (a coupon we would
  refuse must not be created there first, leaving an orphan), stores the ids Stripe returned rather than
  the browser's placeholders, and persists nothing when Stripe refuses — surfacing Stripe's own words,
  because "Coupon code already exists" is actionable and "Stripe rejected the request" is not.
  Needs a read grant on StripeKeysTable.
- **C2 — lifecycle: DONE 2026-09-22.** Disabling deactivates the promotion code at Stripe before the record
  changes, so the two cannot disagree — a record saying `inactive` while the code still works is the more
  dangerous of the two disagreements. Editing a coupon's value, code or duration is refused with 409, and
  the check compares the STORED document so it cannot be edited around by posting a different value.
- **C3 — the element's checkout path: DONE 2026-09-22.** Because C1 stores the real Stripe id, checkout
  needs no second lookup: it resolves the code against the tenant's record and applies the stored id. When
  a code was asked for and cannot be honoured it raises `CouponUnavailable`, and a browser gets the branded
  "this offer is no longer available — you can still buy at the regular price" page with a 410. Seven ways
  to be unhonourable are covered, every one of which previously fell through to full price.
- **C4 — the unenforceable fields: DONE 2026-09-22.** `max_redemptions_per_customer` is disabled in the
  editor with the reason shown, rather than collected and ignored — the real answer to it is C5.
  `applies_to_offer_ids` is now ENFORCED at checkout: a coupon scoped to offers is refused on any other
  offer, the same way an expired one is. An empty list still means "any offer", which is what every coupon
  created so far carries, so nothing existing changes behaviour.

### Eligibility is not the same question as product scoping

Two different questions that `applies_to` blurs, worth keeping apart:

- **Eligibility** — *may this code be used on this offer at all?* App-side, because we know the offer.
  This is what `applies_to_offer_ids` means and what C4 implements.
- **Product scoping** — *which lines in a multi-product cart get the discount?* The grocery-store case: a
  bundle where only some items qualify (author, 2026-09-22). Stripe's `Coupon.applies_to.products` is the
  mechanism for this.

**Do not reach for `applies_to.products` without re-testing it.** Probed against a live connected account
on 2026-09-22 with `Stripe-Version: 2024-06-20`: both `applies_to[products][0]` and `applies_to[products][]`
were **accepted without error and then ignored** — `applies_to: null` on the create response AND on a
subsequent retrieve. Silently doing nothing is the worst available failure: the coupon would look scoped
and discount everything.

So product-level scoping is deliberately **not built**. The options, when it is wanted:

1. Re-test `applies_to` on a newer API version or a differently-configured account; adopt only if it echoes
   back what was sent.
2. Compute it ourselves: sum the qualifying line items and express the discount as a per-session
   `amount_off`. This works with no Stripe scoping at all, but it means a coupon object per checkout rather
   than per tenant — which collides with the immutability model in C2, so it is a real design change and
   not a patch.

## C5 — targeted coupons (the win-back case)

**The idea `max_redemptions_per_customer` was reaching for** (author, 2026-09-22): a tenant with 100
customers notices some who used to buy a product and stopped. She sends each a coupon with a discount good
enough to win them back — possibly a loss leader — and needs a cap on how many times **that customer** can
use it, or the giveaway is unbounded.

### The distinction that makes this work: known customers, not anonymous ones

**A targeted coupon is for a KNOWN customer. It is not a shared code.** That is the whole difference, and
every other property follows from it:

| | Shared coupon (the normal case) | Targeted coupon (C5) |
|---|---|---|
| Who may use it | anyone holding the code | one named customer, and nobody else |
| Who they are to us | anonymous until they pay | known before the code is issued |
| Per-customer cap | **impossible** — see below | natural: the code IS the customer |
| Forwarded to a friend | works for the friend | worthless to them |

**Stripe cannot cap a shared code per customer**, and the reason is exactly the anonymity: a promotion code
has one `max_redemptions` counter and no idea who is holding it. Everyone presenting it is the same unknown
buyer. There is nothing to count *per customer* because there is no customer yet. That is why the field has
never worked and never could, and why disabling it was the honest fix rather than a deferral.

**The cap is OPTIONAL** (author, 2026-09-22). A tenant need not set `max_redemptions` at all; a targeted
coupon with no cap is still safe, because it is bound to one customer either way. The cap exists for the
loss-leader case — where even that one customer using it repeatedly would cost real money — not as
something every targeted coupon must carry. Do not make it required in the editor, and do not default it to
a number: an unset cap means "as often as they like", which is a legitimate choice.

**But Stripe does exactly this from the other direction:** a Promotion Code can be scoped to one customer
with `customer: cus_…`, and `max_redemptions` then means "how many times THAT customer may use it". So the
feature is one code per recipient, not one code for the list.

That is strictly stronger than a counter, and worth stating plainly: a customer-scoped code **cannot be
used by anyone else**, so a recipient who forwards it to a friend or posts it publicly gives away nothing.
A per-customer cap on a shared code would have capped each abuser individually while leaving the code open
to everyone.

**What it needs:**

- A Stripe customer id per recipient. The win-back audience is by definition people who have already
  bought, and orders already carry `customer.stripe_customer_id` — so the audience and the prerequisite are
  the same set.
- One promotion code created per recipient, all pointing at ONE Stripe Coupon (which is what Stripe's
  two-object split is for). 100 recipients = 1 coupon + 100 codes.
- A personalised code in each email, which means campaign tooling — `plans/ATTENTION_PRIMITIVE.md`, not
  built. **C5 is blocked on that**, and should not be started before it.
- A redemption view: which recipients used theirs, which did not. That is the point of the campaign.

**Unresolved:** whether a targeted coupon is a different document type or the same one with a recipient
list. The coupon element renders a code; a targeted campaign renders a DIFFERENT code per visitor, which
a baked artifact cannot do — so the ticket would have to carry the code in its link, or the page resolves
it per visitor. Decide when C5 is picked up, not before.

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
