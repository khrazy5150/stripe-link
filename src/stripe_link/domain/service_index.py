"""The slim list projection of a service.

Third of its kind (offers, products, services). Services are loaded whole by their own screen, by the
Offers screen (item names and the unified item picker) and by Invoices — so the payload is paid three
times, and 2,000 services is ~3.9MB against the 6MB Lambda response ceiling.

Fields chosen by measuring what dashboard/src actually reads off a service, the same way the product index
was scoped: service_id, name, description, prices, presentation, price, location_mode, fulfillment_mode,
default_price_id, booking_flow, allowed_fulfillers. `booking_rules`, `image_dims` and timestamps are not
read by any list or picker, so they stay behind GET /services/{service_id} for the editor.
"""

from typing import Any

# Everything a list card, the search filter, or the Offers item picker reads.
_FIELDS = (
    "service_id", "name", "description", "location_mode", "fulfillment_mode",
    "booking_flow", "default_price_id", "allowed_fulfillers", "active", "status",
    "presentation", "price", "duration_minutes",
)

# A service's prices are needed for the same reason a product's are: the Offers screen prices a service
# line and derives what it can be sold as. Only the read fields survive.
_PRICE_FIELDS = (
    "price_id", "context", "unit_amount", "currency", "pricing_model", "quantity",
    "stripe_price_id", "compare_at_unit_amount", "fee_handling", "label",
)


def service_index_entry(service: dict[str, Any]) -> dict[str, Any]:
    """One service as a list-projection row."""
    entry: dict[str, Any] = {}
    for field in _FIELDS:
        value = service.get(field)
        # Keep False and 0 — `active: false` is what marks a service inactive.
        if value not in (None, "", [], {}):
            entry[field] = value

    prices = []
    for price in service.get("prices") or []:
        if not isinstance(price, dict):
            continue
        slim = {key: price[key] for key in _PRICE_FIELDS if price.get(key) not in (None, "")}
        if slim:
            prices.append(slim)
    if prices:
        entry["prices"] = prices
    return entry
