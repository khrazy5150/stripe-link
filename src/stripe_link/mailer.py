"""Transactional email via Amazon SES v2.

Sends from a single verified platform identity (EMAIL_FROM_ADDRESS, default support@juniorbay.net) with the
tenant's business name as the display name and the tenant's reply address as Reply-To -- so replies reach
the merchant without requiring per-tenant domain verification.

**The identity is resolved HERE**, not by callers. It used to be each emitter's job, and the result was
exactly what you would predict: four of nine senders passed a display name, three passed a Reply-To, and
the two that did resolve a name read different fields, so one shop was "Poliaxis Nutrition" on its review
invite and a bare "support@juniorbay.net" on its receipt (reported 2026-09-23). A caller may still pass
either explicitly -- platform-authored mail does, and explicit always wins -- but a tenant message that
says nothing now gets the tenant's identity instead of the platform's.
"""

import os
from email.utils import formataddr
from typing import Any

from stripe_link.domain.business_email import email_identity
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


def tenant_email_identity(tenant_id: str, profiles_repo: Any | None = None) -> dict[str, str]:
    """The tenant's `{business_name, reply_to}`, read from the OWNER's profile.

    The owner's `user_id` equals their `tenant_id` (verified against every profile in dev and prod,
    2026-09-23), so this is one keyed read rather than a scan.

    Never raises: an identity lookup must not be the reason a receipt fails to send. A failure costs the
    branding, which is recoverable; a failure that loses the message is not.
    """
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return {"business_name": "", "reply_to": ""}
    try:
        if profiles_repo is None:
            from stripe_link.repositories.documents import user_profiles_repository

            profiles_repo = user_profiles_repository()
        return email_identity(profiles_repo.get(tenant_id, tenant_id) or {})
    except Exception:  # noqa: BLE001 - branding is worth less than delivery
        return {"business_name": "", "reply_to": ""}


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
    user_profiles_repo: Any | None = None,
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

    # The tenant's own identity, for anything the caller did not state outright. Platform-authored mail
    # passes no tenant_id, so a verification code still comes from Junior Bay rather than from the shop
    # the recipient happens to own.
    if str(tenant_id or "").strip() and not (from_name and reply_to):
        identity = tenant_email_identity(tenant_id, user_profiles_repo)
        from_name = from_name or identity["business_name"]
        reply_to = reply_to or identity["reply_to"]

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
