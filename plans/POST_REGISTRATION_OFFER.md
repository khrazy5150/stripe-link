# The offer after a free registration

Status: **proposed** (design only — no code yet). Direction approved 2026-11-15; this document is the
architecture, and nothing here is built.

> **Read [WEBINAR.md §3](WEBINAR.md) first.** The same warning applies with more force: almost everything
> this feature appears to need is already running. The genuinely new work is **one stage value, one
> composed section, and one island**. Everything else — the registration, the leads table, the event, the
> confirmation email, checkout, the upsell island pattern — is shipped.

## 0. What this is

A visitor hands over their email for a free thing. In that moment — after they have said yes once, before
they have been confirmed — they are shown one paid offer. They take it or they decline, and either way
they end up confirmed.

This is the standard two-step webinar funnel. It is worth building because the *free* step already works
end to end and there is currently nowhere to put a price.

## 1. The gap, precisely

`WEBINAR.md §6` ends at step 5: lead stored, confirmation emailed, reminders planned. The page shows its
success state and the visitor leaves. There is no step between "registered" and "done", so there is no
surface on which a paid opportunity can be presented.

`purchase_opportunities[].stage` is `landing | checkout | post_purchase`. None of them fits:

| stage | when | why it is wrong here |
|---|---|---|
| `landing` | on the page | the ask competes with the free registration and suppresses it |
| `checkout` | inside Stripe Checkout | there is no Checkout session — registration is free |
| `post_purchase` | after payment | **no payment happened**, so there is no PaymentIntent to charge again |

That last row is the whole reason this needs its own stage rather than a reuse. `post_purchase` exists to
support the **one-click** charge: the buyer's card is already on file and attached to an intent, so a
second charge needs no card entry. A registrant has handed over an email address and nothing else. Their
offer must route into a normal Checkout session.

## 2. Locked decisions

- **A new stage, `post_registration`, on `purchase_opportunities[].stage`.** Not a new offer type, not a
  new page type. The opportunity is still "this product, at this price, at this moment", which is exactly
  what the normalized model already expresses ([OFFER_MODEL_REDESIGN.md](OFFER_MODEL_REDESIGN.md)).
- **A new PRICE CONTEXT `post_registration` as well — the stage alone is not enough.** Found while
  building P1, and it corrected this plan. Every funnel role in this codebase is a *pair*: a stage saying
  when, and a price context saying which price (`order_bump`→checkout, `upsell`/`downsell`→post_purchase).
  The role is derived from the context, never from the stored stage — `funnel_context_items` selects over
  `offer_product_ids`, which returns **every** product the offer touches regardless of stage. A stage with
  no context of its own would therefore have been invisible: there would be no price to quote, and had the
  product carried an `upsell` price it would have been swept into the one-click charge anyway. The pair
  also buys the staleness property the model was redesigned for: deleting the price retires the offer at
  once, and adding one needs no re-save of every offer holding that product.
- **It renders as an ISLAND on the registration page, not a separate published page.** The post-purchase
  upsell is already an island, the booking picker ships "wherever the island renders", and a second page
  would mean a second slug, a second route, a second publish and an indexable URL whose only content is a
  sales pitch. The island is hidden until the server confirms the registration.
- **Claim routes to normal Checkout.** `build_checkout_url` with the opportunity's price, carrying the
  current `?mode=`. No one-click path, because there is no card.
- **Decline is not a downsell in v1.** Declining reveals the confirmation state. `placement.surface`
  already has `downsell`, so a later downsell needs no model change — it is deliberately out of v1 because
  nobody has asked and it doubles the states to test.
- **No new table and no new route.** Registration still posts to the existing public `POST /leads`;
  purchase still goes through the existing checkout. §13's transform-budget warning therefore does not
  bite: this costs no new `AWS::Serverless::Function` and no new table.
- **Scarcity on this island must be real or absent.** Capacity is already enforced server-side
  (`WEBINAR.md §6.2`), so a seat count can be truthful. Nothing on this island invents a countdown, a
  stock level or a price that "goes back up after you leave". Beyond being dishonest, a high-pressure
  false-scarcity page is a merchant-risk signal, and this platform has already lost a connected account to
  a risk review.

## 3. What already exists — verify before building any of it

| Piece | Where | State |
|---|---|---|
| Registration, server-refused on past/full sessions | `src/handlers/leads.py` | shipped |
| `lead_event` composition, `event_date`, deadline countdown | `composition_rules.json` | shipped |
| Confirmation email + `.ics` | webinars P2a | shipped |
| The normalized opportunity model | `schemas/Offer.schema.json`, `domain/opportunities.py` | shipped |
| A post-purchase upsell island with claim/decline | `runtime/html.py`, `handlers/upsell.py` | shipped |
| Checkout URL construction carrying mode | `build_checkout_url` | shipped |

The island is the piece to read hardest before writing anything: v1 should be the post-purchase island with
its charge call swapped for a checkout redirect, not a second island written from scratch.

## 4. Phases

1. **P1 — the stage. DONE** (9,799 tests green). `post_registration` added to the `stage` enum
   (`Offer.schema.json`) and to the price `context` enum (`Price.schema.json`); `STAGE_POST_REGISTRATION`
   in `domain/opportunities.py`; `post_registration_offer()` + `POST_REGISTRATION_CONTEXT` in
   `domain/funnels.py`, deriving exactly as every other role does; a dashboard label in `handlers/offers.py`.

   The invariant turned out to be **already enforced, twice**, which is why `tests/test_post_registration_offer.py`
   asserts it rather than adding a third guard: `post_purchase_plan` selects on `upsell`/`downsell`, and
   `process_upsell` independently refuses anything outside `allowed_price_contexts`. Neither was written
   with this context in mind, so both are now pinned by test.

   One genuine leak was found and closed: landing resolution allowlists `standard`/`sale`/`flash_sale` and
   so refuses a new context by construction, but **listicle slides are chosen by EXCLUSION**
   (`pricing._LISTICLE_EXCLUDED_CONTEXTS`). A denylist that has never heard of a new context passes it, so
   the $27 add-on would have rendered as a buyable slide on the registration page — the offer appearing
   *before* the registration it is meant to follow. Added, and tested.
2. **P2 — composition. DONE.** A `post_registration_offer` element in `composition_rules.json`, seeded into
   `lead_event`. It is **ungoverned**, like `tip_jar` and `event_date`: `is_section_visible` returns True
   for any ungoverned section that is present, so the tenant adds it from the builder and the renderer
   returns `""` when the offer has nothing to sell. No new `compose_page` kwarg was needed.
3. **P3 — the island. DONE.** `render_post_registration_offer` + `SECTION_REGISTRY` entry, styles, and the
   reveal wired into the lead form's **success branch** — not its submit — so a session the server refuses
   as full or past never shows an offer. Claim is an `<a href>` from `build_checkout_url`; decline hides
   the island and confirms the seat.

   `tests/test_element_registration.py` caught three real omissions: an addable element must appear in the
   builder's `newElement`, `elementSection` **and** `elementsFromPage`, or the tenant's section is
   discarded on save with no error. That guard exists because `price_highlight` shipped with exactly that
   bug. Builder editor added (copy only — the product comes from the pricing context). Dashboard builds
   clean; 9,812 tests pass.
4. **P4 — pricing it. DONE.** A price's context IS its funnel role, so the role is created by adding a
   `post_registration` price on the Products screen — no separate wizard step was needed, and adding one
   would have been a second place to say the same thing. Labelled "After registering", by the moment the
   buyer meets it.

   The **same denylist bug turned up a second time**: `Offers.vue` derives `landingPrices` as every price
   *not* in `FUNNEL_CONTEXTS`, so the add-on would have rendered as a buyable landing card — the offer
   appearing before the registration it follows. Exactly `pricing._LISTICLE_EXCLUDED_CONTEXTS`, which
   needed telling about the same context server-side in P1. Both are asserted now.
5. **P5 — attribution. DONE.** `lead_id` + `event_id` + `occurrence_id` ride the claim link into the
   Checkout session's metadata, so an upgrade is distinguishable from a cold purchase.

   The lead id does not exist until the registration POST returns, so the href is completed client-side
   rather than at publish — best-effort, because an unattributed claim link that reaches checkout beats a
   perfect one that does not. Sanitised server-side through a new `identifier_slug`, for the reason the
   existing `src` attribution already records: these are our own ids, but they come back off a static page
   anyone can POST in place of.

## 5. Open questions

- **Does the confirmation email change when they bought?** Probably: one email that mentions both the
  session and the purchase beats two emails arriving together. Needs a decision before P5.
- **Does a declined offer come back?** A later email ("you skipped this") is a campaign, not a page, and
  belongs with the reminder machinery if it is ever wanted.
- **Does this island belong on `lead_capture` too, or only `lead_event`?** P2 allows both on the argument
  that a squeeze page has the same moment. If that proves wrong it is a one-line composition change.
