import json
import os
import time
from typing import Any, Callable

from stripe_link.common import error_response, header_value, json_response
from stripe_link.domain.platform_subscription_sync import reconcile_platform_subscription_event
from stripe_link.repositories.documents import (
    RepositoryError,
    dynamodb_safe_document,
    tenant_profiles_repository,
    webhook_events_repository,
)
from stripe_link.stripe_platform_secrets import get_platform_webhook_secret

# Reuse the Connect webhook's low-level primitives — signature verification and mode-from-livemode are identical;
# only the routing (subscription/invoice -> billing_status) and the signing secret differ.
from handlers.stripe_webhook import _mode_from_livemode, _request_body, _signature_is_valid

# Distinct signing secret from the Connect webhook: payload key whsec_platform_billing_{mode} (or env
# STRIPE_WEBHOOK_SECRET_PLATFORM_BILLING_{MODE}). This endpoint listens to the PLATFORM account's own events.
WEBHOOK_KIND = "platform_billing"


def handler(
    event,
    context,
    *,
    tenant_repo=None,
    webhook_events_repo=None,
    webhook_secret_loader: Callable[[str, str], str | None] = get_platform_webhook_secret,
    now_fn: Callable[[], int] = lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "")
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response("Method not allowed.", 405, code="method_not_allowed")

    body = _request_body(event)
    try:
        stripe_event = json.loads(body)
    except json.JSONDecodeError as exc:
        return error_response(f"Invalid JSON body: {exc}", 400, code="invalid_json")
    if not isinstance(stripe_event, dict):
        return error_response("Stripe webhook payload must be an object.", 400, code="invalid_json")

    mode = _mode_from_livemode(stripe_event)
    secret = webhook_secret_loader(WEBHOOK_KIND, mode)
    if not secret:
        return error_response(
            f"Platform billing webhook signing secret is not configured for {mode}.",
            500,
            code="webhook_secret_not_configured",
        )
    signature_header = header_value(event, "Stripe-Signature")
    if not _signature_is_valid(body=body, signature_header=signature_header, secret=secret, now_fn=now_fn):
        return error_response("Stripe webhook signature verification failed.", 400, code="invalid_signature")

    event_type = str(stripe_event.get("type") or "")
    event_id = str(stripe_event.get("id") or "").strip()

    events_repo = webhook_events_repo or (webhook_events_repository() if os.environ.get("WEBHOOK_EVENTS_TABLE") else None)
    if event_id and events_repo:
        try:
            if events_repo.get(event_id):
                return json_response({"received": True, "duplicate": True})
        except RepositoryError:
            events_repo = None  # never block processing on the idempotency store

    tenant_repo = tenant_repo or tenant_profiles_repository()
    persistence: dict[str, Any] = {}
    if event_type.startswith("customer.subscription.") or event_type.startswith("invoice."):
        try:
            persistence = reconcile_platform_subscription_event(
                stripe_event, mode=mode, tenant_repo=tenant_repo, now_fn=now_fn,
            )
        except RepositoryError as exc:
            return error_response(str(exc), 500, code="repository_error")

    if event_id and events_repo:
        try:
            events_repo.put(dynamodb_safe_document({
                "schema_version": "2026-05-29",
                "document_type": "webhook_event",
                "event_id": event_id,
                "event_type": event_type or "",
                "tenant_id": str(persistence.get("tenant_id") or ""),
                "processed_at": int(now_fn()),
                "result": persistence,
                "payload": stripe_event,
            }))
        except RepositoryError:
            pass

    return json_response({
        "received": True,
        "platform_billing_webhook": {
            "mode": mode,
            "event_id": event_id,
            "type": event_type,
            "result": persistence,
        },
    })
