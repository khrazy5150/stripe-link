"""What the carrier charged, mirrored into the PaymentIntent's metadata.

`plans/MONEY_ACROSS_SILOS.md` P3, the half that was deferred. P2 put COGS on the PaymentIntent at
checkout, which took five of the six ledger components into Stripe; shipping cost is the sixth and it is
the awkward one, because **it is not known at checkout**. It is known when the label is bought, which is
after the charge — so it arrives as a metadata update rather than a stamp.

**What this is for, stated honestly: durability and portability, not verification.** These are OUR
numbers. Stripe has no independent view of what a carrier charged us, so reading them back proves
nothing about them — the plan's own words are *"a side-car value we wrote, with Stripe's durability and
none of Stripe's authority."* The point is that **any silo can reconstruct a tenant's money from Stripe
alone**, without reaching into the owning silo's tables. The ledger stays canonical.

**One key per LABEL, not a running total.** A running total has to be read before it is written, and a
retried purchase would then add the same postage twice. Stripe MERGES metadata on update, so a key named
after the shipment is idempotent by overwrite: the same label writes the same key and the total does not
move. It also costs no GET, on a path that is already waiting on a carrier.

**Positive magnitudes here, negative in the ledger.** `ledger.shipping_cost_entry` negates on the way in
so that "up is good" holds for every component; `cogs` stamps the positive magnitude for the same reason
it reads naturally. The metadata matches `cogs`, and the reader below is the only thing that needs to
know.
"""
from __future__ import annotations

from typing import Any

# Deliberately two characters. Stripe allows 50 keys of 40 characters, and a multi-parcel order spends
# one key per label -- so the prefix is short to leave room for the reference, not to save bytes.
OUTBOUND_PREFIX = "sc_"
RETURN_PREFIX = "sr_"

# Enough of the shipment id to be unique within ONE order, which is the only scope these keys share. A
# carrier id is 30-plus characters and the whole thing is not needed to tell two parcels of one order
# apart; 8 hex characters give a collision chance of about one in a million across fifty labels.
REF_LENGTH = 8

# Stripe's ceiling is 50 metadata keys and the PaymentIntent already carries the silo stamp plus the
# three COGS keys, so an order would need forty-odd parcels to reach it. Deliberately NOT guarded here:
# a guard would cost a GET of the PaymentIntent on every label purchase to answer a question no real
# order asks, and the caller already treats a rejected update as a logged skip rather than a failure.


def _ref(shipment_id: str) -> str:
    """A short, stable reference for one label.

    The TAIL rather than the head, because carrier ids are prefixed (`shp_`, `track_`) and leading
    characters are shared across every shipment of every tenant -- taking the front would make two
    parcels of one order collide, which is the single thing this reference has to prevent.
    """
    cleaned = "".join(ch for ch in str(shipment_id or "").lower() if ch.isalnum())
    return cleaned[-REF_LENGTH:]


def stamp(shipment_id: str, amount: int, *, returning: bool = False) -> dict[str, str]:
    """The one metadata key this label adds, or `{}` when there is nothing to say.

    A zero-cost label writes nothing: a key saying "this parcel cost nothing" is indistinguishable from
    one we failed to record, and it spends a key against the ceiling to say it.
    """
    ref = _ref(shipment_id)
    try:
        cents = abs(int(amount or 0))
    except (TypeError, ValueError):
        return {}
    if not ref or not cents:
        return {}
    return {f"{RETURN_PREFIX if returning else OUTBOUND_PREFIX}{ref}": str(cents)}


def from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """`{"shipping_cost", "outbound", "returns", "labels", "known"}` summed over every label key.

    The outbound and return totals are kept apart because the ledger keeps them apart, and for the same
    reason: `shipping_margin` asks *"did what I charged for postage cover what posting it cost?"*, and a
    return has no postage revenue beside it. Folding the two here would make a tenant's outbound pricing
    look like it loses money whenever a buyer sends something back.

    `known` is False when no label key is present at all — which is every charge taken before this
    shipped, and every physical order whose label has not been bought yet. **Absent is not zero**: a
    reconstruction that reported those as costing nothing to post would overstate profit by exactly the
    postage, which is the failure the whole component exists to prevent.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    outbound = returns = labels = 0
    for key, raw in metadata.items():
        name = str(key)
        if name.startswith(OUTBOUND_PREFIX):
            outbound += _int(raw)
        elif name.startswith(RETURN_PREFIX):
            returns += _int(raw)
        else:
            continue
        labels += 1
    return {
        "shipping_cost": outbound + returns,
        "outbound": outbound,
        "returns": returns,
        "labels": labels,
        "known": labels > 0,
    }


def _int(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0
