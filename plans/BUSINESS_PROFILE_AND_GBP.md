# Business Profile & Google Business Profile (GBP)

## Why

Service/local businesses win local SEO through **NAP consistency** — the business Name/Address/Phone must be
byte-identical on the landing page, in the page's structured data, and in the Google Business Profile. Google
cross-checks them. So NAP needs **one canonical source** that everything derives from (same "derive, don't
ask" pattern as expand_offer / composition_rules). Establishing that source now avoids chasing inconsistent
citations after pages have hardcoded addresses.

This foundation pays off twice: it powers **local landing pages** *and* the future **AI-managed GBP** product,
which share the same profile + review store.

## Canonical entity: Business Profile

A first-class, tenant-scoped entity (its own table-per-entity, e.g. `jb-business-profiles-{env}`), distinct
from `TenantProfile` (tenant/billing) and from `Fulfiller` (a person/calendar). Fields (starter):

- **NAP**: legal name, display name, full address (structured: street/city/region/postal/country), phone.
- **Local**: hours, categories, service area (radius or named areas), map/place coordinates.
- **Links**: website, GBP profile URL, `place_id` (once connected).
- **Connection**: GBP account/location IDs + OAuth token ref (Phase 2), sync status/last-synced.
- **Reviews summary** (denormalized): rating average + count, for fast AggregateRating render.

## One tenant → many businesses (native, not bolted on)

A tenant may run several local businesses, each with its own GBP. So the model is **one tenant → many
Business Profiles**, keyed `(tenant_id, business_id)`. Everything that needs NAP references a `business_id`:

- An **offer** (or its fulfilling business) points at a `business_id`; a **page** derives NAP/reviews/schema
  from the referenced business. (A page-level override is possible but the offer is the natural home, since
  it's the thing a business fulfills.)
- GBP itself is account → locations, so a tenant's GBP *account* can map to several Business Profiles
  (one per location) — the multi-business model lines up with GBP's own shape.

Open question below: exact link point (offer vs page) and the Business↔Fulfiller relationship.

## How the landing page consumes it

Slots directly into [[PAGE_COMPOSER]] + the goal axis ([[LANDING_PAGE_GOAL_COMPOSITION]]):

- **Derived NAP** — the page never stores its own address; it renders NAP from the referenced Business
  Profile. A "View on Google" link is a trivial section.
- **Reviews as a pluggable source** — GBP reviews are one provider (alongside manual, later others) that feed
  the `social_proof` pack (testimonials/ratings). No new page surface; a new feed into existing slots.
- **Structured data** — `LocalBusiness` / `Service` + `AggregateRating` JSON-LD, derived from the profile,
  emitted via the `discoverability` pack on the `head` channel. Lights up for service/appointment
  offer_types on local/SEO goals. Zero manual entry. The richer schema shape (specific @type, geo, hours) and the BODY-side local signals (localized alt, `<figcaption>` NAP, image dimensions, NAP consistency) are plans/LOCAL_SEO_SIGNALS.md, which is gated on this profile.

## Productized services: how a local business earns stars at all

NAP consistency gets a local business **found**. It does nothing to get it **stars**, and the two have
different ceilings — so this plan has to say what the other half is, or every service client ends up
optimized for the local pack and invisible in organic results.

**The ceiling.** Since 2019 Google suppresses organic star snippets for *self-serving* reviews — reviews
about your business, on your own site, marked up as `LocalBusiness`/`Organization`. `Service` is not a
review-snippet-eligible type at all. So a landscaper's or dentist's **firm** can never show stars from its
own markup, no matter how many genuine reviews it collects. Firm reputation ranks on **GBP/Maps**, which is
what the rest of this plan is for.

**The escape hatch.** `Product` is *not* restricted, and a discrete bookable service sold as an **Offer** is
`Product`/`Offer`-eligible. "Branch cleanup — $99" is a product as far as Google is concerned; "landscaping
services, call for a quote" is not. So a local business that can **package** a specific job at a price, on
its own page, converts an un-rankable firm reputation into rankable offer reputation — and those reviews are
collected first-party, through [[REVIEWS]], which is the only legal path to `AggregateRating` (GBP and other
third-party reviews are permanently display-only).

**This is why it belongs in this plan.** The review-invite destination is a per-Site choice — Junior Bay form
*or* the Google write-review link, never both. The deciding question is **not** "is this a service
business?" but:

> Does this business have offer pages that can rank on their own, or does it live or die by the local pack?

A landscaper with five priced offer pages is a Junior Bay client. A landscaper with one "about us" page is a
Google client. The same business can be both over time, which is the point: productizing is the migration
path from the second to the first.

**It is not only an SEO play.** A priced entry offer converts far better than "call for a quote", and it puts
the fulfiller on the property, where the $3,000 job gets quoted in person. The stars are a bonus on top of a
sales mechanic that already works. A client who productizes wins twice; a client who cannot productize is
correctly routed to Google and loses nothing.

**Guardrails — these keep it honest, and a manual action away from not being:**

- **Genuinely buyable.** Structured data must reflect what the page actually offers. A $99 price that is
  really a lead form is a markup violation, and an obvious one.
- **Reviews about *that offer*.** Company-wide reviews reattached to a cheap offer to farm stars are the
  self-serving problem in a costume, and more exposed than the honest version — the mismatch between review
  text and offer is visible to a human reader.
- **Scope limit on the page**, not in the terms. "Up to 2 cubic yards, single-family residential, within 15
  miles" is what makes a fixed price honest and keeps the scope argument out of the reviews.

**Today's gap (not built).** The path that produces `Product` + `AggregateRating` runs through a **Product**
of type service, because the renderer builds Product markup from a product document. Service documents are
not yet first-class Offer inputs ([[SERVICES_IN_OFFERS]], designed, unbuilt). So a landscaper can do this
today — just not the way the Services screen implies, which is how a client ends up with a service that can
never rank. See the open decision below.

## Course correction (2026-07-23): Business Profile = Site.organization (extended), NOT a separate entity

This plan predates the **multi-Site** work. A tenant now has **many Sites**, each with its own
`Site.organization` (NAP), and a page already derives identity from its **owning Site**. So "one tenant →
many businesses" already exists, and `Site.organization` already emits `LocalBusiness`/`Organization` JSON-LD
(via `entity_type`, which includes LocalBusiness subtypes). Building a *separate* Business Profile entity now
would create a **second competing NAP source** — the exact inconsistency this plan set out to avoid.

**Decision (user, 2026-07-23): extend `Site.organization`** with the local/GBP fields instead of a new entity.
A Site *is* the business; GBP account→locations maps onto tenant→Sites. No `business_id` plumbing — the
page→Site→organization chain already carries NAP. If a rare "one business across several Sites" case ever
needs a shared source, introduce a Business entity later that Sites derive from (Site.organization as its
cache). Reviews/AggregateRating stay deferred (the renderer refuses hand-typed AggregateRating —
`html.py` — so it needs *real* review records, which land with GBP sync in Phase 2).

## Phasing

- **Phase 1 SHIPPED (2026-07-23) as Site.organization extension:** added `opening_hours` (schema.org
  OpeningHoursSpecification), `geo` {latitude, longitude}, `place_id`, `gbp_url` to `Site.organization`;
  `organization_node` emits `geo` + `openingHoursSpecification` + `hasMap`; the seller_profile section renders
  visible hours + a "View on Google" link (mirrors the JSON-LD); Sites editor gains the full address +
  local-business fieldset + a day-chip opening-hours editor. **Deferred within Phase 1:** reviews as a manual
  source + AggregateRating (needs real review records, not hand-typed — pairs with GBP sync); categories +
  service-area radius (area_served list already exists).
- ~~Phase 1 (original): canonical Business Profile + derive.~~ Superseded by the course correction above.
- **Phase 2 (deferred): GBP OAuth + API sync.** Connect a Business Profile to a GBP location (reuse the
  existing Google OAuth plumbing from the calendar integration), pull NAP + reviews, flag NAP mismatches.
  Map GBP account→locations onto the tenant's Business Profiles.
- **Phase 3 (deferred): AI-managed GBP.** Auto-posts, review replies, profile optimization — its own product
  surface, built on the same Business Profile + review store.

## Open decisions

- **Link point**: does `business_id` live on the offer, the page, or both (page overrides offer)? Leaning:
  offer, with optional page override.
- **Business ↔ Fulfiller**: a business may have several fulfillers (calendars); confirm the relationship so
  bookings and NAP stay coherent without duplicating identity.
- **Review storage**: reviews as their own per-business records (needed for AI replies in Phase 3) vs. only a
  denormalized summary in Phase 1. Leaning: store the summary now, full records when GBP sync lands.
- **NAP mismatch handling** (Phase 2): warn-only vs. block publish.
- **Productized services — which surface owns it?** Either the Services module learns to produce offer pages
  carrying `Product`/`Offer` markup ([[SERVICES_IN_OFFERS]]), or the guidance becomes explicitly "productize
  it as a Product and leave Services for booking". Today it is ambiguous, and ambiguity here costs a client
  their only route to stars. Leaning: Services module, because a tenant who models the work as a Service
  should not have to know the markup reason for doing it twice.
- **Should the review-destination default be derived rather than asked?** The deciding question ("does this
  business have offer pages that can rank?") is answerable from the Site's own pages, so the default could be
  computed and re-evaluated as the tenant adds offers, with an override. Leaning: derive, warn on override.
