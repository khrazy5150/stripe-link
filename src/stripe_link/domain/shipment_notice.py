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
import os
from typing import Any

from stripe_link.domain.receipts import shipment_tracking_content
from stripe_link.mailer import send_email, tenant_email_identity


def revision_for(order: dict[str, Any], shipment: dict[str, Any], tenant_id: str, mode: str,
                 *, quotes_repo=None) -> dict[str, Any]:
    """The buyer's arrival date, recomputed from the day the parcel really left. `{}` when unknowable.

    plans/THANK_YOU_PAGE.md P4. Lives HERE rather than in either handler because both of them ship
    parcels: `orders.mark_shipped` when the tenant posted it themselves and `shipping.buy_label` when we
    bought the postage. A second copy would word the same correction two ways within a release, which is
    the failure this codebase has spent the week not repeating.

    Never raises. A parcel that shipped must record as shipped whatever happens to its estimate.
    """
    try:
        from datetime import datetime, timezone

        from stripe_link.domain.shipping_promise import revised_promise
        from stripe_link.repositories.documents import shipping_quotes_repository

        quote = {}
        quote_ref = (order or {}).get("shipping_quote") or {}
        quote_id = str(quote_ref.get("quote_id") or "") if isinstance(quote_ref, dict) else ""
        if quote_id:
            repo = quotes_repo or (shipping_quotes_repository(mode=mode)
                                   if os.environ.get("CARTS_TABLE") else None)
            if repo is not None:
                quote = repo.get(tenant_id, quote_id) or {}
        shipped_at = int((shipment or {}).get("shipped_at") or 0)
        if not shipped_at:
            return {}
        # Read in UTC rather than the tenant's zone: unlike the original estimate there is no cutoff left
        # to decide, so the date is used only to count business days forward, and a few hours either side
        # of midnight cannot change which weekday that lands on.
        shipped_on = datetime.fromtimestamp(shipped_at, timezone.utc).date()
        return revised_promise(order, quote, shipment, shipped_on=shipped_on)
    except Exception as exc:  # noqa: BLE001
        print(f"[delivery] revision not computed for {(order or {}).get('order_id')}: "
              f"{type(exc).__name__}: {exc}")
        return {}


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
