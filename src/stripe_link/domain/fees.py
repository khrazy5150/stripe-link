from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Any


class PriceCalculationError(ValueError):
    pass


DEFAULT_GLOBAL_BILLING_CONFIG = {
    "schema_version": "2026-06-04",
    "document_type": "global_billing_config",
    "effective_date": "2026-06-04",
    "canonical": True,
    "platform_fees": {
        "unit": "percent",
        "tiers": {
            "basic": {"physical": Decimal("10.0"), "digital": Decimal("15.0"), "tip_jar": Decimal("5.0")},
            "standard": {"physical": Decimal("8.0"), "digital": Decimal("13.0"), "tip_jar": Decimal("4.0")},
            "pro": {"physical": Decimal("5.0"), "digital": Decimal("10.0"), "tip_jar": Decimal("2.0")},
        },
    },
    "payment_processing": {
        "schedules": {
            "US_USD": {
                "merchant_loc": "US",
                "settlement_currency": "USD",
                "rates": {
                    "domestic_card": {
                        "percentage": Decimal("2.9"),
                        "fixed_cents": 30,
                        "condition": "always",
                    },
                    "international_surcharge": {
                        "percentage": Decimal("1.5"),
                        "fixed_cents": 0,
                        "condition": "card_country_differs_from_merchant_loc",
                    },
                    "fx_conversion": {
                        "percentage": Decimal("1.0"),
                        "fixed_cents": 0,
                        "condition": "card_currency_differs_from_settlement_currency",
                    },
                },
            },
        },
    },
    "created_at": 1780000000,
    "updated_at": 1780000000,
}


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PriceCalculationError(f"{field} must be a non-negative integer.")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise PriceCalculationError(f"{field} must be a non-negative integer.") from exc
    if amount < 0:
        raise PriceCalculationError(f"{field} must be a non-negative integer.")
    return amount


def _rate(value: Any) -> Decimal:
    rate = _decimal(value)
    if rate < 0:
        raise PriceCalculationError("Fee rates must be non-negative.")
    if rate > 1:
        return rate / Decimal("100")
    return rate


def _ceil_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_class_for(product_type: str, pricing_model: str = "one_time") -> str:
    if pricing_model == "customer_chooses" or product_type in {"tip-jar", "tip_jar"}:
        return "tip_jar"
    if product_type == "physical":
        return "physical"
    return "digital"


def default_billing_config() -> dict[str, Any]:
    return deepcopy(DEFAULT_GLOBAL_BILLING_CONFIG)


def platform_fee_rate(
    billing_config: dict[str, Any] | None,
    *,
    tenant_plan: str = "basic",
    product_type: str = "physical",
    pricing_model: str = "one_time",
) -> Decimal:
    fee_class = fee_class_for(product_type, pricing_model)
    config = billing_config or DEFAULT_GLOBAL_BILLING_CONFIG
    tiers = ((config.get("platform_fees") or {}).get("tiers") or {})
    value = (tiers.get(tenant_plan) or {}).get(fee_class)
    if value is None:
        value = (
            DEFAULT_GLOBAL_BILLING_CONFIG["platform_fees"]["tiers"]
            .get(tenant_plan, DEFAULT_GLOBAL_BILLING_CONFIG["platform_fees"]["tiers"]["basic"])
            .get(fee_class, Decimal("0"))
        )
    return _rate(value)


def stripe_fee_terms(
    billing_config: dict[str, Any] | None,
    *,
    stripe_fee_type: str = "domestic_card",
    payment_schedule_key: str = "US_USD",
) -> tuple[Decimal, int]:
    config = billing_config or DEFAULT_GLOBAL_BILLING_CONFIG
    schedules = ((config.get("payment_processing") or {}).get("schedules") or {})
    schedule = schedules.get(payment_schedule_key)
    if not isinstance(schedule, dict):
        schedule = next((item for item in schedules.values() if isinstance(item, dict)), None)
    if not isinstance(schedule, dict):
        schedule = DEFAULT_GLOBAL_BILLING_CONFIG["payment_processing"]["schedules"]["US_USD"]
    rates = schedule.get("rates") or {}
    rate = (
        rates.get(stripe_fee_type)
        or rates.get("domestic_card")
        or DEFAULT_GLOBAL_BILLING_CONFIG["payment_processing"]["schedules"]["US_USD"]["rates"]["domestic_card"]
    )
    if not isinstance(rate, dict):
        rate = DEFAULT_GLOBAL_BILLING_CONFIG["payment_processing"]["schedules"]["US_USD"]["rates"]["domestic_card"]
    percentage = _rate(rate.get("percentage"))
    fixed_cents = _non_negative_int(rate.get("fixed_cents", 0), "stripe_fee.fixed_cents")
    return percentage, fixed_cents


def _stripe_fee(unit_amount: int, stripe_rate: Decimal, fixed_cents: int) -> int:
    if unit_amount <= 0:
        return 0
    return _ceil_cents(Decimal(unit_amount) * stripe_rate) + fixed_cents


def _platform_fee(unit_amount: int, platform_rate: Decimal) -> int:
    if unit_amount <= 0:
        return 0
    return _round_cents(Decimal(unit_amount) * platform_rate)


def calculate_price(
    *,
    tenant_keyed_amount: Any,
    currency: str = "usd",
    product_type: str = "physical",
    fee_handling: str = "standard",
    pricing_model: str = "one_time",
    tenant_plan: str = "basic",
    stripe_fee_type: str = "domestic_card",
    payment_schedule_key: str = "US_USD",
    billing_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    amount = _non_negative_int(tenant_keyed_amount, "tenant_keyed_amount")
    if not isinstance(currency, str) or len(currency) != 3:
        raise PriceCalculationError("currency must be a 3-letter currency code.")
    if fee_handling not in {"standard", "net_guaranteed"}:
        raise PriceCalculationError("fee_handling must be either standard or net_guaranteed.")
    if amount == 0:
        return {
            "unit_amount": 0,
            "breakdown": {
                "tenant_keyed_amount": 0,
                "stripe_fee": 0,
                "platform_fee": 0,
                "net_payout": 0,
            },
        }

    stripe_rate, fixed_cents = stripe_fee_terms(
        billing_config,
        stripe_fee_type=stripe_fee_type,
        payment_schedule_key=payment_schedule_key,
    )
    platform_rate = platform_fee_rate(
        billing_config,
        tenant_plan=tenant_plan,
        product_type=product_type,
        pricing_model=pricing_model,
    )

    if fee_handling == "net_guaranteed":
        variable_rate = stripe_rate + platform_rate
        if variable_rate >= 1:
            raise PriceCalculationError("Combined fee rate must be less than 100%.")
        unit_amount = _ceil_cents((Decimal(amount) + Decimal(fixed_cents)) / (Decimal("1") - variable_rate))
        while True:
            stripe_fee = _stripe_fee(unit_amount, stripe_rate, fixed_cents)
            platform_fee = _platform_fee(unit_amount, platform_rate)
            net_payout = unit_amount - stripe_fee - platform_fee
            if net_payout >= amount:
                break
            unit_amount += 1
    else:
        unit_amount = amount
        stripe_fee = _stripe_fee(unit_amount, stripe_rate, fixed_cents)
        platform_fee = _platform_fee(unit_amount, platform_rate)
        net_payout = unit_amount - stripe_fee - platform_fee

    return {
        "unit_amount": unit_amount,
        "breakdown": {
            "tenant_keyed_amount": amount,
            "stripe_fee": stripe_fee,
            "platform_fee": platform_fee,
            "net_payout": max(net_payout, 0),
        },
    }
