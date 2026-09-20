"""Booking credits: what a recurring service subscription grants, and what spending one looks like.

NOT to be confused with domain/entitlements.py, which is about PLAN capabilities (what a tenant's
subscription to US unlocks). This is what a tenant's customer bought from THEM.

plans/RECURRING_SERVICES.md §4b. A recurring service is NOT a standing appointment -- the customer buys
ENTITLEMENT ("four cuts a month") and books each visit when it suits them, through the booking flow that
already exists. The thing that makes that work is a credit balance the subscription refills each cycle.

Deliberately not a ledger. It records how many bookings this cycle granted and how many are left, and each
paid cycle RESETS the balance rather than adding to it. Rollover turns a balance into an account with a
history, and the plan lists it as explicitly out of scope: "expire is simpler and is what most such plans
do". A tenant who wants rollover is describing a different product.
"""
from __future__ import annotations

import time
from typing import Any

# A subscription that grants no bookings is a product subscription wearing a service's name, so one is the
# floor. The ceiling stops a typo ("100" for "10") quietly promising a year of daily visits.
MIN_BOOKINGS_PER_CYCLE = 1
MAX_BOOKINGS_PER_CYCLE = 60
DEFAULT_BOOKINGS_PER_CYCLE = 1

ENTITLEMENT_STATUSES = {"active", "canceled", "past_due"}


class EntitlementError(ValueError):
    """The grant or the spend is not allowed. The message is shown to whoever attempted it."""


def bookings_per_cycle(service: dict[str, Any]) -> int:
    """How many visits one paid cycle of this service grants."""
    raw = (service or {}).get("bookings_per_cycle")
    if raw is None:
        return DEFAULT_BOOKINGS_PER_CYCLE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise EntitlementError("bookings_per_cycle must be a whole number.") from None
    if not MIN_BOOKINGS_PER_CYCLE <= value <= MAX_BOOKINGS_PER_CYCLE:
        raise EntitlementError(
            f"bookings_per_cycle must be between {MIN_BOOKINGS_PER_CYCLE} and {MAX_BOOKINGS_PER_CYCLE}.")
    return value


def entitlement_id_for(subscription_id: str, service_id: str) -> str:
    """Derived, not random: the webhook that grants a cycle and the one that refills it must address the
    SAME row, and they arrive as separate Stripe events with nothing but these two ids in common."""
    return f"ent_{subscription_id}_{service_id}"


def build_entitlement(*, tenant_id: str, service: dict[str, Any], subscription_id: str,
                      customer: dict[str, Any] | None = None, cycle_start: int | None = None,
                      cycle_end: int | None = None, now: int | None = None) -> dict[str, Any]:
    """A fresh grant, from a subscription's first paid cycle."""
    service_id = str((service or {}).get("service_id") or "")
    if not service_id:
        raise EntitlementError("An entitlement needs the service it grants.")
    if not subscription_id:
        raise EntitlementError("An entitlement needs the subscription that pays for it.")
    granted = bookings_per_cycle(service)
    moment = int(now if now is not None else time.time())
    return {
        "schema_version": "1",
        "document_type": "service_entitlement",
        "entitlement_id": entitlement_id_for(subscription_id, service_id),
        "tenant_id": tenant_id,
        "service_id": service_id,
        "service_name": str(service.get("name") or "Service"),
        "subscription_id": subscription_id,
        "customer": customer or {},
        "bookings_per_cycle": granted,
        "credits_remaining": granted,
        "cycle_start": int(cycle_start or moment),
        "cycle_end": int(cycle_end or 0),
        "status": "active",
        "created_at": moment,
        "updated_at": moment,
    }


def refill(entitlement: dict[str, Any], *, service: dict[str, Any] | None = None,
           cycle_start: int | None = None, cycle_end: int | None = None,
           now: int | None = None) -> dict[str, Any]:
    """A new paid cycle. The balance RESETS -- unused visits do not roll over (see the module docstring).

    Re-reads the grant size from the service when one is given, so a tenant who changes "four cuts" to
    "six cuts" sees it take effect on the next cycle rather than never.
    """
    moment = int(now if now is not None else time.time())
    granted = bookings_per_cycle(service) if service else int(entitlement.get("bookings_per_cycle") or 0)
    return {
        **entitlement,
        "bookings_per_cycle": granted,
        "credits_remaining": granted,
        "cycle_start": int(cycle_start or moment),
        "cycle_end": int(cycle_end or 0),
        "status": "active",
        "updated_at": moment,
    }


def spend(entitlement: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
    """Take one credit for a booking. Raises rather than going negative."""
    if str(entitlement.get("status") or "") != "active":
        raise EntitlementError("This plan is not active.")
    remaining = int(entitlement.get("credits_remaining") or 0)
    if remaining < 1:
        raise EntitlementError(
            "You have used all the bookings in your plan for this period. "
            "Your next booking becomes available when your plan renews.")
    return {
        **entitlement,
        "credits_remaining": remaining - 1,
        "updated_at": int(now if now is not None else time.time()),
    }


def restore(entitlement: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
    """Give a credit back when a booking is CANCELLED, capped at the cycle's grant.

    Without this, cancelling a visit costs the customer a visit -- which reads as a penalty for doing the
    considerate thing. Capped, because a cancellation must never leave someone with more than they bought.
    """
    granted = int(entitlement.get("bookings_per_cycle") or 0)
    remaining = min(granted, int(entitlement.get("credits_remaining") or 0) + 1)
    return {
        **entitlement,
        "credits_remaining": remaining,
        "updated_at": int(now if now is not None else time.time()),
    }
