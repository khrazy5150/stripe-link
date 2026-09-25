"""Can this order be shipped, and if not, whose problem is it?

plans/ORDER_FULFILMENT.md keeps three gates deliberately distinct, because conflating them is what produces
the unactionable "Rates Unavailable" with no path forward:

  TENANT gate   no provider key, no ship-from address     blocks EVERY row -- one banner, not forty rows.
                                                          Already answered by `label_readiness`.
  ORDER gate    no address, wrong country, already gone    blocks this row and the tenant cannot fix it.
                                                          Not a failure: it simply is not a parcel.
  PRODUCT gate  an item with no dimensions                 blocks this row and the tenant CAN fix it --
                                                          the only gate that earns a call to action, and
                                                          it names the product rather than saying
                                                          "package required".

Everything here is pure. The handler joins the documents; this decides what they mean.
"""
from typing import Any

# Where a label can be bought today. Checkout already allows CA (handlers/checkout.py), so a Canadian order
# can arrive that we cannot label without a customs declaration -- it must be refused HERE, in the row,
# rather than at the moment money is spent.
LABELABLE_COUNTRIES = ("US",)

NOT_SHIPPABLE = "not_shippable"
NEEDS_INFO = "needs_info"
READY = "ready"
SHIPPED = "shipped"


def product_index(products: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Every id a line might name -> the product document.

    An order line carries `stripe_product_id` and `stripe_price_id`; `packable_items()` keys on our own
    `product_id`. Without this an order cannot be packed at all, however well measured its products are.
    """
    index: dict[str, dict[str, Any]] = {}
    for product in products or []:
        if not isinstance(product, dict):
            continue
        for key in (product.get("product_id"), product.get("stripe_product_id")):
            identifier = str(key or "").strip()
            if identifier:
                index.setdefault(identifier, product)
        for price in product.get("prices") or []:
            identifier = str((price or {}).get("stripe_price_id") or "").strip()
            if identifier:
                index.setdefault(identifier, product)
    return index


def resolve_order_lines(order: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Order lines with `product_id` filled in wherever the catalogue can be reached.

    A line we cannot resolve is KEPT, with no product_id. Dropping it would silently shrink the parcel --
    the packer would quote postage for two items when three are going in the box.
    """
    resolved = []
    for line in order.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        product = None
        for key in ("product_id", "stripe_product_id", "stripe_price_id"):
            product = index.get(str(line.get(key) or "").strip())
            if product:
                break
        entry = dict(line)
        if product:
            entry["product_id"] = str(product.get("product_id") or "")
        resolved.append(entry)
    if resolved:
        return resolved
    # Older orders and renewals carry a `product` block instead of line_items.
    product_block = order.get("product") or {}
    identifier = str(product_block.get("product_id") or "").strip()
    if identifier:
        return [{"product_id": identifier, "quantity": 1, "name": product_block.get("name") or ""}]
    return []


def _address_country(order: dict[str, Any]) -> str:
    address = order.get("shipping_address") or {}
    return str(address.get("country") or "").strip().upper()


def order_gate(order: dict[str, Any], *, shipment: dict[str, Any] | None = None,
               countries: tuple[str, ...] = LABELABLE_COUNTRIES) -> list[str]:
    """Why this order is not a parcel the tenant can act on. Empty means nothing here stands in the way.

    None of these are the tenant's mistake, so none of them get a call to action.
    """
    reasons = []
    if not (order.get("shipping_address") or {}):
        reasons.append("No shipping address — this order is not a physical shipment.")
    else:
        country = _address_country(order)
        if country and country not in countries:
            reasons.append(
                f"Ships to {country}. International labels are not supported yet — "
                "mark it shipped manually once you have posted it.")
    status = str(order.get("payment_status") or order.get("status") or "").strip().lower()
    if status in {"refunded", "cancelled", "canceled"}:
        reasons.append(f"Order is {status}.")
    if (shipment or {}).get("status") in {"purchased", "shipped"}:
        reasons.append("Already shipped.")
    return reasons


def product_gate(lines: list[dict[str, Any]], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What is missing from the CATALOGUE before this order can be packed.

    Returns the products to fix, not a sentence, because this gate is the one with a call to action and the
    screen needs the ids to link to.
    """
    unmeasured: list[dict[str, str]] = []
    unresolved = 0
    for line in lines or []:
        product_id = str(line.get("product_id") or "").strip()
        product = products_by_id.get(product_id) if product_id else None
        if not product:
            unresolved += 1
            continue
        fulfillment = product.get("fulfillment") or {}
        if fulfillment.get("requires_shipping") is False:
            continue
        own = fulfillment.get("item_dimensions") or {}
        has_own = all(own.get(field) for field in ("length_in", "width_in", "height_in"))
        # A declared box is the EXCEPTION route and it is still a complete answer: an item that always
        # ships alone in a known box needs no dimensions of its own.
        ships_alone_with_box = bool(fulfillment.get("ships_alone")) and all(
            fulfillment.get(field) for field in ("length_in", "width_in", "height_in"))
        if not has_own and not ships_alone_with_box:
            unmeasured.append({
                "product_id": product_id,
                "name": str(product.get("name") or product_id),
            })
    return {"unmeasured": unmeasured, "unresolved_lines": unresolved}


def order_fulfilment_state(
    order: dict[str, Any],
    *,
    products_by_id: dict[str, dict[str, Any]] | None = None,
    index: dict[str, dict[str, Any]] | None = None,
    shipment: dict[str, Any] | None = None,
    countries: tuple[str, ...] = LABELABLE_COUNTRIES,
) -> dict[str, Any]:
    """One order's fulfilment state, computed once on the server.

    The screen must never compute this itself: the buy endpoint and the row would then be able to disagree
    about whether an order is eligible, and the tenant would find out which was right by pressing a button.
    """
    index = index if index is not None else {}
    products_by_id = products_by_id if products_by_id is not None else {}
    lines = resolve_order_lines(order, index)

    shipped = (shipment or {}).get("status") in {"purchased", "shipped"}
    blocked = order_gate(order, shipment=shipment, countries=countries)
    gate_products = product_gate(lines, products_by_id)

    if shipped:
        status = SHIPPED
    elif blocked:
        status = NOT_SHIPPABLE
    elif gate_products["unmeasured"] or gate_products["unresolved_lines"]:
        status = NEEDS_INFO
    else:
        status = READY

    reasons = list(blocked)
    if status == NEEDS_INFO:
        names = [item["name"] for item in gate_products["unmeasured"]]
        if names:
            one = len(names) == 1
            reasons.append(
                f"{_and_more(names)} {'has' if one else 'have'} no size — "
                f"add {'its' if one else 'their'} measurements to buy a label.")
        if gate_products["unresolved_lines"]:
            # Not the tenant's mistake and not fixable from the products screen, so say what it IS: the
            # line names a Stripe product this catalogue does not hold (a deleted product, or a test-mode
            # sale being read by the production backend).
            reasons.append(
                f"{gate_products['unresolved_lines']} item(s) are not in your catalogue, so this order "
                "cannot be packed automatically.")

    return {
        "status": status,
        # Selectable in the table. Shipped orders and non-parcels are not failures, they are simply not
        # work; only a READY row can have a label bought for it.
        "eligible": status == READY,
        "gate": "order" if blocked else ("product" if status == NEEDS_INFO else ""),
        "reasons": reasons,
        # Only when the PRODUCT gate is the live one. An order with nowhere to ship to is not a measuring
        # problem, and offering "+ Add package info" there sends the tenant to fix the wrong thing --
        # they would measure the product and the row would still not be shippable.
        "needs_measurement": gate_products["unmeasured"] if status == NEEDS_INFO else [],
        "lines": lines,
        "shipment": shipment or None,
    }


def _and_more(names: list[str], shown: int = 2) -> str:
    if len(names) <= shown:
        return " and ".join(names) if len(names) == 2 else ", ".join(names)
    return f"{', '.join(names[:shown])} and {len(names) - shown} more"
