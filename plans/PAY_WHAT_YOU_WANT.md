# Pay what you want (Tip Jar)

Status: PLANNED 2026-09-13, not built. Supersedes `SOCIAL_MEDIA_PAGES.md` §9.8b.
Related: `LEAD_GEN_PAGES.md` §10 (the product wizard this belongs in), `CREATOR_LINK_POLICY.md` §3,
`docs/PLATFORM_PLANS.md`, and stripe-cart `plans/one-time-and-recurring-payment-product-implementation.md`
(the behavioural spec — it is BUILT and working there).

---

## 1. What is wrong today: it looks configured and silently sells at a fixed price

"Customer chooses" exists in the product form and is a **lossy, half-imported** copy of the legacy feature.

`pricing.js:138` writes `min_amount` and `suggested_amount` **on top of a normal `unit_amount`** taken from
the Sales price field. Then `pricing_model` appears **nowhere** in `checkout.py`, `pricing.py` or
`runtime/html.py` — all three read `int(price.get("unit_amount", 0))` and treat it as fixed.

So a tenant configures a tip jar, saves it without error, and gets **a product sold at whatever they typed in
Sales price**, with no way for the customer to choose anything. Not a crash, not a $0 product: a plausible
wrong answer, which is the worst failure shape. It is the same family as `same_as[].verified` and
`analytics_summary` — a control the UI offers that nothing downstream honours — and the third one found.

**This is a regression against the legacy app, not a missing feature.** stripe-cart ships it.

## 2. The legacy behaviour, which is the spec

From stripe-cart's plan doc and its product form:

```json
{ "pricing_model": "customer_chooses", "nickname": "Tip Jar", "currency": "usd",
  "presets": [200, 500, 1000, 2500], "allow_custom": true,
  "min_amount": 100, "max_amount": 50000,
  "allow_recurring": true, "recurring_interval": "month" }
```

- **Preset amounts are a LIST** rendered as buttons ($2 / $5 / $10 / $25), not one "suggested amount".
- **Allow custom amount** is a separate switch, with **minimum AND maximum**.
- **Allow monthly recurring** — a tip can be a subscription.
- **No Stripe Price is created.** The config lives in the document; a placeholder Stripe *Product* exists so
  checkout can reference it from inline `price_data`.
- **Checkout takes the chosen amount from the page**, builds inline `price_data`, and validates against
  min/max.

stripe-link today has `min_amount` + a single `suggested_amount`, and no max, no presets, no custom-amount
switch, no recurring. The model needs widening to match before any of it can work.

## 3. Where the amount is chosen — corrected

I first proposed letting Stripe collect it via `custom_unit_amount[minimum|preset]`, on the grounds that an
amount typed on our page reaches our endpoint as a client-supplied number.

**That does not deliver the behaviour.** `custom_unit_amount` gives ONE input on Stripe's page; it cannot
render a row of preset buttons, which is the whole affordance — most people tap $5, they do not type it. So
the amount is chosen on OUR page, as it is in the legacy app.

The security concern does not go away, it just gets answered properly instead of avoided:

- **The server validates, always.** A preset must match the stored list EXACTLY; a custom amount must fall
  within `min_amount`/`max_amount` AND `allow_custom` must be true. A client-supplied amount is never
  trusted, only checked.
- **The fee is computed server-side from the validated amount**, never sent by the page.
- Rejection is an error, not a clamp: silently charging someone a different number than they chose is worse
  than refusing.

## 4. It belongs in the NEW product wizard, not the current form

Author, 2026-09-13. The product screen is changing anyway (`LEAD_GEN_PAGES.md` §10: ask commercial intent
first, then skip the fields that intent does not need), and a tip jar is a third answer to that first
question — not "I want a payment" and not "I want to capture a lead", but "I want to receive tips".

Bolting presets, min, max, custom and recurring onto the existing Pricing card would make the busiest part of
the busiest form worse, right before that form is replaced. So:

- **The wizard asks intent, and "Tip jar" is one of the answers.**
- Choosing it **skips** the transactional fields a tip has no use for — SKU, categories, condition, shipping,
  variants, compare-at price — exactly as the lead-gen branch does.
- What it asks instead: preset amounts, allow-custom (+ min/max), allow-recurring, currency, fee handling.
- The `customer_chooses` pricing model stays the underlying representation, so nothing about Offers, the fee
  class or the index projection has to change shape.

**Sequencing consequence: §10's wizard is now a dependency, not a nicety.** Build the wizard first, or build
the runtime first and the wizard second — but do not extend the current Pricing card.

## 5. Decisions still open

**Is a tip an ORDER?** The receipt, refund, fee and ledger rails all assume one, and a tip has nothing to
fulfil. (a) an order with a synthetic line and `fulfillment: none`, reusing every rail; (b) a second document
type, and every rail learns a shape. (a) is cheaper, (b) is more honest. This decides most of the work.

**Tax.** A gratuity is not a sale of goods and the treatment is jurisdictional. Stripe Tax is configured per
product here. Needs someone qualified, not a default.

**Recurring tips mean `mode: subscription`.** A monthly tip is a Stripe subscription, with everything that
implies: cancellation, dunning, and a customer portal path. Worth asking whether v1 ships one-time only —
the legacy app has the switch, but shipping the switch is not the same as shipping the lifecycle.

**Fee handling on a tip.** The fee class (`tip_jar`, 5/5/0) exists. Whether "Net-guaranteed" is offered — the
buyer covering fees so the creator keeps the round number — is a product question the legacy form answers
yes to.

## 6. It changes the abuse story for `jbay.page`

`CREATOR_LINK_POLICY.md` §3 argues the link allowlist IS the abuse story for the creator domain **because
these pages carry no payment**. A first-party tip jar makes a link hub a page that takes money on a shared,
anonymous-signup domain: card testing against a low minimum, and scam donation pages that look like a person.
The allowlist does nothing about either.

That argument must be re-made before a tip jar can exist on a platform host — at minimum, what onboarding is
required before one can take money, and what §6's takedown path does when a tip jar is reported rather than
a link.

## 7. Order

1. **Stop the silent wrong answer.** Either honour `customer_chooses` end to end, or refuse to save one. A
   product that sells at a price the tenant did not intend is the live bug here.
2. **Widen the model** to the legacy shape: `presets[]`, `allow_custom`, `max_amount`, `allow_recurring`,
   `recurring_interval`. Migrate the existing `suggested_amount` into `presets`.
3. **Runtime**: pricing resolution, the preset-button UI on the page, and checkout with validated inline
   `price_data`.
4. **The product wizard** (§4) — or before 2/3, if the wizard lands first.
5. **The order/tax decisions** (§5) followed through receipts, refunds, fees and the ledger.
6. **Re-make the `jbay.page` abuse argument** (§6) before a tip jar serves on a platform host.
7. **The `tip_jar` element's first-party mode** — smallest piece, depends on all of the above.
