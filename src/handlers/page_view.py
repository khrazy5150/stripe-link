"""Public beacon endpoint for page views: GET|POST /t/view?p={page_id}&v={visitor_id}

Unauthenticated by necessity -- it is called from a published page by an anonymous visitor. That shapes
every decision here:

- **Always 204, never a body.** A tracking endpoint must not tell a caller whether a page exists, whether
  a view was counted, or that anything went wrong. It is also the cheapest possible response for something
  fired on every page load.
- **Nothing the caller sends reaches a key unchecked.** `page_id` is shape-validated before it is used, so
  the endpoint cannot be driven to write arbitrary partition keys.
- **Failure is silent to the caller and loud in the log.** A visitor must never see an analytics error; an
  operator must be able to find one.

Abuse ceiling: a determined caller can inflate one page's count. That is true of every client-side
analytics beacon, including Google's, and the dedupe means it costs a distinct visitor key per increment.
Rate limiting is the follow-up if it ever matters -- the same position plans/LEAD_CAPTURE.md takes.
"""
import os
import time

from stripe_link.domain.page_views import (
    counter_key,
    day_bucket,
    dedupe_item,
    is_trackable_page_id,
    visitor_key,
)
from stripe_link.repositories.page_views import page_views_repository


def _no_content():
    return {
        "statusCode": 204,
        "headers": {
            "Content-Type": "text/plain",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": "",
    }


def handler(event, context, repository=None, now=None):
    event = event or {}
    if str(event.get("httpMethod") or "").upper() == "OPTIONS":
        return _no_content()

    params = event.get("queryStringParameters") or {}
    page_id = str(params.get("p") or "").strip()
    if not is_trackable_page_id(page_id):
        return _no_content()

    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    forwarded = str(headers.get("x-forwarded-for") or "")
    now_ts = int(now if now is not None else time.time())
    day = day_bucket(now_ts)
    visitor = visitor_key(
        ip=forwarded.split(",", 1)[0].strip(),
        user_agent=str(headers.get("user-agent") or ""),
        explicit_id=str(params.get("v") or ""),
        salt=os.environ.get("PAGE_VIEW_SALT", ""),
        day=day,
    )
    try:
        repo = repository or page_views_repository()
        if repo.claim_view(dedupe_item(page_id, day, visitor, now_ts)):
            repo.increment_total(counter_key(page_id), now_ts)
    except Exception as exc:  # noqa: BLE001 - a visitor must never see an analytics failure
        print(f"page view not recorded for {page_id}: {type(exc).__name__}: {exc}")
    return _no_content()
