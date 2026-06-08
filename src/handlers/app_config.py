from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params
from stripe_link.domain.documents import DocumentValidationError, validate_app_config
from stripe_link.repositories.documents import RepositoryError, app_config_repository


def handler(event, context, repository=None):
    repository = repository or app_config_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "GET":
        return get_app_config(event, repository)
    if method in {"POST", "PUT"}:
        return save_app_config(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def get_app_config(event, repository):
    config_key = str(path_params(event).get("config_key") or query_params(event).get("config_key") or "").strip()
    environment = str(query_params(event).get("environment") or "").strip()
    if not environment:
        environment = "global" if config_key == "app_config" else "dev"
    if not config_key:
        return error_response("config_key is required.", code="missing_config_key")
    config = repository.get(config_key, environment)
    if not config:
        return error_response("App config not found.", status_code=404, code="not_found")
    return json_response({"app_config": config})


def save_app_config(event, repository):
    try:
        document = parse_json_body(event)
        if not isinstance(document, dict):
            return error_response("App config document must be an object.", code="invalid_app_config")
        path_config_key = str(path_params(event).get("config_key") or "").strip()
        if path_config_key and document.get("config_key") != path_config_key:
            return error_response("Path config_key must match document config_key.", code="invalid_app_config")
        validate_app_config(document)
        saved = repository.put(document)
        return json_response({"app_config": saved}, status_code=201)
    except (ValueError, DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_app_config")
