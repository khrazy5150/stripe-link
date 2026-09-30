# Shipping Charges — the primitive that was never built

**Status: planned, nothing built · Written 2026-09-30.**

## Why this exists

The author, 2026-09-30: *"I was so focused on 'free shipping' that there is no primitive for shipping
charges."* That is exactly the shape of it.

**Checkout collects a shipping address and charges nothing for shipping.** The entire shipping surface at
checkout is five lines in `handlers/checkout.py:763-765` — `shipping_address_collection[allowed_countries]`,
and that is all. No `shipping_options`, no rate, no line, no amount.

`ShippingConfig.rate_options` already declares `markup_amount` and `free_shipping_threshold`, and
`domain/rate_policy.py` says so out loud in its own docstring: they *"belong to charging the BUYER
(plans/SHIPPING_PROVIDERS.md §PE), which is a different question with a different latency budget, and they
are untouched here."* Two schema fields nothing reads, and a module politely declining to be the place.

So the gap is not a missing Stripe call. **There is no representation of a shipping charge anywhere** — not
on the offer, not on the order, not in the fee maths.

## What already exists (do not rebuild)

- **`ShippingConfig`** — `rate_options`, `boxes`, `default_parcel`, `ship_from_address`, `return_address`.
- **`domain/rate_policy.py`** — which rate to BUY from the carrier. The tenant's cost, not the buyer's price.
- **`plans/SHIPPING_PROVIDERS.md`** — already frames the three options and, importantly, the trap:

  > **`free_shipping_threshold` vs baked-in shipping — they double-count.** If shipping is already in the
  > price, the threshold is either meaningless or discounts something the buyer has already paid for.

- **`plans/SMART_PRICING.md`** — models outbound shipping as a `fixed` cost line, i.e. shipping BAKED INTO
  the price. That is the other half of this and the two must not be designed apart.

## The primitive

A shipping charge is a **priced line on the order**, not a checkout detail. It needs to exist before the
Stripe wiring, or the amount will live only inside a Stripe session and be unreconcilable afterwards.

Three questions the primitive must answer, and today none of them has a home:

1. **Is shipping charged separately, or baked into the price?** Mutually exclusive per offer, and the
   double-counting note above is what happens when nobody decides. This is a FIELD, not an inference.
2. **What is the amount?** Flat per order, flat per item, by weight band, or free above a threshold. All are
   ordinary retail policies and none is expressible today.
3. **Where does it land on the order?** Neither field exists. Without them: shipping margin cannot be
   computed, the fee calculation has no stated base, tax cannot be reasoned about in jurisdictions that tax
   shipping, and a refund cannot know whether shipping comes back.

   **Correcting an earlier overclaim in this plan (2026-09-30):** it said the tenant's P&L is wrong because
   "shipping revenue is invisible". It is not wrong. `domain/ledger.py` already has `shipping_cost` and `cogs`
   as profit components, and `gross` is `session.amount_total` — Stripe's whole total, buyer-paid shipping
   included. So total profit already comes out right. What is missing is the ability to ISOLATE shipping
   revenue: `shipping_amount` sits inside `gross` undifferentiated, so shipping margin cannot be separated
   from product margin. An incomplete breakdown, not a wrong bottom line.

**That third one is why this is a primitive and not a feature.** Every downstream system already in the repo
— ledger, fees, refunds, tax fields — has a shipping-shaped hole in it.

### TWO numbers, not one (author, 2026-09-30)

    order.shipping_amount    what the BUYER paid
    order.shipping_cost      what the CARRIER charged the tenant

They are fundamentally different, and collapsing them loses the only number that matters commercially:

    Product        $50      gross merchandise   $50
    Buyer shipping  $8      shipping revenue     $8
    Carrier cost    $6      shipping cost        $6
                            shipping margin      $2   <- invisible with one field

Under `baked` the same two fields still say something true: `shipping_amount = 0`, `shipping_cost = $6`, and
the margin is wherever Smart Pricing put it.

**A second reason they cannot be one field: they are known at different TIMES, by different actors.**
`shipping_amount` is settled at checkout, by us. `shipping_cost` is not known until a label is bought, which
may be days later and may never happen. One field would have to be written twice with different meanings —
and this repo already has the pattern for exactly this shape: estimated at the time, trued up against the
authority later, the way `fees.py` reconciles against Stripe balance transactions.

## Sequencing, and the one hard question

`plans/SHIPPING_PROVIDERS.md` option **B (flat rates at checkout)** is the natural implementation: Stripe
hosted Checkout takes up to 5 `shipping_options`, the buyer pays, no live carrier call, no change to the
buyer's flow. Option C (live rates) requires leaving hosted Checkout and is out of scope.

But B cannot be wired until the primitive exists, and the primitive forces a decision the repo has been
avoiding:

> **Does the platform's application fee apply to the shipping amount?**

Charging a percentage on postage is a real business decision with a defensible answer either way, and it
must be made once, in `domain/fees.py`, rather than emerging from whichever code path happens to run.
`fee_class_for` has no shipping class today.

**It must be an explicit JuniorBay rule, never inferred from Stripe's resulting transaction total**
(author, 2026-09-30). Stripe will happily report one number; which parts of it we were entitled to a
percentage of is our decision, and a rule that exists only as "whatever the total happened to be" cannot be
audited, explained to a tenant, or changed without archaeology.

### ✅ DECIDED 2026-09-30: shipping is EXCLUDED

    fee_base = merchandise_amount - discounts

Shipped in `domain/fees.py` as `FEE_APPLIES_TO_SHIPPING = False` plus `fee_base()`, with 11 tests. Postage is
a cost the tenant passes through, often at break-even; taking a percentage of it is hard to defend ("we charge
you 2% of the stamp") and would make the platform's cut depend on how heavy the goods are rather than on the
value we added. *"We never charge you on shipping"* is a promise worth being able to make. One constant, so
reversing it is a one-line change that fails a loud test.

`shipping_cost` never appears, under any setting. The platform fee is a share of what the BUYER paid; what the
carrier charged the tenant is the tenant's own cost and none of the platform's business.

### The trap this rule caught, before Checkout was wired

**Stripe has no `application_fee_amount` on a subscription — only `application_fee_percent`, applied to each
invoice's WHOLE total.** `handlers/checkout.py` computed `platform_fee / subtotal`, where `subtotal` is
merchandise only. Add a shipping line to a subscription and Stripe would have applied that percent to
merchandise + shipping:

    merchandise $50.00   shipping $8.00   fee base $50.00   fee owed $1.00
    naive percent = 1.00 / 50.00 = 2.00%
    Stripe charges 2.00% of $58.00 = $1.16      <- 16% more than the rule allows

Charged on every renewal, to every subscription with shipping, with nothing in the code contradicting itself —
the fee module would say shipping is exempt while the checkout payload quietly taxed it. Fixed by dividing by
the CHARGED total (`domain/fees.application_fee_percent`), which keeps the absolute fee equal to the
merchandise-only figure whatever shipping does.

This is exactly what the author meant by resolving the fee interaction *before* wiring Checkout. The bug was
unreachable today — no shipping amount exists yet — and would have shipped the moment one did.

## `free` is not a third pricing model (author's question, 2026-09-30)

> *"`free` needs a little more thought because 'free to the buyer' doesn't mean 'free to the merchant.'"*

Correct, and following it through says the three-mode list above is subtly wrong. Look at what the buyer
sees:

| mode | buyer sees | price recovers the cost? |
|---|---|---|
| `charged` | a shipping line | no — the buyer paid it directly |
| `baked` | no line ("free shipping") | yes — Smart Pricing put it in the price |
| `free` | no line ("free shipping") | **no — the tenant eats it** |

`baked` and `free` are IDENTICAL at checkout and differ only in whether the price was computed to cover the
cost. That is not a checkout fact, it is a Smart Pricing fact — so encoding it in the checkout mode puts one
decision in two places, which is the same failure that produced this plan. **Two axes instead:**

    offer.shipping.mode          charged | free      <- what the BUYER experiences
    Smart Pricing cost profile   has an outbound shipping cost line, or not

    free    + cost line      = baked     (recovered in the price)
    free    + no cost line   = absorbed  (a loss leader, deliberately)
    charged + no cost line   = the buyer pays it
    charged + cost line      = DOUBLE-COUNTED  <- forbidden

### Why `charged` is structurally necessary, not just a tenant preference (author, 2026-09-30)

> *"You need two (charged / free) because shipping could vary (ground, 2-day shipping, overnight) and those
> costs can't be baked in."*

This is a better argument than the one above and it settles the mode count on its own. **Shipping speed is a
BUYER's choice**, and a price fixed before the buyer chooses cannot contain a cost that depends on what they
pick. `baked` is not merely redundant with `free` — for a variable service level it is impossible.

Four consequences, and they reshape the rest of this plan:

1. **`charged` shipping is a LIST of priced options, not an amount.** Ground / 2-day / overnight is the
   ordinary case. Stripe hosted Checkout accepts up to **5** `shipping_options`, which fits with room.

2. **`order.shipping_amount` is not something we compute at session creation.** We OFFER options; the buyer
   picks one; Stripe reports the choice on the completed session (`shipping_cost.amount_total`). So it is
   captured in `handlers/stripe_webhook` alongside `shipping_address`, which is already read from the session
   there (`stripe_webhook.py:2108`) — not calculated in `handlers/checkout`. Any design that has checkout
   deciding the amount is wrong for the variable case.

3. **Reuse the service vocabulary that already exists.** `domain/rate_policy.py` already models service levels
   as `{carrier, service_token, label}` and has `common_services()`; `ShippingConfig.rate_options` already has
   `default_service_level`. The buyer-facing option should carry the same `service_token`, so the option a
   buyer chose can later be tied to the rate the tenant actually buys. Inventing "ground"/"overnight" strings
   here would be a second vocabulary for the same thing.

4. **`free` and `charged` can coexist on one offer, and the invariant must handle it.** "Free ground, paid
   overnight" is a normal offer: the cheapest option is £0 and the upgrades are priced. So the invariant does
   not apply to the mode as a whole — it applies to the **baseline (cheapest) option**:

   > A tenant may carry the BASELINE option's cost in their Smart Pricing cost profile when that option is
   > free to the buyer. The priced upgrades are buyer-paid and must NEVER appear as a cost line — that is the
   > double-count. `mode` is then a summary of the options (all zero ⇒ `free`), not an independent field to
   > keep in step.

**The invariant, stated once** (resolving the SMART_PRICING interaction that was "Open" below):

> For any offer, the BASELINE (cheapest) shipping option may be carried in the Smart Pricing cost profile
> **only when it is free to the buyer**. Every option the buyer pays for is buyer-paid revenue and must NEVER
> appear as a cost line. Never both for the same option — that is the double-count.
>
> So: a £0 baseline ⇒ Smart Pricing MAY include that cost (and if it does not, the tenant is knowingly
> absorbing it). A priced baseline ⇒ Smart Pricing MUST NOT include outbound shipping at all.

This is a validator, not a comment — the forbidden row pays the tenant twice for the same postage and no
tenant would notice from the numbers. `shipping_cost` stays truthful in every row: the carrier charges what
it charges regardless of who ends up paying for it. The `absorbed` row is a legitimate choice and the UI
should say so out loud ("you are paying for shipping on this offer") rather than letting a tenant discover
their margin at tax time.

## How Stripe treats shipping, and how that differs from tax

Asked by the author, 2026-09-30: *does Stripe allow a separate shipping charge like they do taxes?* Yes — a
separate line, separately reported, independently reconcilable. But the two are handled in fundamentally
different ways, and the difference is the whole reason `domain/shipping_charges.py` has to exist:

| | Tax | Shipping |
| --- | --- | --- |
| Who decides the amount | **Stripe.** `automatic_tax[enabled]=true` and Stripe Tax resolves jurisdiction, nexus and product tax codes | **We do.** Stripe only presents the options we supply |
| Reported on the session as | `total_details.amount_tax` | `shipping_cost.amount_total` and `total_details.amount_shipping` |
| Does the buyer choose | No | **Yes** — up to 5 `shipping_options` |
| Recalculates as the buyer types their address | Yes | **No** |
| Can the other one apply to it | n/a | Yes — `tax_behavior` on the rate, reported as `shipping_cost.amount_tax` |

**Stripe computes tax. Stripe does not compute shipping.** If it did, this module would be a thin wrapper
around an API call. It is a real calculator because the amount is ours to decide.

### The constraint that follows, and it is a hard one

**Hosted Checkout cannot call back to us mid-session.** Stripe recalculates tax as the buyer edits their
address; it will never ask us for a shipping rate for the address they just typed. So on hosted Checkout,
shipping options must be decided BEFORE the session opens — flat or table rates, which is what `options_for`
returns.

That is a real limit on `plans/SHIPPING_PROVIDERS.md`: a live carrier quote for *this* buyer's address is not
possible during hosted checkout. A tenant can buy a real rate AFTER the sale (which is what `rate_policy.py`
is for), but quoting one DURING it needs Payment Element or a custom flow, which is a much larger change than
this plan. Flat options are not a shortcut here — they are what the chosen checkout surface supports.

### Two things to verify before step 6 (Checkout)

- **Stripe Tax is not enabled in this app at all** — no `automatic_tax` anywhere in `src/`. So tax is not
  currently collected on anything, and `shipping_cost.amount_tax` will be zero until that changes. Worth
  knowing before claiming shipping tax is handled.
- **Recurring shipping in `mode=subscription` is UNVERIFIED.** Checkout accepts `shipping_options` in
  subscription mode, but whether the chosen shipping recurs on every invoice or applies only to the first has
  not been checked against Stripe's current behaviour. It matters: a subscription box that ships monthly needs
  shipping on each invoice, and one that ships once does not. Do not wire subscription shipping on an
  assumption — the fee-percent trap above came from exactly that kind of guess.

## Stripe's Shipping Rate, and where the boundary sits

The author, 2026-09-30: *"I wouldn't use Stripe's Shipping Rate as your JuniorBay shipping primitive... JuniorBay
remains authoritative, while Stripe becomes the payment/Checkout representation."* Agreed, and that is how
`domain/shipping_charges.py` is built:

    JuniorBay (authoritative)              Stripe (payment representation)
    ─────────────────────────              ──────────────────────────────
    offer.shipping.options[]      ──►      shipping_options[]
      rule: flat | per_item                  shipping_rate_data (fixed amount)
      free_above_amount                      tax_code / tax_behavior
    resolve_amount(cart)          ──►      the buyer picks one
    order.shipping_amount         ◄──      shipping_cost.amount_total
    order.shipping_cost                    (never sent to Stripe — our cost, not theirs)

**Why the rule cannot live in Stripe: a Shipping Rate is a FIXED amount.** It cannot express "$2 a unit", so
"$7.95 then $2 each after" has to be resolved to "$11.95" before the session is created. That is
`resolve_amount`, and it is the reason this module is a calculator rather than a wrapper.

### This corrected something already shipped

The first version of `options[]` stored a flat `amount` per option, which covers `flat` and the threshold and
**cannot express per-item or weight-based pricing at all** — exactly the rules the author listed. Fixed the
same day: an option now carries `kind` (`flat` | `per_item`) plus an optional `first_item_amount`, and the rule
is resolved against the cart. Two consequences worth keeping:

- **Rules are resolved BEFORE sorting.** With per-item pricing the cheapest option depends on the cart, so
  ordering on the stored amount puts the options in the wrong order for a basket of six.
- **`mode` follows the RESOLVED amount**, not the stored one. A per-item option priced at 0 is free however
  many units are in the cart.

Weight bands are the next rule and are deliberately not declared yet — the schema does not offer a `kind` the
calculator cannot honour.

### Tax: classify the line, never guess who bears it

Stripe's shipping tax code `txcd_92010001` is now always sent, because classifying the line is a **fact** about
what it is — without it shipping reaches Stripe Tax as an unclassified amount rather than as shipping.

`tax_behavior` (inclusive / exclusive) is **never defaulted**. Whether the buyer's tax is added on top of the
postage or taken out of it is a tenant decision with a real cash consequence, and Stripe's own default is
`unspecified`. A validator refuses an unknown value at save time.

Both are carried in readiness rather than in use: **Stripe Tax is not enabled anywhere in this app**.

### Tax is PER-TENANT, which changes what this plan may assume

The author, 2026-09-30: *"each tenant must enable Stripe Tax on their own."* Correct, and it has consequences
this plan has to respect rather than design around.

Stripe Tax lives on the **connected account**: the tenant registers their jurisdictions and turns it on in
their own Stripe Dashboard. The platform cannot enable it for them and cannot assume it. So:

1. **`automatic_tax[enabled]=true` must NEVER be sent unconditionally.** For a tenant who has not set Stripe
   Tax up, that flag does not produce a tax-free session — it risks producing **no session at all**, which is
   a lost sale at the pay button. Every tenant is in that state today. The rule for whoever wires this:

   > Send `automatic_tax` only on evidence that THIS tenant's account has tax active. On no evidence, omit it
   > and collect no tax. Fail open — an uncollected tax is recoverable and the tenant can be told; a refused
   > checkout is revenue that never arrives.

   Same shape as the `application_fee_percent` trap earlier in this plan: a platform-level assumption about a
   per-tenant setting, invisible until it fires.

2. **We need to KNOW the status, per tenant.** `domain/connect_sync.py` captures `charges_enabled` and
   `details_submitted` and nothing about tax. Stripe's Tax Settings API on the connected account is the
   likely source (a status of active/pending) — **verify the exact shape before relying on it**, the same
   caution as the subscription-shipping question above. Cache it the way `fees.py` caches billing config; a
   status read on every checkout is a round trip in the buyer's path.

3. **`tax_behavior` is really a TENANT-level decision, not a per-option one.** Inclusive-vs-exclusive is one
   accounting stance, not something a merchant varies between Ground and Overnight. Stripe requires it per
   rate, so the per-option field stays as the wire format — but the tenant should set it once. The storage and
   the UI belong with the tax work, not here: this plan will not invent a settings field it has no screen for.

**So shipping does not "handle tax", and this plan should stop implying it.** It classifies the line correctly
and carries the tenant's stance through. Whether any tax is computed is entirely the tenant's Stripe Tax
setup, and making that work is **its own plan** — there is no `plans/TAX*.md` yet. What shipping needs from it
is recorded in TODO.

### Inline rate, not a persisted Shipping Rate object

Both are the same thing to Stripe and both accept `tax_code` and `tax_behavior`, so the tax participation is
identical. But a resolved amount depends on the cart, and creating a durable Shipping Rate per cart would
litter the tenant's Stripe account with thousands of near-identical objects nobody can read. A persisted rate
is the right shape for a genuinely fixed price a tenant wants to manage in the Stripe Dashboard; it is the
wrong shape for a computed one. Revisit if tenants ask to manage rates in Stripe directly.

## Phases

The author's order, 2026-09-30, with Checkout deliberately LAST:

1. **`offer.shipping`** — ✅ **SHIPPED 2026-09-30**. `options[]` (max 5, Stripe's cap), each with a label, a
   buyer-paid `amount`, and the `service_token` vocabulary `domain/rate_policy.py` already uses. `mode` is
   accepted but DERIVED; a stored mode contradicting its own options is refused, because a stored summary of
   other fields is a second place for the same fact to be wrong.
2. **`domain/shipping_charges.py`** — ✅ **SHIPPED 2026-09-30** (35 tests). Pure: `options_for` (cheapest
   first, threshold applied to the baseline only, capped at 5), `mode_for`, `baseline_option`,
   `smart_pricing_conflict`, `stripe_shipping_options`. Weight bands when the box catalogue justifies them.
3. **`order.shipping_amount`**, and `order.shipping_cost` alongside it — the author's *"(+ eventually
   `shipping_cost`)"*. Both fields land now because adding the second one later means a migration and a
   period where shipping margin cannot be computed for past orders; only its SOURCE is deferred.
4. ✅ **The fee-base rule** (`fees.py`, 2026-09-30) and ✅ **the Smart Pricing invariant**
   (`shipping_charges.smart_pricing_conflict`, 2026-09-30). Still to wire: call the invariant from the offer
   save path once a cost profile exists to check against — SMART_PRICING is not built, so there is nothing to
   conflict with yet and the check has no caller.
   *"Those two decisions determine the economics of the entire shipping primitive, so they're much cheaper to
   settle now than after Stripe, ledger, refunds, and pricing have all been built around an assumption."*
5. **Fee, tax, refund and ledger** read `shipping_amount` rather than assuming zero; P&L and analytics read
   both fields and get shipping margin (`shipping_amount - shipping_cost`) for free.
6. **Stripe Checkout `shipping_options`** — last, on purpose. Checkout is where a wrong rule stops being a
   design question and becomes a charge to a real buyer, and it is the one consumer that cannot be corrected
   after the fact: a session that quoted the wrong shipping has already told someone a price.

`shipping_cost` has no source yet — no carrier integration exists, so it starts nullable and tenant-entered,
and is trued up when SHIPPING_PROVIDERS lands and a real label has a real price. Nullable is honest here;
zero is not, because zero is a claim that postage was free.

## Open

- **Does the buyer ever see a shipping line under `free`?** No — that is what the mode means. SHIPPING_PROVIDERS
  §8 asked this of `baked` and the two-axis model answers it: the buyer sees no line, and whether the price
  recovered the cost is invisible to them and none of their business.
- **International.** Checkout allows US and CA today, hardcoded. A shipping charge that ignores destination
  is wrong the moment a second country is allowed.

## Inbound shipping is a different number

`plans/INVENTORY_COST_BASIS.md` owns the cost of ACQUIRING inventory (`lot.inbound_shipping`); this plan owns
fulfilling one order (`order.shipping_cost`, and `order.shipping_amount` for what the buyer paid). Three
numbers, three names, none of them just "shipping". Inbound is never charged to a buyer, so the double-count
invariant above applies to the outbound pair only.

## The principle both plans exist to serve

> *"Customer-facing commercial promises should never be implicit."* — the author, 2026-09-30

A 30-day refund window nobody configured and a "free shipping" nobody priced are the same bug wearing two
costumes: a promise made to a buyer by a default that no one chose and no one can point to. Every such
promise needs a stored, tenant-visible, tenant-editable answer, and the renderer must say only what that
answer says. Where there is no answer, the page says **nothing** — silence is recoverable, a false promise
is a refund dispute.
