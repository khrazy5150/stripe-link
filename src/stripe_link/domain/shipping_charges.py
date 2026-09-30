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
    payload: list[dict[str, Any]] = []
    for option in options_for(offer, merchandise_amount=merchandise_amount, item_count=item_count):
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
