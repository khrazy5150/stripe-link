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


def _funnel_artifact_page_id(base_page_id, entry, funnel_step):
    """The synthetic post-purchase funnel artifact a reserved funnel slug serves (plans/SALES_FUNNELS.md P2b).
    Derived from the base sales page_id + the entry's `funnel_role`/`strategy` + the request's funnel_step, to
    match what the publisher synthesizes: `{base}__upsell_{n}` (sequence, n from funnel_step, 1-based) or
    `{base}__upsell_carousel` (carousel); `{base}__downsell_carousel`; `{base}__thank_you`."""
    role = str(entry.get("funnel_role") or "")
    strategy = str(entry.get("strategy") or "sequence")
    if role == "thank_you":
        return f"{base_page_id}__thank_you"
    if role == "downsell":
        return f"{base_page_id}__downsell_carousel"  # only attached in carousel mode
    if role == "upsell":
        if strategy == "carousel":
            return f"{base_page_id}__upsell_carousel"
        step = str(funnel_step or "").strip()
        n = step if (step.isdigit() and int(step) >= 1) else "1"
        return f"{base_page_id}__upsell_{n}"
    return base_page_id


def _resolve_slug(slug, routes, homepage_page_id, funnel_step=""):
    """Map a normalized request slug to the (page_id, price_context) that serves it, reading only the
    denormalized route table on the domain-index record (plans/SITE_OBJECT.md §2.6). A Sale/Flash-Sale context
    view (plans/SALES_FUNNELS.md P1c) carries a `price_context` so it serves the base page's sibling artifact.
    A reserved funnel slug (P2b) carries a `funnel_role`, so it serves a synthetic funnel artifact derived from
    the base page_id + the request's funnel_step (funnel artifacts are never context-varied). A legacy record
    without a route table serves the homepage for every path; the root always falls back."""
    if not isinstance(routes, dict):
        return homepage_page_id, ""  # legacy record: homepage-only serving
    entry = routes.get(slug)
    if isinstance(entry, dict) and entry.get("enabled", True) is not False:
        base_page_id = str(entry.get("page_id") or "")
        if entry.get("funnel_role"):
            return _funnel_artifact_page_id(base_page_id, entry, funnel_step), ""
        return base_page_id, str(entry.get("price_context") or "")
    if slug == "/":
        return homepage_page_id, ""
    return "", ""


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
    qp = query_params(event)
    path = str(qp.get("path") or "")
    if path and _WELL_KNOWN_PATH.match(path):
        artifact_key = f"{homepage_page_id}{path}"
    else:
        # funnel_step selects which sequential upsell a reserved /upsell slug serves (P2b); the Worker forwards
        # the buyer's query string, so it arrives here alongside path.
        funnel_step = str(qp.get("funnel_step") or "")
        page_id, price_context = _resolve_slug(normalize_route_path(path), record.get("routes"), homepage_page_id, funnel_step)
        if not page_id:
            return error_response("No page is published at this path.", status_code=404, code="no_route")
        artifact_key = artifact_paths(tenant_id, page_id, context=price_context)["published"]

    origin_url = public_url(pages_domain, artifact_key)
    if not origin_url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    return json_response({"route": {"type": "origin_url", "origin_url": origin_url}})
