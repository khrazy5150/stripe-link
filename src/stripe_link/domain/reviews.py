"""Review aggregation (plans/REVIEWS.md). Kept pure so the renderer and the dashboard compute the same
numbers. Only APPROVED, non-GBP (first-party) reviews are markup-eligible — Google forbids aggregating
third-party/Google reviews into your own AggregateRating, and self-serving business reviews are excluded at
the render layer, not here."""
from typing import Any


def review_mode(review: dict[str, Any] | None) -> str:
    """Which books a review belongs to, or "" when it cannot be placed.

    Reviews are not mode-scoped in storage and changing that would move the sort key under every existing
    one. They do not need it: a verified review carries the `order_id` it came from, and that id names its
    checkout session -- `order_cs_live_...`. The mode has always been in the data.

    `stripe_mode` is stamped at submission now, and wins when present only because it is cheaper to read;
    the two cannot disagree, since the stamp is taken from the same order.

    "" means a review nobody can place: entered by hand with no order behind it, or written before the
    stamp existed. What to do with one differs by surface, deliberately -- see `in_mode`.
    """
    from stripe_link.common import stripe_mode_from_reference

    stored = str((review or {}).get("stripe_mode") or "").strip().lower()
    if stored in ("live", "test"):
        return stored
    return stripe_mode_from_reference((review or {}).get("order_id"))


def in_mode(reviews: list[dict[str, Any]] | None, mode: str, *, include_unplaceable: bool) -> list[dict[str, Any]]:
    """The reviews belonging to `mode`.

    `include_unplaceable` is the whole decision, and it is NOT the same answer on every surface:

    * **A published page: False.** A review that cannot prove which books it came from must not appear in
      a public star rating. The entire value of this system is that the rating is a true claim about real
      buyers (plans/REVIEWS.md), and a test review shown to a real shopper -- counted in AggregateRating,
      in the markup Google reads -- is the one failure that cannot be taken back. Every review written
      from now on is stamped, so this only ever withholds one that predates the stamp AND has no order.
    * **The tenant's own list: True.** Hiding a review a tenant typed in themselves, in a screen they use
      to manage reviews, is a bug report waiting to happen and costs nothing but a moment's confusion.

    Fail in the direction whose cost is recoverable -- the same rule the notification bell, the leads list
    and the refund queue each follow, pointing different ways for the same reason.
    """
    wanted = "live" if str(mode or "").strip().lower() == "live" else "test"
    out = []
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        actual = review_mode(review)
        if actual == wanted or (not actual and include_unplaceable):
            out.append(review)
    return out


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
