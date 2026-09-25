"""Handing the day's parcels to the carrier: manifests, pickups, and the CSV a tenant exports.

A manifest (USPS calls it a SCAN form) and a pickup are both **batch** operations, and both carry a
constraint that is the carrier's rather than ours:

    ONE carrier, ONE ship date, ONE origin address.

Mixing carriers or dates in one request fails at the carrier, so the screen has to GROUP before it can
offer the action. Doing that grouping here, rather than in the component, is what stops the button
offering a batch the carrier will reject.

Only a shipment with a real provider transaction can be manifested or collected: a manifest lists labels,
and a label the tenant bought elsewhere (the manual path) is not one this provider knows about.
"""
import csv
import io
from datetime import datetime, timezone
from typing import Any

MANIFESTABLE_STATUSES = ("purchased",)


def _transaction_id(shipment: dict[str, Any]) -> str:
    provider = shipment.get("provider")
    if isinstance(provider, dict):
        return str(provider.get("transaction_id") or "").strip()
    return ""


def ship_date(shipment: dict[str, Any]) -> str:
    """The calendar day a label was bought, as YYYY-MM-DD in UTC.

    The carrier groups by DATE, so this is the grouping key. UTC because the stored timestamp is, and
    inventing a tenant timezone here would put two labels bought minutes apart into different manifests.
    """
    stamp = int(shipment.get("purchased_at") or shipment.get("created_at") or 0)
    if not stamp:
        return ""
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d")


def manifestable(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shipments a carrier would accept on a handover document.

    A manually-marked parcel is excluded on purpose: the tenant bought that postage at the counter, so
    this provider has no transaction to list and the carrier has nothing to scan.
    """
    out = []
    for shipment in shipments or []:
        if str(shipment.get("status") or "") not in MANIFESTABLE_STATUSES:
            continue
        if shipment.get("manifest_id"):
            continue  # already handed over; a second manifest for the same label is refused anyway
        if not _transaction_id(shipment):
            continue
        out.append(shipment)
    return out


def handover_groups(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The batches a carrier would actually accept, newest day first.

    Each group is one (carrier, ship date) pair -- the unit a manifest or a pickup can cover.
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for shipment in manifestable(shipments):
        carrier = str(shipment.get("carrier") or "").strip().lower()
        day = ship_date(shipment)
        if not carrier or not day:
            continue
        key = (carrier, day)
        group = groups.setdefault(key, {
            "carrier": carrier, "ship_date": day, "shipments": [], "transactions": [], "total": 0,
        })
        group["shipments"].append(shipment)
        group["transactions"].append(_transaction_id(shipment))
        group["total"] += int((shipment.get("cost") or {}).get("amount") or 0)
    return sorted(groups.values(), key=lambda g: (g["ship_date"], g["carrier"]), reverse=True)


ORDER_CSV_COLUMNS = (
    ("order_id", "Order"),
    ("created_at", "Order date"),
    ("customer_name", "Customer"),
    ("customer_email", "Email"),
    ("items", "Items"),
    ("amount_total", "Total"),
    ("currency", "Currency"),
    ("payment_status", "Payment"),
    ("ship_to_city", "City"),
    ("ship_to_state", "State"),
    ("ship_to_postal", "Postal code"),
    ("ship_to_country", "Country"),
    ("status", "Delivery status"),
    ("fulfilled_at", "Fulfilled"),
    ("carrier", "Carrier"),
    ("service", "Service"),
    ("tracking_number", "Tracking"),
    ("shipping_cost", "Postage"),
)


def order_csv_row(order: dict[str, Any]) -> dict[str, str]:
    """One order, flattened. Every value a string: a CSV has no other type, and pretending otherwise is
    how a spreadsheet turns a tracking number into scientific notation."""
    customer = order.get("customer") or {}
    address = order.get("shipping_address") or {}
    fulfilment = order.get("fulfilment") or {}
    shipment = fulfilment.get("shipment") or {}
    lines = order.get("line_items") or []
    items = "; ".join(
        f"{int(line.get('quantity') or 1)} x {line.get('name') or ''}".strip() for line in lines
    ) or str((order.get("product") or {}).get("name") or "")
    created = int(order.get("created_at") or 0)
    return {
        "order_id": str(order.get("order_id") or ""),
        "created_at": datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                      if created else "",
        "customer_name": str(customer.get("name") or ""),
        "customer_email": str(customer.get("email") or ""),
        "items": items,
        "amount_total": _money(order.get("amount_total")),
        "currency": str(order.get("currency") or "usd").upper(),
        "payment_status": str(order.get("payment_status") or order.get("status") or ""),
        "ship_to_city": str(address.get("city") or ""),
        "ship_to_state": str(address.get("state") or ""),
        "ship_to_postal": str(address.get("postal_code") or ""),
        "ship_to_country": str(address.get("country") or ""),
        "status": str((order.get("delivery") or {}).get("label") or ""),
        "fulfilled_at": _date(shipment.get("shipped_at") or shipment.get("purchased_at")),
        "carrier": str(shipment.get("carrier") or ""),
        "service": str(shipment.get("service") or ""),
        "tracking_number": str(shipment.get("tracking_number") or ""),
        "shipping_cost": _money((shipment.get("cost") or {}).get("amount")),
    }


def _date(stamp: Any) -> str:
    try:
        value = int(stamp or 0)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d") if value else ""


def _money(cents: Any) -> str:
    try:
        return f"{int(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return ""


def orders_csv(orders: list[dict[str, Any]]) -> str:
    """The export. Excel-friendly line endings, because that is what opens it."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[key for key, _ in ORDER_CSV_COLUMNS],
                            lineterminator="\r\n", extrasaction="ignore")
    buffer.write(",".join(label for _, label in ORDER_CSV_COLUMNS) + "\r\n")
    for order in orders or []:
        writer.writerow(order_csv_row(order))
    return buffer.getvalue()
