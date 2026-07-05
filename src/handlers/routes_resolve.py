import os

from stripe_link.common import error_response, json_response, query_params
from stripe_link.repositories.documents import RepositoryError, routes_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import public_url


def handler(event, context, *, repository=None, pages_domain=None, api_base_url=None):
    """Public endpoint: resolve a short code to its redirect destination.

    Called by the Cloudflare Worker on every hit to the short-URL host (go.jbay.uk/{code}).
    Read-only, unauthenticated -- reads only the routes table and returns the 302 target.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    repository = repository or routes_repository()
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")
    api_base_url = api_base_url if api_base_url is not None else os.environ.get("PUBLIC_API_BASE_URL", "")

    code = str(query_params(event).get("code") or "").strip()
    if not code:
        return error_response("code is required.", code="missing_code")

    try:
        route = repository.find_by_id(code)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    if not route:
        return error_response("Short link not found.", status_code=404, code="not_found")

    destination = destination_url(route, pages_domain=pages_domain, api_base_url=api_base_url)
    if not destination:
        return error_response("Short link has no destination.", status_code=404, code="no_destination")

    return json_response({"route": {"type": "redirect", "destination_url": destination}})


def destination_url(route, *, pages_domain, api_base_url):
    target_type = route.get("target_type")
    if target_type == "url":
        return str(route.get("target_url") or "")
    if target_type == "page":
        page_id = str(route.get("target_page_id") or "")
        tenant_id = str(route.get("tenant_id") or "")
        if not page_id or not tenant_id:
            return ""
        return public_url(pages_domain, artifact_paths(tenant_id, page_id)["published"])
    if target_type == "experiment":
        # A/B experiment resolver (built in the A/B testing slice); the short code points at
        # the resolver, which does the weighted per-visit variant assignment.
        experiment_id = str(route.get("target_experiment_id") or "")
        base = str(api_base_url or "").rstrip("/")
        return f"{base}/experiments/{experiment_id}/resolve" if base and experiment_id else ""
    return ""
