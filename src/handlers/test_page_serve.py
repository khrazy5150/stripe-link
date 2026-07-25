import os

from stripe_link.common import path_params
from stripe_link.repositories.documents import RepositoryError, routes_repository
from stripe_link.runtime.artifacts import artifact_paths


# The URL segment the visitor uses maps to the price context the artifact was published under.
_VIEW_CONTEXT = {"": "", "sale": "sale", "flash-sale": "flash_sale"}

_NOT_FOUND_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
    "<title>Page not found</title></head><body style=\"font-family:system-ui;text-align:center;padding:4rem 1rem\">"
    "<h1>Page not found</h1><p>This test link is no longer available.</p></body></html>"
)


def _html_response(body, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "public, max-age=60",
            # Test pages must never be indexed, whatever host serves them.
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": body,
    }


def handler(event, context, *, repository=None, s3_client=None, pages_bucket=None):
    """Public endpoint that serves a published page (and its /sale //flash-sale views) by its snowflake
    short_code, for the test.juniorbay.com host (plans/SALES_FUNNELS.md Phase B). Resolves the code to a page
    via the routes table, reads that page's published artifact from S3, and returns the HTML verbatim so the
    visitor's URL stays test.juniorbay.com/published/{short_code}. Read-only, unauthenticated; noindex.

    Routes: GET /published/{code} and GET /published/{code}/{view} (view = sale | flash-sale).
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return _html_response("", 200)
    if method != "GET":
        return _html_response(_NOT_FOUND_HTML, 404)

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

    key = artifact_paths(tenant_id, page_id, context=_VIEW_CONTEXT[view])["published"]
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
