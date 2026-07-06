"""Transactional email via Amazon SES v2.

Sends from a single verified platform identity (EMAIL_FROM_ADDRESS, default
support@juniorbay.net) with the tenant's business name as the display name and the
tenant's support email as Reply-To -- so replies reach the merchant without requiring
per-tenant domain verification.
"""

import os
from typing import Any


class EmailError(RuntimeError):
    pass


DEFAULT_FROM_ADDRESS = "support@juniorbay.net"


def _ses_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return boto3.client("sesv2", region_name=region)


def from_email_address(display_name: str = "") -> str:
    address = os.environ.get("EMAIL_FROM_ADDRESS", DEFAULT_FROM_ADDRESS)
    name = str(display_name or "").strip()
    return f"{name} <{address}>" if name else address


def send_email(
    *,
    to: str,
    subject: str,
    html: str = "",
    text: str = "",
    from_name: str = "",
    reply_to: str = "",
    client: Any | None = None,
) -> dict[str, Any]:
    recipient = str(to or "").strip()
    if not recipient:
        raise EmailError("Recipient email is required.")
    if not html and not text:
        raise EmailError("Email must include an html or text body.")

    body: dict[str, Any] = {}
    if html:
        body["Html"] = {"Data": html, "Charset": "UTF-8"}
    if text:
        body["Text"] = {"Data": text, "Charset": "UTF-8"}

    request: dict[str, Any] = {
        "FromEmailAddress": from_email_address(from_name),
        "Destination": {"ToAddresses": [recipient]},
        "Content": {"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body}},
    }
    reply = str(reply_to or "").strip()
    if reply:
        request["ReplyToAddresses"] = [reply]

    client = client or _ses_client()
    return client.send_email(**request)
