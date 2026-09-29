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

# NOTHING here is the pricing. Allowances are DATA -- `ai_generations` on the plan row in PlatformPlansTable,
# and `ai_trial_generations` / `ai_free_generations` on its CONFIG row -- so they can be edited from the Admin
# Site without a deploy, the same way `entitlements` and `fee_tier` already are (docs/PLATFORM_PLANS.md).
# Hardcoding them in Python would repeat the fee-table mistake exactly: code saying one thing while the
# deployed table says another, and the table winning.
#
# The numbers below are FALLBACKS for when the data cannot be read -- a subscriber whose webhook has not run
# yet, a config row that predates this field. They are not policy and must never be cited as the pricing.
#
# For the record, the ladder agreed with the author 2026-09-29: $19 -> 20, $39 -> 50, $69 -> 100, trial -> 3.
# It replaced a flat 50, which at ~$0.105/generation gives away 27%+ of a $19 subscription at the model layer
# alone. Prod holds exactly one paid plan today (`PLAN#premium`, $19), so the upper rungs are numbers waiting
# for plan rows, not code waiting to be written.
DEFAULT_PLAN_ALLOWANCE = 20      # lowest paid rung: a paying tenant is never left with nothing
DEFAULT_TRIAL_ALLOWANCE = 3
DEFAULT_FREE_ALLOWANCE = 0

# The trial's counter is a LIFETIME one, so it does not live in a calendar period. `period_key` is the month,
# and a trial starting 25 September spans two of them -- handing out the allowance twice.
TRIAL_PERIOD = "trial"

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


def is_live_trial(tenant: dict[str, Any] | None, now: int | None = None) -> bool:
    """An unsubscribed platform trial that has not run out. Mirrors `entitlements.tenant_capabilities`."""
    from stripe_link.domain.billing_status import is_trial_expired

    profile = tenant or {}
    # An EMPTY profile is not a trial. `_profile()` returns {} when the read fails, and defaulting an absent
    # billing_status to "trial" (which is right elsewhere) would turn an unreadable tenant into three free
    # platform-paid generations -- an open tap on exactly the path that must fail closed.
    if not profile:
        return False
    if profile.get("stripe_subscription_id"):
        return False
    if str(profile.get("billing_status") or "trial") != "trial":
        return False
    return not is_trial_expired(profile, now)


def entitlement_for(tenant: dict[str, Any] | None, *, provider: str = "", now: int | None = None,
                    trial_allowance: int | None = None,
                    free_allowance: int | None = None) -> dict[str, Any]:
    """What this tenant may spend, and which counter it comes out of.

    Returns `{"allowance", "period", "source"}`. Pure: the numbers arrive as arguments or off the tenant, so
    this never reads a table. The PERIOD is part of the answer rather than something the caller derives,
    because the trial's counter is a lifetime one and a caller reaching for `period_key()` out of habit would
    hand a trial tenant a fresh three every calendar month.

    A subscriber's allowance comes from `tenant.ai_generations`, denormalized off the plan row by the billing
    webhook exactly as `entitlements` and `tier_id` are. It is deliberately NOT keyed on `tier_id`: that is
    the transaction-FEE tier, which every paid plan shares, so a 20/50/100 ladder keyed there would collapse
    to one number the moment a second paid plan existed.
    """
    profile = tenant or {}
    monthly = period_key(now)
    if profile.get("billing_exempt"):
        return {"allowance": UNLIMITED, "period": monthly, "source": "exempt"}

    key = str(provider or "").strip().lower()
    if not key:
        # NOTHING configured is not the same as "not Bedrock". Reading the absence as BYOK handed every
        # tenant who had never opened the screen a 200-generation ceiling.
        return {"allowance": 0, "period": monthly, "source": "unconfigured"}
    if key != "bedrock":
        return {"allowance": BYOK_CEILING, "period": monthly, "source": "byok"}

    if is_live_trial(profile, now):
        allowance = DEFAULT_TRIAL_ALLOWANCE if trial_allowance is None else int(trial_allowance)
        return {"allowance": allowance, "period": TRIAL_PERIOD, "source": "trial"}
    if profile.get("stripe_subscription_id"):
        # Off the tenant, put there by the webhook from the plan row. Absent means the webhook has not run
        # for this subscriber yet -- they are PAYING, so they get the lowest rung rather than nothing.
        return {"allowance": _int_or(profile.get("ai_generations"), DEFAULT_PLAN_ALLOWANCE),
                "period": monthly, "source": "plan"}
    # Free tier, or a trial that has run out. No platform-paid generations; their own key still works.
    allowance = DEFAULT_FREE_ALLOWANCE if free_allowance is None else int(free_allowance)
    return {"allowance": allowance, "period": monthly, "source": "free"}


def _int_or(value: Any, fallback: int) -> int:
    """DynamoDB hands numbers back as Decimal, so coerce numerically rather than by isinstance."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def remaining(used: int, allowance: int) -> int:
    if allowance == UNLIMITED:
        return UNLIMITED
    return max(0, int(allowance) - int(used or 0))


def may_generate(used: int, allowance: int, source: str = "") -> tuple[bool, str]:
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
        if source == "trial":
            # No reset date to offer, because there isn't one -- the trial allowance is a lifetime count.
            return False, (f"You have used all {int(allowance)} AI generations included with your trial. "
                           f"Upgrade to keep using AI Builder, or connect your own AI provider key.")
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
