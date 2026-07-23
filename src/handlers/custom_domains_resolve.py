import os
import re

from stripe_link.common import error_response, header_value, json_response, query_params
from stripe_link.domain.custom_domains import normalize_domain, normalize_route_path
from stripe_link.repositories.documents import RepositoryError, custom_domains_index_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import public_url

# A root-level well-known file (robots.txt, sitemap.xml, or an IndexNow key) — served from a sibling artifact
# under the homepage page_id. Single path segment only: no directories, no traversal.
_WELL_KNOWN_PATH = re.compile(r"^/[A-Za-z0-9._-]+\.(txt|xml)$")


def _resolve_slug(slug, routes, homepage_page_id):
    """Map a normalized request slug to the page_id that serves it, reading only the denormalized route table
    on the domain-index record (plans/SITE_OBJECT.md §2.6). A legacy record without a route table serves the
    homepage for every path (pre-2.6 behavior); the root slug always falls back to the homepage."""
    if not isinstance(routes, dict):
        return homepage_page_id  # legacy record: homepage-only serving
    entry = routes.get(slug)
    if isinstance(entry, dict) and entry.get("enabled", True) is not False:
        return str(entry.get("page_id") or "")
    if slug == "/":
        return homepage_page_id
    return ""


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

    # A www→apex redirect hostname: 301 to the canonical apex, preserving the path/query (the Worker appends
    # them to this scheme+host base). plans/SITE_OBJECT.md §2.6b.
    redirect_to = str(record.get("redirect_to") or "").strip()
    if redirect_to:
        return json_response({"route": {"type": "redirect", "location": f"https://{redirect_to}"}})

    tenant_id = str(record.get("tenant_id") or "")
    homepage_page_id = str(record.get("target_page_id") or "")

    # A well-known crawl file (/robots.txt, /sitemap.xml, /{key}.txt) is served from the sibling artifact the
    # publisher wrote under the homepage page_id. Every other path routes through the Site's slug map: the
    # homepage at "/", funnel/collection pages at their slugs, an unknown slug is a 404.
    path = str(query_params(event).get("path") or "")
    if path and _WELL_KNOWN_PATH.match(path):
        artifact_key = f"{homepage_page_id}{path}"
    else:
        page_id = _resolve_slug(normalize_route_path(path), record.get("routes"), homepage_page_id)
        if not page_id:
            return error_response("No page is published at this path.", status_code=404, code="no_route")
        artifact_key = artifact_paths(tenant_id, page_id)["published"]

    origin_url = public_url(pages_domain, artifact_key)
    if not origin_url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    return json_response({"route": {"type": "origin_url", "origin_url": origin_url}})
