"""Public booking API (resolve-style, like experiments_resolve / custom_domains_resolve).

Tenant is derived from the service, not an admin session. B.1 ships the availability endpoint;
resolve / reserve / checkout / manage land in later Phase B steps.
"""
import time

from stripe_link.common import error_response, json_response, path_params, query_params
from stripe_link.domain.scheduling import available_slots
from stripe_link.repositories.documents import (
    appointments_repository,
    availability_exceptions_repository,
    fulfillers_repository,
    services_repository,
    tenant_availability_repository,
)

DEFAULT_WINDOW_DAYS = 14


def handler(
    event,
    context,
    services_repo=None,
    availability_repo=None,
    fulfillers_repo=None,
    exceptions_repo=None,
    appointments_repo=None,
):
    services_repo = services_repo or services_repository()
    availability_repo = availability_repo or tenant_availability_repository()
    fulfillers_repo = fulfillers_repo or fulfillers_repository()
    exceptions_repo = exceptions_repo or availability_exceptions_repository()
    appointments_repo = appointments_repo or appointments_repository()
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")

    if method == "OPTIONS":
        return json_response({})
    if "/availability" in path and method == "GET":
        return availability_route(event, services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo)
    return error_response("Unsupported booking route.", status_code=404, code="not_found")


def availability_route(event, services_repo, availability_repo, fulfillers_repo, exceptions_repo, appointments_repo):
    service_id = path_params(event).get("service_id")
    if not service_id:
        return error_response("service_id is required.", code="missing_service_id")
    service = services_repo.find_by_id(service_id)
    if not service or service.get("active") is False:
        return error_response("Service not found.", status_code=404, code="not_found")

    tenant_id = str(service.get("tenant_id") or "")
    params = query_params(event)
    now = int(time.time())
    range_start = _epoch(params.get("from"), default=now)
    range_end = _epoch(params.get("to"), default=now + DEFAULT_WINDOW_DAYS * 86400)
    fulfiller_id = str(params.get("fulfiller_id") or "").strip() or None

    tenant_availability = availability_repo.get(tenant_id, "default") or {}
    fulfillers = fulfillers_repo.list_for_tenant(tenant_id)
    exceptions = exceptions_repo.list_for_tenant(tenant_id)
    appointments = appointments_repo.list_for_tenant(tenant_id)

    slots = available_slots(
        service,
        tenant_availability,
        fulfillers,
        exceptions,
        appointments,
        now_epoch=now,
        range_start_epoch=range_start,
        range_end_epoch=range_end,
        fulfiller_id=fulfiller_id,
    )
    return json_response({
        "service_id": service_id,
        "timezone": tenant_availability.get("timezone") or "UTC",
        "duration_minutes": int(service.get("duration_minutes") or 60),
        "slots": slots,
        "count": len(slots),
    })


def _epoch(value, *, default: int) -> int:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else default
