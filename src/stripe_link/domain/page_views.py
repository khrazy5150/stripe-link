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


# --- per-link clicks (plans/SOCIAL_MEDIA_PAGES.md §11: "link-in-bio pages live or die on click data") ---
#
# Rides the SAME table and the same beacon as views. It needs no new abuse story, no new endpoint shape and
# no new store -- which is why this was worth waiting for the view rail rather than building first.
_LINK_KEY_LENGTH = 16


def link_id(url: Any) -> str:
    """A stable, opaque id for one destination on a page.

    Keyed on the URL, NOT on the link's position. Position looked simpler and is wrong: reordering a hub --
    which creators do constantly -- would silently reassign every link's history to its new neighbour, and
    the numbers would keep looking plausible. Changing a URL starts a fresh count, which is correct: it is a
    different destination.

    Hashed rather than stored raw so the counter key carries no tenant-entered text, and so one key shape
    fits every URL length.
    """
    return hashlib.sha256(str(url or "").strip().encode("utf-8")).hexdigest()[:_LINK_KEY_LENGTH]


def link_dedupe_item(page_id: str, link: str, day: str, visitor: str, now: int) -> dict[str, Any]:
    """The row whose CONDITIONAL creation decides whether this click counts.

    Deduped per (page, link, visitor, day) exactly as views are, and that is a deliberate choice about UNITS
    rather than caution. Views count unique visitors; if clicks counted raw taps the two numbers would be in
    different units, so "8 views, 11 Instagram clicks" would be a true sentence that reads as broken and any
    click-through rate computed from them would be nonsense. Counting unique clickers keeps every number on
    this page an answer about PEOPLE.
    """
    return {
        "PK": f"PAGELINKCLICK#{page_id}#{day}",
        "SK": f"LINK#{link}#VISITOR#{visitor}",
        "page_id": page_id,
        "link_id": link,
        "day": day,
        "created_at": now,
        "ttl": now + VIEW_TTL_DAYS * 24 * 60 * 60,
    }


def link_counter_key(page_id: str, link: str) -> dict[str, str]:
    """The aggregate one link's clicks accumulate on. Every link of a page shares a partition so the
    dashboard reads them all in ONE query instead of a lookup per link."""
    return {"PK": f"PAGELINKS#{page_id}", "SK": f"LINK#{link}"}


def link_counter_partition(page_id: str) -> str:
    return f"PAGELINKS#{page_id}"


def page_link_urls(page: Any, organization: Any = None) -> list[str]:
    """Every outbound URL this page actually renders, in order, de-duplicated.

    Resolves `social_links` through the SAME override-or-inherit rule the renderer uses, so a page showing
    the Site's profiles reports clicks for them too. Reading the page document alone would have labelled
    only page-local links and left the inherited ones as unexplained numbers -- or, worse, made the
    dashboard hash URLs itself, which is a second implementation of the id that must agree with this one
    forever.
    """
    from stripe_link.domain.social_links import section_link_entries

    urls: list[str] = []
    for section in ((page or {}).get("sections") or []):
        if not isinstance(section, dict):
            continue
        kind = section.get("type")
        if kind == "social_links":
            urls.extend(str(e.get("url") or "").strip()
                        for e in section_link_entries(section, organization))
        elif kind == "link_cards":
            urls.extend(str((i or {}).get("url") or "").strip()
                        for i in (section.get("items") or []) if isinstance(i, dict))
    seen, ordered = set(), []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def clicks_by_url(page: Any, totals: dict[str, int], organization: Any = None) -> dict[str, int]:
    """Per-link click counts keyed by URL, for a page and its id-keyed totals.

    Keyed by URL rather than by id because the id is ours, not the tenant's: the dashboard should never
    need to reproduce the hash to read its own numbers. A link with no clicks yet is reported as 0 rather
    than omitted -- "nobody has clicked this" is a real answer, and an absent key would render as blank.
    """
    return {url: int(totals.get(link_id(url), 0)) for url in page_link_urls(page, organization)}


def is_trackable_link_id(link: Any) -> bool:
    """Shape check on an unauthenticated endpoint, same job as is_trackable_page_id: the caller supplies
    this, so it must not be able to drive the key anywhere we did not intend."""
    text = str(link or "").strip()
    return len(text) == _LINK_KEY_LENGTH and all(c in "0123456789abcdef" for c in text)


def is_trackable_page_id(page_id: Any) -> bool:
    """Cheap shape check on an unauthenticated endpoint: reject anything that is not a page id before it
    reaches DynamoDB, so a public beacon cannot be used to write arbitrary keys."""
    text = str(page_id or "").strip()
    return text.startswith("page_") and len(text) <= 64 and text.replace("_", "").isalnum()
