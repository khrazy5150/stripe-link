import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.appointments import AppointmentTransitionError, transition_appointment
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
)


def handler(
    event,
    context,
    services_repo=None,
    fulfillers_repo=None,
    availability_repo=None,
    exceptions_repo=None,
    appointments_repo=None,
):
    services_repo = services_repo or services_repository()
    fulfillers_repo = fulfillers_repo or fulfillers_repository()
    availability_repo = availability_repo or tenant_availability_repository()
    exceptions_repo = exceptions_repo or availability_exceptions_repository()
    appointments_repo = appointments_repo or appointments_repository()
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
    return document_route(event, method, services_repo, "service", validate_service, "services", id_param="service_id")


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


def document_route(event, method, repository, singular, validator, plural, id_param=None):
    if method in {"POST", "PUT"}:
        return save_document(event, repository, validator, singular, f"invalid_{singular}")
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


def save_document(event, repository, validator, response_key, error_code):
    try:
        document = parse_json_body(event)
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
