# Sales Tax — surface Stripe's, never rebuild it

**Status: planned, nothing built · Written 2026-09-30.**

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
- **pending / incomplete** — the tenant started and did not finish. That is the most valuable nudge of all.
- **absent / unreadable** — say nothing about their liability; say only that no tax is being collected.

**VERIFY before relying:** the exact Tax Settings API response shape, and whether a **Standard OAuth**
connected account permits the platform to read it at all. If it does not, the status row degrades to
"we cannot tell — check your Stripe settings", which is still better than silence. This is the same open
question already recorded in `plans/TODO.md` for the embedded components.

### 2. A status row on the Payments screen — not a toggle

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

Determine nexus. Create or modify a tax registration. Enable `automatic_tax` on a tenant's behalf. State or
imply that a tenant is compliant, or that they are not. Email a threshold alert. Those are Stripe's job, the
tenant's job, or their accountant's — and the cost of being confidently wrong about any of them is borne by
the tenant, not by us.

## When `automatic_tax` is eventually wired

Recorded here so it is not rediscovered: **never send `automatic_tax[enabled]=true` unconditionally.** For a
tenant who has not set tax up it risks producing no session at all rather than a tax-free one, and every
tenant is in that state today. Gate it on a verified-active status and fail open — an uncollected tax is
recoverable and the tenant can be told; a refused checkout is revenue that never arrives. Same shape as the
`application_fee_percent` trap in `plans/SHIPPING_CHARGES.md`: a platform-level assumption about a per-tenant
setting, invisible until it fires.

Once it IS on, the order must capture `total_details.amount_tax` **and** `shipping_cost.amount_tax`
separately, and feed the ledger's `tax` component — which nothing writes today, so `tax_liability` is
structurally always zero (`plans/TODO.md`).

## Open

- **Tax Settings API on Standard OAuth** — readable by the platform? Determines phases 1 and 5.
- **Embedded components on Standard OAuth** — supported? Determines phase 5 exists at all.
- **Does Stripe email the account holder on threshold alerts, and by what channel?** Determines whether our
  email must avoid the subject entirely (the assumption above) or merely defer to it.
- **Tenant email preferences.** There is no platform→tenant notification preference today; `mailer` has a
  tenant signature toggle and nothing about which account emails a tenant wants. A tax nudge is arguably
  transactional, but the first platform→tenant nudge is the moment to decide.
