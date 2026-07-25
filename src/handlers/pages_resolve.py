import os

from stripe_link.common import error_response, json_response, query_params
from stripe_link.repositories.documents import RepositoryError, routes_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import public_url


# The URL segment the visitor uses maps to the price context the artifact was published under.
_VIEW_CONTEXT = {"": "", "sale": "sale", "flash-sale": "flash_sale"}


def handler(event, context, *, repository=None, pages_domain=None):
    """Public endpoint: resolve a page short_code (+ optional /sale //flash-sale view) to the origin_url of
    its published artifact, for the test.juniorbay.com Cloudflare Worker to reverse-proxy verbatim
    (plans/SALES_FUNNELS.md Phase B). Read-only, unauthenticated -- reads only the routes table, so it never
    touches Offer/Product/Stripe state. The visitor's URL stays test.juniorbay.com/published/{short_code}.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    repository = repository or routes_repository()
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")

    params = query_params(event)
    code = str(params.get("code") or "").strip()
    view = str(params.get("view") or "").strip().lower()
    if not code:
        return error_response("code is required.", code="missing_code")
    if view not in _VIEW_CONTEXT:
        return error_response("Unknown view.", status_code=404, code="unknown_view")

    try:
        route = repository.find_by_id(code)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    if not route or route.get("target_type") != "page":
        return error_response("Page not found.", status_code=404, code="not_found")

    page_id = str(route.get("target_page_id") or "")
    tenant_id = str(route.get("tenant_id") or "")
    if not page_id or not tenant_id:
        return error_response("Page not found.", status_code=404, code="not_found")

    key = artifact_paths(tenant_id, page_id, context=_VIEW_CONTEXT[view])["published"]
    origin = public_url(pages_domain, key)
    if not origin:
        return error_response("Pages origin is not configured.", status_code=404, code="no_origin")
    return json_response({"route": {"type": "origin_url", "origin_url": origin}})
