# Smart Pricing — design note

**Status:** design, nothing built · **Written:** 2026-09-28 · **Scope:** stripe-link

A tenant tells us what a thing costs them and what they want to earn. We tell them what to charge.

It sounds like a calculator and mostly is one. The interesting part is that **some costs are fixed
per unit and others are a percentage of the sale price**, so the answer cannot be reached by
multiplying — a higher price raises the percentage costs, which raises the required price. You have
to solve for it.

The engine is **generic by construction**: a cost profile is a list of lines, each declaring what
KIND of cost it is. Physical products are where the need is sharpest (an FBA seller genuinely does
not know their number), but services benefit too, and a generic engine ports to any of them without a
second implementation.

---

## 1. The solve already exists

`domain/fees.py` grosses a price up so the merchant nets a target after Stripe's fee and the
platform's:

```python
unit_amount = ceil((amount + buyer_share * fixed_cents) / (1 - variable_rate))
```

That is the same algebra, already written and already tested, with a correction loop that nudges the
result up when rounding would shortchange the merchant. **Smart Pricing computes the cost base,
applies the markup, and hands the result to `calculate_price` as `tenant_keyed_amount`.** There is no
second pricing engine and there must never be one — two of those disagreeing is how a tenant gets
quoted one number and billed another (see plans/TODO.md, the three-week-stale fee table).

And one case is already SHIPPED: the tip jar's `net_guaranteed` handling is exactly "the creator
nets $10, so charge $11". The reverse engine is live in miniature; this generalises it.

---

## 2. The cost model

One list, three kinds. Not a fixed set of named fields, because the named fields differ per business
and a schema of forty optional columns is a form nobody finishes.

```jsonc
"cost_profile": {
  "currency": "usd",
  "lines": [
    { "label": "Source cost",        "kind": "fixed",        "amount": 1000 },
    { "label": "Inbound freight",    "kind": "fixed",        "amount": 150 },
    { "label": "Import duties",      "kind": "pct_of_cost",  "rate": 0.075 },
    { "label": "Prep and labeling",  "kind": "fixed",        "amount": 25 },
    { "label": "Storage",            "kind": "fixed",        "amount": 30 },
    { "label": "Insurance",          "kind": "fixed",        "amount": 10 },
    { "label": "Shipping to customer","kind": "fixed",       "amount": 400 },
    { "label": "Returns allowance",  "kind": "returns",      "rate": 0.01 }
  ],
  "target": { "basis": "markup", "rate": 0.12 },
  "computed_at": 0,
  "computed_price": 0
}
```

### The three kinds, and why three

| kind | Enters the maths as | Example |
| --- | --- | --- |
| `fixed` | a per-unit cash cost, part of `C` | source cost, freight, outbound shipping |
| `pct_of_cost` | a percentage of the fixed base, resolved into `C` BEFORE markup | **duties**, which are levied on landed cost, not on what you sell it for |
| `pct_of_price` | part of `r`, the percentage-of-sale rate | a marketplace commission a tenant also pays |

Stripe's fee and the Junior Bay fee are **not** lines a tenant enters. They come from
`fees.py`/`billing_config`, which already knows the tenant's plan, product type and fee handling.
Asking a tenant to type "5%" invites them to type last year's 5%.

`pct_of_cost` is a category the original sketch did not have, and duties are the reason: a 7.5% tariff
is charged on the landed cost of the goods. Folding it into the percentage-of-sale rate would make
the duty rise every time the tenant raised their margin, which is not how customs works.

---

## 3. Returns are not a percentage of price

Every other variable line is a true fraction of the sale. Returns are not: when a unit comes back the
merchant does not lose 1% of the price, they lose **the whole sale, plus the outbound shipping
already paid, plus the platform fee** — because `refund_application_fee` defaults to false and we
keep ours, which is a decided policy (plans/TODO.md, "say on the refund dialog that the fees are not
coming back"). So the allowance per unit SOLD is roughly:

```
return_rate × (price + outbound_shipping + platform_fee)
```

not `return_rate × price`. On the worked example that is ~25c rather than ~21c. Small, and it is the
one line most likely to be wrong in the tenant's favour, which is the direction that hurts. It gets
its own `kind` so nobody has to remember.

---

## 4. Markup or margin — and over WHAT

Two distinctions, and the second is the one that bites.

**Markup vs margin.** A 12% markup earns `0.12 × cost`; a 12% margin earns `0.12 × price`. On $100 of
cost that is $112 versus $113.64. Both are offered (`target.basis`), because retail genuinely talks
in margin and makers genuinely talk in markup, and the UI names whichever is chosen rather than
saying "12% profit".

**Over which cost base.** Markup over FIXED costs only, or over everything the merchant spends
including the percentage fees? The original sketch used the first and displayed the second, and its
own worked example exposed it: `profit $2.00 / total costs $18.57` is **10.8%**, not the 12% printed
beside it.

**DECIDED: markup applies to TOTAL cost, fees included.** It is what a merchant means by "I need to
make 12%", and a number that quietly means something else is worse than no number. That changes the
solve:

$$P=\frac{(1+M)(C+F)}{1-(1+M)r}$$

On the worked example — C = $16.90, F = $0.30, r = 7.9% + 1% returns — that is **$20.83**, against
$20.57 for the fixed-base reading. The UI must show the basis, not just the rate.

---

## 5. Where it lives

**On the PRICE, not the product.** A price is the sellable unit, it is what carries `unit_amount`,
and `calculate_price` already works at that level. Variants today are size/colour toggles that share
one price, so there is nothing to split; if variants ever gain their own prices, the cost profile
travels with them for free. Putting it on the product would need a migration on the day that happens.

`computed_at` and `computed_price` are stamped so the price can be recognised later as **derived from
this profile** rather than typed.

---

## 5b. Where the cost lines come from

`plans/INVENTORY_COST_BASIS.md` (2026-09-30) supplies them for physical goods. A tenant records what a batch
cost — product, inbound freight, duties — and the lot derives the per-unit `fixed` lines above instead of the
tenant dividing by hand. Two consequences for this plan: where a lot exists its **actual** duties become a
`fixed` amount rather than an estimated `pct_of_cost` rate, and §6 below is the staleness mechanism a new lot
triggers, so inventory does not need its own. A product with no lots has no cost basis and this plan keeps
asking the tenant — never $0.

---

## 6. Costs go stale, and the price does not follow

A price is a SNAPSHOT of a cost profile. When the source cost rises the price does not move, and it
must not move silently — a page whose price changed itself overnight is a support ticket at best.

So: recompute on read, compare with `computed_price`, and notify only when it matters. Per the
repo's own rule (`feedback_notices_only_when_actionable`), the notice states the consequence rather
than the event: **"Your costs rose 8%. At today's price your markup is 4%, not 12%."** with one
action — restore the target. Never an automatic change.

---

## 7. Deferred pricing

The reason this began. Today the product wizard demands a price up front, which forces a tenant to
guess before they have thought about cost.

A product cannot simply lack a price — `prices` and `default_price_id` are required, Stripe sync
mints a Price, offers reference a `price_id`, and products have no draft status (only `active` and
`archived`). But this repo already has the right pattern twice: `shipping.product_readiness` and
`shipping.label_readiness` gate an ACTION without blocking the record from existing.

So `pricing_readiness` joins them. The product exists, is editable, appears in the catalogue, can
have its page generated — and is **blocked from Stripe sync and from publishing** until priced, with
the same "here is what is missing" surface the shipping work already uses. The honest form of the
button is not "no price" but **"not ready to sell yet, and here is why."**

### The control: "Delay Pricing" on the wizard's Pricing step (author, 2026-09-29)

The affordance is a **"Delay Pricing" action on the Pricing step of the product wizard**, sitting with
the step rather than buried in settings — that step is the exact moment a tenant is being asked to guess,
so it is the only place the escape hatch is useful.

Choosing it advances the wizard with no price, sets `pricing_readiness` to unmet, and the product is
created. What it must NOT do is imply the product is finished: the catalogue row, the product detail
screen and the publish action all have to say the same thing, in the same words, about what is missing.
One control that sets a flag three other surfaces silently ignore is worse than demanding a price.

**It does not exist yet, in any form.** Noted because it was mistaken for a shipped feature: a red "Delay
Pricing" label appeared on the Pricing step during sandbox testing on 2026-09-29 and turned out to be
injected by a browser extension — the string appears nowhere in `dashboard/src` or in the built bundle.
Worth knowing that the words read as native to the screen, which is a point in favour of the label.

**It is the pair to the calculator, not a standalone.** Delaying is only reasonable because §2–§4 can
work the price out afterwards from cost lines and a target margin. Shipping the button without the
engine would leave tenants with unpriced products and no way forward, which is worse than the guess it
was meant to spare them.

---

## 8. What AI has to do with it

Almost nothing, and that is the point. The original framing was "smart pricing is an AI feature"; it
is a deterministic primitive that the AI, like the builder, simply USES.

Where a model may genuinely help: explaining the arithmetic in plain language, and sanity-checking a
tenant's own numbers ("a 4% markup on a physical product will not survive one return").

Where it must NOT: **suggesting a price from what comparable products sell for.** That is market data
we do not hold, the model will confabulate it confidently, and a fabricated competitor price is worse
than a fabricated policy claim because the tenant acts on it. It belongs on the §A.7 field floor
(plans/AI_AND_COMMERCE_ARCHITECTURE.md) alongside the other things the AI may never assert.

---

## 9. Build order

1. **`cost_profile` on the Price** + a pure `domain/smart_pricing.py` that resolves lines into `C`,
   `F` and `r` and calls `calculate_price`. No UI. Fully testable, including the worked example above
   as a regression test.
2. **`pricing_readiness`**, alongside the other two gates, and the wizard's **"Delay Pricing"** control
   (§7) — plus the matching "what is missing" wording on the catalogue row, the product detail screen
   and the publish action, so one flag is not set by a control three surfaces ignore.
3. **The pricing panel** — the tenant enters lines, sees the price, the total cost, the profit and
   the basis named.
4. **Staleness notice.**
5. **A physical-product template** to pre-fill the seven usual lines. ONE template, not four: digital
   and service tenants mostly know their costs, and four templates is four things to maintain before
   we know whether one gets used. Services get the generic list, which is enough to model labour,
   materials and travel.

Step 1 is worth doing on its own even if nothing else follows: it is the same data
`plans/TODO.md`'s "transaction ledger — finish P&L" needs, and you cannot report profit without
knowing what things cost.

---

## 10. Open

- **Multi-currency source costs.** A supplier invoices in CNY; the price is in USD. Convert at entry
  and store the rate, or store the source currency and convert on read? The first is simpler and
  wrong the moment rates move; the second needs a rate source we do not have.
- **Outbound shipping as a `fixed` line is an estimate** until the carrier rate API is wired
  (plans/TODO.md, "Wire the shipping providers"). The formula does not change when it lands — only
  where that one number comes from — but a tenant should be told it is their estimate, not a quote.
- **Does the customer-facing price interact with `fee_handling`?** A `net_guaranteed` product already
  grosses fees onto the buyer. Applying a markup on top of that is coherent but needs its display
  thought through, so the tenant is not shown two different "what you keep" numbers.
