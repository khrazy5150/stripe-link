"""Collections CRUD (plans/SITE_COLLECTIONS.md, P1). Tenant-scoped: a Collection is an ordered, curated group of
a Site's landing pages with its own presentation — a reusable page section (collection-embed) that the Site may
also route at a path. Pure data: a Collection is URL-unaware (routability lives in the Site routing table, not
here). Members are page references derived by `rule` (manual/all/category) — the publisher resolves them against
the Site route map so a card only ever links to a real, navigable Site page."""
import secrets
import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_collection
from stripe_link.entitlement_gate import require_capability
from stripe_link.repositories.documents import RepositoryError, collections_repository

_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SCHEMA_VERSION = "2026-07-31"


def _new_collection_id() -> str:
    return "coll_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def handler(event, context, repository=None, tenant_repo=None):
    repository = repository or collections_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    collection_id = path_params(event).get("collection_id")
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        gate = require_capability(event, "collections", tenant_repo)
        if gate is not None:
            return gate
        return upsert_collection(event, repository)
    if method == "GET":
        if collection_id:
            return get_collection(event, repository, collection_id)
        return list_collections(event, repository)
    if method == "DELETE" and collection_id:
        return delete_collection(event, repository, collection_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def upsert_collection(event, repository):
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
        return json_response({"collection": saved}, status_code=201)
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


def delete_collection(event, repository, collection_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, collection_id)
    if not deleted:
        return error_response("Collection not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, "collection": deleted})
