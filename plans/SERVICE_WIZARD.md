# Wizardising the service / booking flow

Raised 2026-09-18: *"When a tenant selects 'I want to sell something' and then selects 'Service', the wizard
incorrectly treats it like a physical product… the booking screen is way too overwhelming… I don't think that
the service screen was ever wired on stripe-link before."*

All three observations are correct. The scope, however, is much smaller than it looks.

---

## 1. What is actually broken

**The wizard lies about what it does.** `Products.vue` offers *"Service — opens booking flow"*, but
`WIZARD_FLOWS` is keyed on **intent** (`transaction` / `lead_gen` / `tip_jar`) and **nothing in that file
branches on `product_type` at all**. Selecting Service runs the identical physical path — package dimensions
included. No booking flow opens because none is wired to open.

**There are two unrelated notions of "service".**

| | `Product.product_type = "service"` | `Service` document |
|---|---|---|
| What it is | a catalog row with a price | duration, fulfillers, calendar, booking rules, check-in |
| Wired? | yes — validator, offers, fee class | yes — own table, own screen, own handler |
| Linked to the other? | **no** | **no** |

The fee side is genuinely correct: `fee_class_for()` routes `service` to its own class, and the *deployed*
`global_billing_config.json` carries `service` in every tier (6% free / 2% pro) — checked, not assumed.

**The Services form asks for ~22 fields to create a 3-field document.** `validate_service` requires
`name`, `price`, `duration_minutes`. The form presents Location Mode, Fulfillment, Booking flow, Fulfiller,
Override Type, Override Amount, Tips go to fulfiller, Compensation Type, Compensation Amount, Default
Fulfiller, Calendar, Check-In Label, Completion Label, Check-In Window Start, Check-In Window End, Check-in
required, Completion required… It is an operations console shown to someone who wants to say *"I cut hair,
£40, 45 minutes."*

This is the same disease the Products wizard already cured, and the same cure applies: **ask for what the
document requires; defer what it merely permits.**

**Nobody has ever used it.** 0 products of type `service` in dev or prod. 0 `Service` documents on prod, 1 on
dev. Nothing to migrate and nobody to disrupt — the cheapest possible moment to fix the shape.

## 2. The part that is NOT broken, and it is most of it

The *selling* half is built and tested. This is not a green field:

- `expand_offer` resolves `service_id` items into priced snapshots (`domain/pricing.py`)
- `checkout.py` loads services and handles service lines
- the renderer touches `services_by_id` in 67 places
- `booking` is a real CTA type with `render_booking_cta`, backed by `handlers/booking.py`
- **59 tests pass** across `test_booking`, `test_booking_page`, `test_services`, `test_services_in_offers`,
  `test_service_landing_page`
- multi-calendar routing shipped to dev+prod (plans/MULTI_CALENDAR_ARCHITECTURE.md P1+P2)

So the question is not "how do we build services". It is **"why can nobody create one?"** — and the answer is
that the only door is a 22-field modal the product wizard never points at.

## 3. The decision that has to come first

**What does "Service" mean when a tenant picks it?** Everything below depends on this and it is the author's
call.

The recommendation: **one concept, two fulfilment modes.** `validate_service` already accepts
`fulfillment_mode: scheduled | no_booking`, and plans/BOOKING_AS_PRIMITIVE.md already reasons about the
distinction (a `no_booking` service is still a service for TAX, not a product). If a Service can be either
bookable or not, then `Product.product_type = "service"` is a third name for a thing that already has two —
and the two-worlds confusion in §1 disappears rather than being papered over.

Consequences to accept if we go that way:
- The product wizard's "Service" option **routes into the service flow** and produces a `Service`, not a
  `Product`.
- `product_type = "service"` is retired from the picker (kept in the validator and the fee table, since
  documents and fee history reference it).
- The fee class keeps working unchanged: it reads `product_type`, and a Service's fee class is resolved the
  same way.

The alternative — keep both, and ask a fourth question ("does this need appointments?") — is more honest to
today's data model and worse to use: the tenant is made to understand our schema in order to sell a haircut.

## 4. The wizard — REVISED 2026-09-18 after the first attempt was wrong

The first build (dev only, commit 796d99d) got two things wrong, and the author named both:

1. **It handed off to the Services screen.** Wrong, because *"when people think of 'product' they think of
   product or service — the labor of one's hands is also a product"*. A tenant looking for where to create the
   thing they sell looks in one place. Sending them somewhere else is our data model leaking into their day.
2. **It hid the console instead of pacing it.** *"If we simply say: here you go… create your service in this
   huge screen, our software loses value."* Hiding fields makes a shallow wizard and leaves the overwhelming
   screen intact for anyone who needs those fields. The value is in **breaking the screen into logical
   pieces**, not in asking less.

So the wizard **covers everything the service screen covers**, one coherent question per step, and it lives
where products are created. It will be well over four steps, and that is correct — a long wizard of easy
steps beats a short one that dumps you into a console.

### 4.1 Everything a Service holds

| Group | Fields | Required | Default |
|---|---|---|---|
| Identity | `name`, `description` | name | — |
| Delivery | `location_mode` (onsite / mobile / virtual / hybrid) | no | `onsite` |
| Booking | `fulfillment_mode` (scheduled / no_booking) | no | `scheduled` |
| Timing | `duration_minutes` | **yes if scheduled** | 60 |
| Price | `prices[]`, `default_price_index` | price | — |
| Payment timing | `booking_flow` (pay_then_book / book_then_pay) | no | `pay_then_book` |
| Team | `allowed_fulfillers[]` — fulfiller, override type/amount, tips_to_fulfiller | no | `[]` |
| New fulfiller | first name, last name, email, `compensation_type` (flat_fee/percent/hourly), amount | email | — |
| Assignment | `default_fulfiller_id`, `calendar_connection_id` | no | — |
| On the day | `check_in_required`, window start (15) / end (5), `check_in_label`, `completion_required` (true), `completion_label` | no | sensible |
| Presentation | `hero_image_url`, `image_dims`, `active` | no | active |

### 4.1b Personal vs tenant availability — the author asked, so it is written down

Three documents, and the distinction is real:

| | What it is | Scope |
|---|---|---|
| `tenant_availability` | the BUSINESS's hours, plus the booking mechanics nobody else carries: `timezone`, `slot_interval_minutes`, `lead_time_minutes`, `weekly_hours` (7 days) | one per tenant |
| `fulfiller.availability.weekly_hours` | when a PERSON works. Hours only — timezone, slot size and lead time still come from the tenant | one per staff member |
| `availability_exception` | a dated override, `type: block` or `open`, with `fulfiller_scope` all-or-specific | holidays, one-off closures, extra open days |

So a **solo tenant only ever needs tenant availability** — they are the business. Per-person hours exist to
NARROW the business's hours for one staff member, and exceptions override either.

### 4.1c The panels already exist, and that is the whole problem

`Services.vue` stacks five self-contained components on one page: `FulfillersPanel`,
`TenantAvailabilityPanel`, `AvailabilityExceptionsPanel`, `CalendarPanel`, `AppointmentsPanel`. None takes a
prop; each owns its store.

Two consequences:

1. **The wizard embeds them, it does not rebuild them.** A step is `<TenantAvailabilityPanel />` with a
   heading over it. This is much cheaper than it looked.
2. **The overwhelm is the page, not just the modal.** Five consoles stacked with no order is the thing that
   made this feel unusable, and the modal was only the last straw.

**They are TENANT-scoped, not service-scoped** — availability, exceptions, staff and calendar are shared by
every service. So the wizard must ask them **once**: on the first service they are steps; on the second they
collapse to a confirmed line ("Your hours: Mon–Fri, 9–5 · Change") that a tenant passes without stopping. A
wizard that re-asks the business's opening hours for every haircut is worse than the console.

### 4.2 The steps (author's list, 2026-09-18)

| # | Step | Asks | Shown when |
|---|---|---|---|
| 1 | What you offer | name, description | always |
| 2 | Details | `product_category`, `location_mode` | always |
| 3 | **Do customers book an appointment?** | `fulfillment_mode` | **always — this is the branch** |
| 4 | Price | `PricingCard` | always |
| 5 | How long does it take? | `duration_minutes` | booked only |
| 6 | When do they pay? | `booking_flow` | booked only |
| 7 | Who will fulfill this? | myself / add a staff member → `FulfillersPanel` | always; panel on "staff" |
| 8 | What is the availability? | `TenantAvailabilityPanel`, + per-fulfiller hours on staff | booked only; **once per tenant** |
| 9 | Are there exceptions? | `AvailabilityExceptionsPanel` | booked only; **once per tenant**; skippable |
| 10 | Who gets the tips? | none / the fulfiller (`tips_to_fulfiller`) | staff only |
| 11 | Calendar & sync | `CalendarPanel`, `calendar_connection_id` | booked only; **once per tenant** |
| 12 | Photo | hero image | always |
| 13 | Review | what was set, links back, `active` | always |

Step 3 is the pivot the author named, and it does most of the work: **not booked collapses to 7 steps**
(1,2,3,4,7,12,13) because availability, exceptions and calendar all fall away with it.

Rough shapes: **solo, not booked → 7** · **solo, booked → 10** · **staff, booked → 13** · and a tenant's
SECOND service is 3–4 shorter again, because the tenant-scoped steps are already answered.

### 4.3 What makes a long wizard bearable

Not polish — without these, thirteen steps is worse than one screen.

- **Tenant-scoped steps are asked once** (§4.1c). This is the single biggest lever on perceived length.
- **Every optional step is skippable with its default stated** — "Most people leave this as *Ready on Site*".
- **A real Review step** listing what was set, each line linking back. It is what lets someone move fast
  without fear, and where `active` belongs, being the last decision.
- **The rail must not lie about conditional steps.** `LandingPages.vue` has the scar: `displayTotal`,
  `displayStep` and the label list must agree, and when they did not the rail misreported how much was left.
  One predicate derives all three, and the rail shows only the steps THIS tenant will see.
- **No word a solo tenant must look up.** "Fulfiller" is our word; only step 7's "staff" answer reveals it.

### 4.4 Where it lives

In the **Products wizard** — *"when people think of 'product' they think of product or service"*. `WIZARD_FLOWS`
is keyed on intent today and gains a service path chosen by `product_type`: the branch that never existed and
caused the original bug. The "Create a service instead" hand-off button is removed; step 2 takes its place
with `product_category`.

Services keeps **+ Create Service** as a second door into the same wizard. One wizard, two doors.

**This settles §3 by construction:** picking "Service" runs the service flow and writes a **Service**
document, so `product_type="service"` is a router in the picker and never a stored product type.

## 4.5 Editing: where a service goes after it is created

The author's constraint: *"the services screen remains intact as a way to edit services."* Agreed — it is a
good console and this plan never touches it. The open question is what happens when a tenant goes looking.

**The problem is created by the fix.** If picking "Service" in the Products wizard writes a `Service`
document (§4.4), then the thing the tenant just made **does not appear in the Products list at all** — and
they made it on the Products screen. That is the same discontinuity we just removed from creation, moved to
the day after.

There is precedent for the answer. `Offers.vue` already merges the two: *"Products and services are both
'items'; the visual selector treats them as one list"*, via `serviceSelectorCard()` (Offers.vue:818), which
shapes a Service into a product-compatible card so every existing helper works unchanged.

### Three options

**A — Services appear in the Products list; Edit deep-links to the Services editor.** *Recommended.*
Reuse `serviceSelectorCard()`'s trick for the list rows, mark them with a type badge, and make Edit call
`navigateTo("services", { edit: service_id })` so the Services screen opens with that service's modal
already up. The tenant finds what they made where they made it, and edits in the console built for it.

Cost: a merged `filteredProducts`-style computed, a badge, and `navigateTo` gaining a payload argument
(it takes only a view name today — it was added this session, so widening it is cheap).

Risks to handle, not hand-wave: the Products list's own filters, search and bulk actions must either work on
service rows or visibly not apply to them. A row that looks like the others and silently ignores "Archive"
is worse than a row that is obviously different.

**B — A pointer, no merged list.** The wizard's final step says where the service now lives, with a button;
the Products list never shows services. Cheapest, and honest, but it re-teaches the tenant that services are
Somewhere Else — exactly the lesson §4.4 exists to unteach.

**C — Merged list, Edit opens the WIZARD again in edit mode.** Rejected. It would mean maintaining a second
editor for the same document, and the wizard is deliberately a create-time narrowing: a tenant editing a
service usually wants one field, not thirteen steps.

### Recommendation

**A**, with **B as the fallback if the list merge proves messy.** The deep-link is the only genuinely new
mechanism, and it is small: `navigateTo` already exists and needs one payload argument, while the Services
screen already has `openEditModal(row)` to call on arrival.

Worth deciding at the same time: whether the Products list **filters** (`type: physical / digital`) gain a
`service` value. If services show in the list they should be filterable like everything else.

## 5. The editor

Unchanged by all of this: the existing screen stays the console for someone who already has a service. It is
a fine tool; it was only ever a bad front door.

Optional later, not required: group it behind `SettingsAccordion` the way Page Settings is, using the same
groupings as §4.1. No fields removed.

## 6. Phasing

1. **Agree §4.2's step list, §4.4's placement, and §4.5's edit route.** All three are author calls.
2. Build the wizard in Products, with the Services door pointing at the same flow.
3. Review step + skip affordances (§4.3) — these are the feature, not polish.
4. **Exercise the selling path end to end.** 59 tests pass but zero real services exist: create one through
   the wizard, attach it to an offer, publish, book it, take payment.

Not in scope: plans/SERVICES_IN_OFFERS.md's remaining items and plans/BOOKING_AS_PRIMITIVE.md's Booking
decoupling. Both are design-only, both are larger, and neither blocks a tenant creating a service.
