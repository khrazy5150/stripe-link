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

## 4. The wizard (the actual ask)

Mirror the Products wizard exactly, because tenants have learned it. Four steps, not five — a service has no
SKU/identifier step worth asking about at creation.

| Step | Asks | Notes |
|---|---|---|
| 1. Purpose | already exists | "Sell something" → type "Service" routes here |
| 2. Details | name, description, **duration** | the three required fields live here + step 3 |
| 3. Pricing | reuse `PricingCard` | services already use the shared Price primitive |
| 4. Scheduling | *does this need appointments?* → calendar, who performs it | defaults: yes, tenant's own calendar, tenant as fulfiller |
| 5. Image | reuse `ProductImagesField` | identical to the product flow |

Everything else — fulfillers beyond oneself, compensation, overrides, check-in/completion labels and windows,
location mode, tips-to-fulfiller — **moves to the editor**, exactly as the product wizard defers identifiers
and tags. A solo tenant should never meet the word "fulfiller".

Step 4's defaults matter more than its fields: a one-person business should be able to press Next through it.

## 5. The editor

The existing 693-line form becomes the *advanced* surface rather than the front door, reorganised the way
Page Settings already is — `SettingsAccordion` sections, collapsed by default:

- **Scheduling** — duration, booking flow, booking rules
- **Who performs it** — fulfillers, compensation, overrides, tips
- **On the day** — check-in/completion labels, windows, required flags
- **Appearance** — hero image

No fields are removed. They stop being the first thing a new tenant sees.

## 6. Phasing

1. **Decide §3.** Nothing else is safe to build first.
2. **Wizard (§4)** — the tenant-visible fix, and the one that was asked for.
3. **Editor reorganisation (§5)** — mechanical once §4 lands.
4. **Exercise the selling path end to end.** 59 tests pass, but zero real services exist: create one through
   the new wizard, attach it to an offer, publish, book it, take the payment. Everything in §2 is *built*;
   none of it is *proven* against a service a tenant made.

Not in scope: plans/SERVICES_IN_OFFERS.md's remaining items and plans/BOOKING_AS_PRIMITIVE.md's Booking
decoupling. Both are design-only, both are larger, and neither blocks a tenant creating a service.
