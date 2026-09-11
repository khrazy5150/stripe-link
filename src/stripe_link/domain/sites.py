"""Pure lookups over Site documents.

Lives in `domain` rather than `runtime.publishing`, where it grew up, because it is a walk over a repository
and a dict -- it renders nothing. Keeping it in the publishing runtime meant that any handler wanting to ask
"which Site owns this page?" imported the whole renderer, which costs cold-start time and, because the
app_config grant test follows the import graph, an IAM grant for a table the handler never reads.
`runtime.publishing` re-exports it, so every existing import site is unchanged.
"""
from typing import Any


def find_site_for_page(sites_repository: Any, tenant_id: str, page_id: str) -> dict[str, Any] | None:
    """Resolve the Site that owns `page_id` (plans/SITE_OBJECT.md §2.2). A page belongs to at most one Site,
    so the first match is authoritative. Returns None when there's no Site yet (legacy pages) — the renderer
    then falls back to its interim identity. Never raises: identity resolution must not block a publish."""
    if sites_repository is None or not tenant_id or not page_id:
        return None
    try:
        for site in sites_repository.list_for_tenant(tenant_id):
            for entry in (site.get("pages") or {}).values():
                if isinstance(entry, dict) and entry.get("page_id") == page_id:
                    return site
    except Exception:
        return None
    return None
