"""The short order reference a tenant actually reads and quotes.

A stored order id is `order_` + Stripe's 66-character Checkout Session id, 72 characters, or 81 with an
upsell suffix. It cannot change -- it is the idempotency key the webhook dedupes on, and the carrier's
idempotency key is derived from it -- so the SHORT form is what people see.

It is a **substring** of the real id, taken from Stripe's own random part, so a tenant who quotes
"b13b4Un3" can paste it into the search box and find the order. A hash would be shorter and prettier and
would lose exactly that.

**Collisions are prevented, not merely improbable.** Stripe's ids are not uniformly random at the front --
measured across 45 real sessions, 42 began `a1` and 3 began `b1` -- so an 8-character prefix carries
closer to 6 characters of entropy. That is still ~5.7e10 combinations and a collision would be a
once-in-a-lifetime event, but "unlikely" and "impossible" are different promises and the tenant was made
the second one. So the reference is computed across the tenant's whole set: if two orders would share a
prefix, both get a longer one until they do not.

A reference therefore only ever changes if a genuine collision appears, which is the right trade -- a
reference that lengthened once beats two orders answering to the same number.
"""
from typing import Any

MIN_LENGTH = 8
MAX_LENGTH = 24

_PREFIXES = ("cs_test_", "cs_live_", "in_", "pi_", "ch_")


def _core(order_id: str) -> tuple[str, str]:
    """The random part of the id, and the upsell suffix that has to stay attached to it."""
    identifier = str(order_id or "")
    if not identifier:
        return "", ""
    suffix = ""
    marker = "_upsell_"
    if marker in identifier:
        identifier, _, sequence = identifier.partition(marker)
        suffix = f"-U{sequence}"
    body = identifier[len("order_"):] if identifier.startswith("order_") else identifier
    for prefix in _PREFIXES:
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    return body, suffix


def short_ref(order_id: str, length: int = MIN_LENGTH) -> str:
    """This id's reference at a given length. Deterministic and independent of any other order."""
    body, suffix = _core(order_id)
    if not body:
        return ""
    return f"{body[:length]}{suffix}"


def short_refs(order_ids: list[str], length: int = MIN_LENGTH) -> dict[str, str]:
    """`{order_id: reference}` for a whole set, with every reference distinct.

    An upsell keeps its sequence, because a post-purchase order carries its PARENT's session id -- without
    it a purchase and both its upsells would share one reference between them.
    """
    ids = [str(i) for i in order_ids if str(i or "")]
    size = max(int(length or MIN_LENGTH), 1)
    while size <= MAX_LENGTH:
        mapping = {identifier: short_ref(identifier, size) for identifier in ids}
        if len(set(mapping.values())) == len(mapping):
            return mapping
        size += 1
    # Two ids identical for 24 characters are the same Stripe object; fall back to the whole thing rather
    # than hand back an ambiguous reference.
    return {identifier: identifier for identifier in ids}


def matches_reference(order: dict[str, Any], needle: str) -> bool:
    """Does this order answer to what the tenant typed?

    Matches the short reference, the full id, and the Stripe session id -- because a tenant pastes
    whichever of the three they happen to be holding, and being told "no results" for the id printed on
    their own screen is the kind of thing that makes a search feel broken.
    """
    wanted = str(needle or "").strip().lower().lstrip("#")
    if not wanted:
        return False
    candidates = [
        str(order.get("order_id") or ""),
        str(order.get("short_ref") or ""),
        str(order.get("session_id") or ""),
    ]
    # A quoted reference carries the -U suffix; the raw id spells it _upsell_. Compare both ways.
    normalized = wanted.replace("-u", "_upsell_")
    return any(wanted in value.lower() or normalized in value.lower()
               for value in candidates if value)
