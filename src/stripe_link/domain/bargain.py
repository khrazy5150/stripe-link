"""The numbers behind the Price Highlight element (plans/PRICE_HIGHLIGHT.md).

Prices are catalog data. The tenant authors two lines of copy; everything numeric here is DERIVED, so a
sale price can never be typed into a page and drift from what checkout charges.

Kept out of html.py deliberately: it is arithmetic with rules, and rules that decide what a shopper is told
about a discount deserve tests that do not go through a renderer.
"""

from typing import Any

from stripe_link.domain.opportunities import STAGE_LANDING, stage_opportunities

# Shown before the amount when an item is tiered, so the figure is a claim about the RANGE rather than
# about whatever tier the visitor has selected. Not tenant-editable: it is what makes the sentence true.
# A tenant who changed it to "just", or deleted it, would turn it back into a selection claim and it could
# then contradict the price selector on the same page.
FROM_PREFIX = "as low as"


def _prices_of(entity: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [price for price in ((entity or {}).get("prices") or []) if isinstance(price, dict)]


def _amounts(price: dict[str, Any]) -> tuple[int, int]:
    """(sale, regular) for one price. Regular falls back to the sale amount when there is no compare-at,
    so an item without a discount contributes honestly to a bundle total instead of inflating it."""
    sale = int(price.get("unit_amount") or 0)
    regular = int(price.get("compare_at_unit_amount") or price.get("compare_at_amount") or 0)
    return sale, (regular if regular > sale else sale)


def _item_amounts(opportunity: dict[str, Any], entity: dict[str, Any] | None) -> tuple[int, int, bool]:
    """(sale, regular, tiered) for one landing opportunity.

    A tiered item contributes its LOWEST tier — the figure "as low as" refers to. Pairing is strict: the
    regular price returned is that same tier's compare-at, never a richer tier's, because pairing a low
    sale price against a high regular from elsewhere overstates the discount.
    """
    prices = _prices_of(entity)
    by_id = {str(price.get("price_id") or ""): price for price in prices}
    quantity = max(1, int(opportunity.get("quantity") or 1))

    tiers = [by_id[str(tier.get("price_id") or "")]
             for tier in (opportunity.get("selectable_prices") or [])
             if str(tier.get("price_id") or "") in by_id]

    if len(tiers) > 1:
        # Lowest by SALE price, then take that same price's regular — the pairing rule.
        cheapest = min(tiers, key=lambda price: int(price.get("unit_amount") or 0))
        sale, regular = _amounts(cheapest)
        return sale * quantity, regular * quantity, True

    chosen = by_id.get(str(opportunity.get("price_id") or "")) or (tiers[0] if tiers else None)
    if chosen is None:
        chosen = next((price for price in prices if str(price.get("context") or "standard") == "standard"), None)
    if chosen is None:
        return 0, 0, False
    sale, regular = _amounts(chosen)
    return sale * quantity, regular * quantity, False


def derived_bargain(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """What the Price Highlight shows.

    Returns {sale, regular, currency, tiered, has_bargain}. `has_bargain` is False when the regular total
    is not greater than the sale total — there is nothing to strike through — and the element must then
    render the price and the copy WITHOUT a strikethrough rather than rendering nothing. Silently dropping
    content when a field is absent is the bug client_marquee has today.
    """
    services_by_id = services_by_id or {}
    sale_total = 0
    regular_total = 0
    tiered = False
    currency = ""

    for opportunity in stage_opportunities(offer, STAGE_LANDING):
        service_id = str(opportunity.get("service_id") or "")
        entity = services_by_id.get(service_id) if service_id else products_by_id.get(
            str(opportunity.get("product_id") or "")
        )
        sale, regular, item_tiered = _item_amounts(opportunity, entity)
        if not sale:
            continue
        sale_total += sale
        regular_total += regular
        tiered = tiered or item_tiered
        if not currency:
            currency = next(
                (str(price.get("currency") or "") for price in _prices_of(entity) if price.get("currency")),
                "",
            )

    return {
        "sale": sale_total,
        "regular": regular_total,
        "currency": currency or "usd",
        "tiered": tiered,
        "has_bargain": regular_total > sale_total > 0,
    }
