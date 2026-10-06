"""One parcel, one label — grouping an order with its upsells.

plans/FULFILMENT_GROUPS.md. A real funnel collected **$6.20** of shipping from a buyer and was offered
**$18.20** of labels: three boxes to one address, $12 lost on a $113 sale, surfacing on a carrier invoice
weeks later rather than anywhere near the order.

The upsells were charged **$0 because they ride in the same parcel** — `shipping_promise.combined_delta`
re-packs the order's lines together with the upsell, re-rates, and charges the difference, which is
correctly nothing. That answer is only honest if one parcel actually ships. The margin bug and the screen
bug are the same bug.

**Money and fulfilment want different groupings.** An upsell is a PaymentIntent we create ourselves, so it
is its own order: right for money (separate charges, separate ledger rows, separately refundable) and
wrong for fulfilment, where it is one parcel to one address from one purchase. The order is the unit of
PAYMENT; this is the unit of FULFILMENT.

**No new identity.** Every order in a group already shares a `session_id`, and `order_reference` already
shows the relationship as `b1vdetVW` / `-U1` / `-U2`, deriving the suffix from exactly that. The knowledge
was in the system; only the screen treated the rows as independent.
"""
from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def group_key(order: Any) -> str:
    """What makes two orders one parcel. The session, falling back to the order's own id.

    An order with no session (an invoice, a legacy row) is its own group rather than joining a bucket of
    everything else that also lacks one -- grouping unrelated buyers' parcels together would be a far
    worse bug than the one this fixes.
    """
    if not isinstance(order, dict):
        return ""
    return _text(order.get("session_id")) or _text(order.get("order_id"))


def destination_key(order: Any) -> str:
    """Where this order is going, flattened for comparison.

    Checked rather than assumed: nothing stops an upsell carrying a different address today, since it is
    read back from the original session, and packing two destinations into one box would put a parcel
    through the wrong door (plans/FULFILMENT_GROUPS.md, Open).
    """
    address = (order or {}).get("shipping_address") or {}
    if not isinstance(address, dict):
        return ""
    parts = (address.get("street1"), address.get("street2"), address.get("city"),
             address.get("state"), address.get("postal_code"), address.get("country"))
    return "|".join(_text(part).upper() for part in parts)


def group_orders(orders: list[dict[str, Any]] | None) -> list[list[dict[str, Any]]]:
    """Orders bucketed into fulfilment groups, each group's own order first.

    The PARENT leads — the order whose id the others extend — because the shipment is keyed on it
    (`shipment_id_for` derives the id, and that derivation is the idempotency key stopping a
    double-clicked Buy Label from becoming two labels).

    A differing destination splits the group. Two parcels to two doors is the correct answer there, and
    the tenant sees them as two lines rather than one impossible box.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order_of_appearance: list[tuple[str, str]] = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        key = (group_key(order), destination_key(order))
        if key not in buckets:
            buckets[key] = []
            order_of_appearance.append(key)
        buckets[key].append(order)
    out = []
    for key in order_of_appearance:
        members = buckets[key]
        # Shortest id first: `order_X` precedes `order_X_upsell_1`, which is the parent by construction.
        members.sort(key=lambda o: (len(_text(o.get("order_id"))), _text(o.get("order_id"))))
        out.append(members)
    return out


def group_lines(group: list[dict[str, Any]] | None,
                index: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every shippable line across the group, as the packer wants them.

    The union is the point: it is exactly what `combined_delta` packed to decide the upsell added nothing,
    so for the first time the number the buyer was charged and the boxes the tenant buys come from one
    computation.

    `resolve_order_lines` does the hard half and is reused rather than re-done. A Stripe line item carries
    `stripe_price_id` and a NAME, not our `product_id` -- a first version of this read `product_id`
    straight off the line and silently dropped every cart item, packing only the upsells, which is the
    exact failure that function's docstring warns about.
    """
    from stripe_link.domain.fulfilment import resolve_order_lines

    lines: list[dict[str, Any]] = []
    for order in group or []:
        for line in resolve_order_lines(order, index or {}):
            product_id = _text(line.get("product_id"))
            if not product_id:
                # Kept out of the PARCEL but not out of sight: an unresolvable line means the catalogue
                # could not be reached, and quoting a box for two items when three are going in it is how
                # a tenant ends up paying a carrier's re-weigh surcharge.
                continue
            lines.append({"product_id": product_id,
                          "price_id": _text(line.get("price_id") or line.get("stripe_price_id")),
                          "quantity": max(1, int(line.get("quantity") or 1))})
    return lines


def parcel_contents(parcel: Any, products_by_id: dict[str, Any] | None) -> list[str]:
    """The product NAMES in a parcel, for a tenant deciding what to put in which box.

    "Medium box: Creatine Gummies, Whey Protein" is a packing slip. "Medium box: 2 items" is a number they
    have to go and look up.
    """
    # COUNTED, not repeated. A "3 Items" tier packs as three units, and listing the same name three
    # times reads as three different things to put in the box rather than three of one.
    counts: dict[str, int] = {}
    order: list[str] = []
    for product_id in (parcel or {}).get("packed_from") or []:
        product = (products_by_id or {}).get(_text(product_id)) or {}
        name = _text(product.get("name")) or _text(product_id)
        if name not in counts:
            order.append(name)
        counts[name] = counts.get(name, 0) + 1
    return [name if counts[name] == 1 else f"{name} x{counts[name]}" for name in order]


def group_parcels(group: list[dict[str, Any]] | None, *, products_by_id: dict[str, Any],
                  boxes: list[dict[str, Any]] | None,
                  index: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The boxes this group actually needs — one line, and one label, per parcel.

    As few as the items allow, which is the packer's whole job and the reason the tenant should not be
    choosing. Each carries its box name and contents so the expanded row reads like a packing slip.
    """
    from stripe_link.domain.shipping import packable_items
    from stripe_link.domain.shipping_packing import pack

    lines = group_lines(group, index)
    if not lines:
        return []
    parcels = pack(packable_items(lines, products_by_id), boxes or [])
    # `item_count` counts THINGS, which `contents` deliberately no longer does: it collapses repeats into
    # "NAD Supplement x2", so counting its entries reports 4 items for a box holding 5. Stated here, from
    # `packed_from` (one entry per unit), so no caller has to know that distinction or reach into the
    # packer's internals to count units for itself.
    return [{**parcel,
             "contents": parcel_contents(parcel, products_by_id),
             "item_count": len(parcel.get("packed_from") or [])}
            for parcel in parcels]
