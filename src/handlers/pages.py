from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.ids import generate_short_url_code
from stripe_link.repositories.documents import RepositoryError, pages_repository


def handler(event, context, repository=None):
    repository = repository or pages_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return create_page(event, repository)
    if method == "GET":
        page_id = path_params(event).get("page_id")
        if page_id:
            return get_page(event, repository, page_id)
        return list_pages(event, repository)
    if method == "DELETE":
        page_id = path_params(event).get("page_id")
        if not page_id:
            return error_response("page_id is required.", code="missing_page")
        return delete_page(event, repository, page_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_page(event, repository):
    try:
        document = parse_json_body(event)
        existing = existing_page_for_document(repository, document)
        assign_short_code(existing, document)
        validate_published_page_mutation(existing, document)
        validate_page_document(document)
        saved = repository.put(document)
        return json_response({"page": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_page")


def assign_short_code(existing: dict | None, document: dict, code_fn=generate_short_url_code) -> None:
    """Give the page a stable snowflake short_code for its shareable test links, assigned the FIRST time it is
    SAVED (any status) and sticky across every later edit (plans/SALES_FUNNELS.md Phase B). The code keys both
    test.juniorbay.com/preview/{code} (draft) and /published/{code} (published); the publish stream turns it
    into a code->page route. Assigning on save (not just publish) means a never-published draft already has a
    working preview link.

    Sticky, so re-publish / unpublish keep the same URL and lifecycle_only_change stays a no-op on it.
    """
    inherited = str((existing or {}).get("short_code") or "").strip()
    if inherited:
        document.setdefault("short_code", inherited)
        return
    if not str(document.get("short_code") or "").strip():
        # Snowflakes are unique by construction (time+worker+seq), so no registry collision check is needed.
        document["short_code"] = code_fn()


def existing_page_for_document(repository, document: dict):
    tenant_id = str(document.get("tenant_id") or "").strip()
    page_id = str(document.get("page_id") or "").strip()
    if not tenant_id or not page_id:
        return None
    return repository.get(tenant_id, page_id)


def validate_published_page_mutation(existing: dict | None, incoming: dict) -> None:
    if not existing or existing.get("status") != "published":
        return
    incoming_status = incoming.get("status") or existing.get("status")
    if incoming_status in {"draft", "archived"} and lifecycle_only_change(existing, incoming):
        return
    raise DocumentValidationError("Published pages cannot be modified. Unpublish this page before editing.")


def lifecycle_only_change(existing: dict, incoming: dict) -> bool:
    # short_code is a system-assigned sticky field (the shareable-link id), not user content, so a
    # publish->draft flip that only differs by it still counts as lifecycle-only.
    ignored = {"status", "published_at", "archived_at", "updated_at", "short_code", "PK", "SK", "GSI1PK", "GSI1SK"}
    return strip_lifecycle_fields(existing, ignored) == strip_lifecycle_fields(incoming, ignored)


def strip_lifecycle_fields(document: dict, ignored: set[str]) -> dict:
    return {
        key: value
        for key, value in document.items()
        if key not in ignored
    }


def get_page(event, repository, page_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page = repository.get(tenant_id, page_id)
    if not page:
        return error_response("Page not found.", status_code=404, code="not_found")
    return json_response({"page": page})


def list_pages(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    return json_response({"pages": repository.list_for_tenant(tenant_id)})


def delete_page(event, repository, page_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page = repository.get(tenant_id, page_id)
    if not page:
        return error_response("Page not found.", status_code=404, code="not_found")
    if page.get("status") == "published":
        return error_response(
            "Published pages must be archived before deletion.",
            status_code=409,
            code="published_page_requires_archive",
        )
    deleted = repository.delete(tenant_id, page_id)
    return json_response({"deleted": True, "page": deleted})
