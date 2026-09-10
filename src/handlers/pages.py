from decimal import Decimal

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.entitlement_gate import require_capability
from stripe_link.ids import generate_short_url_code
from stripe_link.domain.page_analytics import attach_summaries
from stripe_link.repositories.documents import RepositoryError, orders_repository, pages_repository


def handler(event, context, repository=None, tenant_repo=None):
    repository = repository or pages_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        gate = require_capability(event, "landing_pages", tenant_repo)
        if gate is not None:
            return gate
        return create_page(event, repository)
    if method == "GET":
        page_id = path_params(event).get("page_id")
        if page_id:
            return get_page(event, repository, page_id)
        return list_pages(event, repository, mode=resolve_stripe_mode(event))
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
    the {stage}-test.juniorbay.com viewer /preview/{code} (draft) and /published/{code} (published); the publish stream turns it
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
    return comparable(strip_lifecycle_fields(existing, ignored)) == comparable(
        strip_lifecycle_fields(incoming, ignored)
    )


def comparable(value):
    """Normalise numbers so a document compares equal to itself across the storage round trip.

    `existing` comes back from DynamoDB, where every number is a Decimal; `incoming` is JSON straight from
    the browser, where every number is a float. Decimal('0.563') != 0.563 -- the float is really
    0.5629999999999999449, so the two never match -- while Decimal('0.5') == 0.5 does, because 0.5 is exact
    in binary. Compared raw, an UNCHANGED page therefore looks edited whenever it carries a fraction that
    is not a negative power of two, and unpublishing it is refused as a modification.

    Image crop rects are the first fractions to reach these documents (they only became storable once
    dynamo_safe started converting floats to Decimal at the repository boundary), which is why a page with
    a cropped image could not be unpublished while every other page could.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


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


def list_pages(event, repository, orders_repo=None, mode="test"):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    pages = repository.list_for_tenant(tenant_id)
    # Conversions and revenue are DERIVED from paid orders, not counted -- the same fold the A/B results
    # use. `analytics_summary` has been read by the page cards since they were built and written by
    # nothing, so every card showed zeros. Best-effort: a listing must not fail because orders are
    # unreadable, and pages without numbers are exactly what the cards showed before.
    try:
        orders = (orders_repo or orders_repository(mode=mode)).list_for_tenant(tenant_id)
        attach_summaries(pages, orders)
    except Exception as exc:  # noqa: BLE001 - analytics are decoration on a listing, never its failure mode
        # Logged, not swallowed silently. A missing IAM grant fails exactly like "this tenant has no
        # orders", and an invisible AccessDenied is how the favicon bug survived a deploy.
        print(f"page analytics unavailable for {tenant_id}: {type(exc).__name__}: {exc}")
    return json_response({"pages": pages})


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
