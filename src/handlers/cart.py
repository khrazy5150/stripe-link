"""Server-side cart API (plans/LISTICLE_AND_CART.md L2).

Public + anonymous (a shopper on a published listicle page), same posture as `/leads`: tenant/offer are
resolved server-side from the payload IDs, and **every line price is re-resolved server-side** from the
offer + catalog — the client names *what* to add, never the amount. The cart id is opaque, minted here on
first add and echoed back for the browser to persist (localStorage).
"""
import re
import secrets
import time
from typing import Callable

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    query_params,
)
from stripe_link.domain.cart import (
    CartError,
    add_line,
    clamp_qty,
    new_cart,
    resolve_cart_line,
)
from stripe_link.domain.documents import DocumentValidationError, validate_cart
from stripe_link.repositories.documents import (
    RepositoryError,
    carts_repository,
    offers_repository,
    products_repository,
    services_repository,
)

CART_RETENTION_SECONDS = 30 * 24 * 60 * 60  # abandoned carts expire after 30 days (Dynamo TTL)
_CART_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def handler(
    event,
    context,
    *,
    carts_repo=None,
    offers_repo=None,
    products_repo=None,
    services_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    carts_repo = carts_repo or carts_repository()
    if method == "POST":
        return add_item(
            event,
            carts_repo=carts_repo,
            offers_repo=offers_repo or offers_repository(),
            products_repo=products_repo or products_repository(),
            services_repo=services_repo or services_repository(),
            now=now_fn(),
        )
    if method == "GET":
        return get_cart(event, carts_repo)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _load_offer_context(tenant_id, offer_id, product_id, service_id, *, offers_repo, products_repo, services_repo):
    """Load the offer plus only the one product/service being added — enough to re-resolve the line."""
    offer = offers_repo.get(tenant_id, offer_id)
    if not offer:
        return None, {}, {}
    products_by_id = {}
    services_by_id = {}
    if product_id:
        product = products_repo.get(tenant_id, product_id)
        if product:
            products_by_id[product_id] = product
    if service_id:
        service = services_repo.get(tenant_id, service_id)
        if service:
            services_by_id[service_id] = service
    return offer, products_by_id, services_by_id


def add_item(event, *, carts_repo, offers_repo, products_repo, services_repo, now):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_cart")

    tenant_id = str(body.get("tenant_id") or "").strip()
    offer_id = str(body.get("offer_id") or "").strip()
    product_id = str(body.get("product_id") or "").strip()
    service_id = str(body.get("service_id") or "").strip()
    if not tenant_id or not offer_id:
        return error_response("tenant_id and offer_id are required.", code="invalid_cart")
    if not product_id and not service_id:
        return error_response("A product_id or service_id is required.", code="invalid_cart")

    offer, products_by_id, services_by_id = _load_offer_context(
        tenant_id, offer_id, product_id, service_id,
        offers_repo=offers_repo, products_repo=products_repo, services_repo=services_repo,
    )
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")

    try:
        line = resolve_cart_line(
            offer, products_by_id, services_by_id,
            product_id=product_id, service_id=service_id, qty=clamp_qty(body.get("qty", 1)),
        )
    except CartError as exc:
        return error_response(str(exc), code="invalid_cart")

    # Load-or-create the cart. A client-supplied cart_id must be well-formed and belong to this tenant+offer.
    cart_id = str(body.get("cart_id") or "").strip()
    cart = None
    if cart_id:
        if not _CART_ID_RE.match(cart_id):
            return error_response("Invalid cart_id.", code="invalid_cart")
        existing = carts_repo.get(tenant_id, cart_id)
        if existing and existing.get("offer_id") == offer_id:
            cart = existing
    if cart is None:
        cart_id = cart_id if (cart_id and _CART_ID_RE.match(cart_id)) else secrets.token_hex(16)
        cart = new_cart(tenant_id, cart_id, offer_id, now)

    try:
        add_line(cart, line)
    except CartError as exc:
        return error_response(str(exc), code="invalid_cart")

    cart["updated_at"] = int(now)
    cart["retention_expires_at"] = int(now) + CART_RETENTION_SECONDS
    try:
        validate_cart(cart)
        carts_repo.put(cart)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_cart")

    return json_response({"cart_id": cart_id, "cart": _public_cart(cart)}, status_code=201)


def get_cart(event, carts_repo):
    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip()
    cart_id = str(params.get("cart_id") or "").strip()
    if not tenant_id or not cart_id:
        return error_response("tenant_id and cart_id are required.", code="invalid_cart")
    cart = carts_repo.get(tenant_id, cart_id)
    if not cart:
        return error_response("Cart not found.", status_code=404, code="not_found")
    return json_response({"cart": _public_cart(cart)})


def _public_cart(cart: dict) -> dict:
    """The cart shape the browser needs — drops internal bookkeeping (keys already stripped by the repo)."""
    return {
        "cart_id": cart.get("cart_id"),
        "offer_id": cart.get("offer_id"),
        "line_items": cart.get("line_items") or [],
        "total_amount": int(cart.get("total_amount") or 0),
        "item_count": int(cart.get("item_count") or 0),
        "currency": cart.get("currency") or "usd",
    }
