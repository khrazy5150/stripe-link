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

# A PARTITION of an additive component, never an addition to it. `shipping_revenue` is the part of `gross` the
# buyer paid for postage -- it is already inside `gross`, so adding it to `net` or `profit` would count the
# same money twice (plans/SHIPPING_CHARGES.md).
#
# Kept in its own tuple rather than appended to AMOUNT_COMPONENTS because that tuple's contract is stated in
# this module's docstring: summing a component across entries yields its running total, and every one of them
# is additive from the tenant's-cash perspective. A breakdown key sitting in the same list is an invitation for
# the next person to add it up. `summarize` reports it and excludes it from both derived figures, and a test
# pins that net and profit are unchanged by its presence.
BREAKDOWN_COMPONENTS = ("shipping_revenue",)


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
    shipping_revenue: int = 0,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """A sale: customer pays (gross +); Stripe and platform fees and COGS reduce the
    tenant's cash (stored negative); collected tax is a liability (+).

    `shipping_revenue` is what the buyer paid for postage. It is a PARTITION of `gross`, not an addition to
    it -- see BREAKDOWN_COMPONENTS. Recording it is what lets shipping margin be separated from product
    margin later, which `gross` alone cannot express.
    """
    amounts = _clean_amounts(
        gross=abs(int(gross)),
        stripe_fee=-abs(int(stripe_fee)),
        platform_fee=-abs(int(platform_fee)),
        tax=abs(int(tax)),
        cogs=-abs(int(cogs)),
        shipping_revenue=abs(int(shipping_revenue)),
    )
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="sale", occurred_at=occurred_at,
        mode=mode, currency=currency, amounts=amounts, idempotency_key=idempotency_key, **kwargs,
    )


def shipping_cost_entry(
    *,
    tenant_id: str,
    entry_id: str,
    occurred_at: int,
    mode: str,
    currency: str,
    shipping_cost: int,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """What the CARRIER charged for a label. The other half of shipping margin.

    Its own entry rather than a field on the sale, because the ledger is append-only and the label is
    bought AFTER the sale -- sometimes days after, sometimes never. Editing the sale to add it would mean
    a financial row that changes after the fact, which is the one thing an append-only book exists to
    prevent.

    `shipping_cost` is an OUTFLOW and is stored negative, so `summarize`'s
    `shipping_margin = shipping_revenue + shipping_cost` is a sum rather than a subtraction, like every
    other component here. Until this existed nothing wrote `shipping_cost` at all -- it was in
    AMOUNT_COMPONENTS with no builder, so `shipping_margin` could only ever be None and a tenant could
    never learn whether their postage pricing made or lost money.
    """
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="shipping_cost", occurred_at=occurred_at,
        mode=mode, currency=currency,
        amounts=_clean_amounts(shipping_cost=-abs(int(shipping_cost))),
        idempotency_key=idempotency_key, **kwargs,
    )


def shipping_cost_entry_from_shipment(
    shipment: dict[str, Any], order: dict[str, Any], *, now_epoch: int,
) -> dict[str, Any] | None:
    """Build it from a purchased shipment. None when there is nothing to record.

    Keyed on the SHIPMENT, so a re-delivered webhook or a retried purchase overwrites the same row rather
    than double-counting postage the tenant only bought once.
    """
    cost = (shipment or {}).get("cost") or {}
    amount = int(cost.get("amount") or 0)
    shipment_id = str((shipment or {}).get("shipment_id") or "").strip()
    order_id = str((order or {}).get("order_id") or (shipment or {}).get("order_id") or "").strip()
    key_ref = shipment_id or order_id
    if not amount or not key_ref:
        return None
    return shipping_cost_entry(
        tenant_id=str((order or {}).get("tenant_id") or (shipment or {}).get("tenant_id") or ""),
        entry_id=f"le_ship_{key_ref}",
        occurred_at=int((shipment or {}).get("purchased_at") or now_epoch),
        mode="live" if (order or {}).get("mode") == "live" else "test",
        currency=str(cost.get("currency") or (order or {}).get("currency") or "usd"),
        shipping_cost=amount,
        idempotency_key=f"shipping_cost:{key_ref}",
        order_id=order_id or None,
        now_epoch=now_epoch,
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
    shipping_reversed: int = 0,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """A refund: gross reverses (-); the platform keeps its application fee (0);
    Stripe fees are returned only if refunded (usually 0); collected tax reverses (-).

    `shipping_reversed` is the postage that went back with it, and it is the CALLER's job to work out --
    a partial refund cannot be attributed between goods and shipping from the amount alone, and guessing
    would make shipping margin quietly wrong for every partially refunded order.
    """
    amounts = _clean_amounts(
        gross=-abs(int(refund_amount)),
        stripe_fee=abs(int(stripe_fee_returned)),
        platform_fee=0,
        tax=-abs(int(tax_reversed)),
        shipping_revenue=-abs(int(shipping_reversed)),
    )
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="refund", occurred_at=occurred_at,
        mode=mode, currency=currency, amounts=amounts, idempotency_key=idempotency_key, **kwargs,
    )


def dispute_entry(
    *,
    tenant_id: str,
    entry_id: str,
    occurred_at: int,
    mode: str,
    currency: str,
    dispute_amount: int,
    dispute_fee: int = 0,
    shipping_reversed: int = 0,
    idempotency_key: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """A chargeback: the money goes back to the buyer (gross -) and the card network charges for it.

    PRD Phase 5 names `dispute` as one of the four financial events that must append an entry, and until
    now only `charge.dispute.created`'s ORDER FLAG existed -- the ledger never heard about it. A disputed
    order therefore kept counting as revenue, which overstates every report containing one.

    The dispute fee is a cost of taking the payment, so it sits in `stripe_fee` beside the processing fee
    rather than inventing a component for it. Unlike a refund, the platform's application fee is NOT
    returned either -- the same asymmetry `refund_entry` already records.
    """
    amounts = _clean_amounts(
        gross=-abs(int(dispute_amount)),
        stripe_fee=-abs(int(dispute_fee)),
        shipping_revenue=-abs(int(shipping_reversed)),
    )
    return _entry(
        tenant_id=tenant_id, entry_id=entry_id, entry_type="dispute", occurred_at=occurred_at,
        mode=mode, currency=currency, amounts=amounts, idempotency_key=idempotency_key, **kwargs,
    )


def dispute_entry_from_event(dispute: dict[str, Any], order: dict[str, Any], *,
                             now_epoch: int) -> dict[str, Any] | None:
    """Build it from Stripe's dispute object. None when there is nothing to record.

    The dispute FEE lives on the dispute's own balance transactions, not on the dispute. Absent is zero --
    the chargeback itself is the figure that matters and a missing fee must not cost us the entry.
    """
    dispute_id = str((dispute or {}).get("id") or "").strip()
    amount = int((dispute or {}).get("amount") or 0)
    if not dispute_id or not amount:
        return None
    fee = 0
    for txn in (dispute or {}).get("balance_transactions") or []:
        if isinstance(txn, dict):
            fee += abs(int(txn.get("fee") or 0))
    order = order or {}
    return dispute_entry(
        tenant_id=str(order.get("tenant_id") or ""),
        entry_id=f"le_dispute_{dispute_id}",
        occurred_at=int((dispute or {}).get("created") or now_epoch),
        mode="live" if order.get("mode") == "live" else "test",
        currency=str((dispute or {}).get("currency") or order.get("currency") or "usd"),
        dispute_amount=amount,
        dispute_fee=fee,
        # A chargeback takes the WHOLE charge back, postage included -- unlike a partial refund, there is
        # nothing to attribute. Only reversed when the dispute covers the whole order.
        shipping_reversed=(int(order.get("shipping_amount") or 0)
                           if amount >= int(order.get("amount_total") or 0) > 0 else 0),
        idempotency_key=f"dispute:{dispute_id}",
        order_id=str(order.get("order_id") or "") or None,
        stripe={"dispute_id": dispute_id,
                "payment_intent_id": str((dispute or {}).get("payment_intent") or "")},
        now_epoch=now_epoch,
    )


def _fee_of(order: dict[str, Any], key: str) -> int:
    """A fee off an order document, from wherever that document keeps it.

    `fees` is the shape both webhook paths write (`{stripe_fee, platform_fee, net_payout, ...}`); the flat
    key is the fallback for anything older. Reading only the flat key is the bug this exists to prevent
    repeating -- it fails SILENTLY, as a zero, which is a legitimate value for a fee.
    """
    fees = order.get("fees")
    if isinstance(fees, dict) and fees.get(key) is not None:
        return int(fees.get(key) or 0)
    return int(order.get(key) or 0)


def sale_entry_from_order(order: dict[str, Any], *, now_epoch: int,
                          source: str = "webhook") -> dict[str, Any] | None:
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
        # NESTED under `fees`, which is where both order paths write them. Read flat, these were always
        # None and every ledger entry ever written recorded ZERO fees -- so `summarize`'s `net` equalled
        # `gross` and `profit` equalled `gross`, for every tenant, since the ledger shipped. A report built
        # on that tells a tenant their costs are nothing (found 2026-10-01 on a real dev order).
        #
        # The flat read is kept as a fallback because older entries and the invoice path may carry it that
        # way; `fees` wins when present.
        stripe_fee=_fee_of(order, "stripe_fee"),
        platform_fee=_fee_of(order, "platform_fee"),
        # Collected tax is the tenant's LIABILITY, not their income. Zero until Stripe Tax is enabled, and
        # zero is then the true answer -- but it has to be read for the day it is not.
        tax=int(order.get("tax_amount") or 0),
        # Written by `shipping_charges.buyer_paid_shipping` on both order paths. Absent on a digital order,
        # which is why `or 0` is safe here and a stored 0 would not have been (plans/SHIPPING_CHARGES.md).
        shipping_revenue=int(order.get("shipping_amount") or 0),
        idempotency_key=f"sale:{key_ref}",
        order_id=order_id or None,
        offer_id=str(order.get("offer_id") or "") or None,
        product_id=str(order.get("product_id") or "") or None,
        customer=customer,
        stripe={"payment_intent_id": payment_intent} if payment_intent else None,
        # Defaults to "webhook" because that is how nearly every sale arrives. An upsell does not: it is a
        # PaymentIntent the upsell handler creates and records itself, and labelling those rows "webhook"
        # made the ledger's one provenance field state the opposite of the truth.
        source=source,
        now_epoch=now_epoch,
    )


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Derived totals — pure sums over the additive components (never stored)."""
    totals = {key: 0 for key in AMOUNT_COMPONENTS + BREAKDOWN_COMPONENTS}
    counts: dict[str, int] = {}
    for entry in entries:
        for key, value in (entry.get("amounts") or {}).items():
            totals[key] = totals.get(key, 0) + int(value or 0)
        entry_type = str(entry.get("entry_type") or "")
        counts[entry_type] = counts.get(entry_type, 0) + 1
    # Deliberately names its inputs rather than summing `totals`: `shipping_revenue` is already inside
    # `gross`, so a blanket sum would count the postage twice.
    net = totals["gross"] + totals["stripe_fee"] + totals["platform_fee"]
    profit = net + totals["cogs"] + totals["shipping_cost"] - totals["tax"]
    return {
        "totals": totals,
        "net": net,
        "profit": profit,
        "tax_liability": totals["tax"],
        # What the buyer paid for postage. The margin needs BOTH halves, and `shipping_cost` has no source
        # until a carrier label is bought (plans/SHIPPING_CHARGES.md), so it is **None when unknowable**
        # rather than equal to the revenue.
        #
        # Returning `revenue + 0` here would have published a margin implying postage was free -- the exact
        # shape of the `tax_liability` bug this module already has (plans/TODO.md): a figure that looks
        # authoritative, is structurally always wrong, and nobody can tell from reading it. Not worth
        # repeating in new code on the same day it was written up.
        "shipping_revenue": totals["shipping_revenue"],
        "shipping_margin": (totals["shipping_revenue"] + totals["shipping_cost"]
                            if totals["shipping_cost"] else None),
        # THE SEGREGATION, stated rather than left for the reader to subtract. A tenant's accounting needs
        # to know what they sold apart from what they charged to post it: the two have different margins,
        # different tax treatment, and only one of them is what the platform takes its fee on.
        #
        # Derived, never stored: `shipping_revenue` is a partition of `gross`, so merchandise is whatever
        # is left. Storing both would let them drift.
        "merchandise_revenue": totals["gross"] - totals["shipping_revenue"],
        "shipping_cost": totals["shipping_cost"],
        "counts": counts,
    }
