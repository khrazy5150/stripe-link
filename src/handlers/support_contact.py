"""Public, unauthenticated platform support form (juniorbay.com/support).

POST /support/contact {name, email, role, reference?, message, website(honeypot)} -> emails support@ via SES with
the submitter as Reply-To, so replying from the mailbox goes straight back to them. No storage, no auth: the
page is static and posts same-origin through the homepage CloudFront (/support/contact -> API), so no CORS.
Abuse posture mirrors the public /leads ingest: honeypot (silently accepted), strict caps, allow-listed fields.
"""
import html
import os
import re
import time
from typing import Any

from stripe_link.common import error_response, header_value, json_response, parse_json_body
from stripe_link.mailer import EmailError, send_email

HONEYPOT_FIELD = "website"
ROLES = {"buyer": "Buyer", "seller": "Seller", "other": "Other"}
MAX = {"name": 120, "email": 254, "reference": 120, "message": 4000}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _support_inbox() -> str:
    return str(os.environ.get("SUPPORT_INBOX") or os.environ.get("EMAIL_FROM_ADDRESS") or "support@juniorbay.net").strip()


def _clean(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key) or "").strip()[: MAX.get(key, 512)]


def validate(payload: dict[str, Any]) -> dict[str, str]:
    """Return the cleaned submission or raise ValueError with a user-facing message."""
    name, email, message = _clean(payload, "name"), _clean(payload, "email"), _clean(payload, "message")
    role = str(payload.get("role") or "other").strip().lower()
    if not name:
        raise ValueError("Please tell us your name.")
    if not _EMAIL_RE.match(email):
        raise ValueError("Please enter a valid email address so we can reply.")
    if len(message) < 10:
        raise ValueError("Please describe how we can help (at least a sentence).")
    if role not in ROLES:
        role = "other"
    return {"name": name, "email": email, "role": role, "reference": _clean(payload, "reference"), "message": message}


def _request_context(event) -> dict[str, str]:
    identity = ((event or {}).get("requestContext") or {}).get("identity") or {}
    return {
        "ip": str(identity.get("sourceIp") or "")[:64],
        "user_agent": str(header_value(event, "User-Agent") or "")[:256],
    }


def render_email(sub: dict[str, str], ctx: dict[str, str], now: int) -> tuple[str, str, str]:
    """(subject, text, html) for the support inbox."""
    role = ROLES.get(sub["role"], "Other")
    subject = f"[Junior Bay support] {role}: {sub['name']}" + (f" · ref {sub['reference']}" if sub["reference"] else "")
    lines = [
        f"From: {sub['name']} <{sub['email']}>",
        f"Role: {role}",
        f"Reference: {sub['reference'] or '—'}",
        f"Received: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}",
        f"IP: {ctx.get('ip') or '—'} · UA: {ctx.get('user_agent') or '—'}",
        "",
        sub["message"],
    ]
    text = "\n".join(lines)
    esc = html.escape
    body_html = (
        f"<p><strong>From:</strong> {esc(sub['name'])} &lt;{esc(sub['email'])}&gt;<br>"
        f"<strong>Role:</strong> {esc(role)}<br>"
        f"<strong>Reference:</strong> {esc(sub['reference'] or '—')}<br>"
        f"<strong>Received:</strong> {esc(lines[3][10:])}<br>"
        f"<small>IP {esc(ctx.get('ip') or '—')} · UA {esc(ctx.get('user_agent') or '—')}</small></p>"
        f"<pre style=\"white-space:pre-wrap;font-family:inherit\">{esc(sub['message'])}</pre>"
    )
    return subject, text, body_html


def handler(event, context, *, send=None, now_fn=time.time):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
    try:
        payload = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_submission")
    # Honeypot: accept-and-drop so bots get no signal.
    if str((payload or {}).get(HONEYPOT_FIELD) or "").strip():
        return json_response({"status": "accepted"}, status_code=202)
    try:
        sub = validate(payload or {})
    except ValueError as exc:
        return error_response(str(exc), code="invalid_submission")

    subject, text, body_html = render_email(sub, _request_context(event), int(now_fn()))
    try:
        (send or send_email)(
            to=_support_inbox(), subject=subject, text=text, html=body_html,
            from_name="Junior Bay Support Form", reply_to=sub["email"],
        )
    except EmailError as exc:
        return error_response(f"We couldn't send your message right now: {exc}", status_code=502, code="send_failed")
    return json_response({"status": "sent"})
