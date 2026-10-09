"""Money Stripe took that we never recorded.

**Nothing noticed.** On 2026-10-07 a live sale was charged, the buyer's card was debited, and no order,
ledger entry or customer row was written anywhere — the event was stamped for a silo whose webhook
endpoint had been deleted, so production declined it and the sandbox never received it. It was found by
the operator reading the Stripe dashboard by eye, a day later. The second one was found the same way.

Every other guard in this codebase is a PREVENTION: route the event correctly, write the keys correctly,
carry the mode. Each of them was correct right up until the day it wasn't. This is the DETECTION that
sits behind all of them, and it is deliberately ignorant of why: it asks Stripe what it charged, asks the
orders table what it holds, and reports the difference. A deleted endpoint, a stale signing secret, a
silo mismatch, a bug not yet written — all of them surface here as the same sentence.

**It reads the direction nothing else does.** Every other sweep walks our own orders and asks Stripe
about them, which can only ever find orders we already know about. This walks Stripe's charges.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

# A charge younger than this may simply be in flight: the webhook is delivered asynchronously and a
# retry can take minutes. Flagging one at ten seconds would cry wolf on every healthy sale.
MIN_AGE_SECONDS = 900  # 15 minutes

# How far back each pass looks. Generous overlap with the sweep interval, because a charge missed by one
# pass must be caught by the next rather than aging silently out of the window.
LOOKBACK_SECONDS = 6 * 60 * 60


def charge_window(now: int) -> tuple[int, int]:
    """`(created_gte, created_lte)` — old enough to have been delivered, recent enough to still matter."""
    return now - LOOKBACK_SECONDS, now - MIN_AGE_SECONDS


def is_recordable(charge: dict[str, Any]) -> bool:
    """Whether this charge SHOULD have produced an order.

    A failed or uncaptured charge took no money and is not expected in the orders table. A fully
    refunded one still is: the money moved twice and the books have to show both.
    """
    if not isinstance(charge, dict):
        return False
    if not charge.get("paid"):
        return False
    if charge.get("status") != "succeeded":
        return False
    if not int(charge.get("amount_captured") or 0):
        return False
    return True


def orphans(charges: Iterable[dict[str, Any]], *, order_for_payment_intent: Callable[[str], Any]) -> list[dict[str, Any]]:
    """The charges with no order behind them, as reportable facts.

    `order_for_payment_intent` is the lookup, injected so this stays a pure function over the two sides.
    A lookup that RAISES is not treated as an orphan — an unreadable table must never be reported as
    missing money, which would be the most alarming possible way to say "DynamoDB is down".
    """
    found = []
    for charge in charges or []:
        if not is_recordable(charge):
            continue
        payment_intent = str(charge.get("payment_intent") or "").strip()
        if not payment_intent:
            # A charge with no PaymentIntent cannot be matched by the only index we have. Report it
            # rather than skipping: unmatchable is not the same as absent, and silence is what this
            # module exists to end.
            found.append(_fact(charge, reason="no_payment_intent"))
            continue
        try:
            order = order_for_payment_intent(payment_intent)
        except Exception:  # noqa: BLE001 - see docstring: a broken read is not missing money
            continue
        if not order:
            found.append(_fact(charge, reason="no_order"))
    return found


def _fact(charge: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "charge_id": str(charge.get("id") or ""),
        "payment_intent_id": str(charge.get("payment_intent") or ""),
        "amount": int(charge.get("amount_captured") or charge.get("amount") or 0),
        "currency": str(charge.get("currency") or "usd"),
        "created": int(charge.get("created") or 0),
        "livemode": bool(charge.get("livemode")),
        "refunded": bool(charge.get("refunded")),
        "reason": reason,
    }


def summarize(found: list[dict[str, Any]]) -> dict[str, Any]:
    """What the log line and the notification both say, so they cannot disagree."""
    return {
        "count": len(found),
        "amount": sum(int(f.get("amount") or 0) for f in found),
        "charges": [f.get("charge_id") for f in found][:20],
    }
