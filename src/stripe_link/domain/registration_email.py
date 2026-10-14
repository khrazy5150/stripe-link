"""The confirmation a registrant receives (plans/WEBINAR.md P2).

Pure: builds the subject and both bodies and returns them. Nothing here sends, so the wording can be
tested without a mailbox and the handler stays a handler.

Written for someone who just gave up their email address and wants one thing confirmed — that they are in,
and when. So the **date is in the subject line**, where it survives a notification preview, and the join
link appears before any explanation of what the session is. A confirmation that buries the time under a
paragraph of marketing is a confirmation nobody reads.

The time is given in the HOST's zone, matching the page, and the `.ics` carries UTC so the registrant's own
calendar does the conversion. We do not guess their zone from a browser: being wrong about a time is worse
than being explicit about someone else's.
"""
from __future__ import annotations

from html import escape
from typing import Any


def _when(event: dict[str, Any], occurrence: dict[str, Any]) -> str:
    from ..runtime.html import format_event_date
    from .events import starts_at

    moment = starts_at(occurrence)
    if not moment:
        return ""
    return format_event_date(moment, str(occurrence.get("timezone") or ""), with_time=True)


def registration_confirmation(
    event: dict[str, Any],
    occurrence: dict[str, Any],
    *,
    name: str = "",
    brand: str = "",
) -> dict[str, str]:
    """`{subject, html, text}` for one registration. Empty subject means there is nothing worth sending."""
    title = str(event.get("title") or "").strip() or "the session"
    when = _when(event, occurrence)
    if not when:
        return {"subject": "", "html": "", "text": ""}

    join_url = str(event.get("join_url") or "").strip()
    greeting = f"Hi {name.strip()}," if str(name or "").strip() else "Hi,"
    host = str(brand or "").strip()

    # The date in the SUBJECT, because a phone shows the subject and the first line and nothing else.
    subject = f"You're registered: {title} — {when}"

    lines = [greeting, "", f"You're registered for {title}.", "", f"When: {when}"]
    if join_url:
        lines += ["", f"Join here: {join_url}"]
    else:
        # Said plainly rather than left blank: a confirmation with no link and no explanation reads as a
        # broken email, and the registrant cannot tell whether to expect another one.
        lines += ["", "We'll email you the link before the session starts."]
    lines += ["", "The attached calendar file will put it in your diary."]
    if host:
        lines += ["", f"— {host}"]
    text = "\n".join(lines)

    join_html = (
        f'<p style="margin:24px 0"><a href="{escape(join_url)}" '
        f'style="background:#4f46e5;color:#fff;padding:12px 20px;border-radius:8px;'
        f'text-decoration:none;display:inline-block">Join the session</a></p>'
        if join_url else
        "<p>We'll email you the link before the session starts.</p>"
    )
    html = "".join([
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:16px;line-height:1.5">',
        f"<p>{escape(greeting)}</p>",
        f"<p>You're registered for <strong>{escape(title)}</strong>.</p>",
        f'<p style="font-size:18px"><strong>{escape(when)}</strong></p>',
        join_html,
        "<p>The attached calendar file will put it in your diary.</p>",
        (f"<p>— {escape(host)}</p>" if host else ""),
        "</div>",
    ])
    return {"subject": subject, "html": html, "text": text}


def registration_reminder(
    event: dict[str, Any],
    occurrence: dict[str, Any],
    lead_minutes: int,
    *,
    name: str = "",
) -> dict[str, str]:
    """The nudge before a session. `{subject, html, text}`; empty subject means nothing worth sending.

    Shorter than the confirmation on purpose. The registrant already knows what this is -- they signed up
    -- so the whole job is the link and how soon. Re-explaining the session here is how a reminder becomes
    another marketing email to ignore.
    """
    title = str(event.get("title") or "").strip() or "your session"
    when = _when(event, occurrence)
    if not when:
        return {"subject": "", "html": "", "text": ""}

    soon = "tomorrow" if int(lead_minutes) >= 720 else "in about an hour"
    join_url = str(event.get("join_url") or "").strip()
    greeting = f"Hi {name.strip()}," if str(name or "").strip() else "Hi,"
    subject = f"{title} starts {soon}"

    lines = [greeting, "", f"{title} starts {soon}.", "", f"When: {when}"]
    lines += ["", f"Join here: {join_url}"] if join_url else \
             ["", "We'll send the link shortly."]
    text = "\n".join(lines)

    join_html = (
        f'<p style="margin:24px 0"><a href="{escape(join_url)}" '
        f'style="background:#4f46e5;color:#fff;padding:12px 20px;border-radius:8px;'
        f'text-decoration:none;display:inline-block">Join the session</a></p>'
        if join_url else "<p>We'll send the link shortly.</p>"
    )
    html = "".join([
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:16px;line-height:1.5">',
        f"<p>{escape(greeting)}</p>",
        f"<p><strong>{escape(title)}</strong> starts {escape(soon)}.</p>",
        f'<p style="font-size:18px"><strong>{escape(when)}</strong></p>',
        join_html,
        "</div>",
    ])
    return {"subject": subject, "html": html, "text": text}
