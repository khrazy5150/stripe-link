"""Is the address one a carrier will actually deliver to?

The author's spec for the Status column: "Not Shippable" covers digital, services, and "physical products
that don't have a complete shipping address **or an address that's deliverable**". Completeness is
structural and free -- `destination_address_from_session` already refuses a half-filled address.
Deliverability is a question only a carrier can answer, and answering it costs a provider call.

**So the verdict is stored, not recomputed.** Validating on every page render would be one network call per
row per load, which is slow, rate-limited, and pointless: an address does not change between two renders
of the same list. It is checked once, written onto the order, and re-checked only when the address itself
changes.

Why it matters more than it looks: a carrier that refuses an undeliverable address at the counter is the
GOOD case. The common case is that it accepts the parcel, fails to deliver, and returns it weeks later at
the tenant's expense -- having already charged for the label. Finding out before the label is bought is
the entire point.
"""
import hashlib
import json
from typing import Any

UNCHECKED = "unchecked"
DELIVERABLE = "deliverable"
UNDELIVERABLE = "undeliverable"
UNKNOWN = "unknown"

ADDRESS_FIELDS = ("street1", "street2", "city", "state", "postal_code", "country")


def address_fingerprint(address: dict[str, Any] | None) -> str:
    """A stable short hash of the address, so a stored verdict can be tied to what was checked.

    Case- and whitespace-insensitive: "1493 OSAGE ST" and "1493 Osage St" are the same doorstep, and
    re-validating because the buyer used caps would spend a call to learn nothing.
    """
    parts = {field: " ".join(str((address or {}).get(field) or "").split()).lower()
             for field in ADDRESS_FIELDS}
    if not any(parts.values()):
        return ""
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def validation_state(order: dict[str, Any]) -> dict[str, Any]:
    """What we know about this order's address today: `{status, messages, checked_at, stale}`.

    `stale` means a verdict exists but was reached on a DIFFERENT address -- the tenant corrected it since.
    A stale verdict is never shown, because telling someone their corrected address is undeliverable is
    worse than saying nothing.
    """
    address = order.get("shipping_address") or {}
    stored = order.get("address_validation") if isinstance(order.get("address_validation"), dict) else {}
    if not address:
        return {"status": UNCHECKED, "messages": [], "checked_at": 0, "stale": False}
    if not stored:
        return {"status": UNCHECKED, "messages": [], "checked_at": 0, "stale": False}

    stale = bool(stored.get("fingerprint")) and stored["fingerprint"] != address_fingerprint(address)
    status = str(stored.get("status") or UNKNOWN)
    if status not in {DELIVERABLE, UNDELIVERABLE, UNKNOWN}:
        status = UNKNOWN
    return {
        "status": UNCHECKED if stale else status,
        "messages": [] if stale else [str(m) for m in (stored.get("messages") or [])],
        "checked_at": int(stored.get("checked_at") or 0),
        "stale": stale,
    }


def record_validation(address: dict[str, Any], result: dict[str, Any], *, now: int) -> dict[str, Any]:
    """The verdict as it gets written onto the order.

    A provider that declines to answer is recorded as UNKNOWN, never as undeliverable. "We could not
    check" and "a carrier will not deliver here" are different facts, and only one of them should stop a
    tenant shipping.
    """
    valid = (result or {}).get("valid")
    if valid is True:
        status = DELIVERABLE
    elif valid is False:
        status = UNDELIVERABLE
    else:
        status = UNKNOWN
    return {
        "status": status,
        "messages": [str(m) for m in ((result or {}).get("messages") or [])][:5],
        "normalized": (result or {}).get("normalized") or {},
        "fingerprint": address_fingerprint(address),
        "checked_at": int(now),
    }


def needs_check(order: dict[str, Any]) -> bool:
    """Worth spending a provider call on.

    Only an order that HAS an address and has no current verdict for it. An order already known
    undeliverable is not re-checked on a loop: the tenant has to fix the address, and re-asking the
    carrier the same question costs money and changes nothing.
    """
    if not (order.get("shipping_address") or {}):
        return False
    return validation_state(order)["status"] == UNCHECKED


def blocking_reason(order: dict[str, Any]) -> str:
    """The sentence the Status column shows, or "" when nothing about the address stops a label.

    UNKNOWN does not block. A provider outage must not turn every order in the list unshippable.
    """
    state = validation_state(order)
    if state["status"] != UNDELIVERABLE:
        return ""
    detail = "; ".join(state["messages"][:2])
    return (f"The carrier will not deliver to this address. {detail}".strip()
            if detail else "The carrier will not deliver to this address.")


def suggested_correction(order: dict[str, Any]) -> dict[str, Any]:
    """What the carrier would write on the label instead, when it differs from what the buyer typed.

    Returns `{}` when there is nothing worth showing. "Worth showing" excludes pure capitalisation --
    USPS returns everything title-cased, and "1493 Osage St" versus "1493 OSAGE ST" is not a correction,
    it is a house style. A ZIP+4, a folded apartment line or a corrected street IS worth showing, because
    each one changes what a carrier can do with the parcel.

    It is **offered, never applied**. Changing where a parcel goes without being asked is worse than
    failing to deliver it -- the buyer typed an address and is entitled to have it be the one used.
    """
    state = validation_state(order)
    if state["stale"] or state["status"] == UNCHECKED:
        return {}
    stored = order.get("address_validation") or {}
    normalized = stored.get("normalized") or {}
    address = order.get("shipping_address") or {}
    if not normalized.get("street1"):
        return {}

    changed = {}
    for field in ADDRESS_FIELDS:
        was = " ".join(str(address.get(field) or "").split())
        now = " ".join(str(normalized.get(field) or "").split())
        if not now:
            continue
        if was.lower() == now.lower():
            continue  # capitalisation only: a house style, not a correction
        changed[field] = {"was": was, "suggested": now}
    if not changed:
        return {}
    return {"changed": changed, "normalized": normalized,
            "messages": [str(m) for m in (stored.get("messages") or [])]}
