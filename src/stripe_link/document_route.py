"""Generic tenant-scoped CRUD over a document repository.

Lifted out of `handlers/services.py` unchanged on 2026-10-14, when a second handler needed it. It stayed
in that handler while it had one caller; importing a HANDLER from a handler is what the transform-budget
work exists to discourage, because `tests/envreach.py` follows imports transitively and a function that
borrowed one route would inherit every table the other handler reaches.

Nothing here knows what it is storing: the caller supplies the repository, the validator and the names.
"""
from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError
from stripe_link.domain.service_index import service_index_entry
from stripe_link.repositories.documents import RepositoryError


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


# Slim list projections, by response key. `?view=index` returns these instead of full documents so a list
# screen stops paying for what only an editor needs. Adding an entry here gives that entity an index —
# document_route is shared machinery, so this is the one place it belongs.
_INDEX_PROJECTIONS = {"services": service_index_entry}


def list_documents(event, repository, response_key):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    documents = repository.list_for_tenant(tenant_id)
    project = _INDEX_PROJECTIONS.get(response_key)
    if project and str(query_params(event).get("view") or "").strip().lower() == "index":
        documents = [project(document) for document in documents]
    return json_response({response_key: documents, "count": len(documents)})


def delete_document(event, repository, response_key, document_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, document_id)
    if not deleted:
        return error_response(f"{response_key.replace('_', ' ').title()} not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, response_key: deleted})
