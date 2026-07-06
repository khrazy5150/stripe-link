from stripe_link.common import error_response, json_response, path_params, query_params, tenant_id_from_event
from stripe_link.repositories.documents import orders_repository


def handler(event, context, repository=None):
    repository = repository or orders_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    order_id = path_params(event).get("order_id")
    if order_id:
        return get_order(event, repository, order_id)
    return list_orders(event, repository)


def get_order(event, repository, order_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    order = repository.get(tenant_id, order_id)
    if not order:
        return error_response("Order not found.", status_code=404, code="not_found")
    return json_response({"order": order})


def list_orders(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    orders = filter_orders(repository.list_for_tenant(tenant_id), params)
    orders.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return json_response({"orders": orders, "count": len(orders)})


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
