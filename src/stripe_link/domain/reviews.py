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


REVIEW_DESTINATIONS = {"junior_bay", "google"}
# entity_types whose reviews belong on Google/Maps (self-serving suppression means on-site business reviews
# earn no stars — their star surface is GBP). Product stores (OnlineStore/Organization/Store) default to
# Junior Bay, where on-site Product reviews DO earn star snippets.
_GOOGLE_DEFAULT_ENTITY_TYPES = {
    "LocalBusiness", "HomeAndConstructionBusiness", "HealthAndBeautyBusiness",
    "FoodEstablishment", "ProfessionalService",
}


def google_review_link(place_id: Any) -> str:
    """The native Google 'write a review' deep link for a Place ID (empty when there's no place_id)."""
    pid = str(place_id or "").strip()
    return f"https://search.google.com/local/writereview?placeid={pid}" if pid else ""


def default_review_destination(organization: dict[str, Any] | None) -> str:
    """Where a business's review invites should point by default, derived from its entity_type."""
    return "google" if str((organization or {}).get("entity_type") or "") in _GOOGLE_DEFAULT_ENTITY_TYPES else "junior_bay"


def resolve_review_destination(organization: dict[str, Any] | None) -> str:
    """The destination for this business's review invites (plans/REVIEWS.md). Explicit per-Site override wins;
    otherwise the entity_type default. 'google' requires a place_id — without one we fall back to Junior Bay
    rather than email a dead link. Uniform tenant policy, so it's compliant (not sentiment gating)."""
    org = organization or {}
    choice = str(org.get("review_destination") or "").strip()
    if choice not in REVIEW_DESTINATIONS:
        choice = default_review_destination(org)
    if choice == "google" and not google_review_link(org.get("place_id")):
        return "junior_bay"
    return choice


def aggregate_reviews(reviews: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """`{rating_value, review_count}` over the markup-eligible reviews, or None when there are none.
    rating_value is rounded to one decimal place (schema.org accepts a decimal)."""
    eligible = markup_eligible(reviews)
    if not eligible:
        return None
    total = sum(int(r.get("rating") or 0) for r in eligible)
    return {"rating_value": round(total / len(eligible), 1), "review_count": len(eligible)}
