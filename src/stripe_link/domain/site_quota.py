"""How many Sites a tenant may run (plans/SITE_AS_BUSINESS_IDENTITY.md §P5).

§3b's whole point: "Site becomes the unit of a business, and the number of Sites becomes the tier axis".
P1-P4 made identity per-Site; this is what charges for it.

TWO GATES, AND THEY ARE NOT THE SAME QUESTION. `entitlements.sites` is a boolean -- *may* this tenant use
Sites at all -- and stays TRUE on the free floor, because the free tier is free-forever and still gets one
Site. The number lives here. Conflating them turns a downgrade into "Sites removed" rather than "Sites
capped", which would take a paying customer's storefront off the internet for lapsing.

NOTHING here is the pricing. The numbers are DATA: a `sites` entry in the plan row's `limits` map, editable
from the Admin Site's Pricing screen with no deploy, denormalized onto the tenant by the billing webhook
exactly as `ai_generations` is. The constants below are the fallback for a row that predates the field.

SOFT-LOCK, NEVER DELETE. A tenant over the cap keeps every Site and every published page keeps serving --
the pricing pivot's rule is that a lapsed subscription sells on at the free-tier fee, so taking a store
down is not a lever we have. What a locked Site loses is EDITING and PUBLISHING: the work stops, the shop
stays open.
"""
from typing import Any

UNLIMITED = -1

# The free floor is ONE, not zero: free-forever means a working store, not a disabled one.
DEFAULT_FREE_SITES = 1
# The lowest PAID rung, for a subscriber whose plan row predates the field. It fails in the tenant's
# favour deliberately -- they bought something, so a missing number must not read as "none".
DEFAULT_PLAN_SITES = 3

# A subscription in one of these states is not paying for anything, so the free floor applies. Read
# EXPLICITLY rather than inferred from a missing `stripe_subscription_id`: the id is left behind on the
# profile after a cancellation, so "has an id" would keep reading a stale allowance forever.
_LAPSED_STATUSES = frozenset({"canceled", "cancelled", "incomplete_expired", "unpaid", ""})


def _int_or(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def site_allowance(tenant: dict[str, Any] | None, *, free_allowance: int | None = None) -> dict[str, Any]:
    """How many Sites this tenant may run IN ONE MODE, and where the number came from.

    Returns `{"allowance", "source"}`. Pure: the numbers arrive as arguments or off the tenant, so this
    never reads a table -- the same contract `ai_quota.entitlement_for` keeps, and for the same reason.

    PER MODE. "Your plan includes N sites" means N in test and N in live; the two sets of books are not a
    quota to divide. Counting across both would make a tenant's sandbox eat the storefronts they pay for.
    """
    profile = tenant or {}
    if profile.get("billing_exempt"):
        return {"allowance": UNLIMITED, "source": "exempt"}
    free = DEFAULT_FREE_SITES if free_allowance is None else int(free_allowance)
    status = str(profile.get("billing_status") or "").strip().lower()
    if status in _LAPSED_STATUSES:
        return {"allowance": free, "source": "free"}
    # Off the tenant, put there by the billing webhook from the plan row -- so this path never touches the
    # plans table. Absent means the webhook has not run for this subscriber yet; they are PAYING, so they
    # get the lowest paid rung rather than the free floor.
    return {"allowance": _int_or(profile.get("sites"), DEFAULT_PLAN_SITES), "source": "plan"}


def countable_sites(sites: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The Sites that count against the cap, oldest first.

    ARCHIVED SITES DO NOT COUNT. That is also the tenant's lever for "which ones stay active": archiving is
    already a reversible close that keeps every address and username reserved, so a tenant over the cap
    chooses by archiving the ones they are not using rather than by a separate picker that would mean the
    same thing. Nothing is deleted and nothing is given up.

    Ordered by `created_at`, then `site_id` to break a tie, so which Sites are inside the cap is STABLE --
    the answer cannot depend on what order DynamoDB happened to return rows in, or a tenant would see a
    different Site locked on each page load.
    """
    rows = [s for s in (sites or [])
            if isinstance(s, dict) and s.get("site_id") and str(s.get("status") or "") != "archived"]
    return sorted(rows, key=lambda s: (_int_or(s.get("created_at"), 0), str(s.get("site_id") or "")))


def locked_site_ids(sites: list[dict[str, Any]] | None, allowance: int) -> set[str]:
    """The site_ids over the cap: everything after the first `allowance` countable Sites.

    The OLDEST stay active. A tenant who downgrades keeps the business they have been running longest
    rather than whichever one a sort happened to surface, and the newest -- most likely the experiment --
    is what locks.
    """
    if allowance == UNLIMITED:
        return set()
    keep = max(int(allowance), 0)
    return {str(s.get("site_id")) for s in countable_sites(sites)[keep:]}


def site_is_locked(site: dict[str, Any] | None, sites: list[dict[str, Any]] | None, allowance: int) -> bool:
    """Is THIS Site over the cap? False for anything unidentifiable, which is the fail-open direction."""
    site_id = str((site or {}).get("site_id") or "")
    if not site_id:
        return False
    return site_id in locked_site_ids(sites, allowance)


def over_cap_message(allowance: int) -> str:
    """One sentence, naming the number and the way out. A cap a tenant cannot see is one they experience
    as a broken button -- the whole lesson of the Save Site gate (2026-11-05)."""
    if allowance <= 0:
        return "Your plan does not include any Sites. Upgrade to add one."
    noun = "Site" if allowance == 1 else "Sites"
    return (f"Your plan includes {allowance} {noun} per mode. "
            f"Archive one you are not using, or upgrade to add more.")
