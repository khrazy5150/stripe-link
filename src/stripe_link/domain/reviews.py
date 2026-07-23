"""Review aggregation (plans/REVIEWS.md). Kept pure so the renderer and the dashboard compute the same
numbers. Only APPROVED, non-GBP (first-party) reviews are markup-eligible — Google forbids aggregating
third-party/Google reviews into your own AggregateRating, and self-serving business reviews are excluded at
the render layer, not here."""
from typing import Any


def markup_eligible(reviews: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Reviews that may feed AggregateRating/Review markup: approved and not sourced from GBP/third parties."""
    return [
        r for r in (reviews or [])
        if isinstance(r, dict) and r.get("status") == "approved" and r.get("source") != "gbp"
    ]


def aggregate_reviews(reviews: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """`{rating_value, review_count}` over the markup-eligible reviews, or None when there are none.
    rating_value is rounded to one decimal place (schema.org accepts a decimal)."""
    eligible = markup_eligible(reviews)
    if not eligible:
        return None
    total = sum(int(r.get("rating") or 0) for r in eligible)
    return {"rating_value": round(total / len(eligible), 1), "review_count": len(eligible)}
