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


def variant_of_running_experiment(page_id: str, experiments: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The running experiment this page is a NON-CONTROL variant of, or None.

    The mirror image of `running_experiment_for`, and deliberately a DIFFERENT question. That one asks "is
    this page the one under test?" and is matched on `control_page_id`; the answer drives artifact swapping
    at the edge. This one asks "is this page an alternative rendering that has ALSO been given a public URL
    of its own?" and the answer drives indexing.

    Conflating the two is what a noindex bug looks like. An experiment runs at the CONTROL's URL -- same
    address, no redirect, only the origin artifact varies -- so that URL keeps the ranking signals the test
    exists to improve, and must never be made noindex. The risk is at the other end: a variant that someone
    attached to its own slug is a second public URL serving near-identical content. That is the URL to keep
    out of the index, and the control is excluded here for exactly that reason.

    The control appears in `variants` too (with key "control"), so excluding it is not incidental.
    """
    page_id = str(page_id or "")
    if not page_id:
        return None
    for experiment in experiments or []:
        if str(experiment.get("status") or "") != RUNNING:
            continue
        if str(experiment.get("control_page_id") or "") == page_id:
            continue
        for variant in experiment.get("variants") or []:
            if str(variant.get("page_id") or "") == page_id:
                return experiment
    return None


def repoint_to_winner(site: dict[str, Any] | None, control_page_id: str, winner_page_id: str):
    """Move the tested slug from the control to the winner. Returns `(pages, slug)`; slug is "" when there
    was nothing to move.

    The ROUTE is the durable identity and the page behind it is swappable (plans/AB_TESTING.md). Promotion
    is therefore one field, not a content copy: copying the winner's sections into the tested page would
    attach the winner's measured performance to the loser's page_id and falsify the record, and past orders
    legitimately carry the old page_id because the page genuinely changed.

    Deliberately NOT `_attach_page_to_site`, whose contract is to displace the slug's previous occupant to a
    slug of its own so it stays reachable. That is right for attaching and wrong here: it would hand the
    LOSER a public URL at the moment it lost. The loser becomes unrouted, which is the point — its artifact
    keeps a canonical pointing at a URL that now serves the winner, harmless because nothing serves it, and
    a useful record of what lost.

    Slug-level fields (page_type, label, enabled, funnel_role) describe the ADDRESS and stay. Page-derived
    ones (offer_id, category, composition) describe whatever page is behind it and are dropped rather than
    carried over from the loser; publishing re-denormalizes them.
    """
    pages = dict((site or {}).get("pages") or {})
    control_page_id = str(control_page_id or "")
    winner_page_id = str(winner_page_id or "")
    if not control_page_id or not winner_page_id or control_page_id == winner_page_id:
        return pages, ""

    slug = ""
    for candidate, entry in pages.items():
        if isinstance(entry, dict) and str(entry.get("page_id") or "") == control_page_id:
            slug = candidate
            break
    if not slug:
        return pages, ""

    # A variant should hold no slug of its own while it is being tested (Option A), but if one exists, drop
    # it rather than leave the same page routable at two addresses.
    for candidate in [
        c for c, e in list(pages.items())
        if isinstance(e, dict) and str(e.get("page_id") or "") == winner_page_id and c != slug
    ]:
        pages.pop(candidate)

    entry = dict(pages[slug])
    entry["page_id"] = winner_page_id
    for page_derived in ("offer_id", "category", "composition"):
        entry.pop(page_derived, None)
    pages[slug] = entry
    return pages, slug


def experiment_route_block(
    experiment: dict[str, Any],
    artifact_url_for: Any,
    api_base: str = "",
    mode: str = "",
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
    #
    # The mode is IN the URL because the experiments table is mode-partitioned by key: the mode is baked
    # into the SK and GSI1PK, so a lookup made in the wrong mode does not return the wrong document, it
    # returns nothing. The view endpoint is called by an edge worker with no session to infer a mode from,
    # so the only party that knows it is the resolver that built this block. Without it every ping 404s and
    # every experiment reads zero views (found in QA 2026-09-21).
    if api_base:
        view_url = f"{api_base.rstrip('/')}/experiments/{experiment_id}/view"
        if mode:
            view_url = f"{view_url}?mode={mode}"
        block["view_url"] = view_url
    return block
