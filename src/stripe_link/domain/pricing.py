from dataclasses import dataclass
from typing import Any


class PricingError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedOfferItem:
    product_id: str
    product_name: str
    price_id: str
    currency: str
    unit_amount: int
    quantity: int
    price_quantity: int
    label: str
    context: str
    line_amount: int
    selectable: bool


def find_price(product: dict[str, Any], price_id: str) -> dict[str, Any]:
    for price in product.get("prices", []):
        if price.get("price_id") == price_id:
            return price
    raise PricingError(f"Price '{price_id}' was not found on product '{product.get('product_id', '')}'.")


def selected_price_id_for_item(item: dict[str, Any], selected_prices: dict[str, str]) -> str:
    product_id = item.get("product_id", "")
    selectable_prices = item.get("selectable_prices") or []
    if selectable_prices:
        selected_price_id = selected_prices.get(product_id) or item.get("default_price_id", "")
        allowed_price_ids = {price.get("price_id") for price in selectable_prices}
        if selected_price_id not in allowed_price_ids:
            raise PricingError(f"Selected price '{selected_price_id}' is not selectable for product '{product_id}'.")
        return selected_price_id
    return item.get("price_id", "")


def selectable_price_override(item: dict[str, Any], price_id: str) -> dict[str, Any]:
    for price in item.get("selectable_prices") or []:
        if price.get("price_id") == price_id:
            return price
    return {}


def resolve_offer_item(
    item: dict[str, Any],
    product: dict[str, Any],
    offer_context: str,
    selected_prices: dict[str, str] | None = None,
) -> ResolvedOfferItem:
    product_id = item.get("product_id")
    if product.get("product_id") != product_id:
        raise PricingError(f"Offer item product '{product_id}' does not match product '{product.get('product_id', '')}'.")
    product_status = product.get("status") or ("archived" if product.get("active") is False else "active")
    if product_status == "archived":
        raise PricingError(f"Product '{product_id}' is not active.")

    selected_prices = selected_prices or {}
    price_id = selected_price_id_for_item(item, selected_prices)
    price = find_price(product, price_id)
    if price.get("active") is False:
        raise PricingError(f"Price '{price.get('price_id', '')}' is not active.")

    price_context = price.get("context", "standard")
    allowed_contexts = item.get("allowed_price_contexts") or [offer_context]
    if offer_context and price_context not in allowed_contexts:
        raise PricingError(
            f"Price '{price.get('price_id', '')}' context '{price_context}' is not valid for offer context '{offer_context}'."
        )

    item_quantity = int(item.get("quantity", 1))
    override = selectable_price_override(item, price_id)
    unit_amount = int(price.get("unit_amount", 0))
    return ResolvedOfferItem(
        product_id=product_id,
        product_name=product.get("name", ""),
        price_id=price.get("price_id", ""),
        currency=price.get("currency", "usd"),
        unit_amount=unit_amount,
        quantity=item_quantity,
        price_quantity=int(override.get("quantity") or price.get("quantity", 1)),
        label=item.get("display_label") or override.get("label") or price.get("label", ""),
        context=price_context,
        line_amount=unit_amount * item_quantity,
        selectable=bool(item.get("selectable_prices")),
    )


def resolve_offer(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    selected_prices: dict[str, str] | None = None,
) -> dict[str, Any]:
    offer_status = offer.get("status") or ("active" if offer.get("active") is True else "archived")
    if offer_status != "active":
        raise PricingError(f"Offer '{offer.get('offer_id', '')}' is not active.")

    offer_context = offer.get("context", "standard")
    eligibility = offer.get("eligibility") or {}
    allowed_price_contexts = eligibility.get("allowed_price_contexts") or [offer_context]

    resolved_items: list[ResolvedOfferItem] = []
    for item in offer.get("items", []):
        product_id = item.get("product_id", "")
        product = products_by_id.get(product_id)
        if not product:
            raise PricingError(f"Product '{product_id}' was not provided for offer resolution.")
        item_with_context = {**item, "allowed_price_contexts": allowed_price_contexts}
        resolved_items.append(resolve_offer_item(item_with_context, product, offer_context, selected_prices))

    return {
        "offer_id": offer.get("offer_id", ""),
        "tenant_id": offer.get("tenant_id", ""),
        "context": offer_context,
        "currency": resolved_items[0].currency if resolved_items else "usd",
        "subtotal": sum(item.line_amount for item in resolved_items),
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "price_id": item.price_id,
                "currency": item.currency,
                "unit_amount": item.unit_amount,
                "quantity": item.quantity,
                "price_quantity": item.price_quantity,
                "label": item.label,
                "context": item.context,
                "line_amount": item.line_amount,
                "selectable": item.selectable,
            }
            for item in resolved_items
        ],
    }
