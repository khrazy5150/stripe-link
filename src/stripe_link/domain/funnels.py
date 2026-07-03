from typing import Any


class FunnelError(ValueError):
    pass


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
