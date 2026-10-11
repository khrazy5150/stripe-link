"""What the tenant PAID for the goods in a sale.

`domain/ledger.py` has declared `cogs` as one of its six amount components since the ledger was written,
and `sale_entry(cogs=...)` has always negated and stored it. **Nothing ever passed a non-zero value**, so
`profit` has been revenue-minus-fees wearing the word "profit" — and `Reports.vue` has been showing it.
This module is the missing supply (plans/MONEY_ACROSS_SILOS.md P2).

**Absent is not zero, and the distinction is the whole design.** A tenant who has not recorded a cost is
not a tenant with no costs. Treating unknown as zero inflates margin silently, which is the same class of
lie as a failed ledger read displayed as $0 revenue. So every function here returns the count of lines it
could NOT price alongside the total, and the ledger refuses to claim profit while that count is non-zero.

**Why the cost rides in Stripe metadata rather than being looked up later.** It is an immutable snapshot
at the moment of sale. A tenant who corrects a product's cost next month must not retroactively rewrite
last month's margin, and a product that is later deleted must not take its own history with it. Same
reasoning as the frozen `tip_keyed_amount` and the stamped `order_bump_shipping`: the last moment both
facts are in hand is the moment to write them down.
"""
from __future__ import annotations

from typing import Any

# Stripe metadata keys. Deliberately short -- a key may be 40 characters and a session already carries ~14
# keys against a limit of 50.
TOTAL_KEY = "cogs"
UNKNOWN_KEY = "cogs_unknown"
BUMP_KEY = "bump_cogs"


def unit_cost(product: dict[str, Any] | None) -> int | None:
    """The product's acquisition cost per unit, or None when it has none recorded.

    `None` and `0` are different answers and both are legitimate: a digital download really may cost
    nothing to deliver, while a product nobody has costed is simply unknown. Returning `0` for the second
    is how a margin report starts lying.
    """
    if not isinstance(product, dict):
        return None
    raw = product.get("unit_cost")
    if raw is None:
        return None
    try:
        # int() rather than isinstance: a document read back from DynamoDB carries Decimal, and an
        # isinstance check against int passes on a fixture and fails on stored data -- which 404'd
        # published pages once already.
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def items_cogs(items, products_by_id: dict[str, Any]) -> tuple[int, int]:
    """`(total_cost, lines_with_no_cost)` for the resolved checkout items.

    Service lines are counted as unpriceable rather than free. A service has a labour cost that this
    codebase has nowhere to record -- `plans/SERVICES_IN_OFFERS.md` is design-only -- and calling it zero
    would report a service business's entire revenue as profit.
    """
    total = 0
    unknown = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "service" or item.get("service_id"):
            unknown += 1
            continue
        cost = unit_cost(products_by_id.get(str(item.get("product_id") or "")))
        if cost is None:
            unknown += 1
            continue
        total += cost * max(1, int(item.get("quantity") or 1))
    return total, unknown


def encode_bump_costs(pairs) -> str:
    """`"stripe_price_id:cost,..."` for the bumps whose cost is known.

    Same wire format as `order_bump_shipping`, for the same reason: an order bump is ticked on Stripe's
    hosted page AFTER the session is created, so at stamp time we know what each bump WOULD cost but not
    which the buyer will take. The webhook, which sees the purchased lines, adds up the ones they did.
    """
    out = []
    for stripe_price_id, cost in pairs or []:
        if not stripe_price_id or cost is None:
            continue
        out.append(f"{stripe_price_id}:{int(cost)}")
    return ",".join(out)


def decode_bump_costs(raw: Any) -> dict[str, int]:
    """`{stripe_price_id: cost}` from the stamp. `{}` when absent or unreadable.

    Tolerant, exactly like `bump_postage_from_metadata`: this decides what a sale's margin was, never
    whether the order is recorded. A malformed pair costs one line's cost, not the sale.
    """
    out: dict[str, int] = {}
    for pair in str(raw or "").split(","):
        stripe_price_id, _, amount = pair.partition(":")
        stripe_price_id = stripe_price_id.strip()
        if not stripe_price_id:
            continue
        try:
            out[stripe_price_id] = int(str(amount).strip())
        except (TypeError, ValueError):
            continue
    return out


def stamp(total: int, unknown: int, bump_costs: str = "") -> dict[str, str]:
    """The metadata keys to stamp, omitting every one that says nothing.

    A digital offer with no costs recorded adds NO keys at all, which matters against Stripe's 50-key
    ceiling on a session that already carries about fourteen.
    """
    out: dict[str, str] = {}
    if total:
        out[TOTAL_KEY] = str(int(total))
    if unknown:
        out[UNKNOWN_KEY] = str(int(unknown))
    if bump_costs:
        out[BUMP_KEY] = bump_costs
    return out


def from_metadata(metadata: dict[str, Any] | None, *, purchased_bumps=()) -> dict[str, Any]:
    """`{"cogs": int, "unknown_lines": int, "known": bool}` for a completed session.

    `purchased_bumps` are `(stripe_price_id, quantity)` for the bump lines the buyer actually took. The
    quantity is not optional sugar: the stamped cost is PER UNIT, exactly as the postage surcharge is, and
    `bump_postage_collected` multiplies by quantity for the same reason. A bump taken three times cost us
    three times as much, and summing the unit cost once understates COGS and overstates margin -- the
    precise failure this whole component exists to stop.

    A bump with no stamped cost counts against completeness: the buyer bought something we cannot price,
    so the sale's margin is not knowable even though the base lines were.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    total = _int(metadata.get(TOTAL_KEY))
    unknown = _int(metadata.get(UNKNOWN_KEY))
    bumps = decode_bump_costs(metadata.get(BUMP_KEY))
    for stripe_price_id, quantity in purchased_bumps or ():
        cost = bumps.get(str(stripe_price_id))
        if cost is None:
            unknown += 1
        else:
            total += cost * max(1, int(quantity or 1))

    # NOTHING STAMPED AT ALL is its own case, and it is unknown rather than complete-and-free. Every
    # session created before this shipped looks exactly like this, and reporting their profit as equal to
    # their revenue would be the inflated-margin bug arriving through the back door.
    if not metadata.get(TOTAL_KEY) and not metadata.get(UNKNOWN_KEY) and not metadata.get(BUMP_KEY):
        return {"cogs": 0, "unknown_lines": 0, "known": False}
    return {"cogs": total, "unknown_lines": unknown, "known": unknown == 0}


def _int(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0
