from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_stripe_keys_document
from stripe_link.repositories.documents import RepositoryError, stripe_keys_repository
from stripe_link.security import redact_sensitive_fields


def handler(event, context, repository=None):
    repository = repository or stripe_keys_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_keys(event, repository)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        keys = repository.get(tenant_id)
        if not keys:
            return error_response("Stripe keys not found.", status_code=404, code="not_found")
        return json_response({"stripe_keys": redact_sensitive_fields(keys)})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_keys(event, repository):
    try:
        document = parse_json_body(event)
        validate_stripe_keys_document(document)
        saved = repository.put(document)
        return json_response({"stripe_keys": redact_sensitive_fields(saved)}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_stripe_keys")
