from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import (
    DocumentValidationError,
    order_product_document,
    product_stripe_sync_gate,
    validate_product_document,
)
from stripe_link.repositories.documents import RepositoryError, products_repository


def handler(event, context, repository=None):
    repository = repository or products_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    product_id = path_params(event).get("product_id")
    resource = (event or {}).get("resource") or ""
    if method == "PATCH" and product_id and resource.endswith("/status"):
        return update_product_status(event, repository, product_id)
    if method == "POST":
        return create_product(event, repository)
    if method == "GET":
        if product_id:
            return get_product(event, repository, product_id)
        return list_products(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_product(event, repository):
    try:
        document = parse_json_body(event)
        validate_product_document(document)
        document = order_product_document(document)
        saved = repository.put(document)
        return json_response(
            {
                "product": order_product_document(saved),
                "stripe_sync": product_stripe_sync_gate(saved),
            },
            status_code=201,
        )
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_product")


def get_product(event, repository, product_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    product = repository.get(tenant_id, product_id)
    if not product:
        return error_response("Product not found.", status_code=404, code="not_found")
    return json_response({"product": order_product_document(product)})


def list_products(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    return json_response({"products": [order_product_document(product) for product in repository.list_for_tenant(tenant_id)]})


def update_product_status(event, repository, product_id: str):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_product_status")
    status = str(body.get("status") or "").strip()
    if status not in {"active", "archived"}:
        return error_response("Product status must be one of: active, archived.", code="invalid_product_status")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    product = repository.get(tenant_id, product_id)
    if not product:
        return error_response("Product not found.", status_code=404, code="not_found")
    product["status"] = status
    product.pop("active", None)
    if body.get("updated_at") is not None:
        product["updated_at"] = body.get("updated_at")
    try:
        saved = repository.put(product)
        return json_response({"product": order_product_document(saved)})
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_product_status")
