"""Server-side cart (plans/LISTICLE_AND_CART.md L2).

The cart is the authoritative record of what an anonymous shopper intends to buy from a listicle offer.
**Prices are always re-resolved server-side** from the offer + product/service (the same single-unit
resolver the listicle page renders with), never trusted from the client — the client only names *what* to
add (offer_id + product_id/service_id + qty), not the amount. This mirrors `listicle_slides()` in
`runtime/html.py` so a cart line's price always equals the price the page displayed; the shared
`single_unit_price` primitive keeps them from drifting.
"""
from __future__ import annotations

import hashlib
from typing import Any

from stripe_link.domain.pricing import single_unit_price
from stripe_link.domain.service_pricing import resolve_service_price

CART_SCHEMA_VERSION = 1
MAX_CART_LINES = 50
MAX_LINE_QTY = 99


class CartError(ValueError):
    """A cart request that can't be honored (unknown item, no price, full cart)."""


def clamp_qty(qty: Any) -> int:
    try:
        value = int(qty)
    except (TypeError, ValueError):
        value = 1
    return max(1, min(MAX_LINE_QTY, value))


def _line_id(product_id: str, service_id: str, price_id: str) -> str:
    """A stable id for a (product|service, price) pair so re-adding the same item merges quantities."""
    return hashlib.sha1(f"{product_id}|{service_id}|{price_id}".encode()).hexdigest()[:16]


def _find_offer_item(offer: dict[str, Any], product_id: str, service_id: str) -> dict[str, Any] | None:
    """The offer item that exposes this product/service — the offer is the contract; a client can't add an
    item the offer never listed."""
    for item in offer.get("items") or []:
        if product_id and str((item or {}).get("product_id") or "") == product_id:
            return item
        if service_id and str((item or {}).get("service_id") or "") == service_id:
            return item
    return None


def resolve_cart_line(
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
    *,
    product_id: str = "",
    service_id: str = "",
    qty: int = 1,
) -> dict[str, Any]:
    """Re-resolve one cart line from the offer + catalog. Returns the authoritative line dict or raises
    CartError. The pricing mirrors `listicle_slides()` exactly (single-unit price for products; the service's
    designated price for services) so the cart price == the page price."""
    product_id = str(product_id or "").strip()
    service_id = str(service_id or "").strip()
    if not product_id and not service_id:
        raise CartError("A product_id or service_id is required.")
    item = _find_offer_item(offer, product_id, service_id)
    if item is None:
        raise CartError("This item is not part of the offer.")
    qty = clamp_qty(qty)

    if product_id:
        product = products_by_id.get(product_id)
        if not product:
            raise CartError("Product not found.")
        item_default = str(item.get("default_price_id") or item.get("price_id") or product.get("default_price_id") or "")
        selectable_ids = [o.get("price_id") for o in item.get("selectable_prices") or []]
        price = single_unit_price(product, selectable_ids or ([item_default] if item_default else None), item_default)
        if not price:
            raise CartError("No price available for this product.")
        price_id = str(price.get("price_id") or "")
        return {
            "line_id": _line_id(product_id, "", price_id),
            "product_id": product_id, "service_id": "", "price_id": price_id,
            "name": str(product.get("name") or ""),
            "image": str((product.get("images") or [""])[0] or ""),
            "unit_amount": int(price.get("unit_amount") or 0),
            "currency": str(price.get("currency") or "usd"),
            "qty": qty,
        }

    service = services_by_id.get(service_id)
    if not service:
        raise CartError("Service not found.")
    # Mirror listicle_slides' service pricing: the service's designated price (item price_id when set).
    svc_price = resolve_service_price(service, str(item.get("price_id") or "")) or service.get("price") or (service.get("prices") or [{}])[0]
    price_id = str(svc_price.get("price_id") or item.get("price_id") or "")
    return {
        "line_id": _line_id("", service_id, price_id),
        "product_id": "", "service_id": service_id, "price_id": price_id,
        "name": str(service.get("name") or ""),
        "image": str((service.get("presentation") or {}).get("hero_image_url") or ""),
        "unit_amount": int(svc_price.get("unit_amount") or 0),
        "currency": str(svc_price.get("currency") or "usd"),
        "qty": qty,
    }


def new_cart(tenant_id: str, cart_id: str, offer_id: str, now: int) -> dict[str, Any]:
    return {
        "schema_version": CART_SCHEMA_VERSION,
        "document_type": "cart",
        "tenant_id": tenant_id,
        "cart_id": cart_id,
        "offer_id": offer_id,
        "line_items": [],
        "total_amount": 0,
        "item_count": 0,
        "currency": "usd",
        "created_at": int(now),
        "updated_at": int(now),
    }


def _recompute_totals(cart: dict[str, Any]) -> None:
    items = cart.get("line_items") or []
    cart["total_amount"] = sum(int(i.get("unit_amount") or 0) * int(i.get("qty") or 1) for i in items)
    cart["item_count"] = sum(int(i.get("qty") or 1) for i in items)
    cart["currency"] = str((items[0].get("currency") if items else cart.get("currency")) or "usd")


def add_line(cart: dict[str, Any], line: dict[str, Any]) -> dict[str, Any]:
    """Add a resolved line, merging quantity when the same (product/service, price) is already present."""
    items = cart.get("line_items") or []
    for existing in items:
        if existing.get("line_id") == line["line_id"]:
            existing["qty"] = clamp_qty(int(existing.get("qty") or 1) + int(line.get("qty") or 1))
            existing["unit_amount"] = line["unit_amount"]  # refresh price on re-add
            existing["currency"] = line["currency"]
            break
    else:
        if len(items) >= MAX_CART_LINES:
            raise CartError("This cart is full.")
        items.append(line)
    cart["line_items"] = items
    _recompute_totals(cart)
    return cart


def set_line_qty(cart: dict[str, Any], line_id: str, qty: int) -> dict[str, Any]:
    """Set a line's quantity; qty <= 0 removes it. Raises CartError if the line isn't in the cart."""
    items = cart.get("line_items") or []
    for existing in items:
        if existing.get("line_id") == line_id:
            if int(qty) <= 0:
                items.remove(existing)
            else:
                existing["qty"] = clamp_qty(qty)
            cart["line_items"] = items
            _recompute_totals(cart)
            return cart
    raise CartError("That item is not in the cart.")


def remove_line(cart: dict[str, Any], line_id: str) -> dict[str, Any]:
    items = [i for i in (cart.get("line_items") or []) if i.get("line_id") != line_id]
    if len(items) == len(cart.get("line_items") or []):
        raise CartError("That item is not in the cart.")
    cart["line_items"] = items
    _recompute_totals(cart)
    return cart
