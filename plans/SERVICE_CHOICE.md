# Customer-chooses for services

## The problem

Products carry an **Item Mode** (`fixed` | `buyer chooses`). Services carry nothing: selecting a service
pins one price and the landing page sells that one. A tenant offering 60 / 90 / 120 minute massages has no
way to present them as a choice.

Worse, the shape that looks like it should work does not. An offer holding three services resolves to three
LINES:

```
   svc60   $  90.00
   svc90   $ 130.00
   svc120  $ 170.00
   TOTAL   $ 390.00      <- the buyer is charged for all three
```

That is not a bug to delete: multiple services in one offer means a BUNDLE today, coordinated by
`service_booking_mode` (`single_visit` / `separate_visits`) -- "massage + facial in one visit" is a real
offer. Both meanings have to coexist.

## Why services are not products

`duration_minutes` lives on the SERVICE and is required (documents.py: "Service duration_minutes must be
positive"); the booking engine allocates the slot from it. So 60 / 90 / 120 minute massages are three
SERVICES, not three prices of one. A product's variants are prices; a service's variants are services.

That is why the product mechanism (`selectable_prices` on one item) does not cover the case, and why the
choice has to live one level up.

## Decided design

**One offer-level mode, cards are service x price.**

```
Offer
  service_selection: "bundle" | "choice"    # absent => "bundle"
  default_service_id: "svc90"               # choice mode: the card shown checked
  items:
    - service_id: svc60   price_id: p60
    - service_id: svc90   price_id: p90
    - service_id: svc120  price_id: p120
```

- **bundle** (the default, and what every existing offer means): unchanged. All service lines are charged.
- **choice**: every service item contributes a card -- one per price when the item lists
  `selectable_prices`, otherwise one for its `price_id`. All cards share ONE radio group. Checkout resolves
  exactly the selected `(service_id, price_id)` and charges one line.

Covers both axes with one mechanism: 60/90/120 (three services, one price each) and one-time-vs-plan (one
service, two prices).

### Migration: none

Absent `service_selection` means bundle, so every existing offer behaves exactly as it does today and
nothing is rewritten. The tenant opts in per offer. Same approach as the goal/composition packs.

## Layers

1. **Document** -- `service_selection` enum + `default_service_id`, both optional. `service_selection()`
   helper so nothing re-derives the default.
2. **Resolution** -- `resolve_offer` in choice mode resolves ONE service item: the buyer's
   `(service_id, price_id)`, else the default, else the first. Products in the same offer are untouched.
3. **Renderer** -- choice mode puts every service card in one radio group (`name="sl-service-choice"`) with
   exactly one `checked`. Today every service card is hardcoded `data-default="true"` and `checked`, each in
   its own group -- which is why three services render as three independently-checked cards.
4. **CTA** -- the card already carries `data-service-id`; the checkout URL never sent it. It does now.
5. **Checkout** -- `service_id` query param feeds the selection.
6. **Dashboard** -- Service Options grows a mode select and, in choice mode, a Default radio per service.

## Not in scope

- Mixed one-time/recurring inside a listicle CART (still refused; needs a Stripe sandbox test first).
- Per-service `selectable_prices` UI. The model, renderer and checkout accept it; the form emits one card
  per service for now.
