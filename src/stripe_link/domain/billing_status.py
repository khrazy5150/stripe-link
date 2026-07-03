from typing import Any


BLOCKED_BILLING_STATUSES = {"past_due", "suspended"}


class BillingStatusError(RuntimeError):
    def __init__(self, status: str):
        super().__init__(
            "This tenant's account is on hold and cannot accept payments right now."
        )
        self.status = status


def assert_billing_in_good_standing(tenant_profile: dict[str, Any] | None) -> None:
    """Raise BillingStatusError if the tenant is not allowed to take new payments.

    Enforced immediately (no grace period) on TenantProfile.billing_status. A missing
    tenant profile is treated as "trial" (not blocked) rather than failing closed, since
    profile lookup is best-effort here and should never itself break checkout for tenants
    who simply haven't been backfilled yet.
    """
    status = str((tenant_profile or {}).get("billing_status") or "trial")
    if status in BLOCKED_BILLING_STATUSES:
        raise BillingStatusError(status)
