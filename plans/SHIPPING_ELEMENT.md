# The Shipping Element — the page describes the choice, the engine decides the cost

**Status: planned, nothing built · Written 2026-09-30.**
Sits on top of `plans/SHIPPING_CHARGES.md` (shipped) and beside `plans/SHIPPING_PROVIDERS.md`.

## Why this exists

The author's architecture, 2026-09-30. Three levels, and the separation is right:

| level | owns | example |
| --- | --- | --- |
| **Tenant** | capability — origin, carriers, ENABLED SERVICES, defaults, policies | "we ship Ground and 2-Day, not Overnight" |
| **Offer** | what physical merchandise is being bought + shipping eligibility | Product A × 3, Product B × 1 |
| **Page element** | how the customer INTERACTS with shipping here | radio buttons, customer chooses |

> *"The landing page describes the commerce experience; the backend determines the authoritative commerce
> state. The Shipping Element describes what the customer can choose. The shipping engine determines what
> those choices actually cost."*

**This also resolves a granularity mistake in what already shipped.** `offer.shipping.options[]` is currently
the ONLY place buyer-facing shipping lives, so a tenant with forty offers would configure it forty times. Under
the three-level model the tenant defines the services once and the offer only overrides — the same
default→override shape `plans/REFUND_POLICY.md` established. See "What changes in the shipped code".

## What already exists — do not rebuild

The author is right that **the Product object already has everything**:

    fulfillment.weight_lb, dimensions, item_dimensions, compressible, ships_alone

And more than that exists:

- **`domain/shipping_packing.pack()` + `domain/shipping.packable_items()`** — real box-packing against the
  tenant's box catalogue.
- **`handlers/shipping.quote_rates`** — already calls the carrier and returns real rates.
- **`domain/rate_policy.py`** — which rate to BUY, with `{carrier, service_token, label}` and `common_services()`.
- **`ShippingConfig`** — origin, boxes, default parcel, `default_service_level`, `allowed_carriers`.

So the engine is largely built. What is missing is a **buyer-facing** path into it.

## The problem at the centre of this, and it is not small

> **Real carrier rates need a destination. The landing page does not have one.**

The author's mock shows `Ground — $8.42`. That is a computed carrier rate, and a carrier cannot price a parcel
without knowing where it is going. Today the buyer's address is collected by **Stripe Checkout**, i.e. *after*
they leave the page. `quote_rates` reflects this exactly: it quotes against an existing ORDER and reads
`order.shipping_address` as `to_address`. There is no path that prices a parcel for a stranger.

Three ways out, and they are genuinely different products:

| | how | cost |
| --- | --- | --- |
| **A. Collect a destination on the page** | ask for it before quoting | a form appears before checkout |
| **B. Flat/table rates in the element** | no destination needed | "$8.42" becomes a fixed price, not a quote |
| **C. No element — let Stripe present the options** | what shipped today | buyer chooses inside Checkout |

**The author's design requires A — with one large exception, which is the next section.** For most small
parcels a flat-rate service prices without a destination at all, and that exception covers enough of real
commerce to change the build order.

### Flat-rate services are the real answer for most parcels (author, 2026-09-30)

> *"That must be why merchants choose UPS flat rate for parcels that meet a certain criteria. The flat rate
> applies to anywhere in the United States. But that doesn't help with items that don't fit the flat rate
> criteria."*

Exactly right, and it changes the recommendation below from "the answer" to "the fallback". **A flat-rate
service is destination-independent domestically** — USPS Priority Mail Flat Rate, UPS Simple Rate — so the price
is a function of the BOX and the weight tier, not of where it is going. Which means a **real, honest carrier
price can be shown on a landing page with no destination at all**, for any parcel that fits.

**The plumbing for this already exists and was written with it in mind.** `ShippingConfig.$defs.box` carries:

    "template": "A carrier's own packaging identifier (USPS flat-rate envelopes and the like), passed
                 straight through to the provider. Flat-rate packaging is frequently the cheapest option
                 for a soft pack, and omitting it means those rates are never quoted at all."

and the `boxes` description says carrier packaging is *"fetched from the provider as parcel templates... The
packer works against the union of the two."* So `shipping_packing.pack()` is already designed to pack into
carrier flat-rate boxes.

**What is missing is the PRICE.** A box carries `template` but no amount, and asking the carrier for the amount
is a rates call, which wants a `to_address` even when the answer would not vary by it. Two ways round that, and
neither needs a destination from the buyer:

- **The tenant stores the published price** per flat-rate template. It is a public, stable number that changes
  about once a year. Simplest, no API call, no cache, no abuse surface.
- **Quote once against a canonical domestic address and cache** per `(template, weight band)`. More accurate at
  renewal time, and valid precisely BECAUSE the rate is destination-independent — but it inherits a carrier
  dependency for a number the tenant could type.

Recommended: the stored price first. It makes the element work with **zero** carrier integration, which matters
because no tenant has a carrier connected yet.

### One caveat the author's framing invites, and it is a real one

*"Anywhere in the United States"* — and `handlers/checkout.py` allows **US and CA**. Domestic flat rate is not
Canadian flat rate, so destination-independence holds only within one country. The element therefore still needs
**the country**, which is one field and already constrained to two values — not the postcode. That is a far
lighter ask than a full destination form, and it is the difference between a dropdown and a form.

### The tiers are not alternatives — they are ZONES, and tier 3 is not optional

The author, 2026-09-30:

> *"Ultimately, the shipping element must be able to generate a real-time rate once the customer enters an
> address. So even IF tenants offer 'free shipping within the United States' that should not stop a customer
> from Canada from ordering and is willing to pay shipping charges to her country."*

This is the correction that makes the tiering coherent rather than a menu. *"Free shipping within the United
States"* is not an offer-wide mode — it is a rule **scoped to a destination**, and the same offer needs a
different rule for everywhere else:

    Offer: 3-Bottle Bundle
      United States   -> free
      Canada          -> live carrier rate
      elsewhere       -> not offered

**That is shipping zones, and this plan had no concept of them.** Every real cart has the shape (zone × rate),
and without it a tenant advertising domestic free shipping silently becomes a domestic-only business — turning
away a Canadian buyer who was willing to pay, which is a lost sale caused by a modelling gap rather than a
decision.

So **tier 3 is a completeness requirement, not the expensive tier nobody reaches.** It is what any zone that
cannot be flat-rated falls back to, and every tenant who sells beyond their own country has such a zone.

### Which makes the buyer's form PROGRESSIVE

The tiers stop competing and start composing, because the zone decides which tier applies — and the zone is
known from the country alone:

    "Where should we ship?"   [ Country ▾ ]
              │
              ├── US   -> zone rule is free/flat      -> price immediately, ask nothing more
              └── CA   -> zone rule is live rate      -> "Postal code?" [ ______ ] -> quote

A buyer in the tenant's home country gives **one dropdown** and sees a price. A buyer abroad is asked for a
postcode, because their destination genuinely requires one. **Nobody is asked for more than their own
destination needs**, which is a better answer than either "always ask for a postcode" or "never ask".

It also means the element's first render needs no destination at all when every configured zone is flat — the
common single-country tenant sees a price with no interaction whatsoever.

### Consequence: `allowed_countries` must DERIVE from the zones

`handlers/checkout.py` hardcodes `US` and `CA`. Once a tenant can configure zones, that list must come FROM
them — otherwise a tenant who adds a UK zone still cannot receive a UK order, because Checkout will not let the
buyer enter a UK address. A zone nobody can order from is a rule the tenant wrote and the platform ignored.

### Consequence: the page may not assert unqualified "FREE SHIPPING"

If free is scoped to a zone, then so is the claim. **"FREE SHIPPING" on a page is a promise the tenant cannot
keep for a Canadian buyer**, and the qualifier has to come from the zones rather than from whatever the tenant
typed: *"Free shipping within the United States"*.

This is the same rule the refund work established — *customer-facing commercial promises should never be
implicit* (`plans/REFUND_POLICY.md`) — applied to the other promise on the same page. Offer D ("advertised FREE
SHIPPING") therefore renders a zone-qualified claim, not a bare badge, and the AI field floor should treat an
unqualified free-shipping claim the way it treats an ungrounded guarantee.

**There is already an unqualified one shipping today.** `runtime/upsell_pages.py:329` puts
`{"icon": "📦", "title": "Free Shipping", "desc": "Your order will arrive within 5-7 business days."}` on the
DEFAULT thank-you page, mirrored in `Configuration.vue:361` and `LandingPages.vue:2591`. Two promises, neither
verified: that shipping was free, and that it arrives in 5-7 days. Shown after purchase to every tenant who
does not edit it — including, now, a buyer who just paid for shipping. Logged in TODO.

### So the strategy is tiered, and the buyer is asked for as little as possible

| tier | asked of the buyer | works when | carrier API |
| --- | --- | --- | --- |
| **1. Tenant flat table** (shipped) | nothing | always — it is the tenant's own number | none |
| **2. Carrier flat-rate box** | country | the packed parcel fits a flat-rate template | none, if the price is stored |
| **3. Live carrier quote** | country + postcode | anything, incl. oversize, multi-parcel, and **every zone that cannot be flat-rated** | per quote, paid |

Tier 2 is where most small-parcel DOMESTIC commerce lives, so the element can ship for that case before the
public endpoint exists. **But tier 3 is a completeness requirement, not an optional upgrade**: every zone
outside the tenant's flat-rate reach falls back to it, and any tenant selling beyond their own country has such
a zone. Shipping the element without tier 3 means shipping a domestic-only business.

Two honest boundaries, and a plan claiming otherwise would be wrong:

- **An item that fits no flat-rate box has no destination-free price.** Either the tenant sets a flat amount
  they will eat the variance on (tier 1), or the buyer gives a postcode (tier 3).
- **A destination outside the flat-rate zone has no destination-free price either**, however small the parcel.
  Flat rate is domestic by definition.

### The recommended resolution: a MINIMAL destination

A carrier quote does not need a full address. **Country plus postal code is enough** — which is two fields, not
six, and is how most carts do it:

    Where should we ship?    [ United States ▾ ]  [ 80204 ]

        ○ Ground      $8.42     5–7 business days
        ○ 2-Day      $17.31     2 business days

Then the drift hole has to be closed, and there is exactly one clean way:

> **If the buyer chooses shipping on OUR page, Stripe must not be allowed to change the address.** Pass the
> destination to Stripe with the session and **omit `shipping_address_collection` entirely**, so Checkout never
> offers to edit it. Otherwise a buyer quoted $8.42 for Denver can switch to Anchorage at the pay button and
> the tenant silently eats the difference.

That is a real behavioural fork: a page WITH the element collects the address itself and Stripe stops asking; a
page WITHOUT it keeps today's flow. Both must keep working, because most offers will not want a shipping form
above the buy button.

**Corollary the author already implied:** there must never be two shipping selectors. If the element chose the
service, Stripe receives exactly ONE `shipping_option` — the chosen one — and its own shipping UI disappears.

## Rates never go in the Page object

Agreed, and it is worth stating why in the plan: a rate depends on destination, live carrier pricing, package
composition, box availability, and the date. The Page is a published artifact served from S3 — anything stored
in it is a snapshot that starts rotting immediately.

```jsonc
// The element, and this is ALL of it
{ "type": "shipping", "mode": "customer_select", "services": ["ground", "two_day", "overnight"] }
```

Never `{"ground": 842}`. The element is a **runtime commerce component**: static markup, live data — the same
shape as the price card reading `expand_offer` rather than storing a price
(`plans/CONVERSION_CONTEXT.md`).

## The tenant controls the choices; the customer picks among them

The author's caution, and it is the right one:

> *"The customer shouldn't be able to arbitrarily ask 'Give me overnight shipping' if the tenant hasn't enabled
> overnight shipping."*

So `ShippingConfig` gains **enabled services** — the tenant's checklist — and the element's `services` array can
only ever NARROW that set, never widen it. A page asking for a service the tenant has not enabled gets it
dropped, not honoured. Same rule as `resolve_sections` in `domain/ai_resolvers.py`: a request may narrow what
the rules allow and may never add to it.

**This is also where the two dead fields go.** `ShippingConfig.rate_options.markup_amount` and
`free_shipping_threshold` are collected by `dashboard/src/components/Shipping.vue:249-255`, saved to DynamoDB,
and **read by nothing** — `rate_policy.py` mentions them only to say they belong to a question it is not
answering. A tenant can set "Free Shipping Threshold: 5000" today and it does nothing. That is the same fault
as the refund-policy literal: a control implying a promise the system does not keep. `free_shipping_threshold`
folds into the new default shape; `markup_amount` becomes the handling fee the author listed, applied to the
quoted rate. Verify both tables are empty first, as the `UserPreferences` refund slot was.

## The engine owns selection AND validation

The author's correction, adopted in full:

> *"You don't want someone manipulating the browser and submitting a $2.00 shipping option that was never
> actually returned by your shipping service."*

The element never sends an amount. It sends a **service choice**, and the server re-derives the price:

    element  ──"rates for this purchase to 80204"──▶  POST /shipping/quote   (public)
             ◀──  [ground $8.42, two_day $17.31]  ──
    element  ──"I choose two_day"───────────────────▶  cart / checkout state (service token only)
                                                       server re-quotes and prices it
                                                       ▼ one shipping_option, our address, no collection
                                                     Stripe
    
A quote is also **short-lived**: carrier prices move, so a stored quote needs a timestamp and a re-derive at
checkout regardless of what the browser says. Trusting a quote from four days ago is the same hole as trusting
an amount from the browser, just slower.

## Four offer shapes, all of which must work

The author's cases, and the element is absent from half of them:

| offer | element | behaviour |
| --- | --- | --- |
| A — digital course | none | no shipping anywhere |
| B — physical, cheapest automatically | **none** | server picks the tenant's default service; buyer never sees a choice |
| C — physical, customer chooses | yes | rates rendered, buyer selects |
| D — advertised FREE SHIPPING | yes | renders "FREE", no selection |

**B is the important one**, because it is probably the common case and it needs no element at all. That means
the element is an *enhancement*, not the mechanism — and the mechanism has to work without it. Today's shipped
path (flat options passed to Stripe) is very close to B already.

## The thank-you page needs its own element, and it is a different one

The author, 2026-09-30: the baked-in Free Shipping card exists *"because the old software didn't have the level
of sophistication that we are now building. So now, the Thank you page will also have to carry an element that
truthfully reflects shipping."*

**A separate element, not the same one.** The two have opposite jobs:

| | Shipping Element (pre-purchase) | Shipping Summary (post-purchase) |
| --- | --- | --- |
| reads | tenant config + offer contents + destination | **the order** |
| asks the buyer | for a destination, for a choice | nothing |
| states | what shipping WOULD cost | what it DID cost |
| can be wrong by | a stale quote | nothing — it is reporting |

### The hard part is that the thank-you page is STATIC

`runtime/upsell_pages.synthesize_thank_you_page` publishes ONE artifact at `{page_id}__thank_you`, served from
S3 to every buyer. A static page has no order, which is precisely why the current card had to invent a promise —
there was nothing true available to it.

**But the runtime path already exists, and it already carries shipping.** The buyer arrives with Stripe's
`session_id` in the URL (`success_url` … `&session_id={CHECKOUT_SESSION_ID}`), and `handlers/upsell.py:71`
already serves a PUBLIC, session-gated `/upsell/session` that a published page fetches at runtime — returning
the customer's email, name, phone and **`shipping_address`**. The exposure question is settled precedent: an
unguessable session id returns only what that buyer already knows.

So the element is a small extension, not a new surface:

1. **Add one expand** to the existing Stripe retrieve: `expand[]=shipping_cost.shipping_rate`. The endpoint
   already passes several expands.
2. **Include `shipping_charges.buyer_paid_shipping(session)`** in the response. That is the SAME reader the
   webhook uses for `order.shipping_amount` — one function, so the thank-you page and the order can never
   disagree about what the buyer paid.
3. **A `shipping_summary` element** that hydrates from it, the JS-island pattern published pages already use.

### The expand is what makes the delivery window honest

Stripe's shipping_rate object carries `delivery_estimate` — the very window the tenant configured as
`transit_days_min/max` on the option. So the element can say *"Ground — arriving in 5–7 business days"* because
**Stripe is handing back the tenant's own promise**, not because a default invented one.

That closes the loop on the logged bug: the invented window is replaced by a real one from the same source that
priced the parcel.

### Rules the element must obey

- **Render nothing when there is no shipping.** `buyer_paid_shipping` returns `{}` for a digital order, and a
  "Shipping" heading on a download is noise.
- **Never state a window Stripe did not return.** No `delivery_estimate` means no window — the service name
  alone is still true, and true-and-brief beats complete-and-invented.
- **"Free" only when `shipping_amount == 0`**, read from the order rather than from the tenant's intent. A
  Canadian buyer who paid must not be told shipping was free because the US zone is.
- **The tracking claim is fine, and I was wrong to doubt it.** The default footer says *"Look for an email from
  us with tracking information about your order"*, and `handlers/orders.py:202` really does email the buyer via
  `notify_buyer` when the tenant records a shipment — with `domain/carriers.service_has_tracking` deciding
  whether to promise a tracking NUMBER, because USPS First-Class carries none. That is the careful version of
  exactly the pattern this plan keeps finding broken elsewhere. The claim is conditional on the tenant marking
  the order shipped, which is a fair thing for a thank-you page to say.

### Removing the default card is a deliberate live change

`DEFAULT_THANK_YOU.next_steps` is a PLATFORM default, so deleting the card changes every thank-you page that
has not overridden it. That is the point — it is removing a false claim, the same call as dropping the
duplicated refund paragraph — but it is a visible change to published pages and should be stated, not slipped
in. Tenants who edited their cards keep exactly what they wrote.

## Two blockers this design walks into

### 1. Multi-parcel is refused, and the author's own example triggers it

`handlers/shipping.py:289` returns `code="multi_parcel"` and refuses to quote whenever packing yields more than
one box — deliberately, so it never quotes one box and ships three. But the spec's worked example is
**"3-Bottle Bundle" recalculating to "6-Bottle Bundle"**, and six bottles is exactly when a second box appears.

So a dynamic element on a bundle page would hit the unsupported path on the larger tier, which is the tier the
tenant most wants to sell. **Multi-parcel quoting is a prerequisite for C, not a follow-up.** Single-parcel
offers can ship first.

### 2. A public rate endpoint is an abuse surface that costs money

`POST /shipping/quote` must be callable by an anonymous visitor, and every call is a **paid carrier API
request**. Unthrottled, that is someone else's bill. Needs the treatment `plans/LEAD_CAPTURE.md` already worked
out for its public endpoint: per-IP and per-page rate limiting, a cheap cache keyed on
(offer, quantities, country, postcode) since identical carts to the same postcode have identical rates, and a
hard ceiling per tenant per hour. **Cache first** — it removes most of the traffic before any limiter sees it.

## What changes in the shipped code

`plans/SHIPPING_CHARGES.md` is not wrong, it is the tenant-flat-rate half of this:

- **`offer.shipping.options[]` becomes an OVERRIDE**, not the only source. `shipping_charges.options_for()`
  learns to resolve tenant default → offer override, the way `refund_policy.resolve()` does.
- **`offer.shipping` gains eligibility** — whether this offer ships at all, and which services it permits
  (narrowing the tenant's set).
- **A computed-rate mode** joins the existing `flat` and `per_item` kinds. Flat stays, and is the fallback for
  any tenant with no carrier connected — which is every tenant until SHIPPING_PROVIDERS ships.
- **`stripe_shipping_options()` keeps its job** and gains the single-chosen-option case.

Nothing built so far has to be unpicked.

## LOCKED 2026-09-30 — the Phase 1 contract

The author locked these; the only deliberate constraint is that **country is the V1 destination granularity.**

    Product          physical dimensions and weight                        (exists)
    ShippingConfig   enabled services, boxes, ordered zones, defaults      (new)
    Zone             {name, destinations[], rule}
    Zone rule        free | flat | flat_rate_box | live
    Zone matching    ordered, FIRST MATCH WINS, mandatory catch-all
    Box              existing `template` plus country-keyed `flat_rate`
    Shipping screen  owns tenant shipping config and "What buyers pay"
    Offer            eligibility + optional override ONLY
    Element          customer-facing selection; the quote endpoint stays authoritative

### The zone shape, and why `destinations[]` rather than `countries[]`

The author's requirement: *"design the zone shape so country-level zones are the V1 UI, but the schema can
accommodate subdivisions later without breaking it."*

Taken literally, that argues against their own strawman's `countries: ["US"]`. Evolving that to
`destinations: [{country, regions}]` means a SECOND field and a dual-read fallback forever — two shapes meaning
one thing, which is the failure mode this repo keeps paying for. `destinations[]` from day one, with `regions`
simply **absent** in V1, makes the later addition purely additive: no migration, no fallback, no second field.
Same conceptual model, same country-only UI.

```jsonc
"zones": [
  { "name": "United States",   "destinations": [{ "country": "US" }], "rule": { "type": "live" } },
  { "name": "Canada",          "destinations": [{ "country": "CA" }], "rule": { "type": "flat", "amount": 1299 } },
  { "name": "Everywhere Else", "destinations": [{ "country": "*" }],  "rule": { "type": "free" } }
]
```

Later, without touching anything above it:

```jsonc
{ "name": "Lower 48", "destinations": [{ "country": "US", "regions": ["CA", "OR", "WA"] }], ... }
```

**Deliberately NOT in V1** (author): state exclusions, Alaska/Hawaii, territories, provinces, EU regions. That
is a substantially bigger product concept and there is no evidence yet that Junior Bay needs it.

### The validation rules

- **A country may appear in at most ONE non-catch-all zone.** The author's rule, and the reason is exact: with
  first-match-wins, a duplicate is not an error the tenant sees — it is a silently ignored second zone. The
  earlier zone wins and the later one becomes dead configuration the tenant believes is live.
- **The last zone MUST be the catch-all** (`country: "*"`), and only the last one may be. A catch-all in the
  middle makes every zone after it unreachable. Without one, "everywhere else" has no answer and a buyer from
  an unlisted country hits undefined behaviour at the worst moment.
- **`flat` requires an amount; `flat_rate_box` requires at least one box with a `flat_rate` for that zone's
  countries.** A rule that cannot produce a number is not a rule.

### The box shape

`flat_rate` is country-keyed because flat rate is domestic by definition — one number cannot serve two
countries:

```jsonc
{ "template": "usps_medium_flat_rate_box", "flat_rate": { "US": 899, "CA": 1499 } }
```

The author's framing, kept: *"The box template describes the physical container, while `flat_rate` describes
what the tenant charges for that container in a destination country."* And critically — **flat-rate-box pricing
is a shipping-configuration concern, never an Offer concern.**

### Why the Offer editor stays small

The author's reason is the one that matters: otherwise you get *"Why does this offer say $9 shipping when the
Shipping screen says $7?"* So the Offer answers exactly two questions — does this offer ship, and does it
override the default — and holds **no zone editor, no carrier config, no second copy of the shipping system.**

## Phases

1. **`ShippingConfig.enabled_services` + zones + box `flat_rate`, and a UI for them** — replacing the two dead
   inputs. Ships value alone: the first time a tenant can say what they offer and what it costs a buyer.

   **Backend ✅ SHIPPED 2026-09-30** (36 tests): schema, `domain/shipping_zones.py` (pure — matching,
   `services_for`, `allowed_countries`, `resolved_amount`, `flat_rate_for_box`), and
   `validate_shipping_zones` wired into `validate_shipping_config`. **UI still to build.**

   Decisions worth keeping, all of them "None is not zero":

   - `resolved_amount` returns **None** for `live` and `flat_rate_box` — "not answerable from the destination",
     one needing the packed box and the other the carrier. A caller treating it as 0 ships for free.
   - `flat_rate_for_box` returns **None** for an unpriced country. An unpriced box is not a free box.
   - A destination no zone claims is **not served** rather than silently free. Inventing a rule on the tenant's
     behalf is the implicit promise this plan family exists to stop.
   - A catch-all placed early does not shadow a real zone. The schema requires it last, but a hand-written
     document still resolves sensibly rather than making every later zone dead.
2. **Tenant default → offer override resolution** in `shipping_charges`. Removes the forty-times problem.
3. **Offer B end to end** — server picks the default service, no element, no address form. The common case, and
   it needs nothing public.
4. **Flat-rate box pricing (tier 2)** — a stored price per carrier template, priced off the packer's chosen box
   and the weight tier. Needs the country and nothing else, and no carrier integration, so it is the cheapest
   real carrier price the platform can offer.
5. **The Shipping Element for tiers 1–2** (offer C/D): the page component, a country selector, and the
   omit-Stripe's-address-collection change. This is the buyer-visible feature, reachable without a public rate
   endpoint.
6. **`POST /shipping/quote` (tier 3)**, public, cached, throttled, single-parcel only. Returns services and
   prices; never accepts an amount. Only needed for parcels no flat-rate box fits.
7. **Multi-parcel quoting** — the blocker for bundles, and tier 3 only: a multi-box order cannot be flat-rated
   as one parcel.

## Open

- **Does a full address get collected on the page, or country + postcode?** Recommended the latter, but a
  tenant offering a real address form pre-checkout is not unreasonable for high-value goods.
- **What happens when the buyer's quote expires between page and pay?** Re-quote and show a changed price, or
  honour the stale one at the tenant's expense. Needs a tenant-level rule, not a silent default.
- **Display variants** (radio / cards / dropdown) — the author listed them. Cheap, and they belong with the
  composer's element registry rather than as element-specific config.
- **Handling fee semantics.** `markup_amount` per parcel, per order, or per item? It changes the number on a
  multi-item cart and nobody would notice it was wrong.
