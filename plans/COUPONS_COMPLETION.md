# Coupons: make the module do what its schema already promises

**Status: C1–C4 shipped dev + prod 2026-09-22. C5 shipped dev 2026-09-23, not on prod.**
**Written 2026-09-22; status corrected 2026-09-23.**

**Open:** `applies_to_offer_ids` has no editor, per-recipient grant revocation, and reclaiming the
disposable coupons once delete-after-payment is tested. **A and B both shipped 2026-09-23** — A's recorded
blocker was a misread probe, and B's first rule is spend-threshold tiers.

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

### Option B, slice 1 — the redemption ledger: SHIPPED 2026-09-23 (dev pending)

**The bug it closed.** `coupon_is_usable` refused a coupon once `redemption_count >= max_redemptions`, and
nothing anywhere incremented that field. So the cap never fired: a fully-redeemed coupon stayed in the
Offers picker, kept rendering a live ticket, and reached the buyer as a **500 carrying Stripe's raw
wording** instead of the branded 410 that exists for exactly this. The `CouponUnavailable` comment claimed
to cover a coupon "disabled or used up"; the used-up half could not reach it.

**Why a ledger and not a counter.** Writing the counter would have fixed the symptom and entrenched the
architecture that caused it — a local mirror of a number Stripe owns. Under Option B the Stripe Coupon is
disposable and lives for one checkout, so `times_redeemed` can never enforce a tenant's cap. Ours has to be
the authoritative number, and a number you cannot audit has no business being authoritative. So:

```
coupon_redemption
  redemption_id  = redemption_<checkout_session_id>   ← the idempotency key IS the id
  coupon_id · code · grant_id?
  checkout_session_id · payment_intent_id · customer_email
  discount_amount · qualifying_amount · currency
  redeemed_at
```

- **A redemption is a successful ORDER, not an attempted checkout.** It is written from
  `checkout.session.completed`, so an abandoned checkout costs the tenant nothing off their cap. Stripe's
  own counter cannot express that distinction.
- **Replay-proof at the database.** `put_if_absent` is a conditional write on the derived id. Stripe
  retries until it gets a 2xx and can deliver an event twice unprompted, so the second copy has to collide
  rather than be trusted not to arrive.
- **Counters are atomic and come second.** `increment_counter` is a DynamoDB `ADD`; a read-modify-write is
  how a cap of 500 lets a 501st buyer through. They are bumped only when the ledger row was genuinely new,
  and a failed bump is a stale cache rather than a lost redemption — recoverable by counting the ledger,
  which is the point of keeping one.
- **`qualifying_amount` is recorded now and equals the subtotal today**, because product scoping is not
  built. Under Option B it becomes the output of rule evaluation; a ledger that only stored the total would
  need backfilling the day that lands.

**What this does NOT do.** It is the accounting half of Option B, not the evaluation half. Nothing yet
evaluates a tenant's rule against a cart, and no disposable Stripe Coupon is created — checkout still
hands Stripe the tenant's durable promotion code. Option B's evaluation engine remains undecided and
unbuilt; this slice is what makes it affordable, and is worth having under Option A regardless.

### Open — `applies_to_offer_ids` is enforced but cannot be authored (found 2026-09-23)

C4 made offer scoping real: a coupon naming offers is refused on any other offer, the same way an expired
one is. But the Coupons editor has **no offer picker** — `applies_to_offer_ids` appears in
`defaultCouponForm` as `[]` and is copied back out of an existing coupon, and nothing in the form ever sets
it. So the enforcement exists and the authoring does not.

Harmless today, and verified so: the only coupon in `jb-coupons-dev` carries `applies_to_offer_ids: []`,
which means "any offer". Every coupon ever created carries the same. But it is the mirror of the bug C4
fixed — that field was stored and read by nothing; now it is read and *written* by nothing — and the first
tenant who needs a coupon scoped to one offer cannot express it.

Worth deciding alongside the A/B fork, since option B subsumes it: under B the qualification rule is ours
to evaluate, and offer scope becomes one clause of a rule the tenant authors rather than a list bolted to
the document.

### Open — a single recipient's grant cannot be revoked (found 2026-09-23)

`status: "inactive"` on a grant is honoured at checkout (`resolve_targeted_grant` refuses it), and the
document validator accepts it — but no endpoint ever writes it. `/coupons/{id}/grants` is POST, GET and
OPTIONS only. A tenant who needs to cut off one recipient has to disable the whole campaign, which takes
every other recipient's code with it.

Whatever writes it must also call `set_promotion_code_active(promo_id, False)` on that grant's OWN
promotion code, or the two disagree in the dangerous direction: our record says revoked while the code still
works at Stripe.

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

So product-level scoping is deliberately **not built**. This has come up before and never reached a
conclusion, so the options are recorded concretely here rather than re-derived each time. **The author's
lean (2026-09-22) is toward expanding the coupon's scope** — option B or C — but it is not decided.

### The conceptual correction: a Coupon is not a Stripe Coupon (author, 2026-09-23)

The earlier framing of these options conflated two objects that do not have to be the same thing, and that
conflation is most of what stalled the decision twice.

```
                Junior Bay                            Stripe
          ┌────────────────────┐
          │   Tenant Coupon    │   durable, immutable, tenant-owned
          │   SUMMER20 · 20%   │
          │   offers A, B      │
          │   max 500          │
          └─────────┬──────────┘
                    │  evaluate against THIS cart
                    ▼
          ┌────────────────────┐
          │  Discount · $30    │   the computed result
          └─────────┬──────────┘
                    │  materialize
                    ▼                        ┌──────────────────────┐
                                             │ Stripe Coupon $30    │  disposable
                                             │ attached to session  │  execution artifact
                                             └──────────────────────┘
```

The Stripe Coupon is an **adapter between our pricing engine and Stripe's discount mechanism**, not the
tenant's coupon. So Option B is not "the tenant's coupon becomes a per-checkout Stripe coupon"; it is *the
tenant's coupon is a persistent pricing rule whose evaluated discount is materialized as a
checkout-specific Stripe discount.*

**C2 therefore does not have to change at all.** It can stand exactly as written — *a coupon is an
immutable, tenant-owned pricing rule; its scope, value, redemption limit and expiration are fixed when
created* — and B simply adds: *at checkout, we evaluate that rule against the cart and materialize the
result for Stripe.*

### The actual fork

Not "durable coupon vs per-checkout coupon". Both options keep a durable, tenant-owned coupon. The fork is
**who evaluates the rule**:

| | **A — Stripe evaluates** | **B — Junior Bay evaluates** |
|---|---|---|
| Durable tenant coupon | yes | yes |
| Tenant owns the rule | yes | yes |
| Scope stored on the tenant coupon | yes | yes |
| **Evaluation performed by** | **Stripe** | **Junior Bay** |
| Qualification rules possible | only what Stripe supports | anything we implement |
| Stripe Coupon object | durable, one per tenant coupon | disposable, one per checkout |
| Redemption accounting | mostly Stripe's | ours |
| Buyer sees a discount line | yes | yes (B1) / no (B2) |
| Changing the rule needs a new coupon | yes | yes |

### Option A — Stripe is the evaluation engine

Set `applies_to[products][]` on the Coupon at creation. Stripe then discounts only the matching line items.

**Correction, 2026-09-23 — A cannot be driven from `applies_to_offer_ids`.** The earlier text said to
translate offer ids → product ids, and that is a no-op:

- if the checkout's offer is NOT in `applies_to_offer_ids`, `coupon_covers_offer` refuses the code outright
  and Stripe never sees the coupon;
- if it IS, then scoping Stripe to that offer's products covers every line in the cart — the same result as
  no scope at all.

A checkout carries exactly one offer (a cart stores a single `offer_id`, and `cart_checkout.py` has no
coupon support at all), so an offer-level Stripe scope is always either unreachable or a no-op. This is the
document's own "eligibility is not the same question as product scoping" distinction reasserting itself:
**A needs its own product-level field.** Hence `applies_to_product_ids`, which maps 1:1 onto Stripe's
`applies_to.products` and expresses the bundle case the feature exists for — a cart where only some
products qualify.

- **Mechanics:** one extra field at creation. Nothing at checkout. Products must already be synced
  (`product_sync.py` sets `stripe_product_id`), so a never-synced product cannot be named.
- **The 2026-09-22 "blocker" was WRONG, and the correction matters (re-probed 2026-09-23).** That probe
  saw `applies_to: null` on create and retrieve and concluded Stripe was silently ignoring the field. It
  never checked whether the DISCOUNT was scoped. It is:

  | coupon scope (50% off) | discount on a cart of A=$100 + B=$50 |
  |---|---|
  | product A only | **5000** — half of A, not of the cart |
  | product B only | **2500** — half of B |
  | A and B | 7500 |
  | unscoped | 7500 |

  `applies_to.products` **works**. Stripe simply does not echo it back on the Coupon object — the response
  reads `null` whether or not a scope was set. So the field is real and the *API response is the thing that
  lies*. Never conclude a Stripe field is ignored from its echo alone; test the behaviour it is supposed to
  produce. That mistake cost this decision a full extra round.
- **Cost if it works:** cheapest by a wide margin, and the buyer sees a normal Stripe discount line.
- **Ceiling:** every future rule has to be expressible in Stripe's vocabulary. "Cheapest item free",
  tiered thresholds, category rules and bundle logic are not.

### Option A — SHIPPED 2026-09-23 (dev pending)

Adopted first, because A is a special case of B — "the qualifying set is a fixed product list" — so it buys
real product scoping cheaply without foreclosing B. The tenant's coupon document is unchanged under either.

- **New field `applies_to_product_ids`** on the coupon, distinct from `applies_to_offer_ids`. Our product
  ids; the server translates them to `stripe_product_id` and sends `applies_to[products][]` at creation.
  Absent/empty means the whole cart, which is what every coupon created before today carries — so nothing
  existing changes behaviour.
- **An unsynced product REFUSES the coupon** (`coupon_scope_unresolved`, 400) rather than degrading.
  Dropping one would send a shorter scope and discount the wrong set; dropping all of them would send no
  scope and discount the entire cart. Both are silent over-discounts on a money path, and nothing
  downstream could catch either — Stripe does not echo `applies_to` back. Nothing is created at Stripe when
  the scope will not resolve.
- **Frozen like the rest.** Changing the scope is refused with the same 409 as changing the value; Stripe
  freezes `applies_to` on the Coupon anyway, and a discount promised over a set of products is the same
  kind of promise as its percentage.
- **Verified end to end through our own code, live test mode:** `create_coupon_in_stripe` with a scope,
  then a session carrying a $100 qualifying + $50 non-qualifying cart, the discount applied **by promotion
  code** the way checkout does it. Discount came back **5000**, not 7500. The tests assert the payload we
  SEND, because there is nothing truthful to assert in the response.
- **Editor:** a product checklist in the Coupons form, loaded on demand (the products index is the biggest
  payload the dashboard fetches). Products with no `stripe_product_id` are shown disabled with the reason,
  so a tenant meets the limitation before the server refuses rather than after.

**Not covered by A:** anything that is not a fixed product list — cheapest-item-free, tiered thresholds,
category rules, or any rule depending on cart composition. That is B, below, and its accounting half (the
redemption ledger) is already built.

### Option B — Junior Bay is the evaluation engine

At checkout, sum the qualifying lines, apply the tenant's rule, and get a number. Two ways to hand that
number to Stripe.

#### B1 — materialize it as a disposable Stripe Coupon

**Verified against the live API, test mode, 2026-09-23** (`Stripe-Version: 2024-06-20`):

- **There is no inline discount.** `discounts[0][amount_off]` → *"Received unknown parameters: amount_off,
  currency"*. `discounts[0][coupon_data]` → *"Received unknown parameter... Did you mean coupon?"*. A
  Checkout Session's `discounts` takes **only** a `coupon` or `promotion_code` id. So the disposable Coupon
  is not a design preference — it is the only way to put a computed amount in front of a buyer as a
  discount.
- **It works exactly as hoped.** A `$30 amount_off / duration: once` Coupon attached to a $100 session
  produced `amount_total: 7000` and `total_details.amount_discount: 3000`. Native Stripe presentation.
- **The disposable object can be deleted immediately.** `DELETE /v1/coupons/{id}` right after session
  creation returned `deleted: true`, and the still-open session kept `amount_total: 7000`,
  `amount_discount: 2500` on retrieve. So the account does not accumulate one dead Coupon per checkout.
- **And the discount stays readable.** Expanding `total_details.breakdown` after deletion returns the
  discount with the **whole coupon object embedded inline** (`di_estimated_…` carrying `amount_off`,
  `duration`, `currency`). `line_items` likewise expose per-line `discounts` with amounts. Receipts, order
  records and per-line attribution all survive the deletion.

So B1's two obvious objections — Stripe-object garbage and losing the discount on the receipt — are both
answered empirically rather than assumed.

#### B2 — discount the line items directly

Construct the session with reduced `price_data.unit_amount` on the qualifying lines. No Stripe Coupon at
all. This is where B overlaps with C, and it inherits C's cost: Stripe does not know the reduction was a
coupon, so the buyer sees a lower price with no "you saved $X" line and no coupon on the receipt.

**B1 exists precisely to preserve that presentation.** For a campaign whose entire purpose was to send
somebody a coupon, the visible discount is the point, so B1 is the default and B2 is the fallback for cases
where the discount need not read as a discount.

### Option B, slice 2 — the evaluation engine: SHIPPED 2026-09-23 (dev pending)

B1 as described above, with **spend-threshold tiers** as the first rule Stripe cannot express. Everything
else a coupon does is still Stripe's to evaluate, and stays that way — B is for what A cannot say.

```
tenant Coupon    SPEND20 · 20% over $100 · 30% over $250     durable, immutable, ours
      |
      |  evaluate against THIS cart
      v
Discount         $82.50                                       computed
      |
      v
Stripe Coupon    amount_off 8250 · once · max_redemptions 1   disposable, one checkout
```

- **`discount.type: "tiered"`** with a `tiers[]` ladder. The BEST tier the cart reaches wins, not the first
  listed — the tenant wrote a ladder and a ladder is climbed. Order in the document is irrelevant.
- **A tiered coupon creates NOTHING at Stripe on save**, and stores no Stripe ids at all rather than
  placeholder ones: an id naming nothing is how `sync.status` became a fiction the first time. It is also
  the one coupon type that does not require a connected Stripe account to create.
- **`applies_to_product_ids` narrows what counts toward the threshold**, so "spend $100 on coffee" is
  expressible, not just "spend $100".
- **A cart below every tier is NOT a refusal.** The tenant said "spend $100 to get 20%"; a buyer with $40
  has not met terms they can read, and full price is exactly what the coupon promised. That is a different
  situation from a withdrawn or used-up coupon, where the visitor arrived on a ticket that no longer means
  anything — those still raise `CouponUnavailable`. A qualifying buyer whose discount cannot be
  materialized also raises, because charging them full price WOULD be the silent failure.
- **The disposable Coupon is deliberately NOT deleted.** Deleting immediately was verified safe for an
  *open* session, but "delete, then the buyer pays" was never tested, and inventing that path on a money
  route is how a receipt loses its discount. Instead it bounds itself: `max_redemptions: 1` means it can
  never be reused, and `redeem_by` (7 days, against a 24-hour session) makes it inert. Sweeping old ones is
  a chore; a discount vanishing from a paid order is an incident. **Open:** test the delete-after-payment
  path deliberately, then reclaim the tidiness.
- **Immutable like every other coupon.** Moving a threshold is refused with the same 409 as changing a
  percentage — and here the check in `coupon_edit_conflict` is the ONLY thing enforcing it, because there
  is no Stripe object freezing the ladder on our behalf.
- **Verified live, through this code:** a $150 cart evaluated to 3000 and Stripe charged $120.00; a $275
  cart evaluated to 8250 and Stripe charged $192.50; a $40 cart reached no tier and created no Stripe
  object at all. Our arithmetic and Stripe's agree to the cent.

**What a tiered coupon cannot do:** be issued as targeted personal codes (a grant is a Promotion Code
pointing at a durable Coupon, and there is neither), and be typed into Stripe's own promotion-code field —
the code is ours, not Stripe's, so it must arrive through the page. Both are refused explicitly rather than
failing obscurely.

**Also shipped alongside:** a cart can take a coupon at all. `cart_checkout.py` called
`build_checkout_payload` without a `coupon_code`, so every cart paid full price however the buyer arrived
(found 2026-09-23) — and a cart is exactly where a spend ladder matters.

### Option C — discount the line items directly, as the whole feature

B2, adopted as the permanent answer rather than as a fallback: no coupon object anywhere, ever.

- **Mechanics:** simplest to implement; exact to the cent.
- **Cost:** the buyer never sees a discount, Stripe records no redemption, and `allow_promotion_codes`
  cannot coexist with it meaningfully.
- **Recommended only if** the discount never needs to be visible as a discount.

### The one thing B genuinely costs: redemption accounting becomes ours

This is the real difference, and it is not a footnote. Under B the per-checkout Stripe Coupons are each
redeemed at most once and then deleted, so Stripe's `times_redeemed` cannot enforce the tenant's
`max_redemptions: 500`. We have to count.

That needs a durable redemption record rather than a counter — something like:

```
coupon_id · redemption_id · checkout_session_id · payment_intent_id
discount_amount · qualifying_amount · redeemed_at
```

and an atomic increment against the cap.

**Two things make this less of a cost than it looks.** First, we already keep a commerce ledger, so a
coupon redemption becomes another durable business event rather than something delegated and then mirrored.
Second, it lets us define redemption honestly: **a redemption occurs when the associated order reaches a
successful state**, not when a checkout is attempted. Stripe's counter cannot express that distinction;
ours can.

**And we are already paying this cost while getting none of the benefit.** `coupon.redemption_count` is
read by `coupon_is_usable` and written by nothing (see the open item above) — precisely the failure mode of
leaving evaluation with Stripe while keeping a local copy of the count. Under B that counter stops being a
mirror of Stripe's number and becomes the authoritative one, which is the only version that can actually be
kept correct.

### What to decide

Not "object or rule" — the correction above dissolves that question, since the tenant's coupon is a durable
owned object under both. The decision is **where evaluation lives**:

- **A** if "which products qualify" is the whole of the requirement. Its blocker is gone (re-probed
  2026-09-23) and it is far the cheapest: one field at coupon creation, nothing at checkout. Its ceiling is
  that every rule must be expressible as a product list — no "cheapest item free", no tiered thresholds, no
  category rules, and no rule that depends on cart composition.
- **B (B1)** if the rules will outgrow that. All four mechanical objections to it are now tested rather
  than assumed, and its main cost — the redemption ledger — is already built and worth having under A too.

**They are not mutually exclusive, and that is probably the answer.** A is a special case of B: "the
qualifying set is a fixed product list". Adopting A now buys real product scoping cheaply and does not
foreclose B, because the tenant's coupon document is unchanged either way and the ledger already exists.
The day a rule arrives that a product list cannot express, B takes over evaluation for that rule and the
stored coupons do not migrate.

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
- A personalised code in each email. This was read as a block on campaign tooling
  (`plans/ATTENTION_PRIMITIVE.md`), and it is not: **the tenant already has email software.** The platform
  mints the codes and hands back a CSV; Mailchimp, or whatever they pay for, does the sending
  (decision, 2026-09-22). A first-party sending rail can come later and this export stays useful — some
  tenants will always prefer their own list.
- A redemption view: which recipients used theirs, which did not. That is the point of the campaign.

**Resolved (2026-09-22):** a grant is its **own document type** in its **own table**, and the code travels
in the **link**.

- `coupon_grant` documents live in `CouponGrantsTable`, keyed so that `grant_id` IS the code. Checkout
  resolves a personal code with one `GetItem` instead of scanning a tenant's coupons — which matters
  because every checkout of every page pays for that lookup, forever. A recipient list hung off the coupon
  document would have put the whole audience in the path of every unrelated sale.
- A published page is ONE artifact for everybody, so it cannot bake a per-visitor code. The recipient's
  link carries it (`?coupon=…`), and the page swaps it into the ticket — but only when it carries the
  campaign's own prefix, so a stray parameter on somebody else's link changes nothing. The server decides
  whether it is honoured either way.
- The grant lives or dies with its campaign: a coupon turned off takes every code issued from it with it,
  and the recipient is told the offer ended rather than charged full price.
- The session must name the grant's customer (`customer=cus_…`), because the promotion code is scoped to
  them at Stripe. That is also why `customer_creation` is skipped when a grant is applied — Stripe refuses
  the two together.

**Shipped in C5:** `domain/coupon_grants.py` (codes, recipients, the document), `stripe_coupons.find_or_create_customer`
+ `create_targeted_promotion_code`, `POST/GET /coupons/{coupon_id}/grants` (batched, because API Gateway
hangs up at 29s and each recipient costs Stripe round-trips), CSV export, `checkout.resolve_targeted_grant`,
the `?coupon=` swap in the page script, and the **Send to customers** modal on each coupon card.

## Phases

- **C1 — create in Stripe on save.** The server owns the Stripe call (not the browser, which must never hold
  a secret key): `POST /coupons` creates both objects, stores the real ids, persists only on success.
  Idempotency-Key. Real errors surfaced. `sync.status` becomes true for the first time.
- **C2 — lifecycle.** Disable deactivates the promotion code; value/code edits refused with the reason;
  editor states immutability up front.
- **C3 — unblock the element.** Checkout resolves the real id and pre-applies it; when it cannot, it refuses
  with the message above rather than charging full price. `plans/COUPON_ELEMENT.md` finishes here.
- **C4 — the three unenforceable fields.** Decide each: enforce, or remove from the editor.
- **C5 — targeted coupons.** One personal code per named customer, exported as CSV for the tenant's own
  email software. Shipped 2026-09-22; see the resolution above.

Redemptions are counted on the grant itself: the checkout session carries `metadata[coupon_code]`, and
`checkout.session.completed` marks that recipient's code used. Only GRANT codes are counted — a shared
code's redemptions are Stripe's own number, and a second lagging copy of it here would be worse than none.
The count is written last and best-effort, because a campaign statistic must never cost the tenant an
order.

## Risks

- **This is a money path.** A coupon that applies when it should not costs the tenant real margin; one that
  fails when it should work costs them a sale they already paid to advertise.
- **Partial creation.** The Coupon can succeed and the Promotion Code fail. Persist nothing in that case, and
  let the orphaned Stripe coupon be — it is inert without a code pointing at it, and deleting it on a failure
  path invites deleting the wrong one.
- **The element is committed but not deployed**, and its checkout path would fail a session today. Either
  C3 lands first, or the element's pre-apply is made fail-safe before anything ships.
