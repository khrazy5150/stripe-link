import time
from typing import Any, Callable

from stripe_link.domain.platform_billing import billing_status_from_stripe


def _tenant_id_from_object(obj: dict[str, Any]) -> str:
    """Platform-billing events carry no connected account, so the tenant is identified via metadata we stamped on
    the subscription (and which Stripe mirrors onto invoices as subscription_details.metadata)."""
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    tenant_id = str(metadata.get("tenant_id") or "").strip()
    if tenant_id:
        return tenant_id
    subscription_details = obj.get("subscription_details") if isinstance(obj.get("subscription_details"), dict) else {}
    tenant_id = str((subscription_details.get("metadata") or {}).get("tenant_id") or "").strip()
    if tenant_id:
        return tenant_id
    for line in ((obj.get("lines") or {}).get("data") or []):
        if isinstance(line, dict):
            tenant_id = str((line.get("metadata") or {}).get("tenant_id") or "").strip()
            if tenant_id:
                return tenant_id
    return ""


def _subscription_price_id(subscription: dict[str, Any]) -> str:
    for item in ((subscription.get("items") or {}).get("data") or []):
        if isinstance(item, dict):
            price = item.get("price") if isinstance(item.get("price"), dict) else {}
            price_id = str(price.get("id") or "").strip()
            if price_id:
                return price_id
    return ""


def _invoice_period_end(invoice: dict[str, Any]) -> int | None:
    for line in ((invoice.get("lines") or {}).get("data") or []):
        period = line.get("period") if isinstance(line, dict) else None
        if isinstance(period, dict) and isinstance(period.get("end"), int):
            return period["end"]
    period_end = invoice.get("period_end")
    return period_end if isinstance(period_end, int) else None


def reconcile_platform_subscription_event(
    stripe_event: dict[str, Any],
    *,
    mode: str,
    tenant_repo,
    now_fn: Callable[[], int] = lambda: int(time.time()),
) -> dict[str, Any]:
    """Map a platform-account Stripe Billing event (the tenant's SaaS subscription) onto the tenant's
    billing_status + subscription cache fields. Webhook-driven, not live reads. See plans/SAAS_BILLING_PAYWALL.md."""
    obj = ((stripe_event.get("data") or {}).get("object") or {})
    if not isinstance(obj, dict):
        return {"platform_billing": "no_object"}
    event_type = str(stripe_event.get("type") or "")

    tenant_id = _tenant_id_from_object(obj)
    if not tenant_id:
        return {"platform_billing": "no_tenant_id", "event_type": event_type}
    tenant = tenant_repo.get(tenant_id, tenant_id)
    if not tenant:
        return {"platform_billing": "tenant_not_found", "tenant_id": tenant_id}

    # Exempt tenants are never charged; ignore any stray subscription events for them.
    if tenant.get("billing_exempt"):
        return {"platform_billing": "exempt_ignored", "tenant_id": tenant_id}

    updates: dict[str, Any] = {}
    if event_type.startswith("customer.subscription."):
        subscription_id = str(obj.get("id") or "").strip()
        if subscription_id:
            updates["stripe_subscription_id"] = subscription_id
        customer_id = str(obj.get("customer") or "").strip()
        if customer_id:
            updates["stripe_customer_id"] = customer_id
        if event_type == "customer.subscription.deleted":
            updates["billing_status"] = "canceled"
        else:
            updates["billing_status"] = billing_status_from_stripe(obj.get("status"))
        current_period_end = obj.get("current_period_end")
        if isinstance(current_period_end, int):
            updates["current_period_end"] = current_period_end
        price_id = _subscription_price_id(obj)
        if price_id:
            updates["billing_price_id"] = price_id
    elif event_type == "invoice.payment_failed":
        updates["billing_status"] = "past_due"
    elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
        updates["billing_status"] = "active"
        period_end = _invoice_period_end(obj)
        if isinstance(period_end, int):
            updates["current_period_end"] = period_end
    else:
        return {"platform_billing": "ignored", "event_type": event_type, "tenant_id": tenant_id}

    tenant_repo.put({**tenant, **updates})
    return {
        "platform_billing": "updated",
        "tenant_id": tenant_id,
        "billing_status": updates.get("billing_status"),
        "event_type": event_type,
    }
