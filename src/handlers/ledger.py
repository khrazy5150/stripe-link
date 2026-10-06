from stripe_link.common import (
    error_response, json_response, query_params, resolve_stripe_mode, tenant_id_from_event,
)
from stripe_link.domain.ledger import summarize
from stripe_link.repositories.documents import RepositoryError, ledger_repository


def handler(event, context, repository=None):
    # Mode-scoped: one prod endpoint serves both test and live (STRIPE_MODE_DECOUPLING P3), so a summary
    # that did not filter added sandbox money to real money.
    repository = repository or ledger_repository(mode=resolve_stripe_mode(event))
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

    # A PERIOD, filtered here rather than in the browser. Reporting asks "this month against last", and
    # shipping a tenant's whole ledger to the page to slice it there stops working on the first tenant
    # with real volume (plans/REPORTING.md §4). Both bounds optional and inclusive; `occurred_at` is on
    # every entry.
    window = _window(params)
    if window:
        since, until = window
        entries = [entry for entry in entries
                   if (since is None or int(entry.get("occurred_at") or 0) >= since)
                   and (until is None or int(entry.get("occurred_at") or 0) <= until)]

    summary = summarize(entries)
    # HOW MUCH OF THE MARGIN IS KNOWN. `shipping_cost` only exists once a label is bought, so a period
    # where most orders have not shipped reports a margin computed from the few that have -- 5 of 71 read
    # as a ~96% margin on postage, which is the one figure in this summary a tenant could act wrongly on
    # (plans/REPORTING.md §2b). `summarize` already refuses to invent a margin when NO cost exists; the
    # partial case is this. Stated beside the number rather than hidden, and never silently corrected.
    sales = [entry for entry in entries if entry.get("entry_type") == "sale"]
    shipped = {str(entry.get("order_id") or "") for entry in entries
               if entry.get("entry_type") == "shipping_cost" and entry.get("order_id")}
    summary["shipping_cost_coverage"] = {"shipped": len(shipped), "sales": len(sales)}

    return json_response({"entries": entries, "count": len(entries), "summary": summary})


def _window(params):
    """`(since, until)` epoch bounds from `from`/`to`, or None when neither was asked for."""
    def bound(key):
        raw = str(params.get(key) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    since, until = bound("from"), bound("to")
    return (since, until) if (since is not None or until is not None) else None
