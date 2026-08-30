from typing import Any


REDACTED = "********"

# Anything here is masked on the way out and never accepted back in. This list MUST grow with the
# schema: it started as the BYO-key fields only, and when Connect OAuth landed later its two token
# refs were not added, so they shipped to the browser in full kms:v1 ciphertext until 2026-08-30.
# A denylist fails silently every time the document grows -- prefer building responses from an
# allowlist of what the UI actually needs (see plans/TODO.md, Security).
SENSITIVE_FIELDS = {
    "secret_key",
    "secret_key_ref",
    "webhook_secret",
    "webhook_secret_ref",
    "connect_access_token_ref",
    "connect_refresh_token_ref",
}


def redact_sensitive_fields(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    redacted = dict(document)
    for field in SENSITIVE_FIELDS:
        if redacted.get(field):
            redacted[field] = "********"
    return redacted


def restore_redacted_fields(incoming, existing):
    """Drop masked sensitive values from a client payload, keeping what is already stored.

    Redaction is only safe if the mask can never be written back. A client that GETs a document and
    POSTs it unchanged would otherwise persist "********" over the real ciphertext and destroy the
    credential. Returns a copy of `incoming` with every SENSITIVE_FIELD that is blank-or-masked
    replaced by the stored value, or removed when nothing is stored.
    """
    cleaned = dict(incoming or {})
    stored = existing or {}
    for field in SENSITIVE_FIELDS:
        if field not in cleaned:
            continue
        if str(cleaned.get(field) or "").strip() not in {"", REDACTED}:
            continue  # a genuinely new value -- leave it for the caller to encrypt/store
        if stored.get(field):
            cleaned[field] = stored[field]
        else:
            cleaned.pop(field, None)
    return cleaned
