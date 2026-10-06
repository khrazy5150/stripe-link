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
    lines: list[dict[str, Any]] | None = None,
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
    # WHAT WAS IN THE SALE. `product_id` above is the order's PRIMARY product and `amounts.gross` is the
    # whole order, so the two together attribute a bump's revenue to the headline product. Absent when
    # the order could not be broken down, which a report must be able to tell apart from a product that
    # genuinely earned nothing -- so it is omitted rather than written as [].
    if lines:
        document["lines"] = lines
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
        # `stripe_mode` FIRST, because it is the field the repository stamps on every order it writes and
        # the only one guaranteed present. `mode` is written by the webhook's checkout path and by nothing
        # else -- an upsell's order_record has 28 keys and none of them is `mode` -- so reading it alone
        # meant a LIVE upsell produced a ledger entry stamped "test", which the fail-safe default made
        # silent. Live upsell revenue would simply be absent from live reports (found 2026-10-07 while
        # tracing why one concept has two field names).
        mode=_order_mode(order),
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


def what_sold(entries: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Revenue and units per product, from the LINES of each sale.

    Not from `entry.product_id`: that names the order's primary product while `gross` is the whole order,
    so grouping on it hands a bump's revenue to the headline product and reports the bump as having never
    sold. Measured on real data 2026-10-06 -- Creatine Gummies $2,700.55 against $320.38 of its own
    lines, and a bump that had sold $28.90 reading zero.

    `unitemised` is the gross of sales that carry no line breakdown, reported as its own figure rather
    than spread across products or quietly dropped. A product report whose columns do not add up to the
    money report is worse than one that says which part it cannot place.
    """
    products: dict[str, dict[str, Any]] = {}
    unitemised = 0
    for entry in entries or []:
        if entry.get("entry_type") != "sale":
            continue
        lines = entry.get("lines")
        if not lines:
            unitemised += int((entry.get("amounts") or {}).get("gross") or 0)
            continue
        for line in lines:
            # Keyed on the product where it is known and on the NAME where it is not, then merged below:
            # a line whose price predates the catalogue index resolves only to a name, and leaving it on
            # its own key lists one product twice with its revenue split between the rows.
            key = str(line.get("product_id") or line.get("name") or "").strip() or "(unnamed)"
            row = products.setdefault(key, {
                "product_id": str(line.get("product_id") or ""),
                "name": str(line.get("name") or ""),
                "gross": 0, "units": 0, "orders": 0, "bump_gross": 0,
            })
            if not row["name"] and line.get("name"):
                row["name"] = str(line["name"])
            row["gross"] += int(line.get("gross") or 0)
            row["units"] += max(1, int(line.get("units") or 1))
            row["orders"] += 1
            if line.get("order_bump"):
                row["bump_gross"] += int(line.get("gross") or 0)
    return {
        "products": sorted(_merge_by_name(products.values()), key=lambda row: -row["gross"]),
        "unitemised_gross": unitemised,
    }


def _merge_by_name(rows: Any) -> list[dict[str, Any]]:
    """Fold name-only rows into the identified product of the same name.

    One product listed twice with its revenue split between the rows is worse than either figure alone,
    because both look like whole answers.
    """
    identified = {row["name"]: row for row in rows if row.get("product_id") and row.get("name")}
    merged: list[dict[str, Any]] = []
    for row in rows:
        target = identified.get(row.get("name"))
        if target is not None and target is not row and not row.get("product_id"):
            for field in ("gross", "units", "orders", "bump_gross"):
                target[field] += row[field]
            continue
        merged.append(row)
    return merged


def _order_mode(order: dict[str, Any]) -> str:
    """The Stripe mode an order was placed in.

    `stripe_mode` FIRST, because it is what the repository stamps on every order it writes and the only
    field guaranteed present. `mode` is written by the webhook's checkout path and by nothing else -- an
    upsell's order_record has 28 keys and none of them is `mode` -- so reading it alone meant a LIVE
    upsell produced a ledger entry stamped "test", which the fail-safe default made silent. Live upsell
    revenue would simply be absent from live reports (found 2026-10-07).

    Anything not explicitly "live" is "test", matching `common.normalize_stripe_mode`: under-reporting
    real revenue is recoverable, reporting test money as real is not.
    """
    raw = order.get("stripe_mode") or order.get("mode")
    return "live" if str(raw or "").strip().lower() == "live" else "test"


def sale_lines(order: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Per-line revenue for a sale entry, or None when the order is not itemised.

    None rather than `[]`: an order with no line items is one we cannot break down, which is a different
    thing from an order that genuinely sold nothing, and a report must be able to tell them apart and say
    so rather than quietly reporting a product as having earned zero.

    `units` is what the buyer actually received -- a "3 Items" tier is three, however Stripe counts it.
    """
    lines = []
    # POSTAGE THAT RIDES INSIDE A LINE. An order bump's shipping surcharge is folded into the price
    # Stripe charges, so it is inside that line's total AND recorded as shipping revenue. Subtracted here
    # so a product report counts merchandise only and still reconciles with the money report.
    #
    # Newer lines say so themselves. Older ones predate that, so the order's total is apportioned across
    # the bump lines by their share -- which is exact for the one-bump case every real order has had, and
    # never leaves postage sitting in merchandise.
    bump_lines = [l for l in order.get("line_items") or [] if isinstance(l, dict) and l.get("is_order_bump")]
    unstated = max(0, int(order.get("bump_shipping_amount") or 0)
                   - sum(int(l.get("shipping_amount") or 0) for l in bump_lines))
    bump_total = sum(int(l.get("amount_total") or 0) for l in bump_lines) or 1
    for line in order.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        gross = int(line.get("amount_total") or 0)
        postage = int(line.get("shipping_amount") or 0)
        if not postage and unstated and line.get("is_order_bump"):
            postage = round(unstated * gross / bump_total)
        gross = max(0, gross - postage)
        quantity = max(1, int(line.get("quantity") or 1))
        units = quantity * max(1, int(line.get("unit_quantity") or 1))
        entry: dict[str, Any] = {"gross": gross, "units": units}
        for key in ("product_id", "price_id", "name"):
            value = str(line.get(key) or "").strip()
            if value:
                entry[key] = value
        if line.get("is_order_bump"):
            entry["order_bump"] = True
        lines.append(entry)
    if lines:
        return lines
    # An upsell is a single product recorded in its own block rather than as line items, and it is a sale
    # like any other -- leaving it unitemised would make every upsell invisible to a product report.
    product = order.get("product") if isinstance(order.get("product"), dict) else {}
    product_id = str(product.get("product_id") or "").strip()
    if product_id:
        # MERCHANDISE ONLY. An upsell's `amount_total` is what the card was charged, postage included,
        # while `shipping_revenue` records that postage separately -- so taking the whole total here
        # counts the postage twice and a product report stops reconciling with the money report. It was
        # over by $449.12 across 39 upsells before this subtraction (2026-10-06). Stripe's own line items
        # on the checkout path are already merchandise, which is why only this fallback needs it.
        merchandise = max(0, int(order.get("amount_total") or 0)
                          - int(order.get("shipping_amount") or 0)
                          - int(order.get("bump_shipping_amount") or 0))
        return [{"gross": merchandise, "units": 1, "product_id": product_id,
                 **({"name": str(product.get("name"))} if product.get("name") else {}),
                 **({"price_id": str(product.get("price_id"))} if product.get("price_id") else {})}]
    return None


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
        # `stripe_mode` FIRST, because it is the field the repository stamps on every order it writes and
        # the only one guaranteed present. `mode` is written by the webhook's checkout path and by nothing
        # else -- an upsell's order_record has 28 keys and none of them is `mode` -- so reading it alone
        # meant a LIVE upsell produced a ledger entry stamped "test", which the fail-safe default made
        # silent. Live upsell revenue would simply be absent from live reports (found 2026-10-07 while
        # tracing why one concept has two field names).
        mode=_order_mode(order),
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
        # ...PLUS the postage that arrived inside an order bump's price. A bump is ticked after Stripe's
        # shipping options are fixed, so its parcel cost cannot ride the shipping line and is folded into
        # the bump price instead; counting only `shipping_amount` would book that money as merchandise and
        # report a shipping margin that is short by exactly the amount the tenant charged to cover postage.
        shipping_revenue=int(order.get("shipping_amount") or 0) + int(order.get("bump_shipping_amount") or 0),
        # WHAT WAS IN IT. `product_id` above names the order's PRIMARY product and `gross` is the whole
        # order, so by themselves they answer "which product earned this" wrongly whenever a buyer took
        # more than one thing -- the headline product collects the bump's revenue and the bump reads as
        # never having sold. 20 of 73 real orders had more than one line (2026-10-06).
        #
        # Recorded on the ENTRY rather than computed in a report, so money is still added up in exactly
        # one place: a report that re-derived this from orders would be a second ledger.
        lines=sale_lines(order),
        idempotency_key=f"sale:{key_ref}",
        order_id=order_id or None,
        # NESTED, which is where both order paths actually write them -- `attribution.offer_id` and
        # `product.product_id`. Read flat, these were always None and were dropped, so NOT ONE ledger
        # entry ever written carries a product or an offer. Every question a report exists to answer --
        # which product earns, which offer converts, what a funnel is worth -- was unanswerable from the
        # ledger, and nothing said so because an absent field looks exactly like a sale that had none.
        #
        # This is the same mistake as the `fees` one twelve lines above, in the same function, one field
        # over: flat reads against a nested document (found 2026-10-06, while asking what "proper
        # reporting" would need). The flat read stays as a fallback for the invoice path and for anything
        # written before the shapes diverged.
        offer_id=str(order.get("offer_id")
                     or (order.get("attribution") or {}).get("offer_id") or "") or None,
        product_id=str(order.get("product_id")
                       or (order.get("product") or {}).get("product_id") or "") or None,
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
