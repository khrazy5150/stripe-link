"""Public abuse reporting for platform-hosted pages.

plans/CREATOR_LINK_POLICY.md §6. The allowlist and the adult interstitial are preventive; this answers for
what gets through. "A registrar does not ask whether you have an interstitial. It asks what you do when
someone abuses the domain."

PUBLIC and unauthenticated, because the person best placed to report a page is a stranger who landed on it.
That makes it an abuse surface in its own right, so it is protected the way POST /leads is -- a honeypot and
hard payload caps -- plus the page being reported is resolved SERVER-SIDE from its id. A reporter who could
name the tenant could file reports against anyone.
"""
import os

from stripe_link.common import error_response, header_value, json_response, parse_json_body
from stripe_link.domain.abuse_reports import (
    REPORT_REASONS,
    ReportValidationError,
    build_abuse_report,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    abuse_reports_repository,
    pages_repository,
)


def handler(event, context, repository=None, pages_repo=None, now=None):
    event = event or {}
    method = str(event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "GET":
        # The form needs the reason list, and hard-coding it in the page would be a second copy to keep
        # in step with the validator.
        return json_response({"reasons": [{"value": k, "label": v} for k, v in REPORT_REASONS.items()]})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    try:
        payload = parse_json_body(event) or {}
    except ValueError:
        return error_response("Body must be JSON.", code="invalid_body")

    page_id = str(payload.get("page_id") or "").strip()
    if not page_id:
        return error_response("page_id is required.", code="missing_page")

    # Resolve the page to learn WHOSE it is. Never trust a reported tenant_id.
    #
    # BOTH mode partitions. Pages are stored per Stripe mode and `find_by_id` keys on a mode-scoped GSI1PK,
    # so an unscoped repository matches NEITHER -- which made this endpoint accept everything and record
    # nothing, silently, because an unresolvable page is deliberately answered like a real one. Found by
    # checking the table after a live POST rather than by trusting the 200 (2026-09-20).
    #
    # Trying both is safe: the mode only says where to look, and the tenant still comes from the page we
    # find. A reporter has no way to know or influence which partition their page lives in.
    try:
        page = _find_page(page_id, pages_repo)
    except RepositoryError:
        page = None
    if not page:
        # Deliberately the same answer as a page that exists: a probe must not be able to enumerate page ids.
        return json_response({"received": True})

    try:
        report = build_abuse_report(
            payload,
            page_id=page_id,
            tenant_id=str(page.get("tenant_id") or ""),
            host=str(header_value(event, "host") or ""),
            source_ip=_source_ip(event),
            user_agent=str(header_value(event, "user-agent") or ""),
            now=now,
        )
    except ReportValidationError as exc:
        if str(exc) == "__honeypot__":
            # Answer exactly as a real submission does. Telling a bot it was caught teaches it what to avoid.
            return json_response({"received": True})
        return error_response(str(exc), code="invalid_report")

    repository = repository or abuse_reports_repository()
    try:
        repository.put(report)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    # No report_id in the response: the reporter has nothing to do with it, and handing out ids invites
    # probing for other people's.
    return json_response({"received": True})


def _find_page(page_id, pages_repo=None):
    """The page, from whichever mode partition holds it."""
    if pages_repo is not None:
        return pages_repo.find_by_id(page_id)
    for mode in ("live", "test"):
        found = pages_repository(mode=mode).find_by_id(page_id)
        if found:
            return found
    return None


def _source_ip(event):
    identity = ((event or {}).get("requestContext") or {}).get("identity") or {}
    return str(identity.get("sourceIp") or "")
