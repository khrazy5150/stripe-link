"""Telling the buyer their parcel is on its way.

Shared by BOTH paths -- the label we bought and the parcel the tenant posted themselves -- because the
buyer does not care how the postage was obtained, and two implementations would drift.

What is NOT shared is how a failure is treated, and that difference is deliberate:

  label purchase   the label is already bought and paid for, so a bounced address must not turn a
                   successful purchase into an error the tenant thinks they should retry. Best-effort.
  manual           nothing irreversible has happened and the tenant pressed the button IN ORDER TO
                   notify the buyer. Swallowing a failure means the tenant believes their customer was
                   told and the customer hears nothing.

So this function always REPORTS the outcome and never raises; each caller decides what to do with it.
"""
from typing import Any

from stripe_link.domain.receipts import shipment_tracking_content
from stripe_link.mailer import send_email, tenant_email_identity


def notify_buyer(order: dict[str, Any], shipment: dict[str, Any], tenant_id: str, *,
                 has_tracking: bool | None = None, user_profiles_repo=None, mailer_send=None,
                 arrival_line: str = "", tenant_note: str = "") -> dict[str, Any]:
    """Tell the buyer. Reports the OUTCOME rather than swallowing it.

    plans/SHIPPING_PROVIDERS.md §P3 says a tracking email must never break what triggered it, which is
    right when a label is already bought and paid for. On the MANUAL path nothing irreversible has
    happened and the tenant pressed the button IN ORDER TO notify the buyer -- swallowing a failure there
    means the tenant believes their customer was told and the customer hears nothing. So the parcel is
    still recorded as shipped, and the failure is handed back so the screen can offer Resend.
    """
    email = str((order.get("customer") or {}).get("email") or "").strip()
    if not email:
        return {"sent": False, "reason": "no_customer_email"}
    try:
        identity = tenant_email_identity(tenant_id, user_profiles_repo)
        lines = order.get("line_items") or []
        items = str((lines[0] or {}).get("name") or "") if len(lines) == 1 else ""
        if not items:
            items = str((order.get("product") or {}).get("name") or "")
        content = shipment_tracking_content(
            business_name=identity.get("business_name", ""),
            order_id=str(order.get("order_id") or ""),
            items=items,
            carrier_label=str(shipment.get("carrier") or ""),
            service_label=str(shipment.get("service") or ""),
            tracking_number=str(shipment.get("tracking_number") or ""),
            tracking_url=str(shipment.get("tracking_url") or ""),
            has_tracking=has_tracking,
            support_email=identity.get("reply_to", ""),
            arrival_line=arrival_line,
            tenant_note=tenant_note,
        )
        (mailer_send or send_email)(
            to_address=email,
            subject=content["subject"],
            html_body=content["html"],
            text_body=content["text"],
            tenant_id=tenant_id,
        )
        return {"sent": True, "to": email}
    except Exception as exc:  # noqa: BLE001 - reported, never raised: the parcel DID ship
        return {"sent": False, "error": str(exc)}
