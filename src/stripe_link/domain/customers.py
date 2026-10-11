"""A customer is the SUM of what they bought, not the last thing they bought.

Two defects this exists to fix, found 2026-10-11 from a Dashboard reading "Customers 0" beside eight
orders:

**1. A repeat buyer was overwritten.** `customer_record_from_session` builds a whole record with
`total_orders: 1`, `lifetime_value: <this order>` and a one-entry `transaction_history`, and the webhook
`put` it. A plain put. So a customer's second purchase reset their lifetime value to the price of that
purchase, discarded the first transaction, and left `total_orders` at 1 forever. Every repeat-customer
figure in the product was the most recent order wearing a cumulative name.

**2. A subscription renewal recorded no customer at all.** The renewal path writes an order and a ledger
entry; `customers_repo` appears nowhere in it. A subscriber therefore never appeared in Customers, and a
subscriber who was already there stopped growing after their signup. For a business whose revenue IS
renewals, the customer list is then a list of people who once signed up.

**Why merging lives here rather than in the handler.** Both paths need identical arithmetic, and the
second was written without the first — which is how they came to disagree about whether a customer
accumulates at all.
"""
from __future__ import annotations

from typing import Any

# Transaction history is a convenience for the Customers screen, not the ledger. The ledger is the
# financial record and is append-only; this is the most recent slice, bounded so a weekly subscriber of
# three years does not carry 156 rows into every read of their own record.
MAX_TRANSACTIONS = 50


def merge_customer(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """`existing` updated with `incoming`, accumulating rather than replacing.

    Returns `incoming` unchanged when there is nothing to merge, so a first purchase is unaffected.
    """
    if not isinstance(existing, dict) or not existing:
        return incoming
    if not isinstance(incoming, dict) or not incoming:
        return existing

    # IS THIS A PAYMENT WE HAVE ALREADY COUNTED? Stripe redelivers, so this function is called more than
    # once for the same money, and the totals have to survive that on their own. Keying the ARITHMETIC to
    # the same de-duplication the history uses makes the merge idempotent whatever the caller does --
    # which matters because the caller's own guard is a separate conditional write that this must not
    # depend on being correct.
    already = {str(row.get("transaction_id") or "")
               for row in (existing.get("transaction_history") or []) if isinstance(row, dict)}
    arriving = [str(row.get("transaction_id") or "")
                for row in (incoming.get("transaction_history") or []) if isinstance(row, dict)]
    counted_before = bool(arriving) and all(ref and ref in already for ref in arriving)

    merged = {**existing, **incoming}
    merged["contact"] = _merged_contact(existing.get("contact"), incoming.get("contact"))
    merged["summary"] = _merged_summary(existing.get("summary"), incoming.get("summary"),
                                        counted_before=counted_before)
    merged["transaction_history"] = _merged_transactions(
        existing.get("transaction_history"), incoming.get("transaction_history"))
    merged["product_affinity"] = _merged_affinity(
        existing.get("product_affinity"), incoming.get("product_affinity"))
    return merged


def _merged_contact(existing: Any, incoming: Any) -> dict[str, Any]:
    """Later wins, but only where it actually says something.

    A renewal invoice often carries no name or phone -- Stripe puts them on the Customer, not the
    invoice -- and letting an empty string overwrite a name the checkout captured would erase the only
    identity the tenant has for that buyer.
    """
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    out = dict(existing)
    for key, value in incoming.items():
        if str(value or "").strip() and str(value).strip().lower() != "unknown":
            out[key] = value
    return out or incoming


def _merged_summary(existing: Any, incoming: Any, *, counted_before: bool = False) -> dict[str, Any]:
    """The accumulated totals. `counted_before` means this exact payment is already in them.

    `last_order_at` is still advanced on a redelivery, because the event really did refer to that
    payment; only the money and the count are held still.
    """
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    add_orders = 0 if counted_before else _int(incoming.get("total_orders", 1))
    add_value = 0 if counted_before else _int(incoming.get("lifetime_value"))
    return {
        **existing,
        **incoming,
        "total_orders": _int(existing.get("total_orders")) + add_orders,
        "lifetime_value": _int(existing.get("lifetime_value")) + add_value,
        # The LATEST, not the incoming: events can be delivered out of order, and a retried older
        # invoice must not drag a customer's "last seen" backwards.
        "last_order_at": max(_int(existing.get("last_order_at")), _int(incoming.get("last_order_at"))),
        "currency": incoming.get("currency") or existing.get("currency") or "usd",
    }


def _merged_transactions(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    """Newest first, de-duplicated by transaction id.

    **De-duplication is not optional.** Stripe redelivers, and this function is called on every delivery;
    without it a retried webhook would add the same payment again and inflate the customer's history --
    and, through `total_orders` and `lifetime_value`, their worth.
    """
    rows = [row for row in (incoming or []) if isinstance(row, dict)]
    rows += [row for row in (existing or []) if isinstance(row, dict)]
    seen, out = set(), []
    for row in rows:
        key = str(row.get("transaction_id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    out.sort(key=lambda row: _int(row.get("created_at")), reverse=True)
    return out[:MAX_TRANSACTIONS]


def _merged_affinity(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    """Every product this customer has bought, once each. Blank ids are dropped rather than stored as a
    nameless entry nothing can act on."""
    rows = [row for row in (existing or []) if isinstance(row, dict)]
    rows += [row for row in (incoming or []) if isinstance(row, dict)]
    seen, out = set(), []
    for row in rows:
        key = str(row.get("product_id") or "") or str(row.get("product_name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
