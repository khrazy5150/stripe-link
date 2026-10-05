# One parcel, one label: grouping an order with its upsells

## The problem, in money

A real funnel on 2026-10-04. One buyer, one checkout, one address:

| order | paid | shipping collected |
|---|---|---|
| `b1vdetVW` (cart: Creatine Gummies + Whey Protein) | $87.01 | **$6.20** |
| `b1vdetVW-U1` (upsell) | $9.00 | $0.00 |
| `b1vdetVW-U2` (upsell) | $17.86 | $0.00 |

The Orders screen offered three labels at **$18.20**. The buyer paid **$6.20**. The tenant is **$12.00 out
of pocket on a $113 sale** — and would never find out, because the loss lands on a carrier invoice weeks
later rather than anywhere near the order.

**The upsells were charged $0 BECAUSE they ride in the same parcel.** `shipping_promise`'s
`combined_delta` re-packs the original lines together with the upsell, re-rates, and charges the
difference — which came to zero, correctly, because the carrier charges nothing more to carry them. That
answer is only honest if one parcel actually ships.

So the margin bug and the screen bug are **the same bug**: the platform made a promise on the tenant's
behalf and then handed them a screen that cannot keep it.

## What is actually split

Narrower than it first looks, which is what makes it tractable.

**Cart items and order bumps are already one order.** They ride a single Checkout Session, land as one
order document with several line items, and pack into one parcel. The example above printed one label for
two products and would have done so for ten.

**Only upsells split**, for a structural reason: an upsell is a PaymentIntent we create ourselves, so it
becomes its own order document. That is **right for money** — separate charges, separate ledger entries,
separately refundable — and **wrong for fulfilment**, where it is one parcel to one address from one
purchase occasion.

> Money and fulfilment want different groupings. The order is the unit of PAYMENT. What is missing is a
> unit of FULFILMENT.

## The key already exists

Every order in the group carries the same `session_id`, and the screen is already showing the
relationship:

    b1vdetVW       the purchase
    b1vdetVW-U1    its first upsell
    b1vdetVW-U2    its second

`domain/order_reference.py` derives that suffix from the shared session, and says so itself: *"a
post-purchase order carries its PARENT's session id."* The knowledge is in the system; the Orders screen
treats each row as independent anyway.

So no new identity is needed. A fulfilment group is **the orders sharing a `session_id`**.

## The design decision

When the group ships, where does the shipment attach?

**A. To the parent order, upsells fulfilled by reference.** `shipment_id_for` already derives
`shp_<order_id>_outbound_1` from the order id, and that derivation is load-bearing — it is the
idempotency key that stops a double-clicked Buy Label becoming two labels, which is money that cannot be
un-spent by refreshing a page. Keying on the parent keeps all of that untouched; the upsells read their
fulfilment state through the group.

**B. A fulfilment-group record the orders point at.** Cleaner if partial fulfilment ever matters — two of
three items shipping because one is on backorder — but it introduces a second identity for a thing that
already has one, and `shipment_id_for` would need a new derivation.

**Recommended: A.** Partial fulfilment is a real need eventually, but it is a *different* feature:
splitting a group deliberately is what `shipment_id_for(..., sequence=2)` was already built for, and B
can be introduced later for that without unpicking A. Doing it now trades certain work against a
speculative requirement.

## What it touches

- **The Orders screen.** One row per group, showing the combined line items and a single rate. The
  per-order rows become the group's contents rather than peers.
- **Packing and rating.** The union of every line in the group — which is exactly what `combined_delta`
  already packs to produce the $0, so the two finally agree.
- **Buying.** One rate, one label, one shipment keyed on the parent order.
- **The tracking email.** One message listing everything, rather than three saying "your order is on its
  way" to someone expecting one parcel.
- **The overdue notice** (P4c) fires per group, or a tenant gets three warnings about one box.
- **`record_shipping_cost_entry`.** The postage is one cost against a group that collected revenue on one
  of its orders; the ledger's `shipping_margin` is wrong until both sides agree on the unit.

## Open

- **An upsell that arrives after the parent shipped.** Unlikely — upsells happen seconds later in the same
  flow — but possible if a tenant is fast. The group would need to either refuse to re-use a spent
  shipment or deliberately start `sequence=2`.
- **Mixed destinations.** Nothing stops an upsell carrying a different shipping address today, since it is
  read from the original session. Grouping must verify the addresses match rather than assume it.
- **What the tenant sees for money.** Grouping fulfilment must not group REVENUE: the Orders screen's
  PAID column, the ledger and refunds stay per-order, or a refund of one upsell becomes ambiguous.
