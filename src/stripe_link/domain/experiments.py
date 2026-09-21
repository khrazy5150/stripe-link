"""Which experiment, if any, is running on a page — and what the edge needs to run it.

Pure. The split matters (plans/AB_TESTING.md): the SERVER says what an experiment IS, because that is the
same for every visitor and therefore cacheable; the EDGE decides who gets which variant, because that is
per-request and must never be cached. The Worker caches resolve responses for 60 seconds, so an assignment
made here would hand every visitor in that window the same variant — a time-bucketed split rather than a
random one, which on low traffic gives one variant nearly everything.
"""
from typing import Any

RUNNING = "running"

# The short-code entry point is DISABLED, not dismantled (plans/AB_TESTING.md A1c).
#
# It was right in stripe-cart, where the short URL WAS the published page. Here a page lives on the
# tenant's own domain, so entering an experiment only through go.jbay.uk/{code} BIASES it: organic traffic
# to the real URL never enters the test, and what gets measured is the slice deliberately routed through
# the link. Assignment now happens at the edge, on the page's own URL.
#
# The code stays because there is no cost to keeping it and a real cost to a half-removal, but nothing may
# route to it: two live assignment paths would roll separately and set separate cookies, and that drift is
# invisible until the numbers look wrong. Flip this to re-enable, and re-read that sentence first.
SHORT_CODE_ENTRY_ENABLED = False


def running_experiment_for(page_id: str, experiments: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The running experiment whose CONTROL is this page, or None.

    Matched on the control page because that is the page with a route — the one a visitor actually asks
    for. Variants have no route of their own while an experiment runs, which is what keeps them out of the
    index and makes promoting a winner a matter of moving the route.

    Only `running` counts. Draft, paused and completed experiments serve the control, which is what the
    URL already does, so they need no edge behaviour at all.
    """
    page_id = str(page_id or "")
    if not page_id:
        return None
    for experiment in experiments or []:
        if str(experiment.get("status") or "") != RUNNING:
            continue
        if str(experiment.get("control_page_id") or "") == page_id:
            return experiment
    return None


def experiment_route_block(
    experiment: dict[str, Any],
    artifact_url_for: Any,
    api_base: str = "",
) -> dict[str, Any]:
    """What the edge needs to assign a visitor, and nothing more.

    `artifact_url_for(page_id)` resolves a variant's published artifact. A variant whose artifact cannot be
    resolved is DROPPED rather than sent with a broken URL: the edge would proxy a 404 to a real visitor,
    and losing one arm of a test is better than serving nobody a page.

    Weights are normalised to non-negative integers here so the edge can roll without re-validating. If
    every weight is zero or nothing survives, an empty variant list is returned and the caller omits the
    block entirely — the control keeps serving, which is exactly what should happen.
    """
    variants = []
    for variant in experiment.get("variants") or []:
        page_id = str(variant.get("page_id") or "")
        if not page_id:
            continue
        origin_url = artifact_url_for(page_id)
        if not origin_url:
            continue
        try:
            weight = max(0, int(variant.get("weight") or 0))
        except (TypeError, ValueError):
            weight = 0
        variants.append({
            "page_id": page_id,
            "weight": weight,
            "origin_url": origin_url,
        })
    if not variants or not any(variant["weight"] for variant in variants):
        return {}
    experiment_id = str(experiment.get("experiment_id") or "")
    block = {
        "experiment_id": experiment_id,
        # The cookie pins a visitor to one variant across refreshes. Named per experiment so two running at
        # once on different pages cannot overwrite each other's assignment.
        "cookie_name": str(experiment.get("cookie_name") or f"jb_ab_{experiment_id}"),
        "variants": variants,
    }
    # A fully-formed URL, so the edge never has to know an API base, a mode, or how an id is shaped. It
    # pings what it was given. Omitted when there is no base configured, and the edge simply does not count
    # -- a missing metric must never stop a page being served.
    if api_base:
        block["view_url"] = f"{api_base.rstrip('/')}/experiments/{experiment_id}/view"
    return block
