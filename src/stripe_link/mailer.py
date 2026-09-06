"""Transactional email via Amazon SES v2.

Sends from a single verified platform identity (EMAIL_FROM_ADDRESS, default
support@juniorbay.net) with the tenant's business name as the display name and the
tenant's support email as Reply-To -- so replies reach the merchant without requiring
per-tenant domain verification.
"""

import os
from email.utils import formataddr
from typing import Any

from stripe_link.domain.platform_signature import (
    shows_platform_signature,
    signature_html,
    signature_text,
)


class EmailError(RuntimeError):
    pass


DEFAULT_FROM_ADDRESS = "support@juniorbay.net"


def _ses_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return boto3.client("sesv2", region_name=region)


def from_email_address(display_name: str = "") -> str:
    """`Business Name <support@juniorbay.net>`, correctly quoted.

    The display name is a TENANT-typed business name, so it routinely contains the characters RFC 5322
    calls specials -- "Acme, Inc." being the ordinary case. Pasted in raw, the comma reads as an address
    separator and SES rejects the whole message, which surfaces to a visitor as a failed download with no
    explanation. formataddr quotes when it must and RFC 2047-encodes a non-ASCII name.
    """
    address = os.environ.get("EMAIL_FROM_ADDRESS", DEFAULT_FROM_ADDRESS)
    name = str(display_name or "").strip()
    return formataddr((name, address)) if name else address


def _tenant_shows_signature(tenant_id: str, profiles_repo: Any | None = None) -> bool:
    """Read the tenant's tier. Unreadable means free: a lookup failure must not hand out the premium perk."""
    try:
        if profiles_repo is None:
            from stripe_link.repositories.documents import tenant_profiles_repository

            profiles_repo = tenant_profiles_repository()
        return shows_platform_signature(profiles_repo.get(tenant_id, tenant_id))
    except Exception:  # noqa: BLE001 - a footer must never be the reason a message fails to send
        return True


def send_email(
    *,
    to: str,
    subject: str,
    html: str = "",
    text: str = "",
    from_name: str = "",
    reply_to: str = "",
    tenant_id: str = "",
    signature: bool | None = None,
    profiles_repo: Any | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Send one message as the tenant, appending the platform sign-off unless they have paid it away.

    The signature decision lives HERE, at the single choke point every send already passes through, rather
    than in each of the eight callers -- the next feature that mails something would forget, and the whole
    point of a sign-off is that it is on everything.

    `tenant_id` opts a message in and resolves the tier. `signature=False` opts out explicitly, which is
    what platform-to-tenant mail does: a verification code is not the place to invite someone to start the
    store they already run.
    """
    recipient = str(to or "").strip()
    if not recipient:
        raise EmailError("Recipient email is required.")
    if not html and not text:
        raise EmailError("Email must include an html or text body.")

    if signature is None:
        signature = bool(str(tenant_id or "").strip()) and _tenant_shows_signature(tenant_id, profiles_repo)
    if signature:
        if html:
            html += signature_html()
        if text:
            text += signature_text()

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
