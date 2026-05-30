from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_user_preferences
from stripe_link.repositories.documents import RepositoryError, user_preferences_repository


def handler(event, context, repository=None):
    repository = repository or user_preferences_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_preferences(event, repository)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        user_id = str(query_params(event).get("user_id") or "").strip()
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        if not user_id:
            return error_response("user_id is required.", code="missing_user")
        preferences = repository.get(tenant_id, user_id)
        if not preferences:
            return error_response("Preferences not found.", status_code=404, code="not_found")
        return json_response({"preferences": preferences})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_preferences(event, repository):
    try:
        document = parse_json_body(event)
        validate_user_preferences(document)
        saved = repository.put(document)
        return json_response({"preferences": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_preferences")
