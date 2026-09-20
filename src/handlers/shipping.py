from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
from stripe_link.kms_secrets import KmsSecretCipher, is_encrypted_secret_ref
from stripe_link.repositories.documents import RepositoryError, shipping_config_repository


REDACTED_SECRET = "********"
# Provider api_key_ref values that are already stored references, not a freshly-typed key.
KNOWN_SECRET_REF_PREFIXES = ("kms:v1:", "kms://", "secretsmanager://")
# Encryption context values binding a provider key ciphertext to this document/field.
SECRET_MODE = "shipping"
SECRET_FIELD = "provider.api_key_ref"


def handler(event, context, repository=None, secret_cipher=None):
    repository = repository or shipping_config_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_shipping_config(event, repository, secret_cipher)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        config = repository.get(tenant_id)
        if not config:
            return error_response("Shipping config not found.", status_code=404, code="not_found")
        return json_response({"shipping_config": redact_shipping_config(config)})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_shipping_config(event, repository, secret_cipher):
    try:
        document = parse_json_body(event)
        tenant_id = str(document.get("tenant_id") or "").strip()
        existing = repository.get(tenant_id) if tenant_id else None
        document = prepare_provider_secret(document, existing, secret_cipher)
        validate_shipping_config(document)
        saved = repository.put(document)
        return json_response({"shipping_config": redact_shipping_config(saved)}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_shipping_config")


def _looks_like_secret_ref(value: str) -> bool:
    return is_encrypted_secret_ref(value) or value.startswith(KNOWN_SECRET_REF_PREFIXES)


def prepare_provider_secret(document, existing, secret_cipher):
    """Encrypt a newly-entered provider API key, or preserve/clear the stored one.

    The provider key is saved as a unit with its provider name: an unchanged key is
    preserved only while the provider is unchanged; selecting a different provider without
    entering a new key clears the old key so a key never lingers on the wrong provider.
    """
    provider = dict(document.get("provider") or {})
    existing_provider = dict((existing or {}).get("provider") or {})
    tenant_id = str(document.get("tenant_id") or "").strip()

    submitted = str(provider.get("api_key_ref") or "").strip()
    new_name = provider.get("name")
    old_name = existing_provider.get("name")
    old_ref = existing_provider.get("api_key_ref")

    if submitted and submitted != REDACTED_SECRET and not _looks_like_secret_ref(submitted):
        # A freshly-typed plaintext key: encrypt it and mark the connection untested.
        provider["api_key_ref"] = secret_cipher.encrypt(
            submitted, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD
        )
        provider["connection_status"] = "untested"
        provider.pop("last_tested_at", None)
    elif submitted and _looks_like_secret_ref(submitted):
        # Already a stored reference (e.g. seeded fixture): keep it as-is.
        provider["api_key_ref"] = submitted
    elif old_ref and new_name == old_name:
        # No new key and the same provider: preserve the stored key and its status.
        provider["api_key_ref"] = old_ref
        provider.setdefault("connection_status", existing_provider.get("connection_status") or "untested")
        if existing_provider.get("last_tested_at") is not None:
            provider.setdefault("last_tested_at", existing_provider["last_tested_at"])
    else:
        # No key, or the provider changed without a new key: drop it.
        provider.pop("api_key_ref", None)
        provider["connection_status"] = "not_configured"
        provider.pop("last_tested_at", None)

    document["provider"] = provider
    return document


def redact_shipping_config(config):
    if not config:
        return config
    redacted = dict(config)
    provider = dict(redacted.get("provider") or {})
    if provider.get("api_key_ref"):
        provider["api_key_ref"] = REDACTED_SECRET
    redacted["provider"] = provider
    return redacted
