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
3. **Where does it land on the order?** `order.shipping_amount` does not exist. Without it: the tenant's P&L
   is wrong (shipping revenue is invisible), the fee calculation is wrong (is the platform fee charged on
   shipping?), tax is wrong in jurisdictions that tax shipping, and a refund cannot know whether shipping
   comes back.

**That third one is why this is a primitive and not a feature.** Every downstream system already in the repo
— ledger, fees, refunds, tax fields — has a shipping-shaped hole in it.

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

## Phases

1. **`order.shipping_amount` + the offer's shipping mode** (`baked` | `charged` | `free`). Schema and
   validators first, so nothing downstream has to guess.
2. **`domain/shipping_charges.py`** — pure: given the config, the cart and the mode, return the amount. Flat
   and threshold first; weight bands when the box catalogue justifies them.
3. **The fee decision** (above), recorded in `fees.py` with its reasoning.
4. **Checkout wiring** — `shipping_options` on the session for `charged`; nothing for `baked` or `free`.
5. **Ledger, refunds and tax** read `shipping_amount` rather than assuming zero.

## Open

- **Does the buyer ever see a shipping line under `baked`?** SHIPPING_PROVIDERS §8 asks this already and it
  is still unanswered. Under `baked` the page may honestly say "free shipping"; under `charged` it must not.
- **International.** Checkout allows US and CA today, hardcoded. A shipping charge that ignores destination
  is wrong the moment a second country is allowed.
- **Interaction with SMART_PRICING.** If a tenant models shipping as a cost line AND charges for it, they
  are paid twice. The two plans need one rule, and it probably belongs here: `baked` means Smart Pricing
  owns it, `charged` means this does.
