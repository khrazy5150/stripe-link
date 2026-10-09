# The textable voucher — a card terminal that is a link

**Status: NOT BUILT. Proposed 2026-10-09 from a client request.** The capability already exists; what is
missing is presentation and one field.

## What the client actually needs

A cash-only service business — no POS, no card terminal. She wants to take card payments without buying
hardware or opening a merchant account. The request arrived as *"a textable coupon"*, which is the
marketing wrapper, not the need.

The sequence, once unpacked:

1. She texts a link. It shows her business, the service, and a discounted price (`Regular $80 /
   Voucher $70 — $10 off`) with an expiry.
2. The customer comes in and **has the service**.
3. **Afterwards**, they open the same link and pay by card from their own phone.

Only customers who want to pay by card use it. Cash customers are untouched.

## Why the order of events matters more than it sounds

The first reading of this was payment-BEFORE-service, which carries two real problems: a redemption
story (what stops a screenshot being reused, what does staff check) and chargeback exposure on something
not yet delivered. **Payment after service dissolves both.** Paying IS redeeming — there is nothing to
verify, because she watches it happen. And she has already delivered, which is how services normally
settle.

One risk replaces them: **walk-out**. She has done the work and the customer can leave without paying.
That is the same exposure a card terminal has and the same mitigation — do not hand the phone back until
it says paid. It is worth saying to her out loud, because cash never had that gap.

**One link does both jobs.** It advertises beforehand and collects afterwards; the page does not care
when it is opened. An earlier draft of this proposed splitting it into a marketing coupon and a separate
payment request. That was wrong — the combined artifact is what makes the flow work.

## Almost all of it exists today

| the request | what already exists |
|---|---|
| textable URL | published landing page on a free `*.jbay.be` host — no domain needed |
| business name and address | business profile NAP, rendered with `LocalBusiness` structured data |
| the exact service | Service, reaching an Offer through `linked_product` |
| `Regular $80 / Voucher $70` | `offer.discount` (`type`, `value`) |
| **"smart"** — pay from the link | `buy` CTA → Stripe Checkout |
| **"dumb"** — a flyer | `call` CTA — `tel:` button plus a top phone banner |
| she sees the payment land | checkout fires a tenant notification |

**"Dumb" and "smart" are a CTA type the composition design already enumerates** (`buy`, `call`, `email`,
`external`, `booking`). The client has described a toggle that is already designed for other reasons.

Offer her `booking` as a third option: for a service business, *"book your discounted appointment"* beats
*"come to the shop"*, and the inline calendar exists.

## What is genuinely missing

**1. Expiry, with server-side enforcement.** `offer.context` is a deprecated enum (`sale`, `flash_sale`)
with no date. A voucher needs a real `expires_at` that renders on the page and **refuses checkout after
it passes** — refusing in the UI alone is not refusing.

Subtlety worth settling with the client: the expiry governs *when they must come in*, not *when they may
pay*. Someone who had the service on the last valid day must still be able to pay afterwards. A single
hard cutoff on checkout would strand them at the counter having already been served — the worst possible
moment for a rejection.

**2. Compare-at display.** The discount exists as data; rendering `~~$80~~ $70 — save $10` is a change to
the one shared price card.

**3. Nothing else.** This is days of work, not weeks, and most of it makes existing systems better.

## How to build it

**Not as a new document type.** `Coupon` already means something specific and unrelated here: a
Stripe-first discount CODE with `stripe_coupon_id` and `redemption_count`, typed at checkout. A second
thing called "coupon" would make every future conversation ambiguous and would show two different
Coupons in the tenant UI. **Call it a voucher.**

Build it as a **goal** in the existing composition system (`plans/GOAL_COMPOSITION.md`: offer_type × goal,
chosen in a wizard step, pulling capability packs). A `voucher` goal seeds the headline, the compare-at
block, the NAP, the expiry and a default CTA from elements that already exist.

## Sequencing, and what to do first

**Get her live on what exists before building anything.** Stripe connected, service priced, page
published, link texted. A day of her time, none of yours, and it proves the money works for her before
any of the above is written.

Two things to warn her about, both learned the hard way on 2026-10-07/08:

- **Stripe is the merchant account.** No bank relationship, no hardware, no monthly fee, self-serve. If
  "I need a merchant account" is what stopped her, that advice is a decade out of date.
- **Stripe will verify her**, and a cash-only business often has loose ends — no registered entity, a
  home address, an unused EIN. Walk her through onboarding BEFORE she promises customers anything. A
  capped or paused account mid-campaign is far worse than a delayed start.
- **The fees are visible on a small ticket**: ~2.9% + 30¢ is about $2.33 on a $70 service, plus the
  platform fee, and a refund returns none of Stripe's share. Say it plainly to someone used to cash.

## One dependency to watch

`plans/SERVICES_IN_OFFERS.md` is design-only. A service reaches an offer today through the
`linked_product` workaround that plan exists to retire. Selling a service by link works, but it is built
on a seam that is scheduled to move — worth knowing before promising a lot of this.

## Related

- `plans/LANDING_PAGE_CTA_AND_COMPOSITION.md` — the CTA types that make "dumb" and "smart" a toggle
- `plans/GOAL_COMPOSITION.md` — where a `voucher` goal belongs
- `plans/SERVICES_IN_OFFERS.md` — the dependency
- `plans/BUSINESS_PROFILE_AND_GBP.md` — the NAP the voucher displays
