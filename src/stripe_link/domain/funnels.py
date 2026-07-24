import re
from typing import Any


class FunnelError(ValueError):
    pass


# Slugs the sales funnel owns — tenants may never assign a page to these manually (plans/SALES_FUNNELS.md).
# "/" is the sales page; the others are funnel views/steps the builder auto-provisions.
RESERVED_SITE_SLUGS = frozenset({"/", "/sale", "/flash-sale", "/upsell", "/downsell", "/thank-you"})


def is_reserved_slug(slug: str) -> bool:
    """True when `slug` is a funnel-reserved route. Expects a canonical slug (lowercased, no trailing slash),
    e.g. the output of normalize_route_path."""
    return str(slug or "").strip().lower() in RESERVED_SITE_SLUGS


_SLUG_SEGMENT_RE = re.compile(r"[^a-z0-9]+")


def funnel_step_slug(step_id: str) -> str:
    """A Site route slug derived from a funnel step_id: lowercased, non-alphanumerics folded to hyphens
    ("upsell_1" -> "/upsell-1"). Empty string when nothing usable remains."""
    segment = _SLUG_SEGMENT_RE.sub("-", str(step_id or "").lower()).strip("-")
    return f"/{segment}" if segment else ""


def funnel_slug_entries(post_checkout: dict[str, Any]) -> list[dict[str, str]]:
    """The Site.pages entries the pages of a Page's inline funnel need so the whole funnel routes on the
    custom domain (plans/SITE_OBJECT.md §2.6): the thank-you page at /thank-you and each funnel step at a
    slug from its step_id. All are noindex — post-checkout pages are never organic search entry points.
    Returns [] for an external thank-you URL, a detached funnel_id, or no funnel."""
    if not isinstance(post_checkout, dict) or post_checkout.get("funnel_id"):
        return []
    entries: list[dict[str, str]] = []
    thank_you = post_checkout.get("thank_you_page") or {}
    if thank_you.get("page_id"):
        entries.append({"slug": "/thank-you", "page_id": str(thank_you["page_id"]), "page_type": "thank_you"})
    for step in post_checkout.get("funnel_steps") or []:
        page_id = str(step.get("page_id") or "")
        slug = funnel_step_slug(step.get("step_id"))
        if page_id and slug:
            entries.append({"slug": slug, "page_id": page_id, "page_type": "funnel_step"})
    return entries


def resolve_funnel_transition(
    post_checkout: dict[str, Any],
    *,
    current_step_id: str | None,
    outcome: str,
) -> dict[str, Any]:
    """Resolve the next post-checkout destination for a Page's inline funnel (Phase 1 only).

    Pure routing decision: this never touches Offer, Product, or Stripe state. The caller
    is responsible for any charge (e.g. a one-click upsell) completing *before* asking for
    the "accept" transition — this function has no way to know whether a charge happened.

    `current_step_id=None` resolves the destination immediately after the entry checkout
    (before any funnel step has been shown): the first step, or thank_you if there are no
    steps. Otherwise `current_step_id` must match a step_id in `funnel_steps`, and `outcome`
    ("accept" or "decline") selects that step's on_accept/on_decline target.

    Returns either {"kind": "page", "page_id": ..., "step_id": ...} or {"kind": "url", "url": ...}.
    """
    if outcome not in ("accept", "decline"):
        raise FunnelError("outcome must be 'accept' or 'decline'.")
    if post_checkout.get("funnel_id"):
        raise FunnelError("Detached funnel resolution (Phase 2) is not yet supported.")

    steps = post_checkout.get("funnel_steps") or []
    thank_you_page = post_checkout.get("thank_you_page") or {}

    if current_step_id is None:
        if steps:
            return _step_destination(steps[0])
        return _thank_you_destination(thank_you_page)

    step = _find_step(steps, current_step_id)
    if step is None:
        raise FunnelError(f"Funnel step '{current_step_id}' was not found.")

    target = step.get("on_accept") if outcome == "accept" else step.get("on_decline")
    if not target or target == "thank_you":
        return _thank_you_destination(thank_you_page)

    next_step = _find_step(steps, target)
    if next_step is None:
        raise FunnelError(f"Funnel step target '{target}' was not found.")
    return _step_destination(next_step)


def _find_step(steps: list[dict[str, Any]], step_id: str) -> dict[str, Any] | None:
    return next((step for step in steps if step.get("step_id") == step_id), None)


def _step_destination(step: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "page", "page_id": step.get("page_id", ""), "step_id": step.get("step_id", "")}


def _thank_you_destination(thank_you_page: dict[str, Any]) -> dict[str, Any]:
    if thank_you_page.get("url"):
        return {"kind": "url", "url": thank_you_page["url"]}
    if thank_you_page.get("page_id"):
        return {"kind": "page", "page_id": thank_you_page["page_id"], "step_id": "thank_you"}
    raise FunnelError("post_checkout.thank_you_page is not configured.")
