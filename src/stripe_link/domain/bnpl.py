"""Buy-Now-Pay-Later / installment payment methods (Klarna, Afterpay/Clearpay, Affirm, Zip), offered per tenant
and controlled by the platform (plans/BNPL_PAYMENT_METHODS.md).

Each method maps to a Stripe *capability* (requested on the tenant's connected Standard account) and a Stripe
*payment_method_type* (added to the Checkout Session). Country/currency lists pre-gate the UI and keep us from
listing a currency-ineligible method in `payment_method_types` (which errors); Stripe's returned capability
status is the final word on whether the method is actually live. Amount limits are left to Stripe (it just
doesn't render an out-of-range method).

Lists are approximate and evolve — verify against Stripe when touching them.
"""
from typing import Any

# Ordered so the Checkout page + dashboard show methods consistently. Backend handles all four generically;
# the dashboard surfaces Klarna first (P1) and the rest in P2 (plans/BNPL_PAYMENT_METHODS.md).
BNPL_METHODS: dict[str, dict[str, Any]] = {
    "klarna": {
        "capability": "klarna_payments",
        "payment_method_type": "klarna",
        "label": "Klarna",
        "currencies": {"usd", "gbp", "eur", "dkk", "nok", "sek", "chf", "pln", "czk", "cad", "aud", "nzd"},
        "countries": {"US", "GB", "AT", "BE", "CZ", "DK", "FI", "FR", "DE", "GR", "IE", "IT", "NL", "NO",
                      "PL", "PT", "ES", "SE", "CH", "CA", "AU", "NZ"},
    },
    "afterpay_clearpay": {
        "capability": "afterpay_clearpay_payments",
        "payment_method_type": "afterpay_clearpay",
        "label": "Afterpay / Clearpay",
        "currencies": {"usd", "cad", "gbp", "aud", "nzd", "eur"},
        "countries": {"US", "CA", "GB", "AU", "NZ", "FR", "IT", "ES"},
    },
    "affirm": {
        "capability": "affirm_payments",
        "payment_method_type": "affirm",
        "label": "Affirm",
        "currencies": {"usd", "cad"},
        "countries": {"US", "CA"},
    },
    "zip": {
        "capability": "zip_payments",
        "payment_method_type": "zip",
        "label": "Zip",
        "currencies": {"usd", "aud"},
        "countries": {"US", "AU"},
    },
}

# The capability states Stripe returns (Account.capabilities values).
CAPABILITY_STATUSES = {"active", "pending", "inactive", "unrequested"}

# Stripe's Payment Method Messaging Element ("As low as 4 payments of $X") supports these (Zip is not supported
# by the messaging element) — used for the on-page BNPL messaging (plans/BNPL_PAYMENT_METHODS.md P3).
MESSAGING_METHODS = {"klarna", "afterpay_clearpay", "affirm"}


def is_valid_method(method: str) -> bool:
    return method in BNPL_METHODS


def capability_name(method: str) -> str:
    return str((BNPL_METHODS.get(method) or {}).get("capability") or "")


def currency_eligible(method: str, currency: str) -> bool:
    return str(currency or "").lower() in (BNPL_METHODS.get(method) or {}).get("currencies", set())


def country_eligible(method: str, country: str) -> bool:
    return str(country or "").upper() in (BNPL_METHODS.get(method) or {}).get("countries", set())


def checkout_payment_method_types(bnpl_config: dict[str, Any] | None, currency: str) -> list[str]:
    """Stripe `payment_method_type` strings to add to a Checkout Session for a tenant's ENABLED + capability-
    ACTIVE + currency-eligible BNPL methods (order follows BNPL_METHODS). Does NOT include 'card' — the caller
    prepends it. An empty list means "don't override the session's default payment methods." Amount limits are
    left to Stripe."""
    config = bnpl_config or {}
    out: list[str] = []
    for method, spec in BNPL_METHODS.items():
        entry = config.get(method) or {}
        if (entry.get("enabled")
                and entry.get("capability_status") == "active"
                and currency_eligible(method, currency)):
            out.append(spec["payment_method_type"])
    return out


def messaging_method_types(bnpl_config: dict[str, Any] | None) -> list[str]:
    """Stripe `payment_method_type` strings for the on-page Payment Method Messaging Element — the tenant's
    ENABLED + capability-ACTIVE methods that the messaging element supports (Klarna/Afterpay/Affirm; not Zip).
    No currency gate here — the messaging element itself filters plans by amount/currency/buyer. Empty → render
    no messaging."""
    config = bnpl_config or {}
    out: list[str] = []
    for method, spec in BNPL_METHODS.items():
        if method not in MESSAGING_METHODS:
            continue
        entry = config.get(method) or {}
        if entry.get("enabled") and entry.get("capability_status") == "active":
            out.append(spec["payment_method_type"])
    return out
