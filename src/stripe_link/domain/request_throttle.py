"""A small counter for public endpoints that do expensive or outbound things.

Built for `/purchase/manage` (plans/PURCHASE_SELF_SERVICE.md §9.1), which is unauthenticated and, per
request, both reads a tenant's whole order list and can send mail. The tenant id sits in a public footer
URL, so the only thing between a stranger and that amplification is this.

Deliberately NOT a precise limiter. It is a read-modify-write on one row per window, so concurrent requests
can undercount and a few extra get through. A gate that is approximately right and costs one get+put beats
an exact one that needs infrastructure nobody is going to operate.

Pure functions: the caller owns the repository.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Per (tenant, contact): one lookup per window. Covers both halves of the exposure — the same address cannot
# be mailed repeatedly, and the same contact cannot make us re-read the order list.
CONTACT_WINDOW_SECONDS = 15 * 60
CONTACT_LIMIT = 1

# Per tenant: a cap on DIFFERENT contacts, which the per-contact gate cannot see. Someone enumerating
# addresses against one tenant is the case this exists for.
TENANT_WINDOW_SECONDS = 60 * 60
TENANT_LIMIT = 20


def throttle_id(scope: str, *parts: str) -> str:
    """A stable id for one counter.

    Hashed because the parts include a contact: this id becomes a primary key, and a key is the one place
    that ends up in logs, metrics and index scans without anyone deciding it should.
    """
    digest = hashlib.sha256("|".join([scope, *(str(part) for part in parts)]).encode("utf-8")).hexdigest()
    return f"{scope}_{digest[:40]}"


def window_start(now: int, window_seconds: int) -> int:
    return int(now) - (int(now) % int(window_seconds))


def throttle_doc(
    tenant_id: str,
    identifier: str,
    *,
    now: int,
    window_seconds: int,
    count: int = 1,
) -> dict[str, Any]:
    start = window_start(now, window_seconds)
    return {
        "schema_version": "2026-09-15",
        "document_type": "purchase_throttle",
        "tenant_id": tenant_id,
        "throttle_id": identifier,
        "window_start": start,
        "count": int(count),
        # Two windows of slack so a row written at the very end of one is still around to be read at the
        # start of the next; DynamoDB deletes on TTL are not immediate anyway.
        "expires_at": start + (2 * int(window_seconds)),
    }


def is_over_limit(record: dict[str, Any] | None, *, now: int, window_seconds: int, limit: int) -> bool:
    """Whether this counter has already spent its allowance for the CURRENT window."""
    if not record:
        return False
    if int(record.get("window_start") or 0) != window_start(now, window_seconds):
        return False  # a stale row from an earlier window counts for nothing
    return int(record.get("count") or 0) >= int(limit)


def next_count(record: dict[str, Any] | None, *, now: int, window_seconds: int) -> int:
    """The count to write after this request — restarting at 1 whenever the window has rolled."""
    if not record or int(record.get("window_start") or 0) != window_start(now, window_seconds):
        return 1
    return int(record.get("count") or 0) + 1
