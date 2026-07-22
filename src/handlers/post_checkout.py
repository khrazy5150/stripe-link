import os
from urllib.parse import urlencode

from stripe_link.common import error_response, json_response, path_params, query_params, tenant_id_from_event
from stripe_link.domain.connect_sync import site_domain_verified
from stripe_link.domain.funnels import FunnelError, resolve_funnel_transition
from stripe_link.repositories.documents import RepositoryError, pages_repository, sites_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import find_site_for_page, public_url, site_page_slug


def _next_page_url(site, tenant_id, next_page_id, pages_domain):
    """The buyer-facing URL for the funnel's next page. Prefer the Site's verified custom domain at the page's
    own slug so the buyer never leaves the domain mid-funnel (plans/SITE_OBJECT.md §2.6); otherwise fall back
    to the interim platform artifact URL."""
    if site and site_domain_verified(site):
        slug = site_page_slug(site, next_page_id)
        custom_domain = str((site.get("hosting") or {}).get("custom_domain") or "")
        if slug and custom_domain:
            path = "" if slug == "/" else slug.lstrip("/")
            return f"https://{custom_domain}/{path}"
    return public_url(pages_domain, artifact_paths(tenant_id, next_page_id)["published"])


def handler(event, context, *, repository=None, pages_domain=None, sites_repo=None):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    repository = repository or pages_repository()
    sites_repo = sites_repo or (sites_repository() if os.environ.get("SITES_TABLE") else None)
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")

    page_id = path_params(event).get("page_id")
    params = query_params(event)
    tenant_id = tenant_id_from_event(event)
    outcome = str(params.get("outcome") or "").strip().lower()
    current_step_id = str(params.get("step_id") or "").strip() or None
    session_id = str(params.get("session_id") or "").strip()

    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not page_id:
        return error_response("page_id is required.", code="missing_page")

    try:
        page = repository.get(tenant_id, page_id)
        if not page:
            return error_response("Page not found.", status_code=404, code="not_found")

        destination = resolve_funnel_transition(
            page.get("post_checkout") or {},
            current_step_id=current_step_id,
            outcome=outcome,
        )
    except FunnelError as exc:
        return error_response(str(exc), code="funnel_error")
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    if destination["kind"] == "url":
        return redirect_response(destination["url"])

    next_page_id = destination["page_id"]
    next_step_id = destination.get("step_id", "")
    site = find_site_for_page(sites_repo, tenant_id, page_id)
    url = _next_page_url(site, tenant_id, next_page_id, pages_domain)
    if not url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    query = {}
    if session_id:
        query["session_id"] = session_id
    if next_step_id and next_step_id != "thank_you":
        query["funnel_page"] = page_id
        query["funnel_step"] = next_step_id
    if query:
        url = f"{url}?{urlencode(query)}"
    return redirect_response(url)


def redirect_response(url):
    return {
        "statusCode": 303,
        "headers": {
            "Location": url,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": "",
    }
