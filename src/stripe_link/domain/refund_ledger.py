"""Refund aggregate + ledger logic (pure -- no I/O).

An order carries running payment aggregates (amount_paid/refunded, refundable_amount,
refund_count, last_refund_at, payment_status). Each refund is also appended to an immutable
refunds ledger. This module computes both, so the handler and webhook stay thin.
"""

from typing import Any

PAYMENT_STATUSES = {"paid", "partially_refunded", "refunded", "disputed", "cancelled", "completed"}


def payment_status_after_refund(amount_paid: int, amount_refunded: int) -> str:
    if amount_refunded <= 0:
        return "paid"
    if amount_refunded >= amount_paid:
        return "refunded"
    return "partially_refunded"


def order_paid_amount(order: dict[str, Any]) -> int:
    return int(order.get("amount_paid") or order.get("amount_total") or 0)


def set_refund_aggregates(
    order: dict[str, Any],
    *,
    amount_refunded: int,
    refund_count: int,
    at: int,
    disputed: bool = False,
) -> dict[str, Any]:
    """Return the order with refund aggregates set to authoritative totals."""
    amount_paid = order_paid_amount(order)
    amount_refunded = int(amount_refunded)
    refundable = max(0, amount_paid - amount_refunded)
    status = "disputed" if disputed else payment_status_after_refund(amount_paid, amount_refunded)
    return {
        **order,
        "amount_paid": amount_paid,
        "amount_refunded": amount_refunded,
        "refundable_amount": refundable,
        "refund_count": int(refund_count),
        "last_refund_at": at,
        "payment_status": status,
        "updated_at": at,
    }


def initial_payment_aggregates(amount_total: int) -> dict[str, Any]:
    """Aggregates stamped on an order when it is first recorded as paid."""
    amount = int(amount_total or 0)
    return {
        "payment_status": "paid",
        "amount_paid": amount,
        "amount_refunded": 0,
        "refundable_amount": amount,
        "refund_count": 0,
        "last_refund_at": None,
    }


def build_refund_entry(
    *,
    refund_id: str,
    tenant_id: str,
    order_id: str,
    payment_intent_id: str,
    charge_id: str,
    amount: int,
    currency: str,
    reason: str,
    initiated_by: str,
    stripe_refund_id: str,
    status: str,
    created_at: int,
) -> dict[str, Any]:
    """An immutable refunds-ledger row."""
    return {
        "schema_version": "2026-05-29",
        "document_type": "refund",
        "tenant_id": tenant_id,
        "refund_id": refund_id,
        "order_id": order_id,
        "payment_intent_id": payment_intent_id,
        "charge_id": charge_id,
        "amount": int(amount or 0),
        "currency": str(currency or "usd"),
        "reason": str(reason or ""),
        "initiated_by": str(initiated_by or ""),
        "stripe_refund_id": str(stripe_refund_id or ""),
        "status": str(status or ""),
        "created_at": int(created_at),
    }
