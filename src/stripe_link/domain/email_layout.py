"""The standard transactional email: one shell every message a tenant sends is poured into.

Before this, each emitter built its own HTML from scratch. They disagreed about everything a recipient
notices — the review invite used a 32rem column in `-apple-system, Segoe UI, Roboto` on #1f2937, the
abandoned-cart mail a 520px column in `system-ui, Arial` on #111, the invoice a third set of greys — and
none of them named the business anywhere in the message body. Two emails from one shop did not look like
they came from the same place (reported 2026-09-23).

So the shell is fixed and the content is not: a caller supplies the words and the blocks, and this decides
what a Junior Bay email looks like. It is deliberately the SAME for every tenant. Per-tenant theming is a
larger question (a brand colour, a logo) and belongs to the Business Profile work, not to a layer whose
job is to stop nine emitters disagreeing.

Constraints this is written against, which explain most of the odd choices:

- **Table layout, inline styles.** Outlook renders with Word's HTML engine: no flexbox, no grid, and
  `<style>` blocks are unreliable. A table with inline styles is the only thing that lands everywhere.
- **Images are blocked by default** in most clients, so nothing meaningful may live in one. The business
  name is TEXT, which is why this works for a tenant who has never uploaded a logo — which is all of them.
- **A preheader is the second line in an inbox list.** Left unset the client scrapes the first text it
  finds, which is usually a link or "View in browser". Setting it deliberately is free.
- **Dark mode inverts unstyled backgrounds.** Every surface states its own background and colour, so a
  client flipping the page cannot leave dark text on a dark card.
"""

from html import escape
from typing import Any

# One typeface stack, one column width, one accent. The accent matches the platform signature's indigo so
# a free tenant's footer does not clash with the button above it.
FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MAX_WIDTH = "560px"
INK = "#1f2937"
MUTED = "#6b7280"
RULE = "#e5e7eb"
CANVAS = "#f4f4f7"
SURFACE = "#ffffff"
ACCENT = "#4f46e5"


def button(label: str, url: str) -> str:
    """One call to action, as a table cell rather than a styled anchor — Outlook drops padding on inline
    anchors, which collapses a button into a bare link exactly where a message needs its click."""
    if not str(url or "").strip():
        return ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:24px auto 8px"><tr>'
        f'<td align="center" bgcolor="{ACCENT}" style="border-radius:8px">'
        f'<a href="{escape(str(url), quote=True)}" '
        f'style="display:inline-block;padding:13px 26px;font-family:{FONT_STACK};font-size:15px;'
        f'font-weight:700;color:#ffffff;text-decoration:none;border-radius:8px">'
        f"{escape(str(label or 'View'))}</a></td></tr></table>"
    )


def paragraph(text: str, *, muted: bool = False) -> str:
    if not str(text or "").strip():
        return ""
    colour = MUTED if muted else INK
    return (f'<p style="margin:0 0 14px;font-family:{FONT_STACK};font-size:15px;line-height:1.6;'
            f'color:{colour}">{escape(str(text))}</p>')


def rows_table(rows: list, *, total: tuple | None = None) -> str:
    """A line-item table: `[(label, value), ...]`, with an optional emphasised total row.

    Every email that shows money — receipt, invoice, abandoned cart — was drawing its own version of this
    with different padding and a different grey.
    """
    if not rows and not total:
        return ""
    cells = []
    for label, value in rows:
        cells.append(
            f'<tr><td style="padding:7px 0;font-family:{FONT_STACK};font-size:14px;line-height:1.5;'
            f'color:{INK}">{escape(str(label))}</td>'
            f'<td align="right" style="padding:7px 0;font-family:{FONT_STACK};font-size:14px;'
            f'color:{INK};white-space:nowrap">{escape(str(value))}</td></tr>'
        )
    if total:
        cells.append(
            f'<tr><td style="padding:12px 0 0;border-top:1px solid {RULE};font-family:{FONT_STACK};'
            f'font-size:15px;font-weight:700;color:{INK}">{escape(str(total[0]))}</td>'
            f'<td align="right" style="padding:12px 0 0;border-top:1px solid {RULE};'
            f'font-family:{FONT_STACK};font-size:15px;font-weight:700;color:{INK};white-space:nowrap">'
            f"{escape(str(total[1]))}</td></tr>"
        )
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:4px 0 18px">' + "".join(cells) + "</table>")


def render_email(
    *, business_name: str = "", title: str = "", body: str = "", preheader: str = "",
    reply_to: str = "", footer_note: str = "", footer_html: str = "",
) -> str:
    """The whole message, minus the platform signature the mailer appends.

    `body` is already-escaped HTML from the helpers above (or a caller's own markup); everything else is
    plain text and is escaped here.
    """
    name = str(business_name or "").strip()
    head = (
        f'<td style="padding:22px 28px 0;font-family:{FONT_STACK};font-size:15px;font-weight:700;'
        f'letter-spacing:.02em;color:{INK}">{escape(name)}</td>'
    ) if name else '<td style="padding:8px 0 0"></td>'

    # The reply line is the whole point of having a Reply-To: a recipient must be TOLD they can answer,
    # or they look for a support link that does not exist and give up.
    reply_line = ""
    if str(reply_to or "").strip():
        who = f"{name} " if name else ""
        reply_line = (
            f'<p style="margin:0 0 6px;font-family:{FONT_STACK};font-size:13px;line-height:1.5;'
            f'color:{MUTED}">Questions? Just reply to this email and it reaches {escape(who.strip() or "us")}'
            ".</p>"
        )
    note = (f'<p style="margin:0 0 6px;font-family:{FONT_STACK};font-size:12px;line-height:1.5;'
            f'color:{MUTED}">{escape(str(footer_note))}</p>') if str(footer_note or "").strip() else ""
    # For footers that need a LINK — an unsubscribe line, which a marketing nudge must carry and a
    # receipt must not. Markup, so the caller escapes it; `footer_note` is the plain-text door.
    extra = str(footer_html or "")

    # Hidden, zero-height, and padded: clients that show a preview line take this instead of scraping the
    # first link out of the body.
    preview = (
        f'<div style="display:none;font-size:1px;color:{CANVAS};line-height:1px;max-height:0;'
        'max-width:0;opacity:0;overflow:hidden">'
        f"{escape(str(preheader))}&#8204;{'&nbsp;&#8204;' * 60}</div>"
    ) if str(preheader or "").strip() else ""

    heading = (
        f'<h1 style="margin:0 0 16px;font-family:{FONT_STACK};font-size:21px;line-height:1.35;'
        f'font-weight:700;color:{INK}">{escape(str(title))}</h1>'
    ) if str(title or "").strip() else ""

    return (
        f'<div style="margin:0;padding:0;background:{CANVAS}">'
        f"{preview}"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{CANVAS};padding:24px 12px">'
        '<tr><td align="center">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:{MAX_WIDTH};margin:0 auto;background:{SURFACE};border-radius:12px;'
        f'border:1px solid {RULE}">'
        f"<tr>{head}</tr>"
        f'<tr><td style="padding:14px 28px 26px">{heading}{body}</td></tr>'
        f'<tr><td style="padding:0 28px 22px">{reply_line}{note}{extra}</td></tr>'
        "</table></td></tr></table></div>"
    )


def render_text(*, business_name: str = "", title: str = "", body: str = "", reply_to: str = "") -> str:
    """The plain-text half. Not an afterthought: it is what a screen reader and a text-only client get,
    and a message with no text part scores worse with spam filters."""
    parts = []
    if str(business_name or "").strip():
        parts.append(str(business_name).strip())
    if str(title or "").strip():
        parts.append(str(title).strip())
    if str(body or "").strip():
        parts.append(str(body).strip())
    if str(reply_to or "").strip():
        parts.append("Questions? Just reply to this email.")
    return "\n\n".join(parts)
