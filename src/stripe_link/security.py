from typing import Any


SENSITIVE_FIELDS = {
    "secret_key",
    "secret_key_ref",
    "webhook_secret",
    "webhook_secret_ref",
}


def redact_sensitive_fields(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    redacted = dict(document)
    for field in SENSITIVE_FIELDS:
        if redacted.get(field):
            redacted[field] = "********"
    return redacted
