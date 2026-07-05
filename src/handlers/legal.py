from datetime import datetime, timezone

from stripe_link.common import json_response, path_params
from stripe_link.domain.legal import (
    LEGAL_CONFIG,
    merge_page_with_default,
    pages_with_defaults,
    render_public_page,
)
from stripe_link.repositories.documents import (
    PLATFORM_TENANT_ID,
    RepositoryError,
    legal_pages_repository,
)


def handler(event, context, *, repository=None, config=None, year_fn=None):
    """Public, unauthenticated legal pages.

    GET /legal              -> JSON list of enabled pages (footer links) + company_name.
    GET /legal/{page_id}    -> full styled HTML page (terms/privacy/refund).

    Platform-global: built-in defaults are served when the table is empty, and a stored
    legal_page document overrides any field per page.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return _html_response("<h1>Method not allowed</h1>", status_code=405)

    repository = repository or legal_pages_repository()
    config = config or LEGAL_CONFIG
    page_id = str(path_params(event).get("page_id") or "").strip()

    if not page_id:
        return list_pages(repository, config)
    return serve_page(repository, config, page_id, year_fn)


def list_pages(repository, config):
    try:
        stored = repository.list_for_tenant(PLATFORM_TENANT_ID)
    except RepositoryError:
        stored = []
    pages = pages_with_defaults(stored, config)
    links = [
        {
            "page_id": page["page_id"],
            "title": page.get("title", ""),
            "link_text": page.get("link_text", page.get("title", "")),
            "display_order": page.get("display_order", 0),
            "url": f"/legal/{page['page_id']}",
        }
        for page in pages
    ]
    return json_response({"pages": links, "company_name": config.get("company_name", "")})


def serve_page(repository, config, page_id, year_fn):
    try:
        stored = repository.get(PLATFORM_TENANT_ID, page_id)
    except RepositoryError:
        stored = None
    page = merge_page_with_default(page_id, stored, config)
    if not page or not page.get("enabled", True):
        return _html_response("<h1>Page not found</h1>", status_code=404)
    year = int(year_fn()) if year_fn else datetime.now(timezone.utc).year
    return _html_response(render_public_page(page, config, year))


def _html_response(body, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": body,
    }
