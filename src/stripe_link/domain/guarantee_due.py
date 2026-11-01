"""Which delivery guarantees have come due (plans/DELIVERY_TRACKING.md, "Next" 1).

`buyer_guarantees.no_delivery_refund` publishes "if your order has not arrived N days after it ships, we
refund it or send it again -- your choice", and honouring it was entirely manual: a tenant switched it on
and nothing watched the clock. This is the thing that watches.

**IT NOTIFIES. IT NEVER REFUNDS.** Two separate reasons, and either alone would be enough:

* the promise says *your choice* -- refund or resend -- so a sweep that moved money would deny the buyer
  the choice the page promised them;
* nobody asked a buyer anything yet. A guarantee coming due means the tenant owes a conversation, not
  that a decision has been made.

**THE REGISTRATION GATE IS WHAT MAKES THIS HONEST.** `tracking.has_arrived` is False for a parcel that was
never tracked, for a carrier that never scans, and for a parcel genuinely lost -- three different things
wearing one answer. So the question asked here is not "did it arrive" but "**are we in a position to know,
and it did not**": a shipment with no `tracking_registered_at` is invisible to us and is skipped. Without
that clause this sweep would report every order older than the window, including every one delivered on
time, which is `feedback_absence_reads_as_safety` with a refund attached.

That gate also dates the feature automatically. Nothing shipped before the tracking feed carries a
registration, so no historical order can be dragged into a promise nobody was watching at the time.
"""
from __future__ import annotations

from typing import Any

from stripe_link.domain.buyer_guarantees import NO_DELIVERY_REFUND, NO_TRACKING_UPDATE_REFUND
from stripe_link.domain.tracking import has_arrived

DAY_SECONDS = 86_400

# Only these two have a clock that a shipment can answer. `damaged_in_transit` needs someone to look in
# the box, and the two price promises are about a price list, not a parcel -- a sweep cannot see any of
# them, and pretending otherwise would put a notice on a tenant's bell with nothing behind it.
SWEEPABLE: tuple[str, ...] = (NO_DELIVERY_REFUND, NO_TRACKING_UPDATE_REFUND)

SCHEMA_VERSION = "2026-05-29"


def _whole(value: Any) -> int:
    """An integer, or 0. `Decimal` survives a DynamoDB round trip and `isinstance(x, int)` is False for
    it -- the trap that has already 404'd published pages once (`feedback_decimal_from_dynamo`), and every
    timestamp read here comes straight off a stored document."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def observable(shipment: Any) -> bool:
    """Whether we are in a position to say anything about this parcel's arrival at all.

    A shipment whose tracker was never registered tells us nothing, and "nothing" must not be read as "it
    did not arrive". Covers the tenant who posts at their local counter with no provider account, every
    order predating the feed, and a registration that failed.
    """
    stored = shipment if isinstance(shipment, dict) else {}
    return _whole(stored.get("tracking_registered_at")) > 0


def _clock_start(key: str, shipment: dict[str, Any]) -> int:
    """When this guarantee's clock started, or 0 when it has not.

    `no_delivery_refund` runs from DISPATCH, which is what the published sentence says ("N days after it
    ships"). `no_tracking_update_refund` runs from the last scan -- and from REGISTRATION when there has
    never been one, because a tracker registered three weeks ago that has never scanned is the purest
    case of "tracking shows no movement" rather than a case with no clock.
    """
    if key == NO_DELIVERY_REFUND:
        return _whole(shipment.get("shipped_at"))
    return _whole(shipment.get("tracking_status_at")) or _whole(shipment.get("tracking_registered_at"))


def due_guarantees(order: Any, shipment: Any, promises: Any, *, now: int) -> list[dict[str, Any]]:
    """The guarantees this order has outrun, newest promise first. [] whenever nothing is owed.

    `promises` is `buyer_guarantees.resolve(tenant_config)` -- enabled ones only, each carrying the day
    count the tenant set and the sentence their page published. A tenant who enabled nothing gets nothing,
    which is the point: this reports on promises they made, never on promises we think they should have.

    Every condition has to hold, and each is here because its absence would produce a false notice:

    * the order is PAID -- a pending or refunded order is not waiting on anything;
    * a parcel was DISPATCHED, so there is something to have not arrived;
    * we can SEE it (`observable`), the clause this whole module turns on;
    * it has NOT arrived;
    * the clock has run out.

    A RETURNED or FAILED parcel is deliberately still reported. It did not reach the buyer, which is
    exactly when they are owed the refund or the resend -- the tenant's own Orders screen says "Returned"
    beside it, so the notice adds the promise rather than the news.
    """
    if not isinstance(order, dict) or _text(order.get("status")) != "paid":
        return []
    stored = shipment if isinstance(shipment, dict) else {}
    if not _whole(stored.get("shipped_at")):
        return []
    if not observable(stored):
        return []
    if has_arrived(stored):
        return []

    by_key = {}
    for promise in promises if isinstance(promises, list) else []:
        if isinstance(promise, dict) and _text(promise.get("key")) in SWEEPABLE:
            by_key[_text(promise["key"])] = promise

    out: list[dict[str, Any]] = []
    for key in SWEEPABLE:
        promise = by_key.get(key)
        days = _whole((promise or {}).get("days"))
        if not promise or days < 1:
            continue
        started = _clock_start(key, stored)
        if not started:
            continue
        elapsed = (int(now) - started) // DAY_SECONDS
        if elapsed < days:
            continue
        out.append({"key": key, "days": days, "elapsed_days": elapsed,
                    "sentence": _text(promise.get("sentence"))})
    # Longest overdue first, so a tenant with both due reads the one they are furthest past.
    out.sort(key=lambda item: item["elapsed_days"] - item["days"], reverse=True)
    return out


TITLES: dict[str, str] = {
    NO_DELIVERY_REFUND: "Delivery guarantee is due",
    NO_TRACKING_UPDATE_REFUND: "Tracking guarantee is due",
}


def _reason(key: str, due: dict[str, Any]) -> str:
    if key == NO_DELIVERY_REFUND:
        return f"has not arrived {due['elapsed_days']} days after it shipped"
    return f"has shown no tracking movement for {due['elapsed_days']} days"


def guarantee_notification(order: dict[str, Any], due: dict[str, Any], *, now: int) -> dict[str, Any]:
    """The bell entry for one due guarantee on one order.

    The id is DETERMINISTIC on the order AND the guarantee, so a sweep running every five minutes rewrites
    one row rather than filling the bell with copies of itself -- `fulfilment_overdue`'s rule, and the
    dedup is the primary key rather than a query. Keyed on the guarantee too, because an order can outrun
    both promises and they are two different things to settle.

    It earns its place by `feedback_notices_only_when_actionable`: not "a parcel is late", which the
    tenant can see, but "you promised this buyer a refund or a replacement and the date has passed". The
    sentence their own page published is quoted back, because that is the promise they have to honour and
    it is theirs, not ours.
    """
    order_id = _text(order.get("order_id"))
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    who = _text((customer or {}).get("name")) or _text((customer or {}).get("email")) or "A customer"
    key = _text(due.get("key"))
    message = (f"{who}'s order {_reason(key, due)}, and you promised to act after {due['days']}. "
               "Settle it with them — a refund or a replacement, their choice.")
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "notification",
        "tenant_id": _text(order.get("tenant_id")),
        "notification_id": f"notif_guarantee_{key}_{order_id}",
        "type": "fulfilment",
        # A warning rather than an error: nothing has broken, and the tenant may have settled it with the
        # buyer by email already. It is a thing to do today, which is what this severity means here.
        "severity": "warning",
        "title": TITLES.get(key, "Buyer guarantee is due"),
        "message": message,
        "status": "unread",
        # Above the overdue-to-ship notice (90): that one is a parcel the tenant still has, this one is a
        # promise already broken in the buyer's eyes.
        "sort_priority": 95,
        "related": {"order_id": order_id,
                    "customer_id": _text((customer or {}).get("stripe_customer_id")),
                    "guarantee": key},
        "action": {"label": "View order", "route": "orders"},
        "created_at": int(now),
    }
