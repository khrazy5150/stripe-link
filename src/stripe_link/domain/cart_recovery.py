"""Abandoned-cart recovery email (plans/LISTICLE_AND_CART.md L2 Slice D2).

Pure content builder — the sweep (handlers/cart_recovery.py) supplies the already-built recovery + unsubscribe
URLs and the tenant's business identity. Kept out of the renderer so it has no HTML-runtime dependency.
"""
from __future__ import annotations

from html import escape
from typing import Any

from stripe_link.domain.email_layout import FONT_STACK, button, paragraph, render_email, rows_table


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
    reply_to: str = "",
) -> dict[str, str]:
    """Build the {subject, html, text} for one abandoned-cart nudge."""
    business = str((organization or {}).get("name") or "").strip()
    lines = cart.get("line_items") or []
    count = int(cart.get("item_count") or sum(int(i.get("qty") or 1) for i in lines))
    currency = str(cart.get("currency") or "usd")
    total = _money(cart.get("total_amount"), currency)
    plural = "s" if count != 1 else ""
    subject = f"You left {count} item{plural} in your cart"

    body = (
        paragraph(f"You left {count} item{plural} in your cart"
                  f"{f' at {business}' if business else ''}. It's saved and ready when you are.")
        + rows_table(
            [(f"{i.get('name') or 'Item'} \u00d7{int(i.get('qty') or 1)}",
              _money(int(i.get("unit_amount") or 0) * int(i.get("qty") or 1), currency)) for i in lines],
            total=("Total", total),
        )
        + button("Return to your cart", recovery_url)
    )
    # The unsubscribe line is the ONE piece of chrome this email has that others do not: a marketing
    # nudge must carry its own way out, and it belongs in the footer where a recipient looks for it.
    unsubscribe = (
        f'<p style="margin:0;font-family:{FONT_STACK};font-size:12px;line-height:1.5;color:#6b7280">'
        f'Don\'t want these reminders? <a href="{escape(unsubscribe_url, quote=True)}" '
        'style="color:#6b7280">Unsubscribe</a>.</p>'
    ) if unsubscribe_url else ""
    html = render_email(
        business_name=business,
        title="Still thinking it over?",
        body=body,
        preheader=f"{count} item{plural} — {total}",
        reply_to=reply_to,
        footer_html=unsubscribe,
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
