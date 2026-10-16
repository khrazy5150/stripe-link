"""Reviews CRUD + moderation (plans/REVIEWS.md, Phase 1). Tenant-authed: the dashboard adds real reviews and
moderates them. Public customer submission (Leads-style abuse gate) is Phase 2. Only approved, non-GBP
reviews render / feed AggregateRating markup — enforced at the render layer, not here."""
import secrets
import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.abuse_reports import (
    REVIEW_REPORT_REASONS,
    ReportValidationError,
    build_review_report,
)
from stripe_link.domain.documents import DocumentValidationError, REVIEW_STATUSES, validate_review
from stripe_link.entitlement_gate import require_capability
from stripe_link.repositories.documents import (
    RepositoryError,
    abuse_reports_repository,
    reviews_repository,
)

_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SCHEMA_VERSION = "2026-07-23"


def _new_review_id() -> str:
    return "review_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def handler(event, context, repository=None, tenant_repo=None, reports_repo=None):
    repository = repository or reviews_repository()
    method = (event or {}).get("httpMethod", "").upper()
    resource = (event or {}).get("resource") or ""
    review_id = path_params(event).get("review_id")
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        # Folded onto this route rather than given one of its own: the stack is at CloudFormation's 1MB
        # transform limit and a new route fails the deploy outright (proved 2026-10-05).
        try:
            body = parse_json_body(event)
        except ValueError as exc:
            return error_response(str(exc), code="invalid_request")
        if str(body.get("action") or "").strip() == "report":
            # BEFORE the entitlement gate, deliberately. A tenant whose plan no longer includes reviews
            # still has live reviews on live pages; taking away their only way to flag a doxxed phone
            # number because of a billing tier would be the worst possible moment to enforce one.
            return report_review(event, repository, body, reports_repo=reports_repo)
        gate = require_capability(event, "reviews", tenant_repo)
        if gate is not None:
            return gate
        return create_review(event, repository, body)
    if method == "PATCH" and review_id and resource.endswith("/status"):
        return moderate_review(event, repository, review_id)
    if method == "GET":
        if review_id:
            return get_review(event, repository, review_id)
        return list_reviews(event, repository)
    if method == "DELETE" and review_id:
        return delete_review(event, repository, review_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_review(event, repository, document=None):
    try:
        document = parse_json_body(event) if document is None else dict(document)
        if not isinstance(document, dict):
            return error_response("Review body must be an object.", code="invalid_review")
        document["document_type"] = "review"
        document.setdefault("schema_version", SCHEMA_VERSION)
        document.setdefault("tenant_id", tenant_id_from_event(event, document))
        if not str(document.get("review_id") or "").strip():
            document["review_id"] = _new_review_id()
        document.setdefault("source", "manual")
        document.setdefault("status", "pending")
        now = int(time.time())
        document.setdefault("created_at", now)
        document["updated_at"] = now
        validate_review(document)
        saved = repository.put(document)
        return json_response({"review": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_review")



def report_review(event, repository, body, reports_repo=None, now=None):
    """A tenant tells the platform something is wrong with one of their reviews.

    This is the ONLY lever a tenant has over a review (plans/REVIEWS.md "Review integrity"). They cannot
    approve, reject, hold or delete one, and filing this does not change the review in any way -- it stays
    published until a platform admin decides otherwise, in [[ADMIN_SITE]] §1b.

    **The rule that makes the queue honest is that a report never hides the review**, and it is kept here by
    not having the code to break it: nothing in this function writes to the reviews repository. If flagging
    pulled a review down pending a decision, tenants would flag every two-star review and recover curation
    with a delay -- the promise laundered through the platform's own queue.

    Filed through the AUTHENTICATED route rather than the public `POST /report` the plan first suggested.
    Same table, different door: the public endpoint cannot say which tenant filed a report, and "how many
    reports name this tenant" is the question §1b exists to ask. A tenant reporting every two-star review
    has to be visible, and that is only possible if the reporter is verified.
    """
    tenant_id = tenant_id_from_event(event, body)
    review_id = str(body.get("review_id") or "").strip()
    if not review_id:
        return error_response("review_id is required.", code="missing_review")

    review = repository.get(tenant_id, review_id)
    if not review:
        # A tenant may only report reviews on their OWN products. Scoping the lookup to the caller's tenant
        # means a report against a competitor's review is indistinguishable from one against a review that
        # does not exist, which is the right answer to both.
        return error_response("That review could not be found.", status_code=404, code="not_found")

    try:
        report = build_review_report(
            body,
            review=review,
            reported_by=tenant_id,
            source_ip=((event or {}).get("requestContext") or {}).get("identity", {}).get("sourceIp", ""),
            now=now,
        )
    except ReportValidationError as exc:
        return error_response(str(exc), code="invalid_report")

    try:
        (reports_repo or abuse_reports_repository()).put(report)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    # The review is returned UNCHANGED, so the screen can say so plainly rather than implying something
    # happened to it.
    return json_response({"reported": True, "review": review}, status_code=201)

def moderate_review(event, repository, review_id):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")
    status = str(body.get("status") or "").strip()
    if status not in REVIEW_STATUSES:
        return error_response("status must be one of: pending, approved, rejected.", code="invalid_status")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    review = repository.get(tenant_id, review_id)
    if not review:
        return error_response("Review not found.", status_code=404, code="not_found")
    review["status"] = status
    review["updated_at"] = int(time.time())
    try:
        validate_review(review)
        return json_response({"review": repository.put(review)})
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_review")


def get_review(event, repository, review_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    review = repository.get(tenant_id, review_id)
    if not review:
        return error_response("Review not found.", status_code=404, code="not_found")
    return json_response({"review": review})


def list_reviews(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    reviews = repository.list_for_tenant(tenant_id)
    params = query_params(event)
    target_id = str(params.get("target_id") or "").strip()
    status = str(params.get("status") or "").strip()
    if target_id:
        reviews = [r for r in reviews if str((r.get("target") or {}).get("id") or "") == target_id]
    if status:
        reviews = [r for r in reviews if r.get("status") == status]
    # The report reasons ride along on the list the screen already fetches, rather than on a route of their
    # own -- the stack has no transform budget for one. The screen therefore offers exactly the reasons the
    # validator accepts, which is how "low rating" stays off a form a tenant reads.
    return json_response({
        "reviews": reviews,
        "report_reasons": [{"value": k, "label": v} for k, v in REVIEW_REPORT_REASONS.items()],
    })


def delete_review(event, repository, review_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, review_id)
    if not deleted:
        return error_response("Review not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, "review": deleted})
