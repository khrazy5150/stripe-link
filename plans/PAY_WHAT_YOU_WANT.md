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

## 1a. The schema models a tip jar as a discounted sale, and forbids the rest

Checked 2026-09-13 at the author's prompting. `Price.schema.json` **does** carry `pricing_model`
(`one_time | recurring | customer_chooses`), `min_amount` and `suggested_amount` — so it is not absent. It is
**partial, and closed**:

- `additionalProperties: false`. The legacy fields — `presets`, `max_amount`, `allow_custom`,
  `allow_recurring`, `recurring_interval` — would be **rejected on write**. The schema does not merely omit
  the correct model; it currently blocks it.
- `unit_amount` is described as *"Sale amount charged to the customer"* and is the field every runtime path
  reads. A tip jar is therefore modelled as a sale with two decorative extra fields, which is exactly why it
  behaves as one.

So the author's read is right in substance: nobody designed a tip jar here, the transaction shape was reused
and two fields were bolted on. Widening the schema (§7 step 2) is a prerequisite for everything else, and it
is a schema change rather than an addition — `unit_amount` has to stop being the answer for this model.

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

## 5a. Fee handling, the maximum, and what presets MEAN

Three modes, and two of them mean **the buyer is charged more than the tip**:

| mode | buyer pays |
|---|---|
| `standard` | the tip; fees come out of it |
| `split` | the tip **+ half** the fees |
| `net_guaranteed` | the tip **+ all** the fees |

`calculate_price()` already does this: given a `tenant_keyed_amount` it returns `unit_amount`, the grossed-up
figure the buyer is actually charged. The page shows that full figure, so nothing is hidden.

**`max_amount` is a reasonable-range guardrail, not a compliance boundary — so fees pushing the charge past
it are fine.** Raised and then WITHDRAWN by the author 2026-09-13, after checking: tips are not capped by
platforms, and Stripe's hard ceiling is one penny under $1,000,000. The legacy form's `$500` was an arbitrary
sensible default (`products.js:2233`, `|| 500`), not a limit anyone imposes. A `net_guaranteed` tip of $500
charging ~$516 needs no special handling.

Recorded rather than deleted, because the worry is a natural one to have again: anyone meeting the three fee
modes for the first time will wonder whether the cap has to bound the charge, and the answer is no.

Two things that DO survive it:

**Unusually large tips get flagged and accounts frozen pending fraud review** (author's research). That is an
argument for the tenant keeping a sane default maximum — which is what the $500 was — not for the platform
enforcing one. Worth surfacing in the wizard as guidance rather than as a rule.

**Presets are ambiguous, and that is a real decision.** Presets are stored as amounts, but under `split` and
`net_guaranteed` a "$25" preset does not charge $25:

**DECIDED 2026-09-13 (author): presets are CHARGED amounts.** The stored number always includes the platform
fee, so the buyer taps round numbers and the creator receives what is left after whichever fee mode applies.

Not a new rule — it is **exactly what product prices already do** under `split` and `net_guaranteed`, where
the tenant keys an amount and `calculate_price()` returns the grossed-up figure the buyer is charged. A tip
jar behaving differently from every other price in the system would be the surprising choice, and it also
matches "nothing is hidden": the number on the button is the number on the card statement.

Under `standard` the two readings are identical, which is why the question only appears once someone switches
mode — and why it had to be settled before presets were built rather than after.

## 5b. Every tip must be RECORDED as a tip (author, 2026-09-13)

Not a display concern — an accounting one. The money has to be classifiable as tip income after the fact,
separately from sales.

**Motivation, as the author put it:** most tenants will not qualify for the US federal deduction on tip income
(~$25,000 annually, currently scoped to occupations that customarily receive tips, which does not obviously
include content creators). But the classification is worth keeping regardless — for ordinary accounting, and
because the scope of that rule could widen. The treatment itself is a question for someone qualified; what
engineering owes is that the DATA supports whatever answer they give.

**Where it goes.** `domain/ledger.py` already types every entry — `entry_type` is `"sale"` or `"refund"`. A
tip is a third sibling, `"tip"`, which gives the tenant's books the separation for free and needs no new
table. Plus:

- the order (or whatever §5 decides a tip is) carrying the same classification on the line, so a receipt and
  an export agree with the ledger;
- Stripe metadata on the PaymentIntent, so the tenant's own Stripe reporting shows it without going through
  us at all.

**Freeze it at transaction time. Do NOT derive it later from the product.** The classification must be written
onto the ledger entry when the money moves, never reconstructed by looking up whether that product's
`pricing_model` is still `customer_chooses`. A product can be edited, re-priced or archived, and last year's
books must not change when this year's catalogue does.

That deliberately **inverts the rule this codebase has been applying all week.** Identity and presentation are
derived on purpose — the avatar, the brand label, the creator's name — so that changing them updates every
page, and freezing any of those caused a bug each time. Financial records are the opposite: a transaction is a
statement about a moment, and re-deriving it later is how history quietly rewrites itself. Both rules are
right; they apply to different kinds of fact, and the distinction is worth naming because the recent
precedent all points the other way.

**Do not reuse `fee_class_for()` as the classifier.** It returns `"tip_jar"` today for exactly this pricing
model, which makes it tempting. But it answers *"what does the PLATFORM charge for this?"* — our pricing — and
the income classification answers *"what kind of income is this for the TENANT?"* Two questions that happen to
agree today and have no reason to stay aligned: a future fee tier, a promotional rate, or a second product
type that bills like a tip would break the coupling silently, and it would break it inside someone's books.

**Consequence for §5.** The open "is a tip an ORDER?" question now has a constraint on it rather than being
free: whichever shape wins has to carry this classification durably through receipts, refunds and exports. A
refunded tip is a reversal of tip income, not of a sale.

## 5c. The element offers a Junior Bay tip jar, created on the fly (author, 2026-09-13)

The `tip_jar` element already links out to Ko-fi, Patreon or Buy Me a Coffee. It should also be able to point
at a Junior Bay tip jar — **and offer to create one**, in the same field where the tenant would otherwise
paste a competitor's URL.

**Why create-on-the-fly rather than "go make one first".** A first-party tip jar needs a Product, an Offer and
a Page. Sending someone off to build three documents, then come back and link them, is the friction that makes
pasting a Ko-fi URL the obvious choice instead. Seeded defaults invert that: it is far easier to edit a page
that exists than to build one that does not. The tenant then opens it and changes whatever they like.

**Reuse the provisioning state machine, do not invent one.** `DIGITAL_MARKETPLACE.md` §4.2 already answers
this exact problem: DynamoDB transactions do not span the tables this repo uses, so multi-document creation is
a **resumable, idempotent state machine, not a transaction** — anchor row first, then Product, then Offer,
then the draft page via the existing composition pipeline, each step keyed off the anchor so a retry resumes
instead of duplicating. The tip jar is a smaller instance of the same shape and should share it.

**Say what was created, and where.** Three catalogue rows appearing from one click is exactly the kind of
thing a tenant finds a month later and does not recognise. The confirmation names the product, the offer and
the page, and links to the page.

### The pitch, and keeping it true

The differentiator is real: every other platform in this slot takes its cut **out of the tip**. Junior Bay can
put the fees on the customer instead (`net_guaranteed`), so the creator receives the full amount they asked
for. The author's copy —

> *"Want to keep most or all of your tip income? Create your free Tip Jar page here!"*

— is accurate as written, and worth protecting from being "improved" into something that is not:

- **"most or all"** is exact. Under `net_guaranteed` the buyer covers everything and the creator nets the full
  keyed amount; under `split` they cover half. Both are real options; "all" alone would not be.
- **"free"** is accurate for the PAGE — landing pages are free-forever post-pivot — and should not be read as
  the tip being fee-free. At the free tier the platform's tip fee is 5% (`fees.py`, 5/5/0 by tier); what
  changes is who pays it.
- **The comparative claim is DECIDED and narrow** (author, 2026-09-13). We say:

  > *Everywhere else, the fees come out of your tip. Here, your customer can cover them.*

  We do **not** say "other platforms deduct fees and we don't". Ko-fi charges no platform fee on donations and
  is the likeliest competitor in this exact field, so the broad version is falsifiable by the first person who
  checks — and a marketing claim that fails a five-second check costs more than the claim was worth. The
  narrow one is also true of Ko-fi, whose Stripe fees still come out of the creator's payout, which is what
  makes it both safer AND stronger.

### Seeded defaults

- `fee_handling: net_guaranteed` — it IS the pitch, and a default that contradicts the sentence that sold it
  would be strange. The trade-off is honest and visible: the buyer sees a slightly higher number. Editable.
- Presets, a minimum, and custom amounts on — per §5a, once the keyed-vs-charged question is answered.
- A page seeded from the tip-jar composition, attached to the same Site as the page that created it.

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
2. ~~**Widen the model**~~ ✅ **DONE 2026-09-13.** `Price.schema.json` carries `presets[]`, `max_amount`,
   `allow_custom`, `allow_recurring`, `recurring_interval`; `suggested_amount` is deprecated in place rather
   than deleted, so existing documents keep validating. Validation now REFUSES a `customer_chooses` price that
   offers no way to choose — the rule that stops the original bug recurring — plus presets outside the bounds,
   duplicates, more than eight, and inverted bounds. The schema stays `additionalProperties: false`, which is
   what caught the gap in the first place. Still to migrate: fold a legacy `suggested_amount` into `presets`.
3. **Runtime**: pricing resolution, the preset-button UI on the page, and checkout with validated inline
   `price_data` — presets being CHARGED amounts per §5a.
4. **The product wizard** (§4) — or before 2/3, if the wizard lands first.
5. **The order/tax decisions** (§5) followed through receipts, refunds, fees and the ledger — carrying the
   `entry_type: "tip"` classification of §5b, frozen at transaction time.
6. **Re-make the `jbay.page` abuse argument** (§6) before a tip jar serves on a platform host.
7. **The `tip_jar` element's first-party mode and its create-on-the-fly** (§5c) — smallest piece, depends on
   all of the above, and reuses the `DIGITAL_MARKETPLACE.md` §4.2 provisioning state machine.
