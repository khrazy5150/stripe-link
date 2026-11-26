"""Publish Ads plan limits through the tenant's existing subscription snapshot."""

from decimal import Decimal
from typing import Any


def ads_subscription(
    plan: dict[str, Any] | None, *, billing_mode: str, effective_at: int,
) -> dict[str, Any] | None:
    limits = (plan or {}).get("ads")
    features = (plan or {}).get("entitlements")
    if (
        not isinstance(features, dict) or features.get("ads") is not True
        or billing_mode not in ("test", "live") or type(effective_at) is not int or effective_at < 0
    ):
        return None
    if not isinstance(limits, dict) or limits.get("mode") not in ("promo", "scale"):
        return None

    values = {}
    for field, minimum, maximum in (
        ("max_active_campaigns", 1, None),
        ("max_average_daily_budget_micros", 1, None),
        ("monthly_fee_allowance_micros", 0, None),
        ("management_fee_bps", 0, 10_000),
    ):
        value = limits.get(field)
        if (
            type(value) not in (int, Decimal)
            or (isinstance(value, Decimal) and not value.is_finite())
            or not (minimum <= value and (maximum is None or value <= maximum))
            or value != int(value)
        ):
            return None
        values[field] = int(value)

    advanced = limits.get("advanced_campaign_types", [])
    if not isinstance(advanced, list) or any(not isinstance(item, str) or not item for item in advanced):
        return None
    if limits["mode"] == "promo" and (advanced or values["management_fee_bps"]):
        return None
    return {
        **values,
        "mode": limits["mode"],
        "advanced_campaign_types": sorted(set(advanced)),
        "billing_mode": billing_mode,
        "effective_at": effective_at,
    }
