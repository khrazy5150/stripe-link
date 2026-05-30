from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_invoice
from stripe_link.repositories.documents import RepositoryError, invoices_repository


def handler(event, context, repository=None):
    repository = repository or invoices_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_invoice(event, repository)
    if method == "GET":
        invoice_id = path_params(event).get("invoice_id")
        if invoice_id:
            return get_invoice(event, repository, invoice_id)
        return list_invoices(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_invoice(event, repository):
    try:
        document = parse_json_body(event)
        validate_invoice(document)
        saved = repository.put(document)
        return json_response({"invoice": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_invoice")


def get_invoice(event, repository, invoice_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    invoice = repository.get(tenant_id, invoice_id)
    if not invoice:
        return error_response("Invoice not found.", status_code=404, code="not_found")
    return json_response({"invoice": invoice})


def list_invoices(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    invoices = filter_invoices(repository.list_for_tenant(tenant_id), params)
    invoices.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return json_response({"invoices": invoices, "count": len(invoices)})


def filter_invoices(invoices, params):
    status = str(params.get("status") or "").strip()
    customer = str(params.get("customer") or "").strip().lower()
    filtered = []
    for invoice in invoices:
        invoice_customer = invoice.get("customer") or {}
        haystack = f"{invoice_customer.get('name', '')} {invoice_customer.get('email', '')}".lower()
        if status and invoice.get("status") != status:
            continue
        if customer and customer not in haystack:
            continue
        filtered.append(invoice)
    return filtered
