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

**Two false positives, both found 2026-10-10 by reading what this module was actually logging.** It had
been crying wolf every five minutes in BOTH silos over a $197.92 charge that was recorded correctly:

1. *A subscription charge has no PaymentIntent we store.* Subscription orders are keyed
   `order_{invoice_id}` and carry no `payment_intent_id` at all, so the one index this module had could
   never match one. Every renewal was unrecorded money, forever. Now matched by invoice as well.
2. *A charge belonging to another silo looks exactly like missing money.* Both silos hold credentials
   for the same connected account, so each lists the other's charges and finds no order — correctly,
   because the other silo holds it. Now each silo reports only what it OWNS, by the same rule the
   webhook used when it decided where to write.

Both were the same underlying mistake: asking "do I hold this?" without first asking "should I?"
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from stripe_link.domain.silo_routing import LEGACY_SILO_FOR_MODE, stamp_from_object
from stripe_link.silo import normalize_silo

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


def invoice_id_of(charge: dict[str, Any]) -> str:
    """The invoice this charge settled, if any.

    Stripe gives `invoice` as an id, or as the whole object when the caller expanded it. The sweep
    expands it (one list call, no extra round trips) because the subscription's silo stamp lives on the
    invoice and nowhere on the charge.
    """
    invoice = (charge or {}).get("invoice")
    if isinstance(invoice, dict):
        return str(invoice.get("id") or "").strip()
    return str(invoice or "").strip()


def order_id_for_invoice(invoice_id: str) -> str:
    """`order_{invoice_id}` — the same derivation `order_record_from_invoice` writes.

    Asking this question a different way than the writer answers it is how a recorded order becomes
    invisible, which is defect (1) in this module's docstring.
    """
    invoice_id = str(invoice_id or "").strip()
    return f"order_{invoice_id}" if invoice_id else ""


def owning_silo(charge: dict[str, Any], mode: str = "") -> str:
    """Which silo SHOULD hold an order for this charge, or `""` when nothing says.

    The same rule the webhook applied when it chose where to write (`silo_routing.event_belongs_here`):
    the stamp if there is one, else the legacy mode correspondence. Mirroring it is the whole point — if
    the sweep and the writer disagree about ownership, the sweep reports as missing exactly the charges
    the writer correctly declined.

    The stamp is read from the charge AND from its expanded invoice, because a subscription charge
    carries no metadata of its own: `payment_intent_data` is payment-mode only, so the stamp we set at
    checkout never reaches a renewal's charge. It does reach the subscription, and the invoice carries
    the subscription's metadata — verified on a live renewal.
    """
    charge = charge if isinstance(charge, dict) else {}
    stamped = stamp_from_object(charge)
    if stamped:
        return stamped
    invoice = charge.get("invoice")
    if isinstance(invoice, dict):
        stamped = stamp_from_object(invoice)
        if stamped:
            return stamped
    # Unstamped. Fall back to what every record written before stamping existed was written under, which
    # is also what `event_belongs_here` does for an event carrying no evidence.
    mode = str(mode or "").strip().lower()
    if not mode:
        mode = "live" if charge.get("livemode") else "test"
    return LEGACY_SILO_FOR_MODE.get(mode, "")


def is_ours(charge: dict[str, Any], *, this_silo: str, mode: str = "") -> bool:
    """Should THIS silo have an order for this charge?

    Fails OPEN, in both the ways that matter. A deployment that cannot say which silo it is reports
    everything, and a charge nothing can attribute is reported too: a false alarm costs a look at the
    Stripe dashboard, and a suppressed one costs a sale nobody ever records. That asymmetry is why this
    filter is allowed to exist at all.
    """
    mine = normalize_silo(this_silo)
    if not mine:
        return True
    owner = owning_silo(charge, mode)
    return not owner or owner == mine


def orphans(charges: Iterable[dict[str, Any]], *, order_for_payment_intent: Callable[[str], Any],
            order_for_id: Callable[[str], Any] | None = None, this_silo: str = "",
            mode: str = "") -> list[dict[str, Any]]:
    """The charges THIS silo should hold an order for and does not, as reportable facts.

    Two lookups, because we key orders two ways and a charge only ever has one of them:

    * `order_for_payment_intent` — a checkout's order, found by the PaymentIntent index.
    * `order_for_id` — a subscription's order, fetched by `order_{invoice_id}`. **Optional only so the
      existing callers keep working;** without it every renewal reads as missing money, which is what it
      did until 2026-10-10.

    `this_silo` turns on the ownership filter. Left empty, every charge on the account is considered
    ours — which is the behaviour that had production reporting the sandbox silo's subscription charges.

    A lookup that RAISES is not treated as an orphan — an unreadable table must never be reported as
    missing money, which would be the most alarming possible way to say "DynamoDB is down".
    """
    found = []
    for charge in charges or []:
        if not is_recordable(charge):
            continue
        if not is_ours(charge, this_silo=this_silo, mode=mode):
            continue

        # An invoice charge FIRST, because such a charge also has a PaymentIntent — one we never store,
        # so asking the index about it returns nothing and looks exactly like a lost sale.
        invoice_id = invoice_id_of(charge)
        if invoice_id and order_for_id is not None:
            try:
                order = order_for_id(order_id_for_invoice(invoice_id))
            except Exception:  # noqa: BLE001 - see docstring: a broken read is not missing money
                continue
            if not order:
                found.append(_fact(charge, reason="no_order_for_invoice"))
            continue

        payment_intent = str(charge.get("payment_intent") or "").strip()
        if not payment_intent:
            # A charge with neither an invoice nor a PaymentIntent cannot be matched by anything we
            # key on. Report it rather than skipping: unmatchable is not the same as absent, and
            # silence is what this module exists to end.
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
        "invoice_id": invoice_id_of(charge),
        "silo": owning_silo(charge),
        "reason": reason,
    }


def summarize(found: list[dict[str, Any]]) -> dict[str, Any]:
    """What the log line and the notification both say, so they cannot disagree."""
    return {
        "count": len(found),
        "amount": sum(int(f.get("amount") or 0) for f in found),
        "charges": [f.get("charge_id") for f in found][:20],
    }
