"""Per-recipient codes for a targeted coupon (plans/COUPONS_COMPLETION.md C5).

A targeted campaign is one Stripe Coupon and one promotion code PER RECIPIENT, each scoped to that
recipient's Stripe Customer. This module owns the part that is pure: what a recipient's code looks like,
and what their grant record holds. Stripe lives in `stripe_link.stripe_coupons`; the audience and the
export live in the handler.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

# The alphabet a person can read off a printed email and type without asking which character that is: no
# O/0, no I/1/L. A recipient who mistypes their own code cannot fall back to somebody else's, because the
# code is bound to them -- so a wrong character is a dead end, not a cheaper order.
_UNAMBIGUOUS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_SUFFIX_LENGTH = 6
_CODE_RE = re.compile(r"^[A-Z0-9_-]+$")

# Stripe's promotion-code ceiling. The prefix is trimmed rather than the suffix, because the suffix is what
# makes the code unguessable.
MAX_CODE_LENGTH = 200

SCHEMA_VERSION = "2026-09-22"


def grant_prefix(code: str) -> str:
    """The campaign half of a recipient's code, derived from the coupon's own code.

    ONE definition, because the renderer needs it too: a published page accepts a code from `?coupon=` only
    when it belongs to the campaign on that page, and it can only tell by the prefix.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "", str(code or "")).upper().strip("-_") or "SAVE"


def grant_code(prefix: str, *, suffix: str = "") -> str:
    """One recipient's code: the campaign's prefix, then random characters nobody can guess.

    The prefix is the tenant's -- it is what a recipient recognises in their inbox -- and the suffix is what
    keeps a code from being derived from anyone else's. Six characters of a 31-symbol alphabet is ~30 bits,
    which matters less than it looks: guessing one only reaches a code bound to a customer who is not you.
    """
    cleaned = grant_prefix(prefix)
    suffix = str(suffix or "") or "".join(secrets.choice(_UNAMBIGUOUS) for _ in range(_SUFFIX_LENGTH))
    head = cleaned[: MAX_CODE_LENGTH - len(suffix) - 1]
    return f"{head}-{suffix}"


def normalize_recipients(rows: Any) -> list[dict[str, str]]:
    """The audience, de-duplicated by email and stripped of the blanks a pasted list always carries.

    Two grants for one email would be two codes in one inbox, and the second is pure confusion: the
    recipient uses whichever they see first and the tenant's redemption view shows one unused code forever.
    """
    seen: set[str] = set()
    recipients: list[dict[str, str]] = []
    for row in rows or []:
        if isinstance(row, str):
            row = {"email": row}
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        recipients.append({"email": email, "name": str(row.get("name") or "").strip()})
    return recipients


def grant_document(
    *, tenant_id: str, coupon_id: str, code: str, email: str, name: str = "",
    stripe_promo_code_id: str, stripe_customer_id: str, stripe_mode: str,
    max_redemptions: int | None = None, expires_at: int | None = None, now: int,
) -> dict[str, Any]:
    """The stored grant. `grant_id` IS the code, so checkout resolves one by key instead of scanning."""
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "coupon_grant",
        "tenant_id": tenant_id,
        "grant_id": code,
        "code": code,
        "coupon_id": coupon_id,
        "email": email,
        "stripe_promo_code_id": stripe_promo_code_id,
        "stripe_customer_id": stripe_customer_id,
        "stripe_mode": stripe_mode,
        "status": "active",
        # Counted by the webhook when this recipient pays. Present from the start so the campaign view
        # never has to distinguish "nobody used it" from "we never wrote the field".
        "redemption_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    if name:
        document["name"] = name
    if max_redemptions:
        document["max_redemptions"] = int(max_redemptions)
    if expires_at:
        document["expires_at"] = int(expires_at)
    return document


def is_grant_code(code: str) -> bool:
    """Cheap shape check before a lookup. A code that cannot be a grant is not worth a read."""
    code = str(code or "").strip().upper()
    return bool(code) and bool(_CODE_RE.match(code))
