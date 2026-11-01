"""Carrier tracking, RECEIVED rather than guessed.

**One reader, zero writers.** `fulfilment.delivery_status` has read `shipment["tracking_status"]` since the
shipping work landed, and nothing in this repository has ever written it: the Shippo adapter asks for rates,
buys a label and never asks again. So the Orders screen's Status cell could not say "Delivered" however long
a parcel had been delivered, and `_TRACKING` -- a map written against Shippo's exact vocabulary -- had
nothing to translate.

**Why it matters beyond a stale cell.** `buyer_guarantees.no_delivery_refund` publishes "if your order has
not arrived N days after it ships, we refund it or send it again". `shipped_at` is recorded on both paths, so
the clock is exact; whether the parcel ARRIVED was unknowable. A sweep built on the clock alone would fire on
every order older than N days including every one delivered on time -- a gate built from an absence, read as
"not delivered" when the truth is "nobody ever looked". That is `feedback_absence_reads_as_safety`, on a
feature that moves money.

**The meaning stays in `fulfilment._TRACKING`.** This module carries the provider's own word -- `DELIVERED`,
`TRANSIT`, `PRE_TRANSIT` -- and `delivery_status` goes on translating it for the screen. A second copy of
that table here is how two readers of one fact come to disagree, and the existing one is already correct.

**Nothing here trusts the payload for anything but a status.** The shipment is found by OUR id, carried in
Shippo's `metadata` because we put it there; the webhook cannot name a tenant, an amount or an order. The
worst a forged body can do is set a status on a shipment whose id it already knew.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Shippo's own status vocabulary, for the two decisions this module makes: has it arrived, and may a later
# event move it. Deliberately NOT a translation table -- see the module docstring.
PRE_TRANSIT = "PRE_TRANSIT"
TRANSIT = "TRANSIT"
DELIVERED = "DELIVERED"
RETURNED = "RETURNED"
FAILURE = "FAILURE"
UNKNOWN = "UNKNOWN"

KNOWN_STATUSES: frozenset[str] = frozenset({PRE_TRANSIT, TRANSIT, DELIVERED, RETURNED, FAILURE, UNKNOWN})

# A parcel that was delivered and then came back is a real journey -- a refused delivery, a wrong address,
# a return to sender -- so these two may follow DELIVERED. Nothing else may: a carrier posting a late
# in-transit scan after the box was on the doorstep must not un-deliver it, whatever date it carries.
AFTER_DELIVERED: frozenset[str] = frozenset({RETURNED, FAILURE})


def normalize_status(value: Any) -> str:
    """Shippo's status, upper-cased and trimmed. "" when it is not one we know.

    An unrecognised status is dropped rather than stored, because `delivery_status` would fall through it
    to our own gate view anyway -- and storing a word nothing can translate puts a value on the document
    that looks like a delivery fact and is not one.
    """
    text = str(value or "").strip().upper()
    return text if text in KNOWN_STATUSES else ""


def parse_status_date(value: Any) -> int:
    """The event's own clock as epoch seconds, or 0 when it has none.

    This is the ordering key for everything below, so it is the provider's timestamp rather than ours: two
    events can reach us in either order, and only the carrier knows which actually happened first. 0 means
    "undated", and an undated event is never allowed to displace a dated one.
    """
    text = str(value or "").strip()
    if not text:
        return 0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def shipment_id_from(payload: Any) -> str:
    """Our own shipment id, which we put in Shippo's `metadata` when registering the tracker.

    The only identifier on the payload we are willing to resolve. `tracking_number` would need a new index
    and is not ours; `transaction` is the provider's. `metadata` is a string we wrote.
    """
    data = payload if isinstance(payload, dict) else {}
    # Shippo wraps the Tracking object in `data` on a webhook and returns it bare from POST /tracks, so
    # both shapes are read rather than only the one a test happened to use.
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    return str(inner.get("metadata") or "").strip()


def reading(payload: Any) -> dict[str, Any]:
    """The payload reduced to what we store. `{}` when it says nothing usable.

    Flat fields rather than a nested blob: `delivery_status` reads `tracking_status` off the shipment
    today, and a reshaped home for it would mean changing the one reader that already works.
    """
    data = payload if isinstance(payload, dict) else {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    status_block = inner.get("tracking_status")
    status_block = status_block if isinstance(status_block, dict) else {}

    status = normalize_status(status_block.get("status"))
    if not status:
        return {}
    out: dict[str, Any] = {
        "tracking_status": status,
        "tracking_status_at": parse_status_date(status_block.get("status_date")),
    }
    substatus = status_block.get("substatus")
    # Shippo sends substatus as an object on some carriers and a bare code on others.
    if isinstance(substatus, dict):
        code = str(substatus.get("code") or "").strip()
    else:
        code = str(substatus or "").strip()
    if code:
        out["tracking_substatus"] = code[:80]
    detail = str(status_block.get("status_details") or "").strip()
    if detail:
        # Shown in the Status cell's note, so it is trimmed to something that fits a table row rather
        # than stored at whatever length a carrier feels like sending.
        out["tracking_detail"] = detail[:200]
    return out


def accepts(shipment: Any, incoming: dict[str, Any]) -> bool:
    """Whether this reading may be written over what the shipment already holds.

    Shippo retries a webhook twice on a non-2XX and events for one parcel can arrive out of order, so
    "latest received" is not "latest happened". The rules, in order:

    * An unusable reading changes nothing.
    * DELIVERED is STICKY, except for the two statuses that genuinely follow it. A late in-transit scan
      must not un-deliver a parcel -- that is the one transition that would make a delivery guarantee pay
      out on an order the buyer already has.
    * Otherwise the provider's own clock decides, and an equal timestamp is allowed through so a retry of
      the same event is idempotent rather than refused.
    """
    if not incoming.get("tracking_status"):
        return False
    stored = shipment if isinstance(shipment, dict) else {}
    current = normalize_status(stored.get("tracking_status"))
    if not current:
        return True
    status = str(incoming["tracking_status"])
    if current == DELIVERED and status not in AFTER_DELIVERED:
        return False
    return int(incoming.get("tracking_status_at") or 0) >= int(stored.get("tracking_status_at") or 0)


def fields_to_write(shipment: Any, incoming: dict[str, Any], *, now: int) -> dict[str, Any]:
    """The shipment attributes this event sets, or `{}` when it sets none.

    `delivered_at` is written ONCE and never moved. It is the fact a delivery guarantee is measured
    against, and a parcel delivered, returned and redelivered did still arrive on the first date -- moving
    it would silently re-open a promise that had been kept.
    """
    if not accepts(shipment, incoming):
        return {}
    stored = shipment if isinstance(shipment, dict) else {}
    out = dict(incoming)
    out["tracking_updated_at"] = int(now)
    if out["tracking_status"] == DELIVERED and not int(stored.get("delivered_at") or 0):
        # Falls back to our own clock only when the carrier dated nothing: a delivery with no date at all
        # is still a delivery, and leaving it unset would leave the guarantee measuring against nothing.
        out["delivered_at"] = int(out.get("tracking_status_at") or 0) or int(now)
    return out


def register(provider: Any, shipment: Any, *, now: int) -> dict[str, Any]:
    """Ask the provider to start reporting on this parcel. Returns the fields its first reading sets.

    The PROVIDER IS PASSED IN, never built here: this module stays free of keys, ciphers and HTTP so the
    whole of it can be tested without any of them. Both ship paths call this -- the bought label and the
    hand-typed number -- so there is one registration and one treatment of its answer.

    **BEST-EFFORT, ALWAYS.** `{}` on a missing carrier, a provider with no tracking feed, a network
    failure, or a reading we cannot read. By the time this is called the postage is paid and the parcel is
    going; a tracking registration that failed must never turn a successful shipment into an error the
    tenant thinks they should retry. It is the same rule the ledger writes after a label purchase follow.
    The cost of failing is that this parcel has no delivery feed, which is where every parcel started.
    """
    carrier = str((shipment or {}).get("carrier") or "").strip()
    number = str((shipment or {}).get("tracking_number") or "").strip()
    shipment_id = str((shipment or {}).get("shipment_id") or "").strip()
    if not provider or not carrier or not number or not shipment_id:
        return {}
    try:
        answer = provider.register_tracking(carrier=carrier, tracking_number=number,
                                            reference=shipment_id)
    except Exception:  # noqa: BLE001 - see docstring
        return {}
    initial = reading(answer)
    if not initial:
        # Registered, but with nothing to say yet -- the ordinary case for a label bought seconds ago.
        # Recorded anyway, so the Orders screen can tell "registered, no scan" from "never registered".
        return {"tracking_registered_at": int(now)}
    fields = fields_to_write(shipment, initial, now=now)
    if fields:
        fields["tracking_registered_at"] = int(now)
    return fields


def has_arrived(shipment: Any) -> bool:
    """Whether this parcel is known to have arrived. FALSE IS NOT "IT DID NOT ARRIVE" -- it is "we have no
    delivery for it", which is also the answer for every shipment predating this feed and every carrier
    that never scans. A caller deciding anything about money must treat the two apart."""
    stored = shipment if isinstance(shipment, dict) else {}
    return bool(int(stored.get("delivered_at") or 0))
