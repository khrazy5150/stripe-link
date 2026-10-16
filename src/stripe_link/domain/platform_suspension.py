"""Suspending a tenant for abuse (plans/ADMIN_SITE.md §1c).

Separate from `billing_status` on purpose, and the reason would never show up in testing: billing_status is
**webhook-driven**. `platform_subscription_sync` writes it from Stripe subscription events, so an abuse
suspension stored there would be overwritten with "active" by the next `customer.subscription.updated` —
silently, with nobody watching, and the first evidence would be the page coming back.

Billing and abuse are different questions about a tenant and get different fields.
"""
from __future__ import annotations

import time
from typing import Any

ACTIVE = "active"
SUSPENDED = "suspended"
PLATFORM_STATUSES = {ACTIVE, SUSPENDED}

# Why a platform suspends an account. Short on purpose: every entry is something a human has decided, and a
# longer list invites mis-filing the one case that ends up in front of a registrar or a card network.
SUSPENSION_REASONS = {
    "illegal_products": "Selling illegal or prohibited products",
    "fraud": "Fraud or deceptive practices",
    "prohibited_content": "Prohibited content",
    "impersonation": "Impersonating a person or business",
    "malware_or_phishing": "Malware or phishing",
    "abuse_of_platform": "Abusing the platform or its systems",
    "other": "Something else",
}


class SuspendedError(Exception):
    """A suspended tenant tried to do something a suspension stops. Carries the reason so a sign-in can say
    which one, rather than failing in a way that looks like a bug."""

    def __init__(self, reason: str = "", note: str = ""):
        self.reason = reason or "other"
        self.note = note
        super().__init__(SUSPENSION_REASONS.get(self.reason, SUSPENSION_REASONS["other"]))


def is_suspended(tenant_profile: dict[str, Any] | None) -> bool:
    """Whether this tenant is suspended by the platform.

    Note the asymmetry with `entitlement_gate.require_capability`, which fails OPEN on a lookup error and
    explains that a cross-cutting gate must never itself break a tenant action. That is right for a plan
    feature and wrong here: wrongly allowing means a live illegal page, wrongly refusing means a merchant
    who contacts support. **A profile this function cannot read is not a profile it will clear**, so the
    caller must pass what it read and treat a read failure as a refusal.
    """
    return str((tenant_profile or {}).get("platform_status") or ACTIVE) == SUSPENDED


def assert_not_suspended(tenant_profile: dict[str, Any] | None) -> None:
    """Raise `SuspendedError` if this tenant is suspended. Sits beside `assert_billing_in_good_standing` at
    every checkout, on the profile that call already has in hand."""
    if is_suspended(tenant_profile):
        profile = tenant_profile or {}
        raise SuspendedError(str(profile.get("suspended_reason") or ""),
                             str(profile.get("suspension_note") or ""))


def suspend(profile: dict[str, Any] | None, *, reason: str, by: str, note: str = "",
            now: int | None = None) -> dict[str, Any]:
    """The tenant profile, suspended. Returns a NEW document; the caller writes it.

    Nothing of the tenant's is deleted — documents, orders, products and media all stay. A suspension is a
    stop, not a purge, and the evidence has to survive for whoever asks next.
    """
    if not isinstance(profile, dict) or not profile.get("tenant_id"):
        raise ValueError("That tenant could not be found.")
    if reason not in SUSPENSION_REASONS:
        raise ValueError("Choose a reason for suspending this tenant.")
    if reason == "other" and not str(note or "").strip():
        raise ValueError("Describe why this tenant is being suspended.")
    if not str(by or "").strip():
        # An unattributed suspension is one nobody can answer for later.
        raise ValueError("A suspension must record who made it.")
    moment = int(now if now is not None else time.time())
    return {
        **profile,
        "platform_status": SUSPENDED,
        "suspended_reason": reason,
        "suspended_by": str(by).strip(),
        "suspended_at": moment,
        "suspension_note": str(note or "").strip()[:2000],
        "updated_at": moment,
    }


def restore(profile: dict[str, Any] | None, *, by: str, now: int | None = None) -> dict[str, Any]:
    """The tenant profile, un-suspended. The history of the suspension is KEPT — who did it, when and why
    — under `last_suspension`, because "has this account been suspended before" is a question the next
    report will ask."""
    if not isinstance(profile, dict) or not profile.get("tenant_id"):
        raise ValueError("That tenant could not be found.")
    if not is_suspended(profile):
        raise ValueError("That tenant is not suspended.")
    if not str(by or "").strip():
        raise ValueError("A restore must record who made it.")
    moment = int(now if now is not None else time.time())
    restored = {
        **profile,
        "platform_status": ACTIVE,
        "last_suspension": {
            "reason": profile.get("suspended_reason"),
            "by": profile.get("suspended_by"),
            "at": profile.get("suspended_at"),
            "note": profile.get("suspension_note"),
            "restored_by": str(by).strip(),
            "restored_at": moment,
        },
        "updated_at": moment,
    }
    for key in ("suspended_reason", "suspended_by", "suspended_at", "suspension_note"):
        restored.pop(key, None)
    return restored
