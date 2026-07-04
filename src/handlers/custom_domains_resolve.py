import os

from stripe_link.common import error_response, header_value, json_response, query_params
from stripe_link.domain.custom_domains import normalize_domain
from stripe_link.repositories.documents import RepositoryError, custom_domains_index_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import public_url


def handler(event, context, *, index_repo=None, pages_domain=None):
    """Public endpoint: given a custom domain hostname, resolve where to reverse-proxy it.

    Called by the Cloudflare Worker on every request to a custom hostname. Deliberately
    has no tenant auth and no knowledge of Offer/Product/Stripe state -- pure routing,
    reading only the denormalized domain index (never TenantConfig directly), matching
    the funnel/offer separation principle documented in schemas/README.md.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    index_repo = index_repo or custom_domains_index_repository()
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")

    host = str(query_params(event).get("host") or header_value(event, "host") or "").strip()
    if not host:
        return error_response("host is required.", code="missing_host")

    try:
        record = index_repo.find_by_id(normalize_domain(host))
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    if not record or record.get("status") != "active":
        return error_response("Domain is not active.", status_code=404, code="not_active")

    tenant_id = str(record.get("tenant_id") or "")
    page_id = str(record.get("target_page_id") or "")
    origin_url = public_url(pages_domain, artifact_paths(tenant_id, page_id)["published"])
    if not origin_url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    return json_response({"route": {"type": "origin_url", "origin_url": origin_url}})
