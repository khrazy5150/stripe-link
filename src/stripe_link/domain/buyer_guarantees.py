"""Promises about things going WRONG (plans/REFUND_POLICY_AND_GUARANTEES.md P4).

A refund policy answers one question — may I send this back, and by when. The Temu-style list the author
brought is a different axis entirely: price match, delay credit, damaged in transit, no-tracking-update
refund, non-delivery refund. None of those is a rule about returning an item, and no amount of
window/condition/return-method vocabulary can express one. So they are a SECOND primitive rather than
more fields on the first.

**The copy is generated here, server-side**, for the reason the first refund plan established: a browser
is not allowed to author a commercial promise. A JavaScript literal composing a refund sentence is how
every live page came to carry a promise nobody chose.

**These are the TENANT's promises, not the platform's.** Temu's list works because Temu is a marketplace
guaranteeing on its sellers' behalf; here the tenant IS the merchant. The generated copy reads in their
voice and must never imply that Junior Bay backs the promise, because it does not.

**Honouring them is manual in this phase, and this says so rather than implying otherwise.** Enabling
`no_delivery_refund` publishes a promise; the merchant still handles the request, exactly as with every
refund today. `delivery_status` already exists, so automatic detection is a credible later phase --
shipping the promise and the automation together would hold the promise hostage to the harder half.

`late_delivery_credit` from the example is deliberately absent: a store credit needs a buyer balance, and
this platform has no buyer accounts at all. A credit we cannot issue is a promise we cannot keep.

Free returns is deliberately absent too. It is `return_shipping: seller_pays` on the refund policy, and
two places to say one thing is the duplicate-source fault this repo keeps paying for.
"""

from typing import Any

DAMAGED_IN_TRANSIT = "damaged_in_transit"
NO_DELIVERY_REFUND = "no_delivery_refund"
NO_TRACKING_UPDATE_REFUND = "no_tracking_update_refund"
PRICE_MATCH = "price_match"
PRICE_ADJUSTMENT = "price_adjustment"

# CANONICAL ORDER, and it is load-bearing: the rendered list follows it, so two tenants' pages are
# comparable and a buyer who has read one knows where to look on the next. Ordered as the promises
# occur to a worried buyer -- did it arrive, is it moving, did I overpay.
GUARANTEES: tuple[str, ...] = (
    DAMAGED_IN_TRANSIT,
    NO_DELIVERY_REFUND,
    NO_TRACKING_UPDATE_REFUND,
    PRICE_MATCH,
    PRICE_ADJUSTMENT,
)

# `days` is None where the promise has no clock. The default is the number the example used, and it is a
# STARTING POINT the tenant edits -- never a value we publish without them enabling the guarantee first.
SPECS: dict[str, dict[str, Any]] = {
    DAMAGED_IN_TRANSIT: {
        "label": "Damaged or lost in transit",
        "days": None,
        "hint": "Covers the journey, not the goods: a parcel that arrives broken or never arrives at all.",
    },
    NO_DELIVERY_REFUND: {
        "label": "Not delivered in time",
        "days": 20,
        "min_days": 1,
        "max_days": 180,
        "hint": "Counts from the day it ships, so a slow carrier is on you rather than on the buyer.",
    },
    NO_TRACKING_UPDATE_REFUND: {
        "label": "Tracking stops moving",
        "days": 15,
        "min_days": 1,
        "max_days": 180,
        "hint": "A parcel that has stopped scanning is usually lost. This promises an answer before the "
                "buyer has to ask twice.",
    },
    PRICE_MATCH: {
        "label": "Cheaper somewhere else",
        "days": 30,
        "min_days": 1,
        "max_days": 365,
        "hint": "You refund the difference, not the order. Buyers have to show you where.",
    },
    PRICE_ADJUSTMENT: {
        "label": "Your own price drops",
        "days": 30,
        "min_days": 1,
        "max_days": 365,
        "hint": "The one most often asked for after a sale. You refund the difference to anyone who "
                "bought just before it.",
    },
}


def _whole(value: Any) -> int | None:
    """An integer, or None. Decimal survives a DynamoDB round trip and `isinstance(x, int)` is False
    for it -- the trap that once made stored page ids unreadable."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def default_days(key: str) -> int | None:
    return SPECS.get(key, {}).get("days")


def clamp_days(key: str, value: Any) -> int | None:
    """The tenant's number, held inside what the promise can mean. None where it has no clock.

    Clamped rather than refused: a settings screen that rejects 400 teaches the tenant to fight the form,
    and a promise of "within 400 days" is not a promise anyone acts on. Zero and negatives fall back to
    the default -- "refund if not delivered within 0 days" is a sentence with no behaviour behind it.
    """
    spec = SPECS.get(key) or {}
    if spec.get("days") is None:
        return None
    number = _whole(value)
    if number is None or number < 1:
        return int(spec["days"])
    return max(int(spec.get("min_days", 1)), min(int(spec.get("max_days", 365)), number))


def sentence(key: str, days: Any = None) -> str:
    """The promise, in the tenant's voice, generated here and never in a browser.

    First person plural throughout -- "we refund", not "the seller refunds" and not "Junior Bay
    refunds". The tenant is the merchant, and a sentence that named the platform would be claiming a
    guarantee the platform does not stand behind.
    """
    if key not in SPECS:
        return ""
    count = clamp_days(key, days)
    if key == DAMAGED_IN_TRANSIT:
        return ("If your order is lost or arrives damaged, we refund it in full — "
                "you do not need to send anything back.")
    if key == NO_DELIVERY_REFUND:
        return (f"If your order has not arrived {count} days after it ships, "
                "we refund it or send it again — your choice.")
    if key == NO_TRACKING_UPDATE_REFUND:
        return (f"If tracking shows no movement for {count} days, "
                "we refund it or send it again — your choice.")
    if key == PRICE_MATCH:
        return (f"Find it cheaper elsewhere within {count} days of buying and we refund the "
                "difference. Show us where.")
    return (f"If our own price drops within {count} days of your order, "
            "we refund you the difference.")


def normalize(stored: Any) -> dict[str, dict[str, Any]]:
    """Coerce the stored map into the shape the renderer reads. NEVER raises.

    Only ENABLED guarantees come back, and only ones this module knows -- a key retired later stops
    rendering rather than printing a promise nothing can explain. The sentence is regenerated on every
    read rather than trusted from storage, so a tenant who enabled this in October and a wording fix
    made in November cannot disagree on the page.
    """
    raw = stored if isinstance(stored, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for key in GUARANTEES:
        entry = raw.get(key)
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        days = clamp_days(key, entry.get("days"))
        promise: dict[str, Any] = {"enabled": True, "sentence": sentence(key, days)}
        if days is not None:
            promise["days"] = days
        out[key] = promise
    return out


def stored_guarantees(tenant_config: dict[str, Any] | None) -> dict[str, Any]:
    """Pull the map out of the settings document. Beside the refund policies, in the same place and for
    the same reason -- `legal_defaults` is where the tenant's promises live."""
    config = tenant_config or {}
    legal = config.get("legal_defaults")
    if isinstance(legal, dict) and isinstance(legal.get("buyer_guarantees"), dict):
        return legal["buyer_guarantees"]
    stored = config.get("buyer_guarantees")
    return stored if isinstance(stored, dict) else {}


def resolve(tenant_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The enabled guarantees, in canonical order, ready to render. Empty means the section does not
    render at all -- a tenant who wants none is unaffected."""
    enabled = normalize(stored_guarantees(tenant_config))
    return [{"key": key, **enabled[key]} for key in GUARANTEES if key in enabled]


def vocabulary() -> dict[str, Any]:
    """Everything the settings screen needs, INCLUDING the previewed sentence at the default number.

    The preview arrives from the server for the same reason the refund previews do: the browser must
    never be the thing that composes a commercial promise. The screen re-asks when the number changes.
    """
    return {
        "order": list(GUARANTEES),
        "items": [{
            "key": key,
            "label": SPECS[key]["label"],
            "hint": SPECS[key]["hint"],
            "days": SPECS[key]["days"],
            "min_days": SPECS[key].get("min_days"),
            "max_days": SPECS[key].get("max_days"),
            "sentence": sentence(key, SPECS[key]["days"]),
        } for key in GUARANTEES],
    }
