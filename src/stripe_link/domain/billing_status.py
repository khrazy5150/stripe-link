from typing import Any


# past_due is the Stripe DUNNING/grace window (still allowed); Stripe moves it to unpaid->suspended / canceled per
# the account's no-code dunning settings, which is what actually blocks. trial/active are allowed. See
# plans/SAAS_BILLING_PAYWALL.md and [[project_billing_paywall]].
BLOCKED_BILLING_STATUSES = {"suspended", "canceled"}


class BillingStatusError(RuntimeError):
    def __init__(self, status: str):
        super().__init__(
            "This tenant's account is on hold and cannot accept payments right now."
        )
        self.status = status


def is_billing_in_good_standing(tenant_profile: dict[str, Any] | None) -> bool:
    """True if the tenant may take new payments / serve pages. Exempt (comped) tenants always pass. A missing
    profile is treated as "trial" (not blocked) rather than failing closed, since profile lookup is best-effort and
    should never itself break a tenant who simply hasn't been backfilled yet. past_due is allowed (grace)."""
    profile = tenant_profile or {}
    if profile.get("billing_exempt"):
        return True
    status = str(profile.get("billing_status") or "trial")
    return status not in BLOCKED_BILLING_STATUSES


def assert_billing_in_good_standing(tenant_profile: dict[str, Any] | None) -> None:
    """Raise BillingStatusError if the tenant is not allowed to take new payments."""
    if not is_billing_in_good_standing(tenant_profile):
        raise BillingStatusError(str((tenant_profile or {}).get("billing_status") or "trial"))
