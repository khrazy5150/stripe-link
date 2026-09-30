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

**The author's design requires A.** A carrier-computed figure on the page is not reachable any other way.

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

## Phases

1. **`ShippingConfig.enabled_services` + a real UI for it**, replacing the two dead inputs. Ships value alone:
   it is the first time a tenant can say what they offer, and it makes `markup_amount`/`free_shipping_threshold`
   honest instead of decorative.
2. **Tenant default → offer override resolution** in `shipping_charges`. Removes the forty-times problem.
3. **Offer B end to end** — server picks the default service, no element, no address form. The common case, and
   it needs nothing public.
4. **`POST /shipping/quote`**, public, cached, throttled, single-parcel only. Returns services and prices; never
   accepts an amount.
5. **Multi-parcel quoting** — the blocker for bundles.
6. **The Shipping Element** (offer C/D): the page component, the minimal destination form, and the
   omit-Stripe's-address-collection change. Last, because it is the only part that alters the buyer's flow.

## Open

- **Does a full address get collected on the page, or country + postcode?** Recommended the latter, but a
  tenant offering a real address form pre-checkout is not unreasonable for high-value goods.
- **What happens when the buyer's quote expires between page and pay?** Re-quote and show a changed price, or
  honour the stale one at the tenant's expense. Needs a tenant-level rule, not a silent default.
- **Display variants** (radio / cards / dropdown) — the author listed them. Cheap, and they belong with the
  composer's element registry rather than as element-specific config.
- **Handling fee semantics.** `markup_amount` per parcel, per order, or per item? It changes the number on a
  multi-item cart and nobody would notice it was wrong.
