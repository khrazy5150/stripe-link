"""Server-side cart API (plans/LISTICLE_AND_CART.md L2).

Public + anonymous (a shopper on a published listicle page), same posture as `/leads`: tenant/offer are
resolved server-side from the payload IDs, and **every line price is re-resolved server-side** from the
offer + catalog — the client names *what* to add, never the amount. The cart id is opaque, minted here on
first add and echoed back for the browser to persist (localStorage).
"""
import os
import re
import secrets
import time
from typing import Callable

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    path_params,
    query_params,
)
from stripe_link.domain.cart import (
    CartError,
    add_line,
    apply_email,
    cart_token_valid,
    clamp_qty,
    mark_opted_out,
    new_cart,
    normalize_page_url,
    remove_line,
    resolve_cart_line,
    set_line_qty,
)
from stripe_link.domain.documents import DocumentValidationError, validate_cart
from stripe_link.repositories.documents import (
    RepositoryError,
    cart_tokens_repository,
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
    cart_tokens_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    carts_repo = carts_repo or carts_repository()
    if cart_tokens_repo is None and os.environ.get("CARTS_TABLE"):
        cart_tokens_repo = cart_tokens_repository()
    resource = str((event or {}).get("resource") or (event or {}).get("path") or "")
    if resource.endswith("/unsubscribe"):
        return unsubscribe(event, carts_repo, cart_tokens_repo, now_fn())
    if method == "POST":
        return add_item(
            event,
            carts_repo=carts_repo,
            offers_repo=offers_repo or offers_repository(),
            products_repo=products_repo or products_repository(),
            services_repo=services_repo or services_repository(),
            cart_tokens_repo=cart_tokens_repo,
            now=now_fn(),
        )
    if method == "GET":
        return get_cart(event, carts_repo, cart_tokens_repo, now_fn())
    if method in ("PATCH", "DELETE"):
        line_id = str(path_params(event).get("line_id") or "").strip()
        if not line_id:
            return error_response("line_id is required.", code="invalid_cart")
        return mutate_item(event, carts_repo, line_id, remove=(method == "DELETE"), now=now_fn())
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


def _resolve_email(body, tenant_id, cart_tokens_repo, now):
    """Identify the shopper for recovery: an identified-link `ct` token (dereferenced server-side, no PII in
    the URL) wins; otherwise an explicit `email` a checkout-start/lead form may send. '' when neither valid."""
    token = str(body.get("ct") or "").strip()
    if token and cart_tokens_repo is not None:
        token_doc = cart_tokens_repo.get(tenant_id, token)
        if cart_token_valid(token_doc, now):
            return str(token_doc.get("email") or "")
    return str(body.get("email") or "")


def add_item(event, *, carts_repo, offers_repo, products_repo, services_repo, cart_tokens_repo, now):
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

    # Identify the shopper (identified-link token or explicit email) so the cart is recovery-eligible.
    apply_email(cart, _resolve_email(body, tenant_id, cart_tokens_repo, now))
    page_url = normalize_page_url(body.get("page_url"))
    if page_url:
        cart["page_url"] = page_url  # where a recovery link returns the shopper

    cart["updated_at"] = int(now)
    cart["retention_expires_at"] = int(now) + CART_RETENTION_SECONDS
    try:
        validate_cart(cart)
        carts_repo.put(cart)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_cart")

    return json_response({"cart_id": cart_id, "cart": _public_cart(cart)}, status_code=201)


def mutate_item(event, carts_repo, line_id, *, remove, now):
    """PATCH sets a line's qty (qty<=0 removes); DELETE removes it. tenant_id + cart_id identify the cart —
    a shopper can only touch a cart whose id they hold (minted for their browser)."""
    try:
        body = parse_json_body(event)
    except ValueError:
        body = {}
    params = query_params(event)
    tenant_id = str(body.get("tenant_id") or params.get("tenant_id") or "").strip()
    cart_id = str(body.get("cart_id") or params.get("cart_id") or "").strip()
    if not tenant_id or not cart_id:
        return error_response("tenant_id and cart_id are required.", code="invalid_cart")
    cart = carts_repo.get(tenant_id, cart_id)
    if not cart:
        return error_response("Cart not found.", status_code=404, code="not_found")
    try:
        if remove:
            remove_line(cart, line_id)
        else:
            try:
                qty = int(body.get("qty", 1))
            except (TypeError, ValueError):
                qty = 1
            set_line_qty(cart, line_id, qty)  # set_line_qty clamps; qty <= 0 removes the line
    except CartError as exc:
        return error_response(str(exc), status_code=404, code="not_found")

    cart["updated_at"] = int(now)
    cart["retention_expires_at"] = int(now) + CART_RETENTION_SECONDS
    try:
        validate_cart(cart)
        carts_repo.put(cart)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_cart")
    return json_response({"cart": _public_cart(cart)})


def get_cart(event, carts_repo, cart_tokens_repo=None, now=0):
    """Fetch a cart by `cart_id`, or by a recovery `ct` token (token -> cart_id) so a recovery link
    rehydrates the exact cart on ANY device (the cart_id otherwise lives only in the abandoning browser)."""
    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip()
    cart_id = str(params.get("cart_id") or "").strip()
    token = str(params.get("ct") or "").strip()
    if tenant_id and token and not cart_id and cart_tokens_repo is not None:
        token_doc = cart_tokens_repo.get(tenant_id, token)
        if cart_token_valid(token_doc, now):
            cart_id = str(token_doc.get("cart_id") or "").strip()
    if not tenant_id or not cart_id:
        return error_response("tenant_id and cart_id (or ct) are required.", code="invalid_cart")
    cart = carts_repo.get(tenant_id, cart_id)
    if not cart:
        return error_response("Cart not found.", status_code=404, code="not_found")
    return json_response({"cart": _public_cart(cart)})


def unsubscribe(event, carts_repo, cart_tokens_repo, now):
    """One-click unsubscribe from a recovery email — resolves the token to its cart and opts it out. Returns a
    tiny HTML confirmation (the link is clicked in an email client). Always confirms, even on a stale token,
    so we never leak whether a token/cart exists."""
    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip()
    token = str(params.get("token") or "").strip()
    if tenant_id and token and cart_tokens_repo is not None:
        token_doc = cart_tokens_repo.get(tenant_id, token)
        cart_id = str((token_doc or {}).get("cart_id") or "").strip()
        if cart_id:
            try:
                cart = carts_repo.get(tenant_id, cart_id)
                if cart and not cart.get("email_opted_out"):
                    carts_repo.put(mark_opted_out(cart, now))
            except Exception:  # noqa: BLE001 - always confirm to the clicker
                pass
    body = ("<!doctype html><meta charset=utf-8><title>Unsubscribed</title>"
            "<div style=\"font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;text-align:center;color:#111;\">"
            "<h2>You're unsubscribed</h2><p>You won't receive cart reminders for this cart anymore.</p></div>")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Access-Control-Allow-Origin": "*"},
        "body": body,
    }


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
