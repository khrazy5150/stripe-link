import os

from stripe_link.common import path_params
from stripe_link.repositories.documents import RepositoryError, routes_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.error_pages import render_error_page


# The URL segment the visitor uses maps to the price context the artifact was published under.
_VIEW_CONTEXT = {"": "", "sale": "sale", "flash-sale": "flash_sale"}

_NOT_FOUND_HTML = render_error_page(404, "This test link is no longer available.", title="Page not found", badge="Test Environment")


def _html_response(body, status_code=200):
    # Publishing is asynchronous (a DynamoDB stream drives the render), so a freshly-published link 404s for a
    # few seconds until its artifact lands in S3. Caching that 404 (max-age) made the "no longer available" page
    # stick long after the page went live, so a not-found is never cached — only a real hit is.
    cache_control = "public, max-age=60" if status_code == 200 else "no-store"
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": cache_control,
            # Test pages must never be indexed, whatever host serves them.
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": body,
    }


def handler(event, context, *, repository=None, s3_client=None, pages_bucket=None, preview_bucket=None):
    """Public endpoint that serves a test page (and its /sale //flash-sale views) by its snowflake short_code,
    for the test.juniorbay.com host (plans/SALES_FUNNELS.md Phase B). Resolves the code to a page via the
    routes table, reads that page's artifact from S3, and returns the HTML verbatim so the visitor's URL stays
    test.juniorbay.com/{preview|published}/{short_code}. Read-only, unauthenticated; noindex.

    Routes:
      GET /preview/{code}[/{view}]   -> the SAVED (draft or published) render, from the preview bucket
      GET /published/{code}[/{view}] -> the PUBLISHED render, from the pages bucket (404 until published)
    (view = sale | flash-sale.) A custom domain is live-only, so this is the canonical way to view test pages.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return _html_response("", 200)
    if method != "GET":
        return _html_response(_NOT_FOUND_HTML, 404)

    is_preview = str((event or {}).get("resource") or (event or {}).get("path") or "").startswith("/preview")

    params = path_params(event)
    code = str(params.get("code") or "").strip()
    view = str(params.get("view") or "").strip().lower()
    if not code or view not in _VIEW_CONTEXT:
        return _html_response(_NOT_FOUND_HTML, 404)

    repository = repository or routes_repository()
    try:
        route = repository.find_by_id(code)
    except RepositoryError:
        return _html_response(_NOT_FOUND_HTML, 404)
    if not route or route.get("target_type") != "page":
        return _html_response(_NOT_FOUND_HTML, 404)

    page_id = str(route.get("target_page_id") or "")
    tenant_id = str(route.get("tenant_id") or "")
    if not page_id or not tenant_id:
        return _html_response(_NOT_FOUND_HTML, 404)

    paths = artifact_paths(tenant_id, page_id, context=_VIEW_CONTEXT[view])
    if is_preview:
        key = paths["preview"]
        bucket = preview_bucket if preview_bucket is not None else os.environ.get("PAGES_PREVIEW_BUCKET", "")
    else:
        key = paths["published"]
        bucket = pages_bucket if pages_bucket is not None else os.environ.get("PAGES_BUCKET", "")
    if not bucket:
        return _html_response(_NOT_FOUND_HTML, 404)
    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        html = obj["Body"].read().decode("utf-8")
    except Exception:
        # No artifact for this view (e.g. /sale on a page without a sale price, or an unpublished page).
        return _html_response(_NOT_FOUND_HTML, 404)
    return _html_response(html, 200)
