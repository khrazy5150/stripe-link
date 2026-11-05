"""How many social accounts a tenant may connect (plans/ATTENTION_PRIMITIVE.md §6.2c).

**This is a COST lever before it is a product one, and the arithmetic is unusually direct.** The
publishing vendor bills a flat $19/mo up to 100 connected accounts and $129/mo at 101 — a hard step, not
an overage. So the accounts each tenant connects decides when that step lands:

| Accounts/tenant | Tenants inside the $19 tier | Peak publishing cost at the crossing |
|---|---|---|
| 1 | 100 | 1.85% of revenue |
| 2 | 50 | 3.67% |
| 3 | 33 | 5.50% |
| 4 | 25 | 7.19% |

Granting four brings the cliff forward four times sooner and makes it four times worse on arrival. None
of it threatens the business at the ~$69 tier — the worst case is 7.2% and it improves immediately — but
the difference between 1 and 4 is the difference between a rounding error and a line somebody explains.

**The default is 3 because the product supports 3 channels** (`../attention` `domain/channels.py`:
instagram, tiktok, youtube_shorts). One account per channel is the smallest number that lets a campaign
do what it says on the box; anything less sells multi-channel publishing and then rations it. That puts
the vendor cliff at ~33 tenants, which is a deliberate choice and not an accident of arithmetic.

NOTHING here is the pricing. The number is a `connected_accounts` entry in the plan row's generic
`limits` map, editable from the Admin Site's Pricing screen with no deploy, denormalized onto the tenant
by the billing webhook — the same road `sites` and `ai_generations` travel. This module only resolves it.
"""
from typing import Any

UNLIMITED = -1

# The free floor is ZERO, and that is not the same decision as the Site cap's floor of one. A Site is the
# tenant's own storefront and free-forever means a working one; a connected social account spends OUR
# vendor allowance on every post. `attention` is a beta/premium capability that the free tier does not
# include at all (`../attention` `entitlement.py` :: FREE_TIER), so a free tenant connecting accounts
# would be spending against a plan they are not on.
DEFAULT_FREE_CONNECTED_ACCOUNTS = 0

# One per supported channel. See the module docstring for why this number and not a larger one.
DEFAULT_PLAN_CONNECTED_ACCOUNTS = 3

_LAPSED_STATUSES = frozenset({"canceled", "cancelled", "incomplete_expired", "unpaid", ""})


def _int_or(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def account_allowance(tenant: dict[str, Any] | None,
                      *, free_allowance: int | None = None) -> dict[str, Any]:
    """How many accounts this tenant may have connected, and where the number came from.

    Returns `{"allowance", "source"}`. Pure: the numbers arrive as arguments or off the tenant, the same
    contract `site_quota.site_allowance` and `ai_quota.entitlement_for` keep.

    NOT per mode, unlike the Site cap. A connected Instagram account is one account at the vendor whether
    a test-mode campaign or a live one posts to it — the vendor has no idea our modes exist, and counting
    per mode would let one tenant hold twice the accounts we are billed for.
    """
    profile = tenant or {}
    if profile.get("billing_exempt"):
        return {"allowance": UNLIMITED, "source": "exempt"}
    free = DEFAULT_FREE_CONNECTED_ACCOUNTS if free_allowance is None else int(free_allowance)
    status = str(profile.get("billing_status") or "").strip().lower()
    if status in _LAPSED_STATUSES:
        return {"allowance": free, "source": "free"}
    return {"allowance": _int_or(profile.get("connected_accounts"), DEFAULT_PLAN_CONNECTED_ACCOUNTS),
            "source": "plan"}


def may_connect(tenant: dict[str, Any] | None, connected: int,
                *, free_allowance: int | None = None) -> dict[str, Any]:
    """May this tenant connect ONE more? `{"allowed", "allowance", "connected", "remaining"}`.

    Asked BEFORE the vendor OAuth round trip, never after. A tenant who authorises Instagram and is then
    told they are over their plan has given a third party access for nothing, and the account may already
    be consuming our vendor allowance by the time we refuse it.
    """
    resolved = account_allowance(tenant, free_allowance=free_allowance)
    allowance, have = resolved["allowance"], max(int(connected or 0), 0)
    if allowance == UNLIMITED:
        return {"allowed": True, "allowance": None, "connected": have, "remaining": None,
                "source": resolved["source"]}
    room = max(int(allowance) - have, 0)
    return {"allowed": room > 0, "allowance": max(int(allowance), 0), "connected": have,
            "remaining": room, "source": resolved["source"]}


def over_cap_message(allowance: int) -> str:
    """One sentence, naming the number and the way out. A cap a tenant meets only as a refusal reads as a
    bug; one they can see beforehand is a boundary (the Site-cap lesson, 2026-11-05)."""
    if allowance <= 0:
        return "Your plan does not include connected social accounts. Upgrade to add one."
    noun = "account" if allowance == 1 else "accounts"
    return (f"Your plan includes {allowance} connected social {noun}. "
            f"Disconnect one you are not using, or upgrade to add more.")
