"""Page-view counting: unique visitors per page per day.

The zero-configuration baseline. A tenant who never sets up GA4 or a Meta pixel still sees whether anyone
is looking at their page; a tenant who wants sessions, sources and funnels configures a real analytics
product, which the renderer already supports. We deliberately do not compete with that.

Three decisions carried over from the legacy implementation (stripe-cart `page_tracking.py`), which got
these right:

- **A beacon, not a redirect.** `navigator.sendBeacon` on the published page. A `/go/...` redirector would
  make the shared platform host an open redirect, which is the abuse surface plans/SOCIAL_MEDIA_PAGES.md §7
  exists to prevent.
- **Unique visitors per day, not raw hits.** A conditional write per (page, day, visitor) means a refresh
  does not inflate the number. A tenant reloading their own page all afternoon counts once.
- **A TTL on the dedupe rows**, so the store stays proportional to traffic rather than growing forever.

And two that differ deliberately:

- **Its own table, never the Pages table.** Legacy incremented `stats.views` on the page item. Here any
  MODIFY to PagesTable fires the publish stream (`should_publish_record`), so counting there would
  re-render and re-upload the page on every visitor, and the dedupe rows would themselves be handed to the
  publisher as though they were pages.
- **A salted visitor key.** Legacy hashed IP + user-agent unsalted, which is a stable pseudonymous
  identifier: anyone holding the table could test whether a given IP visited a given page. Mixing in a
  secret plus the day makes the key unlinkable across days and unguessable without the secret, while
  deduping exactly as well within the day it is used.
"""
import hashlib
import time
from typing import Any

VIEW_TTL_DAYS = 45
_VISITOR_KEY_LENGTH = 32


def day_bucket(now: float | None = None) -> str:
    """UTC day, the window uniqueness is measured over."""
    return time.strftime("%Y%m%d", time.gmtime(now if now is not None else time.time()))


def visitor_key(*, ip: str = "", user_agent: str = "", explicit_id: str = "", salt: str = "",
                day: str = "") -> str:
    """A per-day pseudonym for one visitor.

    `explicit_id` (a first-party id the page itself stored) is preferred: it survives a changed IP and is
    not derived from anything about the person. The IP + user-agent fallback is a heuristic, and is the
    reason the salt matters -- without it the digest is a stable, testable identifier for a household.
    """
    basis = f"vid:{explicit_id.strip()}" if explicit_id.strip() else f"{ip.strip()}|{user_agent.strip()}"
    return hashlib.sha256(f"{salt}|{day}|{basis}".encode("utf-8")).hexdigest()[:_VISITOR_KEY_LENGTH]


def dedupe_item(page_id: str, day: str, visitor: str, now: int) -> dict[str, Any]:
    """The row whose CONDITIONAL creation decides whether this view counts."""
    return {
        "PK": f"PAGEVIEW#{page_id}#{day}",
        "SK": f"VISITOR#{visitor}",
        "page_id": page_id,
        "day": day,
        "created_at": now,
        "ttl": now + VIEW_TTL_DAYS * 24 * 60 * 60,
    }


def counter_key(page_id: str) -> dict[str, str]:
    """The aggregate this page's views accumulate on. No TTL -- the total outlives the dedupe rows."""
    return {"PK": f"PAGEVIEWS#{page_id}", "SK": "TOTAL"}


def is_trackable_page_id(page_id: Any) -> bool:
    """Cheap shape check on an unauthenticated endpoint: reject anything that is not a page id before it
    reaches DynamoDB, so a public beacon cannot be used to write arbitrary keys."""
    text = str(page_id or "").strip()
    return text.startswith("page_") and len(text) <= 64 and text.replace("_", "").isalnum()
