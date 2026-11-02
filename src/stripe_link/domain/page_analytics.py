"""Per-page conversion and revenue, derived from orders rather than counted.

The dashboard has always shown views / conversions / revenue on every landing-page card, reading
`page.analytics_summary` — a field NOTHING in the backend has ever written. Every card showed zeros. Same
shape as `same_as[].verified`: read, displayed, no producer.

Two of the three numbers need no ingest at all. A paid order already records which page it came from
(`attribution.page_id`), which is exactly how the A/B experiment results are computed — so conversions and
revenue are a fold over orders the tenant already has, not a counter to maintain.

VIEWS are deliberately absent, not zero. Counting them needs real ingest: a public write endpoint, a
counters store that is NOT the Pages table (any MODIFY there republishes the page — see
should_publish_record), and an abuse story for an unauthenticated endpoint on a shared host. Reporting
"0 views" for traffic we never measured is the bug this module exists to stop repeating, so the number is
omitted and the UI shows nothing rather than a confident zero.
"""
from typing import Any

# A conversion is a PAID order. Shared with the experiment results so a status added to one is not missing
# from the other -- they answer the same question about the same table.
PAID_ORDER_STATUSES = {"paid", "complete", "completed"}


def summarize_by_page(orders: Any) -> dict[str, dict[str, int]]:
    """{page_id: {"conversions": n, "revenue_cents": n}} over paid orders that name a page."""
    summary: dict[str, dict[str, int]] = {}
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        if str(order.get("status") or "") not in PAID_ORDER_STATUSES:
            continue
        page_id = str((order.get("attribution") or {}).get("page_id") or "").strip()
        if not page_id:
            continue
        entry = summary.setdefault(page_id, {"conversions": 0, "revenue_cents": 0})
        entry["conversions"] += 1
        try:
            entry["revenue_cents"] += int(order.get("amount_total") or 0)
        except (TypeError, ValueError):
            pass  # a malformed amount must not cost the whole listing its numbers
    return summary


def summarize_by_source(orders: Any, page_id: str = "") -> dict[str, dict[str, int]]:
    """{source: {"conversions": n, "revenue_cents": n}} over paid orders that name a source.

    The money half of attribution (plans/ATTENTION_PRIMITIVE.md §8). Arrivals are counted in the
    page-views table; this is the same fold `summarize_by_page` does, keyed on the post instead of the
    page, so the two numbers are derived the same way and cannot disagree about what a conversion is.

    `page_id` narrows it to one page's orders. Without it the answer is the tenant's whole book by source,
    which is the right shape for a campaign report and the wrong one for a page card.
    """
    wanted = str(page_id or "").strip()
    summary: dict[str, dict[str, int]] = {}
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        if str(order.get("status") or "") not in PAID_ORDER_STATUSES:
            continue
        attribution = order.get("attribution") or {}
        source = str(attribution.get("source") or "").strip()
        if not source:
            continue
        if wanted and str(attribution.get("page_id") or "").strip() != wanted:
            continue
        entry = summary.setdefault(source, {"conversions": 0, "revenue_cents": 0})
        entry["conversions"] += 1
        try:
            entry["revenue_cents"] += int(order.get("amount_total") or 0)
        except (TypeError, ValueError):
            pass  # a malformed amount must not cost the whole report its numbers
    return summary


def attribution_rows(arrivals: dict[str, int] | None,
                     by_source: dict[str, dict[str, int]] | None) -> list[dict[str, Any]]:
    """One row per source: arrivals, conversions, revenue. Sorted by revenue, then arrivals.

    **The union of both sides, not the intersection.** A source with arrivals and no sales is the most
    useful row on the report -- it is the post that got attention and sold nothing, which is the whole
    point of measuring. And a source with sales but no arrivals is real too: the visitor arrived before
    the tracker shipped, or cleared their storage, and dropping it would quietly understate revenue.

    `arrivals` is omitted from a row that has none, rather than written as 0, for `attach_summaries`'
    reason: "nobody came" and "we were not measuring" must stay distinguishable.
    """
    arrivals = arrivals or {}
    by_source = by_source or {}
    rows = []
    for source in sorted(set(arrivals) | set(by_source)):
        money = by_source.get(source) or {}
        row: dict[str, Any] = {
            "source": source,
            "conversions": int(money.get("conversions") or 0),
            "revenue_cents": int(money.get("revenue_cents") or 0),
        }
        if source in arrivals:
            row["arrivals"] = int(arrivals[source])
        rows.append(row)
    rows.sort(key=lambda r: (r["revenue_cents"], r.get("arrivals", 0)), reverse=True)
    return rows


def attach_summaries(pages: list[dict[str, Any]], orders: Any,
                     views_by_page: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Give each page its derived analytics_summary.

    Written for every page, including pages with no orders, so the UI can distinguish "measured, zero
    conversions" from "not measured". A page absent from the fold genuinely has no paid orders.
    """
    summary = summarize_by_page(orders)
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        page_id = str(page.get("page_id") or "")
        derived = dict(summary.get(page_id, {"conversions": 0, "revenue_cents": 0}))
        # Views are present ONLY when the rail has actually seen this page. A page that has never been
        # published has no tracker in its artifact, so an absent key means "not measured" -- which the UI
        # must be able to tell apart from "measured, nobody came".
        if views_by_page and page_id in views_by_page:
            derived["views"] = int(views_by_page[page_id])
        page["analytics_summary"] = derived
    return pages
