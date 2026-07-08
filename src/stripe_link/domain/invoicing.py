"""Invoicing domain — pure builders for Stripe Invoicing params and the invoice email.

Turns a stripe-link Invoice document into the Stripe API payloads (customer, invoice items,
invoice) and the customer-facing "here's your invoice, pay here" email. No I/O.
"""
from decimal import Decimal
from html import escape
from typing import Any

CURRENCY_SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£"}
DEFAULT_DAYS_UNTIL_DUE = 7


def invoice_from_appointment(appointment: dict[str, Any], *, invoice_id: str, now: int) -> dict[str, Any]:
    """Build a draft Invoice for a book-then-pay appointment, linked back via source.appointment_id
    (STORY-6.4). Amount is the appointment's sticker price; the send flow adds the platform fee."""
    price = appointment.get("price") or {}
    currency = str(price.get("currency") or "usd").lower()
    unit_amount = int(price.get("tenant_keyed_amount") if price.get("tenant_keyed_amount") is not None else price.get("unit_amount") or 0)
    service_name = str(appointment.get("service_name") or "Service")
    line = {
        "type": "service",
        "description": service_name,
        "quantity": 1,
        "unit_amount": unit_amount,
        "currency": currency,
        "service_id": str(appointment.get("service_id") or ""),
        "appointment_id": str(appointment.get("appointment_id") or ""),
    }
    return {
        "schema_version": "2026-05-29",
        "document_type": "invoice",
        "tenant_id": str(appointment.get("tenant_id") or ""),
        "invoice_id": invoice_id,
        "status": "draft",
        "stripe_mode": str(appointment.get("stripe_mode") or ""),
        "customer": dict(appointment.get("customer") or {}),
        "line_items": [line],
        "amounts": {"currency": currency, "subtotal": unit_amount, "total": unit_amount, "amount_paid": 0, "amount_due": unit_amount},
        "source": {"appointment_id": str(appointment.get("appointment_id") or ""), "service_id": str(appointment.get("service_id") or ""), "created_from": "appointment"},
        "created_at": now,
        "updated_at": now,
    }


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
