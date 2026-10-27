"""Collections CRUD (plans/SITE_COLLECTIONS.md, P1). Tenant-scoped: a Collection is an ordered, curated group of
a Site's landing pages with its own presentation — a reusable page section (collection-embed) that the Site may
also route at a path. Pure data: a Collection is URL-unaware (routability lives in the Site routing table, not
here). Members are page references derived by `rule` (manual/all/category) — the publisher resolves them against
the Site route map so a card only ever links to a real, navigable Site page."""
import secrets
import time

import logging
from typing import Any

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_collection
from stripe_link.entitlement_gate import require_capability
from stripe_link.repositories.documents import RepositoryError, collections_repository, pages_repository

logger = logging.getLogger(__name__)

_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SCHEMA_VERSION = "2026-07-31"


def _new_collection_id() -> str:
    return "coll_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def handler(event, context, repository=None, tenant_repo=None, pages_repo=None):
    repository = repository or collections_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    collection_id = path_params(event).get("collection_id")
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        gate = require_capability(event, "collections", tenant_repo)
        if gate is not None:
            return gate
        return upsert_collection(event, repository, pages_repo)
    if method == "GET":
        if collection_id:
            return get_collection(event, repository, collection_id)
        return list_collections(event, repository)
    if method == "DELETE" and collection_id:
        return delete_collection(event, repository, collection_id, pages_repo)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def pages_embedding_collection(pages_repository: Any, tenant_id: str, collection_id: str) -> list[str]:
    """The PUBLISHED page_ids whose sections embed this collection — the pages whose artifacts go stale
    the moment it changes (plans/ROUNDUP_PAGES.md §5).

    Lives here rather than in `runtime/publishing.py`, where it conceptually belongs, because importing
    that module drags in the whole publish surface: the grant tests then require this function to be
    given three further tables and a bucket it never touches. It has one caller, twenty lines below.

    (Those tests read the SOURCE, comments included, so naming the constants here would re-trigger them
    even though nothing imports them -- which is exactly what the first draft of this docstring did.)

    The cascade ran one way only. `cascade_publish_collection_drafts` fires when the EMBEDDING PAGE
    publishes and publishes that page's draft members; nothing ran when the Collection itself changed. So
    a tenant adding three products in February left every already-published artifact — and anything
    derived from the member list, such as a counted headline — exactly as it was in October. Artifacts are
    pre-rendered and served from the CDN, so none of this can be computed at request time.

    DRAFTS ARE SKIPPED. A draft has no artifact to go stale, and it will resolve the collection fresh
    whenever it does publish. Re-putting one would spend a write to change nothing a visitor can see.
    """
    collection_id = str(collection_id or "").strip()
    if not pages_repository or not collection_id:
        return []
    page_ids: list[str] = []
    seen: set[str] = set()
    for page in pages_repository.list_for_tenant(tenant_id) or []:
        if not isinstance(page, dict) or str(page.get("status") or "") != "published":
            continue
        page_id = str(page.get("page_id") or "")
        if not page_id or page_id in seen:
            continue
        if any(isinstance(section, dict) and section.get("type") == "catalog_grid"
               and str(section.get("collection_id") or "") == collection_id
               for section in (page.get("sections") or [])):
            seen.add(page_id)
            page_ids.append(page_id)
    return page_ids


def _republish_embedding_pages(tenant_id: str, collection_id: str, mode: str,
                               pages_repo=None) -> list[str]:
    """Re-render the published pages that embed this Collection (plans/ROUNDUP_PAGES.md §5).

    The cascade used to run one way only: publishing a page published that page's draft members, and
    nothing happened when the Collection itself changed. A tenant adding products in February left every
    already-published artifact exactly as it was — the grid, and anything derived from the member list
    such as a counted headline. Artifacts are pre-rendered and served from the CDN, so there is no
    render-time escape hatch; something has to re-put the page.

    IT TERMINATES. Re-putting a page fires the publish stream, which runs
    `cascade_publish_collection_drafts` and may write that page's DRAFT members. No step in the publish
    path writes a Collection — `backfill_page_collections` does, but it is a one-off migration script and
    is never called from publish — so this cascade cannot re-trigger itself.

    BEST-EFFORT, PER PAGE. The Collection write has already succeeded and the tenant's edit is saved; a
    page that fails to re-render must not turn that into an error they cannot act on, and must not stop
    the other pages re-rendering either.

    The re-put is written out here rather than imported from `handlers.sites._republish_page`, which does
    the same three lines. Importing it makes this function statically reach everything that module
    reaches -- Stripe keys, user profiles, Cloudflare credentials, six further tables -- and the grant
    tests say so, correctly: the function would have to be given all of it to deploy. Three lines of
    duplication is the cheaper side of that trade. This needs one table, and now reaches exactly one.
    """
    republished: list[str] = []
    try:
        pages_repo = pages_repo or pages_repository(mode=mode)
        page_ids = pages_embedding_collection(pages_repo, tenant_id, collection_id)
    except Exception:  # noqa: BLE001 - the edit is saved; discovering its readers is the best-effort half
        logger.exception("collections: could not find pages embedding %s", collection_id)
        return republished
    now = int(time.time())
    for page_id in page_ids:
        try:
            page = pages_repo.get(tenant_id, page_id)
            if page:
                page["updated_at"] = now
                pages_repo.put(page)       # a MODIFY fires page_publish, which re-renders the artifact
                republished.append(page_id)
        except Exception:  # noqa: BLE001
            logger.exception("collections: re-publish of %s after %s changed failed", page_id, collection_id)
    return republished


def upsert_collection(event, repository, pages_repo=None):
    try:
        document = parse_json_body(event)
        if not isinstance(document, dict):
            return error_response("Collection body must be an object.", code="invalid_collection")
        document["document_type"] = "collection"
        document.setdefault("schema_version", SCHEMA_VERSION)
        document.setdefault("tenant_id", tenant_id_from_event(event, document))
        if not str(document.get("collection_id") or "").strip():
            document["collection_id"] = _new_collection_id()
        document.setdefault("rule", "manual")
        now = int(time.time())
        document.setdefault("created_at", now)
        document["updated_at"] = now
        validate_collection(document)
        saved = repository.put(document)
        # The readers go stale the moment this is written: their grids, and anything derived from the
        # member list. Re-rendered AFTER the put so a page can never be published from a version of the
        # Collection that failed to save.
        republished = _republish_embedding_pages(
            str(document.get("tenant_id") or ""), str(document.get("collection_id") or ""),
            resolve_stripe_mode(event), pages_repo)
        return json_response({"collection": saved, "republished": republished}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_collection")


def get_collection(event, repository, collection_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    collection = repository.get(tenant_id, collection_id)
    if not collection:
        return error_response("Collection not found.", status_code=404, code="not_found")
    return json_response({"collection": collection})


def list_collections(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    collections = repository.list_for_tenant(tenant_id)
    site_id = str(query_params(event).get("site_id") or "").strip()
    if site_id:
        collections = [c for c in collections if str(c.get("site_id") or "") == site_id]
    return json_response({"collections": collections})


def delete_collection(event, repository, collection_id, pages_repo=None):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, collection_id)
    if not deleted:
        return error_response("Collection not found.", status_code=404, code="not_found")
    # A deleted Collection leaves its readers rendering a grid that resolves to nothing. They need the
    # re-render at least as much as an edited one does — arguably more, since the page is now wrong
    # rather than merely out of date.
    republished = _republish_embedding_pages(
        tenant_id, collection_id, resolve_stripe_mode(event), pages_repo)
    return json_response({"deleted": True, "collection": deleted, "republished": republished})
