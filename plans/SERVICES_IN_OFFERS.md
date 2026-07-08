# Services as First-Class Offer Inputs

Status: **proposed** (design only — no code yet). Author-approved direction:

- A **bookable service is a first-class thing an Offer can present** — `offer.items[]` accepts a
  `service_id` item exactly like a `product_id` item. Retire the `linked_product` workaround.
- **Service pricing reuses the shared `Price` primitive** (`schemas/Price.schema.json`) — so services
  inherit **net-guaranteed**, sale/flash contexts, compare-at, and the fee engine with no bespoke logic.
- **Two booking timings**, chosen per offer/service:
  - **book-then-pay** — customer books a slot first, pays later (e.g. tax prep). Payment via the
    standalone **invoice / pay-link** path.
  - **pay-then-book** — customer pays first, then schedules (e.g. mobile massage).
- **Invoicing stays standalone.** A service can be sold with **no landing page at all**: the tenant
  creates an invoice and texts/emails a pay link (the C.3 flow, already built). This is a first-class
  third path, not an afterthought.

---

## 1. Why (the disconnect we're fixing)

Today there are two parallel worlds:

- **Commerce:** `Product` (owns `prices[]`) → `Offer` (references `product_id` + `price_id`) →
  **Landing Page** (renders *from the Offer* — the single source of truth) → Checkout → Order.
- **Booking:** `Service` (owns a single `price`) → server-rendered `/book/{service}` → direct booking
  checkout → Appointment. Fulfillers, availability, calendar, reminders, delegation live here.

`Service.linked_product` was a **workaround** to let a service be *charged* through an offer — but it
has **no backend consumer**, so it never actually booked anything. Confirmed in legacy `stripe-cart`:
its massage landing pages (e.g. `page_2ebc3baaba2e`) use the ordinary offer checkout and **only
charge** — booking lived in a separate `/api/appointments/*` system the pages never called. So the
charge-without-booking split is a **legacy limitation, not a pattern to preserve.**

Services are now first-class in stripe-link (scheduling, fulfillers, availability, calendar,
appointments, delegation, reminders — all in prod). Making them shadow a Product means duplicated,
sync-prone data and tenant confusion. We make them first-class instead.

---

## 2. Target model

A **Service** is the scheduling + pricing authority for a bookable thing. An **Offer** can list
products and/or services. A service can be sold three ways, all converging on the same `Appointment`
(except invoice-only, which may book or just charge):

| Path | Entry point | Timing | Payment |
|---|---|---|---|
| Direct booking page | `/book/{service}` | schedule-then-pay (today) | Checkout at booking |
| **Offer / landing page** | Offer → page | **book-then-pay** or **pay-then-book** | Checkout or invoice |
| **Standalone invoice** | pay-link by email/SMS | book-then-pay (or charge-only) | Hosted invoice |

---

## 3. Data-model changes

### 3.1 `Service` (schema)

- **`prices[]`** — array of `Price` (reuse `Price.schema.json`) + **`default_price_id`**. Migrate the
  current single `price` → `prices[0]` (default). The `Price` fields we care about: `unit_amount`,
  `tenant_keyed_amount`, `compare_at_unit_amount`, `context` (**limited to `standard`/`sale`/`flash_sale`**
  for services — `upsell`/`order_bump`/`downsell` are funnel-only and meaningless here),
  `fee_handling` (`standard` | `net_guaranteed`), `pricing_model` (`one_time` now; `recurring`/
  `customer_chooses` later), `fee_breakdown`.
- **`booking_flow`** (default): `book_then_pay` | `pay_then_book` — the service's natural timing; an
  offer item may override it.
- **`price` (legacy)** — kept transiently for back-compat reads, then removed once callers use `prices[]`.

### 3.2 `Offer` (schema)

- **`items[]` item = product XOR service.** Add a service path alongside the existing product path:
  `{ "service_id", "price_id", "quantity" }` (price_id references a `Service.prices[]` price).
  Enforce one of `product_id` / `service_id` per item (extend the existing `oneOf`).
- **`fulfillment` / `booking_flow` per service item** (override of the service default): `book_then_pay`
  | `pay_then_book`. Lets the *same* service be sold "pay first" on one page and "book first" on another.
- `product_intent` stays `transaction` (services are transactional, not lead-gen).
- `checkout.mode` stays `payment` for one-time; `subscription` reserved for recurring services (later).

### 3.3 `Appointment` (schema)

- Add linkage: **`order_id`**, **`offer_id`**, **`invoice_id`**, **`page_id`** (attribution +
  reconciliation), and **`source`** (`booking_page` | `offer` | `invoice`).
- **pay-then-book** needs an "awaiting schedule" state: add **`awaiting_schedule: bool`** (or a status
  `purchased`) — the appointment exists as *paid but unscheduled* until the customer picks a time.
  (Decide in Open Questions: new status vs flag.)
- **book-then-pay** uses existing `payment_status` (`unpaid`/`pending`/`paid`) — booked first, invoice
  drives payment.

### 3.4 Fees

- Add a **`service` product-type fee class** in the billing config (defaults to the `digital` rate,
  independently tunable) so `calculate_price(product_type="service", …)` prices services correctly.
  (Services currently borrow `digital`.)

---

## 4. The two booking flows

### 4.1 pay-then-book (mobile massage)

1. Landing page shows the service (from the Offer) with a **Buy / Book** CTA.
2. CTA → **offer Checkout Session** (existing `create_stripe_checkout_session`), line item built from
   the service price (net-guaranteed honored), `application_fee_amount` = platform fee. Metadata carries
   `service_id`, `booking_flow=pay_then_book`, `offer_id`, `page_id`.
3. Webhook (`stripe_webhook`) on paid session → create Order **and** an Appointment
   `payment_status=paid`, `awaiting_schedule=true`, with a manage token.
4. Success/thank-you routes the customer to the **slot picker** (reuse the booking availability +
   `manage` endpoints) → picking a slot sets `starts_at`/`ends_at`, clears `awaiting_schedule`, status
   `booked` → **calendar sync + reminders + delegate email fire** (the Phase-2 delegation flow).

### 4.2 book-then-pay (tax preparation)

1. Landing page (or direct booking page) shows the service with a **Book now** CTA.
2. CTA → slot picker → reserve/confirm → Appointment `status=booked`, `payment_status=unpaid`, no charge
   yet. Calendar/reminders/delegate-email fire on book.
3. Payment is collected via the **standalone invoice path (C.3)**: auto-create (or one-click) an
   Invoice from the appointment (`invoice.source.appointment_id`), send the hosted pay link by
   email/SMS. On `invoice.paid` webhook → appointment `payment_status=paid` (already wired in C.3b).
4. Optional deposit / pay-at-service variants are a Phase-4 refinement.

### 4.3 Standalone invoice (no landing page)

Unchanged from C.3, and explicitly preserved: the tenant creates an invoice (from a service or custom
lines) and sends a pay link by email (SMS later) — **no offer or page required**. book-then-pay reuses
this exact machinery; the difference is only whether an Appointment is attached
(`invoice.source.appointment_id`) and whether a landing page initiated it.

---

## 5. Backend wiring

- **`domain/pricing.py`** — `resolve_offer_item` / `resolve_offer` / `load_offer_products` learn the
  **service item**: resolve `service_id` → Service + selected `Price`; return the same resolved shape
  (currency, unit_amount, name, image) the checkout already consumes, tagged `kind: "service"`.
- **`domain/fees.build_fee_context`** — resolve `product_type="service"` and the price's `fee_handling`
  for service items; reuse `calculate_price` unchanged.
- **`handlers/checkout.py`** — build the Stripe line item from a service price; stamp booking metadata;
  for `book_then_pay` offers, **do not** open a payment session — route to the booking flow instead.
- **`handlers/stripe_webhook.py`** — extend the checkout-completed path: a paid **service-offer** session
  creates the Order + the `awaiting_schedule` Appointment (pay-then-book). The existing
  `persist_appointment_paid` and `invoice.*` handlers already cover the direct + invoice paths.
- **`handlers/booking.py`** — availability + `manage` endpoints gain a "schedule a purchased
  appointment" entry (set the time on an `awaiting_schedule` appointment via its manage token).
- **`handlers/invoices.py`** — add "create invoice from appointment" (book-then-pay convenience);
  `invoice.source.appointment_id` links them.
- **Retire `linked_product`** — drop reads/writes; services no longer shadow a Product. Migration:
  dev-only data; no prod services reference it. Any offer that pointed at a shadow product is re-pointed
  at the service item (manual/one-shot; expected count ~0).

## 6. Landing page / dashboard

- **Renderer + page builder** — an Offer item that's a service renders name + price (compare-at for
  sale/flash) and a CTA whose behavior follows `booking_flow`: pay-then-book → Buy → checkout → schedule;
  book-then-pay → Book now → slot picker → (invoice). The page still renders **from the Offer** (single
  source of truth) — no new data source.
- **Offer editor** — item picker lists **products and services**; per service item, a `booking_flow`
  selector (defaulting to the service's own).
- **Service editor** — the **Pricing card** ports the shared price UI (fee handling std/net-guaranteed,
  context standard/sale/flash, compare-at, live preview) on the `Price` primitive; a `booking_flow`
  default selector.

## 7. Security / integrity

- `mode` (test/live) isolation across service prices, offers, checkout, invoices (as today).
- Webhook idempotency (existing `webhook_events` table) covers the new service-offer session path.
- Manage tokens gate "schedule a purchased appointment"; least-privilege IAM unchanged.

## 8. Testing

- Offer resolver with a service item → correct resolved price/name; mixed product+service offer.
- `calculate_price` net-guaranteed on a service price; fee context `product_type="service"`.
- pay-then-book: paid session → `awaiting_schedule` appointment → schedule → booked + calendar/reminders/
  delegate email.
- book-then-pay: book → unpaid appointment → invoice from appointment → `invoice.paid` → paid.
- Standalone invoice still works with no offer/page.
- Landing page renders the right CTA per `booking_flow`.

## 9. Phasing

- **Phase 1 — Service pricing on the `Price` primitive (quick win, zero rework).** Migrate `Service.price`
  → `prices[]` + `default_price_id`; direct booking checkout **and** standalone invoice compute via
  `calculate_price` with the price's `fee_handling`/`pricing_model`. Dashboard Services pricing card
  (net-guaranteed + standard/sale/flash + compare-at + preview). **Ships net-guaranteed now.**
- **Phase 2 — Offers accept service items.** Offer schema + `domain/pricing` resolver + fee context;
  offer checkout builds service line items; `booking_flow` field; **retire `linked_product`**.
- **Phase 3 — Landing-page presentation + both booking timings end-to-end.** Renderer/page-builder
  service CTA; pay-then-book (post-purchase schedule) and book-then-pay (book → invoice) wired.
- **Phase 4 — Refinements.** Deposits/partial payment for book-then-pay; service fee-tier tuning;
  multi-price/packages (single vs package of sessions, needs a booking-page price selector); recurring
  (subscription) services + customer-chooses (PWYW).

## 10. Open questions (resolve before/within each phase)

- **Where `booking_flow` lives:** service default + per-offer-item override (leaning yes) vs offer-only.
- **pay-then-book state:** new appointment status `purchased`/`awaiting_schedule` vs a boolean flag on a
  `paid` appointment. (Leaning: `awaiting_schedule` flag — fewer status-machine changes.)
- **book-then-pay payment trigger:** auto-send the invoice on book vs a one-click "Send invoice" action.
  (Leaning: configurable per service, default one-click.)
- **Mixed offers:** a single offer containing a product *and* a service — checkout handles both lines,
  but scheduling is per-service; confirm the thank-you flow handles "pay once, schedule the service part."
- **Multi-price / packages for services:** single price now; packages (5-session bundle) deferred to
  Phase 4 (needs a booking-page price selector).

## 11. Relationship to existing plans

- Reuses the `Price` primitive and offer/checkout machinery from `AI_AND_COMMERCE_ARCHITECTURE.md`
  (which already allows **mixed fulfillment types** in offers/carts — services slot in cleanly).
- The delegate calendar/email flow from `MULTI_CALENDAR_ARCHITECTURE.md` fires on the *booked* transition
  regardless of which path booked it.
- Supersedes the `linked_product` bridge noted in `SERVICES_IMPLEMENTATION*.md`.
