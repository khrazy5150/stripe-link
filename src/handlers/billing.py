import time
from typing import Callable

from stripe_link.common import error_response, json_response, query_params, tenant_id_from_event
from stripe_link.domain.fees import cached_billing_config, normalize_tier_id
from stripe_link.repositories.documents import (
    RepositoryError,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.security import redact_sensitive_fields


def connect_card_handler(
    event,
    context,
    *,
    tenant_repository=None,
    stripe_repository=None,
    billing_config_loader=None,
    now_fn: Callable[[], float] = time.time,
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    tenant_repository = tenant_repository or tenant_profiles_repository()
    stripe_repository = stripe_repository or stripe_keys_repository()

    try:
        tenant = tenant_repository.get(tenant_id, tenant_id)
        if not tenant:
            return error_response("Tenant not found.", status_code=404, code="not_found")

        billing_config = cached_billing_config(billing_config_loader, now_fn)
        tier_id = normalize_tier_id(tenant.get("tier_id"))
        tiers = ((billing_config.get("platform_fees") or {}).get("tiers") or {})
        effective_tier = tiers.get(tier_id) or tiers.get("basic") or {}
        mode = "live" if query_params(event).get("mode") == "live" else "test"
        stripe_keys = stripe_repository.get(tenant_id, mode=mode)

        return json_response({
            "stripe_connect_card": {
                "tenant_id": tenant_id,
                "mode": mode,
                "tier_id": tier_id,
                "billing_status": tenant.get("billing_status") or "trial",
                "platform_fees": {
                    "unit": ((billing_config.get("platform_fees") or {}).get("unit") or "percent"),
                    "rates": effective_tier,
                },
                "billing_config": {
                    "schema_version": billing_config.get("schema_version"),
                    "effective_date": billing_config.get("effective_date"),
                    "canonical": billing_config.get("canonical"),
                },
                "stripe_connect": redact_sensitive_fields(stripe_keys) if stripe_keys else {
                    "connect_status": "not_connected",
                },
            }
        })
    except RepositoryError as exc:
        return error_response(str(exc), code="billing_connect_card_error")
