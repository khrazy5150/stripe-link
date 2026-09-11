"""The slim list projection of a product.

Why: the Offers screen loads the WHOLE product catalogue on mount — it needs names for card item summaries,
prices for deriving funnel roles, and images for the card fallback — and the Products screen loads it too.
Product documents average ~3.1KB, LARGER than offers, and tenants usually have more of them, so on the
numbers this payload reaches the 6MB Lambda response ceiling before offers do (2,000 products = 5.9MB).

Unlike the offer index this CANNOT drop the dominant field. `prices` is ~57% of a product and the funnel
derivation reads every price's context; without them the Offers screen could not tell an upsell from a
landing item. What it drops is the parts of each price nothing reads.

Field choices were measured, not guessed — every field the dashboard demonstrably accesses is kept:
  kept on the price   price_id, context, unit_amount, currency, pricing_model, quantity,
                      stripe_price_id (the edit form's "not synced" warning), compare_at_unit_amount
                      (discount %), fee_handling, suggested_amount, tenant_keyed_amount
  dropped             fee_breakdown (93B, the single largest), previous_price_id, created_at/updated_at
  dropped on the doc  refund_policy (~10%), variants, image_dims, sync, fulfillment detail, identifiers

Editing a product fetches the full document via GET /products/{product_id}, the same split the offer index
uses: the list never loads what only an editor needs.
"""

from typing import Any

# Everything the dashboard reads off a price. Anything not here is not referenced anywhere in dashboard/src.
_PRICE_FIELDS = (
    "price_id", "context", "unit_amount", "currency", "pricing_model", "quantity",
    "stripe_price_id", "compare_at_unit_amount", "fee_handling", "suggested_amount",
    "tenant_keyed_amount", "label",
)

# Card display, search (stores/products.js productSearchText) and status filtering.
_DOC_FIELDS = (
    "product_id", "name", "description", "product_category", "product_type", "tags",
    "status", "active", "stripe_product_id", "images", "lead_capture",
    # product_intent was MISSING here while lead_capture was present, which is a shape that cannot be
    # right: the row carried the lead-gen DETAIL and not the flag saying it was lead-gen. The dashboard
    # defaults a missing intent to "transaction", so a lead-gen product was badged "Transaction" in the
    # offer selector (indistinguishable from the rest) and the offer built from it was stamped
    # transaction -- which the backend then rejected against the product's real intent. Reported
    # 2026-09-10.
    "product_intent",
)


def product_index_entry(product: dict[str, Any]) -> dict[str, Any]:
    """One product as a list-projection row: card fields, search fields, and slim prices."""
    entry: dict[str, Any] = {}
    for field in _DOC_FIELDS:
        value = product.get(field)
        # Keep False and 0 — `active: false` is what marks a product archived.
        if value not in (None, "", [], {}):
            entry[field] = value

    prices = []
    for price in product.get("prices") or []:
        if not isinstance(price, dict):
            continue
        slim = {key: price[key] for key in _PRICE_FIELDS if price.get(key) not in (None, "")}
        if slim:
            prices.append(slim)
    if prices:
        entry["prices"] = prices
    return entry
