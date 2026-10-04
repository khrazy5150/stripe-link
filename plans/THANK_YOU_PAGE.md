# The Thank-You page tells the truth about shipping

## The problem

The thank-you page's "What's Next?" cards are static strings baked into a default:

```python
{"icon": "📦", "title": "Free Shipping", "desc": "Your order will arrive within 5–7 business days."}
```

Both halves can be false at once. A real order on 2026-10-04 paid **$39.59** to Vancouver and was shown
"Free Shipping"; the 5–7 days was typed by nobody who knew the destination or the service chosen.

A third card, "Start Your Journey", was written as *inspiration* — a worked example for tenants selling
courses, to be edited or deleted. It is being left exactly as shipped, which is what a default always
becomes. Defaults are not suggestions; whatever a default says is what most stores will say.

## It is possible to be exact, and nothing new is needed to find out

| What an ETA needs | Where it already is |
|---|---|
| Per-order data on a page that is a static artifact | The thank-you URL already carries `?session_id=` — the same pattern the upsell island uses |
| Which service the buyer chose | `order.shipping_quote.service_token` |
| Transit days for that service | The stored quote row carries `transit_days_min/max` **per option** |

Measured: `Ground Advantage 5/5`, `Ground Saver 2/2` — min equals max, so an exact date is usually
available rather than a range.

**And every zone type carries transit days,** which was the thing most likely to sink this:

    free           options=1 mode='free'    label='Ground' transit=5-7
    flat           options=1 mode='charged' label='Ground' transit=5-7
    flat_rate_box  options=1 mode='charged' label='Ground' transit=5-7
    live           the carrier's own, destination-specific

A `live` zone gets the carrier's estimate; the others get the days the tenant configured on their own
services. The only case with no ETA at all is an **unmeasured** product, where there is no rate, no
service and no days — by design, since a parcel nobody measured must not produce a price.

## The shape

### `shipping_eta` is its own element, not a card

The author's requirement: *"The shipping element for physical products must be the very first thing that
appears after the headline and subheadline."* So it is a section in its own right, rendered between the
subheadline and the message — not a card inside "What's Next?", which sits below the message and is where
a tenant puts their own copy.

The tenant owns its **icon and title**. The body is generated, which is the whole point: a sentence
nobody can type is a sentence that cannot be wrong.

### What it says

| Case | Card |
|---|---|
| Rated, min == max | *USPS Ground Advantage — due to arrive Wednesday, October 8* |
| Rated, min ≠ max | *USPS Ground Advantage — arriving between Tue Oct 8 and Thu Oct 10* |
| Free zone, or unmeasured product | *Free shipping — we'll email tracking when it ships* |
| Not physical / no shipping | **The element does not render at all** |

"Free" is said in exactly three situations and no others (author, 2026-10-04): the tenant never entered
dimensions and weight, the tenant deliberately chose a free zone, or it is not a physical product — and
the third of those is the one where the element disappears rather than reassures.

### The arrival date

    ship date = order date, or the next business day if placed after the cutoff
    arrival    = ship date + transit days, counting business days only

- **Cutoff: 15:00 by default, tenant-editable** on the Shipping screen. It is a deliberate buffer, not a
  rule: most tenants will still ship same-day and quietly beat the estimate. Setting expectations low and
  exceeding them is the point.
- **Weekends are skipped. Holidays are not modelled** — carriers already fold them into their own transit
  estimates, and stacking our calendar on theirs means being wrong twice. The card says *estimated*.

### Store Timezone

15:00 in whose day? `ship_from_address` carries country, state and postal code but **no timezone**.

A new **Store Timezone** goes in the tenant profile's Business Address section, *inferred from the
address and freely overridable*. The author's reasoning, which generalises past this feature: a tenant may
live in Pacific time but ship from a warehouse in Mountain time, and only they know which one is their
working day. *"Just like everything else in this software, we suggest but don't dictate."*

It is **not** built for this feature alone — Sabbath mode needs exactly the same setting to know when
Friday sundown falls, so it is a store-wide property that happens to be needed here first.

## "What's Next?" becomes the short version of the same story

The element above is the prominent answer. The section below is the **summary**, and repeating the arrival
date inside it is deliberate rather than redundant — it is the line a buyer scans for, and a buyer who
scrolled past the element should still meet it.

The author's shape (2026-10-04), as a brief enumerated summary:

> 1. Look for an email from us …
> 2. Wait for your package to arrive on *{date or date range}* …
> 3. Contact us if you find any issues with your purchase …

**One mechanism, not two.** The card does not get its own `kind`. Card text supports an **`{{arrival}}`
token**, substituted by the same island and the same formatter that fills the element — so the date is
computed once and worded wherever the tenant wants it. A tenant who rewrites the sentence keeps the date;
a tenant who deletes the token keeps their sentence. Adding a second card type that happened to print the
same date is how two implementations of one answer start to disagree, which this codebase has relearned
more than once this month.

When there is no date to put there — an unmeasured product, a free zone — the token resolves to the same
fallback the element uses (*"soon — we'll email tracking when it ships"*) rather than to a blank.

Defaults become those three steps. Tenants add their own, as they always could.

> **Presentation left open.** The existing look is a three-up grid of icon cards, and the steps read as
> steps without numerals. A genuinely numbered list is a different component; worth doing only if the
> author wants the ordering to be visually explicit.

## Also changing

- **"Start Your Journey" leaves the defaults.** Safe to do: `thankYouCopyOverrides` only persists
  `next_steps` when they have been *edited away from* the defaults, so every tenant who left them alone
  inherits the new list and the card disappears. Tenants who edited keep theirs — their data, their
  choice, no migration.
- **The shipping card leaves "What's Next?" too**, since it becomes its own element — but the section
  does not shrink to one card; it becomes the three-step summary above.
- **Card icons get the icon picker.** `showIconPicker` already exists and is already wired for the
  countdown icons; the thank-you editor uses a bare `<input maxlength="4">`. Two call sites, same pattern.

## Preview

The builder has no order, so the element must render a clearly-marked **example** date. Without that, the
first thing every tenant does is report the thank-you page as broken.

## Build order

1. **Store Timezone + the ETA calculator** ✅ *shipped 2026-10-04.* `domain/delivery_estimate.py` is pure
   — order time, cutoff, timezone and transit days in; a date or a date range out, `{}` when it cannot be
   known. `domain/store_timezone.py` suggests from the address and never insists. The open question below
   was settled by measurement before either was written.
2. **The element** ✅ *shipped 2026-10-04.* `shipping_promise.py` builds the promise and is the only
   place that words it; the webhook computes it once at order time and stores `delivery_estimate` on the
   order; `render_shipping_eta` emits a shell that is true without JavaScript, placed between the
   subheadline and the message; an island fills it and substitutes `{{arrival}}` from one fetch.

   Served from the existing `/upsell/session` rather than a new route: the thank-you screen is a funnel
   step, it already calls that endpoint with the same `session_id`, and the stack sits at 94.8% of
   CloudFormation's transform limit — a route costs bytes that should be kept for something which cannot
   be answered anywhere else.
3. **The builder** ✅ *shipped 2026-10-04.* Defaults became the three-step summary (with `{{arrival}}` in
   the middle card), "Start Your Journey" and the "Free Shipping" card are gone, card icons use the shared
   `showIconPicker`, the preview renders a labelled example date, and the cutoff hour joins the timezone
   on the profile.

   A parity test now holds the two default lists together. They are load-bearing in a way that is easy to
   miss: `thankYouCopyOverrides` COMPARES the saved cards against the Vue copy to decide whether to
   persist them, so a drift of one character would make every page store its cards and no future default
   change would ever reach anyone.

## P4 — the promise has to come true (not built)

The thank-you page now says *"Your receipt and tracking details are on the way to your inbox."* Whether
that becomes true depends on a tenant doing something nothing asks them to do.

**The email is not missing.** Both fulfilment paths already send it — `orders.mark_shipped` (the manual
"mark as shipped") and `shipping.buy_label` (automatic, `has_tracking=True`). What is missing is the
trigger:

    shipments recorded: 0

No order has ever been marked shipped or had a label bought, so the email has had nothing to fire on.
That is not a bug, it is an unperformed step — and a buyer who waits for an email that never arrives
contacts support instead, which costs the tenant more than the step would have.

So P4 closes the loop rather than building another email:

1. **Tell the tenant there are orders to fulfil.** The notification bell and its badge already exist and
   already have emitters deferred (`docs/NOTIFICATION_EMITTERS.md`); an unfulfilled physical order is a
   better first emitter than most of what is queued there, because it has a clear action attached — which
   is the bar `feedback_notices_only_when_actionable` sets.
2. **Make the page's promise conditional on the state of the order.** Until a shipment exists there is no
   tracking to promise, and the card can say what is true now ("we'll email tracking when it ships")
   rather than asserting something is already on its way.
3. **Nudge after N days** of an unshipped physical order, as the last resort before the buyer notices.

### The shipment notice revises the date (author, 2026-10-04)

**Yes** — and the delay case is what makes it worth building. *"It may be possible that a tenant who has
run out of inventory had their shipment delayed. So a revised date with a possible tenant explanation
should work."*

The buyer was promised a date computed from an **assumed** ship day. The moment a parcel actually ships,
that assumption is replaced by a fact, and the arrival is recomputed from it:

    revised arrival = actual ship date + transit days of the service ACTUALLY used

Note the second half. The tenant picks a carrier and service on the mark-shipped form, and it need not be
the one the buyer chose and paid for — an upgrade to get a late parcel there on time is exactly the kind
of thing a tenant does. The honest date uses what actually shipped, not what was sold.

**Only call it revised when it changed.** A date that still matches the original is just stated; an
apology for nothing teaches buyers to expect one, and the next real apology is worth less. The same logic
means an EARLIER date is worth sending too — arriving sooner than promised is good news nobody currently
hears.

**The tenant's explanation is optional free text**, carried to the buyer in their own words. "We ran out
of stock and restocked Tuesday" is a sentence only they can write, and it does more than any wording we
could ship.

**A discount coupon is OFFERED, not applied** — suggested only when the date actually slipped, and never
automatic. A goodwill gesture attached to every shipment stops being a gesture, and a tenant who ships
late routinely would bleed margin without ever being asked whether they meant to.

*Either an existing coupon or an ad-hoc one* (author, 2026-10-04). Those look like two features and are
one, because **both routes end in a `coupon_grant`** — the primitive that already exists for exactly this:
*"one recipient's own code for a campaign coupon"*, bound to an email and a Stripe customer, with
`grant_id` equal to the code so checkout resolves it in a single read.

    existing coupon  ->  grant it to this buyer
    ad-hoc coupon    ->  create the coupon, then grant it to this buyer

So there is one issuing path with two sources for the coupon behind it, not two flows to keep in step.

And it should be a GRANT either way, not a shared code. A goodwill gesture is personal, and a public code
in an apology email ends up on a deals site within the week — the grant binds it to the buyer who was
actually let down, and redemption tracking already follows it.

> **Worth deciding when it is built:** an ad-hoc coupon mints a coupon document per apology, and those
> accumulate in a tenant's coupon list where they are noise rather than campaigns. Marking them with their
> origin and hiding them from that screen by default is probably right, but it is a judgement about the
> Coupons screen rather than this one.

**What the order keeps.** `delivery_estimate` holds what the buyer was ORIGINALLY told; the revision
lives beside it rather than overwriting it. Support answering "you said the 12th" needs to see both the
promise and the correction, and a field that quietly becomes the new truth loses the thing that was
actually promised.

**Where it stops.** Once a parcel is with the carrier, tracking is the source of truth and we do not chase
it with further revisions. One correction, at the moment the assumption became a fact.

## Open

- ~~Carrier transit days are business days already~~ **— CONFIRMED 2026-10-04.** Shippo returns a
  `duration_terms` sentence alongside `estimated_days`, and it says so outright:

      ups_second_day_air   estimated_days=2  "Delivery by the end of the second business day."
      ups_next_day_air     estimated_days=1  "Next business day delivery by 10:30 a.m. ..."

  So arrival counts N business days FORWARD from the ship date. Adding N calendar days and then nudging
  off a weekend would push nearly every estimate out by two days; a test holds that line.
- **The confirmation email** is where buyers actually look for a delivery date. The same calculator
  should feed it, and does not yet.
