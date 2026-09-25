"""Which rate to buy, decided once instead of per order.

plans/ORDER_FULFILMENT.md: a tenant should not hunt for the best rate on every order, because hunting is
exactly what makes a bulk flow impossible. They state a preference once; this applies it to every order;
the row's dropdown exists for the exceptions.

The provider already gives us everything needed. `_shippo_rate()` returns `amount`, `estimated_days` and
Shippo's own `attributes` (CHEAPEST / FASTEST / BESTVALUE). We rank from amount and days ourselves so the
behaviour is identical on a provider that tags nothing, and use the tags only as corroboration.

Stored on `ShippingConfig.rate_options` -- the object that was already about rates and that nothing had
ever written to -- rather than in a second object beside it. Its existing `markup_amount` and
`free_shipping_threshold` belong to charging the BUYER (plans/SHIPPING_PROVIDERS.md §PE), which is a
different question with a different latency budget, and they are untouched here.

Four knobs, all optional, all with defensible defaults:

  prefer             cheapest (default) | fastest | best_value
  max_transit_days   narrows the candidates BEFORE prefer is applied -- how a tenant who promised two-day
                     delivery stops ground service being chosen silently
  preferred_carrier  + tolerance: "USPS, if within $2 of the cheapest". Tenants consolidate carriers for
                     pickup reasons that have nothing to do with price
  max_auto_amount    a ceiling. The rate is still SHOWN; it is just not auto-selected, because one click
                     in a bulk flow spends money on twenty parcels at once
"""
from typing import Any

CHEAPEST = "cheapest"
FASTEST = "fastest"
BEST_VALUE = "best_value"
PREFERENCES = (CHEAPEST, FASTEST, BEST_VALUE)

DEFAULT_POLICY: dict[str, Any] = {
    "prefer": CHEAPEST,
    "max_transit_days": None,
    "preferred_carrier": "",
    "preferred_carrier_tolerance": 200,  # cents
    "max_auto_amount": None,
}


def normalize_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """A stored policy, with anything missing or nonsensical replaced by the default.

    Never raises: a malformed policy must not be able to stop a tenant seeing their rates. It degrades to
    "cheapest", which is the behaviour they had before a policy existed.
    """
    stored = policy if isinstance(policy, dict) else {}
    prefer = str(stored.get("prefer") or "").strip().lower()
    return {
        "prefer": prefer if prefer in PREFERENCES else CHEAPEST,
        "max_transit_days": _positive_int(stored.get("max_transit_days")),
        "preferred_carrier": str(stored.get("preferred_carrier") or "").strip(),
        "preferred_carrier_tolerance": _positive_int(stored.get("preferred_carrier_tolerance"))
            or DEFAULT_POLICY["preferred_carrier_tolerance"],
        "max_auto_amount": _positive_int(stored.get("max_auto_amount")),
    }


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _amount(rate: dict[str, Any]) -> int:
    try:
        return int(rate.get("amount") or 0)
    except (TypeError, ValueError):
        return 0


def _days(rate: dict[str, Any]) -> int | None:
    value = rate.get("estimated_days")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sort_rates(rates: list[dict[str, Any]], policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every rate, best first by this policy. The dropdown renders exactly this order."""
    settings = normalize_policy(policy)
    prefer = settings["prefer"]

    def key(rate: dict[str, Any]):
        amount = _amount(rate)
        days = _days(rate)
        # A rate with no transit estimate must not win a speed race by default -- unknown is not fast.
        unknown_days = days is None
        if prefer == FASTEST:
            return (unknown_days, days if days is not None else 10**6, amount)
        if prefer == BEST_VALUE:
            tagged = "BESTVALUE" not in {str(a).upper() for a in (rate.get("attributes") or [])}
            return (tagged, amount, unknown_days, days if days is not None else 10**6)
        return (amount, unknown_days, days if days is not None else 10**6)

    return sorted(rates or [], key=key)


def select_rate(rates: list[dict[str, Any]], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """The rate this policy chooses, and WHY -- the row shows the reason, not a menu.

    Returns `{rate, reason, withheld, candidates}`. `withheld` means a rate was found but deliberately not
    auto-selected; the row still shows it and asks the tenant to choose, which is the guardrail on a flow
    whose whole point is that one click buys twenty labels.
    """
    settings = normalize_policy(policy)
    everything = sort_rates(rates, settings)
    if not everything:
        return {"rate": None, "reason": "", "withheld": False, "candidates": []}

    # 1. The promise first: a delivery commitment narrows the field before price is considered at all.
    candidates = everything
    narrowed_by_days = False
    if settings["max_transit_days"]:
        within = [r for r in everything if (_days(r) or 10**6) <= settings["max_transit_days"]]
        if within:
            candidates, narrowed_by_days = within, True
        # If NOTHING arrives in time, fall back to the whole list rather than showing nothing: the tenant
        # needs to see that their promise cannot be met, not an empty cell.

    chosen = candidates[0]
    reason = _reason(settings, chosen, everything, candidates, narrowed_by_days)

    # 2. A preferred carrier wins when it is close enough on price.
    preferred = settings["preferred_carrier"].lower()
    if preferred:
        same = [r for r in candidates if str(r.get("carrier") or "").lower() == preferred]
        if same and same[0] is not chosen:
            gap = _amount(same[0]) - _amount(chosen)
            if gap <= settings["preferred_carrier_tolerance"]:
                chosen = same[0]
                reason = (f"{chosen.get('carrier')} preferred"
                          + (f", {_money(gap)} more than the cheapest" if gap > 0 else ""))

    # 3. The ceiling is checked LAST, against whatever was actually chosen.
    if settings["max_auto_amount"] and _amount(chosen) > settings["max_auto_amount"]:
        return {
            "rate": chosen,
            "reason": f"{_money(_amount(chosen))} is above your {_money(settings['max_auto_amount'])} "
                      "limit — choose a rate",
            "withheld": True,
            "candidates": everything,
        }

    return {"rate": chosen, "reason": reason, "withheld": False, "candidates": everything}


def _reason(settings, chosen, everything, candidates, narrowed_by_days) -> str:
    total = len(everything)
    if narrowed_by_days:
        within = len(candidates)
        limit = settings["max_transit_days"]
        speed = f"within {limit} day{'' if limit == 1 else 's'}"
        if settings["prefer"] == FASTEST:
            return f"fastest {speed} ({within} of {total})"
        return f"cheapest {speed} ({within} of {total})"
    if settings["prefer"] == FASTEST:
        days = _days(chosen)
        return f"fastest of {total}" + (f" ({days} day{'' if days == 1 else 's'})" if days else "")
    if settings["prefer"] == BEST_VALUE:
        return f"best value of {total}"
    return f"cheapest of {total}"


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def common_services(rate_sets: list[list[dict[str, Any]]]) -> list[dict[str, str]]:
    """Service levels available on EVERY selected order.

    "Apply overnight to these twelve" is a trap when the service exists for eleven of them, so a bulk
    override may only offer what they all share.
    """
    if not rate_sets:
        return []
    shared: set[tuple[str, str]] | None = None
    labels: dict[tuple[str, str], str] = {}
    for rates in rate_sets:
        keys = set()
        for rate in rates or []:
            token = str(rate.get("service_token") or rate.get("service") or "").strip()
            carrier = str(rate.get("carrier") or "").strip()
            if not token:
                continue
            keys.add((carrier, token))
            labels[(carrier, token)] = f"{carrier} {rate.get('service') or token}".strip()
        shared = keys if shared is None else (shared & keys)
    return [{"carrier": carrier, "service_token": token, "label": labels[(carrier, token)]}
            for carrier, token in sorted(shared or set())]
