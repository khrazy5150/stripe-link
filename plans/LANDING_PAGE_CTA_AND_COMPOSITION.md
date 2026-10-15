# Landing Pages: CTA Components + Page Composition

Status: **proposed** (design; supersedes the "retire simple / lead-gen" Phase 3 plan and folds in the
component-based CTA + page-composition direction). No code yet beyond the offer-as-contract work already
shipped (Phases 1–2).

## Principles

1. **The offer is the contract.** The landing page renders entirely from the offer (Phase 1: presentation
   snapshot). It never reaches into products/services for copy.
2. **One theme.** `universal_bundle` is the only template. "simple" is retired. **No migration** — old
   pages can be blown away; we start fresh.
3. **CTA is a component chosen by type.** The offer's `presentation.cta.type` selects which CTA component
   renders. Each type is its own shared component (mirroring the existing `PricingCard`), so adding a new
   CTA is "add a component + a type", nothing else.
4. **A page is composed of elements.** Beyond the offer-derived core (hero, CTA), the tenant can add
   optional element components (testimonials, ratings, client marquee, FAQ, …) and reorder them
   (drag-and-drop). Each element is a Vue component in the builder + a server render function.

## CTA types → components (the core of this work)

`offer.presentation.cta = { type, label, target, … }`, snapshotted at offer save (like the rest of the
presentation). `type` ∈:

| type | component | behavior | source |
|---|---|---|---|
| `buy` | PriceCard (exists) | price card(s) + Stripe checkout | transaction offer, resolved prices |
| `call` | CallCTA | `tel:` button + **top phone banner** | product `lead_capture` action `call_number`, target phone |
| `email` | EmailCollector | inline email (± phone) capture form → lead store | `capture_email` / `capture_email_phone` |
| `external` | ExternalCTA | button linking out (new/same tab) | `external_url` / `social_redirect`, target url |
| `booking` | **BookingWidget** | button reveals an **inline booking calendar** (month grid + time slots, timezone), books the service | a `scheduled` service item; reuses the existing availability + reserve flow |

Notes:
- **BookingWidget** is the interactive one (see screenshots): a "Book a Session" button reveals the
  calendar inline (availability grid + slots + timezone), then reserves/checks out. It reuses the existing
  public booking flow (`/services/{id}/availability`, `/appointments/reserve`, `/appointments/checkout`)
  rather than a new backend. A service offer with `fulfillment_mode: scheduled` gets `cta.type = "booking"`;
  `no_booking` services stay `buy`.
- Each CTA renders in **two places**: the builder **Live Preview** (Vue component) and the **published
  page** (server HTML in `runtime/html.py`, + a small JS island for the interactive ones — email submit,
  booking calendar). Keep the two in sync via one shared markup contract.

## The CTA is a BUTTON, not a form (added 2026-10-15)

A lead CTA renders the form itself, inline, in the CTA slot. A buy CTA renders a button. That difference
looks harmless and is the reason a long lead page cannot repeat its ask.

**The trigger.** A Page Ribbon that "acts like the page's CTA" (see [[RIBBON_ACTIONS]] §7) is trivial for a
buy offer — reuse the emitter — and impossible for a lead offer, because you cannot put a second copy of a
form mid-page. The runtime says so already: the lead handler is
`document.querySelector('[data-lead-form]')`, **singular**. A second form on the page is never bound and
sits there dead.

**The shape: one form, many buttons.** The form moves into a native `<dialog>`; the CTA becomes a button
that calls `showModal()`. Every other ask on the page — a ribbon, a repeat CTA — opens the same dialog.
One form instance, one submit path, one lead.

Native `<dialog>` deliberately, not a hand-rolled overlay: focus trapping, Escape-to-close and an inert
background come with it, and a registration form is exactly where hand-rolling those goes wrong.

**No progressive-enhancement cost.** The form is already JS-submitted — `preventDefault()` then fetch — so
it has never worked without JS. A dialog takes nothing away that existed.

### It is a CHOICE, not a replacement

Inline forms often convert better than modals: the field is in front of the visitor with no click in the
way. Modals win when the page is long and the form would otherwise be far from the argument that earned the
click. This is genuinely A/B-dependent, so the tenant picks:

> **Registration form:** `Shown on the page` (default) · `Opens from a button`

Defaulting to today's behaviour means no existing page changes when this ships, and the A/B module can
settle it per page later. The ribbon's CTA action requires the button mode on a lead offer, and says so.

### The closed-state gate is SHARED, not copied

The gate lives in the CTA renderer today: with no open sitting, the form is replaced by the "Registration
has closed" alert. Once other elements can open registration, each of them must ask the **same**
`accepts_registration` function rather than carry its own idea of whether registration is open — otherwise
a ribbon button cheerfully opens a modal for a webinar that ran last week.

Done right this is the opposite of a risk: a closed event means **every** ask on the page shows the closed
state, because they all read one answer.

### Why this matters beyond the ribbon

It makes the CTA one shape across every offer type — *a button that converts* — which is what lets any
element host one. It is also the precondition [[BUILDER_SECTION_ORDER]] §4a named for reopening the
baseline order: the ask sits after the persuasion precisely because `checkout_cta` is non-repeatable and
there is exactly ONE of it. A repeatable ask changes that calculation.

## Page composition (addable / draggable elements)

The universal page = an ordered list of element sections. Core elements come from the offer (hero, CTA);
the tenant adds optional ones and reorders them:

- Addable elements (each a Vue builder component + a server render fn): **testimonials, customer ratings,
  client logo marquee, FAQ (exists), content block (exists), countdown (exists), trust badges (exists)**.
- **Drag-and-drop** ordering in the builder; the page document stores the `sections[]` order (already the
  shape). Reorder = reorder `sections[]`.
- This makes the builder a light page composer without a second template.

## Listicle — a section, not a separate template

The listicle spec is **already written**: `AI_AND_COMMERCE_ARCHITECTURE.md` **Part C**. Key correction to
the earlier assumption: **listicle is a `product_carousel` *section*, not a separate theme.** It stays
inside the one universal template — which reinforces the "one template + composable sections" direction
rather than contradicting it.

- A `product_carousel` section iterates several offers/products: swipeable, **per-slide dynamic CTA** that
  morphs into that product's price, **Buy now** + **Add to cart** + a persistent **mini-cart**.
- Sells **unrelated / mixed-fulfillment items** together (physical + digital-bonus etc.); the
  transactional-vs-lead-gen restriction still holds (enforced in `offers.py`).
- **Buy-now ships first** on the *existing* single-offer checkout (no new primitives). The **server-side
  cart** (multi-line order model, abandoned-cart recovery, per-line refunds/receipts/fees) is its own
  deliberate later project.
- Prerequisite: promote `offer_type` (single / bundle / listicle) to a first-class validated field
  (currently UI-only, stripped before validation).

So in *this* plan, the listicle is just another addable section (Phase 4 composition), with its cart work
tracked under `AI_AND_COMMERCE_ARCHITECTURE.md` — not a fifth template phase.

## Retire "simple"

- Remove the `simple` fork everywhere (dashboard template selection, section generators, server
  `TEMPLATE_STYLES`/`template_name`, `SUPPORTED_PAGE_TEMPLATES`, `Page.schema` enum).
- **No migration / no alias** — per direction, old pages are disposable. Just stop writing "simple" and
  make `universal_bundle` the only value.
- Reconcile the naming trap: the `page-simple-coffee` fixture (a *transaction* page templated "simple") is
  re-templated to `universal_bundle`; its tests updated.

## Server render gap to close (the real fix)

`render_checkout_cta` (`runtime/html.py`) currently **always** renders a Stripe price button and ignores the
lead-gen `url`. It must branch on `cta.type` and render the right CTA component's markup (buy/call/email/
external/booking). `validate_page_document` must carry+validate the CTA/action fields. This is the one net-
new backend behavior; the rest is deletions of the simple/universal forks.

## Phasing

1. **CTA contract + non-interactive CTAs — ✅ SHIPPED (dev+prod, 2026-07-09).** `presentation.cta
   {type,label,target}` snapshotted at offer save; server (`render_checkout_cta`) + builder render `buy` /
   `call` (tel: + phone banner) / `external`; `email`/`booking` render an interim labeled button. Retired
   "simple" everywhere (no migration). **Removed the page-level lead-flow CHOICE** — the offer dictates the
   CTA; the page renders exactly one CTA component and never lets the tenant pick call-vs-external. Builder
   preview renders the single CTA component by `cta.type`.
2. **EmailCollector CTA — TABLED (2026-07-09).** No lead-capture backend exists yet (`capture_email` has
   never had a receiving endpoint). Deferred: needs a new lead-submission primitive (public `POST /leads`
   endpoint + `lead_submission` doc + where the tenant sees leads — notification bell vs a dashboard Leads
   screen). Decide storage scope when picked up. Until then the email CTA renders the interim button.
3. **BookingWidget CTA.** Inline calendar reveal reusing the booking flow; the biggest CTA component.
4. **Page composition — ✅ SHIPPED (2026-07-10).** The page body is a composable, drag-to-reorder list of
   elements (builder "Page Elements" card). New element types with server render + validation + tests:
   **testimonials, rating, client_marquee**. Existing content-block/FAQ migrated into the list. **Listicle
   `product_carousel`** section: references multiple offers; the render pipeline (`load_render_context`)
   now resolves multiple offers; each slide shows that offer's price + a Buy-now launching *that offer's*
   existing single-offer checkout. **Server-side cart still deferred** (see `AI_AND_COMMERCE_ARCHITECTURE.md`
   Part C) — buy-now only for now.

## Relationship to other plans
- Builds on the offer-as-contract work (Phases 1–2, shipped) and `SERVICES_IN_OFFERS` / `BOOKING_AS_PRIMITIVE`
  (the BookingWidget reuses the appointment/availability flow).
- Listicle + cart tie into `AI_AND_COMMERCE_ARCHITECTURE.md`.
