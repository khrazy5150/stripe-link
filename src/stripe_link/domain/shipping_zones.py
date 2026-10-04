"""What buyers pay, by destination. Ordered zones, first match wins.

plans/SHIPPING_ELEMENT.md, contract locked by the author 2026-09-30.

    zones: [ {name, destinations: [{country}], rule: {type, amount?, services?}} ]
    rule types: free | flat | flat_rate_box | live

**Country is the V1 granularity**, deliberately. State exclusions, Alaska/Hawaii, territories, provinces and EU
regions are a substantially bigger product concept with no evidence yet that it is needed. `destinations[]`
carries an unused `regions` key so that adding them later is purely additive -- no second field, no dual-read
fallback, no migration. The shape that cannot break is better than the shape that is shorter.

This module answers "which rule applies to this destination". It does NOT price anything: `free` and `flat`
resolve to an amount here, while `flat_rate_box` needs the packed box and `live` needs the carrier. Pricing
lives with whatever knows those things (`domain/shipping_charges.py`, `handlers/shipping.py`), so this stays
pure and destination-only.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

FREE, FLAT, FLAT_RATE_BOX, LIVE = "free", "flat", "flat_rate_box", "live"
RULE_TYPES = (FREE, FLAT, FLAT_RATE_BOX, LIVE)

# The catch-all destination. A zone carrying it answers for every country no earlier zone claimed.
ANYWHERE = "*"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _country(value: Any) -> str:
    code = _text(value).upper()
    return ANYWHERE if code == ANYWHERE else code[:2]


def _whole(value: Any) -> int:
    """Cents, tolerating the `Decimal` a stored document hands back (`feedback_decimal_from_dynamo`)."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    try:
        return int(_text(value))
    except (TypeError, ValueError):
        return 0


def zone_countries(zone: dict[str, Any] | None) -> list[str]:
    """The countries a zone claims, catch-all included."""
    out: list[str] = []
    for destination in (zone or {}).get("destinations") or []:
        if not isinstance(destination, dict):
            continue
        code = _country(destination.get("country"))
        if code and code not in out:
            out.append(code)
    return out


def is_catch_all(zone: dict[str, Any] | None) -> bool:
    return ANYWHERE in zone_countries(zone)


def zones_of(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    zones = (config or {}).get("zones")
    return [z for z in zones if isinstance(z, dict)] if isinstance(zones, list) else []


def zone_for(config: dict[str, Any] | None, country: Any) -> dict[str, Any] | None:
    """The zone governing this destination, or None when nothing claims it.

    ORDER MATTERS and is the tenant's: the first zone listing the country wins, and a catch-all wins only for
    countries no earlier zone claimed. Returning None is a real answer -- a tenant with no catch-all has not
    said what happens to a buyer from an unlisted country, and inventing "free" or "live" on their behalf would
    be the implicit commercial promise this whole plan family exists to stop.
    """
    code = _country(country)
    if not code:
        return None
    fallback = None
    for zone in zones_of(config):
        countries = zone_countries(zone)
        if code in countries:
            return zone
        if ANYWHERE in countries and fallback is None:
            # Remembered rather than returned: a catch-all placed before a specific zone must not beat it.
            # The schema requires the catch-all last, but a document written before that rule existed -- or by
            # hand -- must still resolve sensibly rather than shadow the tenant's real zones.
            fallback = zone
    return fallback


def rule_for(config: dict[str, Any] | None, country: Any) -> dict[str, Any]:
    """The rule governing this destination. `{}` when no zone claims it and there is no catch-all."""
    zone = zone_for(config, country)
    rule = (zone or {}).get("rule")
    if not isinstance(rule, dict):
        return {}
    kind = _text(rule.get("type")).lower()
    return dict(rule, type=kind) if kind in RULE_TYPES else {}


def ships_to(config: dict[str, Any] | None, country: Any) -> bool:
    """Whether this tenant ships here at all. A destination with no zone is not a destination they serve."""
    return bool(rule_for(config, country))


def allowed_countries(config: dict[str, Any] | None) -> list[str]:
    """Every country the zones name, for Stripe's `shipping_address_collection[allowed_countries]`.

    `handlers/checkout.py` hardcodes US and CA today. Once zones exist the list must come FROM them, or a tenant
    who adds a zone still cannot receive that order -- a rule the tenant wrote and the platform ignored
    (plans/SHIPPING_ELEMENT.md).

    A catch-all contributes NOTHING HERE, and that is about Stripe rather than about the tenant. The list
    Stripe is given is fixed BEFORE the buyer picks a country, and it is handed the same `shipping_options`
    whichever they pick -- so a list spanning destinations that disagree on price has no correct option in
    it, and `checkout_shipping` rightly charges nothing. Widening this list to the whole world would
    therefore not open up international selling; it would turn every catch-all tenant's domestic postage
    into zero (found by the unanimity tests, 2026-10-04).

    `offerable_countries` is the expanded list, and the distinction between the two is where the buyer is:
    choosing on OUR page, where every country can be re-quoted, or choosing on Stripe's, where one set of
    options has to serve all of them.
    """
    out: list[str] = []
    for zone in zones_of(config):
        for code in zone_countries(zone):
            if code != ANYWHERE and code not in out:
                out.append(code)
    return out


def offerable_countries(config: dict[str, Any] | None) -> list[str]:
    """Every country this tenant will ship to, catch-all EXPANDED. What the page's dropdown offers.

    `allowed_countries` dropped the catch-all, documented as the honest answer: Stripe wants an explicit
    list and "everywhere" is not one. For Stripe that is still true. For the BUYER it was not -- a tenant
    whose zones read "United States" and "Everywhere else" was shown a dropdown holding only the United
    States, the platform silently refusing a rule the tenant wrote (author, 2026-10-04: *"someone in
    Mexico, Canada, or the European Union cannot purchase the item when the system says that they can"*).

    The page can honour the whole list where Stripe cannot, because it re-quotes on every change: the
    buyer names a country, that country alone is rated, and checkout is then told that one country. Named
    countries keep their place at the front, since the tenant's order is a statement about where they
    mainly sell. A country the CARRIER cannot reach is answered a step later, by the element failing to
    quote it, rather than by this list guessing at coverage it does not know.
    """
    out = allowed_countries(config)
    if not any(is_catch_all(zone) for zone in zones_of(config)):
        return out
    from stripe_link.domain.shipping_countries import shippable_countries

    seen = set(out)
    return out + [code for code in shippable_countries() if code not in seen]


def services_for(config: dict[str, Any] | None, country: Any) -> list[dict[str, Any]]:
    """The services offerable to this destination: the tenant's enabled set, narrowed by the zone.

    A zone may only NARROW -- the author's rule: *"The customer shouldn't be able to arbitrarily ask 'Give me
    overnight shipping' if the tenant hasn't enabled overnight shipping."* Same shape as
    `ai_resolvers.resolve_sections`, where a request narrows what the rules allow and can never add to it.
    """
    enabled = (config or {}).get("enabled_services")
    enabled = [s for s in enabled if isinstance(s, dict) and _text(s.get("service_token"))] \
        if isinstance(enabled, list) else []
    rule = rule_for(config, country)
    permitted = rule.get("services")
    if isinstance(permitted, list) and permitted:
        wanted = {_text(token) for token in permitted if _text(token)}
        enabled = [s for s in enabled if _text(s.get("service_token")) in wanted]
    return enabled


def flat_rate_for_box(box: dict[str, Any] | None, country: Any) -> int | None:
    """What this container costs a buyer in this country, or None when the tenant has not priced it.

    None rather than 0: an unpriced box is not a free box, and a `flat_rate_box` zone with no price for the
    destination cannot produce a rate -- the caller must fall back or refuse rather than ship for nothing.
    """
    rates = (box or {}).get("flat_rate")
    if not isinstance(rates, dict):
        return None
    code = _country(country)
    for key, value in rates.items():
        if _country(key) == code:
            return _whole(value)
    return None


def resolved_amount(config: dict[str, Any] | None, country: Any) -> int | None:
    """The buyer-facing amount when the destination's rule alone decides it.

    `free` is 0 and `flat` is its amount. `flat_rate_box` and `live` return **None**, meaning "not answerable
    from the destination" -- one needs the packed box, the other needs the carrier. None is not zero, and a
    caller that treats it as zero ships for free.
    """
    rule = rule_for(config, country)
    kind = rule.get("type")
    if kind == FREE:
        return 0
    if kind == FLAT:
        return _whole(rule.get("amount"))
    return None
