import os
from urllib.parse import urlencode

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.repositories.documents import RepositoryError, stripe_keys_repository
from stripe_link.security import redact_sensitive_fields


def start_handler(event, context):
    tenant_id = tenant_id_from_event(event)
    mode = (event.get("queryStringParameters") or {}).get("mode", "test")
    client_id = os.environ.get("STRIPE_CLIENT_ID", "")
    redirect_uri = os.environ.get("STRIPE_CONNECT_REDIRECT_URI", "")
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not client_id or not redirect_uri:
        return error_response("Stripe Connect is not configured for this environment.", status_code=503, code="connect_not_configured")
    state = f"{tenant_id}:{mode}"
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return json_response({
        "connect_url": f"https://connect.stripe.com/oauth/authorize?{params}",
        "state": state,
    })


def status_handler(event, context, repository=None):
    repository = repository or stripe_keys_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        keys = repository.get(tenant_id)
        return json_response({"stripe_connect": redact_sensitive_fields(keys) if keys else {"connect_status": "not_connected"}})
    if method in {"POST", "PUT"}:
        try:
            document = parse_json_body(event)
            if not document.get("tenant_id"):
                return error_response("tenant_id is required.", code="missing_tenant")
            saved = repository.put({
                "schema_version": "2026-05-29",
                "document_type": "stripe_keys",
                "mode": document.get("mode", "test"),
                "publishable_key": document.get("publishable_key", ""),
                **document,
            })
            return json_response({"stripe_connect": redact_sensitive_fields(saved)}, status_code=201)
        except (ValueError, RepositoryError) as exc:
            return error_response(str(exc), code="invalid_connect_status")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
