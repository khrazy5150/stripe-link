"""Which silo does this Stripe event belong to? (plans/SILO_MODEL.md S3)

S3 RESOLVES and LOGS. It refuses nothing — that is S4 — because a resolver that starts dropping events on
its first day drops the ones it is wrong about, and we do not yet know which those are.

**Why the Customer anchor (S2) is not among the rules.** The plan had the order stamp → Customer anchor →
"do I hold the order?". Measured against 126 stored production events on 2026-09-25, the webhook ACTS on
only five event types, and both of the ones that occur carry a stamp today:

    checkout.session.completed   metadata[silo]                              (S1)
    invoice.*                    parent.subscription_details.metadata.silo   (verified on a live renewal)

Everything the stamp cannot reach — every customer.created/updated/deleted, every
checkout.session.expired, every payment_intent.succeeded — is ignored by the webhook entirely. An anchor
built to resolve events nobody reads is a mapping table to keep true for no gain, so S2 is skipped rather
than built. It stays available the day we act on `customer.*`.

What remains is two rules and an honest "unknown".
"""
from typing import Any

from stripe_link.silo import KNOWN_SILOS, SANDBOX, normalize_silo

# How the answer was reached, so the logs can say more than which silo won.
BY_STAMP = "stamp"
BY_HOLDING = "holding"
BY_DEFAULT = "default"
UNRESOLVED = "unresolved"


def stamp_from_event(event: dict[str, Any]) -> str:
    """The silo WE wrote onto the object, wherever this API version keeps it.

    Reads the same places `invoice_subscription_metadata` does, for the same reason: the account is on a
    preview API version that moved `subscription_details` under `parent`, and a resolver written against
    remembered field names resolves nothing and falls through to its default — which, for S4, is the
    difference between processing money and dropping it.
    """
    obj = ((event or {}).get("data") or {}).get("object") or {}
    metadata = obj.get("metadata")
    if isinstance(metadata, dict) and normalize_silo(metadata.get("silo")):
        return normalize_silo(metadata["silo"])

    # An invoice carries the SUBSCRIPTION's metadata, not its own.
    parent = obj.get("parent")
    if isinstance(parent, dict):
        details = parent.get("subscription_details")
        if isinstance(details, dict) and isinstance(details.get("metadata"), dict):
            stamped = normalize_silo(details["metadata"].get("silo"))
            if stamped:
                return stamped
    details = obj.get("subscription_details")
    if isinstance(details, dict) and isinstance(details.get("metadata"), dict):
        stamped = normalize_silo(details["metadata"].get("silo"))
        if stamped:
            return stamped

    # A line's own metadata, last: renewals created before the subscription carried a stamp.
    lines = ((obj.get("lines") or {}).get("data") or []) if isinstance(obj.get("lines"), dict) else []
    for line in lines:
        if isinstance(line, dict) and isinstance(line.get("metadata"), dict):
            stamped = normalize_silo(line["metadata"].get("silo"))
            if stamped:
                return stamped
    return ""


def resolve_event_silo(event: dict[str, Any], *, this_silo: str, holds_order=None) -> dict[str, Any]:
    """Which silo owns this event, how we know, and whether the evidence AGREES.

    `holds_order(order_id) -> bool` answers "is this already in my tables?" — the fallback for records
    written before stamping existed. It is asked only when the stamp is absent or as a cross-check, and it
    may be None.

    Returns `{silo, source, agrees, disagreement, mine}`. `mine` is what S4 will eventually act on; today
    every caller ignores it except the logger.
    """
    stamped = stamp_from_event(event)
    held = _holds(event, holds_order)

    if stamped:
        silo, source = stamped, BY_STAMP
    elif held:
        # We already hold the order this event is about, so it is ours whatever it forgot to say.
        silo, source = this_silo, BY_HOLDING
    else:
        # The documented read rule, applied exactly once, where it is written down: unstamped means
        # sandbox, never production (plans/SILO_MODEL.md, Migration).
        silo, source = SANDBOX, BY_DEFAULT

    # A stamp that says one thing while our own tables say another is an invariant violation, and it is
    # the single thing worth seeing before any of this starts refusing events.
    disagreement = ""
    if stamped and held and stamped != this_silo:
        disagreement = (f"stamp says {stamped} but {this_silo} already holds this order")

    return {
        "silo": silo,
        "source": source if silo else UNRESOLVED,
        "agrees": not disagreement,
        "disagreement": disagreement,
        "mine": silo == this_silo,
    }


def _holds(event: dict[str, Any], holds_order) -> bool:
    if not callable(holds_order):
        return False
    order_id = order_id_for_event(event)
    if not order_id:
        return False
    try:
        return bool(holds_order(order_id))
    except Exception:  # noqa: BLE001 - a lookup that fails must not decide a silo
        return False


def order_id_for_event(event: dict[str, Any]) -> str:
    """The order this event would write, derived the same way the writers derive it.

    `order_record_from_session` uses `order_{session_id}` and `order_record_from_invoice` uses
    `order_{invoice_id}`; asking the same question a different way here would make "do I hold it?"
    answerable only by accident.
    """
    obj = ((event or {}).get("data") or {}).get("object") or {}
    identifier = str(obj.get("id") or "").strip()
    return f"order_{identifier}" if identifier else ""


def routing_log(event: dict[str, Any], resolution: dict[str, Any], *, this_silo: str) -> dict[str, Any]:
    """One structured line per event, which is the entire deliverable of S3.

    S4 is only safe once these are quiet. Logging the SOURCE as well as the answer is what makes them
    readable: a run of `default` means the stamp is not arriving, which is a different problem from a run
    of disagreements.
    """
    return {
        "silo_routing": {
            "event_id": str((event or {}).get("id") or ""),
            "event_type": str((event or {}).get("type") or ""),
            "livemode": bool((event or {}).get("livemode")),
            "this_silo": this_silo,
            "resolved_silo": resolution.get("silo") or "",
            "source": resolution.get("source") or "",
            "mine": bool(resolution.get("mine")),
            "agrees": bool(resolution.get("agrees")),
            "disagreement": resolution.get("disagreement") or "",
            # Named so a search for the phase finds every line it wrote.
            "phase": "S3",
        }
    }


__all__ = ["BY_DEFAULT", "BY_HOLDING", "BY_STAMP", "KNOWN_SILOS", "UNRESOLVED",
           "order_id_for_event", "resolve_event_silo", "routing_log", "stamp_from_event"]
