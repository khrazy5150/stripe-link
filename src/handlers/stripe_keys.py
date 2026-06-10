import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_stripe_keys_document
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import RepositoryError, stripe_keys_repository
from stripe_link.security import redact_sensitive_fields


def handler(event, context, repository=None, secret_cipher=None):
    repository = repository or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        path = (event or {}).get("path", "")
        if path.endswith("/verify"):
            return verify_keys(event, repository, secret_cipher)
        return save_keys(event, repository, secret_cipher)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        keys = {
            "test": repository_get(repository, tenant_id, "test"),
            "live": repository_get(repository, tenant_id, "live"),
        }
        if not keys["test"] and not keys["live"]:
            return error_response("Stripe keys not found.", status_code=404, code="not_found")
        return json_response({"stripe_keys": redact_stripe_key_modes(keys)})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_keys(event, repository, secret_cipher):
    try:
        incoming = parse_json_body(event)
        documents = stripe_key_documents_from_payload(incoming)
        if not documents:
            raise DocumentValidationError("Stripe keys payload must include test or live keys.")
        saved = {}
        for mode, incoming_document in documents.items():
            tenant_id = str(incoming_document.get("tenant_id") or "").strip()
            existing = repository_get(repository, tenant_id, mode) if tenant_id else None
            document = prepare_stripe_keys_document(incoming_document, existing, secret_cipher)
            validate_stripe_keys_document(document)
            saved[mode] = repository.put(document)
        return json_response({"stripe_keys": redact_stripe_key_modes(saved)}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_stripe_keys")


def stripe_key_documents_from_payload(incoming):
    tenant_id = str(incoming.get("tenant_id") or "").strip()
    now = incoming.get("updated_at")
    modes = incoming.get("modes")
    if isinstance(modes, dict):
        documents = {}
        for mode in ("test", "live"):
            mode_document = modes.get(mode) or {}
            if not mode_document or stripe_key_mode_is_empty(mode_document):
                continue
            documents[mode] = {
                "schema_version": incoming.get("schema_version", "2026-05-29"),
                "document_type": "stripe_keys",
                "tenant_id": mode_document.get("tenant_id") or tenant_id,
                "mode": mode,
                "publishable_key": mode_document.get("publishable_key", ""),
                "secret_key_ref": mode_document.get("secret_key_ref", ""),
                "webhook_secret_ref": mode_document.get("webhook_secret_ref", ""),
                "updated_at": mode_document.get("updated_at") or now,
            }
        return documents
    mode = incoming.get("mode") if incoming.get("mode") in {"test", "live"} else "test"
    return {mode: incoming}


def stripe_key_mode_is_empty(document):
    return not any(
        str(document.get(field) or "").strip()
        for field in ("publishable_key", "secret_key_ref", "webhook_secret_ref", "connect_account_id")
    )


def prepare_stripe_keys_document(incoming, existing, secret_cipher):
    document = dict(existing or {})
    document.update(incoming)
    tenant_id = str(document.get("tenant_id") or "").strip()
    mode = document.get("mode") if document.get("mode") in {"test", "live"} else "test"
    document["tenant_id"] = tenant_id
    document["mode"] = mode
    for field in ("secret_key_ref", "webhook_secret_ref"):
        submitted = str(incoming.get(field) or "").strip()
        if submitted in {"", "********"}:
            if existing and existing.get(field):
                document[field] = existing[field]
            else:
                document.pop(field, None)
            continue
        document[field] = secret_cipher.encrypt(submitted, tenant_id=tenant_id, mode=mode, field=field)
    return document


def verify_keys(event, repository, secret_cipher):
    try:
        payload = parse_json_body(event)
        tenant_id = str(payload.get("tenant_id") or tenant_id_from_event(event) or "").strip()
        mode = "live" if payload.get("mode") == "live" else "test"
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        document = repository_get(repository, tenant_id, mode)
        if not document:
            return error_response(f"{mode} Stripe keys not found.", status_code=404, code="not_found")
        secret_ref = document.get("secret_key_ref") or ""
        if not secret_ref:
            return error_response(f"{mode} Stripe secret key is not saved.", status_code=400, code="missing_secret_key")
        secret_key = secret_cipher.decrypt(secret_ref, tenant_id=tenant_id, mode=mode, field="secret_key_ref")
        account = verify_stripe_secret_key(secret_key)
        return json_response({
            "stripe_keys_verification": {
                "tenant_id": tenant_id,
                "mode": mode,
                "valid": True,
                "account_id": account.get("id"),
                "livemode": account.get("livemode"),
            }
        })
    except HTTPError as exc:
        message = "Stripe rejected the secret key."
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            message = payload.get("error", {}).get("message") or message
        except (ValueError, UnicodeDecodeError):
            pass
        return error_response(message, status_code=400, code="invalid_stripe_key")
    except (DocumentValidationError, ValueError, RepositoryError, URLError) as exc:
        return error_response(str(exc), code="verify_failed")


def verify_stripe_secret_key(secret_key):
    token = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    request = Request(
        "https://api.stripe.com/v1/account",
        headers={
            "Authorization": f"Basic {token}",
            "Stripe-Version": "2024-06-20",
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def repository_get(repository, tenant_id, mode):
    try:
        return repository.get(tenant_id, mode)
    except TypeError:
        document = repository.get(tenant_id)
        if document and document.get("mode", "test") == mode:
            return document
        return None


def redact_stripe_key_modes(keys):
    return {
        mode: redact_sensitive_fields(document) if document else None
        for mode, document in keys.items()
    }
