from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.ledger import summarize
from stripe_link.repositories.documents import RepositoryError, ledger_repository


def handler(event, context, repository=None):
    repository = repository or ledger_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    params = query_params(event)
    order_id = str(params.get("order_id") or "").strip()
    try:
        if order_id:
            entries = repository.list_for_order(order_id)
        else:
            tenant_id = tenant_id_from_event(event)
            if not tenant_id:
                return error_response("tenant_id is required.", code="missing_tenant")
            entries = repository.list_for_tenant(tenant_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="ledger_read_failed")

    return json_response({"entries": entries, "count": len(entries), "summary": summarize(entries)})
