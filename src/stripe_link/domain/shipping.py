"""Shipping domain — pure, no I/O.

Starts with the destination address, because nothing else in shipping can happen without one. Checkout has
been collecting a shipping address from buyers of physical goods all along (`shipping_address_collection`
in handlers/checkout.py), and the order record never read it: every order ever placed here knows who bought
and not where it goes. A label cannot be bought, a rate cannot be quoted, and an integration has nothing to
hand a provider.
"""
from typing import Any

# The address shape used everywhere in shipping. Deliberately identical to ShippingConfig's `$defs/address`
# (ship-from and return-to), so a provider call takes an origin and a destination that look the same and
# nothing has to translate between two dialects of "address".
ADDRESS_FIELDS = (
    "name", "company", "street1", "street2", "city", "state", "postal_code", "country",
    "phone", "email", "residential",
)
REQUIRED_ADDRESS_FIELDS = ("name", "street1", "city", "state", "postal_code", "country")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def destination_address_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """The ship-to address a Checkout Session collected, or {} when it collected none.

    Reads BOTH shapes on purpose. `session.shipping_details` is where it has always lived; newer API
    versions move it under `session.collected_information.shipping_details`. We pin Stripe-Version
    2024-06-20 today, so the flat one is what arrives -- but a version bump that silently emptied every
    shipping address would be found by a tenant whose labels stopped working, not by us.

    Returns {} rather than a half-filled address when the required fields are not all present: a partial
    destination buys a label that cannot be delivered, and "no address" is a condition the caller can
    reason about while "an address missing its postcode" is not.
    """
    session = session or {}
    collected = session.get("collected_information")
    details = None
    for candidate in (session.get("shipping_details"),
                      (collected or {}).get("shipping_details") if isinstance(collected, dict) else None):
        if isinstance(candidate, dict) and candidate:
            details = candidate
            break
    if not isinstance(details, dict):
        return {}

    address = details.get("address") if isinstance(details.get("address"), dict) else {}
    customer = session.get("customer_details") if isinstance(session.get("customer_details"), dict) else {}

    destination = {
        # The name on the PARCEL is the shipping name when Stripe collected one; a buyer shipping to someone
        # else typed a different name there and the box has to carry it.
        "name": _clean(details.get("name")) or _clean(customer.get("name")),
        "street1": _clean(address.get("line1")),
        "street2": _clean(address.get("line2")),
        "city": _clean(address.get("city")),
        "state": _clean(address.get("state")),
        "postal_code": _clean(address.get("postal_code")),
        "country": _clean(address.get("country")).upper(),
        # Carriers charge more for a residential delivery and some require a phone number for it. Both come
        # from the customer block -- Stripe does not put them on the shipping address.
        "phone": _clean(customer.get("phone")),
        "email": _clean(customer.get("email")) or _clean(session.get("customer_email")),
    }
    if not all(destination.get(field) for field in REQUIRED_ADDRESS_FIELDS):
        return {}
    return {key: value for key, value in destination.items() if value}


# --- shipments -------------------------------------------------------------------------------------

SHIPMENT_KINDS = ("outbound", "return")
SHIPMENT_STATUSES = ("draft", "purchasing", "purchased", "failed", "voided")


class ShipmentError(ValueError):
    """A shipment that cannot be built, or a transition that must not happen."""


def shipment_id_for(order_id: str, kind: str = "outbound", sequence: int = 1) -> str:
    """The id IS the idempotency key, and it is derived rather than random.

    The first outbound label for an order is always `shp_<order_id>_outbound_1`. A double-clicked Buy Label
    therefore tries to claim a row that already exists and loses the conditional write, so it returns the
    first shipment instead of buying a second label. A random id would have made the two clicks two labels,
    and a label is money that cannot be un-spent by refreshing the page.

    A deliberate split shipment asks for sequence=2. An accident cannot produce one, because it would have
    to ask.
    """
    order = str(order_id or "").strip()
    if not order:
        raise ShipmentError("A shipment needs the order it ships.")
    if kind not in SHIPMENT_KINDS:
        raise ShipmentError(f"Shipment kind must be one of: {', '.join(SHIPMENT_KINDS)}.")
    try:
        index = int(sequence)
    except (TypeError, ValueError):
        raise ShipmentError("Shipment sequence must be a whole number.") from None
    if index < 1:
        raise ShipmentError("Shipment sequence starts at 1.")
    return f"shp_{order}_{kind}_{index}"


def build_shipment(
    *,
    order: dict[str, Any],
    from_address: dict[str, Any],
    parcel: dict[str, Any],
    kind: str = "outbound",
    sequence: int = 1,
    packed_from: list[str] | None = None,
    estimated_cost: int | None = None,
    now: int = 0,
) -> dict[str, Any]:
    """A shipment claimed BEFORE any provider is called.

    Status starts at `purchasing`, not `purchased`: the row is written first, then the money is spent. A
    crash between the two leaves a row saying "we were buying this" with the provider idempotency key
    needed to find out whether it happened -- which is recoverable. The other order (spend, then record)
    loses the label silently and bills the tenant for it.

    Addresses and parcel are SNAPSHOTS. An order whose address is corrected next week must not change what
    was printed on a label last week.
    """
    order = order or {}
    order_id = str(order.get("order_id") or "").strip()
    to_address = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else {}
    if not to_address:
        # The gap P0 exists to close: for most of this codebase's life the order had nowhere to ship to.
        raise ShipmentError(f"Order '{order_id or '?'}' has no shipping address to ship to.")
    for field in REQUIRED_ADDRESS_FIELDS:
        if not str(to_address.get(field) or "").strip():
            raise ShipmentError(f"Destination address is missing {field}.")
        if not str((from_address or {}).get(field) or "").strip():
            raise ShipmentError(f"Ship-from address is missing {field}.")
    if not parcel:
        raise ShipmentError("A shipment needs a parcel.")

    shipment = {
        "schema_version": "2026-05-29",
        "document_type": "shipment",
        "tenant_id": str(order.get("tenant_id") or ""),
        "shipment_id": shipment_id_for(order_id, kind, sequence),
        "order_id": order_id,
        "sequence": int(sequence),
        "kind": kind,
        "status": "purchasing",
        # One prod endpoint serves both modes, so a shipment has to say which one it belongs to or a
        # sandbox label shows up in a live list (see the mode-isolation work of 2026-09-20).
        "stripe_mode": "live" if str(order.get("stripe_mode") or "test") == "live" else "test",
        "to_address": {key: value for key, value in to_address.items() if key in ADDRESS_FIELDS and value},
        "from_address": {key: value for key, value in (from_address or {}).items()
                         if key in ADDRESS_FIELDS and value},
        "parcel": dict(parcel),
        "created_at": int(now),
        "updated_at": int(now),
    }
    if packed_from:
        shipment["packed_from"] = [str(item) for item in packed_from if item]
    if estimated_cost is not None:
        # Recorded from the FIRST label so estimate-vs-actual can be measured later. It cannot be
        # backfilled, which is why it is written before anything reads it.
        shipment["estimated_cost"] = int(estimated_cost)
    return shipment


def mark_purchased(shipment: dict[str, Any], *, purchase: dict[str, Any], now: int = 0) -> dict[str, Any]:
    """Record what the provider actually sold us. Only a shipment we claimed can become purchased."""
    if str((shipment or {}).get("status") or "") != "purchasing":
        raise ShipmentError("Only a shipment that was claimed for purchase can be marked purchased.")
    cost = purchase.get("cost") or {}
    updated = {
        **shipment,
        "status": "purchased",
        "purchased_at": int(now),
        "updated_at": int(now),
        "provider": {**(shipment.get("provider") or {}), **(purchase.get("provider") or {})},
    }
    for field in ("carrier", "service", "tracking_number", "tracking_url", "label_url", "label_format"):
        if purchase.get(field):
            updated[field] = str(purchase[field])
    if cost.get("amount") is not None:
        updated["cost"] = {"amount": int(cost["amount"]), "currency": str(cost.get("currency") or "usd").lower()}
    return updated


def mark_failed(shipment: dict[str, Any], message: str, *, now: int = 0) -> dict[str, Any]:
    """A purchase that did not happen. Kept rather than deleted: the row is the evidence that the attempt
    was made, and the provider's idempotency key lives on it."""
    return {
        **(shipment or {}),
        "status": "failed",
        "updated_at": int(now),
        "error": {"message": str(message or "")[:500], "at": int(now)},
    }


# --- the box catalog -------------------------------------------------------------------------------

# A convenience seed of ordinary corrugated sizes, so a tenant is not staring at an empty table. NOT a
# source of truth, and deliberately NOT carrier packaging: USPS Flat Rate, UPS Express and FedEx Box
# dimensions belong to the carriers and are fetched from the provider as parcel templates. Hand-copying
# them here would go stale the moment a size is retired, and a stale box is a label at the wrong postage.
STARTER_BOXES = (
    {"name": "Small box (6x4x4)", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15},
    {"name": "Medium box (10x8x6)", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35},
    {"name": "Large box (14x11x8)", "length": 14, "width": 11, "height": 8, "empty_weight": 0.6},
    {"name": "Extra large box (18x14x12)", "length": 18, "width": 14, "height": 12, "empty_weight": 1.0},
    {"name": "Padded mailer (9x6x1)", "length": 9, "width": 6, "height": 1, "empty_weight": 0.05},
)

BOX_FIELDS = ("name", "length", "width", "height", "distance_unit", "empty_weight", "max_weight", "mass_unit")


def starter_boxes() -> list[dict[str, Any]]:
    """A fresh copy, so a caller editing one cannot edit the seed for everybody."""
    return [dict(box) for box in STARTER_BOXES]


def tenant_boxes(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The boxes a tenant packs into. Empty is a real answer -- it means the packer falls back to one
    parcel per item, which over-estimates rather than inventing a box that does not exist."""
    boxes = (config or {}).get("boxes")
    if not isinstance(boxes, list):
        return []
    return [dict(box) for box in boxes if isinstance(box, dict) and box.get("name")]


def packable_items(lines: list[dict[str, Any]], products_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Order lines + product documents -> what `pack()` takes.

    One place that knows the difference between a product's OWN size and the BOX a tenant declared for it,
    so the label buyer, the price estimator and the carrier calculator cannot each read it differently and
    quote three different parcels for the same order.

    A line with no shipping requirement is skipped entirely: a download has no parcel, and including it
    would add a zero-sized nothing to the packing maths.
    """
    items = []
    for line in lines or []:
        product = products_by_id.get(str(line.get("product_id") or "")) or {}
        fulfillment = product.get("fulfillment") or {}
        if fulfillment.get("requires_shipping") is False:
            continue
        item: dict[str, Any] = {
            "product_id": str(line.get("product_id") or ""),
            "quantity": max(1, int(line.get("quantity") or 1)),
            "weight": fulfillment.get("weight_lb"),
        }
        own = fulfillment.get("item_dimensions") or {}
        for source, target in (("length_in", "length"), ("width_in", "width"), ("height_in", "height")):
            if own.get(source):
                item[target] = own[source]
        declared = fulfillment.get("dimensions") or {}
        if all(declared.get(field) for field in ("length_in", "width_in", "height_in")):
            item["package"] = {
                "length": declared["length_in"], "width": declared["width_in"], "height": declared["height_in"],
                "weight": fulfillment.get("weight_lb"),
            }
        items.append(item)
    return items
