import os
import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_route
from stripe_link.ids import generate_short_url_code
from stripe_link.repositories.documents import RepositoryError, routes_repository


def _short_url_host():
    return os.environ.get("SHORT_URL_HOST", "go.jbay.uk")


def with_short_url(route):
    return {**route, "short_url": f"https://{_short_url_host()}/{route.get('short_code', '')}"}


def handler(event, context, *, repository=None, now_fn=lambda: int(time.time()), code_fn=generate_short_url_code):
    repository = repository or routes_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    short_code = path_params(event).get("short_code")
    try:
        if method == "GET" and not short_code:
            return list_routes(event, repository)
        if method == "POST" and not short_code:
            return create_route(event, repository, now_fn, code_fn)
        if method == "DELETE" and short_code:
            return delete_route(event, repository, short_code)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def list_routes(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    routes = [with_short_url(route) for route in repository.list_for_tenant(tenant_id)]
    routes.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return json_response({"routes": routes, "count": len(routes)})


def create_route(event, repository, now_fn, code_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    body = parse_json_body(event)
    target_type = str(body.get("target_type") or "").strip()
    now = int(now_fn())
    document = {
        "schema_version": "2026-05-29",
        "document_type": "route",
        "tenant_id": tenant_id,
        "target_type": target_type,
        "created_at": now,
        "updated_at": now,
    }
    label = str(body.get("label") or "").strip()
    if label:
        document["label"] = label
    if target_type == "page":
        document["target_page_id"] = str(body.get("target_page_id") or "").strip()
    elif target_type == "url":
        document["target_url"] = str(body.get("target_url") or "").strip()
    elif target_type == "experiment":
        document["target_experiment_id"] = str(body.get("target_experiment_id") or "").strip()

    short_code = allocate_short_code(repository, code_fn)
    if not short_code:
        return error_response("Could not allocate a unique short code.", status_code=500, code="code_generation_failed")
    document["short_code"] = short_code

    try:
        validate_route(document)
        saved = repository.put(document)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_route")
    return json_response({"route": with_short_url(saved)}, status_code=201)


def allocate_short_code(repository, code_fn):
    for _ in range(5):
        candidate = str(code_fn() or "").strip()
        if candidate and not repository.find_by_id(candidate):
            return candidate
    return ""


def delete_route(event, repository, short_code):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, short_code)
    if not deleted:
        return error_response("Short link not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, "short_code": short_code})
