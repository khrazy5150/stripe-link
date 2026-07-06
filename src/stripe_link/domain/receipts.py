"""Order-confirmation / receipt email rendering (pure -- no I/O).

The webhook builds an order record on checkout.session.completed and hands it here to
render the buyer's receipt. Optional download_links are appended for digital products.
"""

from html import escape
from typing import Any


def format_money(cents: Any, currency: str = "usd") -> str:
    amount = int(cents or 0) / 100
    return f"{str(currency or 'usd').upper()} {amount:,.2f}"


def receipt_content(
    order: dict[str, Any],
    *,
    business_name: str = "",
    support_email: str = "",
    download_links: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    business = str(business_name or "").strip() or "Your order"
    customer = order.get("customer") or {}
    product = order.get("product") or {}
    customer_name = str(customer.get("name") or "there").strip() or "there"
    product_name = str(product.get("name") or "Your order").strip()
    currency = str(order.get("currency") or "usd")
    total = format_money(order.get("amount_total"), currency)
    order_id = str(order.get("order_id") or "")
    links = download_links or []

    subject = f"Your receipt from {business}" if business_name else "Your order receipt"

    # Plain text
    text_lines = [
        f"Hi {customer_name},",
        "",
        f"Thanks for your purchase from {business}. Here is your receipt.",
        "",
        f"Order: {order_id}",
        f"Item: {product_name}",
        f"Total: {total}",
    ]
    if links:
        text_lines += ["", "Your downloads:"]
        text_lines += [f"- {link.get('label') or 'Download'}: {link.get('url', '')}" for link in links]
    if support_email:
        text_lines += ["", f"Questions? Reply to this email or contact {support_email}."]
    text = "\n".join(text_lines)

    # HTML
    rows = [
        _html_row("Order", order_id),
        _html_row("Item", product_name),
        _html_row("Total", total),
    ]
    downloads_html = ""
    if links:
        items = "".join(
            f'<li style="margin:0 0 8px"><a href="{escape(link.get("url", ""))}" '
            f'style="color:#4f46b5;font-weight:600">{escape(link.get("label") or "Download")}</a></li>'
            for link in links
        )
        downloads_html = (
            '<h3 style="font-size:16px;margin:24px 0 8px">Your downloads</h3>'
            f'<ul style="padding-left:18px;margin:0">{items}</ul>'
        )
    support_html = (
        f'<p style="color:#6b7280;font-size:13px;margin:24px 0 0">Questions? Reply to this email'
        f'{f" or contact {escape(support_email)}" if support_email else ""}.</p>'
    )
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;'
        'max-width:560px;margin:0 auto;color:#1f2937">'
        f'<h1 style="font-size:22px;margin:0 0 4px">{escape(business)}</h1>'
        f'<p style="color:#6b7280;margin:0 0 20px">Thanks for your purchase, {escape(customer_name)}.</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:14px">'
        f'{"".join(rows)}</table>'
        f'{downloads_html}'
        f'{support_html}'
        '</div>'
    )
    return {"subject": subject, "html": html, "text": text}


def _html_row(label: str, value: str) -> str:
    return (
        '<tr>'
        f'<td style="padding:8px 0;color:#6b7280;border-bottom:1px solid #e5e7eb">{escape(label)}</td>'
        f'<td style="padding:8px 0;text-align:right;font-weight:600;border-bottom:1px solid #e5e7eb">{escape(value)}</td>'
        '</tr>'
    )
