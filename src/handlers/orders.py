"""Orders, and what stands between each one and a shipping label.

plans/ORDER_FULFILMENT.md. The fulfilment state is computed HERE, on the server, and travels with every
order -- never recomputed by the screen. One implementation means the table and the buy endpoint cannot
disagree about whether an order is eligible, which is the kind of disagreement a tenant discovers by
pressing a button and being told no.
"""
import os
import time
from datetime import datetime
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
from stripe_link.domain.address_validation import (
    needs_check,
    record_validation,
    suggested_correction,
)
from stripe_link.domain.carriers import carrier_options, service_has_tracking, tracking_url
from stripe_link.domain.shipping_promise import revised_sentence
from stripe_link.domain.fulfilment import delivery_status, order_fulfilment_state, product_index
from stripe_link.domain.handover import handover_groups, orders_csv
from stripe_link.domain.order_reference import matches_reference, short_refs
from stripe_link.domain.shipment_notice import notify_buyer
from stripe_link.domain.shipping_quotes import order_variance
from stripe_link.domain.shipping_providers import ProviderError, provider_for
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.domain.shipping import ShipmentError, build_manual_shipment, label_readiness
from stripe_link.repositories.documents import (
    RepositoryError,
    orders_repository,
    products_repository,
    shipments_repository,
    shipping_config_repository,
    user_profiles_repository,
)


# The same encryption context the shipping handler uses, so one key decrypts under both.
SECRET_MODE = "shipping"
SECRET_FIELD = "provider.api_key_ref"


def handler(event, context, repository=None, products_repo=None, shipments_repo=None,
            shipping_config_repo=None, user_profiles_repo=None, mailer_send=None,
            secret_cipher=None, now_fn: Callable[[], int] = lambda: int(time.time())):
    mode = resolve_stripe_mode(event)
    repository = repository or orders_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    order_id = path_params(event).get("order_id")
    if method == "POST" and _is_validate_path(event):
        return validate_addresses(event, repository, mode, shipping_config_repo=shipping_config_repo,
                                  secret_cipher=secret_cipher, now_fn=now_fn)
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
    if str(query_params(event).get("format") or "").lower() == "csv":
        return export_orders(event, repository, mode, products_repo=products_repo,
                             shipments_repo=shipments_repo, shipping_config_repo=shipping_config_repo)
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
    everything = repository.list_for_tenant(tenant_id)
    _stamp_references(everything)
    orders = filter_orders(everything, params)
    orders.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)

    context = fulfilment_context(tenant_id, mode, products_repo, shipments_repo, shipping_config_repo)
    for order in orders:
        order["fulfilment"] = order_fulfilment_state(
            order,
            products_by_id=context["products_by_id"],
            index=context["index"],
            shipment=context["shipments"].get(str(order.get("order_id") or "")),
        )
        # The Status column is the DELIVERY story, derived once here so the table, the drawer and the CSV
        # cannot each tell a different one.
        order["delivery"] = delivery_status(order)
        # What the buyer was charged for postage against what the label actually cost
        # (plans/LIVE_SHIPPING_RATES.md phase 5). Derived from the two halves already loaded rather than
        # read per order: the durable record is `shipping_actual`, but a list of forty orders must not
        # become forty extra lookups to render a badge most of them never show. Absent when there is
        # nothing to compare, which is most orders.
        variance = order_variance(order, context["shipments"].get(str(order.get("order_id") or "")))
        if variance:
            order["shipping_variance"] = variance
        suggestion = suggested_correction(order)
        if suggestion:
            order["address_suggestion"] = suggestion
    return json_response({
        "orders": orders,
        "count": len(orders),
        # The TENANT gate, once, for a banner -- not repeated on forty rows.
        "shipping_readiness": context["readiness"],
        "shipping_configured": context["configured"],
        "carriers": carrier_options(),
        # What a carrier would actually accept as one handover: ONE carrier, ONE ship date. Grouped on the
        # server so the toolbar cannot offer a batch the carrier will reject.
        "handover_groups": [
            {k: v for k, v in group.items() if k != "shipments"}
            for group in handover_groups(list(context["shipments"].values()))
        ],
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


def _revised_arrival(order, shipment, tenant_id, mode, *, quotes_repo=None):
    """The recomputed arrival, or `{}`. Never raises: a parcel that shipped must still record as shipped.

    The ship date is the one the tenant gave, read in UTC rather than their timezone — unlike the original
    estimate there is no cutoff to decide, so the only thing the date is used for is counting business days
    forward, and a few hours either side of midnight cannot change which weekday that lands on.
    """
    try:
        from datetime import timezone as _tz

        from stripe_link.domain.shipping_promise import revised_promise
        from stripe_link.repositories.documents import shipping_quotes_repository

        quote = {}
        quote_id = str(((order.get("shipping_quote") or {}) if isinstance(order, dict) else {}).get("quote_id") or "")
        if quote_id:
            repo = quotes_repo or (shipping_quotes_repository(mode=mode)
                                   if os.environ.get("CARTS_TABLE") else None)
            if repo is not None:
                quote = repo.get(tenant_id, quote_id) or {}
        shipped_at = int(shipment.get("shipped_at") or 0)
        if not shipped_at:
            return {}
        shipped_on = datetime.fromtimestamp(shipped_at, _tz.utc).date()
        return revised_promise(order, quote, shipment, shipped_on=shipped_on)
    except Exception as exc:  # noqa: BLE001
        print(f"[delivery] revision not computed for {order.get('order_id')}: {type(exc).__name__}: {exc}")
        return {}


def mark_shipped(event, repository, order_id, mode, *, shipments_repo=None, user_profiles_repo=None,
                 mailer_send=None, quotes_repo=None, now_fn=lambda: int(time.time())):
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

    # WHAT THE BUYER WAS TOLD, CORRECTED. The date on their thank-you page was computed from a guess
    # about when this would ship; now it has, that guess is a fact (plans/THANK_YOU_PAGE.md P4). Stored on
    # the SHIPMENT, never over the order's own `delivery_estimate`: support answering "but you said the
    # 12th" needs both the promise and the correction, and a field that quietly becomes the new truth
    # loses the thing that was actually promised.
    revised = _revised_arrival(order, shipment, tenant_id, mode, quotes_repo=quotes_repo)
    if revised:
        shipment["delivery_revision"] = revised
    note = str(body.get("note") or "").strip()[:400]
    if note:
        shipment["tenant_note"] = note

    notified = notify_buyer(
        order, shipment, tenant_id,
        has_tracking=service_has_tracking(carrier, service),
        user_profiles_repo=user_profiles_repo, mailer_send=mailer_send,
        arrival_line=revised_sentence(revised), tenant_note=note)
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


def filter_orders(orders, params):
    """Filter by status, and by a search box that matches a person OR an order reference.

    The reference has to be searchable or removing the full id from the screen would leave a tenant
    holding a number they cannot look up.
    """
    status = str(params.get("status") or "").strip()
    needle = str(params.get("customer") or "").strip().lower()
    filtered = []
    for order in orders:
        order_customer = order.get("customer") or {}
        haystack = f"{order_customer.get('name', '')} {order_customer.get('email', '')}".lower()
        order_status = order.get("payment_status") or order.get("status")
        if status and order_status != status:
            continue
        if needle and needle not in haystack and not matches_reference(order, needle):
            continue
        filtered.append(order)
    return filtered


def export_orders(event, repository, mode, *, products_repo=None, shipments_repo=None,
                  shipping_config_repo=None):
    """The same list the screen shows, as CSV.

    Built from the same joined data rather than from what the browser happens to be holding, so an export
    says the same thing as the screen -- including the fulfilment columns, which is most of why a tenant
    exports at all.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    everything = repository.list_for_tenant(tenant_id)
    _stamp_references(everything)
    orders = filter_orders(everything, params)
    orders.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    context = fulfilment_context(tenant_id, mode, products_repo, shipments_repo, shipping_config_repo)
    for order in orders:
        order["fulfilment"] = order_fulfilment_state(
            order,
            products_by_id=context["products_by_id"],
            index=context["index"],
            shipment=context["shipments"].get(str(order.get("order_id") or "")),
        )
        order["delivery"] = delivery_status(order)
    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="orders-{stamp}.csv"',
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,PATCH,DELETE",
        },
        "body": orders_csv(orders),
    }


def _stamp_references(orders) -> None:
    """Give every order its short reference, computed across the WHOLE set.

    Across the whole set rather than per order, because uniqueness is a property of the set: two orders
    that would share a prefix both get a longer one. Done before filtering, so a search result shows the
    same reference the full list did.
    """
    mapping = short_refs([str(o.get("order_id") or "") for o in orders])
    for order in orders:
        reference = mapping.get(str(order.get("order_id") or ""))
        if reference:
            order["short_ref"] = reference


def _is_validate_path(event) -> bool:
    path = str((event or {}).get("resource") or (event or {}).get("path") or "")
    return path.rstrip("/").endswith("/validate-addresses")


# One request, a bounded batch. Each address is a provider call, so this is the number the screen can ask
# for without turning a page load into a minute of waiting.
VALIDATION_BATCH = 20


def validate_addresses(event, repository, mode, *, shipping_config_repo=None, secret_cipher=None,
                       now_fn=lambda: int(time.time())):
    """Ask the carrier whether these addresses are deliverable, and write the answers down.

    Batched and bounded on purpose. Validating on every render would be one network call per row per
    load; validating one row per request would be twenty requests for a page of twenty. This is one
    request that checks the orders which have no current verdict, and stops.

    An order already known undeliverable is NOT re-checked -- the tenant has to fix the address, and
    asking the carrier the same question again costs money and changes nothing.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    config = (shipping_config_repo or shipping_config_repository()).get(tenant_id) or {}
    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    if not name:
        return error_response("Set up a shipping provider before checking addresses.",
                              code="no_provider")

    orders = [o for o in repository.list_for_tenant(tenant_id) if needs_check(o)][:VALIDATION_BATCH]
    if not orders:
        return json_response({"checked": 0, "orders": []})

    secret_ref = str(provider_config.get("api_key_ref") or "")
    try:
        cipher = secret_cipher if secret_cipher is not None else KmsSecretCipher()
        api_key = cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        provider = provider_for(name, api_key)
    except ProviderError as exc:
        return error_response(str(exc), status_code=502, code="provider_error")

    now = int(now_fn())
    checked = []
    for order in orders:
        address = order.get("shipping_address") or {}
        try:
            result = provider.validate_address(address)
        except ProviderError as exc:
            # UNKNOWN, never undeliverable: a provider outage must not turn a tenant's whole list
            # unshippable.
            result = {"valid": None, "messages": [str(exc)[:200]]}
        except Exception:  # noqa: BLE001 - one bad address must not stop the batch
            result = {"valid": None, "messages": []}
        order["address_validation"] = record_validation(address, result, now=now)
        try:
            repository.put(order)
        except RepositoryError:
            pass
        checked.append({"order_id": order.get("order_id"),
                        "address_validation": order["address_validation"],
                        "suggestion": suggested_correction(order)})

    # A count per verdict, so the screen can say what happened rather than just vanishing.
    tally: dict[str, int] = {}
    for entry in checked:
        key = str(entry["address_validation"].get("status") or "unknown")
        tally[key] = tally.get(key, 0) + 1
    return json_response({
        "checked": len(checked),
        "summary": tally,
        "suggestions": sum(1 for entry in checked if entry["suggestion"]),
        "orders": checked,
    })
