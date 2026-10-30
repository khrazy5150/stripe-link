"""Pure lookups over Site documents.

Lives in `domain` rather than `runtime.publishing`, where it grew up, because it is a walk over a repository
and a dict -- it renders nothing. Keeping it in the publishing runtime meant that any handler wanting to ask
"which Site owns this page?" imported the whole renderer, which costs cold-start time and, because the
app_config grant test follows the import graph, an IAM grant for a table the handler never reads.
`runtime.publishing` re-exports it, so every existing import site is unchanged.
"""
from typing import Any


def site_for_page(sites_repository: Any, tenant_id: str, page_id: str, *,
                  consistent: bool = False) -> dict[str, Any] | None:
    """Resolve the Site that owns `page_id` (plans/SITE_OBJECT.md §2.2). A page belongs to at most one Site,
    so the first match is authoritative. None means the page is attached to no Site.

    STRICT: a table that cannot be read raises. Callers that must distinguish "attached to nothing" from "I
    could not find out" need that difference — for commerce eligibility the two answers are opposite
    verdicts, and collapsing them turns a missing IAM grant into a refusal of every legitimate checkout
    (plans/COMMERCE_ELIGIBILITY.md). Use `find_site_for_page` where a failed lookup should simply mean "no
    Site".
    """
    if sites_repository is None or not tenant_id or not page_id:
        return None
    # The keyword is passed ONLY when it is asked for, so every repository and test double that predates
    # it keeps working untouched -- and the retry in `find_site_for_page` has something different to try.
    rows = (sites_repository.list_for_tenant(tenant_id, consistent=True) if consistent
            else sites_repository.list_for_tenant(tenant_id))
    for site in rows:
        for entry in (site.get("pages") or {}).values():
            if isinstance(entry, dict) and entry.get("page_id") == page_id:
                return site
    return None


def find_site_for_page(sites_repository: Any, tenant_id: str, page_id: str, *,
                       consistent: bool = False) -> dict[str, Any] | None:
    """`site_for_page`, best-effort: returns None when there's no Site yet (legacy pages) AND when the lookup
    fails — the renderer then falls back to its interim identity. Never raises: identity resolution must not
    block a publish."""
    try:
        return site_for_page(sites_repository, tenant_id, page_id, consistent=consistent)
    except TypeError:
        # A repository (or test double) whose list_for_tenant predates `consistent`. The lookup matters
        # more than the guarantee, so fall back rather than losing the Site entirely -- which would
        # publish the page with its interim identity and no Organization graph.
        return site_for_page(sites_repository, tenant_id, page_id)
    except Exception:
        return None
