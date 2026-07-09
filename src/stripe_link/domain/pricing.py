from dataclasses import dataclass
from typing import Any

from stripe_link.domain.service_pricing import resolve_service_price, service_booking_flow


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
    kind: str = "product"
    service_id: str = ""
    booking_flow: str = ""
    fulfillment_mode: str = "scheduled"
    duration_minutes: int = 0
    default_fulfiller_id: str = ""


def load_offer_products(tenant_id: str, offer: dict[str, Any], products_repo: Any) -> dict[str, dict[str, Any]]:
    products_by_id = {}
    for item in offer.get("items", []):
        product_id = str(item.get("product_id") or "")
        if not product_id:
            continue  # service items are loaded separately
        product = products_repo.get(tenant_id, product_id)
        if not product:
            raise PricingError(f"Product '{product_id}' was not found.")
        products_by_id[product_id] = product
    return products_by_id


def load_offer_services(tenant_id: str, offer: dict[str, Any], services_repo: Any) -> dict[str, dict[str, Any]]:
    services_by_id = {}
    for item in offer.get("items", []):
        service_id = str(item.get("service_id") or "")
        if not service_id:
            continue
        if services_repo is None:
            raise PricingError("Services repository is unavailable for a service offer item.")
        service = services_repo.get(tenant_id, service_id)
        if not service:
            raise PricingError(f"Service '{service_id}' was not found.")
        services_by_id[service_id] = service
    return services_by_id


def service_fulfillment_mode(service: dict[str, Any]) -> str:
    mode = str((service or {}).get("fulfillment_mode") or "scheduled").strip()
    return mode if mode in {"scheduled", "no_booking"} else "scheduled"


def booking_groups_for(offer: dict[str, Any], services_by_id: dict[str, dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Expand the Offer's service_booking_mode into groups of SCHEDULED service items — the single
    place grouping is computed. single_visit -> one group with all scheduled items; separate_visits
    -> one group per item. no_booking services are excluded (they never book). Returns item groups."""
    mode = str((offer or {}).get("service_booking_mode") or "single_visit")
    scheduled = [
        item
        for item in (offer.get("items") or [])
        if str(item.get("service_id") or "")
        and service_fulfillment_mode(services_by_id.get(str(item.get("service_id") or ""))) != "no_booking"
    ]
    if not scheduled:
        return []
    if mode == "separate_visits":
        return [[item] for item in scheduled]
    return [scheduled]


def resolve_service_offer_item(item: dict[str, Any], service: dict[str, Any], offer_context: str) -> ResolvedOfferItem:
    service_id = str(item.get("service_id") or "")
    if service.get("service_id") != service_id:
        raise PricingError(f"Offer item service '{service_id}' does not match service '{service.get('service_id', '')}'.")
    if service.get("active") is False:
        raise PricingError(f"Service '{service_id}' is not active.")
    price = resolve_service_price(service, str(item.get("price_id") or ""))
    if not price:
        raise PricingError(f"Price '{item.get('price_id', '')}' was not found on service '{service_id}'.")
    price_context = str(price.get("context") or "standard")
    quantity = int(item.get("quantity", 1))
    unit_amount = int(price.get("unit_amount", 0))
    flow = str(item.get("booking_flow") or "").strip() or service_booking_flow(service)
    return ResolvedOfferItem(
        product_id="",
        product_name=str(service.get("name") or ""),
        price_id=str(price.get("price_id") or ""),
        currency=str(price.get("currency") or "usd"),
        unit_amount=unit_amount,
        quantity=quantity,
        price_quantity=int(price.get("quantity") or 1),
        label=str(item.get("display_label") or price.get("label") or service.get("name") or ""),
        context=price_context,
        line_amount=unit_amount * quantity,
        selectable=False,
        kind="service",
        service_id=service_id,
        booking_flow=flow,
        fulfillment_mode=service_fulfillment_mode(service),
        duration_minutes=int(service.get("duration_minutes") or 0),
        default_fulfiller_id=str(service.get("default_fulfiller_id") or ""),
    )


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
    services_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    offer_status = offer.get("status") or ("active" if offer.get("active") is True else "archived")
    if offer_status != "active":
        raise PricingError(f"Offer '{offer.get('offer_id', '')}' is not active.")

    offer_context = offer.get("context", "standard")
    eligibility = offer.get("eligibility") or {}
    allowed_price_contexts = eligibility.get("allowed_price_contexts") or [offer_context]
    services_by_id = services_by_id or {}

    resolved_items: list[ResolvedOfferItem] = []
    for item in offer.get("items", []):
        service_id = str(item.get("service_id") or "")
        if service_id:
            service = services_by_id.get(service_id)
            if not service:
                raise PricingError(f"Service '{service_id}' was not provided for offer resolution.")
            resolved_items.append(resolve_service_offer_item(item, service, offer_context))
            continue
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
                "kind": item.kind,
                "product_id": item.product_id,
                "service_id": item.service_id,
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
                "booking_flow": item.booking_flow,
                "fulfillment_mode": item.fulfillment_mode,
                "duration_minutes": item.duration_minutes,
                "default_fulfiller_id": item.default_fulfiller_id,
            }
            for item in resolved_items
        ],
    }


def merge_resolved_offers(primary: dict[str, Any], additions: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold resolved order-bump offers into the primary resolved offer for a single checkout session.

    Each addition is itself the output of resolve_offer() for a distinct order-bump Offer document
    (context/price-context "order_bump"), so its own eligibility/active-status checks already ran.
    """
    currency = primary.get("currency", "usd")
    items = list(primary.get("items") or [])
    subtotal = int(primary.get("subtotal") or 0)
    for addition in additions:
        addition_currency = addition.get("currency", "usd")
        if addition.get("items") and addition_currency != currency:
            raise PricingError("Order bump currency does not match the primary offer currency.")
        items.extend(addition.get("items") or [])
        subtotal += int(addition.get("subtotal") or 0)
    return {**primary, "items": items, "subtotal": subtotal}
