"""Pure lookups over Site documents.

Lives in `domain` rather than `runtime.publishing`, where it grew up, because it is a walk over a repository
and a dict -- it renders nothing. Keeping it in the publishing runtime meant that any handler wanting to ask
"which Site owns this page?" imported the whole renderer, which costs cold-start time and, because the
app_config grant test follows the import graph, an IAM grant for a table the handler never reads.
`runtime.publishing` re-exports it, so every existing import site is unchanged.
"""
import re
from typing import Any

# THE site_id contract, in one place. It was written out five times across `domain/documents.py` and
# `handlers/sites.py`, and a sixth was about to be added for the per-Site shipping override. A pattern
# copied per caller is a rule that can be relaxed in one of them without anyone noticing.
SITE_ID_PATTERN = r"^site_[A-Za-z0-9]+$"
SITE_ID_RE = re.compile(SITE_ID_PATTERN)


def is_site_id(value: Any) -> bool:
    """True for a well-formed site_id. The one question every caller was asking with its own regex."""
    return bool(SITE_ID_RE.match(str(value or "")))


def site_for_page(sites_repository: Any, tenant_id: str, page_id: str, *,
                  consistent: bool = False, page: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Resolve the Site that owns `page_id` (plans/SITE_OBJECT.md §2.2). A page belongs to at most one Site,
    so the first match is authoritative. None means the page is attached to no Site.

    Pass `page` when the caller already holds the page document: its `site_id` reverse edge answers in ONE
    keyed read instead of listing every Site the tenant has
    (plans/SITE_AS_BUSINESS_IDENTITY.md §3.1). The scan below remains the fallback and the authority — a
    page written before the edge existed, or one whose edge went stale because a reconcile failed, still
    resolves correctly. `Site.pages` is the source of truth; `page.site_id` is a cache of it.

    A `site_id` that resolves to NOTHING falls through to the scan rather than returning None: a dangling
    edge must not be able to detach a page that a Site still routes.

    STRICT: a table that cannot be read raises. Callers that must distinguish "attached to nothing" from "I
    could not find out" need that difference — for commerce eligibility the two answers are opposite
    verdicts, and collapsing them turns a missing IAM grant into a refusal of every legitimate checkout
    (plans/COMMERCE_ELIGIBILITY.md). Use `find_site_for_page` where a failed lookup should simply mean "no
    Site".
    """
    if sites_repository is None or not tenant_id or not page_id:
        return None
    hinted = str((page or {}).get("site_id") or "").strip()
    if hinted:
        try:
            direct = sites_repository.get(tenant_id, hinted)
        except Exception:  # noqa: BLE001 - the scan below is the authority; a failed shortcut is not fatal
            direct = None
        if direct:
            return direct
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
                       consistent: bool = False, page: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """`site_for_page`, best-effort: returns None when there's no Site yet (legacy pages) AND when the lookup
    fails — the renderer then falls back to its interim identity. Never raises: identity resolution must not
    block a publish."""
    try:
        return site_for_page(sites_repository, tenant_id, page_id, consistent=consistent, page=page)
    except TypeError:
        # A repository (or test double) whose list_for_tenant predates `consistent`. The lookup matters
        # more than the guarantee, so fall back rather than losing the Site entirely -- which would
        # publish the page with its interim identity and no Organization graph.
        return site_for_page(sites_repository, tenant_id, page_id)
    except Exception:
        return None
