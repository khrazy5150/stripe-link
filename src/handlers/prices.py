import time
from typing import Callable

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.fees import (
    PriceCalculationError,
    cached_billing_config,
    calculate_price,
    clear_config_cache,
    load_billing_config_from_s3,
)


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
