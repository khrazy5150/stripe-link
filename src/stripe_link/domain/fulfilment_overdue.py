"""Which orders should have shipped by now.

plans/THANK_YOU_PAGE.md P4. The thank-you page tells a buyer their parcel is due on a date, and the
shipment email corrects that date if it slips — but both of those depend on the tenant marking the order
shipped, and nothing asked them to. `shipments recorded: 0` across every order ever placed.

A notification already fires on every sale. This is the second one, and it earns its place by a different
rule: `feedback_notices_only_when_actionable` says a notice needs an action the tenant must take, and
"you have orders" is not that — they know. **"This order should have shipped by now" is**, because we
stored the date we promised on their behalf and can say exactly which promise is at risk.

That date is `delivery_estimate.ships_on`, written when the order was created. Without it there is no
promise to be late against, so there is nothing to say and we say nothing.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Shipment statuses that mean the parcel is gone. Mirrors `domain/fulfilment`, which is where the Orders
# screen reads the same fact -- two different answers to "has this shipped" would put a notice on a
# tenant's bell for a parcel their own order list shows as sent.
SHIPPED_STATUSES = {"purchased", "shipped"}

# A day's grace past the promised ship date. The cutoff is already a buffer and the tenant may well have
# posted it without telling us, so firing at one minute past midnight would be a notice about our own
# bookkeeping rather than their parcel.
GRACE_DAYS = 1


def _text(value: Any) -> str:
    return str(value or "").strip()


def promised_ship_date(order: Any) -> str:
    """The day we told the buyer this would leave, or "" when nothing was promised."""
    estimate = (order or {}).get("delivery_estimate") if isinstance(order, dict) else None
    return _text((estimate or {}).get("ships_on")) if isinstance(estimate, dict) else ""


def has_shipped(shipment: Any) -> bool:
    return _text((shipment or {}).get("status")) in SHIPPED_STATUSES


def is_overdue(order: Any, shipment: Any, today: date, *, grace_days: int = GRACE_DAYS) -> bool:
    """Whether this order is past the ship date we promised on the tenant's behalf.

    Four conditions, each of which has to hold for the notice to be worth sending:

    - something was PROMISED. No `delivery_estimate.ships_on` means no parcel, or an order placed before
      this existed, and either way there is no broken promise to report;
    - it has NOT shipped;
    - the promised day plus a day's grace is behind us;
    - the order is PAID. A pending or refunded order is not waiting on the tenant to post it.
    """
    if not isinstance(order, dict):
        return False
    if _text(order.get("status")) != "paid":
        return False
    if has_shipped(shipment):
        return False
    promised = promised_ship_date(order)
    if not promised:
        return False
    try:
        due = date.fromisoformat(promised)
    except ValueError:
        return False
    return today > due + timedelta(days=max(0, int(grace_days)))


def overdue_notification(order: dict[str, Any], today: date) -> dict[str, Any]:
    """The bell entry. Its id is DETERMINISTIC, so a sweep running every five minutes writes the same row
    rather than a new notice each pass -- the dedup is the primary key, not a query."""
    order_id = _text(order.get("order_id"))
    customer = (order.get("customer") or {}) if isinstance(order.get("customer"), dict) else {}
    who = _text(customer.get("name")) or _text(customer.get("email")) or "a customer"
    promised = promised_ship_date(order)
    days = (today - date.fromisoformat(promised)).days if promised else 0
    return {
        "schema_version": "2026-05-29",
        "document_type": "notification",
        "tenant_id": _text(order.get("tenant_id")),
        "notification_id": f"notif_overdue_{order_id}",
        "type": "fulfilment",
        # Not an error -- nothing has failed, and a red badge for a parcel posted this morning without
        # being recorded would be crying wolf. It is a thing to do today.
        "severity": "warning",
        "title": "Order waiting to ship",
        "message": (f"{who}'s order was due to ship {_days_ago(days)}. "
                    "They were told a delivery date — mark it shipped to send them tracking."),
        "status": "unread",
        "sort_priority": 90,
        "related": {"order_id": order_id,
                    "customer_id": _text(customer.get("stripe_customer_id"))},
        "action": {"label": "View order", "route": "orders"},
    }


def _days_ago(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"
