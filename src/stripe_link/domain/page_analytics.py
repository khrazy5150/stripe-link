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


def attach_summaries(pages: list[dict[str, Any]], orders: Any) -> list[dict[str, Any]]:
    """Give each page its derived analytics_summary.

    Written for every page, including pages with no orders, so the UI can distinguish "measured, zero
    conversions" from "not measured". A page absent from the fold genuinely has no paid orders.
    """
    summary = summarize_by_page(orders)
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        derived = summary.get(str(page.get("page_id") or ""), {"conversions": 0, "revenue_cents": 0})
        page["analytics_summary"] = dict(derived)
    return pages
