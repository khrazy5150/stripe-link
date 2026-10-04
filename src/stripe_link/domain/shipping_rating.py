"""Packed parcels in, buyer-facing services out. The carrier call, factored out of the tenant's tooling.

plans/LIVE_SHIPPING_RATES.md phase 2. `handlers/shipping.preview_rates` already packs a cart and asks a
carrier -- but it rates **the first parcel only**, which its own docstring says, because a tenant comparing
boxes wants one box's price. A BUYER is quoted for the whole order, so the summing lives here rather than
being bolted onto a function that deliberately does not do it.

The provider is INJECTED. Nothing in this module knows about KMS, Dynamo or an API key; the handler
decrypts and passes a provider in, and tests pass `MockProvider`. That is what keeps the one rule worth
testing -- *a service is only offerable when every parcel can travel by it* -- testable without a carrier.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def rate_parcels(provider: Any, *, from_address: dict[str, Any], to_address: dict[str, Any],
                 parcels: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Every parcel in the order, rated and summed per service.

    Returns `{options, error}`. `options` carry `service_token`, `carrier`, `label`, `amount` (the SUM
    across parcels) and `estimated_days` (the SLOWEST parcel's, because the order is not delivered until
    the last box arrives).

    **A service survives only when EVERY parcel can travel by it.** A two-box order where UPS will carry
    one box and not the other has no UPS price -- offering the one it quoted would undercharge by a whole
    parcel. Carriers bill per parcel, so summing is how they charge; dropping the incomplete ones is how
    we avoid inventing a price for a shipment nobody quoted.

    Errors are RETURNED, not raised. This runs in the buyer's path, where a carrier having a bad minute
    must produce "we could not get rates" rather than a 500 on a landing page.
    """
    if not parcels:
        return {"options": [], "error": "no_parcels"}

    per_parcel: list[dict[str, dict[str, Any]]] = []
    for parcel in parcels:
        try:
            rates = provider.rates(from_address=from_address, to_address=to_address, parcel=parcel)
        except Exception as exc:  # noqa: BLE001 - every provider failure is one answer to the buyer
            return {"options": [], "error": f"{type(exc).__name__}: {exc}"}
        by_token: dict[str, dict[str, Any]] = {}
        for rate in rates or []:
            token = _text(rate.get("service_token"))
            if not token:
                # Shippo sometimes returns a bare servicelevel string with no token. Unusable here: the
                # token is what the buyer's pick is validated against later, and what a label is bought with.
                continue
            existing = by_token.get(token)
            if existing is None or int(rate.get("amount") or 0) < int(existing.get("amount") or 0):
                by_token[token] = rate
        per_parcel.append(by_token)

    offerable = set(per_parcel[0])
    for by_token in per_parcel[1:]:
        offerable &= set(by_token)

    options = []
    for token in offerable:
        first = per_parcel[0][token]
        amount = sum(int(p[token].get("amount") or 0) for p in per_parcel)
        days = [p[token].get("estimated_days") for p in per_parcel
                if p[token].get("estimated_days") is not None]
        option = {
            "service_token": token,
            "carrier": _text(first.get("carrier")),
            "label": _text(first.get("service")) or token,
            "amount": amount,
        }
        if days:
            # The SLOWEST parcel decides. An order is not delivered until the last box arrives, and the
            # buyer was shown one estimate for the order.
            option["estimated_days"] = max(int(d) for d in days)
        options.append(option)

    options.sort(key=lambda o: (o["amount"], o["label"]))
    return {"options": options, "error": ""}


def carrier_menu(options: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The carrier's own services, unnarrowed, wearing the carrier's own names.

    What a zone falls back to when the tenant has adopted no service the carrier offers for this
    destination. That is not the tenant declining those services -- it is the tenant never having been
    shown them. `enabled_services` is populated by adopting rows from the Shipping screen's rate preview,
    and a tenant previews the address they ship to most, so a US seller's adopted list is US-domestic by
    construction. Narrowing an INTERNATIONAL quote by it leaves nothing, every time, for every tenant
    (author, 2026-10-04, on a catch-all zone that could price no country on earth).

    The author's narrowing rule is untouched, because it answers a different question: *"the customer
    shouldn't be able to arbitrarily ask for overnight shipping if the tenant hasn't enabled overnight
    shipping"* protects a choice the tenant MADE. Where they made none, the carrier's menu is the honest
    answer, and the alternative is refusing a sale the tenant asked for.

    Labelled from the carrier's own words, then the service name, then the raw token -- `normalize_option`
    drops a nameless option, and a dropped option is a service the buyer is never offered.
    """
    out = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        merged = dict(option)
        merged["label"] = (_text(option.get("label")) or _text(option.get("service"))
                           or _text(option.get("service_token")))
        days = merged.pop("estimated_days", None)
        if days is not None:
            merged["transit_days_min"] = int(days)
            merged["transit_days_max"] = int(days)
        out.append(merged)
    return out


def apply_tenant_services(options: list[dict[str, Any]] | None,
                          services: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The carrier's menu, narrowed to what the tenant actually sells, wearing the tenant's own words.

    The rule is `shipping_zones.services_for`'s and is restated here only as a FILTER over live rates:
    *"The customer shouldn't be able to arbitrarily ask for overnight shipping if the tenant hasn't enabled
    overnight shipping."* A carrier will happily quote twelve services; a tenant who adopted two sells two.

    The tenant's `label` wins when they set one -- they chose how to describe the service to their buyers,
    and "UPS Ground Saver" is the carrier's name for it, not necessarily theirs. The DELIVERY ESTIMATE goes
    the other way: the live one is destination-specific and therefore truer than a figure typed once in
    settings, so a configured range fills in only where the carrier gave none.
    """
    wanted = {}
    for service in services or []:
        token = _text(service.get("service_token"))
        if token:
            wanted[token] = service
    if not wanted:
        return []
    out = []
    for option in options or []:
        service = wanted.get(_text(option.get("service_token")))
        if service is None:
            continue
        merged = dict(option)
        # A label is GUARANTEED here, not assumed. `normalize_option` drops an option that has none, and a
        # dropped option is a service the buyer is never offered and a sale that quietly ships free -- the
        # silent-zero pattern again. Tenant's words first, then the carrier's, then the raw token, which is
        # ugly but visible and therefore fixable.
        merged["label"] = (_text(service.get("label")) or _text(option.get("label"))
                           or _text(option.get("service")) or _text(option.get("service_token")))
        # The estimate lands on transit_days_min/max because that is the pair `normalize_option` carries
        # and `stripe_option_payload` turns into Stripe's `delivery_estimate`. A live figure is a single
        # number, so min == max and the buyer reads "Estimated 4 business days"; a tenant's configured
        # range stays a range and reads "Estimated 3-5 business days".
        days = merged.pop("estimated_days", None)
        if days is not None:
            merged["transit_days_min"] = int(days)
            merged["transit_days_max"] = int(days)
        else:
            for field in ("transit_days_min", "transit_days_max"):
                if service.get(field) is not None:
                    merged[field] = service.get(field)
        out.append(merged)
    return out
