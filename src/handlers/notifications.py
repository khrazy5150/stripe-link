import time
from typing import Callable

from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_notification, validate_refund_request
from stripe_link.repositories.documents import (
    RepositoryError,
    notifications_repository,
    refund_requests_repository,
)


def handler(event, context, notifications_repo=None, refund_requests_repo=None, now_fn: Callable[[], int] = lambda: int(time.time())):
    notifications_repo = notifications_repo or notifications_repository()
    refund_requests_repo = refund_requests_repo or refund_requests_repository()
    method = (event or {}).get("httpMethod", "").upper()
    resource = (event or {}).get("resource") or ""
    path = (event or {}).get("path") or ""
    is_refund_request = resource.endswith("/refund-requests") or path.endswith("/refund-requests")
    is_mark_read = resource.endswith("/mark-read") or path.rstrip("/").endswith("/mark-read")

    if method == "OPTIONS":
        return json_response({})
    if is_mark_read:
        if method == "POST":
            return mark_notifications_read(event, notifications_repo, now_fn)
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
    if is_refund_request:
        if method in {"POST", "PUT"}:
            return save_refund_request(event, refund_requests_repo)
        if method == "GET":
            return list_refund_requests(event, refund_requests_repo)
    if method in {"POST", "PUT"}:
        return save_notification(event, notifications_repo)
    if method == "GET":
        return list_notifications(event, notifications_repo)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def mark_notifications_read(event, repository, now_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        now = int(now_fn())
        marked = 0
        for notification in repository.list_for_tenant(tenant_id):
            if notification.get("status") == "unread":
                notification["status"] = "read"
                notification["read_at"] = now
                repository.put(notification)
                marked += 1
        return json_response({"marked": marked})
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")


def save_notification(event, repository):
    try:
        document = parse_json_body(event)
        validate_notification(document)
        saved = repository.put(document)
        return json_response({"notification": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_notification")


def save_refund_request(event, repository):
    try:
        document = parse_json_body(event)
        validate_refund_request(document)
        saved = repository.put(document)
        return json_response({"refund_request": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_refund_request")


def list_notifications(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    notifications = repository.list_for_tenant(tenant_id)
    notifications.sort(key=lambda item: (item.get("created_at", 0), item.get("sort_priority", 0)), reverse=True)
    return json_response({"notifications": notifications})


def list_refund_requests(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    requests = repository.list_for_tenant(tenant_id)
    requests = filter_refund_requests(requests, params)
    requests.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return json_response({"refund_requests": requests, "count": len(requests)})


def filter_refund_requests(requests, params):
    status = str(params.get("status") or "").strip()
    risk_level = str(params.get("risk_level") or "").strip()
    customer = str(params.get("customer") or "").strip().lower()
    page_or_offer = str(params.get("page_or_offer") or "").strip()
    order_id = str(params.get("order_id") or "").strip()
    start_date = _int_param(params.get("start_at"))
    end_date = _int_param(params.get("end_at"))

    filtered = []
    for request in requests:
        customer_doc = request.get("customer") or {}
        haystack = f"{customer_doc.get('name', '')} {customer_doc.get('email', '')}".lower()
        created_at = int(request.get("created_at") or 0)
        if status and request.get("status") != status:
            continue
        if risk_level and request.get("risk_level") != risk_level:
            continue
        if customer and customer not in haystack:
            continue
        if page_or_offer and page_or_offer not in {request.get("page_id"), request.get("offer_id")}:
            continue
        if order_id and request.get("order_id") != order_id:
            continue
        if start_date is not None and created_at < start_date:
            continue
        if end_date is not None and created_at > end_date:
            continue
        filtered.append(request)
    return filtered


def _int_param(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
