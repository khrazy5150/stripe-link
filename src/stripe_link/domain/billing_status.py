import os
import time
from typing import Any

# The free platform trial every signup gets (a self-managed clock, NOT a Stripe trial — no subscription exists
# during it). Trial-first onboarding: full access until it expires, then a hard subscribe wall. Length is env-driven
# (TRIAL_PERIOD_DAYS, default 14) so dev can use a short trial for testing while prod stays 14. Read at import;
# changing it needs a redeploy and only affects NEW signups (existing trials keep their stamped trial_ends_at).
# See plans/SAAS_BILLING_PAYWALL.md and [[project_saas_billing_paywall]].
try:
    TRIAL_PERIOD_DAYS = max(0, int(os.environ.get("TRIAL_PERIOD_DAYS", "14") or "14"))
except ValueError:
    TRIAL_PERIOD_DAYS = 14
TRIAL_PERIOD_SECONDS = TRIAL_PERIOD_DAYS * 86400

# Blocked: past_due is the Stripe DUNNING/grace window (still allowed). trial_expired is an unsubscribed platform
# trial past its clock. trial/active are allowed. billing_exempt is always allowed.
BLOCKED_BILLING_STATUSES = {"suspended", "canceled", "trial_expired"}


class BillingStatusError(RuntimeError):
    def __init__(self, status: str):
        super().__init__(
            "This tenant's account is on hold and cannot accept payments right now."
        )
        self.status = status


def _is_platform_trial(profile: dict[str, Any]) -> bool:
    """A pre-subscribe platform trial: billing_status 'trial' with NO Stripe subscription. A subscribed tenant that
    Stripe reports as 'trialing' has a stripe_subscription_id and is NOT a platform trial (Stripe manages it)."""
    return str(profile.get("billing_status") or "trial") == "trial" and not profile.get("stripe_subscription_id")


def is_trial_expired(tenant_profile: dict[str, Any] | None, now: int | None = None) -> bool:
    """True once an unsubscribed platform trial passes its trial_ends_at. A missing/zero trial_ends_at is treated as
    grandfathered (never expires) so tenants created before trial clocks aren't retroactively walled."""
    profile = tenant_profile or {}
    if not _is_platform_trial(profile):
        return False
    # trial_ends_at comes back from DynamoDB as a Decimal (not int), so coerce numerically rather than isinstance.
    try:
        ends = int(profile.get("trial_ends_at"))
    except (TypeError, ValueError):
        return False
    if ends <= 0:
        return False
    current = now if now is not None else int(time.time())
    return current >= ends


def is_billing_in_good_standing(tenant_profile: dict[str, Any] | None, now: int | None = None) -> bool:
    """True if the tenant may take new payments / serve pages. Exempt tenants always pass; an active platform trial
    passes until it expires; past_due is the dunning grace window. A missing profile is treated as trial (allowed)."""
    profile = tenant_profile or {}
    if profile.get("billing_exempt"):
        return True
    if is_trial_expired(profile, now):
        return False
    status = str(profile.get("billing_status") or "trial")
    return status not in BLOCKED_BILLING_STATUSES


def assert_billing_in_good_standing(tenant_profile: dict[str, Any] | None, now: int | None = None) -> None:
    """Raise BillingStatusError if the tenant is not allowed to take new payments."""
    if not is_billing_in_good_standing(tenant_profile, now):
        raise BillingStatusError(str((tenant_profile or {}).get("billing_status") or "trial"))
