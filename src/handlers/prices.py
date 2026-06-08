import json
import os
import time
from typing import Any, Callable

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.fees import PriceCalculationError, calculate_price, default_billing_config


CONFIG_CACHE_TTL_SECONDS = int(os.environ.get("BILLING_CONFIG_CACHE_TTL_SECONDS", "300"))
BILLING_CONFIG_KEY = os.environ.get("BILLING_CONFIG_KEY", "global_billing_config.json")
_CONFIG_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "billing_config": None,
}
_S3_CLIENT = None


def clear_config_cache() -> None:
    _CONFIG_CACHE["expires_at"] = 0.0
    _CONFIG_CACHE["billing_config"] = None


def s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is None:
        import boto3

        _S3_CLIENT = boto3.client("s3")
    return _S3_CLIENT


def load_billing_config_from_s3() -> dict[str, Any]:
    bucket = os.environ.get("BILLING_CONFIG_BUCKET")
    if not bucket:
        return default_billing_config()
    try:
        response = s3_client().get_object(Bucket=bucket, Key=BILLING_CONFIG_KEY)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return default_billing_config()


def cached_billing_config(
    billing_config_loader: Callable[[], dict[str, Any]] | None = None,
    now_fn: Callable[[], float] = time.time,
) -> dict[str, Any]:
    now = now_fn()
    if _CONFIG_CACHE["billing_config"] is not None and _CONFIG_CACHE["expires_at"] > now:
        return _CONFIG_CACHE["billing_config"]

    loader = billing_config_loader or load_billing_config_from_s3
    billing_config = loader() or default_billing_config()
    _CONFIG_CACHE["billing_config"] = billing_config
    _CONFIG_CACHE["expires_at"] = now + CONFIG_CACHE_TTL_SECONDS
    return billing_config


def handler(event, context, billing_config_loader=None, now_fn: Callable[[], float] = time.time):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
    return calculate(event, billing_config_loader, now_fn)


def calculate(event, billing_config_loader=None, now_fn: Callable[[], float] = time.time):
    try:
        body = parse_json_body(event)
        tenant_id = tenant_id_from_event(event, body)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")

        billing_config = cached_billing_config(billing_config_loader, now_fn)
        result = calculate_price(
            tenant_keyed_amount=body.get("tenant_keyed_amount"),
            currency=body.get("currency", "usd"),
            product_type=body.get("product_type", "physical"),
            fee_handling=body.get("fee_handling", "standard"),
            pricing_model=body.get("pricing_model", "one_time"),
            tenant_plan=body.get("tenant_plan", "basic"),
            stripe_fee_type=body.get("stripe_fee_type", "domestic_card"),
            payment_schedule_key=body.get("payment_schedule_key", "US_USD"),
            billing_config=billing_config,
        )
        return json_response(result)
    except (ValueError, PriceCalculationError) as exc:
        return error_response(str(exc), code="invalid_price_calculation")
