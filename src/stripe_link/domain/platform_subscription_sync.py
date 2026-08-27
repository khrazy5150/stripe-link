import time
from typing import Any, Callable

from stripe_link.domain.entitlements import plan_entitlements
from stripe_link.domain.fees import normalize_tier_id
from stripe_link.domain.platform_billing import billing_status_from_stripe, platform_plan


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
    plans_repository=None,
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

    # Stripe does NOT guarantee webhook delivery order, and this sync is last-write-wins — without a guard, the
    # initial subscription.updated (status "incomplete", pre-payment -> past_due) can arrive AFTER invoice.paid
    # and strand a validly-paid tenant on past_due (observed 2026-08-27). Skip events strictly older than the
    # newest one already applied (equal timestamps still apply: same-second events can't be ordered).
    event_created = stripe_event.get("created")
    try:
        last_applied = int(tenant.get("last_billing_event_at"))
    except (TypeError, ValueError):
        last_applied = None
    if isinstance(event_created, int) and last_applied is not None and event_created < last_applied:
        return {"platform_billing": "stale_event_skipped", "tenant_id": tenant_id, "event_type": event_type}

    updates: dict[str, Any] = {}
    if event_type.startswith("customer.subscription."):
        subscription_id = str(obj.get("id") or "").strip()
        if subscription_id:
            updates["stripe_subscription_id"] = subscription_id
        customer_id = str(obj.get("customer") or "").strip()
        if customer_id:
            updates["stripe_customer_id"] = customer_id
        if event_type == "customer.subscription.deleted":
            # Free-forever model: cancellation reverts to the free tier, never to nothing. Stripe fires this at
            # period end for cancel_at_period_end, so a mid-cycle cancel keeps premium (entitlements + pro fee)
            # until the paid-through date. The empty list is topped up by the free-tier floor at read time
            # (entitlements.tenant_entitlement_set), and tier_id=basic flips checkout to free-tier fees.
            updates["billing_status"] = "canceled"
            updates["entitlements"] = []
            updates["tier_id"] = "basic"
            updates["cancel_at_period_end"] = False  # the pending cancel has now happened
        else:
            updates["cancel_at_period_end"] = bool(obj.get("cancel_at_period_end"))
            updates["billing_status"] = billing_status_from_stripe(obj.get("status"))
            # Denormalize the plan's entitlements onto the tenant so the per-feature guards are a pure profile check.
            plan_key = str((obj.get("metadata") or {}).get("plan_key") or tenant.get("billing_plan_key") or "").strip()
            if plan_key:
                updates["billing_plan_key"] = plan_key
                plan = platform_plan(mode, plan_key, plans_repository)
                updates["entitlements"] = plan_entitlements(plan)
                # The plan's fee tier drives the live transaction fee (fees.build_fee_context reads tenant.tier_id):
                # premium plans carry fee_tier "pro" (2%/0%); default to pro so a plan row without the field still
                # grants the premium fee a subscriber is paying for.
                updates["tier_id"] = normalize_tier_id((plan or {}).get("fee_tier") or "pro")
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

    if isinstance(event_created, int):
        updates["last_billing_event_at"] = event_created
    tenant_repo.put({**tenant, **updates})
    return {
        "platform_billing": "updated",
        "tenant_id": tenant_id,
        "billing_status": updates.get("billing_status"),
        "event_type": event_type,
    }
