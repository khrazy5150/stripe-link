"""Does this refund have to wait for the goods to come back?

plans/ORDER_FULFILMENT.md R1, and the author's rule: **if a product requires a physical return, no Stripe
refund is issued until the product is received.**

Most of the vocabulary already existed. `Product.refund_policy.return_method` has carried
`return_required`, `no_return_customer_keeps` and `digital_revoke_access` since the schema was written --
this reads it rather than inventing a second way to say the same thing.

The rule is right for physical goods and it is NOT free, which is why `keep_it_below` exists: when return
postage costs more than the item is worth, asking for it back loses money, and a buyer held for three
weeks files a chargeback that costs more than the refund would have. Withholding a refund does not remove
risk -- it trades refund risk for dispute risk.
"""
from typing import Any

RETURN_REQUIRED = "return_required"
KEEPS = "no_return_customer_keeps"
REVOKE = "digital_revoke_access"

# RefundRequest states. The leg between `approved` and `refunded` is the whole of R1: `approved` goes back
# to meaning "the claim is valid" rather than "the money is going back now".
RETURN_PENDING = "return_pending"
RETURN_IN_TRANSIT = "return_in_transit"
RETURN_RECEIVED = "return_received"
RETURN_STATES = (RETURN_PENDING, RETURN_IN_TRANSIT, RETURN_RECEIVED)

# A return label the buyer never uses cannot be left open forever: it holds the tenant's money hostage and
# the refund window is finite. The author's figure.
DEFAULT_RETURN_WINDOW_DAYS = 3


def _policy(product: dict[str, Any]) -> dict[str, Any]:
    policy = (product or {}).get("refund_policy")
    return policy if isinstance(policy, dict) else {}


def return_requirement(lines: list[dict[str, Any]], products_by_id: dict[str, dict[str, Any]],
                       *, order_total: int = 0, keep_it_below: int | None = None) -> dict[str, Any]:
    """Whether these goods have to come back before money goes out.

    Returns `{required, reason, products, keep_it}`. `keep_it` means a return WAS required and is being
    waived because the goods are worth less than the postage to retrieve them.
    """
    requiring: list[dict[str, str]] = []
    for line in lines or []:
        product = products_by_id.get(str(line.get("product_id") or "").strip())
        if not product:
            continue
        policy = _policy(product)
        method = str(policy.get("return_method") or "").strip()
        fulfillment = product.get("fulfillment") or {}
        # A download cannot be posted back, whatever the policy says. Physical-return language on a
        # digital product is a trap the tenant set for themselves, not an instruction to follow.
        if fulfillment.get("requires_shipping") is False or method == REVOKE:
            continue
        if method == RETURN_REQUIRED:
            requiring.append({"product_id": str(product.get("product_id") or ""),
                              "name": str(product.get("name") or "")})

    if not requiring:
        return {"required": False, "reason": "", "products": [], "keep_it": False}

    if keep_it_below and order_total and int(order_total) < int(keep_it_below):
        return {
            "required": False,
            "keep_it": True,
            "products": requiring,
            "reason": "Worth less than the postage to get it back — refunded without a return.",
        }

    names = [item["name"] for item in requiring if item["name"]]
    one = len(names) == 1
    return {
        "required": True,
        "keep_it": False,
        "products": requiring,
        "reason": (f"{', '.join(names)} must come back before the refund is released."
                   if names else "The goods must come back before the refund is released."),
    }


def policy_snapshot(lines: list[dict[str, Any]], products_by_id: dict[str, dict[str, Any]],
                    *, order_total: int = 0, keep_it_below: int | None = None,
                    window_days: int = DEFAULT_RETURN_WINDOW_DAYS) -> dict[str, Any]:
    """The terms as they stood WHEN THE BUYER ASKED.

    `RefundRequest.policy_snapshot` already exists for exactly this reason: a tenant editing their policy
    must not retroactively change the terms of a return already in flight. The buyer agreed to what was
    written at the time.
    """
    requirement = return_requirement(lines, products_by_id, order_total=order_total,
                                     keep_it_below=keep_it_below)
    return {
        "return_required": bool(requirement["required"]),
        "keep_it": bool(requirement["keep_it"]),
        "reason": requirement["reason"],
        "products": requirement["products"],
        "return_window_days": int(window_days),
        "keep_it_below": int(keep_it_below) if keep_it_below else None,
    }


def next_status_after_approval(snapshot: dict[str, Any] | None) -> str:
    """What `approved` leads to. The entire R1 change lives in this one decision."""
    return RETURN_PENDING if (snapshot or {}).get("return_required") else "approved"


def can_release_refund(request: dict[str, Any]) -> tuple[bool, str, str]:
    """May the money go back yet? Returns `(allowed, why_not, error_code)`.

    The gate the author asked for. It is deliberately a function of the REQUEST's own recorded state, not
    of the product's policy as it stands today -- a policy edited mid-return must not release a refund for
    goods still in the post, nor trap one whose return was already received.

    The code distinguishes the two refusals, because they are different problems: a request still sitting
    at `new` has not been DECIDED, while one at `return_pending` has been decided and is waiting on a
    parcel. Telling a tenant "awaiting return" about a request nobody has approved sends them looking for
    a parcel that was never asked for.
    """
    status = str((request or {}).get("status") or "")
    if status in (RETURN_RECEIVED, "approved"):
        return True, "", ""
    if status in (RETURN_PENDING, RETURN_IN_TRANSIT):
        snapshot = (request or {}).get("policy_snapshot") or {}
        names = [p.get("name") for p in snapshot.get("products") or [] if p.get("name")]
        what = ", ".join(names) if names else "the goods"
        return (False,
                f"Waiting for {what} to come back. Mark the return received to release the refund.",
                "awaiting_return")
    return False, "Only approved refund requests can be executed.", "not_approved"


def return_deadline(request: dict[str, Any], *, now: int) -> int:
    """When an unused return label stops being the tenant's problem."""
    snapshot = (request or {}).get("policy_snapshot") or {}
    days = int(snapshot.get("return_window_days") or DEFAULT_RETURN_WINDOW_DAYS)
    started = int(request.get("return_started_at") or request.get("updated_at") or now)
    return started + days * 86400


def return_label_expired(request: dict[str, Any], *, now: int) -> bool:
    """Has the buyer's window to post it back lapsed?

    The author's rule: the buyer has about three days to act or forfeits the free return postage. Enforced
    where the label is ISSUED rather than by a sweep that closes the request, because the two are
    different consequences: a lapsed window costs the buyer free postage, it does not by itself decide
    their refund. Whether to close the request as well is the tenant's call.
    """
    expires_at = int((request or {}).get("return_label_expires_at") or 0)
    return bool(expires_at) and int(now) > expires_at


def advance_to_in_transit(request: dict[str, Any], *, now: int) -> dict[str, Any]:
    """A carrier scan says the parcel is moving. It does NOT say it arrived, or that the right item is in
    it -- which is why `return_received` stays the tenant's decision (R1).

    The scan itself will come from the provider's tracking webhook, which belongs to §P3; this is the
    transition it drives, kept here so both callers agree on what a scan means.
    """
    updated = dict(request or {})
    if str(updated.get("status") or "") == RETURN_PENDING:
        updated["status"] = RETURN_IN_TRANSIT
        updated["return_in_transit_at"] = int(now)
        updated["updated_at"] = int(now)
    return updated
