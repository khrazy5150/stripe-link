"""Coupon rules Stripe cannot express — Option B's evaluation engine (plans/COUPONS_COMPLETION.md).

Everything a coupon did before today was expressible as a Stripe Coupon: a percentage, a fixed amount,
optionally scoped to a product list (Option A). Stripe evaluated it, and that is still the right answer for
those — it is cheaper, and the discount is Stripe's own object.

A TIERED rule is the first thing Stripe has no vocabulary for: "spend $100, get 20% off; spend $250, get
30%". The qualifying amount is a property of the cart, not of any product, so no durable Coupon can
represent it. We evaluate it, and hand Stripe the number.

The split, restated, because it is the whole architecture:

    tenant Coupon   a durable, immutable, tenant-owned pricing RULE      (unchanged under both options)
    evaluation      Stripe's job (A) or ours (B)                         <- the fork
    Stripe Coupon   A: durable, one per tenant coupon
                    B: disposable, one per checkout, an execution artifact

This module is the "ours" half, and it is deliberately PURE: no Stripe, no repositories, no clock. What it
returns is an amount in minor units; materializing that as something Stripe will accept belongs to the
caller, which is the only part that needs a network.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Rule types this module evaluates. Anything not named here is Stripe's to evaluate (Option A), which is
# the default and stays the default -- B is for what A cannot say.
PLATFORM_EVALUATED = ("tiered",)


def is_platform_evaluated(coupon: dict[str, Any]) -> bool:
    """Whether WE work this coupon's discount out, rather than Stripe.

    Read off the rule itself rather than stored as a flag: a coupon is platform-evaluated because of what
    it says, and a flag that could disagree with the rule is a flag that eventually will.
    """
    return str(((coupon or {}).get("discount") or {}).get("type") or "") in PLATFORM_EVALUATED


def normalized_tiers(discount: dict[str, Any]) -> list[dict[str, Any]]:
    """The rule's tiers, ordered by threshold ascending, with the shape already checked by the validator."""
    tiers = []
    for tier in (discount or {}).get("tiers") or []:
        if not isinstance(tier, dict):
            continue
        tiers.append({
            "min_subtotal": int(tier.get("min_subtotal") or 0),
            "percent": Decimal(str(tier.get("percent") or 0)),
        })
    return sorted(tiers, key=lambda tier: tier["min_subtotal"])


def matching_tier(discount: dict[str, Any], subtotal: int) -> dict[str, Any] | None:
    """The BEST tier the subtotal reaches, or None when it reaches none.

    Best = highest threshold met, not first match. A buyer who spends enough for the 30% tier must not be
    given 20% because that tier was listed first -- the tenant wrote a ladder, and a ladder is climbed.
    """
    reached = [tier for tier in normalized_tiers(discount) if subtotal >= tier["min_subtotal"]]
    return reached[-1] if reached else None


def qualifying_subtotal(lines: list[dict[str, Any]], scope_product_ids=None) -> int:
    """The part of the cart the rule looks at, in minor units.

    `scope_product_ids` narrows it the same way Option A's `applies_to_product_ids` does, so a tenant can
    say "spend $100 on coffee" rather than "$100 on anything". Empty means the whole cart.
    """
    scope = {str(pid) for pid in (scope_product_ids or []) if str(pid or "").strip()}
    total = 0
    for line in lines or []:
        if scope and str(line.get("product_id") or "") not in scope:
            continue
        total += int(line.get("amount") or 0) * max(1, int(line.get("quantity") or 1))
    return total


def evaluate(coupon: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Work out what this rule is worth against these lines.

    Returns `{"amount_off": int, "qualifying_amount": int, "reason": str}`. `amount_off` of 0 means the
    rule matched nothing -- a cart below every threshold -- which is NOT an error and NOT a refusal: the
    tenant said "spend $100 to get 20%", and a buyer who spent $40 simply has not.

    Rounding is HALF UP on the minor unit, the same direction a shopper expects and the same one Stripe
    uses for percentage coupons, so our number and theirs agree on the cent.
    """
    discount = (coupon or {}).get("discount") or {}
    scope = (coupon or {}).get("applies_to_product_ids") or []
    subtotal = qualifying_subtotal(lines, scope)

    tier = matching_tier(discount, subtotal)
    if tier is None:
        lowest = normalized_tiers(discount)
        needed = lowest[0]["min_subtotal"] if lowest else 0
        return {"amount_off": 0, "qualifying_amount": subtotal,
                "reason": f"below the first tier ({subtotal} < {needed})"}

    amount = (Decimal(subtotal) * tier["percent"] / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    amount_off = int(amount)
    # Never discount more than the qualifying amount, whatever the tenant typed. A 120% tier is refused by
    # the validator, but a rule read back from storage predates whatever the validator says today.
    amount_off = max(0, min(amount_off, subtotal))
    return {
        "amount_off": amount_off,
        "qualifying_amount": subtotal,
        "reason": f"{tier['percent']}% at {tier['min_subtotal']}",
    }


def lines_from_resolved(resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """The cart, as this module wants it, from what `resolve_offer` already produced.

    One shape conversion in one place: the evaluator should not know what a resolved offer looks like, and
    the checkout handler should not know what the evaluator wants.
    """
    lines = []
    for item in (resolved or {}).get("items") or []:
        lines.append({
            "product_id": str(item.get("product_id") or ""),
            "amount": int(item.get("unit_amount") or item.get("amount") or 0),
            "quantity": int(item.get("quantity") or 1),
        })
    return lines
