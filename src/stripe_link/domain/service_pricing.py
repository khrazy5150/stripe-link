"""Service pricing on the shared Price primitive (pure — no I/O).

A Service is the source of truth for its own pricing, expressed with the SAME `Price` shape that
products use (`schemas/Price.schema.json`), so services inherit net-guaranteed, sale/flash contexts,
compare-at, and the fee engine with no bespoke logic.

Back-compat: legacy services stored a single `price = {currency, unit_amount}`. These helpers are the
**read adapter** — every consumer resolves pricing through them and never branches on legacy vs
migrated documents. `normalize_service_pricing` writes the migrated shape forward on save.
"""
from __future__ import annotations

from typing import Any

DEFAULT_BOOKING_FLOW = "pay_then_book"
BOOKING_FLOWS = {"book_then_pay", "pay_then_book"}
SERVICE_PRICE_CONTEXTS = {"standard", "sale", "flash_sale"}


def _legacy_price_to_price(service: dict[str, Any]) -> dict[str, Any]:
    legacy = service.get("price") or {}
    amount = int(legacy.get("unit_amount") or 0)
    return {
        "price_id": f"svcprice_{service.get('service_id') or 'default'}",
        "currency": str(legacy.get("currency") or "usd").lower(),
        "unit_amount": amount,
        "tenant_keyed_amount": amount,
        "quantity": 1,
        "context": "standard",
        "pricing_model": "one_time",
        "fee_handling": "standard",
    }


def service_prices(service: dict[str, Any]) -> list[dict[str, Any]]:
    """The service's Price list. Synthesized from the legacy single `price` when `prices[]` is absent."""
    prices = service.get("prices")
    if isinstance(prices, list) and prices:
        return [p for p in prices if isinstance(p, dict)]
    return [_legacy_price_to_price(service)]


def default_price_id(service: dict[str, Any]) -> str:
    prices = service_prices(service)
    stored = str(service.get("default_price_id") or "")
    if stored and any(p.get("price_id") == stored for p in prices):
        return stored
    return str(prices[0].get("price_id") or "")


def resolve_service_price(service: dict[str, Any], price_id: str | None = None) -> dict[str, Any] | None:
    """The Price for `price_id`, or the default price when `price_id` is falsy. None if not found."""
    prices = service_prices(service)
    if price_id:
        return next((p for p in prices if p.get("price_id") == price_id), None)
    target = default_price_id(service)
    return next((p for p in prices if p.get("price_id") == target), prices[0] if prices else None)


def price_tenant_keyed_amount(price: dict[str, Any]) -> int:
    """The tenant-keyed (sticker) amount a price is anchored to — what the tenant wants before fee
    handling. For net_guaranteed the charged amount is grossed up from this."""
    price = price or {}
    if price.get("tenant_keyed_amount") is not None:
        return max(0, int(price.get("tenant_keyed_amount") or 0))
    return max(0, int(price.get("unit_amount") or 0))


def service_booking_flow(service: dict[str, Any]) -> str:
    flow = str(service.get("booking_flow") or "").strip()
    return flow if flow in BOOKING_FLOWS else DEFAULT_BOOKING_FLOW


def normalize_service_pricing(service: dict[str, Any]) -> dict[str, Any]:
    """Write-forward migration for save: ensure `prices[]` + `default_price_id` + `booking_flow`, and
    mirror the default price back into legacy `price` (so old readers and the required schema field
    stay valid). Idempotent. Returns a new dict."""
    result = dict(service)
    result.pop("linked_product", None)  # retired workaround — never persist it
    prices = service_prices(result)  # honors incoming prices[] or synthesizes from legacy price
    result["prices"] = prices
    result["default_price_id"] = default_price_id(result)
    result["booking_flow"] = service_booking_flow(result)
    default = resolve_service_price(result) or {}
    result["price"] = {
        "currency": str(default.get("currency") or "usd").lower(),
        "unit_amount": int(default.get("unit_amount") or 0),
    }
    return result
