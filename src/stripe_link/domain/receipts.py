"""Order-confirmation / receipt email rendering (pure -- no I/O).

The webhook builds an order record on checkout.session.completed and hands it here to
render the buyer's receipt. Optional download_links are appended for digital products.
"""

import re
import time
from html import escape
from typing import Any

from stripe_link.domain.email_layout import ACCENT, button, paragraph, render_email, rows_table
from stripe_link.domain.tips import fee_breakdown


def format_money(cents: Any, currency: str = "usd") -> str:
    amount = int(cents or 0) / 100
    return f"{str(currency or 'usd').upper()} {amount:,.2f}"


def _first_line_name(order: dict[str, Any]) -> str:
    """The first line item's description, and more lines named when there are more.

    Stripe writes a renewal line as "1 x Creatine Gummies (at $32.91 / month)". The quantity and price are
    already shown beside it on the receipt, so the leading "1 x " is noise here; the rest is the only name
    the invoice carries.
    """
    lines = order.get("line_items") or []
    if not lines:
        return ""
    name = str((lines[0] or {}).get("name") or "").strip()
    name = re.sub(r"^\s*\d+\s*[x\u00d7]\s*", "", name)
    name = re.sub(r"\s*\(at .*\)\s*$", "", name).strip()
    if not name:
        return ""
    extra = len(lines) - 1
    return f"{name} + {extra} more" if extra > 0 else name


def receipt_content(
    order: dict[str, Any],
    *,
    business_name: str = "",
    support_email: str = "",
    download_links: list[dict[str, str]] | None = None,
    manage_url: str = "",
) -> dict[str, str]:
    business = str(business_name or "").strip()
    customer = order.get("customer") or {}
    product = order.get("product") or {}
    customer_name = str(customer.get("name") or "there").strip() or "there"
    # A SUBSCRIPTION RENEWAL has no `product` block — it is built from a Stripe invoice, whose lines are
    # the only description there is — so a renewal receipt said "Item: Your order" while the real name sat
    # in line_items[0] (first real renewal, prod 2026-09-23). Fall through to the lines before giving up.
    product_name = (
        str(product.get("name") or "").strip()
        or _first_line_name(order)
        or "Your order"
    )
    currency = str(order.get("currency") or "usd")
    total = format_money(order.get("amount_total"), currency)
    order_id = str(order.get("order_id") or "")
    links = download_links or []
    # A supporter who covered the fees typed $10.00 and was charged $11.00. Show both, the way the tip card
    # did before they paid -- a receipt carrying only the grossed-up total looks like we charged more than
    # they chose. It is also the figure a refund returns (domain/tips.py refund_amount), so this is the
    # buyer's record of what they can ask back. None for every other order, which shows the total alone.
    breakdown = fee_breakdown(order)
    money_rows = [("Order", order_id), ("Item", product_name)]
    if breakdown:
        tip_amount, fees_covered = breakdown
        money_rows += [("Tip", format_money(tip_amount, currency)),
                       ("Fees you covered", format_money(fees_covered, currency))]

    # The shop's name belongs in the SUBJECT, not only in the From line: an inbox list shows the subject
    # at full width and truncates the sender. The fallback is the generic one, and seeing it in a real
    # inbox is what exposed that no tenant had a business name on the field this used to read
    # (reported 2026-09-23).
    subject = f"Your receipt from {business}" if business else "Your order receipt"

    text_lines = [
        f"Hi {customer_name},",
        "",
        f"Thanks for your purchase{f' from {business}' if business else ''}. Here is your receipt.",
        "",
        f"Order: {order_id}",
        f"Item: {product_name}",
    ]
    if breakdown:
        text_lines += [f"Tip: {format_money(breakdown[0], currency)}",
                       f"Fees you covered: {format_money(breakdown[1], currency)}"]
    text_lines += [f"Total: {total}"]
    if links:
        text_lines += ["", "Your downloads:"]
        text_lines += [f"- {link.get('label') or 'Download'}: {link.get('url', '')}" for link in links]
    # A repeating tip has to carry its own OFF switch. We ask for no account, so this link is the whole of
    # how a supporter stops one (plans/PAY_WHAT_YOU_WANT.md §5g) -- without it the only route is asking the
    # creator, which is the behaviour that design deliberately rejected.
    if manage_url:
        text_lines += ["", f"Manage or cancel this recurring tip: {manage_url}"]
    # Named explicitly as well as being the Reply-To: a customer whose client strips Reply-To, or who
    # forwards the receipt to someone else, still has an address they can write to.
    if support_email:
        text_lines += ["", f"Questions? Reply to this email or contact {support_email}."]

    downloads_html = ""
    if links:
        items = "".join(
            f'<li style="margin:0 0 8px"><a href="{escape(link.get("url", ""), quote=True)}" '
            f'style="color:{ACCENT};font-weight:600">{escape(link.get("label") or "Download")}</a></li>'
            for link in links
        )
        downloads_html = (
            f'<h2 style="font-size:15px;margin:22px 0 8px;font-weight:700">Your downloads</h2>'
            f'<ul style="padding-left:18px;margin:0 0 6px">{items}</ul>'
        )

    body = (
        paragraph(f"Thanks for your purchase, {customer_name}.")
        + rows_table(money_rows, total=("Total", total))
        + downloads_html
        + (button("Manage or cancel this recurring tip", manage_url) if manage_url else "")
    )
    html = render_email(
        business_name=business,
        title=subject,
        body=body,
        preheader=f"{product_name} — {total}",
        reply_to=support_email,
        footer_note=f"You can also reach us at {support_email}." if support_email else "",
    )
    return {"subject": subject, "html": html, "text": "\n".join(text_lines)}


def cancellation_content(
    *,
    business_name: str = "",
    product: str = "",
    ends_at: int = 0,
    manage_url: str = "",
    support_email: str = "",
) -> dict[str, str]:
    """Confirming a cancellation the CUSTOMER made, in writing.

    Cancelling used to render a web page and send nothing, so the only record was a tab the customer
    could close. That is the shape that produces a chargeback -- not "I was charged after
    cancelling", which `cancel_at_period_end` already prevents, but "I think I cancelled, I have
    nothing that says so, and I cannot tell whether another payment is coming". Someone in that state
    calls their bank, which costs the seller a dispute fee and their ratio (found 2026-09-28).

    Three things earn their place. That no further payment is coming, because that is the actual
    question. WHEN access ends, because a cancelled subscription is still `active` until then and
    "cancelled" on something still running reads as a failure. And the manage link again -- cancelling
    and wanting money back are usually the same conversation, and the refund route is otherwise a link
    they have just navigated away from.
    """
    business = str(business_name or "").strip()
    item = str(product or "").strip() or "your subscription"
    ends = ""
    if ends_at:
        try:
            ends = time.strftime("%d %B %Y", time.gmtime(int(ends_at)))
        except (ValueError, OSError, OverflowError):
            ends = ""

    subject = f"You cancelled {item}" if not business else f"You cancelled {item} — {business}"
    text_lines = [
        f"This confirms you cancelled {item}"
        + (f" from {business}" if business else "") + ".",
        "",
        "You will not be charged again.",
    ]
    if ends:
        text_lines += ["", f"You keep access until {ends}. Nothing else is needed from you."]
    if manage_url:
        text_lines += ["", "Changed your mind about a payment already made? You can ask for a refund "
                           f"here:\n{manage_url}"]
    if support_email:
        text_lines += ["", f"Questions? Reply to this email or contact {support_email}."]

    body = (
        paragraph(f"This confirms you cancelled <strong>{escape(item)}</strong>"
                  + (f" from {escape(business)}" if business else "") + ".")
        + paragraph("<strong>You will not be charged again.</strong>")
        + (paragraph(f"You keep access until {escape(ends)}. Nothing else is needed from you.")
           if ends else "")
        + (button("Ask for a refund", manage_url) if manage_url else "")
        + (paragraph("Payments already made are not returned by cancelling. If you want one back, "
                     "use the button above.", muted=True) if manage_url else "")
    )
    html = render_email(
        business_name=business,
        title=subject,
        body=body,
        preheader="You will not be charged again.",
        reply_to=support_email,
        footer_note=f"You can also reach us at {support_email}." if support_email else "",
    )
    return {"subject": subject, "html": html, "text": "\n".join(text_lines)}


def _html_row(label: str, value: str) -> str:
    return (
        '<tr>'
        f'<td style="padding:8px 0;color:#6b7280;border-bottom:1px solid #e5e7eb">{escape(label)}</td>'
        f'<td style="padding:8px 0;text-align:right;font-weight:600;border-bottom:1px solid #e5e7eb">{escape(value)}</td>'
        '</tr>'
    )


def tip_renewal_content(
    *,
    business_name: str = "",
    amount: Any = 0,
    currency: str = "usd",
    interval: str = "month",
    manage_url: str = "",
    support_email: str = "",
) -> dict[str, str]:
    """The note that goes out on EVERY repeat charge of a tip.

    Two jobs, and the second is the one that matters: say the charge happened, and carry a working cancel
    link. A recurring charge nobody was told about is the most reliable way to produce a dispute, and the
    link in the FIRST receipt is the one a supporter cannot find a year later — so the newest email always
    carries a fresh one (plans/PAY_WHAT_YOU_WANT.md §5g).

    Short on purpose. It is a notice, not a receipt: Stripe already emails the invoice.
    """
    business = str(business_name or "").strip() or "the creator"
    every = {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}.get(str(interval), "recurring")
    total = format_money(amount, currency)

    subject = f"Your {every} tip to {business}" if business_name else f"Your {every} tip"
    text_lines = [
        f"Your {every} tip of {total} to {business} was charged today.",
        "",
        "Thank you for the support — it goes straight to them.",
    ]
    if manage_url:
        text_lines += ["", f"Change or cancel this {every} tip any time: {manage_url}"]
    if support_email:
        text_lines += ["", f"Questions? Reply to this email or contact {support_email}."]

    manage_html = (
        f'<p style="margin:20px 0 0"><a href="{escape(manage_url)}" '
        f'style="color:#4f46b5;font-weight:600">Change or cancel this {escape(every)} tip</a></p>'
        if manage_url else ""
    )
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;'
        'max-width:560px;margin:0 auto;color:#1f2937">'
        f'<h1 style="font-size:20px;margin:0 0 8px">Your {escape(every)} tip of {escape(total)}</h1>'
        f'<p style="color:#6b7280;margin:0">Charged today and on its way to {escape(business)}. '
        'Thank you for the support.</p>'
        f'{manage_html}'
        f'{f"<p style=\'color:#6b7280;font-size:13px;margin:24px 0 0\'>Questions? Reply to this email or contact {escape(support_email)}.</p>" if support_email else ""}'
        '</div>'
    )
    return {"subject": subject, "html": html, "text": "\n".join(text_lines)}


def _shipped_via(carrier: str, service: str) -> str:
    """"USPS Ground Advantage", not "USPS via Ground Advantage" and not "USPS USPS Ground Advantage".

    Carrier service labels routinely embed the carrier's own name, so naively joining the two repeats it.
    """
    carrier = str(carrier or "").strip()
    service = str(service or "").strip()
    if not service:
        return carrier
    if not carrier:
        return service
    if service.lower().startswith(carrier.lower()):
        return service
    return f"{carrier} {service}"


def shipment_tracking_content(
    *,
    business_name: str = "",
    order_id: str = "",
    items: str = "",
    carrier_label: str = "",
    service_label: str = "",
    tracking_number: str = "",
    tracking_url: str = "",
    has_tracking: bool | None = None,
    support_email: str = "",
) -> dict[str, str]:
    """"Your order is on its way" — for a label we bought AND for a parcel the tenant posted themselves.

    One builder for both paths, because the buyer does not care how the postage was obtained and two
    builders would drift.

    The hard case is the parcel with NO tracking number. USPS First-Class Mail carries none, so this must
    degrade honestly rather than sending "track your parcel" with nothing to track — which produces exactly
    the support message the email exists to prevent. Three shapes:

      number + url  -> the link, and the number as text for anyone who cannot use it
      no number, service known to have none -> say so plainly, so nobody waits for a link
      no number, unknown -> say it is on its way and stop. We do not KNOW there is no tracking, and
                            telling a buyer "there is none" when the tenant simply had not typed it yet
                            would be a second kind of lie.
    """
    business = str(business_name or "").strip()
    number = str(tracking_number or "").strip()
    url = str(tracking_url or "").strip()
    carrier = str(carrier_label or "").strip()
    service = str(service_label or "").strip()
    what = str(items or "").strip()

    subject = f"Your order from {business} is on its way" if business else "Your order is on its way"

    shipped_line = f"{what} is on its way." if what else "Your order is on its way."
    via = _shipped_via(carrier, service)
    if via:
        shipped_line += f" Sent via {via}."

    text_lines = [shipped_line, ""]
    rows = []
    if order_id:
        rows.append(("Order", str(order_id)))
    if via:
        rows.append(("Shipped via", via))
    if number:
        rows.append(("Tracking number", number))
        text_lines.append(f"Tracking number: {number}")
        if url:
            text_lines.append(f"Track it: {url}")
    elif has_tracking is False:
        # Said once, plainly, and never dressed up as a link.
        no_tracking = (f"{service or 'This service'} does not include tracking, so there is no number to "
                       "follow — it is on its way by post.")
        text_lines.append(no_tracking)

    if support_email:
        text_lines += ["", f"Questions? Reply to this email or write to {support_email}."]

    body = [paragraph(escape(shipped_line))]
    if rows:
        body.append(rows_table([(escape(label), escape(value)) for label, value in rows]))
    if number and url:
        body.append(button("Track your parcel", url))
    elif not number and has_tracking is False:
        body.append(paragraph(escape(
            f"{service or 'This service'} does not include tracking, so there is no number to follow — "
            "it is on its way by post.")))
    if support_email:
        body.append(paragraph(
            f'Questions? Reply to this email or write to '
            f'<a href="mailto:{escape(support_email)}" style="color:{ACCENT};">{escape(support_email)}</a>.'))

    return {
        "subject": subject,
        "html": render_email(
            title=subject,
            preheader=(f"Tracking {number}" if number else shipped_line),
            business_name=business,
            body="".join(body),
        ),
        "text": "\n".join(text_lines),
    }
