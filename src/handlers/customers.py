from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_customer
from stripe_link.repositories.documents import RepositoryError, customers_repository


def handler(event, context, repository=None):
    repository = repository or customers_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_customer(event, repository)
    if method == "GET":
        customer_id = path_params(event).get("customer_id")
        if customer_id:
            return get_customer(event, repository, customer_id)
        return list_customers(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_customer(event, repository):
    try:
        document = parse_json_body(event)
        validate_customer(document)
        saved = repository.put(document)
        return json_response({"customer": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_customer")


def get_customer(event, repository, customer_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    customer = repository.get(tenant_id, customer_id)
    if not customer:
        return error_response("Customer not found.", status_code=404, code="not_found")
    return json_response({"customer": customer})


def list_customers(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    customers = filter_customers(repository.list_for_tenant(tenant_id), params)
    customers.sort(key=lambda item: ((item.get("contact") or {}).get("name") or "").lower())
    return json_response({"customers": customers, "count": len(customers)})


def filter_customers(customers, params):
    customer_query = str(params.get("customer") or "").strip().lower()
    product_query = str(params.get("product") or "").strip().lower()
    if not customer_query and not product_query:
        return customers

    filtered = []
    for customer in customers:
        contact = customer.get("contact") or {}
        customer_haystack = f"{contact.get('name', '')} {contact.get('email', '')} {contact.get('phone', '')}".lower()
        products = " ".join(
            f"{item.get('product_id', '')} {item.get('product_name', '')}"
            for item in customer.get("product_affinity", [])
            if isinstance(item, dict)
        ).lower()
        if customer_query and customer_query not in customer_haystack:
            continue
        if product_query and product_query not in products:
            continue
        filtered.append(customer)
    return filtered
