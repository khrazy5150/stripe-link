"""Per-tenant generation allowance (pure -- no I/O).

AI_AND_COMMERCE_ARCHITECTURE.md §A.1/§A.6. This exists in the FIRST commit rather than as later
hardening, for a reason the original plan did not have: §A.1 was revised 2026-09-27 to add a
platform-paid Bedrock path, which reverses who pays. Under BYO-key a runaway loop spends the tenant's
money and embarrasses us; under Bedrock it spends OURS, and Bedrock's account-level quotas mean one
tenant's burst can starve every other tenant's generation.

Two jobs, one counter, because they are the same count:
  - the COMMERCIAL allowance ("50 generations a month included"), which must be countable rather than
    implied-unlimited or one heavy tenant costs more than their subscription; and
  - the ABUSE cap, which is the same number viewed as a ceiling.

No usage metering existed anywhere in this repo when this was written, so nothing here had a pattern
to follow.
"""

from __future__ import annotations

import time
from typing import Any

# Allowance per billing period, by plan key. Measured 2026-09-27: a full page generation on the
# default model runs ~$0.046 (§A.7), so 50/month is ~12% of a $19 subscription -- comfortable. 200
# would be 49%, which is where a flat bundle stops working. The free tier gets a real number rather
# than zero because BYO-key tenants pay their own inference; see `allowance_for`.
PLATFORM_PAID_ALLOWANCE = {
    "premium": 50,   # ~$0.94/month of inference against a $19 plan -- under 5%
    "pro": 50,
    # The free tier gets a REAL taste rather than nothing (revised 2026-09-27). It used to be zero on
    # the theory that free tenants would bring their own key; that theory died when BYO-key turned out
    # to require a separate vendor account funded with non-refundable, one-year-expiry prepaid credits
    # -- four steps before a free tenant sees a single page. Five generations costs us ~9 cents and is
    # enough to see the feature work, which is the whole job of an acquisition feature.
    "basic": 5,
}
# A tenant on their own key still gets a ceiling -- not to ration their spend, which is theirs, but
# because a generation loop hammering their provider looks like our outage and costs them real money.
BYOK_CEILING = 200

UNLIMITED = -1


def period_key(at: int | None = None) -> str:
    """The calendar month a generation counts against, as `YYYY-MM`.

    Calendar month, deliberately, not a rolling window or the tenant's billing anniversary: the number
    has to be one a tenant can check against their own calendar without us explaining it, and a rolling
    window cannot be read off a dashboard.
    """
    stamp = time.gmtime(int(at) if at is not None else time.time())
    return f"{stamp.tm_year:04d}-{stamp.tm_mon:02d}"


def allowance_for(*, plan_key: str = "", provider: str = "", exempt: bool = False) -> int:
    """How many generations this tenant may run this period. `UNLIMITED` (-1) means uncapped."""
    if exempt:
        return UNLIMITED
    provider = str(provider or "").strip().lower()
    if not provider:
        # NOTHING configured is not the same as "not Bedrock". Reading the absence as BYOK handed every
        # tenant who had never opened the screen a 200-generation ceiling.
        return 0
    if provider != "bedrock":
        return BYOK_CEILING  # their key, their bill -- a safety ceiling, not a ration
    return int(PLATFORM_PAID_ALLOWANCE.get(str(plan_key or "").strip().lower(), 0))


def remaining(used: int, allowance: int) -> int:
    if allowance == UNLIMITED:
        return UNLIMITED
    return max(0, int(allowance) - int(used or 0))


def may_generate(used: int, allowance: int) -> tuple[bool, str]:
    """May this tenant run one more? Returns (allowed, reason-if-not).

    The refusal text is the tenant's, not a log line: it says what ran out and what to do, because the
    alternative is a spinner that stops working with no explanation.
    """
    if allowance == UNLIMITED:
        return True, ""
    if int(allowance) <= 0:
        return False, ("AI generation is not included on your plan. Upgrade, or connect your own AI "
                       "provider key to use your own account.")
    if int(used or 0) >= int(allowance):
        return False, (f"You have used all {int(allowance)} AI generations included this month. They "
                       f"reset on the 1st, or you can connect your own AI provider key.")
    return True, ""


def usage_record(tenant_id: str, *, period: str = "", used: int = 0, at: int = 0) -> dict[str, Any]:
    """The counter document. One row per tenant per period, so a period rolls over by not existing."""
    return {
        "schema_version": "2026-09-27",
        "document_type": "ai_usage",
        "tenant_id": str(tenant_id or ""),
        "period": period or period_key(at or None),
        "used": int(used or 0),
        "updated_at": int(at or time.time()),
    }
