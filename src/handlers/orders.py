"""Orders, and what stands between each one and a shipping label.

plans/ORDER_FULFILMENT.md. The fulfilment state is computed HERE, on the server, and travels with every
order -- never recomputed by the screen. One implementation means the table and the buy endpoint cannot
disagree about whether an order is eligible, which is the kind of disagreement a tenant discovers by
pressing a button and being told no.
"""
import time
from typing import Any, Callable

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    path_params,
    query_params,
    resolve_stripe_mode,
    tenant_id_from_event,
)
from stripe_link.domain.carriers import carrier_options, service_has_tracking, tracking_url
from stripe_link.domain.fulfilment import order_fulfilment_state, product_index
from stripe_link.domain.receipts import shipment_tracking_content
from stripe_link.domain.shipping import ShipmentError, build_manual_shipment, label_readiness
from stripe_link.mailer import send_email, tenant_email_identity
from stripe_link.repositories.documents import (
    RepositoryError,
    orders_repository,
    products_repository,
    shipments_repository,
    shipping_config_repository,
    user_profiles_repository,
)


def handler(event, context, repository=None, products_repo=None, shipments_repo=None,
            shipping_config_repo=None, user_profiles_repo=None, mailer_send=None,
            now_fn: Callable[[], int] = lambda: int(time.time())):
    mode = resolve_stripe_mode(event)
    repository = repository or orders_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    order_id = path_params(event).get("order_id")
    if method == "POST":
        if not order_id:
            return error_response("An order id is required.", code="missing_order")
        return mark_shipped(
            event, repository, order_id, mode,
            shipments_repo=shipments_repo, user_profiles_repo=user_profiles_repo,
            mailer_send=mailer_send, now_fn=now_fn)
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    if order_id:
        return get_order(event, repository, order_id)
    return list_orders(event, repository, mode,
                       products_repo=products_repo, shipments_repo=shipments_repo,
                       shipping_config_repo=shipping_config_repo)


def get_order(event, repository, order_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    order = repository.get(tenant_id, order_id)
    if not order:
        return error_response("Order not found.", status_code=404, code="not_found")
    return json_response({"order": order})


def list_orders(event, repository, mode, *, products_repo=None, shipments_repo=None, shipping_config_repo=None):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    orders = filter_orders(repository.list_for_tenant(tenant_id), params)
    orders.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)

    context = fulfilment_context(tenant_id, mode, products_repo, shipments_repo, shipping_config_repo)
    for order in orders:
        order["fulfilment"] = order_fulfilment_state(
            order,
            products_by_id=context["products_by_id"],
            index=context["index"],
            shipment=context["shipments"].get(str(order.get("order_id") or "")),
        )
    return json_response({
        "orders": orders,
        "count": len(orders),
        # The TENANT gate, once, for a banner -- not repeated on forty rows.
        "shipping_readiness": context["readiness"],
        "shipping_configured": context["configured"],
        "carriers": carrier_options(),
    })


def fulfilment_context(tenant_id, mode, products_repo=None, shipments_repo=None, shipping_config_repo=None):
    """Everything the gates need, fetched once per request.

    Best-effort throughout: a tenant who sells downloads has no shipping config and no measured products,
    and their Orders screen must still load. A missing table makes rows un-shippable, never un-listable.
    """
    products: list[dict[str, Any]] = []
    shipments: dict[str, dict[str, Any]] = {}
    config: dict[str, Any] = {}
    try:
        repo = products_repo or products_repository(mode=mode)
        products = repo.list_for_tenant(tenant_id) or []
    except Exception:  # noqa: BLE001 - see docstring
        products = []
    try:
        repo = shipments_repo or shipments_repository(mode=mode)
        for shipment in repo.list_for_tenant(tenant_id) or []:
            key = str(shipment.get("order_id") or "")
            # Newest wins: a re-shipped order has more than one, and the latest is the true state.
            if key and int(shipment.get("updated_at") or 0) >= int((shipments.get(key) or {}).get("updated_at") or 0):
                shipments[key] = shipment
    except Exception:  # noqa: BLE001
        shipments = {}
    try:
        repo = shipping_config_repo or shipping_config_repository()
        config = repo.get(tenant_id) or {}
    except Exception:  # noqa: BLE001
        config = {}

    return {
        "products_by_id": {str(p.get("product_id") or ""): p for p in products if p.get("product_id")},
        "index": product_index(products),
        "shipments": shipments,
        "readiness": label_readiness(config) if config else [],
        "configured": bool(config),
    }


def mark_shipped(event, repository, order_id, mode, *, shipments_repo=None, user_profiles_repo=None,
                 mailer_send=None, now_fn=lambda: int(time.time())):
    """The manual path: the tenant posted it themselves and is telling the buyer so.

    The tracking number is OPTIONAL -- USPS First-Class Mail carries none. What is NOT optional is honesty
    about it, which `shipment_tracking_content` handles.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    order = repository.get(tenant_id, order_id)
    if not order:
        return error_response("Order not found.", status_code=404, code="not_found")

    body = parse_json_body(event)
    carrier = str(body.get("carrier") or "").strip()
    service = str(body.get("service") or "").strip()
    number = str(body.get("tracking_number") or "").strip()
    pasted_url = str(body.get("tracking_url") or "").strip()
    if number and not carrier:
        return error_response("Choose a carrier so the tracking number becomes a link.",
                              code="carrier_required")

    now = int(now_fn())
    link = tracking_url(carrier, number, custom_url=pasted_url)
    try:
        shipment = build_manual_shipment(
            order=order, carrier=carrier, service=service, tracking_number=number,
            tracking_url=link, shipped_at=int(body.get("shipped_at") or now), now=now)
    except ShipmentError as exc:
        return error_response(str(exc), code="invalid_shipment")

    notified = notify_buyer(
        order, shipment, tenant_id,
        has_tracking=service_has_tracking(carrier, service),
        user_profiles_repo=user_profiles_repo, mailer_send=mailer_send)
    if notified.get("sent"):
        shipment["notified_at"] = now
    elif notified.get("error"):
        shipment["notify_error"] = str(notified["error"])[:300]

    try:
        repo = shipments_repo or shipments_repository(mode=mode)
        saved = repo.put(shipment)
    except RepositoryError as exc:
        return error_response(str(exc), code="shipment_not_saved")

    return json_response({"shipment": saved, "notification": notified}, status_code=201)


def notify_buyer(order, shipment, tenant_id, *, has_tracking=None, user_profiles_repo=None, mailer_send=None):
    """Tell the buyer. Reports the OUTCOME rather than swallowing it.

    plans/SHIPPING_PROVIDERS.md §P3 says a tracking email must never break what triggered it, which is
    right when a label is already bought and paid for. On the MANUAL path nothing irreversible has
    happened and the tenant pressed the button IN ORDER TO notify the buyer -- swallowing a failure there
    means the tenant believes their customer was told and the customer hears nothing. So the parcel is
    still recorded as shipped, and the failure is handed back so the screen can offer Resend.
    """
    email = str((order.get("customer") or {}).get("email") or "").strip()
    if not email:
        return {"sent": False, "reason": "no_customer_email"}
    try:
        identity = tenant_email_identity(tenant_id, user_profiles_repo)
        lines = order.get("line_items") or []
        items = str((lines[0] or {}).get("name") or "") if len(lines) == 1 else ""
        if not items:
            items = str((order.get("product") or {}).get("name") or "")
        content = shipment_tracking_content(
            business_name=identity.get("business_name", ""),
            order_id=str(order.get("order_id") or ""),
            items=items,
            carrier_label=str(shipment.get("carrier") or ""),
            service_label=str(shipment.get("service") or ""),
            tracking_number=str(shipment.get("tracking_number") or ""),
            tracking_url=str(shipment.get("tracking_url") or ""),
            has_tracking=has_tracking,
            support_email=identity.get("reply_to", ""),
        )
        (mailer_send or send_email)(
            to_address=email,
            subject=content["subject"],
            html_body=content["html"],
            text_body=content["text"],
            tenant_id=tenant_id,
        )
        return {"sent": True, "to": email}
    except Exception as exc:  # noqa: BLE001 - reported, never raised: the parcel DID ship
        return {"sent": False, "error": str(exc)}


def filter_orders(orders, params):
    status = str(params.get("status") or "").strip()
    customer = str(params.get("customer") or "").strip().lower()
    filtered = []
    for order in orders:
        order_customer = order.get("customer") or {}
        haystack = f"{order_customer.get('name', '')} {order_customer.get('email', '')}".lower()
        order_status = order.get("payment_status") or order.get("status")
        if status and order_status != status:
            continue
        if customer and customer not in haystack:
            continue
        filtered.append(order)
    return filtered
