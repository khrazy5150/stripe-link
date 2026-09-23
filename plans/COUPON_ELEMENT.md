# The coupon element: a ticket on a landing page

**Status: BUILT and deployed dev + prod, 2026-09-22.** Written after the fact, because four places already
referenced this file and none of them had one to point at.

## What it is

A tenant emails a coupon; the recipient taps it and lands on a page showing the same ticket. Tapping it
applies the code, and the discount lands at checkout.

The visual follows the paper coupons it imitates: the picture of what you get on the left, the business
named above the value, the value in the largest type on the ticket, a dashed edge because that is the whole
idiom. **The whole ticket is the control** — someone who tapped a coupon in an email expects to tap the
same shape again, and a small button inside it makes them hunt for the part that works.

## The decisions, and why

### Applying does NOT restate the price

The price card already carries a strike-through and a "Save X%" badge. Recalculating for the coupon adds a
third number and invites "is this before or after my code?". Instead the ticket confirms — a green
**Coupon Applied** with *"Your discount will appear at checkout"* — and the discount lands at payment, the
way an electronic coupon at a supermarket till does (author, 2026-09-22).

It is also the only version that stays TRUE. Stripe decides `first_time_transaction` from the email typed
at checkout, so any figure shown beforehand is a guess we would then have to honour. A test asserts the
apply path touches no amount, so a later "improvement" that recalculates fails loudly.

### It applies to the page, it does not navigate

The first version was a link built at publish from the offer's FIRST item. On a tiered or multi-product
offer that sent every buyer to tier one whatever they had selected — a bug, invisible on a single-product
page. Now the ticket sets page state and the CTA, which already rebuilds its href from the selected card,
carries `coupon=CODE`. The code follows the buyer's choice.

The ticket stays an anchor pointing at a working checkout, with the script intercepting the click, so a
visitor without JavaScript gets the old behaviour rather than a dead ticket.

### Smart by the offer's shape, not by a setting

A transacting offer applies in place. A lead offer — which by composition HAS no checkout — links to the
destination the section names, which is what a bridge page does with its redirect anyway.

### Values are COPIED onto the section, not referenced

Picking a coupon denormalises its code, expiry and value. A published page then keeps the coupon it was
published with, so editing the coupon afterwards cannot silently change what an already-emailed campaign
promised. The cost is that changes do not propagate; the tenant re-picks. For something that goes out in
email, immutability is the right side of that trade.

### An expired coupon still renders

Desaturated and inert, linking nowhere. An email outlives its deadline, and a page with a hole in it reads
as broken. Checkout must never be where a visitor learns the offer ended.

## Two ways to attach one

Mirroring how a Site can come from the Sites screen or from this builder: pick a coupon already made, or
make one inline. Creating goes through `couponsStore.saveCoupon`, the same path the Coupons screen uses —
one shape, one validator, one place to change.

## Bugs this shipped with, all found in QA the same day

Recorded because each is a class, not a one-off:

1. **White-on-white on dark presets.** The ticket paints its own white ground but took its ink from
   `--sl-text`. A colour whose default comes from the host theme, paired with a background that does not,
   is the bug — not the particular colour.
2. **`clientID or tenant_id is required`.** The link was built by appending `?coupon=` to the bare checkout
   URL, which carries no tenant, offer or price. `checkout_context()` is the only thing that knows what a
   checkout link needs. The element's existing test passed throughout, because it asserted the only part of
   the URL I had written myself.
3. **The applied panel showed before any click.** `hidden` is only `display:none` in the UA stylesheet, so
   the panel's own `display:flex` outranked it. Anything given a display must restate `[hidden]`.
4. **The inline form omitted `duration`.** The builder guards are source-greps: they prove the wiring
   exists, not that the payload is complete.

## Not built

- **Product scoping** — which lines in a bundle get discounted. See `plans/COUPONS_COMPLETION.md`; the
  options are recorded and the decision is whether a coupon is an object the tenant owns or a rule they
  write.
- **A `cta_label` field in the element editor.** The default ("Click to redeem this offer") is all a tenant
  gets unless it is set programmatically.

## There is no second renderer

The Live Preview IS the published renderer: the builder POSTs the draft page to `/pages/render`, which runs
the same `render_page()`, and shows the HTML in a `srcdoc` iframe with `allow-scripts`. One JSON, one
renderer, two consumers — so the element needed no preview implementation, and cannot drift into one.
