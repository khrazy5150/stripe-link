"""What outbound shipping costs THE BUYER. Pure -- no I/O, no carrier calls.

plans/SHIPPING_CHARGES.md. Three numbers in this system are called "shipping" and they are not the same:

    InventoryLot.inbound_shipping   cost of ACQUIRING stock          (plans/INVENTORY_COST_BASIS.md)
    Order.shipping_cost             what the CARRIER charged us      (domain/rate_policy.py buys it)
    Order.shipping_amount           what the BUYER paid              <- this module

The author's point that settled the design, 2026-09-30: *"shipping could vary (ground, 2-day shipping,
overnight) and those costs can't be baked in."* Shipping speed is a BUYER's choice, so this module returns a
LIST of priced options rather than an amount. A price fixed before the buyer chooses cannot contain a cost
that depends on what they pick -- which is why there is no `baked` mode.

**This module does not decide `order.shipping_amount`.** It decides what to OFFER. The buyer picks, and Stripe
reports the choice on the completed session; `handlers/stripe_webhook` records it beside `shipping_address`.
Anything that computes a single amount at session-creation time is wrong for the variable case.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

CHARGED, FREE = "charged", "free"

# How an option's price is WORKED OUT, not what it is. The author, 2026-09-30: shipping rules may be *"free,
# flat rate, per item, threshold-based, weight-based, potentially carrier-derived"*, and **Stripe's own
# Shipping Rate is a FIXED amount** -- so JuniorBay has to resolve the rule to a number before Stripe ever
# sees it. A stored flat amount covers `flat` and the threshold; it cannot express "$2 per unit", because that
# depends on the cart.
FLAT, PER_ITEM = "flat", "per_item"
PRICING_KINDS = (FLAT, PER_ITEM)

# Stripe's tax code for shipping. Classifying the line is a FACT about what it is, not a pricing decision, so
# it is defaulted -- it is what lets shipping participate properly in Stripe Tax instead of arriving as an
# unclassified extra amount. `tax_behavior` (inclusive/exclusive) IS a tenant decision and is never defaulted
# here: guessing it would silently decide whether the buyer's tax is added on top of the postage or taken out
# of it. Stripe Tax is not enabled in this app yet (no `automatic_tax` anywhere in src/), so both fields are
# carried through in readiness rather than in use.
SHIPPING_TAX_CODE = "txcd_92010001"
TAX_BEHAVIOURS = ("inclusive", "exclusive", "unspecified")

# Stripe hosted Checkout accepts no more than 5 `shipping_options` on a session. Ground / 2-day / overnight
# fits with room; a tenant who configures more must have them truncated rather than have the whole session
# rejected, because a refused session is a lost sale and a missing sixth option is not.
MAX_OPTIONS = 5


def _whole(value: Any) -> int:
    """Cents, tolerating the `Decimal` a stored document hands back.

    `isinstance(x, int)` is False for `Decimal`, which has already 404'd published pages once in this repo
    (`feedback_decimal_from_dynamo`).
    """
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_option(option: Any) -> dict[str, Any] | None:
    """One buyer-facing service level, or None when it cannot be offered.

    A nameless or negative option is dropped rather than corrected: an option with no label is a blank radio
    button on a checkout page, and a negative amount would pay the buyer to receive goods.
    """
    if not isinstance(option, dict):
        return None
    label = _text(option.get("label"))
    if not label:
        return None
    amount = _whole(option.get("amount"))
    if amount < 0:
        return None
    kind = _text(option.get("kind")).lower() or FLAT
    if kind not in PRICING_KINDS:
        kind = FLAT
    out: dict[str, Any] = {"label": label, "amount": amount, "kind": kind}
    if option.get("first_item_amount") is not None:
        first = _whole(option.get("first_item_amount"))
        if first >= 0:
            out["first_item_amount"] = first
    for field in ("service_token", "carrier", "tax_behavior", "tax_code"):
        if _text(option.get(field)):
            out[field] = _text(option.get(field))
    for field in ("transit_days_min", "transit_days_max"):
        if option.get(field) is not None:
            out[field] = _whole(option.get(field))
    return out


def resolve_amount(option: dict[str, Any], *, item_count: int = 1) -> int:
    """The rule worked out against this cart. What Stripe is eventually told.

    `per_item` exists because Stripe's Shipping Rate cannot express it: a rate is a fixed amount, so "$2 a
    unit" has to become "$6" here before the session is created. `first_item_amount` covers the common real
    shape -- $7.95 for the first, $2 for each after -- which is neither flat nor purely per-unit.
    """
    amount = int(option.get("amount") or 0)
    if _text(option.get("kind")) != PER_ITEM:
        return amount
    units = max(1, int(item_count or 1))
    first = option.get("first_item_amount")
    if first is None:
        return amount * units
    return int(first) + amount * (units - 1)


def options_for(offer: dict[str, Any] | None, *, merchandise_amount: Any = 0,
                item_count: int = 1) -> list[dict[str, Any]]:
    """The shipping options to present, cheapest first, with every rule resolved to a number.

    `free_above_amount` frees the BASELINE only. A threshold that also freed overnight would give away the
    premium the buyer was already willing to pay for, and no merchant means that by "free shipping over $50".
    """
    shipping = (offer or {}).get("shipping")
    if not isinstance(shipping, dict):
        return []
    normalized = [opt for opt in (normalize_option(o) for o in shipping.get("options") or []) if opt]
    if not normalized:
        return []
    # Resolve every rule BEFORE sorting: with per-item pricing the cheapest option depends on the cart, so a
    # sort on the stored amount would put them in the wrong order for a basket of six.
    for option in normalized:
        option["amount"] = resolve_amount(option, item_count=item_count)
    normalized.sort(key=lambda opt: opt["amount"])

    threshold = _whole(shipping.get("free_above_amount"))
    if threshold > 0 and _whole(merchandise_amount) >= threshold:
        # Only the cheapest becomes free. Mutating a copy, because a pure function that edits the offer it was
        # handed would make the second call disagree with the first.
        normalized = [dict(opt) for opt in normalized]
        normalized[0]["amount"] = 0
        normalized[0]["free_reason"] = "order_total"

    return normalized[:MAX_OPTIONS]


def mode_for(offer: dict[str, Any] | None, *, merchandise_amount: Any = 0,
             item_count: int = 1) -> str:
    """`free` when nothing on offer costs the buyer anything, else `charged`.

    DERIVED, never trusted from storage. `mode` is a summary of the options, and a stored summary is a second
    place for the same fact to be wrong -- which is the failure this plan's sibling (REFUND_POLICY.md) exists
    to fix. An offer with no options at all is `free`: nothing is being charged.
    """
    options = options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count)
    return CHARGED if any(opt["amount"] > 0 for opt in options) else FREE


def baseline_option(offer: dict[str, Any] | None, *, merchandise_amount: Any = 0,
                    item_count: int = 1) -> dict[str, Any] | None:
    """The cheapest option -- the one the Smart Pricing invariant is about."""
    options = options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count)
    return options[0] if options else None


def smart_pricing_conflict(offer: dict[str, Any] | None, cost_profile: dict[str, Any] | None, *,
                           merchandise_amount: Any = 0) -> str:
    """The forbidden combination: the buyer pays for shipping AND the price recovers it. `""` when clean.

    The invariant, stated once (plans/SHIPPING_CHARGES.md):

        The BASELINE option's cost may sit in the Smart Pricing cost profile only when that option is FREE to
        the buyer. Every option the buyer pays for is buyer-paid revenue and must never be a cost line.

    A validator rather than a comment, because the tenant would be paid twice for the same postage and no
    tenant would ever notice from the numbers -- the price looks right and the shipping line looks right.

    Deliberately checks the BASELINE rather than the mode: "free ground, paid overnight" is an ordinary offer
    where the tenant absorbs the baseline and may price it in, while the upgrade is pure buyer-paid.
    """
    baseline = baseline_option(offer, merchandise_amount=merchandise_amount)
    if baseline is None or baseline["amount"] <= 0:
        return ""
    for line in (cost_profile or {}).get("lines") or []:
        if not isinstance(line, dict):
            continue
        if _text(line.get("kind")) != "fixed":
            continue
        label = _text(line.get("label")).lower()
        # Matched on the label because SMART_PRICING models cost lines as free text rather than an enum. It is
        # a heuristic and it is deliberately narrow: a false positive blocks a save the tenant meant, so only
        # an outbound-shipping-shaped label counts, and inbound freight must NOT (that is acquisition cost,
        # plans/INVENTORY_COST_BASIS.md, and is never charged to a buyer).
        if "inbound" in label or "freight" in label:
            continue
        if "ship" in label or "postage" in label or "delivery" in label:
            return (f"This offer charges the buyer {baseline['amount']} for its cheapest shipping option AND "
                    f"carries \"{_text(line.get('label'))}\" as a cost line, so the same postage is recovered "
                    f"twice. Remove the cost line, or make the cheapest option free.")
    return ""


def stripe_shipping_options(offer: dict[str, Any] | None, *, currency: str = "usd",
                            merchandise_amount: Any = 0,
                            item_count: int = 1) -> list[dict[str, Any]]:
    """The options as Stripe's Checkout Session wants them.

    **Inline `shipping_rate_data`, not a persisted Shipping Rate object.** Both are the same thing to Stripe
    and both accept `tax_behavior` and `tax_code`, so the tax participation is identical -- but a resolved
    amount depends on the cart (`per_item`, the free-above threshold), and creating a durable Shipping Rate per
    cart would litter the tenant's Stripe account with thousands of near-identical objects nobody can read. A
    persisted rate is the right shape for a genuinely fixed price a tenant wants to manage in the Stripe
    Dashboard; it is the wrong shape for a computed one.

    Shape only -- `handlers/checkout` does the form encoding. Kept here so the 5-option cap, the ordering and
    the tax classification are decided in the same place as everything else about shipping.
    """
    return stripe_option_payload(
        options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count), currency=currency)


def stripe_option_payload(options: list[dict[str, Any]] | None, *, currency: str = "usd") -> list[dict[str, Any]]:
    """Already-resolved options in Stripe's shape. The wire format, separated from WHICH options to send.

    Two callers need the same encoding from different decisions: an offer's explicit table
    (`stripe_shipping_options`) and a zone resolution (`checkout_shipping`). One encoder, so the 5-option cap
    and the tax classification cannot drift apart.
    """
    payload: list[dict[str, Any]] = []
    for option in (options or [])[:MAX_OPTIONS]:
        rate: dict[str, Any] = {
            "type": "fixed_amount",
            "fixed_amount": {"amount": option["amount"], "currency": str(currency or "usd").lower()},
            "display_name": option["label"],
            # Classifying the line is a fact about what it is, so it is always sent. Without it shipping
            # reaches Stripe Tax as an unclassified amount rather than as shipping.
            "tax_code": _text(option.get("tax_code")) or SHIPPING_TAX_CODE,
        }
        # Never defaulted: whether tax is added on top of the postage or taken out of it is the tenant's
        # decision, and Stripe's own default is "unspecified".
        if _text(option.get("tax_behavior")) in TAX_BEHAVIOURS:
            rate["tax_behavior"] = _text(option.get("tax_behavior"))
        entry: dict[str, Any] = {"shipping_rate_data": rate}
        minimum, maximum = option.get("transit_days_min"), option.get("transit_days_max")
        if minimum is not None or maximum is not None:
            estimate: dict[str, Any] = {}
            if minimum is not None:
                estimate["minimum"] = {"unit": "business_day", "value": int(minimum)}
            if maximum is not None:
                estimate["maximum"] = {"unit": "business_day", "value": int(maximum)}
            rate["delivery_estimate"] = estimate
        payload.append(entry)
    return payload


def buyer_paid_shipping(source: dict[str, Any] | None) -> dict[str, Any]:
    """What the buyer ACTUALLY paid for shipping, read off a Stripe Checkout Session or Invoice.

    The other half of this module. `options_for` decides what to OFFER; this records what was CHOSEN -- and it
    is a read rather than a calculation because **we cannot know the amount at session-creation time.** The
    buyer picks the service level, so the figure only exists once Stripe reports it (plans/SHIPPING_CHARGES.md).

    Both shapes carry the same `shipping_cost` object, which is why one function serves the checkout path and
    the renewal path: a subscription's shipping arrives on each invoice, not on a session.

    Returns only what is KNOWN. An absent key means "Stripe reported nothing", never zero -- a digital order
    has no shipping and a stored `shipping_amount: 0` would claim the buyer was offered shipping and declined
    to pay for it. `order.shipping_cost` (the carrier's charge) is deliberately NOT here: nobody knows it until
    a label is bought, which may be days later and may never happen.
    """
    if not isinstance(source, dict):
        return {}
    block = source.get("shipping_cost")
    block = block if isinstance(block, dict) else {}

    amount = block.get("amount_total")
    if amount is None:
        # `total_details.amount_shipping` is the same figure in a different place. Read as a fallback rather
        # than as the primary, because it is absent on invoices while `shipping_cost` appears on both.
        totals = source.get("total_details")
        if isinstance(totals, dict):
            amount = totals.get("amount_shipping")
    if amount is None:
        return {}

    out: dict[str, Any] = {"shipping_amount": _whole(amount)}
    if block.get("amount_tax") is not None:
        # Kept separate from the order's other tax because the fee base excludes shipping while tax may
        # include it -- two independent rules over the same money (domain/fees.FEE_APPLIES_TO_SHIPPING).
        out["shipping_tax"] = _whole(block.get("amount_tax"))
    rate = block.get("shipping_rate")
    if isinstance(rate, str) and rate.strip():
        # WHICH service the buyer bought. Operationally this is the important one: a buyer who paid for
        # overnight must not be posted second class. It is an id (`shr_...`) for an inline rate, so resolving
        # it to a service level needs expansion at read time or a match against the offer's own options --
        # noted rather than guessed at, because guessing the service level is how the wrong parcel ships.
        out["shipping_rate_id"] = rate.strip()
    elif isinstance(rate, dict) and rate.get("id"):
        out["shipping_rate_id"] = str(rate["id"])
        if rate.get("display_name"):
            out["shipping_service"] = str(rate["display_name"])
    return out


# ---------------------------------------------------------------------------------------------------
# TENANT ZONES -> OFFER OVERRIDE -> the options a buyer sees.
#
# plans/SHIPPING_ELEMENT.md phase 2. Before this, `offer.shipping.options[]` was the only place buyer-facing
# shipping lived, so a tenant with forty offers configured it forty times. Now the tenant says it once in their
# zones and an offer only DEPARTS from that -- the same default-then-override shape `domain/refund_policy.py`
# uses, and for the same reason: two places holding the same fact is how they come to disagree.

ELIGIBILITY_NONE = "none"
OVERRIDE_NONE, OVERRIDE_FREE, OVERRIDE_FLAT, OVERRIDE_CALCULATED = "none", "free", "flat", "calculated"


def ships_at_all(offer: dict[str, Any] | None) -> bool:
    """Whether this offer offers shipping. An explicit `none` wins over anything the tenant's zones say."""
    shipping = (offer or {}).get("shipping")
    shipping = shipping if isinstance(shipping, dict) else {}
    return _text(shipping.get("eligibility")).lower() != ELIGIBILITY_NONE


def offer_override(offer: dict[str, Any] | None) -> dict[str, Any]:
    """The offer's departure from the tenant's zones, or `{}` when it defers to them."""
    shipping = (offer or {}).get("shipping")
    shipping = shipping if isinstance(shipping, dict) else {}
    override = shipping.get("override")
    if not isinstance(override, dict):
        return {}
    kind = _text(override.get("type")).lower()
    if kind in (OVERRIDE_FREE, OVERRIDE_FLAT, OVERRIDE_CALCULATED):
        return dict(override, type=kind)
    return {}


def resolve_options(offer: dict[str, Any] | None, tenant_config: dict[str, Any] | None, *,
                    country: Any, merchandise_amount: Any = 0, item_count: int = 1,
                    box: dict[str, Any] | None = None) -> dict[str, Any]:
    """What this buyer, at this destination, may choose from — and whether we can price it yet.

    Returns `{options, mode, source, needs}`:

    - `options` — priced and ready to present, cheapest first.
    - `mode` — `free` or `charged`, derived from the options as always, or **`""` when no shipping is being
      offered at all** (the offer does not ship, or no zone serves this destination). Empty rather than `free`
      on purpose: a caller switching on `mode` alone would read "free" as "charge nothing and ship it", which
      for an unserved country means posting a parcel somewhere the tenant never agreed to send one. `""`
      matches no branch and forces the caller to look.
    - `source` — which layer decided: `offer_options`, `offer_override`, `zone`, or `unserved`. A tenant asking
      why a buyer saw a price needs to know WHICH of the three layers answered, exactly as
      `refund_policy.resolve` reports its source.
    - `needs` — what is missing before a price exists: `carrier` (a live zone with no rate yet) or `box_price`
      (a by-box zone whose packed box has no price for this country). **Empty options with a `needs` is not
      "free shipping"** — it is "not answerable yet", and a caller that renders it as free ships for nothing.

    Precedence, strongest first:

        offer.shipping.options[]   an explicit per-offer table (the shipped shape; still honoured)
        offer.shipping.override    free / flat / calculated, for every destination
        tenant zone for `country`  the normal path
    """
    if not ships_at_all(offer):
        # Not free shipping -- NO shipping. See `mode` in the docstring.
        return {"options": [], "mode": "", "source": ELIGIBILITY_NONE, "needs": ""}

    # 1. An explicit table on the offer still wins. It is what `stripe_shipping_options` already reads, it is
    #    deployed, and a tenant who hand-built one meant it.
    explicit = options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count)
    if explicit:
        return {"options": explicit, "mode": mode_for(offer, merchandise_amount=merchandise_amount,
                                                      item_count=item_count),
                "source": "offer_options", "needs": ""}

    from stripe_link.domain.shipping_zones import (
        FLAT as ZONE_FLAT,
        FLAT_RATE_BOX,
        FREE as ZONE_FREE,
        LIVE,
        flat_rate_for_box,
        rule_for,
        services_for,
    )

    override = offer_override(offer)
    rule = rule_for(tenant_config, country)
    services = services_for(tenant_config, country)

    # 2. The offer's override replaces the zone's RULE but never its services: which speeds a tenant can
    #    actually ship is a capability, and an offer cannot grant one the tenant does not have.
    if override:
        if override["type"] == OVERRIDE_FREE:
            rule = {"type": ZONE_FREE}
        elif override["type"] == OVERRIDE_FLAT:
            rule = {"type": ZONE_FLAT, "amount": _whole(override.get("amount"))}
        else:  # calculated: force rating even where the zone says a flat price
            rule = {"type": FLAT_RATE_BOX if box else LIVE}
        source = "offer_override"
    else:
        source = "zone" if rule else "unserved"

    if not rule:
        # No zone claims this country and the tenant set no catch-all. Not served, and NOT free.
        return {"options": [], "mode": "", "source": "unserved", "needs": "zone"}

    kind = rule.get("type")
    amount: int | None
    needs = ""
    if kind == ZONE_FREE:
        amount = 0
    elif kind == ZONE_FLAT:
        amount = _whole(rule.get("amount"))
    elif kind == FLAT_RATE_BOX:
        amount = flat_rate_for_box(box, country) if box else None
        if amount is None:
            needs = "box_price"
    else:  # live
        amount = None
        needs = "carrier"

    if amount is None:
        # Deliberately no options rather than a zero-priced one. The caller must ask a carrier, or say it
        # cannot quote -- never present "free" for a price nobody has worked out.
        return {"options": [], "mode": CHARGED, "source": source, "needs": needs}

    # One option per service the tenant offers here, all at the zone's price. Differential pricing per speed
    # is what `live` and `flat_rate_box` are for; a flat zone charges the same whatever the buyer picks.
    options = [normalize_option({
        "label": _text(service.get("label")) or _text(service.get("service_token")),
        "amount": amount,
        "service_token": _text(service.get("service_token")),
        "carrier": _text(service.get("carrier")),
        "transit_days_min": service.get("transit_days_min"),
        "transit_days_max": service.get("transit_days_max"),
    }) for service in services]
    options = [opt for opt in options if opt]
    if not options:
        # A priced zone with no services still charges: the buyer is simply not offered a choice of speed.
        options = [normalize_option({"label": "Shipping", "amount": amount})]
        options = [opt for opt in options if opt]

    return {"options": options[:MAX_OPTIONS],
            "mode": CHARGED if amount > 0 else FREE,
            "source": source, "needs": ""}


def checkout_shipping(offer: dict[str, Any] | None, tenant_config: dict[str, Any] | None, *,
                      merchandise_amount: Any = 0, item_count: int = 1,
                      box: dict[str, Any] | None = None,
                      countries: list[str] | None = None) -> dict[str, Any]:
    """What a hosted Checkout Session may charge for shipping when NO page element asked the buyer anything.

    plans/SHIPPING_ELEMENT.md phase 3 — the author's "offer B": physical goods, shipping handled
    automatically, the buyer never presented with a choice.

    **The constraint that shapes this: Stripe presents ONE shipping list to every buyer, whatever address they
    type.** `shipping_options` is fixed when the session is created and Stripe never asks us again. So
    zone-derived pricing is only safe here when every destination the tenant allows agrees on the price:

        US $7.00, CA $12.99   ->  no single option is right for both. Charge nothing, say why.
        US $7.00, CA $7.00    ->  one option, correct for everyone who can reach checkout.

    Returns `{options, countries, reason}`. A `reason` with no options is the honest outcome, not a failure:
    it names what stopped us so a tenant can see why their zones are not being charged, rather than
    discovering it as silently free shipping. Per-destination pricing needs the buyer's country BEFORE the
    session, which is what the Shipping Element exists to collect.
    """
    if not ships_at_all(offer):
        return {"options": [], "countries": [], "reason": "this offer does not ship"}

    # An explicit per-offer table is destination-independent by construction -- the tenant typed the numbers --
    # so it needs none of the agreement checking below.
    explicit = options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count)
    if explicit:
        return {"options": explicit, "countries": [], "reason": ""}

    from stripe_link.domain.shipping_zones import allowed_countries

    destinations = [c for c in (countries or allowed_countries(tenant_config)) if c]
    if not destinations:
        return {"options": [], "countries": [],
                "reason": "no shipping zones are configured, so nothing is charged"}

    resolved: dict[str, dict[str, Any]] = {}
    for country in destinations:
        result = resolve_options(offer, tenant_config, country=country,
                                 merchandise_amount=merchandise_amount, item_count=item_count, box=box)
        if result["needs"]:
            # One unpriceable destination poisons the whole session, because the buyer picks the country
            # AFTER these options are fixed. Better to charge nothing than to quote a price that is only
            # right for some of the people who can reach the page.
            return {"options": [], "countries": destinations,
                    "reason": (f"shipping to {country} needs {result['needs'].replace('_', ' ')}, "
                               f"and Stripe cannot ask again once checkout opens")}
        resolved[country] = result

    # "Agree" means the same priced services, not merely the same total: a buyer offered Ground-only in one
    # country and Ground-plus-Overnight in another is being shown a list that is wrong for one of them.
    def signature(result: dict[str, Any]) -> tuple:
        return tuple((opt["label"], opt["amount"]) for opt in result["options"])

    signatures = {country: signature(result) for country, result in resolved.items()}
    distinct = set(signatures.values())
    if len(distinct) > 1:
        disagreeing = ", ".join(
            f"{country} {[amount for _, amount in sig] or 'nothing'}"
            for country, sig in sorted(signatures.items()))
        return {"options": [], "countries": destinations,
                "reason": (f"shipping costs differ by destination ({disagreeing}) and Stripe shows one list "
                           f"to every buyer, so nothing is charged. A shipping element on the page can ask "
                           f"the buyer's country first.")}

    return {"options": resolved[destinations[0]]["options"], "countries": destinations, "reason": ""}
