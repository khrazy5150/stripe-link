# The Shipping Wallet — prepaid postage, and a platform that never fronts money

**Status: planned, nothing built · Written 2026-10-01.**
Follows `plans/SHIPPING_ELEMENT.md` (shipped) and depends on nothing in `plans/IDENTITY_VERIFICATION.md`.

## Why this exists

The author's architecture, 2026-10-01:

    BUYER ──$48.95──▶ STRIPE ──proceeds──▶ TENANT
                                              │ label request
                                              ▼
                                         JUNIOR BAY ──$6.42──▶ SHIPPO/EASYPOST ──▶ CARRIER

    Label purchased ──▶ Tenant Shipping Ledger
                          ├── Actual postage      $6.42
                          ├── JB fee              $0.50
                          └── Tenant liability     $6.92  ──▶ balance ──▶ auto-recharge

**This solves the objection that blocked a shared platform key.** Postage is bought AFTER the sale, when the
buyer's money has already moved, so a platform holding one carrier account would be fronting every tenant's
postage and chasing it afterwards. A prepaid balance inverts that: the tenant's money arrives first and the
platform never carries a receivable.

## Two findings that make this cheaper than it looks

**1. The tenant is ALREADY a Stripe customer on the platform account.** `TenantProfile` carries
`stripe_customer_id` and `stripe_subscription_id`, created by `handlers/platform_subscription.py` for the SaaS
plan. So auto-recharge is a PaymentIntent against an existing customer with a card already on file — not a
billing rail built from nothing.

That matters because `plans/IDENTITY_VERIFICATION.md` concluded the platform needs a **metered** rail
(subscription items, usage records) and called it *"a broadly reusable investment… build that rail first"*.
**A prepaid wallet does not need metering at all.** Usage is debited from a balance we hold; nothing has to be
reported to Stripe per event. So this is the cheaper of the two shapes, not a second customer for an expensive
one — and if the metered rail is ever built for something else, the wallet does not need it.

**2. The ledger already has two of the three numbers.** `domain/ledger.py` has `shipping_revenue` (what the
buyer paid, a partition of gross — shipped) and a `shipping_cost` component plus entry type that **nothing
writes**. This is what writes it. The wallet adds the third: what the tenant paid JuniorBay.

## The distinction that must not blur

Two different transactions, and conflating them would reopen a question already settled:

| | who pays whom | the platform's cut |
| --- | --- | --- |
| **Buyer-paid shipping** (`order.shipping_amount`) | buyer → tenant, through Stripe | **none** — `FEE_APPLIES_TO_SHIPPING = False` |
| **Postage** (`order.shipping_cost`) | tenant → JuniorBay → carrier | **a markup**, the JB fee above |

The platform takes **0% of what a buyer pays for shipping** and **a fee on what a tenant pays for postage**.
Those are not the same money and must never be netted. A tenant charging $8.95 and paying $6.92 keeps $2.03 of
shipping margin; the platform's $0.50 is inside the $6.92, not taken from the $8.95.

Stating it here because `domain/fees.py` already carries the first rule as a loud constant, and a future reader
finding a shipping fee might reasonably think the constant had been reversed.

## What gets built

    domain/shipping_wallet.py     pure: balance arithmetic, the recharge trigger, the liability breakdown
    ShippingWalletTable           balance + an append-only entry per movement
    POST /shipping/wallet/topup   a PaymentIntent on the existing platform customer
    GET  /shipping/wallet         balance, recent movements, the recharge settings

- **The balance is a DERIVED SUM of entries, never a stored number that can drift.** Same discipline as
  `ledger.summarize`: entries are the truth, the balance is their sum. A stored balance and a list of
  movements eventually disagree, and the one people trust is the wrong one.
- **Every movement is idempotent on the label's own id.** `buy_label` already takes an idempotency key; a
  retried purchase must debit once.
- **A voided label credits the wallet back**, which is the clean part of this model: the money returns exactly
  where it came from, with no refund to a card and no reconciliation.

## Auto-recharge, and the failure that matters

A top-up at `$10` is a card charge at the moment a tenant is trying to post a parcel. So:

- **Never silently fail mid-fulfilment.** A declined recharge must surface as *"your card was declined, add
  credit to buy this label"* — at the label button, not in an email tomorrow.
- **Never retry-storm.** One attempt per window, with the next attempt backed off, or a declined card turns
  into a hundred declines and a Stripe risk flag.
- **A floor, not a cliff.** Recharge when the balance would not cover a typical label, rather than at zero —
  otherwise the first failure is always in front of a buyer waiting for a parcel.
- **Manual top-up must always work**, including when auto-recharge is off or failing. The feature cannot be
  the only way to add money.

## What I cannot verify from here, and will not assert

The author's reading of the vendor landscape, recorded as **claims to check** rather than as settled facts:

- *EasyPost Forge*: child-account postage flowing through a parent/platform wallet, and **FlexRate** supporting
  fixed or percentage adjustments to the rates shown to child accounts — which would be the platform margin
  built into the provider rather than bolted on.
- *Shippo*: whether its current platform offering has an equivalent prepaid/centralised billing and merchant
  chargeback mechanism.

**If that asymmetry holds, it is an argument for EasyPost as the platform provider**, and it is worth settling
BEFORE building, because the wallet's shape depends on whether the provider does the margin or we do. I have no
way to read either vendor's current documentation, and vendor terms move; this needs a human to confirm.

The adapter is not the obstacle either way: `ShippingProvider` is a four-method interface and `_request` sets a
single auth header, so a platform key plus a per-tenant account header is a small change. `easypost` is already
in the provider enum and unimplemented.

## Open

- **Stored value and the law.** Holding tenant funds as a prepaid balance is closed-loop (spendable only on
  postage we buy), which is the low-risk end of this, but it is still customer money on the platform's books.
  Worth one conversation with counsel before launch rather than after — naming it because it is the kind of
  thing that is cheap to answer early and expensive to discover late.
- **Who is the shipper of record.** Labels bought on the platform's carrier account make JuniorBay the
  counterparty for claims, insurance and carrier chargebacks. The wallet fixes the cash flow, not this.
- **Blast radius.** One carrier account for every tenant: a suspension stops shipping platform-wide, where
  per-tenant keys isolate it. Prepaid does not change that.
- **A rating-only platform key is a smaller first step** and needs none of the above: quotes cost nothing and
  carry no liability. It would make *Try a rate* work on signup instead of after the three-day wait the author
  hit, and it is the only part of this that could ship without the wallet existing.
