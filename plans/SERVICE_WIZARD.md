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

### 4.2 The steps

Conditional, so the path adapts to the business rather than the schema. **[c]** = conditional.

| # | Step | Asks | Shown when |
|---|---|---|---|
| 1 | What you offer | name, description | always |
| 2 | Where it happens | `location_mode`, as four choices | always |
| 3 | Appointments | "do customers book a time?" → `duration_minutes` | always (duration **[c]** on scheduled) |
| 4 | Price | `PricingCard` | always |
| 5 | When they pay | pay first / book first | **[c]** scheduled only |
| 6 | Who performs it | just me / me and my team / my team | always |
| 7 | Your team | assign or create fulfillers, compensation | **[c]** team answers |
| 8 | Calendar | which calendar; default fulfiller | **[c]** scheduled; fulfiller part on team |
| 9 | On the day | check-in / completion labels, windows, required | **[c]** team, and skippable |
| 10 | Photo | hero image | always |
| 11 | Review | what you set, with links back; `active` | always |

Rough shapes: **solo, no appointments → 6 steps**; **solo, scheduled → 8**; **team, scheduled → 11.**

### 4.3 What makes a long wizard bearable

These are not decoration; without them eleven steps is worse than one screen.

- **Every step past the required ones is skippable**, with the default stated on screen ("Most people leave
  this as *Ready on Site*"). A tenant should be able to get to Review in under a minute.
- **A real Review step** listing what was set, each line linking back to its step. This is what lets someone
  move fast without fear — and it is where `active` belongs, because it is the last decision.
- **The rail must not lie about conditional steps.** `LandingPages.vue` already has the scar: `displayTotal`
  and `displayStep` and the label list have to agree, and when they did not the rail misreported how much was
  left. One predicate derives all three, and the rail shows only the steps THIS tenant will see.
- **No word a solo tenant has to look up.** "Fulfiller" is our word. Step 6 asks who does the work; only a
  tenant who answers "my team" ever meets the vocabulary.

### 4.4 Where it lives, and what it creates

In the **Products wizard**, because that is where a tenant looks for the thing they sell.
`WIZARD_FLOWS` is keyed on intent today; it gains a service path chosen by `product_type`, which is the
branch that never existed and caused the original bug.

Services keeps its own **+ Create Service** entry into the same wizard, for the service-led tenant who lives
on that screen. One wizard, two doors — not two wizards.

**This also settles §3 by construction.** If picking "Service" runs the service flow and writes a **Service**
document, then `product_type="service"` is a router in the picker and never a stored product type. One
concept, two fulfilment modes, arrived at through what the tenant does rather than by decree.

## 5. The editor

Unchanged by all of this: the existing screen stays the console for someone who already has a service. It is
a fine tool; it was only ever a bad front door.

Optional later, not required: group it behind `SettingsAccordion` the way Page Settings is, using the same
groupings as §4.1. No fields removed.

## 6. Phasing

1. **Agree §4.2's step list and the §4.4 placement.** Both are author calls.
2. Build the wizard in Products, with the Services door pointing at the same flow.
3. Review step + skip affordances (§4.3) — these are the feature, not polish.
4. **Exercise the selling path end to end.** 59 tests pass but zero real services exist: create one through
   the wizard, attach it to an offer, publish, book it, take payment.

Not in scope: plans/SERVICES_IN_OFFERS.md's remaining items and plans/BOOKING_AS_PRIMITIVE.md's Booking
decoupling. Both are design-only, both are larger, and neither blocks a tenant creating a service.
