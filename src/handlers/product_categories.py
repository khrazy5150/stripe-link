"""GET /product-categories?q=&product_type= — autocomplete over the shared category taxonomy.

Returns curated categories + promoted contributed ones (used by enough distinct tenants), plus the
requesting tenant's own not-yet-promoted ones, scoped to the product type. See
plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md.
"""

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.categories import search_suggestions
from stripe_link.repositories.documents import RepositoryError, product_categories_repository


def handler(event, context, repository=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    params = query_params(event)
    query = str(params.get("q") or "")
    product_type = str(params.get("product_type") or "")
    tenant_id = tenant_id_from_event(event) or str(params.get("tenant_id") or "")

    repository = repository or product_categories_repository()
    try:
        contributed = repository.list_all()
    except RepositoryError as exc:
        return error_response(str(exc), code="categories_error")

    suggestions = search_suggestions(
        query, contributed, product_type=product_type, tenant_id=tenant_id,
    )
    return json_response({"categories": suggestions})
