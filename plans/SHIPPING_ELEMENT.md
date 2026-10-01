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

### The Offer editor — ✅ SHIPPED 2026-09-30

A single section on the offer form, hidden entirely unless something in the offer actually ships
(`requires_shipping` first, falling back to `product_type` for documents written before that field):

    Eligibility      [ Ships to the buyer ▾ ]   or   No shipping
    Shipping charge  [ Use my shipping zones ▾ ]  Free / A flat amount / Always calculate a rate
    Flat amount      [ 12.99 ]                    only when "A flat amount"

**Nothing is stored for the default.** An offer that ships and defers to the tenant's zones emits no
`shipping` block at all — storing it would turn "not configured" into a decision nobody made, the same reason
the Shipping screen does not save a lone catch-all.

It links to the Shipping screen for the zones themselves. **Note for anyone adding such a link: this app has
no vue-router.** A `<router-link>` builds cleanly and renders nothing; the shell provides
`inject("navigateTo")`, as `Orders.vue:385` says in as many words.

### Why the Offer editor stays small

The author's reason is the one that matters: otherwise you get *"Why does this offer say $9 shipping when the
Shipping screen says $7?"* So the Offer answers exactly two questions — does this offer ship, and does it
override the default — and holds **no zone editor, no carrier config, no second copy of the shipping system.**

## Phases

1. **`ShippingConfig.enabled_services` + zones + box `flat_rate`, and a UI for them** — replacing the two dead
   inputs. Ships value alone: the first time a tenant can say what they offer and what it costs a buyer.

   **✅ SHIPPED 2026-09-30** — backend (36 tests) and UI. `domain/shipping_zones.py` (pure — matching,
   `services_for`, `allowed_countries`, `resolved_amount`, `flat_rate_for_box`), `validate_shipping_zones`
   wired into `validate_shipping_config`, and two new cards on the Shipping screen: **Services** (what speeds
   the tenant offers) and **What buyers pay** (ordered zones), plus per-box prices on the Boxes card.

   The two dead inputs are gone from the form. A stored `markup_amount` or `free_shipping_threshold` is
   carried through on save rather than deleted — a tenant who set one should not lose data to a screen that
   stopped showing it; retiring the fields properly belongs with the handling-fee work.

   UI decisions worth keeping:

   - **The catch-all is structural, not a choice.** The form always keeps exactly one, last, un-removable and
     un-renamable, and `zonesFromDocument` normalises a stored set that has none or several. The tenant never
     sees an error about a shape they did not type, and the validator can never fire on this screen's output.
   - **"Add zone" inserts BEFORE the catch-all**, because a zone after it would never be reached.
   - **A duplicate country is named inline**, identifying the earlier zone that wins — first-match-wins makes
     the LATER zone silently dead, so the tenant would otherwise believe both were live.
   - **Per-box price fields appear only for countries in a zone priced by box**, so a tenant charging flat or
     live rates never sees a column they do not use.
   - **A lone catch-all is not saved.** It is the form's own default, and storing it would turn "not
     configured" into "everything ships free".

   Decisions worth keeping, all of them "None is not zero":

   - `resolved_amount` returns **None** for `live` and `flat_rate_box` — "not answerable from the destination",
     one needing the packed box and the other the carrier. A caller treating it as 0 ships for free.
   - `flat_rate_for_box` returns **None** for an unpriced country. An unpriced box is not a free box.
   - A destination no zone claims is **not served** rather than silently free. Inventing a rule on the tenant's
     behalf is the implicit promise this plan family exists to stop.
   - A catch-all placed early does not shadow a real zone. The schema requires it last, but a hand-written
     document still resolves sensibly rather than making every later zone dead.
2. **Tenant default → offer override resolution** — ✅ **SHIPPED 2026-09-30** (19 tests).
   `shipping_charges.resolve_options(offer, tenant_config, country=…, box=…)` returns
   `{options, mode, source, needs}`. Removes the forty-times problem: the tenant says it once in their zones
   and an offer only departs from it. Schema gains `offer.shipping.eligibility` and `override`.

   - **`source` names which layer answered** — `offer_options` / `offer_override` / `zone` / `unserved` /
     `none`. A tenant asking why a buyer saw a price needs to know which of three layers decided, exactly as
     `refund_policy.resolve` reports its source.
   - **`needs` says what is missing**: `carrier` for a live zone, `box_price` for a by-box zone whose packed
     box has no price for that country, `zone` for a destination nothing claims. **Empty options WITH a
     `needs` is "not answerable yet", never "free"** — a caller rendering it as free ships for nothing.
   - **`mode` is `""` when no shipping is offered at all** (the offer does not ship, or nothing serves the
     destination). Empty rather than `free`, because a caller switching on `mode` alone would read free as
     "charge nothing and ship it" — which for an unserved country means posting a parcel somewhere the tenant
     never agreed to send one. `""` matches no branch and forces the caller to look.
   - **An override replaces the zone's RULE but never its services.** Which speeds a tenant can ship is a
     capability; an offer can change the price, not what the carrier will carry.
   - **An explicit `offer.shipping.options[]` still wins.** It is what `stripe_shipping_options` already reads,
     it is deployed, and a tenant who hand-built one meant it.

   **Checkout is deliberately NOT switched over yet.** `resolve_options` needs a destination and Checkout has
   none at session-creation time, so wiring it there would mean assuming a country — showing a Canadian buyer
   the US zone's prices. The no-element path stays on the explicit table until the element can supply a
   country (phase 5). Zones resolve for the element's benefit first.
3. **Offer B end to end** — ✅ **SHIPPED 2026-09-30** (18 tests). `checkout_shipping()` resolves the tenant's
   zones through the offer's override and hands Checkout at most ONE priced set. No element, no address form,
   nothing public.

   **The constraint that shaped it, and it is narrower than this plan first implied.** Stripe fixes
   `shipping_options` when the session opens and never asks again, so it shows ONE list to every buyer
   whatever address they type. Zone pricing is therefore safe here only when **every allowed destination
   agrees**:

       US $7.00, CA $7.00     ->  one option, correct for everyone who can reach checkout
       US $7.00, CA $12.99    ->  no option is right for both. Charge nothing, and SAY WHY.

   Where they disagree, `reason` names it (*"shipping costs differ by destination (CA [1299], US [700]) and
   Stripe shows one list to every buyer"*) and it is logged — a tenant whose zones are not being charged needs
   to know which of their own settings stopped it, not discover it as silently free shipping.

   - **Agreement means the same priced SERVICES, not merely the same total.** A buyer offered Ground-only in
     one country and Ground-plus-Overnight in another is being shown a list that is wrong for one of them.
   - **One unpriceable destination poisons the whole session** — a live zone with no carrier means no price
     for anyone, because the buyer picks the country after the options are fixed.
   - **An offer-level flat override RESOLVES the multi-country problem** rather than working around it: it is
     destination-independent by construction, so a tenant with disagreeing zones can still charge for shipping
     on one offer.
   - **`allowed_countries` now comes from the zones**, with the old hardcoded US/CA as the fallback when none
     are configured — an empty allowed list would take checkout down, and silently changing behaviour for
     tenants who configured nothing is not an improvement.
   - **The config is only read when it can matter**: a digital cart, or an offer marked not-shipping, pays for
     no lookup. The read fails open with a logged reason, because it runs in the buyer's path and a settings
     table that blinked must not refuse a sale.
4. **Flat-rate box pricing (tier 2)** — ✅ **SHIPPED 2026-09-30** (16 tests).
   `shipping_charges.packed_box_price(items, products, tenant_config, country)` packs the cart with the
   existing `shipping_packing.pack` and prices it from the chosen box's `flat_rate` for that country. No
   carrier call, no postcode — the country and nothing else.

   `resolve_options` now takes a computed `box_amount` rather than a box document, so it stays pure and knows
   nothing about packing; `checkout_shipping` prices per country, because a flat-rate box costs a different
   amount in each.

   Three distinct refusals, because each needs a different thing from the tenant: `no_dimensions` (the products
   have no sizes, so the packer will not invent a parcel), `no_box` (fits nothing listed), `no_price` (fits,
   but that box has no price for this country). None of them is ever 0.

   **CORRECTION — the reach of this tier is narrower than this plan implied.** I wrote that multi-parcel would
   price naturally by summing, two boxes being two flat rates. That is how carriers bill and **not how this
   packer works**: `shipping_packing` has two strategies, everything in one shared box or *"one parcel per
   thing... the honest fallback"*, and the per-item fallback **assigns no box at all**. So a cart larger than
   one listed box cannot be flat-rated, and needs tier 3 or a tenant-set flat amount. Tier 2 covers
   **single-box carts**, which is still most small-parcel domestic commerce but is not "most orders" without
   qualification.

   That also means the multi-parcel blocker (phase 7) gates more than the plan said: not only bundles under
   live rating, but any by-box cart that outgrows one box.
5. **A declared destination** — ✅ **BACKEND SHIPPED 2026-09-30** (7 tests). `/checkout` accepts
   `ship_to_country`, and declaring one lifts the unanimity restriction: there is only one zone to satisfy, so
   zones that disagree stop forcing us to charge nothing.

       no declaration   US $7.00 / CA $12.99  ->  charges nothing
       ship_to_country=US                     ->  charges $7.00,  allowed_countries = [US]
       ship_to_country=CA                     ->  charges $12.99, allowed_countries = [CA]

   **The address is still collected — I had this wrong in the design above.** The plan said to "omit
   `shipping_address_collection` entirely" so Stripe could not change the destination. But a parcel needs a
   STREET, and the country alone is not an address; omitting collection would leave nothing to ship to. The
   correct move is to **narrow `allowed_countries` to the declared country**: Stripe still collects the
   address, and the only part of it that can move a tier 1 or tier 2 price — the country — is fixed. Within one
   country those tiers are destination-independent by definition, so the rest of the address cannot change the
   number.

   A country the tenant does not ship to is ignored rather than honoured: a country typed into a URL is not a
   zone.

   **PAGE COMPONENT ✅ SHIPPED 2026-09-30** (22 tests), and because phase 6 landed first it shows real prices
   rather than deferring them to Checkout:

       Shipping
       Where should we ship your order?   [ US ▾ ]
         ( ) Ground            $6.99
         ( ) Overnight        $24.99

   Seven registration points, all mechanical: `composition_rules.json` (element, order, governed),
   `runtime/html.py` (renderer + registry + script + the CTA param), `documents.py`, `ai_floor.py`, and the
   builder's state/editor/save/load. The Vue composer needed no edit — it imports the rules JSON directly.

   What the element puts in the artifact: **an empty shell**. No prices, no country list, nothing but the three
   data attributes the fetch needs. It starts `hidden` so an unpopulated selector never flashes, and renders
   nothing at all for a digital offer, with no API base, or when disabled.

   - **The radio's value is the SERVICE TOKEN, never the amount.** The author's rule: a browser must not be
     able to submit a $2.00 option it was never offered. The server re-derives the price.
   - **An unknown is never shown as "Free".** `needs: carrier` or `box_price` becomes *"Shipping is calculated
     at checkout"* — the honest answer, where "Free" would be a promise the tenant did not make.
   - **`needs: zones` keeps the element hidden entirely**, so a tenant who has configured nowhere to ship gets
     no empty dropdown.
   - **A tier change re-asks.** A different tier is a different parcel, so it is a different price.
   - **A failed fetch is silent and the element stays hidden.** A shipping selector that cannot reach the API
     must never block a sale: the buyer checks out and Stripe collects the address as it does today.
   - **The AI may not author it** (`ai_floor`), because there is nothing to write — the whole content is
     computed from the tenant's zones.
   - **OPT-IN, not on by default.** It is deliberately absent from every `offer_types[*].sections`: adding it
     there would put a destination selector above the buy button on every existing physical page at its next
     publish, and only tenants who ship multi-country need one.
6. **`GET /shipping-quote`** — ✅ **SHIPPED 2026-09-30** (15 tests), and it came BEFORE the element rather
   than after. Returns `{ships, countries, country, options, needs, mode, source}`; never accepts an amount.

   **Reordered deliberately.** The element needs the country LIST as well as prices, and seeding that list
   into a static page reintroduces exactly the stale-snapshot problem this plan forbids — a tenant who adds a
   zone would not see it until republish. With the endpoint first, the element asks for both in one call and
   nothing in the artifact can go stale.

   **It lives on the checkout function**, because a quote needs precisely what checkout already loads (the
   offer, its products, the tenant's shipping config) and every grant for them. It branches before checkout's
   redirect-url validation, since a quote needs no `success_url`.

   **The abuse picture is smaller than this plan assumed.** For tiers 1–2 a quote makes **no carrier call** —
   it is a config read plus arithmetic — so it costs nothing to abuse beyond ordinary API traffic. The
   cache-and-throttle the plan calls for becomes a hard prerequisite when **tier 3** arrives and each quote
   spends money at a carrier. Stated so nobody reads its absence as an oversight.

   `needs` is never a zero price: `zones` (the tenant has configured nowhere to ship), `country` (nothing
   chosen, or one the tenant does not serve), `carrier`, `box_price` (with a `box_reason` naming which of the
   three packing refusals it was). A page rendering an unknown as "Free shipping" would make a promise the
   tenant did not.

   **`zones` exists because the deployed endpoint answered unactionably.** Called against the real dev tenant
   it returned `needs: country` alongside `countries: []` — advice nobody can act on, and an element would have
   rendered an empty dropdown. "Choose one of these" and "the tenant has configured nowhere to ship" are
   different facts and now say so. Found by hitting the live route, not by a test.
7. **Multi-parcel** — ✅ **PACKING SHIPPED 2026-09-30** (13 tests). `shipping_packing` gains a **multi-box**
   strategy between "one shared box" and "per item": first-fit-decreasing over the catalog, so a cart that
   outgrows one box becomes several NAMED parcels instead of per-item parcels with no box.

   **This is what unblocks bundles**, and not only for tier 3 as this plan said. The per-item fallback assigns
   no box, so a flat-rate-box price had nothing to look up — a 6-bottle bundle could not be quoted at all. Now
   two Mediums cost two flat rates, which is how carriers bill.

   It reuses an extracted `_best_box` rather than testing fit a second way, because this module's docstring
   warns that two implementations of *"what parcel is this"* would disagree and the one that priced the order
   would not be the one that bought the label.

   Boundaries kept deliberately: an item fitting NO box still falls through to per-item, because splitting the
   rest into boxes and leaving one homeless would report a parcel count nobody can post; a single group is
   never reported as multi-box, since strategy 2 already tried one box; weight limits apply per parcel; and
   items with no dimensions still produce NO parcels rather than an invented one.

   **STILL OPEN: buying multi-parcel LABELS.** `handlers/shipping.py:289` still refuses, and that is a
   fulfilment change (N labels, N tracking numbers, per-parcel shipment records) which belongs with
   `plans/SHIPPING_PROVIDERS.md`. Pricing a bundle and posting one are now different questions with different
   answers, and that is worth knowing before a tenant sells one.

## Carriers are CHOSEN, never typed — and services are discovered, not invented (author, 2026-09-30)

> *"Carriers cannot be manually entered in free-text form. That begs for typos and human error. They should be
> choices that come straight from the API."*

Right, and the typo is the smaller half of the problem. **A `service_code` a tenant invents will never match a
real carrier rate.** The Services section currently accepts `ground`, `two_day`, `overnight` — reasonable words
that no carrier uses. Shippo's token for USPS ground is `usps_ground_advantage`; a tenant who types `ground`
has configured a service that can never be quoted, and nothing tells them until a buyer sees no options.

So the fix is not only a picker. It is that **the service identity must come from the carrier**, which is what
the second ask provides.

### What already exists (this needs no new provider work)

- **`domain/carriers.carrier_options()`** — a static registry of carriers and their services, built for a
  picker. Four carriers today plus `other`.
- **`ShippingProvider.test_connection()`** returns `{"ok", "message", "carriers": [...]}` — the tenant's
  **actually connected** carriers, which is better than a static list: a tenant with no UPS account should not
  be offered UPS.
- **`ShippingProvider.rates(from_address, to_address, parcel)`** returns normalised rates carrying
  `carrier`, `service`, `service_token`, `amount`, `estimated_days`, `rate_id`.
- **`shipping_packing.pack()`** turns products + a box into the parcel those rates need.
- **The dev tenant has Shippo connected with a live key** (`connection_status: connected`), so this is
  buildable now rather than theoretical.

### The rate viewer, and what it is actually FOR

> *"Create a section where the tenant can select one or more products, select a box, and click a button that
> will list them their options (all carriers and their rates). They can then choose... and THAT will be the
> carrier/rate that appears in the Services section."*

    Try a rate
      Products  [ Creatine Gummies ×] [ Whey Protein ×]      <- the Offers modal's chip precedent
      Box       [ Medium (10x8x6) ▾ ]
      Ship to   [ US ] [ 80204 ]
      [ Get rates ]

      USPS   Ground Advantage      $8.42    5–7 days   [ Use this ]
      USPS   Priority Mail        $11.90    2–3 days   [ Use this ]
      UPS    2nd Day Air          $17.31    2 days     [ Use this ]

**What "Use this" harvests is the SERVICE IDENTITY, not the price.** That distinction decides whether the
feature is sound: a rate is destination-specific and goes stale within days, but `usps_ground_advantage` is
stable and is what a later live quote needs to match. The prices are shown as CONTEXT — they tell the tenant
what a flat rate should be set to — and are deliberately not stored as the zone price. A tenant who wants that
number types it into a zone themselves.

So the viewer is a **service discovery tool** that shows prices, not a price import. A row that wrote its
amount into a zone would be a snapshot with a timestamp nobody can see.

### Build order

1. **The pickers**, which make the existing fields safe: Carrier becomes a select sourced from the tenant's
   connected carriers (falling back to `carrier_options()` when no provider is connected), and "Allowed
   carriers" becomes dismissible chips rather than a comma-separated string.
2. **The rate viewer**, which makes the Service CODE correct rather than merely well-spelled.

One before the other because the first is useful even for a tenant with no carrier connected, and the second
cannot run without one.

### ✅ BOTH SHIPPED 2026-09-30 (24 tests)

**Pickers** — `GET /shipping/carriers` returns the tenant's CONNECTED carriers via `test_connection()`, falling
back to the `carrier_options()` registry with a message saying why. Carrier is a select; Allowed Carriers is
dismissible chips. A carrier the registry does not know is still offered: the provider is the authority on what
this account can quote.

**Rate viewer** — `POST /shipping/rate-preview` packs the chosen products into a box and asks the carrier.

    Try a rate
      Products  [ Gummies ×] [ Whey ×]          Box [ Medium ▾ ]   Ship to [ US ] [ 80204 ]
      USPS  Ground Advantage   $8.42   6 days   code usps_ground_advantage   [ Use this ]
      UPS   2nd Day Air       $17.31   2 days   code ups_2nd_day_air         [ Use this ]

- **"Use this" copies the SERVICE, never the amount** — carrier, `service_token`, and the carrier's own transit
  estimate become the buyer-facing window. A test asserts `adoptRate` does not touch `amount`, because the
  temptation to import the price is exactly the mistake: a rate is destination-specific and stale within days.
- **The destination defaults to the tenant's own ship-from**, merged field-by-field with anything they type, so
  a partial override keeps a complete address. A carrier will not quote a postcode that does not exist, and
  inventing one would fail in a way that looks like our bug.
- **A named box is rated rather than the packer's preference**, because a tenant comparing boxes wants THIS one
  priced.
- **The parcel count is reported.** A multi-box order is several labels, and showing one parcel's rate as the
  order's would understate it.
- Every failure is an answer: `missing_ship_from`, `no_dimensions` (naming Products as the fix),
  `missing_provider`, and a 502 that relays what the carrier said.

## Why only UPS and USPS came back (measured 2026-09-30)

The author asked, looking at a live preview that returned only those two. The answer is the Shippo
**sandbox**, not our code. Reading the account's own `/carrier_accounts`:

    ups usps canada_post chronopost colissimo couriersplease correos deutsche_post
    dhl_express dpd_de dpd_uk hermes_uk lso sendle        <- all active=True, ALL test=True

Three facts explain it:

1. **Every account is `test=True`** with a `shippo_*` id — Shippo's shared sandbox accounts, not the tenant's
   own. The API key is a `shippo_test_*` token.
2. **FedEx is not there at all.** Shippo's sandbox provides no FedEx account; it requires connecting a real
   one. So FedEx cannot quote, and no amount of code changes that.
3. **The rest are origin-restricted.** `canada_post`, `chronopost`, `colissimo`, `correos`, `deutsche_post`,
   `dpd_de`, `dpd_uk`, `hermes_uk`, `sendle` cannot quote a shipment ORIGINATING in the US, which is why a
   US→CA and a US→GB preview also returned USPS only. `dhl_express` is connected and returns nothing on these
   lanes for the same reason.

**In live mode with the tenant's own carrier accounts, FedEx and DHL appear without any change here.** Worth
knowing before chasing it as a bug.

**A smaller finding worth acting on eventually:** `/shipping/carriers` offers all nine "connected" carriers,
most of which can never produce a rate from a US origin. The picker is therefore honest about what the account
has and misleading about what it can do. Filtering by what actually quotes would need a probe per carrier, so
the cheaper fix is to say which are test accounts.

## Services adopted from a rate are LOCKED

The author, 2026-09-30: *"make the Service section read-only — don't allow tenants to change the values that
were pre-selected."*

Done, with one deliberate exception. A service carries `source`:

- **`rate`** — adopted from a live quote. Service code, carrier and transit days are the CARRIER's and render
  read-only. Changing one is how a service becomes unquotable, which is the whole failure this feature exists
  to end.
- **`manual`** — typed by hand. Still editable, and labelled *"nothing has checked this code against a
  carrier"*, because a tenant with no provider connected must still be able to configure something.

**The buyer-facing label stays editable on both.** It is how the tenant talks to their customers, not a fact
about the carrier — locking it would stop them writing "Arrives by Friday" over "Ground Advantage" for no
safety gain.

`enabled_services` also gained a runtime validator, which it never had: the JSON schema described the shape
and nothing enforced it. It refuses a duplicate service code (the second is dead configuration the tenant
believes is live), a missing code, an inverted transit window, and an unknown `source`.

## Open

- **Does a full address get collected on the page, or country + postcode?** Recommended the latter, but a
  tenant offering a real address form pre-checkout is not unreasonable for high-value goods.
- **What happens when the buyer's quote expires between page and pay?** Re-quote and show a changed price, or
  honour the stale one at the tenant's expense. Needs a tenant-level rule, not a silent default.
- **Display variants** (radio / cards / dropdown) — the author listed them. Cheap, and they belong with the
  composer's element registry rather than as element-specific config.
- **Handling fee semantics.** `markup_amount` per parcel, per order, or per item? It changes the number on a
  multi-item cart and nobody would notice it was wrong.
