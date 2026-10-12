# Sales Tax — surface Stripe's, never rebuild it

**Status: Phases 1–2 BUILT 2026-10-12, plus a status-gated switch this plan originally ruled out.**
Written 2026-09-30. Phases 3–5 (in-app notice, email, embedded monitoring panel) remain unbuilt.

## Why this exists

The author, 2026-09-30: *"I just think we should wire it in the app and maybe even send an email
notification."* Agreed, with one boundary that decides the whole shape of the work:

> **Stripe determines tax. We make sure the tenant knows it exists, knows whether theirs is on, and knows
> where to go. We never determine, declare, or imply anything about their liability.**

Today the app is silent on tax. There is no `automatic_tax` anywhere in `src/`, nothing reads a tenant's tax
status, no screen mentions it, and `domain/connect_sync.py` learns `charges_enabled` and `details_submitted`
and nothing about tax. A tenant can take $200k through JuniorBay and never once be told sales tax is a thing.

That silence is the actual problem — not a missing calculator.

## What Stripe already does, and we must not rebuild

| | Stripe | Us |
| --- | --- | --- |
| Tax calculation at checkout | `automatic_tax` — jurisdiction, rates, product tax codes | nothing |
| Threshold monitoring (where you may need to register) | **free**, per connected account | nothing |
| Registrations (the legal declaration) | tenant does it in their Dashboard | **never us** |
| Keeping 50 states' rules current | theirs, forever | would be a permanent liability |
| Remittance | tenant / their accountant | never |

**The case against building a nexus tracker is in `plans/TODO.md`** and it stands: economic nexus is per state
with varying thresholds, measurement periods and gross-vs-taxable rules; we can approximate destination gross
for physical orders from `order.shipping_address` but NOT for digital or services, whose nexus turns on a buyer
location we do not hold; and a tracker covering part of a tenant's revenue is worse than none because it reads
as coverage.

**This plan therefore does not compute nexus at all.** That single decision removes the need for per-state
aggregation, which in turn makes the whole feature small.

## What gets built

### 1. A tenant tax status the app can read

    domain/tax_status.py        pure: interpret a status payload, decide what to say about it
    stripe_client               GET /v1/tax/settings with Stripe-Account: <tenant's account>
    TenantConfig or a cache row status + when it was read

Cached like `fees.py` caches billing config (300s TTL precedent), **never read in the buyer's path** — a tax
status lookup inside checkout is a round trip on every sale to answer a question that changes monthly.

Three states worth distinguishing, because the right thing to say differs:

- **active** — tax is being calculated. Say so, and stop nudging.
- **pending / incomplete** — ~~the tenant started and did not finish. That is the most valuable nudge of
  all.~~ **WRONG, corrected 2026-10-12 against live data.** `tax.settings` **always exists** and is
  `pending` by default for every account that has never touched Stripe Tax, so `pending` is the
  **starting** state and not evidence of an abandoned attempt. The two cases are indistinguishable from
  the status alone. The first tenant to see this screen had never opened Stripe Tax and was told their
  setup was "Unfinished". The badge reads **"Not set up"** and the copy never says "you did not finish";
  naming Stripe's `missing_fields` is still the useful part, and it fits both cases.
- **absent / unreadable** — say nothing about their liability; say only that no tax is being collected.

**VERIFY before relying:** the exact Tax Settings API response shape, and whether a **Standard OAuth**
connected account permits the platform to read it at all. If it does not, the status row degrades to
"we cannot tell — check your Stripe settings", which is still better than silence. This is the same open
question already recorded in `plans/TODO.md` for the embedded components.

### 2. A status row on the Payments screen — not a toggle

> **AMENDED 2026-10-12, at the author's instruction.** There *is* now a switch. The paragraph below is
> kept because its reasoning is right and still constrains the design — what changed is the recognition
> that it argues against a control over **the tenant's compliance**, and not against a control over
> **our own behaviour**.
>
> The switch is labelled **"Add sales tax at checkout"**, and it is `may_enable`-gated: it is only
> rendered, and only honoured by the server, once Stripe **already** reports `tax.settings.status ==
> "active"` for that account — which means the tenant has done the head-office and registration work in
> their own Dashboard. We never make the tax claim; we act on one Stripe has already accepted. Nothing
> in the app creates a registration or says a word about whether one is owed.
>
> The server re-reads Stripe before honouring a switch-on, because a client is not a permission.

It belongs beside the BNPL toggles (`plans/BNPL_PAYMENT_METHODS.md`): both answer "what happens to money at
checkout". But it is a **read-only status plus a link**, because enabling Stripe Tax means declaring tax
registrations per jurisdiction, and a registration is a legal statement that the tenant has nexus there and
will remit. A control labelled "Enable Stripe Tax" would imply the platform can make that statement, and a
tenant clicking it would reasonably believe they were now compliant. **That is the most expensive kind of
wrong, so the control does not exist.**

    Sales tax                                        Not enabled
    No sales tax is being collected on your orders.
    Stripe can monitor for free where you may need to register.   [Open Stripe Tax ↗]

### 3. Threshold monitoring, embedded if possible

Stripe ships monitoring as a Connect embedded component (`tax_threshold_monitoring`) via an Account Session
and `@stripe/connect-js`. Nothing in this repo uses embedded components yet — no `connect-js`, no Account
Session anywhere — so this is genuinely new ground here.

**VERIFY: embedded components with Standard OAuth accounts.** The platform-liable model fits Express/Custom,
and `plans/TODO.md` already flags this doubt. Fallback is a deep link to the tenant's own Stripe Tax settings,
which costs one line and works regardless. **Ship the deep link first**, add the embedded panel only once
Standard support is confirmed — the link delivers most of the value and cannot fail.

### 4. The email, and what it must NOT be about

The author asked for an email. The important design call:

> **Our email is about ENABLING MONITORING. It is never about crossing a threshold.**

Stripe's own monitoring notifies the account holder when a threshold is approached (**VERIFY** the exact
channel). If we also email on thresholds we produce duplicate alerts from two systems that will eventually
disagree — and ours would be the wrong one, since we do not compute nexus. Worse, a tenant who gets our
threshold email may assume we are tracking their liability.

So one email, with a narrow job: *"You're at the size where sales tax is worth a look. Stripe monitors it for
free — here's where."* Sent from the platform identity (`mailer.from_email_address`), not the tenant's sender
identity — this is JuniorBay talking to its customer, not a storefront talking to a buyer.

### 5. The trigger, deliberately coarse

Because we are not determining nexus, the trigger does not need to be clever — and must not look clever:

- **Total gross**, read from the ledger, which already aggregates it. No per-state maths, no order scans.
- A **conservative floor** stored as config, not a constant in code (the `PlatformPlansTable` precedent:
  the author's rule that thresholds are data a tenant-less admin can change without a deploy).
- Rides an existing **15-minute sweep** rather than a new schedule — `cart-recovery-sweep`,
  `review-invites-sweep` and `reminders-sweep` all establish the pattern.

**Wording that never claims nexus.** Not *"you must register in Ohio"*, not *"you owe tax"*, not even
*"you have nexus"*. Only: you are this big, tax is worth checking, Stripe does it free. Per
`feedback_notices_only_when_actionable`, the action is "look at Stripe's monitoring" — the only action we can
honestly ask for.

### 6. Not nagging

A notice that repeats becomes invisible, and a tax notice that repeats is alarming as well as useless.

- **Stop permanently** when status is `active`.
- **Dismissible**, and a dismissal is respected — recorded per tenant, not per session.
- **At most once per N days** (config, not code) while undismissed and inactive.
- **Never** to a tenant with no completed sales, whatever the config says.

## The open questions, answered 2026-10-12

All four were blocking. Three are now settled against Stripe's own docs.

- **Tax Settings API on Standard OAuth — readable by the platform?** **YES.** `GET /v1/tax/settings` with
  `Stripe-Account: acct_…` and the platform key. Stripe's Connect-platform guidance describes exactly
  this: *"Complete this check when the Standard account configures Stripe Tax through the Stripe
  Dashboard but your platform needs to assess if Stripe Tax can be enabled."* Phase 1 is therefore the
  normal path, not the degraded one.
- **Status vocabulary.** `active` or `pending`, with `status_details.pending.missing_fields` naming what
  is absent (e.g. `["head_office"]`). We add our own `unknown` for *"we asked and could not find out"* —
  never shown as "no tax due".
- **A webhook instead of polling.** `tax.settings.updated` exists and fires *"when accounts update their
  tax settings **or when new required tax settings are introduced**"* — the second case polling on a TTL
  would miss for as long as the TTL. Needs *Listen to events on Connected accounts*, which this
  integration already has for `account.updated`.
- **Does Stripe email the account holder on threshold alerts?** STILL OPEN. Phases 3–4 still rest on the
  assumption that it does, so our email must stay off the subject of thresholds.

### The trap this plan predicted, confirmed

> *"never send `automatic_tax[enabled]=true` unconditionally … it risks producing no session at all
> rather than a tax-free one"*

Correct. `automatic_tax` fails on a `pending` account, which is why `tax_status.calculates()` — and
nothing else — decides whether we send it, and why the retry ladder drops it rather than losing the sale.

Two things the plan did not know:

1. **With no registration for the buyer's location Stripe returns ZERO tax, not an error.** So an
   active-but-unregistered tenant is safe: a $0 tax line, not a broken checkout. The screen says so, because
   an unexplained $0 reads as a bug.
2. **A second condition is needed, and it is ours rather than Stripe's.** Stripe: *"`defaults.tax_code`
   and `defaults.tax_behavior` are only required if not provided in the product or price on each API
   call."* **This codebase never sets either on a Price** — only shipping rates carry them
   (`domain/shipping_charges.py`). So the account default is not optional here, and `may_enable` requires
   it. Without that check a tenant could switch tax on, have every session fall down the fail-open
   ladder, and collect nothing while the screen said "Calculating" — **a silent failure dressed as
   success**, which is the worst outcome available. It gets its own screen state: Stripe says active, we
   say "One setting left", and we name the setting.

## What was built

- **`domain/tax_status.py`** — pure. `from_settings`, `apply_settings` (shared by the screen read and the
  webhook, exactly as `bnpl.apply_capability_statuses` is, so the two cannot refresh differently),
  `may_enable`, `calculates`, `describe`. **All the copy lives here**, not in the Vue component: a
  sentence about a tenant's tax carries legal risk, and one that exists only in a template is one nobody
  can test. A test forbids `nexus`, `you owe`, `must register`, `compliant`, `liable` across every state.
- **Folded onto `/payment-methods`**, both verbs, rather than taking a route — it belongs on that screen
  and the stack is near the 1MB transform ceiling (`plans/TRANSFORM_BUDGET.md`). A body key costs nothing.
- **No entitlement gate**, unlike BNPL beside it. A tenant on any plan owes the tax they owe; putting
  compliance behind a paywall would be indefensible.
- **Cached on `stripe_keys` per mode** (`payment_methods.tax`), beside the BNPL toggles. Checkout reads
  the doc it already fetched for credentials, so **the buyer's path gains no round trip** — the plan's
  rule that a tax lookup must never sit inside checkout.
- **A failed status read never clears a good status.** A momentary outage would otherwise flip a
  calculating tenant to `unknown` and silently drop tax from their next sale.
- **A lapse never clears the tenant's intent.** `calculates()` stops sending `automatic_tax` by itself,
  so their choice waits for them instead of appearing to have been switched off by us.
- **Every sale path that can carry tax, does**: `checkout`, `cart_checkout` (a cart owes the same tax) and
  `booking` (a booked service is a sale). `booking` was moved onto the shared retry ladder so a tax
  failure costs the tax and not the booking.
- **`create_checkout_session_with_bnpl_fallback` renamed to `create_checkout_session_with_fallback`**,
  since tax is now a rung and `booking.py` offers no installments at all.
- **`tax.settings.updated`** refreshes the cache, writing only on a real change.
- **Reports shows "Sales tax collected"** — see `plans/MONEY_ACROSS_SILOS.md`. `summarize` had returned
  `tax_liability` since tax was first captured and nothing displayed it.

### Not covered, deliberately

**Post-purchase upsells.** `handlers/upsell.py` charges a `PaymentIntent` directly, and `automatic_tax`
is a Checkout-Session/Invoice feature — a PaymentIntent has no such parameter. Taxing an upsell needs the
Tax Calculation API and a decision about who bears a mis-calculation, which is its own piece of work. A
tenant with tax on therefore collects it on checkouts, carts and bookings, and **not** on one-click
upsells. Worth stating to a tenant before it is worth building.

## Phases

1. **`domain/tax_status.py`** + the Tax Settings read, cached. Pure interpretation, testable, no UI.
   Includes the degraded "cannot tell" path, because on Standard OAuth that may be the normal one.
2. **The status row + deep link** on the Payments screen. Ships value on its own and cannot fail.
3. **The in-app notice** on the existing notifications rail, with the dismissal and frequency rules.
4. **The email**, on the 15-minute sweep, gated on the same rules as the notice.
5. **The embedded monitoring panel**, only if Standard support verifies. Otherwise this phase is deleted, not
   deferred — the deep link already did the job.

Phase 2 is the one that matters most and is a day's work. Everything after it is a nudge, and a tenant who
opens the Payments screen has already been told.

## What this will NEVER do

Determine nexus. Create or modify a tax registration. State or imply that a tenant is compliant, or that
they are not. Email a threshold alert. Those are Stripe's job, the tenant's job, or their accountant's —
and the cost of being confidently wrong about any of them is borne by the tenant, not by us.

**Amended 2026-10-12:** this list used to include *"Enable `automatic_tax` on a tenant's behalf"*. It now
reads **never enable `automatic_tax` except at the tenant's explicit instruction, and only while Stripe
already reports their account active.** Sending it is not a claim about their liability — it is asking
Stripe to apply a configuration the tenant built in their own Dashboard. The thing the old wording was
protecting against is still forbidden: we never turn it on for them, never infer that they want it, and
never present the switch to an account Stripe has not already accepted.

## When `automatic_tax` is eventually wired — DONE 2026-10-12

Kept as written, because every word of it held up. **never send `automatic_tax[enabled]=true` unconditionally.** For a
tenant who has not set tax up it risks producing no session at all rather than a tax-free one, and every
tenant is in that state today. Gate it on a verified-active status and fail open — an uncollected tax is
recoverable and the tenant can be told; a refused checkout is revenue that never arrives. Same shape as the
`application_fee_percent` trap in `plans/SHIPPING_CHARGES.md`: a platform-level assumption about a per-tenant
setting, invisible until it fires.

Once it IS on, the order must capture `total_details.amount_tax` **and** `shipping_cost.amount_tax`
separately, and feed the ledger's `tax` component.

**Status 2026-10-12:** `total_details.amount_tax` is captured (`order_record_from_session`), the invoice
path captures `invoice.tax`, and both reach the ledger's `tax` component through
`sale_entry_from_order` — so `tax_liability` is no longer structurally zero and Reports now shows it.
**`shipping_cost.amount_tax` is still NOT captured separately**; shipping rates already accept
`tax_behavior`/`tax_code`, so the tax on postage is calculated by Stripe and lands inside the order's
total tax without being attributable to shipping. That makes shipping margin slightly understated for a
tax-collecting tenant, and it is the next thing to fix here.

## Open

- ~~**Tax Settings API on Standard OAuth**~~ — **answered YES, 2026-10-12.** See above.
- **Embedded components on Standard OAuth** — supported? Determines phase 5 exists at all. Still open, and
  now lower value: the deep link ships and the switch works without it.
- **Does Stripe email the account holder on threshold alerts, and by what channel?** Determines whether our
  email must avoid the subject entirely (the assumption above) or merely defer to it.
- **Tax on postage is not attributed to shipping.** See the section above: it inflates product margin and
  understates shipping margin for a tax-collecting tenant.
- **Upsells are untaxed.** `handlers/upsell.py` charges a PaymentIntent, which has no `automatic_tax`.
  Needs the Tax Calculation API and a decision about who bears a mis-calculation.
- **Tenant email preferences.** There is no platform→tenant notification preference today; `mailer` has a
  tenant signature toggle and nothing about which account emails a tenant wants. A tax nudge is arguably
  transactional, but the first platform→tenant nudge is the moment to decide.
