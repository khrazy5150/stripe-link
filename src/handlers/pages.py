from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.repositories.documents import RepositoryError, pages_repository


def handler(event, context, repository=None):
    repository = repository or pages_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return create_page(event, repository)
    if method == "GET":
        page_id = path_params(event).get("page_id")
        if page_id:
            return get_page(event, repository, page_id)
        return list_pages(event, repository)
    if method == "DELETE":
        page_id = path_params(event).get("page_id")
        if not page_id:
            return error_response("page_id is required.", code="missing_page")
        return delete_page(event, repository, page_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_page(event, repository):
    try:
        document = parse_json_body(event)
        validate_page_document(document)
        saved = repository.put(document)
        return json_response({"page": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_page")


def get_page(event, repository, page_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page = repository.get(tenant_id, page_id)
    if not page:
        return error_response("Page not found.", status_code=404, code="not_found")
    return json_response({"page": page})


def list_pages(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    return json_response({"pages": repository.list_for_tenant(tenant_id)})


def delete_page(event, repository, page_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page = repository.get(tenant_id, page_id)
    if not page:
        return error_response("Page not found.", status_code=404, code="not_found")
    if page.get("status") == "published":
        return error_response(
            "Published pages must be archived before deletion.",
            status_code=409,
            code="published_page_requires_archive",
        )
    deleted = repository.delete(tenant_id, page_id)
    return json_response({"deleted": True, "page": deleted})
