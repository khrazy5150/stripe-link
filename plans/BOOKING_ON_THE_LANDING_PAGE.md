# Booking from the tenant's page, not from a link

Proposed 2026-11-10, after the booking flow ran end to end in production for the first time. Design only
— no code yet. The author's framing: *"a customer should be able to come to the tenant's website and
click a booking button."* Today the only way in is a URL somebody has to send them, which is not a
website; it is a link.

## What already works (proven in prod 2026-11-10, not assumed)

The whole booking spine is live and was exercised against a real Google account:

| | Evidence |
|---|---|
| Availability from the tenant's working hours | 08:00–17:36 Denver, 16-minute grid |
| The tenant's own calendar blocks slots | a 13:20→15:12 hole from a real event |
| A booking writes to the **app-created** calendar | `calendar_id: 183b00fa…`, not `primary` |
| Google accepted the write | `event_id: o84t29ot6t1hifpe0b3qcomh1c` |
| The booking blocks its own slot | 31 → 30 slots; 16:00 withdrawn |

So this plan adds no scheduling logic. It is about the **entry point**.

## What already exists, and must be reused rather than rebuilt

**The data model is further along than its own plan says.** `SERVICES_IN_OFFERS.md` is marked
"proposed — no code yet", but:

* `validate_offer_item` already enforces *"exactly one of `product_id` or `service_id`"*, and already
  validates `booking_flow` ∈ {`book_then_pay`, `pay_then_book`} on the item.
* The renderer already has `render_service_price_card`, and emits `data-service-id` on price options.

So an Offer can already carry a service and the page can already render its price. **Nothing in the
model needs changing to put a service on a landing page.**

## The actual gap: the CTA means "buy", and a scheduled service cannot be bought in one click

The page's call to action is a checkout button. For a `no_booking` service that is correct. For a
`scheduled` one it is wrong in both directions:

* **book_then_pay** — the customer must choose a time BEFORE any payment. A checkout button skips the
  only step that matters.
* **pay_then_book** — payment comes first, but the appointment is then `awaiting_schedule` and the
  customer must be handed somewhere to pick a time. Today nothing does that from a page.

This is the one real decision in this plan, and it belongs with `LANDING_PAGE_CTA_AND_COMPOSITION.md`,
whose principle is that **`offer.presentation.cta` drives the per-type CTA**. A booking CTA is a new
member of that family, not a special case bolted onto checkout.

## Shape to build (for review, not yet agreed)

1. **A `book` CTA type** in the composition layer, selected when the item is a service whose
   `fulfillment_mode` is `scheduled`. Derived, not configured: a tenant should not be able to put a
   "Buy now" button on something that cannot be bought in one click.
2. **The slot picker on the page itself**, not a redirect. The booking page already renders slots
   server-side; the same markup can be a section of the landing page, so the customer never leaves. A
   redirect is the fallback if that proves heavy, not the goal.
3. **`pay_then_book` returns to the page**, not to a dead end. After checkout the customer lands back on
   a scheduling step for the appointment they just paid for (`awaiting_schedule` already exists in the
   appointment model and already skips the time fields, so the state is modelled).

## Loose ends found today that this should not inherit

* **`?mode=` cannot survive a customer.** `/book/{service_id}` 404s without it, because
  `resolve_stripe_mode` defaults to `test` — a correct fail-safe that makes the bare URL useless. A page
  reached through a **Site hostname** must resolve the mode from the Site, the way published pages do,
  rather than from a query string the customer can lose. Any on-page booking must take the Site's mode,
  never a parameter.
* **Nothing surfaced the booking URL** until 2026-11-10. The page had existed and worked for months and
  the author had never seen it. Whatever this builds must be reachable from the dashboard by someone who
  does not already know it exists.
* **An unpaid `book_then_pay` appointment holds its slot forever.** Nothing chases or expires it. Putting
  booking on a public page multiplies that exposure, so expiry should be decided before, not after.

## Open questions for the author

1. **One service per page, or several?** A landing page can carry several offer items. Several bookable
   services means several pickers, or a chooser before the picker.
2. **Does the page show a picker inline, or a button that opens one?** Inline is fewer steps; a button
   keeps the page short and is closer to how the CTA family works today.
3. **What happens when nobody can take the work?** The slot engine already answers
   `{"reason": "no_available_fulfiller"}` when every candidate's calendar is broken. On a landing page
   that has to become something a customer can read without being told the tenant's staffing problems.
