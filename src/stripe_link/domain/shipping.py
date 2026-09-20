"""Shipping domain — pure, no I/O.

Starts with the destination address, because nothing else in shipping can happen without one. Checkout has
been collecting a shipping address from buyers of physical goods all along (`shipping_address_collection`
in handlers/checkout.py), and the order record never read it: every order ever placed here knows who bought
and not where it goes. A label cannot be bought, a rate cannot be quoted, and an integration has nothing to
hand a provider.
"""
from typing import Any

# The address shape used everywhere in shipping. Deliberately identical to ShippingConfig's `$defs/address`
# (ship-from and return-to), so a provider call takes an origin and a destination that look the same and
# nothing has to translate between two dialects of "address".
ADDRESS_FIELDS = (
    "name", "company", "street1", "street2", "city", "state", "postal_code", "country",
    "phone", "email", "residential",
)
REQUIRED_ADDRESS_FIELDS = ("name", "street1", "city", "state", "postal_code", "country")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def destination_address_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """The ship-to address a Checkout Session collected, or {} when it collected none.

    Reads BOTH shapes on purpose. `session.shipping_details` is where it has always lived; newer API
    versions move it under `session.collected_information.shipping_details`. We pin Stripe-Version
    2024-06-20 today, so the flat one is what arrives -- but a version bump that silently emptied every
    shipping address would be found by a tenant whose labels stopped working, not by us.

    Returns {} rather than a half-filled address when the required fields are not all present: a partial
    destination buys a label that cannot be delivered, and "no address" is a condition the caller can
    reason about while "an address missing its postcode" is not.
    """
    session = session or {}
    collected = session.get("collected_information")
    details = None
    for candidate in (session.get("shipping_details"),
                      (collected or {}).get("shipping_details") if isinstance(collected, dict) else None):
        if isinstance(candidate, dict) and candidate:
            details = candidate
            break
    if not isinstance(details, dict):
        return {}

    address = details.get("address") if isinstance(details.get("address"), dict) else {}
    customer = session.get("customer_details") if isinstance(session.get("customer_details"), dict) else {}

    destination = {
        # The name on the PARCEL is the shipping name when Stripe collected one; a buyer shipping to someone
        # else typed a different name there and the box has to carry it.
        "name": _clean(details.get("name")) or _clean(customer.get("name")),
        "street1": _clean(address.get("line1")),
        "street2": _clean(address.get("line2")),
        "city": _clean(address.get("city")),
        "state": _clean(address.get("state")),
        "postal_code": _clean(address.get("postal_code")),
        "country": _clean(address.get("country")).upper(),
        # Carriers charge more for a residential delivery and some require a phone number for it. Both come
        # from the customer block -- Stripe does not put them on the shipping address.
        "phone": _clean(customer.get("phone")),
        "email": _clean(customer.get("email")) or _clean(session.get("customer_email")),
    }
    if not all(destination.get(field) for field in REQUIRED_ADDRESS_FIELDS):
        return {}
    return {key: value for key, value in destination.items() if value}
