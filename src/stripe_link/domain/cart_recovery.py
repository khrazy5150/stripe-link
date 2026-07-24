"""Abandoned-cart recovery email (plans/LISTICLE_AND_CART.md L2 Slice D2).

Pure content builder — the sweep (handlers/cart_recovery.py) supplies the already-built recovery + unsubscribe
URLs and the tenant's business identity. Kept out of the renderer so it has no HTML-runtime dependency.
"""
from __future__ import annotations

from html import escape
from typing import Any


def _money(cents: Any, currency: str) -> str:
    amount = int(cents or 0) / 100
    code = str(currency or "usd").upper()
    return f"${amount:,.2f}" if code == "USD" else f"{amount:,.2f} {code}"


def recovery_email(
    cart: dict[str, Any],
    *,
    recovery_url: str,
    unsubscribe_url: str,
    organization: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build the {subject, html, text} for one abandoned-cart nudge."""
    business = str((organization or {}).get("name") or "").strip() or "our shop"
    lines = cart.get("line_items") or []
    count = int(cart.get("item_count") or sum(int(i.get("qty") or 1) for i in lines))
    currency = str(cart.get("currency") or "usd")
    total = _money(cart.get("total_amount"), currency)
    plural = "s" if count != 1 else ""
    subject = f"You left {count} item{plural} in your cart"

    rows = "".join(
        f"<tr><td style=\"padding:6px 0;\">{escape(str(i.get('name') or 'Item'))}"
        f" &times;{int(i.get('qty') or 1)}</td>"
        f"<td style=\"padding:6px 0;text-align:right;\">{escape(_money(int(i.get('unit_amount') or 0) * int(i.get('qty') or 1), currency))}</td></tr>"
        for i in lines
    )
    html = (
        f"<div style=\"font-family:system-ui,Arial,sans-serif;max-width:520px;margin:0 auto;color:#111;\">"
        f"<h2 style=\"font-size:20px;\">Still thinking it over?</h2>"
        f"<p>You left {count} item{plural} in your cart at {escape(business)}. It's saved and ready when you are.</p>"
        f"<table style=\"width:100%;border-collapse:collapse;font-size:15px;margin:12px 0;\">{rows}"
        f"<tr><td style=\"padding:10px 0 0;font-weight:700;border-top:1px solid #ddd;\">Total</td>"
        f"<td style=\"padding:10px 0 0;text-align:right;font-weight:700;border-top:1px solid #ddd;\">{escape(total)}</td></tr>"
        f"</table>"
        f"<p style=\"margin:20px 0;\"><a href=\"{escape(recovery_url)}\" "
        f"style=\"background:#111;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;display:inline-block;\">"
        f"Return to your cart</a></p>"
        f"<p style=\"font-size:12px;color:#888;margin-top:28px;\">"
        f"Don't want these reminders? <a href=\"{escape(unsubscribe_url)}\" style=\"color:#888;\">Unsubscribe</a>.</p>"
        f"</div>"
    )
    item_text = "\n".join(
        f"  - {str(i.get('name') or 'Item')} x{int(i.get('qty') or 1)}: {_money(int(i.get('unit_amount') or 0) * int(i.get('qty') or 1), currency)}"
        for i in lines
    )
    text = (
        f"You left {count} item{plural} in your cart at {business}. It's saved and ready when you are.\n\n"
        f"{item_text}\n  Total: {total}\n\n"
        f"Return to your cart: {recovery_url}\n\n"
        f"Unsubscribe from these reminders: {unsubscribe_url}\n"
    )
    return {"subject": subject, "html": html, "text": text}
