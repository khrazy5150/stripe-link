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

**DECIDED 2026-09-13 (author): presets are CHARGED amounts.** ~~The stored number always includes the
platform fee, so the buyer taps round numbers and the creator receives what is left after whichever fee mode
applies.~~ **SUPERSEDED the same day by §5e:** a preset stores BOTH — the tenant's keyed amount in `presets`
and the buyer's charge in `preset_charges` — because "you keep the full amount" has to be true of a button,
not only of the typed box. The paragraph below is the reasoning that led here and is left standing, since it
is also the reasoning FOR the pair.

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

## 5d. The range and the row are the PLATFORM's (author, 2026-09-13) — REVERSES part of 5a

Hands-on with the wizard, the author settled three things §5a had left to the tenant:

**"System set range: $1 – $500. Don't allow tenants to change it."** This reverses §5a's conclusion that the
$500 was "an arbitrary sensible default, not a limit anyone imposes". The reasoning §5a recorded still holds —
platforms do not cap tips, and Stripe's ceiling is a penny under $1,000,000 — but the *other* finding in the
same section wins: unusually large tips get flagged and accounts frozen pending fraud review, and a floor
below what Stripe will charge produces a button that fails at checkout. Neither of those is a per-tenant
judgement call, so neither is a per-tenant field.

Because presets are CHARGED amounts (§5a), the ceiling bounds the CHARGE, and there is no second reading to
worry about: a `net_guaranteed` tip cannot be keyed high enough to be charged past $500.

**"4 max IF [the custom-amount] checkbox is checked, 5 max if unchecked."** The buttons sit in one row on a
phone, and "enter your own" is a button too. Replaces §1a's "at most eight".

**Recurring tips are IN** — "daily, weekly, monthly, yearly or whatever Stripe supports" — which closes §5's
open question in the affirmative. `allow_recurring` + `recurring_interval` are set in the wizard; the cards
carry the frequency; and checkout now opens a real `mode: subscription` session with the interval on the
inline price. What is still missing is the half §5 actually warned about: **a supporter cannot cancel one.**
See §5g — recurring tips must not be enabled for live tenants until they can.

**Every tip jar is filed under one category, `tip`.** It is not a catalogue item, so nothing about it wants a
taxonomy entry of its own, and the shared taxonomy's promote-after-three-tenants rule makes one shared key the
right shape. Its product type is always `digital`: nothing ships and nothing is booked.

## 5e. A preset stores BOTH numbers — REVERSES §5a (author, 2026-09-13)

§5a decided presets were charged amounts outright. Hands-on, that made the fee selector's own sentence false:
"the customer covers the fees, you keep the full amount" cannot be true of a $25 button that charges $25 and
nets ~$23. And the box the author asked for — type an amount, see it recalculated with the fee — meant a
typed 25 and a tapped $25 would have charged two different numbers on one page.

The author's resolution: **"conceptually, each preset tip is a separate price (price card) that will be
created and displayed to the customer. The amount will vary based on what fee mode is selected"** — with a
preview of "what the customer will pay and what the tenant keeps" beside each amount, the way the single
price card already previews one.

So a preset is the pair an ordinary price already stores:

| field | meaning | ordinary price |
|---|---|---|
| `presets[]` | what the TENANT keys, and keeps under `net_guaranteed` | `tenant_keyed_amount` |
| `preset_charges[]` | what the BUYER is charged, same order | `unit_amount` |

**Confirmed against the legacy app**, which the author suspected did this: `api_products.py:151` stores
`_gross_amount` beside the price's `unit_amount` (the tenant's target net), and the template picks
`sp.gross_amount` over `sp.unit_amount` for display when the price is net-guaranteed (`components.js:1095`).
Each preset was its own Stripe Price, so each carried its own pair. For the VARIABLE amount legacy did no
such thing — it grossed the typed amount up at checkout, which is exactly what this build does.

The charges are computed at authoring time by the same `/prices/calculate` everything else uses, and stored,
because the page renderer holds no billing config — deriving them per request would be a second answer to a
question already answered. Documents written before the split carry no `preset_charges`; their presets WERE
the charges, so they read back as their own and keep rendering the same numbers.

The disambiguation the author actually asked for is the preview: `TipAmountsField.vue` shows
"Customer pays $5.45 · you keep $5.00" per amount, and the wizard asks who pays the fees BEFORE the amounts,
since every amount restates itself when that changes.

**Where these live.** `src/stripe_link/tip_rules.json`, read by BOTH `domain/tips.py` (which overwrites
whatever a price document claims) and `dashboard/src/config/tips.js`. One file, because a form that caps at
five and a server that accepts eight is this codebase's recurring failure: two things that must agree with
nothing forcing them to.

## 5f. What a refund policy on a tip even means — OPEN (author, 2026-09-13)

The composition keeps `refund_policy` on a tip jar page, and the author is right that it sits oddly:
**there is nothing to return.** A refund policy on a sales page answers "what if the thing is wrong?"; a tip
has no thing. What it actually has to answer is narrower and more awkward: *how long can a supporter change
their mind, and what happens when they do?*

### What is already known

**Stripe sets no refund deadline for cards, but the rails do.** [Stripe's refund
documentation](https://docs.stripe.com/refunds) states no maximum age for a card refund (the documented
180-day limit is for [ACH and SEPA](https://support.stripe.com/questions/refunds-for-ach-direct-debit-payments),
which cannot be refunded past it). Practically, a card refund long after the charge can fail — an expired or
closed card returns the money to us, which then has to reach the supporter some other way.

**The peers converge on 180 days, and on "the creator decides".** Ko-fi's supporters are told donations are
non-refundable and that refunds are a matter between supporter and creator; when a creator does refund,
[Ko-fi's own help says it is full amount only and must be within 180
days](https://help.ko-fi.com/hc/en-us/articles/7733731935773-How-to-issue-a-refund). [Buy Me a
Coffee](https://help.buymeacoffee.com/en/articles/8722330-buy-me-a-coffee-refund-policy) says supports are
non-refundable, does not refund on a creator's behalf except for fraud, and sends the supporter to the
creator first. Neither platform guarantees a refund; both leave the decision with the person who received
the money.

**The real deadline is the chargeback, not the policy.** A supporter who is refused can dispute instead, and
the card networks' windows are the numbers that bind — commonly ~120 days from the transaction, with longer
outer limits in specific scenarios ([Stripe's own summary of the 120/540-day
rules](https://stripe.com/resources/more/chargeback-time-limits-in-the-uk)). A policy shorter than the
dispute window does not stop the money leaving; it only decides whether it leaves as a refund (fee kept,
no dispute fee) or as a chargeback (dispute fee, and a mark against the tenant's account).

### What still has to be answered

1. **Is a tip legally a sale at all?** Consumer cooling-off and return statutes are written about goods and
   services. A gratuity with no deliverable may fall outside them entirely — or may not, and it is
   jurisdictional. Needs someone qualified, not a default. Pairs with the tax question in §5b.
2. **Fraud and stolen cards are NOT the "change my mind" case** and must be handled separately: there the
   refund is mandatory in practice, whatever the policy says.
3. **Who owns the decision — the tenant or the platform?** Both peers put it on the creator. That is also
   the honest answer for a Connect direct-charge model, where the money went to the tenant's account. But
   Junior Bay's fee comes out of it, so a refunded tip has a platform-fee question of its own (§5b's ledger
   work).
4. **Recurring tips are different.** A supporter who forgot a monthly tip and wants three months back is a
   subscription-cancellation problem, not a refund problem, and the page currently offers no way to cancel
   (see §5d: the switch shipped, the lifecycle did not).

### DECIDED 2026-09-14: refund the TIP, keep the fees

The rule generalises more cleanly than "keep" or "return": **a refund returns the tip, and whoever paid the
fees loses them.** Not a new policy — it is the fee mode applied a second time, so there is nothing extra to
explain to either side.

| mode | buyer paid | tenant got | refund | tenant ends | buyer loses |
|---|---|---|---|---|---|
| `net_guaranteed` | $11.19 | $10.00 | $10.00 | **$0.00** | $1.19 — the fees they agreed to cover |
| `split` | $10.57 | $9.43 | $9.43 | **$0.00** | $1.14 |
| `standard` | $10.00 | $8.91 | $10.00 | **−$1.09** | $0 |

(A $10 keyed tip, free tier: 5% platform + Stripe's 2.9% + 30¢.)

**This is a genuine advantage over the peers, and it is the DEFAULT here.** Under `net_guaranteed` a
refunded tip costs the creator nothing: they received $10, they return $10, and they did no work either way.
The supporter carries the ~11% they volunteered when they chose to cover the fees (author, 2026-09-14).

**`standard` is the trap, and structurally so.** The buyer contributed nothing toward the fees, so there is
nothing to hold back — refunding less than they paid is not a refund. The creator absorbs ~11% for doing
nothing. Two consequences: `net_guaranteed` stays the default for tips, and the wizard should say what
`standard` costs on a refund rather than only "fees come out of your tip".

**The platform fee is KEPT** (`refund_application_fee` stays false, as it already is everywhere). Under the
net-refund rule that costs the tenant nothing — it is paid out of the buyer's fee contribution — so there is
no one to make whole. Stripe's cut is unrecoverable regardless.

### What this needs, in order

1. **Record the tenant's keyed amount on the order, frozen at transaction time.** A preset's keyed amount is
   recoverable (the charge's index in `preset_charges` → `presets`), but a TYPED amount exists only in the
   checkout request and is gone afterwards — `handlers/checkout.py` writes no `tip_keyed_amount` into the
   session metadata. Without it, "refund the tip, keep the fees" is uncomputable for exactly the tips most
   likely to be disputed. **Prerequisite for everything else here.**
2. **Refund the NET for a tip.** `handlers/refunds.py` refunds `order.amount_total` — the gross — unless the
   request names a smaller amount. Run today against a net-guaranteed tip it debits $11.19 for the $10.00
   the tenant received, leaving them $1.19 down: the opposite of the rule above.
3. **Say it in three places.** The card already shows the charged amount and that it includes the fees; the
   receipt and the refund confirmation must too. The whole defence of keeping $1.19 is that it was never
   presented as the tip — it was presented as the cost of sending one. If the supporter first meets it when
   $10.00 lands in their statement, that defence is gone and the support contact arrives anyway.

### Still open

The wording itself — *tips are not refundable as a matter of course; if you change your mind, contact the
creator within N days* — rendered instead of the product refund-policy block on a tip page, with N set once
at the platform level rather than typed per tenant (the §5d reasoning). The composition leaves
`refund_policy` on the page today, which is the status quo and at least not a false promise.

### Product refunds are NOT this, and the difference matters

Checked 2026-09-14 on the author's prompt ("I believe net-refund is already set up for product refunds").
It is not: `handlers/refunds.py:118-121` refunds `order.amount_total` — the gross the buyer paid — and the
module docstring records that the application fee is not reversed, "legacy behavior" carried from
stripe-cart.

That is probably RIGHT for products, for a reason that does not apply to tips: under `net_guaranteed` the
grossed number IS the advertised price. The buyer sees "$107.50" and buys a widget; no fee was ever
disclosed to them separately. Refunding $100 for a returned widget short-changes them by $7.50 they never
agreed to — a chargeback they would win. A tip is the opposite case: the page says "$11.19, includes the
fees", and the supporter chose to cover them.

So the tip rule must NOT be generalised to products. The narrower question for products — the platform fee
being silently kept on every refunded order — was **decided 2026-09-14: keep it, and say so on the "Issue
refund?" dialog.** Keeping it prices refund risk to the only party who can reduce it. See the TODO entry for
the wording, the per-mode numbers, and why the warning must NOT sit on the pricing form: `net_guaranteed`
earns a product seller +$8.20 per completed sale and costs only +$0.71 per refunded one (break-even at a 92%
refund rate), so a caveat aimed at the fee mode would steer tenants into the worse deal. The ~$8.20 is the
refund, not the mode.

## 5g. Cancelling a recurring tip: a LINK, not an account (DECIDED, author 2026-09-14)

### The decision

**No buyer-side accounts — "at least not initially" (author).** A supporter cancels a recurring tip through a
tokenized link, and support can act on their behalf without one. The reason given is the one that should
govern the whole buyer surface: *no friction between customers and tenants when it comes to giving a tip or
buying a product.*

### Why the account model looked necessary, and why it is not

The peers (Patreon, Ko-fi, Buy Me a Coffee) all require a supporter account, and cancellation runs through
it: log in → settings → memberships → find the creator → cancel. The author's objection to links was the
right one to raise: *what if the supporter loses access to that email account? Support has no way to verify
them.* Three things answer it.

**1. Account recovery IS email recovery.** "Forgot password" sends a reset to the same dead inbox. The
account adds a layer on top of the dependency rather than removing it. The one real exception — lost inbox
AND remembered password — is narrow, and it is the case most people solve by clicking "forgot password"
anyway.

**2. Cancellation is FAIL-SAFE, so the verification bar is legitimately low.** The worst outcome of a
wrongful cancel is that a donation stops and the supporter re-subscribes. Nobody attacks a system to stop
someone else's tip. Accounts protect valuable state — content access, stored cards, purchase history; a tip
guards a button whose misuse costs nothing. That is what makes a support runbook (below) an adequate
substitute for a login, which it would NOT be for, say, a download or an order history.

**3. There is always a third path, and it is the expensive one.** A supporter who cannot reach us calls
their bank and blocks the merchant. That works every time and is the worst outcome for the tenant: a dispute
fee plus a ratio that eventually costs them the ability to take payments. So the question is not "can
everyone always self-serve" but "how often do we push someone to their bank" — and a link plus a support
desk that can actually act answers it.

Against that: buyer accounts would be a **new subsystem**. Cognito here is the DASHBOARD's gatekeeper —
tenants only. Every buyer-facing feature we have already works without an account (digital downloads by
purchase-verified link, lead magnets by link, cart recovery by opaque token), so accounts for the cancel
button alone would mean carrying a login system for one action while everything else keeps using links.

### What the account model genuinely wins, and when to revisit

One dashboard showing everything a supporter funds across creators. That is Patreon's actual product, and it
only matters to someone supporting many creators. **The decision it belongs to is "do we want a buyer-side
product?" — not "how do people cancel?"** If the marketplace direction (plans/DIGITAL_MARKETPLACE.md) is
taken up, accounts earn themselves there and cancellation rides along. Revisit it then, on those merits.

**If accounts ever arrive they are ADDITIVE**: an optional "save this so you can manage it" prompt AFTER the
tip, never a gate before it. The link keeps working for everyone who ignores the prompt, which is most
people.

### The mechanism — every piece already exists here

1. Checkout in `mode: subscription` already creates a Stripe Customer on the tenant's **connected** account.
2. The receipt for a recurring tip carries "manage or cancel this monthly tip", minted as an **opaque
   token** — the pattern `cart_token_doc` (domain/cart.py) already uses for abandoned-cart recovery: the
   token dereferences to an email server-side, so no PII rides in the URL, and it carries a TTL.
3. The link opens a **Stripe Billing portal session** on the connected account.
   `handlers/platform_subscription.py:280` already creates these for tenant billing — the same call plus
   `stripe_account`. The portal has to be configured for the connected account (or configuration passed at
   session create); verify which before building.
4. The tip page carries a small **"Manage an existing tip"** link that asks only for an email and re-sends a
   fresh token. This is what makes a short TTL safe, and it is the backstop when the receipt never arrived —
   email deliverability is this design's single point of failure, so it gets a second door.

### The support runbook (what replaces "log in to prove it's you")

Verify ONE of: card last-4 + expiry · the exact amount and date of a charge · the billing postcode. All are
things Stripe search can confirm and only the cardholder has. Then cancel. No account, no notarised proof —
because per (2) above, the action is fail-safe. Write this down for whoever answers support@; the failure
mode to avoid is a support agent refusing to act and the supporter calling their bank instead.

### Gate

**Recurring tips must not be enabled for live tenants until the link ships.** Checkout creates real
subscriptions today; the only way to stop one right now is to ask the creator to do it in their Stripe
dashboard — which is exactly the Ko-fi behaviour this section argues against.

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
   duplicates, and more than the row holds (5, or 4 alongside "enter your own" — §5d). The schema stays
   `additionalProperties: false`, which is what caught the gap in the first place. Still to migrate: fold a legacy `suggested_amount` into `presets`.
3. ~~**Runtime**~~ ✅ **DONE 2026-09-13**: the page renders one `.sl-price-option` card per preset plus an
   optional "Other" box (`runtime/html.py` `_tip_option_cards`); a resolved tip line defaults to the checked
   preset rather than to zero (`domain/pricing.py`); the box prices a typed amount through the SERVER's
   `/prices/calculate` rather than a second copy of the fee maths; and `handlers/checkout.py`
   `apply_tip_amount` re-decides the charge — a preset must be one the price offers, a typed amount must sit
   in the platform range — then prices the line inline. Markup states the RANGE, never `price: 0.00`.
   Still missing: recurring tips (`mode: subscription`), and tips as ORDERS (step 5).
4. ~~**The product wizard**~~ ✅ **DONE 2026-09-13** (§4): intent first, then only what that intent
   needs. Tip jars file themselves (`digital` / `tip`), carry the platform range, offer up to five preset
   amounts and an optional recurring interval. Authoring only — see step 3 for what still does not run.
5. **The order/tax decisions** (§5) followed through receipts, refunds, fees and the ledger — carrying the
   `entry_type: "tip"` classification of §5b, frozen at transaction time.
6. **Re-make the `jbay.page` abuse argument** (§6) before a tip jar serves on a platform host.
7. **The `tip_jar` element's first-party mode and its create-on-the-fly** (§5c) — smallest piece, depends on
   all of the above, and reuses the `DIGITAL_MARKETPLACE.md` §4.2 provisioning state machine.
