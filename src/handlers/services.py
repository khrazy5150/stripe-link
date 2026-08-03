import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.appointments import AppointmentTransitionError, transition_appointment
from stripe_link.domain.entitlements import CAPABILITIES, is_entitled
from stripe_link.domain.service_pricing import normalize_service_pricing
from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_appointment,
    validate_availability_exception,
    validate_fulfiller,
    validate_service,
    validate_tenant_availability,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    availability_exceptions_repository,
    fulfillers_repository,
    services_repository,
    tenant_availability_repository,
    tenant_profiles_repository,
)


def _require_capability(event, capability, tenant_repo):
    """Gate a tenant-facing action on a plan capability (plans/SAAS_BILLING_PAYWALL.md). Reads the tenant's
    denormalized entitlements. Fails OPEN when the profile is absent or the lookup errors (never break an
    un-backfilled tenant); blocks only when a profile exists and lacks the capability."""
    try:
        body = parse_json_body(event) if (event or {}).get("body") else {}
    except ValueError:
        body = {}
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return None
    try:
        tenant = (tenant_repo or tenant_profiles_repository()).get(tenant_id, tenant_id)
    except RepositoryError:
        return None
    if tenant is None or is_entitled(tenant, capability):
        return None
    return error_response(
        f"Your plan does not include {CAPABILITIES[capability]['label']}. Upgrade to enable it.",
        status_code=403, code="plan_upgrade_required",
    )


def handler(
    event,
    context,
    services_repo=None,
    fulfillers_repo=None,
    availability_repo=None,
    exceptions_repo=None,
    appointments_repo=None,
    tenant_repo=None,
):
    # services + appointments carry per-mode Stripe state / are mode-specific transactions, so they are
    # mode-scoped; scheduling config (fulfillers/availability/exceptions) is mode-agnostic.
    mode = resolve_stripe_mode(event)
    services_repo = services_repo or services_repository(mode=mode)
    fulfillers_repo = fulfillers_repo or fulfillers_repository()
    availability_repo = availability_repo or tenant_availability_repository()
    exceptions_repo = exceptions_repo or availability_exceptions_repository()
    appointments_repo = appointments_repo or appointments_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")

    if method == "OPTIONS":
        return json_response({})
    if "/services/fulfillers" in path:
        return document_route(event, method, fulfillers_repo, "fulfiller", validate_fulfiller, "fulfillers")
    if "/services/availability/exceptions" in path:
        return document_route(event, method, exceptions_repo, "availability_exception", validate_availability_exception, "availability_exceptions", id_param="exception_id")
    if "/services/availability/defaults" in path:
        return default_availability_route(event, method, availability_repo)
    if "/services/appointments" in path:
        action = path_params(event).get("action")
        if action and method == "POST":
            return appointment_action_route(event, appointments_repo, action)
        return document_route(event, method, appointments_repo, "appointment", validate_appointment, "appointments", id_param="appointment_id")
    # Creating/editing a service = using the booking feature; gate it on the tenant's plan.
    if method in {"POST", "PUT"}:
        gate = _require_capability(event, "booking", tenant_repo)
        if gate is not None:
            return gate
    return document_route(event, method, services_repo, "service", validate_service, "services", id_param="service_id", normalizer=normalize_service_pricing)


def appointment_action_route(event, repository, action):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    appointment_id = path_params(event).get("appointment_id")
    appointment = repository.get(tenant_id, appointment_id) if appointment_id else None
    if not appointment:
        return error_response("Appointment not found.", status_code=404, code="not_found")
    try:
        body = parse_json_body(event) if (event or {}).get("body") else {}
    except ValueError:
        body = {}
    try:
        updated = transition_appointment(
            appointment,
            action,
            now_epoch=int(time.time()),
            assigned_fulfiller_id=body.get("assigned_fulfiller_id"),
        )
        saved = repository.put(updated)
        return json_response({"appointment": saved})
    except AppointmentTransitionError as exc:
        return error_response(str(exc), code="invalid_transition")
    except RepositoryError as exc:
        return error_response(str(exc), code="save_failed")


def default_availability_route(event, method, repository):
    if method in {"POST", "PUT"}:
        return save_document(event, repository, validate_tenant_availability, "availability", "invalid_tenant_availability")
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        document = repository.get(tenant_id, "default")
        if not document:
            return error_response("Tenant availability not found.", status_code=404, code="not_found")
        return json_response({"availability": document})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def document_route(event, method, repository, singular, validator, plural, id_param=None, normalizer=None):
    if method in {"POST", "PUT"}:
        return save_document(event, repository, validator, singular, f"invalid_{singular}", normalizer=normalizer)
    if method == "GET":
        document_id = path_params(event).get(id_param or f"{singular}_id")
        if document_id:
            return get_document(event, repository, singular, document_id)
        return list_documents(event, repository, plural)
    if method == "DELETE":
        key = id_param or f"{singular}_id"
        document_id = path_params(event).get(key) or query_params(event).get(key)
        if not document_id:
            return error_response(f"{key} is required.", code=f"missing_{key}")
        return delete_document(event, repository, singular, document_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_document(event, repository, validator, response_key, error_code, normalizer=None):
    try:
        document = parse_json_body(event)
        if normalizer:
            document = normalizer(document)
        validator(document)
        saved = repository.put(document)
        return json_response({response_key: saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code=error_code)


def get_document(event, repository, response_key, document_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    document = repository.get(tenant_id, document_id)
    if not document:
        return error_response(f"{response_key.replace('_', ' ').title()} not found.", status_code=404, code="not_found")
    return json_response({response_key: document})


def list_documents(event, repository, response_key):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    documents = repository.list_for_tenant(tenant_id)
    return json_response({response_key: documents, "count": len(documents)})


def delete_document(event, repository, response_key, document_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, document_id)
    if not deleted:
        return error_response(f"{response_key.replace('_', ' ').title()} not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, response_key: deleted})
