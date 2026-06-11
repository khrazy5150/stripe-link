from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_profile
from stripe_link.repositories.documents import (
    RepositoryError,
    tenant_profiles_registration_repositories,
    tenant_profiles_repository,
)


def handler(event, context, repository=None, registration_repositories=None):
    provided_repository = repository is not None
    repository = repository or tenant_profiles_repository()
    if registration_repositories is None:
        registration_repositories = (
            [repository]
            if provided_repository
            else tenant_profiles_registration_repositories()
        )
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return register_tenant(event, registration_repositories)
    if method == "GET":
        tenant_id = path_params(event).get("tenant_id") or tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        profile = repository.get(tenant_id, tenant_id)
        if not profile:
            return error_response("Tenant not found.", status_code=404, code="not_found")
        return json_response({"tenant": profile})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def register_tenant(event, repositories):
    try:
        document = parse_json_body(event)
        document.pop("password", None)
        document["tier_id"] = str(document.get("tier_id") or "basic")
        document["billing_status"] = str(document.get("billing_status") or "trial")
        validate_tenant_profile(document)
        saved = None
        for repository in repositories:
            saved = repository.put(document)
        return json_response({"tenant": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_tenant")
