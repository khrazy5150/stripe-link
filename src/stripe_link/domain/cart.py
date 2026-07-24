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
CART_STATUSES = {"open", "converted"}
CART_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # identified/recovery links expire after 30 days


class CartError(ValueError):
    """A cart request that can't be honored (unknown item, no price, full cart)."""


def normalize_email(email: Any) -> str:
    """A lightly-normalized email (trim + lowercase) or '' when it doesn't look like one. Not RFC-strict —
    just enough to gate recovery eligibility and keep junk out of the cart."""
    value = str(email or "").strip().lower()
    if "@" not in value or "." not in value.split("@")[-1] or " " in value or len(value) > 254:
        return ""
    return value


def apply_email(cart: dict[str, Any], email: Any) -> dict[str, Any]:
    """Stamp a customer email onto the cart (recovery eligibility). Latest valid email wins; junk is ignored."""
    normalized = normalize_email(email)
    if normalized:
        cart["email"] = normalized
    return cart


def cart_token_doc(
    tenant_id: str,
    token: str,
    email: str,
    offer_id: str,
    now: int,
    *,
    cart_id: str = "",
    ttl_seconds: int = CART_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    """An opaque identified-link / recovery token that dereferences to a customer's email (+ optional cart).
    Stored so the token itself carries no PII in the URL (plans/LISTICLE_AND_CART.md L2 Slice D)."""
    return {
        "schema_version": CART_SCHEMA_VERSION,
        "document_type": "cart_token",
        "tenant_id": tenant_id,
        "token": token,
        "email": normalize_email(email),
        "offer_id": str(offer_id or ""),
        "cart_id": str(cart_id or ""),
        "created_at": int(now),
        "expires_at": int(now) + ttl_seconds,
        "retention_expires_at": int(now) + ttl_seconds,  # Dynamo TTL cleanup
    }


def cart_token_valid(token_doc: dict[str, Any] | None, now: int) -> bool:
    """A token resolves only if it exists, carries an email, and hasn't expired."""
    if not token_doc:
        return False
    if not normalize_email(token_doc.get("email")):
        return False
    return int(token_doc.get("expires_at") or 0) > int(now)


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


def resolved_items_for_checkout(
    cart: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-resolve every cart line against the current offer/catalog and shape it for
    `build_checkout_payload` (a `resolved`-style item). Prices are re-resolved here (not read from storage)
    so a merchant price change between add and checkout is honored. Raises CartError on an empty cart or a
    line that no longer resolves. Service lines are not yet cart-checkout-eligible (booking has its own flow).
    """
    items: list[dict[str, Any]] = []
    for line in cart.get("line_items") or []:
        product_id = str(line.get("product_id") or "").strip()
        service_id = str(line.get("service_id") or "").strip()
        if service_id:
            raise CartError("A service in your cart must be booked individually.")
        fresh = resolve_cart_line(offer, products_by_id, services_by_id, product_id=product_id, qty=int(line.get("qty") or 1))
        items.append({
            "product_id": fresh["product_id"],
            "price_id": fresh["price_id"],
            "currency": fresh["currency"],
            "unit_amount": fresh["unit_amount"],
            "quantity": fresh["qty"],
            "product_name": fresh["name"],
        })
    if not items:
        raise CartError("Your cart is empty.")
    return items


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
        "email": "",
        "status": "open",  # -> "converted" once the cart's checkout is paid (drops it from the recovery sweep)
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


def mark_converted(cart: dict[str, Any], now: int) -> dict[str, Any]:
    """Flag the cart paid so the abandonment sweep skips it. Set on the Stripe payment webhook, NOT at session
    creation — a shopper who reaches Stripe but doesn't pay stays `open` and is a prime recovery target."""
    cart["status"] = "converted"
    cart["updated_at"] = int(now)
    return cart


def normalize_page_url(url: Any) -> str:
    """The listicle page URL a recovery link points back to. HTTPS-only + length-capped; the recovery email
    only ever goes to the cart's own email, so the blast radius is the email owner (still, gate the scheme)."""
    value = str(url or "").strip()
    return value if value.startswith("https://") and len(value) <= 2048 else ""


def recoverable(cart: dict[str, Any], now: int, *, min_age_seconds: int, max_attempts: int) -> bool:
    """Whether the abandonment sweep should email this cart: still open, has an email + items + a page to
    return to, not opted out, gone quiet longer than the threshold, and under the send cap."""
    if cart.get("status") != "open" or cart.get("email_opted_out"):
        return False
    if not normalize_email(cart.get("email")) or int(cart.get("item_count") or 0) <= 0:
        return False
    if not normalize_page_url(cart.get("page_url")):
        return False
    if int(now) - int(cart.get("updated_at") or 0) < int(min_age_seconds):
        return False
    return int((cart.get("recovery") or {}).get("attempts") or 0) < int(max_attempts)


def mark_recovery_sent(cart: dict[str, Any], now: int) -> dict[str, Any]:
    """Record a recovery send (bumps the attempt count so the cap holds). Does NOT touch `updated_at` — that
    tracks shopper activity, not our outreach."""
    recovery = dict(cart.get("recovery") or {})
    recovery["attempts"] = int(recovery.get("attempts") or 0) + 1
    recovery["last_sent_at"] = int(now)
    cart["recovery"] = recovery
    return cart


def mark_opted_out(cart: dict[str, Any], now: int) -> dict[str, Any]:
    """Honor an unsubscribe — the cart is never emailed again."""
    cart["email_opted_out"] = True
    cart["updated_at"] = int(now)
    return cart
