"""Transaction ledger — pure builders for append-only financial entries.

Amounts are signed minor units from the tenant's-cash perspective (inflow +, outflow -),
so summing a component across entries yields its running total — no stored net/profit that
can drift. Builders take magnitudes and enforce the sign convention per entry type.

This is the minimal, order-level primitive (PRD Phase 5 groundwork). Rollups, per-line
entries, COGS capture, the platform-revenue book, and RefundsTable/WebhookEvents
consolidation are the fuller design in plans/TRANSACTION_LEDGER_STRIPE_LINK.md.
"""
from typing import Any

LEDGER_SCHEMA_VERSION = "2026-07-07"

AMOUNT_COMPONENTS = ("gross", "stripe_fee", "platform_fee", "tax", "cogs", "shipping_cost")


def _clean_amounts(**components: int) -> dict[str, int]:
    # Store only non-zero components; every value is an int (minor units).
    return {key: int(value) for key, value in components.items() if int(value or 0) != 0}


def _entry(
    *,
    tenant_id: str,
    entry_id: str,
    entry_type: str,
    occurred_at: int,
    mode: str,
    currency: str,
    amounts: dict[str, int],
    idempotency_key: str,
    order_id: str | None = None,
    offer_id: str | None = None,
    product_id: str | None = None,
    customer: dict[str, Any] | None = None,
    stripe: dict[str, Any] | None = None,
    source: str = "webhook",
    description: str | None = None,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "document_type": "ledger_entry",
        "tenant_id": str(tenant_id),
        "entry_id": str(entry_id),
        "entry_type": entry_type,
        "occurred_at": int(occurred_at),
        "mode": mode if mode in {"test", "live"} else "test",
        "currency": str(currency or "usd").lower(),
        "amounts": amounts,
        "idempotency_key": str(idempotency_key),
        "source": source,
        "created_at": int(now_epoch if now_epoch is not None else occurred_at),
    }
    if order_id:
        document["order_id"] = str(order_id)
    if offer_id:
        document["offer_id"] = str(offer_id)
    if product_id:
        document["product_id"] = str(product_id)
    if customer:
        ref = {key: customer[key] for key in ("email", "name") if customer.get(key)}
        if ref:
            document["customer_ref"] = ref
    if stripe:
        refs = {key: value for key, value in stripe.items() if value}
        if refs:
            document["stripe"] = refs
    if description:
        document["description"] = description
    return document


def sale_entry(
    *,
    tenant_id: str,
    entry_id: str,
    occurred_at: int,
    mode: str,
    currency: str,
    gross: int,
    stripe_fee: int = 0,
    platform_fee: int = 0,
    tax: int = 0,
    cogs: int = 0,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """A sale: customer pays (gross +); Stripe and platform fees and COGS reduce the
    tenant's cash (stored negative); collected tax is a liability (+)."""
    amounts = _clean_amounts(
        gross=abs(int(gross)),
        stripe_fee=-abs(int(stripe_fee)),
        platform_fee=-abs(int(platform_fee)),
        tax=abs(int(tax)),
        cogs=-abs(int(cogs)),
    )
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="sale", occurred_at=occurred_at,
        mode=mode, currency=currency, amounts=amounts, idempotency_key=idempotency_key, **kwargs,
    )


def refund_entry(
    *,
    tenant_id: str,
    entry_id: str,
    occurred_at: int,
    mode: str,
    currency: str,
    refund_amount: int,
    stripe_fee_returned: int = 0,
    tax_reversed: int = 0,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """A refund: gross reverses (-); the platform keeps its application fee (0);
    Stripe fees are returned only if refunded (usually 0); collected tax reverses (-)."""
    amounts = _clean_amounts(
        gross=-abs(int(refund_amount)),
        stripe_fee=abs(int(stripe_fee_returned)),
        platform_fee=0,
        tax=-abs(int(tax_reversed)),
    )
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="refund", occurred_at=occurred_at,
        mode=mode, currency=currency, amounts=amounts, idempotency_key=idempotency_key, **kwargs,
    )


def sale_entry_from_order(order: dict[str, Any], *, now_epoch: int) -> dict[str, Any] | None:
    """Build a sale entry from a checkout order document. Returns None if there is no
    payable amount or identity to key on. The entry_id is deterministic (le_sale_<pi/order>)
    so a duplicate webhook overwrites the same row — idempotent by primary key."""
    gross = int(order.get("amount_paid") or order.get("amount_total") or 0)
    payment_intent = str(order.get("payment_intent_id") or "").strip()
    order_id = str(order.get("order_id") or "").strip()
    key_ref = payment_intent or order_id
    if not gross or not key_ref:
        return None
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else None
    return sale_entry(
        tenant_id=str(order.get("tenant_id") or ""),
        entry_id=f"le_sale_{key_ref}",
        occurred_at=int(order.get("created_at") or now_epoch),
        mode="live" if order.get("mode") == "live" else "test",
        currency=str(order.get("currency") or "usd"),
        gross=gross,
        stripe_fee=int(order.get("stripe_fee") or 0),
        platform_fee=int(order.get("platform_fee") or 0),
        idempotency_key=f"sale:{key_ref}",
        order_id=order_id or None,
        offer_id=str(order.get("offer_id") or "") or None,
        product_id=str(order.get("product_id") or "") or None,
        customer=customer,
        stripe={"payment_intent_id": payment_intent} if payment_intent else None,
        now_epoch=now_epoch,
    )


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Derived totals — pure sums over the additive components (never stored)."""
    totals = {key: 0 for key in AMOUNT_COMPONENTS}
    counts: dict[str, int] = {}
    for entry in entries:
        for key, value in (entry.get("amounts") or {}).items():
            totals[key] = totals.get(key, 0) + int(value or 0)
        entry_type = str(entry.get("entry_type") or "")
        counts[entry_type] = counts.get(entry_type, 0) + 1
    net = totals["gross"] + totals["stripe_fee"] + totals["platform_fee"]
    profit = net + totals["cogs"] + totals["shipping_cost"] - totals["tax"]
    return {
        "totals": totals,
        "net": net,
        "profit": profit,
        "tax_liability": totals["tax"],
        "counts": counts,
    }
