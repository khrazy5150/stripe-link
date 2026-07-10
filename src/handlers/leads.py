"""Lead capture API.

- POST /leads is PUBLIC (anonymous visitor on a published landing page). Tenant/offer are resolved
  server-side from the payload IDs, never from a client-supplied key. Protected by a honeypot + payload
  caps (rate limiting is a documented follow-up, plans/LEAD_CAPTURE.md §8).
- GET/PATCH paths are tenant-scoped like every other authenticated dashboard handler.

See plans/LEAD_CAPTURE.md.
"""
import secrets
import time
from typing import Callable

from stripe_link.common import (
    error_response,
    header_value,
    json_response,
    parse_json_body,
    path_params,
    query_params,
    tenant_id_from_event,
)
from stripe_link.domain.documents import DocumentValidationError, validate_lead_submission
from stripe_link.domain.leads import (
    LeadValidationError,
    build_consent,
    build_lead_submission,
    is_spam,
    lead_capture_fields,
    lead_id_for,
    lead_notification,
    validate_and_extract_fields,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    leads_repository,
    notifications_repository,
    offers_repository,
    products_repository,
)


def handler(
    event,
    context,
    *,
    leads_repo=None,
    offers_repo=None,
    products_repo=None,
    notifications_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    leads_repo = leads_repo or leads_repository()
    if method == "POST":
        return ingest_lead(
            event,
            leads_repo=leads_repo,
            offers_repo=offers_repo or offers_repository(),
            products_repo=products_repo or products_repository(),
            notifications_repo=notifications_repo,
            now=now_fn(),
        )
    if method == "GET":
        lead_id = path_params(event).get("lead_id")
        if lead_id:
            return get_lead(event, leads_repo, lead_id)
        return list_leads(event, leads_repo)
    if method == "PATCH":
        lead_id = path_params(event).get("lead_id")
        if not lead_id:
            return error_response("lead_id is required.", code="missing_lead")
        return update_lead_status(event, leads_repo, lead_id, now_fn())
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _request_context(event) -> dict:
    ctx = (event or {}).get("requestContext") or {}
    identity = ctx.get("identity") or {}
    return {
        "ip": str(identity.get("sourceIp") or "")[:64],
        "user_agent": str(header_value(event, "User-Agent") or "")[:512],
        "referer": str(header_value(event, "Referer") or header_value(event, "Referrer") or "")[:512],
    }


def ingest_lead(event, *, leads_repo, offers_repo, products_repo, notifications_repo, now):
    try:
        payload = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_lead")

    # Honeypot: silently accept-and-drop so bots get no signal that they were caught.
    if is_spam(payload):
        return json_response({"status": "accepted"}, status_code=202)

    tenant_id = str(payload.get("tenant_id") or "").strip()
    offer_id = str(payload.get("offer_id") or "").strip()
    page_id = str(payload.get("page_id") or "").strip()
    if not tenant_id or not offer_id:
        return error_response("tenant_id and offer_id are required.", code="invalid_lead")

    offer = offers_repo.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")

    products_by_id = {}
    for item in offer.get("items") or []:
        product_id = str((item or {}).get("product_id") or "").strip()
        if product_id and product_id not in products_by_id:
            product = products_repo.get(tenant_id, product_id)
            if product:
                products_by_id[product_id] = product

    declared = lead_capture_fields(offer, products_by_id)
    try:
        fields = validate_and_extract_fields(payload.get("fields") or {}, declared)
    except LeadValidationError as exc:
        return error_response(str(exc), code="invalid_lead")

    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    lead_id = lead_id_for(tenant_id, offer_id, idempotency_key, now=now, token=secrets.token_hex(8))

    # Request-level idempotency: a retried submit resolves to the same lead, returned without a rewrite.
    if idempotency_key:
        existing = leads_repo.get(tenant_id, lead_id)
        if existing:
            return json_response({"lead_id": lead_id, "status": "duplicate"}, status_code=200)

    context = _request_context(event)
    consent = build_consent(payload.get("consent"), ip=context["ip"], now=now, offer_id=offer_id)
    provenance = {**context, "submitted_at": int(now)}
    lead = build_lead_submission(
        tenant_id=tenant_id,
        lead_id=lead_id,
        offer_id=offer_id,
        page_id=page_id,
        fields=fields,
        consent=consent,
        provenance=provenance,
        idempotency_key=idempotency_key,
        now=now,
    )
    try:
        validate_lead_submission(lead)
        leads_repo.put(lead)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_lead")

    _emit_lead_notification(notifications_repo, lead, tenant_id, now)
    return json_response({"lead_id": lead_id, "status": "captured"}, status_code=201)


def _emit_lead_notification(notifications_repo, lead, tenant_id, now):
    import os

    repo = notifications_repo or (notifications_repository() if os.environ.get("NOTIFICATIONS_TABLE") else None)
    if not repo:
        return
    try:
        repo.put(lead_notification(lead, tenant_id, now))
    except Exception:  # noqa: BLE001 - a notification failure must never fail the capture
        pass


def list_leads(event, leads_repo):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    leads = leads_repo.list_for_tenant(tenant_id)
    params = query_params(event)
    offer_id = str(params.get("offer_id") or "").strip()
    status = str(params.get("status") or "").strip()
    if offer_id:
        leads = [lead for lead in leads if lead.get("offer_id") == offer_id]
    if status:
        leads = [lead for lead in leads if lead.get("status") == status]
    leads.sort(key=lambda lead: lead.get("created_at", 0), reverse=True)
    return json_response({"leads": leads, "count": len(leads)})


def get_lead(event, leads_repo, lead_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    lead = leads_repo.get(tenant_id, lead_id)
    if not lead:
        return error_response("Lead not found.", status_code=404, code="not_found")
    return json_response({"lead": lead})


def update_lead_status(event, leads_repo, lead_id, now):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_lead")
    status = str(body.get("status") or "").strip()
    if status not in {"new", "contacted", "qualified", "archived"}:
        return error_response("Lead status must be one of: new, contacted, qualified, archived.", code="invalid_lead")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    lead = leads_repo.get(tenant_id, lead_id)
    if not lead:
        return error_response("Lead not found.", status_code=404, code="not_found")
    lead["status"] = status
    lead["updated_at"] = int(now)
    try:
        saved = leads_repo.put(lead)
        return json_response({"lead": saved})
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_lead")
