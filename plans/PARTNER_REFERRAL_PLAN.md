# Junior Bay Partner Program

**Status:** design locked, not built. Raised 2026-09-06.

## What this is

Not an affiliate program. A **tenant-powered distribution network**: every merchant on Junior Bay can
become an acquisition channel, and is rewarded from the economic activity they create.

The distinction is not cosmetic. "Affiliate" sets the expectation of *send traffic, maybe collect $19 if
somebody subscribes*. What is actually on offer is a share of the platform revenue a partner brings in —
closer to a revenue-sharing partnership, and it produces a different object in the tenant's head. They are
not holding a link. They are building an income-producing referral asset.

The naming matters downstream: dashboard copy, terms, and the destination page should all say **Partner**,
never *affiliate*.

## The economic principle

**Junior Bay pays only when Junior Bay is paid.**

Commission is a share of *collected platform fees*, not of GMV and not a per-signup bounty.

| Referred tenant does | Platform fee (5% physical) | Partner at 20% |
|---|---|---|
| $0 (signed up, never sold) | $0 | **$0** |
| $500/mo | $25 | $5/mo |
| $2,000/mo | $100 | **$20/mo** |
| $10,000/mo | $500 | $100/mo |

Two properties fall out of this and both are worth protecting:

**Fraud is self-defeating.** A fabricated tenant that never sells generates no platform fee and therefore
no commission. The thing being paid on is the same thing that proves the referral was real, so the program
needs far less anti-abuse machinery than a bounty model would.

**Acquisition cost scales with revenue, never ahead of it.** There is no cohort of referrals that costs
money before earning any.

## Locked decisions

| Decision | Value |
|---|---|
| Name | Junior Bay Partner Program |
| Commission base | Collected platform fees (excludes Stripe fees, tax, refunds, chargebacks) |
| Rate | **20% for the first 12 months, then 5% lifetime tail** |
| Clock starts | The referred tenant's **first qualifying sale** — not signup |
| Attribution | **First touch wins**, 30-day capture window, permanently stamped at registration |
| Reassignment | Never. Attribution is immutable once set |
| v1 redemption | Junior Bay account credit only. No cash |
| Architecture | Cash-capable from day one, cash *disabled* |
| Credit threshold | None for credit. A future cash rail gets a $50 minimum |
| Email footer | Stays clean. The referral code is invisible to the recipient |

### Why a declining tail rather than a 12-month cliff

A hard 12-month cutoff is financially tidy and feels arbitrary to the person it happens to. A partner who
brought in a $20k/month store watches the income stop on an anniversary for no reason they can perceive.

The tail solves it: **20% for twelve months, then 5% for as long as that tenant keeps selling.** It keeps a
large initial incentive, removes the cliff, gives partners a reason to keep sending customers rather than
treating each referral as a one-year annuity, and still caps the aggressive rate to a predictable window.

The tail is a *share of Junior Bay's own fee*, not of the merchant's revenue — 5% of a $500 platform fee is
$25, not 5% of $10,000. That is a small marginal cost for potentially permanent distribution.

**Accounting note:** the 5% tail is a perpetual, unbounded obligation against every future dollar a
referred tenant generates. It is small per tenant and it never expires. It should be modelled as
contra-revenue from the start rather than discovered later.

## Attribution and commission eligibility are two different things

Conflating these is the mistake that makes referral systems unexplainable. Model them separately.

**Attribution** answers *who gets credit for bringing this tenant?*

```
tenant.referred_by = "partner_abc123"     # write-once, set at registration, never changes
tenant.referred_at = 1788716851
```

**Commission eligibility** answers *when does the revenue-sharing obligation begin and end?*

```
commission_start = first_qualifying_sale_at    # not signup
tier_20_ends_at  = commission_start + 12 months
tail_rate        = 0.05                        # applies indefinitely thereafter
```

A tenant is attributed the moment they register. They become *commissionable* only when they first sell
something real. The gap between the two is where a merchant is still building their store, and starting a
12-month clock during that period would burn the partner's window on setup time.

### The qualifying-sale rule

A sale qualifies when it is: **live mode**, successfully captured, and generated a non-zero platform fee.

- **Live mode only.** Ledger entries already carry `mode`; test-mode sales generate no real fee and must
  never start a clock or accrue commission. This is a filter that is easy to forget and produces
  fabricated commission if missed.
- **The clock does not reset.** If the first qualifying sale is later refunded, the commission on that sale
  reverses, but `commission_start` stands. Otherwise the start date becomes non-deterministic and
  recomputable, which makes every downstream balance unauditable.

## Data model

### Partner identity

Lives on the tenant profile. Every tenant is a potential partner; no separate enrolment object in v1.

```
referral_code        "KEITH123"        # short, human-typable, unique, case-insensitive
referred_by          "partner_abc123"  # WRITE-ONCE
referred_at          epoch
commission_start     epoch | absent    # set on first qualifying sale
```

**`referred_by` must be server-controlled.** `register_tenant` in
[registration.py](../src/handlers/registration.py) currently persists the POSTed body more or less as it
arrives. A client could stamp any partner it likes, or change it later through a profile update. The rule:
the field is accepted only at registration, only after resolving the code to a real partner, only if it is
not the registering tenant, and is rejected on every subsequent write.

### Commission entries

These belong in the existing append-only
[ledger](../src/stripe_link/repositories/documents.py#L706) — it is already per-tenant, idempotent by
deterministic entry id, and already records `platform_fee` on every sale. No new financial primitive is
needed.

```
le_commission_<payment_intent>            # accrual, on the PARTNER's ledger
le_commission_reversal_<refund_id>        # clawback, proportional
```

**The architectural exception worth naming:** a commission accrues to the *partner's* ledger from the
*referred tenant's* sale. The webhook runs in the referred tenant's context, so this is the one write in
the system that deliberately crosses a tenant boundary. Every other write is tenant-scoped and the
isolation is load-bearing. This needs to be an explicit, reviewed exception with its own tests — not an
incidental consequence of passing a different `tenant_id` to a repository.

### Partner balance

Do **not** build `commission → credit`. Build:

```
commission
    ↓
Partner Balance
    ├── Junior Bay credit   (v1: enabled)
    └── Cash payout         (v1: disabled, schema present)
```

The balance is derived from ledger entries, not a mutable counter — same discipline as the rest of the
financial model. Adding a cash rail later then changes redemption only, never the commission engine.

## The redemption problem — the sharpest unresolved issue

"Credit offsets platform fees" does not work the way it sounds, and this needs deciding before anything
is built.

Platform fees are collected by Stripe as `application_fee` **atomically at charge time**. There is no
mechanism to retroactively reduce a fee that has already been taken, and reducing a tenant's *rate* to
work off a balance would make their effective pricing unpredictable and hard to reconcile.

What credit can cleanly pay:

- **A Premium subscription invoice.** Stripe supports customer balance credits natively, so this is a real
  mechanism, not a workaround. It is also the conversion moment described below.
- **Future Junior Bay purchases** — marketplace inventory, Attention features — once those bill through
  something invoice-shaped.

What it cannot cleanly pay in v1: the transaction fees of a free tenant who never upgrades.

**This leaves a real gap.** Free tenants are the ones most motivated to refer, and in v1 a free tenant who
never upgrades accrues credit with nothing to spend it on. Three ways to resolve it, and the choice is a
product decision, not an engineering one:

1. **Accept it, and treat credit as an upgrade driver.** Dead credit is the point — it converts.
2. **Periodic rebate** against fees already collected. Honest, but it is cash by another name and brings
   the payout rail forward.
3. **Enable cash earlier** for partners with no billable surface.

My recommendation is (1) for v1, stated plainly in the partner terms so nobody discovers it later — with
(3) as the natural second step once there is evidence anyone earns enough to care.

### The conversion mechanism this unlocks

Once credit pays the subscription, the upgrade prompt stops being a pitch:

```
Premium                 $19.00 / month
Referral credit        −$14.72
Your cost               $4.28 / month
```

and eventually

```
Referral credit        $31.40
Premium                $19.00
Covered — with $12.40 remaining
```

"Your referrals just paid for Premium" is a materially different message from "Upgrade to Premium".

## Fraud rules

Revenue-based commission removes most of the incentive, so v1 needs rules rather than a detection system:

- No self-referral, direct or indirect
- No circular or ring referrals — a tenant cannot earn on itself through any chain
- No reassignment after attribution
- No commission on refunded or charged-back transactions (proportional reversal)
- No commission on transactions between related or commonly-controlled tenant accounts
- Junior Bay may reverse commission associated with fraudulent activity

The circular case (A refers B, B refers A) is the only one needing real logic: walk the referral chain at
accrual time and refuse if the partner appears in the referred tenant's own upstream. Chains are short and
the walk is cheap.

## Distribution surfaces

The referral identity is one code; the surfaces are many:

- **Email footer** — the highest-context surface. The recipient has *just completed a purchase* from a
  small business running on Junior Bay. They are not reading an ad; they are noticing infrastructure that
  visibly works.
- Personal link: `juniorbay.com/?ref=KEITH123`
- Website, blog, social bio, YouTube description, newsletter, community posts
- Invoices, business cards, QR codes
- "Powered by Junior Bay" links on published pages

### The footer must change — and it is a reversal of what shipped today

What is live as of 2026-09-06 is promotional:

> Want to start your own online store? **Try it for free**

That is too much to put on someone's *customer's* receipt once it also earns the merchant money. The
footer should become quiet:

> Powered by Junior Bay

The referral code rides in the link, invisible to the recipient. The *destination page* does the selling,
and can be referral-aware:

> This store is powered by Junior Bay. Want to build your own?

This keeps the tenant's customer experience clean and moves the pitch to a page whose entire job is to
pitch — where it will convert better anyway.

**Premium tenants have no footer**, having paid to remove it, so their only surface is the deliberate link.
That is correct and worth stating in the partner UX rather than letting them wonder where their footer
went.

### Disclosure

Once a tenant earns compensation from the link, the financial relationship is a material connection under
current FTC guidance, and affiliate relationships are expected to be disclosed clearly and conspicuously
where a consumer would not otherwise understand them. Whether a quiet "Powered by Junior Bay" on a receipt
crosses that line is a judgement call about the exact wording, not something to reason out from first
principles here. **Have counsel review the final footer copy and the partner terms before launch** — the
cost of asking is an hour; the cost of assuming is a regulatory problem attached to every tenant at once.

## Partner dashboard

Not "Referrals: 12 / Earned: $437". The dashboard's job is to make the referral network feel like an
asset, which means showing the network, not just the payout.

```
Your referral link          juniorbay.com/?ref=KEITH123

Referred tenants                    24
Active stores                       17
Stores generating revenue           11
Referred GMV                   $38,420
Junior Bay revenue generated    $1,421
Your commission                   $284
Available credit                  $284
```

| Store | Status | Monthly JB revenue | Your share |
|---|---|---|---|
| Store A | Active | $42 | $8.40 |
| Store B | Active | $116 | $23.20 |
| Store C | New | $0 | $0 |
| Store D | Active | $318 | $63.60 |

**The metric that matters most is "Junior Bay revenue generated", shown beside the partner's share.** It
says something no commission figure says on its own: *I am helping build this, and they are sharing the
upside with me.* That is a different relationship from vendor and customer, and it is the most valuable
thing the program produces.

Privacy boundary to settle: how much of a referred tenant's performance a partner may see. Showing exact
GMV per store exposes another business's revenue to a third party. Showing *Junior Bay revenue generated*
(the commission base) is defensible because it is the partner's own earnings basis. **Referred GMV per
store is probably too much and should likely be aggregate-only.**

## Open questions

1. **Redemption gap for free tenants** — options above; needs a product decision.
2. **Per-store GMV visibility** — aggregate only, or per-store?
3. **Does the referral code survive the signup round-trip?** Attribution is captured client-side on a
   static homepage, then must survive the auth redirect into `register_tenant`. If that flow round-trips
   through a hosted auth UI, query parameters can be dropped. **This must be verified against the real
   flow before anything else is built** — it is the single point where the whole chain silently breaks,
   and a broken attribution chain looks exactly like "nobody referred anyone".
4. **Cross-device attribution** — someone who clicks on a phone and signs up on a laptop loses the
   attribution. Accept it; do not build identity-stitching for v1.
5. **Code format and collision** — short and human-typable pulls toward collisions; needs a generation
   rule and a uniqueness guarantee.

## Phasing

**P1 — Attribution.** Referral code on the tenant profile, `?ref=` capture with a 30-day window, survival
through signup, write-once `referred_by`. Nothing else works without this, and question 3 is resolved here.

**P2 — Commission engine.** Qualifying-sale detection, accrual and proportional clawback as ledger entries,
the cross-tenant write exception, mode filtering, the referral-chain check.

**P3 — Partner balance and credit.** Derived balance, credit applied to the Premium invoice, the upgrade
screen showing credit against the subscription price.

**P4 — Partner dashboard.**

**P5 — Footer becomes referral-aware** and reverts to the quiet wording. Nearly free once codes exist,
which is why it comes last rather than first — the temptation is to ship the visible part before the
accounting is trustworthy.

**Later — cash payout rail**, $50 minimum, only if partners actually accumulate balances worth paying out.

## Why this is bigger than a referral program

Three things converge:

- Every tenant has customers, and some of those customers are latent entrepreneurs
- Every tenant now has an incentive to bring more tenants, because referrals produce recurring value
- Junior Bay already intends to help tenants acquire attention
  ([ATTENTION_PRIMITIVE.md](ATTENTION_PRIMITIVE.md))

```
                    JUNIOR BAY
                        │
          ┌─────────────┼─────────────┐
          │             │             │
       Commerce      Attention      Referrals
          │             │             │
          ▼             ▼             ▼
      Sell stuff    Get traffic   Get tenants
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                 Earn Junior Bay
                     credits
```

Credit earned in one arm is spendable in the others, which closes the loop: the program stops being a
payout channel and becomes the platform's internal economy. That is the version worth building toward, and
it is reachable from the v1 above without rework — provided the Partner Balance is a real abstraction from
day one rather than a credit counter that later has to become one.

## Related

- [PLATFORM_PLANS.md](../docs/PLATFORM_PLANS.md) — tier definitions the commission rate sits beside
- [TENANT_SENDER_IDENTITY.md](TENANT_SENDER_IDENTITY.md) — the email footer this program repurposes
- [ATTENTION_PRIMITIVE.md](ATTENTION_PRIMITIVE.md) — the other arm of the flywheel
- [SAAS_BILLING_PAYWALL.md](SAAS_BILLING_PAYWALL.md) — the invoice surface credit would pay against
