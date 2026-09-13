# Pay what you want (Tip Jar)

Status: PLANNED 2026-09-13, not built. Supersedes `SOCIAL_MEDIA_PAGES.md` §9.8b, which assumed far more was
missing than actually is.
Related: `SOCIAL_MEDIA_PAGES.md` §9.8, `CREATOR_LINK_POLICY.md` §3, `LEAD_GEN_PAGES.md` §4, `docs/PLATFORM_PLANS.md`.

---

## 1. It is half-built already, and the half that exists is the half I assumed was missing

Corrected 2026-09-13 after the author pointed at the pricing form. `customer_chooses` is a real pricing model
with a UI, a document contract and its own fee class:

| Piece | State |
|---|---|
| `pricing_model: "customer_chooses"` + `min_amount` + `suggested_amount` | **Exists** — `documents.py:774-779` |
| Dashboard control ("Customer chooses", Minimum, Suggested, fee preview) | **Exists** — `PricingCard.vue` |
| Fee class `tip_jar`, distinct rates per tier | **Exists** — `fees.py:122`, 5% / 5% / 0% |
| `suggested_amount` on the product index projection | **Exists** — `product_index.py` |
| Pricing resolution | **Missing** |
| Rendered price card / CTA | **Missing** |
| Stripe Checkout | **Missing** |

**`pricing_model` appears NOWHERE in `checkout.py`, `pricing.py` or `runtime/html.py`.** Every one of them
reads `int(price.get("unit_amount", 0))` and treats it as fixed. A `customer_chooses` price has no
`unit_amount`, so it resolves to **zero** — the page would show $0.00 and checkout would send
`unit_amount=0`.

So this is a configured capability with no runtime behind it: the tenant can set it up today and nothing
downstream honours it. The same shape as `same_as[].verified` (read, never written) and `analytics_summary`
(read by the cards, written by nothing) — both of which shipped looking complete and were not. **Before
anything else, that gap should either be filled or the control should refuse to save**, because a tenant who
configures a tip jar today gets a $0 product and no error.

## 2. The buyer names the amount on STRIPE'S page, not ours

Stripe Checkout takes `price_data[custom_unit_amount][enabled|minimum|maximum|preset]`. The buyer types the
amount on the Checkout page.

That is the right first move for a reason beyond effort. An amount typed on OUR page has to travel to our
checkout endpoint as a client-supplied number, and a client-supplied amount is a tampering surface that has to
be re-validated server-side against the product's `min_amount` on every path. Letting Stripe collect it means
the amount never passes through anything of ours that could be lied to. `minimum` is enforced by Stripe, and
`preset` is exactly what `suggested_amount` already stores.

The page-side affordance is then a button, not an input, which is also what a link hub wants.

## 3. Decisions to make before building

**Is a tip an ORDER?** The receipt, refund, fee and ledger rails all assume one, and a tip has no line item to
fulfil, no shipping, no return. Options: (a) an order with a synthetic line and `fulfillment: none`, reusing
every rail; (b) a second document type, and every rail learns a shape. (a) is cheaper and (b) is more honest;
the answer decides most of the work.

**Tax.** Stripe Tax is configured per product here. A gratuity is not a sale of goods and its treatment is
jurisdictional. This needs an answer from someone qualified, not a default.

**Refunds.** A tip is refundable in principle, and the existing refund path assumes an order (see above).

**Minimum.** `min_amount` is already in the document and already validated. It must be passed to Stripe, not
merely displayed — a minimum enforced only in the UI is decoration.

**Currency.** `customer_chooses` inherits the price's currency. No new decision, but worth stating.

## 4. It changes the abuse story for `jbay.page`

`CREATOR_LINK_POLICY.md` §3 argues the link allowlist IS the abuse story for the creator domain **because
these pages carry no payment** — the outbound link being an abuser's only lever. A first-party tip jar makes a
link hub a page that takes money on a shared, anonymous-signup domain.

That is a different surface and the allowlist does nothing about it: card testing against a $1-minimum
endpoint, and scam donation pages that look like a person. Neither is hypothetical for this product category.

**So the §3 argument must be re-made, not inherited.** At minimum: what does signup require before a tip jar
can take money (Connect onboarding already gates payouts — does it gate this?), and what does the takedown
path in §6 do when a tip jar is reported rather than a link?

## 5. The `tip_jar` element gains a second mode

Today it is an outbound link (shipped 2026-09-13). It should become: link to a destination, OR take the tip
here. Same element, one switch, because from the visitor's side it is one button either way.

The first-party mode needs a product with a `customer_chooses` price — which the tenant already creates in the
form pictured above — so the element references a product rather than growing its own pricing.

**Note the composition tension.** `lead_social` excludes `checkout_cta` on the grounds that a link hub's cards
ARE its calls to action and a page that takes no money needs no checkout. A first-party tip jar does not
reintroduce `checkout_cta` — it is its own element with its own button — but "this page sells nothing" stops
being true of the SHAPE, and §4's exclusions were justified partly on that. Worth re-reading them together.

## 6. Order

1. **Make the existing control honest** — either resolve/render/checkout a `customer_chooses` price, or refuse
   to save one. Today it saves and silently produces $0.
2. **Checkout**: `custom_unit_amount` with `minimum` and `preset`, amount collected by Stripe.
3. **Decide the order question** (§3) and follow it through receipts, refunds, fees and the ledger.
4. **Re-make the `jbay.page` abuse argument** (§4) before a tip jar can exist on a platform host.
5. **The element's second mode** (§5). Last: it is the smallest piece and it depends on all of the above.
