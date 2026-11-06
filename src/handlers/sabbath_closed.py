"""The page a shopper sees while a store is closed for the Sabbath.

Public, unauthenticated, and **not the thing that decides the closure**. The live page resolver
(`custom_domains_resolve`) decides, and points the Cloudflare Worker at this URL for the duration of the
window; the Worker proxies whatever comes back, exactly as it proxies a published page. So this handler
only renders, and the reopening moment travels in the query string from the resolver that computed it.

That split is deliberate. Recomputing the window here would mean a second implementation of the one number
this feature is about -- free to disagree with the gate that enforces it -- plus a second set of table
reads on every request. Here the query string is DISPLAY DATA: a crafted link can only make this page
state a different time to the person who crafted it, and nothing acts on it.

**503 with `Retry-After`, not 200.** A store closed for twenty-five hours every week gets crawled during
the window. 503 is the signal that says "the page is fine, come back" and keeps the URL in the index; a
200 would invite Google to index "we are closed" as the content of a product page, and a 404 or 403 would
invite it to drop the URL. The shopper sees the same page either way -- the status is for the crawler.
"""
import datetime
import logging

from stripe_link.common import query_params
from stripe_link.runtime.platform_pages import render_sabbath_closed

logger = logging.getLogger(__name__)

#: Long enough that the Worker is not re-fetching per visitor, short enough that reopening is prompt. The
#: resolve that points here is itself cached 60s, so this is the same granularity.
CACHE_SECONDS = 60


def _moment(raw: str):
    """The reopening instant from the query string, or None when it is absent or unparseable.

    None drops the sentence rather than inventing a time (see `render_sabbath_closed`)."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def _retry_after(moment) -> str:
    """Seconds until the store reopens, as `Retry-After` wants them. Never negative, never absurd."""
    if moment is None:
        return str(CACHE_SECONDS)
    delta = (moment - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    # Clamped to a day: the window is ~25h, so anything larger is a bad parameter rather than a real wait,
    # and telling a crawler to stay away for a week over a typo is not recoverable from our side.
    return str(int(max(CACHE_SECONDS, min(delta, 86400))))


def handler(event, context):
    method = (event or {}).get("httpMethod", "GET").upper()
    params = query_params(event) or {}
    moment = _moment(params.get("until"))
    try:
        body = render_sabbath_closed(
            reopen_at=moment,
            timezone_name=str(params.get("tz") or "UTC").strip() or "UTC",
            store_name=str(params.get("store") or "").strip(),
        )
    except Exception:  # noqa: BLE001 - a store must never go blank because a clock format failed
        logger.exception("sabbath: could not render the closed page")
        body = render_sabbath_closed()
    return {
        "statusCode": 503,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Retry-After": _retry_after(moment),
            "Cache-Control": f"public, max-age={CACHE_SECONDS}",
        },
        # HEAD and OPTIONS get the same headers and no body, so a crawler probing the URL still reads the
        # 503 and the Retry-After.
        "body": "" if method in {"HEAD", "OPTIONS"} else body,
    }
