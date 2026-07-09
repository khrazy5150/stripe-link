"""Invoicing domain — pure builders for Stripe Invoicing params and the invoice email.

Turns a stripe-link Invoice document into the Stripe API payloads (customer, invoice items,
invoice) and the customer-facing "here's your invoice, pay here" email. No I/O.
"""
from decimal import Decimal
from html import escape
from typing import Any

from stripe_link.domain.booking import service_lines

CURRENCY_SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£"}
DEFAULT_DAYS_UNTIL_DUE = 7


def _appointment_invoice_lines(appointment: dict[str, Any]) -> list[dict[str, Any]]:
    """One invoice line per service line in an appointment (tenant-keyed amount for payout parity)."""
    appointment_id = str(appointment.get("appointment_id") or "")
    lines = []
    for line in service_lines(appointment):
        price = line.get("price") or {}
        amount = int(price.get("tenant_keyed_amount") if price.get("tenant_keyed_amount") is not None else price.get("unit_amount") or 0)
        lines.append({
            "type": "service",
            "description": str(line.get("service_name") or "Service"),
            "quantity": 1,
            "unit_amount": amount,
            "currency": str(price.get("currency") or "usd").lower(),
            "service_id": str(line.get("service_id") or ""),
            "appointment_id": appointment_id,
        })
    return lines


def invoice_from_order(
    appointments: list[dict[str, Any]], *, invoice_id: str, now: int,
    no_booking_lines: list[dict[str, Any]] | None = None,
    tenant_id: str | None = None, customer: dict[str, Any] | None = None,
    order_id: str = "", stripe_mode: str = "",
) -> dict[str, Any]:
    """Build ONE draft Invoice for a book-then-pay purchase: one line per service line across all its
    appointments, plus any no_booking lines. Links source.appointment_ids[] (0..N — empty for a
    no_booking-only purchase). The send flow adds the platform fee (STORY-3.3)."""
    appointments = list(appointments or [])
    no_booking_lines = list(no_booking_lines or [])
    first = appointments[0] if appointments else {}
    tenant_id = tenant_id if tenant_id is not None else str(first.get("tenant_id") or "")
    customer = customer if customer is not None else dict(first.get("customer") or {})
    stripe_mode = stripe_mode or str(first.get("stripe_mode") or "")
    order_id = order_id or str(first.get("order_id") or "")

    line_items: list[dict[str, Any]] = []
    for appointment in appointments:
        line_items.extend(_appointment_invoice_lines(appointment))
    line_items.extend(dict(line) for line in no_booking_lines)

    currency = str((line_items[0].get("currency") if line_items else "usd") or "usd").lower()
    subtotal = sum(int(item.get("unit_amount") or 0) * max(1, int(item.get("quantity") or 1)) for item in line_items)
    appointment_ids = [str(a.get("appointment_id") or "") for a in appointments]
    return {
        "schema_version": "2026-05-29",
        "document_type": "invoice",
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "status": "draft",
        "stripe_mode": stripe_mode,
        "customer": customer,
        "line_items": line_items,
        "amounts": {"currency": currency, "subtotal": subtotal, "total": subtotal, "amount_paid": 0, "amount_due": subtotal},
        "source": {"appointment_ids": appointment_ids, "order_id": order_id, "created_from": "order"},
        "created_at": now,
        "updated_at": now,
    }


def invoice_from_appointment(appointment: dict[str, Any], *, invoice_id: str, now: int) -> dict[str, Any]:
    """Single-appointment convenience over invoice_from_order (book-then-pay direct booking)."""
    return invoice_from_order([appointment], invoice_id=invoice_id, now=now)


def line_total(item: dict[str, Any]) -> int:
    return int(item.get("unit_amount") or 0) * max(1, int(item.get("quantity") or 1))


def invoice_total(invoice: dict[str, Any]) -> int:
    return sum(line_total(item) for item in invoice.get("line_items") or [])


def invoice_currency(invoice: dict[str, Any]) -> str:
    items = invoice.get("line_items") or []
    currency = (items[0].get("currency") if items else None) or (invoice.get("amounts") or {}).get("currency") or "usd"
    return str(currency).lower()


def format_money(amount_cents: int, currency: str = "usd") -> str:
    symbol = CURRENCY_SYMBOLS.get(str(currency).lower(), "")
    value = Decimal(int(amount_cents)) / Decimal(100)
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {str(currency).upper()}"


def stripe_customer_params(customer: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"email": str(customer.get("email") or "")}
    if customer.get("name"):
        params["name"] = customer["name"]
    if customer.get("phone"):
        params["phone"] = customer["phone"]
    return params


def stripe_invoiceitem_params(customer_id: str, item: dict[str, Any], currency: str) -> dict[str, Any]:
    return {
        "customer": customer_id,
        "currency": currency,
        "amount": line_total(item),
        "description": str(item.get("description") or "Item"),
    }


def stripe_invoice_params(customer_id: str, *, days_until_due: int = DEFAULT_DAYS_UNTIL_DUE, application_fee: int = 0, metadata: dict | None = None, footer: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {
        "customer": customer_id,
        "collection_method": "send_invoice",
        "days_until_due": days_until_due,
        "auto_advance": "false",  # we finalize explicitly
    }
    if application_fee and int(application_fee) > 0:
        params["application_fee_amount"] = int(application_fee)
    if footer:
        params["footer"] = footer
    if metadata:
        params["metadata"] = {k: str(v) for k, v in metadata.items() if v}
    return params


def invoice_email_content(invoice: dict[str, Any], hosted_url: str, *, business_name: str = "", support_email: str = "") -> dict[str, str]:
    currency = invoice_currency(invoice)
    total = format_money(invoice_total(invoice), currency)
    biz = business_name or "A business"
    rows = "".join(
        f"<tr><td style='padding:6px 0;color:#374151'>{escape(str(i.get('description') or 'Item'))} &times; {max(1, int(i.get('quantity') or 1))}</td>"
        f"<td style='padding:6px 0;text-align:right;color:#111827'>{format_money(line_total(i), currency)}</td></tr>"
        for i in invoice.get("line_items") or []
    )
    memo = str((invoice.get("presentation") or {}).get("memo") or "").strip()
    memo_html = f"<p style='color:#6b7280'>{escape(memo)}</p>" if memo else ""
    html = (
        f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:34rem;margin:auto;padding:1.5rem'>"
        f"<h2 style='margin:0 0 .25rem'>Invoice from {escape(biz)}</h2>"
        f"<p style='color:#6b7280;margin:.25rem 0 1.25rem'>Amount due: <strong>{total}</strong></p>"
        f"{memo_html}"
        f"<table style='width:100%;border-collapse:collapse;margin:1rem 0;border-top:1px solid #e5e7eb'>{rows}"
        f"<tr><td style='padding:10px 0;border-top:1px solid #e5e7eb;font-weight:700'>Total</td>"
        f"<td style='padding:10px 0;border-top:1px solid #e5e7eb;text-align:right;font-weight:700'>{total}</td></tr></table>"
        f"<p style='margin:1.5rem 0'><a href='{escape(hosted_url)}' "
        f"style='background:#4f46e5;color:#fff;padding:.8rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:700'>Pay invoice</a></p>"
        f"<p style='color:#9ca3af;font-size:.85rem'>Or paste this link into your browser:<br>{escape(hosted_url)}</p>"
        f"</div>"
    )
    text = f"{biz} sent you an invoice for {total}.\nPay securely: {hosted_url}"
    return {"subject": f"Invoice from {biz} — {total} due", "html": html, "text": text}
