import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Callable

from stripe_link.common import error_response, header_value, json_response
from stripe_link.repositories.documents import RepositoryError, stripe_keys_repository
from stripe_link.stripe_platform_secrets import get_platform_webhook_secret


SIGNATURE_TOLERANCE_SECONDS = 300


def _request_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return str(body)


def _webhook_kind(event: dict[str, Any]) -> str:
    path = str(event.get("path") or event.get("rawPath") or "")
    return "preview" if path.rstrip("/").endswith("/stripe-preview") else "stable"


def _mode_for_environment() -> str:
    return "live" if os.environ.get("ENVIRONMENT") == "prod" else "test"


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    timestamp = 0
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = 0
        elif key == "v1" and value:
            signatures.append(value)
    return timestamp, signatures


def _signature_is_valid(
    *,
    body: str,
    signature_header: str,
    secret: str,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> bool:
    timestamp, signatures = _parse_signature_header(signature_header)
    if not timestamp or not signatures:
        return False
    if abs(now_fn() - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False

    signed_payload = f"{timestamp}.{body}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _metadata_tenant_id(stripe_event: dict[str, Any]) -> str:
    data_object = ((stripe_event.get("data") or {}).get("object") or {})
    metadata = data_object.get("metadata") if isinstance(data_object, dict) else {}
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("tenant_id") or metadata.get("client_id") or "").strip()


def handler(
    event,
    context,
    *,
    repository=None,
    webhook_secret_loader: Callable[[str, str], str | None] = get_platform_webhook_secret,
    now_fn: Callable[[], int] = lambda: int(time.time()),
):
    method = event.get("httpMethod", "")
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response("Method not allowed.", 405, code="method_not_allowed")

    kind = _webhook_kind(event)
    mode = _mode_for_environment()
    secret = webhook_secret_loader(kind, mode)
    if not secret:
        return error_response(
            f"Stripe {kind} webhook signing secret is not configured for {mode}.",
            500,
            code="webhook_secret_not_configured",
        )

    body = _request_body(event)
    signature_header = header_value(event, "Stripe-Signature")
    if not _signature_is_valid(body=body, signature_header=signature_header, secret=secret, now_fn=now_fn):
        return error_response("Stripe webhook signature verification failed.", 400, code="invalid_signature")

    try:
        stripe_event = json.loads(body)
    except json.JSONDecodeError as exc:
        return error_response(f"Invalid JSON body: {exc}", 400, code="invalid_json")
    if not isinstance(stripe_event, dict):
        return error_response("Stripe webhook payload must be an object.", 400, code="invalid_json")

    account_id = str(stripe_event.get("account") or "").strip()
    tenant_document = None
    if account_id:
        try:
            tenant_document = (repository or stripe_keys_repository()).find_by_connect_account_id(account_id, mode)
        except RepositoryError as exc:
            return error_response(str(exc), 500, code="repository_error")

    tenant_id = str((tenant_document or {}).get("tenant_id") or "").strip() or _metadata_tenant_id(stripe_event)
    return json_response({
        "received": True,
        "webhook": {
            "kind": kind,
            "mode": mode,
            "event_id": stripe_event.get("id", ""),
            "type": stripe_event.get("type", ""),
            "api_version": stripe_event.get("api_version", ""),
            "livemode": bool(stripe_event.get("livemode")),
            "connect_account_id": account_id,
            "tenant_id": tenant_id,
            "tenant_status": "resolved" if tenant_id else "unknown",
        },
    })
