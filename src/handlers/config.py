from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_config
from stripe_link.repositories.documents import RepositoryError, platform_config_repository


def handler(event, context, repository=None):
    repository = repository or platform_config_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_config(event, repository)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        config = repository.get(tenant_id)
        if not config:
            return error_response("Tenant config not found.", status_code=404, code="not_found")
        return json_response({"config": config})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_config(event, repository):
    try:
        document = parse_json_body(event)
        validate_tenant_config(document)
        saved = repository.put(document)
        return json_response({"config": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_config")
